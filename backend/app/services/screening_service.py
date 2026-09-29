"""Screening orchestration: run the pipeline, persist everything, audit it.

This is the only place that knows the ORDER of a screening run. Routes call it;
it calls `src/pipeline.py` for the science and the repositories for storage.

Reproducibility is the organising constraint. Before any component is scored
the run row records the dataset hash, the model artifact and its checksum, the
pipeline/feature/policy versions and the effective configuration. A decision
that cannot be traced back to those is not usable in a hi-rel flow.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

from src.explain import MODEL_VERSION, Thresholds, reason_codes_for_part
from src.features import LOT_COL, PARAM_NAMES
from src.fusion import RiskWeights
from src.module_a import static_limit_flags
from src.pipeline import ScreenResult, screen

from backend.app.core.config import Settings, get_settings
from backend.app.core.exceptions import NotFoundError, ScreeningError
from backend.app.core.logging import get_logger, log_event, timed
from backend.app.ml.inference import (
    FEATURE_VERSION, PIPELINE_VERSION, get_active_forecaster,
)
from backend.app.repositories.repositories import (
    AuditRepository, ComponentRepository, JobRepository, ModelRepository,
    ScreeningRepository,
)
from backend.app.services.dataset_service import DatasetService
from backend.app.services.evidence_service import (
    module_a_evidence, module_b_evidence,
)
from backend.app.services.explanation_service import build_explanation

__all__ = ["ScreeningService"]

log = get_logger("screening")

SUB_SCORE_NAMES = ("static_margin", "dynamic_outlier", "predicted_drift",
                   "multivariate", "curvature")


def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(x) else round(x, 6)


class ScreeningService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.settings.ensure_dirs()
        db = self.settings.sqlite_path
        self.runs = ScreeningRepository(db)
        self.components = ComponentRepository(db)
        self.audit = AuditRepository(db)
        self.jobs = JobRepository(db)
        self.models = ModelRepository(db)
        self.datasets = DatasetService(self.settings)

    # ------------------------------------------------------------ create
    def create_run(self, dataset_id: str, *, actor: str | None = None) -> str:
        ds = self.datasets.get(dataset_id)
        loaded = get_active_forecaster(self.models, self.settings.artifact_dir)
        run_id = self.runs.create(
            dataset_id=dataset_id,
            dataset_sha256=ds["sha256"],
            pipeline_version=PIPELINE_VERSION,
            model_version=loaded.model_version if loaded else MODEL_VERSION,
            feature_version=FEATURE_VERSION,
            policy_version=self.settings.policy_version,
            config_hash=self.settings.policy_fingerprint(),
            config=self.settings.policy_dict(),
            actor=actor)
        self.audit.record("RUN_CREATED", run_id=run_id, dataset_id=dataset_id,
                          actor=actor,
                          metadata={"dataset_sha256": ds["sha256"],
                                    "policy_version": self.settings.policy_version,
                                    "config_hash": self.settings.policy_fingerprint()})
        return run_id

    # ------------------------------------------------------------ execute
    def execute(self, run_id: str, *, job_id: str | None = None) -> dict:
        """Run the screen and persist every component result.

        Failures are recorded on the run and the job, then re-raised: a run
        that failed must be visible as FAILED, never left RUNNING forever.
        """
        run = self.start(run_id, job_id=job_id)
        t0 = time.perf_counter()

        try:
            df = self.datasets.load_frame(run["dataset_id"])
            loaded = get_active_forecaster(self.models, self.settings.artifact_dir)

            # Out-of-fold is a fact about THIS pairing of model and data, so it
            # is established here by hash comparison rather than assumed.
            oof = (loaded.is_out_of_fold_for(
                       run["dataset_sha256"],
                       set(df["serial"].astype(str)) if "serial" in df.columns else None)
                   if loaded else False)

            with timed("SCREEN", log, run_id=run_id, rows=len(df),
                       model=loaded.artifact_id if loaded else "in-request"):
                res = screen(
                    df,
                    weights=RiskWeights(),
                    target_reject=self.settings.target_reject_rate,
                    forecaster=loaded.model if loaded else None,
                    forecaster_is_out_of_fold=oof)

            return self.persist_result(run, df, res, loaded, t0, job_id=job_id)

        except Exception as exc:
            self.fail(run, exc, job_id=job_id)
            raise

    def start(self, run_id: str, *, job_id: str | None = None) -> dict:
        """Mark a QUEUED/FAILED run RUNNING. Shared by execute() and the agents."""
        run = self.runs.get(run_id)
        if not run:
            raise NotFoundError(f"No screening run with id {run_id!r}.")
        if run["status"] not in ("QUEUED", "FAILED"):
            raise ScreeningError(
                f"Run {run_id} is {run['status']}; only a QUEUED or FAILED run "
                "can be executed.")
        self.runs.mark_running(run_id)
        if job_id:
            self.jobs.mark_running(job_id)
        return run

    def persist_result(self, run: dict, df: pd.DataFrame, res: ScreenResult,
                       loaded, t0: float, *, job_id: str | None = None) -> dict:
        """Persist a finished ScreenResult: components, run row, audit trail."""
        run_id = run["run_id"]
        rows = self._component_rows(df, res)
        self.components.bulk_insert(run_id, rows)

        summary = res.fused.verdict.value_counts().to_dict()
        duration = time.perf_counter() - t0
        self.runs.mark_completed(
            run_id, duration_s=round(duration, 3),
            bands={"watch": round(res.bands.watch, 3),
                   "reject": round(res.bands.reject, 3)},
            summary={k: int(v) for k, v in summary.items()},
            row_count=len(df),
            forecast_out_of_fold=res.forecast_out_of_fold,
            module_b_available=res.module_b is not None,
            model_artifact_id=loaded.artifact_id if loaded else None,
            model_sha256=loaded.artifact_sha256 if loaded else None)

        self.audit.record(
            "RUN_COMPLETED", run_id=run_id, dataset_id=run["dataset_id"],
            actor=run.get("actor"),
            metadata={"summary": {k: int(v) for k, v in summary.items()},
                      "duration_s": round(duration, 3),
                      "model_artifact_id": loaded.artifact_id if loaded else None,
                      "forecast_out_of_fold": res.forecast_out_of_fold})
        # One line per rejection, so "why was this part rejected" has an
        # audit answer and not only a database row.
        for r in rows:
            if r["verdict"] == "REJECT":
                self.audit.record(
                    "COMPONENT_REJECTED", run_id=run_id, serial=r["serial"],
                    actor=run.get("actor"),
                    metadata={"risk_score": r["risk_score"],
                              "lot": r["lot"],
                              "primary_reason":
                                  (r.get("explanation") or {})
                                  .get("primary_reason", {})
                                  .get("code")})

        if job_id:
            self.jobs.mark_completed(job_id, run_id)

        log_event("SCREENING_COMPLETED", log, run_id=run_id, rows=len(df),
                  accept=int(summary.get("ACCEPT", 0)),
                  watch=int(summary.get("WATCH", 0)),
                  reject=int(summary.get("REJECT", 0)),
                  duration_s=round(duration, 3),
                  model_version=run["model_version"])
        return self.get_run(run_id)

    def fail(self, run: dict, exc: BaseException, *, job_id: str | None = None) -> None:
        """Record FAILED on the run (and job). Never leaves a run RUNNING."""
        run_id = run["run_id"]
        self.runs.mark_failed(run_id, f"{type(exc).__name__}: {exc}")
        self.audit.record("RUN_FAILED", run_id=run_id,
                          dataset_id=run["dataset_id"],
                          metadata={"error_type": type(exc).__name__})
        if job_id:
            self.jobs.mark_failed(job_id, str(exc),
                                  getattr(exc, "code", "SCREENING_FAILED"))
        log_event("SCREENING_FAILED", log, run_id=run_id,
                  error_type=type(exc).__name__)

    # ------------------------------------------------- result construction
    def _component_rows(self, df: pd.DataFrame, res: ScreenResult) -> list[dict]:
        """Build one persistable row per component, explanation included.

        The explanation is generated HERE, from the same fused sub-scores that
        produced the verdict, and stored with the result. Persisting it means
        the record cannot drift from the decision afterwards - and it is what
        lets the report be rendered from the database.
        """
        flags = static_limit_flags(df)
        fused = res.fused
        thresholds = Thresholds()
        weights = RiskWeights()
        bands = {"watch": round(res.bands.watch, 3),
                 "reject": round(res.bands.reject, 3)}

        rows: list[dict] = []
        for i in df.index:
            frow = fused.loc[i]
            subs = {k: _f(frow[k]) for k in SUB_SCORE_NAMES if k in fused.columns}

            ev_a = module_a_evidence(df, res.features, i, static_flags=flags)
            ev_b = module_b_evidence(
                df, i, res.forecast_point, res.forecast_upper, res.module_b,
                quantile=self.settings.module_b_quantile,
                out_of_fold=res.forecast_out_of_fold,
                population_k=res.population_k)
            evidence = {**ev_a, "module_b": ev_b}

            verdict = str(frow["verdict"])
            codes = reason_codes_for_part(df, res.features, i, res.module_b,
                                          thresholds)
            verdict, escalated = self._apply_escalation(verdict, codes)

            explanation = build_explanation(
                df, res.features, i,
                sub_scores=subs,
                risk_score=float(frow["risk_score"]),
                verdict=verdict,
                evidence=evidence,
                module_b=res.module_b,
                weights=weights, thresholds=thresholds, bands=bands)
            if escalated:
                explanation["escalated"] = {
                    "from": str(frow["verdict"]),
                    "to": verdict,
                    "trigger": [c.code for c in codes if c.severity == "high"],
                    "reason": ("A high-severity finding forces at least WATCH. "
                               "The weighted score alone placed this component "
                               "lower, but the screen may add flags and never "
                               "remove them."),
                }

            point = ({p: _f(res.forecast_point.at[i, p]) for p in PARAM_NAMES
                      if p in res.forecast_point.columns}
                     if i in res.forecast_point.index else None)
            upper = ({p: _f(res.forecast_upper.at[i, p]) for p in PARAM_NAMES
                      if p in res.forecast_upper.columns}
                     if i in res.forecast_upper.index else None)

            rows.append({
                "serial": str(df.at[i, "serial"]),
                "lot": str(df.at[i, LOT_COL]),
                "wafer": str(df.at[i, "wafer"]) if "wafer" in df.columns else None,
                "risk_score": float(frow["risk_score"]),
                "verdict": verdict,
                "static_breach": bool(flags.at[i, "static_any"]),
                "module_a_score": _f(res.module_a.at[i, "l2_dpat_z"])
                if "l2_dpat_z" in res.module_a.columns else None,
                "module_a_pooled": _f(res.module_a.at[i, "l3_pooled"])
                if "l3_pooled" in res.module_a.columns else None,
                "module_b_score": _f(res.module_b.at[i, "worst_ratio"])
                if res.module_b is not None else None,
                "predicted_168h": point,
                "prediction_upper": upper,
                "sub_scores": subs,
                "evidence": evidence,
                "explanation": explanation,
                "reason_codes": explanation["reason_codes"],
            })
        return rows

    def _apply_escalation(self, verdict: str, codes) -> tuple[str, bool]:
        """Raise a verdict that contradicts a high-severity finding.

        Only ever upgrades: ACCEPT -> WATCH. A component already at WATCH or
        REJECT is untouched, and nothing is ever downgraded. Disabled by
        setting SENTINEL_ESCALATE_ON_HIGH_SEVERITY=0, which changes the policy
        fingerprint so a run made without it is identifiable.
        """
        if not self.settings.escalate_on_high_severity or verdict != "ACCEPT":
            return verdict, False
        if any(c.severity == "high" for c in codes):
            return "WATCH", True
        return verdict, False

    # -------------------------------------------------------------- reads
    def get_run(self, run_id: str) -> dict:
        run = self.runs.get(run_id)
        if not run:
            raise NotFoundError(f"No screening run with id {run_id!r}.")
        run["lot_summary"] = self._lot_summary(run_id)
        return run

    def _lot_summary(self, run_id: str) -> list[dict]:
        pda = self.settings.pda_limit
        out = []
        for row in self.components.lot_summary(run_id):
            parts = int(row["parts"]) or 1
            frac = int(row["reject"] or 0) / parts
            out.append({**{k: row[k] for k in
                           ("lot", "parts", "reject", "watch", "accept", "mean_risk")},
                        "reject_fraction": round(frac, 4),
                        "pda_limit": pda,
                        "status": "LOT REVIEW" if frac > pda else "OK"})
        return out

    def list_components(self, run_id: str, **kw) -> list[dict]:
        self.get_run(run_id)
        return self.components.list(run_id, **kw)

    def get_component(self, run_id: str, serial: str) -> dict:
        row = self.components.get(run_id, serial)
        if not row:
            raise NotFoundError(
                f"No component {serial!r} in screening run {run_id!r}.")
        return row

    def audit_trail(self, run_id: str, limit: int = 200) -> list[dict]:
        self.get_run(run_id)
        return self.audit.for_run(run_id, limit)

    # ---------------------------------------------------- reproducibility
    def reproducibility(self, run_id: str) -> dict:
        """Everything needed to reproduce this run, and how to do it.

        If any of these differ, the run is not comparable - which is the point
        of returning them together rather than scattered across endpoints.
        """
        run = self.get_run(run_id)
        ds = self.datasets.datasets.get(run["dataset_id"]) or {}
        artifact = (self.models.get(run["model_artifact_id"])
                    if run.get("model_artifact_id") else None)
        return {
            "run_id": run_id,
            "status": run["status"],
            "dataset": {
                "dataset_id": run["dataset_id"],
                "sha256": run["dataset_sha256"],
                "filename": ds.get("filename"),
                "row_count": ds.get("row_count"),
                "read_points": ds.get("read_points"),
            },
            "model": {
                "artifact_id": run.get("model_artifact_id"),
                "model_version": run["model_version"],
                "artifact_sha256": run.get("model_sha256"),
                "training_dataset_sha256": (artifact or {}).get("training_dataset_sha"),
                "random_seed": (artifact or {}).get("random_seed"),
                "hyperparameters": (artifact or {}).get("hyperparameters"),
                "fitted_in_request": run.get("model_artifact_id") is None,
            },
            "versions": {
                "pipeline_version": run["pipeline_version"],
                "feature_version": run["feature_version"],
                "policy_version": run["policy_version"],
            },
            "configuration": {
                "config_hash": run["config_hash"],
                "effective_policy": run["config"],
            },
            "outcome": {
                "bands": run["bands"],
                "summary": run["summary"],
                "row_count": run["row_count"],
                "forecast_out_of_fold": run["forecast_out_of_fold"],
                "module_b_available": run["module_b_available"],
            },
            "determinism_note": (
                "Given the same dataset SHA256, the same model artifact "
                "SHA256 and the same configuration hash, this run reproduces "
                "exactly. The forecaster is loaded from a checksum-verified "
                "artifact rather than refitted, and every seed is fixed."),
        }
