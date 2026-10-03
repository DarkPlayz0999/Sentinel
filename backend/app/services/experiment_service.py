"""Experiment campaigns behind /v1/experiments.

A thin wrapper over src.twin.experiments.run_experiment: the campaign runs in
a background job, progress is written as it goes, and the benchmark dataset
(one row per board, every run) lands as a CSV next to the database. The API
returns the summary; the CSV is the thing to re-score.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.explain import MODEL_VERSION
from src.twin import TWIN_VERSION
from src.twin.experiments import ExperimentSpec, run_experiment, _json_default

from backend.app.core.config import Settings, get_settings
from backend.app.core.exceptions import ConflictError, NotFoundError
from backend.app.core.logging import get_logger, log_event
from backend.app.repositories.repositories import AuditRepository, JobRepository, utc_now
from backend.app.repositories.simulation import ExperimentRepository

__all__ = ["ExperimentService"]

log = get_logger("experiments")


class ExperimentService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.settings.ensure_dirs()
        self.repo = ExperimentRepository(self.settings.sqlite_path)
        self.jobs = JobRepository(self.settings.sqlite_path)
        self.audit = AuditRepository(self.settings.sqlite_path)

    @property
    def outdir(self) -> Path:
        # Beside the database, so a test's temporary DB keeps its artefacts too.
        p = Path(self.settings.sqlite_path).parent / "experiments"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def create(self, req: dict, *, actor: str | None = None) -> dict:
        try:
            spec = ExperimentSpec(kind=req["kind"], runs=int(req["runs"]), seed=int(req["seed"]),
                                  boards=int(req["boards"]), fault_rate=float(req["fault_rate"]),
                                  train_lots=int(req.get("train_lots", 4)),
                                  scenarios=tuple(req.get("scenarios") or ()))
        except ValueError as exc:
            raise ConflictError(str(exc)) from exc
        eid = self.repo.create(kind=spec.kind, spec=spec.as_dict(), seed=spec.seed,
                               runs=spec.runs, model_version=MODEL_VERSION,
                               software_version=TWIN_VERSION, actor=actor)
        job_id = self.jobs.create("EXPERIMENT", actor=actor)
        self.repo.update(eid, job_id=job_id)
        self.audit.record("EXPERIMENT_CREATED", actor=actor,
                          metadata={"experiment_id": eid, "spec": spec.as_dict()})
        return self.get(eid)

    def execute(self, eid: str) -> dict:
        exp = self.get(eid)
        spec = ExperimentSpec(**{**exp["spec"],
                                 "esr_targets_ohm": tuple(exp["spec"]["esr_targets_ohm"]),
                                 "stress_temps_c": tuple(exp["spec"]["stress_temps_c"]),
                                 "scenarios": tuple(exp["spec"]["scenarios"])})
        self.repo.update(eid, status="RUNNING")
        if exp.get("job_id"):
            self.jobs.mark_running(exp["job_id"])

        def progress(done, total, cell):
            self.repo.update(eid, progress={"done": done, "total": total, "cell": cell})

        try:
            out = run_experiment(spec, progress)
        except Exception as exc:
            self.repo.update(eid, status="FAILED", completed_at=utc_now(),
                             error=f"{type(exc).__name__}: {exc}")
            if exp.get("job_id"):
                self.jobs.mark_failed(exp["job_id"], str(exc), "EXPERIMENT_FAILED")
            log_event("EXPERIMENT_FAILED", log, experiment_id=eid, error_type=type(exc).__name__)
            raise
        rows = out["rows"].copy()
        rows["components_ranked"] = rows["components_ranked"].apply(lambda v: ",".join(v or []))
        path = self.outdir / f"{eid}.csv"
        rows.to_csv(path, index=False)
        summary = json.loads(json.dumps(out["summary"], default=_json_default))
        self.repo.update(eid, status="COMPLETED", completed_at=utc_now(), summary=summary,
                         artifact_path=path.name)
        if exp.get("job_id"):
            self.jobs.mark_completed(exp["job_id"])
        self.audit.record("EXPERIMENT_COMPLETED", metadata={
            "experiment_id": eid, "runs": summary["runs"],
            "boards": summary["boards_scored"]})
        log_event("EXPERIMENT_COMPLETED", log, experiment_id=eid, runs=summary["runs"])
        return self.get(eid)

    def get(self, eid: str) -> dict:
        exp = self.repo.get(eid)
        if not exp:
            raise NotFoundError(f"No experiment {eid!r}.")
        return exp

    def list(self, limit: int = 50) -> list[dict]:
        return [{k: e[k] for k in ("experiment_id", "created_at", "completed_at", "status",
                                   "kind", "random_seed", "runs", "progress")}
                | {"headline": _headline(e.get("summary"))} for e in self.repo.list(limit)]


def _headline(summary: dict | None) -> dict | None:
    if not summary:
        return None
    o = summary.get("overall") or {}
    return {k: o.get(k) for k in ("recall", "precision", "f2", "pr_auc",
                                  "recall_observable_faults")} | {
        "boards": summary.get("boards_scored")}
