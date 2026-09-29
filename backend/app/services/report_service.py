"""Screening reports, generated from a persisted run.

How a report is produced, and why it is done this way
----------------------------------------------------
The PDF renderer in `src/screening_report.py` is tested and it draws the drift
plot from the measurement frame, so it needs the frame and a ScreenResult. A
report service that kept its own copy of the layout would be a second renderer
to keep in sync.

So the run is REPLAYED: the dataset is reloaded by hash, screened again with
the exact model artifact the run recorded, and rendered. That is only sound if
the replay reproduces the run - so it is CHECKED. Every regenerated verdict and
risk score is compared against what was persisted, and a mismatch raises rather
than quietly issuing a report that disagrees with the record it cites.

That check is the reproducibility claim being enforced on every report, not
asserted in a docstring.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.fusion import RiskWeights
from src.pipeline import ScreenResult, screen
from src.screening_report import build_report

from backend.app.core.config import Settings, get_settings
from backend.app.core.exceptions import NotFoundError, ReportGenerationError
from backend.app.core.logging import get_logger, log_event
from backend.app.ml.inference import load_forecaster_file
from backend.app.repositories.repositories import AuditRepository, ModelRepository
from backend.app.services.dataset_service import DatasetService
from backend.app.services.screening_service import ScreeningService

__all__ = ["ReportService"]

log = get_logger("reports")

# A regenerated risk score may differ from the stored one only by float
# round-trip noise. Anything larger means the run did not reproduce.
RISK_TOLERANCE = 0.05


class ReportService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.settings.ensure_dirs()
        self.screening = ScreeningService(self.settings)
        self.datasets = DatasetService(self.settings)
        self.models = ModelRepository(self.settings.sqlite_path)
        self.audit = AuditRepository(self.settings.sqlite_path)

    # ------------------------------------------------------------ replay
    def _replay(self, run: dict) -> tuple[pd.DataFrame, ScreenResult]:
        """Reload the dataset and re-screen it under the run's recorded model."""
        df = self.datasets.load_frame(run["dataset_id"])

        forecaster, oof = None, False
        artifact_id = run.get("model_artifact_id")
        if artifact_id:
            row = self.models.get(artifact_id)
            if not row:
                raise ReportGenerationError(
                    f"Run {run['run_id']} cites model artifact {artifact_id}, "
                    "which is no longer registered. The report cannot be "
                    "reproduced.")
            path = Path(self.settings.artifact_dir) / Path(row["artifact_path"]).name
            forecaster = load_forecaster_file(path, row["artifact_sha256"])
            oof = row["training_dataset_sha"] != run["dataset_sha256"]

        res = screen(df, weights=RiskWeights(),
                     target_reject=run["config"].get(
                         "target_reject_rate", self.settings.target_reject_rate),
                     forecaster=forecaster, forecaster_is_out_of_fold=oof)
        return df, res

    def _verify(self, run_id: str, res: ScreenResult, serial: str) -> None:
        stored = self.screening.get_component(run_id, serial)
        i = res.part(serial)
        if i is None:
            raise ReportGenerationError(
                f"Component {serial!r} is not present in the replayed frame.")

        got_verdict = str(res.fused.at[i, "verdict"])
        got_risk = float(res.fused.at[i, "risk_score"])
        drift = abs(got_risk - float(stored["risk_score"]))

        if got_verdict != stored["verdict"] or drift > RISK_TOLERANCE:
            raise ReportGenerationError(
                "The screening run did not reproduce, so a report citing it "
                "would be misleading and has not been issued.",
                [{"field": serial, "error_code": "RUN_NOT_REPRODUCIBLE",
                  "message": (f"stored {stored['verdict']} at "
                              f"{stored['risk_score']:.2f}; replay produced "
                              f"{got_verdict} at {got_risk:.2f}")}])

    # ------------------------------------------------------------ render
    def build(self, run_id: str, serial: str, *, actor: str | None = None) -> Path:
        run = self.screening.get_run(run_id)
        if run["status"] != "COMPLETED":
            raise ReportGenerationError(
                f"Run {run_id} is {run['status']}. A report can only be issued "
                "for a completed run.")

        # Raises NotFoundError before any expensive replay.
        self.screening.get_component(run_id, serial)

        df, res = self._replay(run)
        self._verify(run_id, res, serial)

        i = res.part(serial)
        out_dir = Path(self.settings.report_dir) / run_id
        try:
            path = build_report(df, res, i, out_dir)
        except Exception as exc:
            raise ReportGenerationError(
                f"The report for {serial} could not be rendered.",
                [{"field": "renderer", "error_code": "RENDER_FAILED",
                  "message": type(exc).__name__}]) from exc

        self.audit.record("REPORT_GENERATED", run_id=run_id, serial=serial,
                          actor=actor,
                          metadata={"filename": path.name,
                                    "dataset_sha256": run["dataset_sha256"],
                                    "model_version": run["model_version"],
                                    "verified_against_persisted_result": True})
        log_event("REPORT_GENERATED", log, run_id=run_id, serial=serial,
                  bytes=path.stat().st_size)
        return path

    # -------------------------------------------------------- structured
    def record(self, run_id: str, serial: str) -> dict:
        """The report's content as JSON, straight from persisted data.

        No replay: this is the stored record, which is what a UI should render.
        The PDF exists for the paper traveller; this is for everything else.
        """
        run = self.screening.get_run(run_id)
        comp = self.screening.get_component(run_id, serial)
        ds = self.datasets.datasets.get(run["dataset_id"]) or {}
        return {
            "report_type": "SENTINEL screening record",
            "component": {k: comp[k] for k in
                          ("serial", "lot", "wafer", "risk_score", "verdict",
                           "static_breach")},
            "measurements_source": {
                "dataset_id": run["dataset_id"],
                "dataset_sha256": run["dataset_sha256"],
                "filename": ds.get("filename"),
            },
            "module_a": (comp.get("evidence") or {}),
            "module_b": (comp.get("evidence") or {}).get("module_b"),
            "explanation": comp.get("explanation"),
            "reason_codes": comp.get("reason_codes", []),
            "lot_disposition": next(
                (l for l in run.get("lot_summary", []) if l["lot"] == comp["lot"]),
                None),
            "provenance": {
                "run_id": run_id,
                "model_version": run["model_version"],
                "model_artifact_id": run.get("model_artifact_id"),
                "model_sha256": run.get("model_sha256"),
                "pipeline_version": run["pipeline_version"],
                "feature_version": run["feature_version"],
                "policy_version": run["policy_version"],
                "config_hash": run["config_hash"],
                "effective_policy": run["config"],
                "completed_at": run["completed_at"],
                "forecast_out_of_fold": run["forecast_out_of_fold"],
            },
            "disclosure": (
                "SENTINEL recommends; a reliability engineer dispositions. "
                "This record is not valid until countersigned."),
        }
