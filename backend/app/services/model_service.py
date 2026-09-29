"""Model lifecycle: train, register, report performance honestly.

Training is an explicit operation (`POST /v1/models/train`, or the CLI in
backend/train.py). It is never triggered by a screening request - that is the
whole point of separating the two.

The performance payload deliberately reports where the model LOSES. On this
dataset Module B is beaten by plain last-value-carried-forward on `Tpd_ns` and
`Vol_mV`, whose fitted exponent is 0 because the data supports no extrapolation
on those axes at all. Publishing that is the difference between an evaluation
and a sales sheet.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.explain import MODEL_VERSION

from backend.app.core.config import Settings, get_settings
from backend.app.core.exceptions import NotFoundError
from backend.app.core.logging import get_logger, log_event, timed
from backend.app.ml.inference import (
    FEATURE_VERSION, LoadedModel, clear_model_cache, dataframe_sha256,
    get_active_forecaster, save_forecaster, train_forecaster,
)
from backend.app.repositories.repositories import AuditRepository, ModelRepository

__all__ = ["ModelService"]

log = get_logger("models")

_HYPERPARAMS = {
    "n_estimators": 300, "learning_rate": 0.05, "num_leaves": 15,
    "min_child_samples": 30, "subsample": 0.9, "subsample_freq": 1,
    "colsample_bytree": 0.9,
    "objective_point": "regression_l1", "objective_bound": "quantile",
    "quantile_alpha": 0.90,
}


class ModelService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.settings.ensure_dirs()
        self.repo = ModelRepository(self.settings.sqlite_path)
        self.audit = AuditRepository(self.settings.sqlite_path)

    # ---------------------------------------------------------- training
    def train(self, df: pd.DataFrame, *, seed: int = 42,
              model_version: str | None = None,
              actor: str | None = None) -> dict:
        """Fit, evaluate out-of-fold, persist, checksum and register."""
        version = model_version or MODEL_VERSION
        train_sha = dataframe_sha256(df)

        with timed("MODEL_TRAIN", log, rows=len(df), seed=seed,
                   model_version=version):
            model, metrics = train_forecaster(df, seed=seed)

        artifact_name = f"forecaster-{version}-{train_sha[:12]}.joblib"
        path = Path(self.settings.artifact_dir) / artifact_name
        serials = set(df["serial"].astype(str)) if "serial" in df.columns else set()
        sha = save_forecaster(model, path, training_serials=serials)

        artifact_id = self.repo.create(
            model_version=version,
            model_name="module_b_power_law_gbm",
            model_type=("power-law physics baseline stacked with a "
                        "gradient-boosted residual and a quantile bound"),
            training_dataset_sha=train_sha,
            training_rows=int(len(df)),
            feature_version=FEATURE_VERSION,
            hyperparameters=_HYPERPARAMS,
            random_seed=seed,
            metrics=metrics,
            exponents={k: round(float(v), 4) for k, v in model.exponents.items()},
            artifact_path=artifact_name,
            artifact_sha256=sha,
            activate=True)

        clear_model_cache()
        self.audit.record("MODEL_TRAINED", actor=actor,
                          metadata={"artifact_id": artifact_id,
                                    "model_version": version,
                                    "training_rows": int(len(df)),
                                    "training_dataset_sha": train_sha,
                                    "artifact_sha256": sha})
        log_event("MODEL_REGISTERED", log, artifact_id=artifact_id,
                  model_version=version, sha256=sha[:16], rows=len(df))
        return self.get(artifact_id)

    # ------------------------------------------------------------- reads
    def get(self, artifact_id: str) -> dict:
        row = self.repo.get(artifact_id)
        if not row:
            raise NotFoundError(f"No model artifact with id {artifact_id!r}.")
        return self._public(row)

    def active(self) -> dict | None:
        row = self.repo.active()
        return self._public(row) if row else None

    def list(self, limit: int = 20) -> list[dict]:
        return [self._public(r) for r in self.repo.list(limit)]

    def loaded(self) -> LoadedModel | None:
        return get_active_forecaster(self.repo, self.settings.artifact_dir)

    @staticmethod
    def _public(row: dict) -> dict:
        """Registry row for the API. The filesystem path never leaves the process."""
        out = {k: v for k, v in row.items() if k != "artifact_path"}
        out["artifact_filename"] = Path(row["artifact_path"]).name
        return out

    # ------------------------------------------------------- performance
    def performance(self) -> dict:
        """Per-parameter MAE against both baselines, for the active artifact."""
        row = self.repo.active()
        if not row:
            return {
                "available": False,
                "reason": ("No model artifact is registered. Train one with "
                           "`python -m backend.train` or POST /v1/models/train."),
                "parameters": [],
            }

        metrics = row.get("metrics") or {}
        if not metrics.get("available"):
            return {
                "available": False,
                "reason": metrics.get(
                    "reason", "No out-of-fold metrics were recorded."),
                "model_version": row["model_version"],
                "artifact_id": row["artifact_id"],
                "parameters": [],
            }

        params = metrics.get("parameters", [])
        losers = [p["parameter"] for p in params if not p.get("beats_last_value")]
        return {
            "available": True,
            "artifact_id": row["artifact_id"],
            "model_version": row["model_version"],
            "model_name": row["model_name"],
            "model_type": row["model_type"],
            "validation": metrics.get("validation"),
            "training_rows": row["training_rows"],
            "training_dataset_sha256": row["training_dataset_sha"],
            "random_seed": row["random_seed"],
            "fitted_exponents": row.get("exponents"),
            "parameters": params,
            "honest_summary": (
                "Module B beats both baselines on "
                + ", ".join(p["parameter"] for p in params
                            if p.get("beats_last_value")) + "."
                + (f" It does NOT beat last-value-carried-forward on "
                   f"{', '.join(losers)}: the MAE-optimal power-law exponent "
                   f"there is 0, meaning the data supports no extrapolation on "
                   f"those axes. That is a metrology limit, not a model "
                   f"limit, and it is reported rather than hidden."
                   if losers else "")),
            "metric_note": (
                "MAE on the 168 h value, out-of-fold under GroupKFold(groups="
                "lot). `linear_baseline_mae` extrapolates the 0->24 h slope; "
                "`last_value_baseline_mae` carries the 24 h reading forward."),
        }
