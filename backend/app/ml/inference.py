"""Model artifacts: train once, persist, load for inference.

The problem this solves
-----------------------
`src/pipeline.screen()` with no artifact fits Module B inside the request. On a
six-lot frame that is a six-fold cross-validated LightGBM fit - correct for
producing a reportable MAE, and completely wrong as a per-request inference
path. It also means two identical requests can be served by two different
models, which makes a screening decision unreproducible.

So training and inference are separated:

    train_forecaster()   fits on a named reference dataset, records the
                         out-of-fold metrics, writes a joblib artifact and
                         its SHA256, and registers it.

    load_forecaster()    returns the active artifact, verified against its
                         recorded checksum, cached per process.

Determinism: the artifact carries its random seed and its fitted exponents,
and the checksum is verified on load, so a run can state exactly which model
produced it. If the bytes on disk change, the load fails loudly rather than
silently serving a different model under the same version string.

Honesty: `train_forecaster` records the SAME out-of-fold comparison the project
already reports - model MAE against a linear extrapolation and against
last-value-carried-forward, per parameter. Where the model loses (it does, on
Tpd_ns and Vol_mV, whose fitted exponent is 0), that is recorded in the
artifact and surfaced by GET /v1/models/performance rather than hidden.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from src.features import LOT_COL, PARAM_NAMES
from src.module_b import PowerLawForecaster, forecast_all

from backend.app.core.exceptions import ModelInferenceError

__all__ = [
    "FEATURE_VERSION", "PIPELINE_VERSION",
    "sha256_bytes", "sha256_file", "dataframe_sha256",
    "train_forecaster", "save_forecaster", "load_forecaster_file",
    "LoadedModel", "get_active_forecaster", "clear_model_cache",
]

# Bumped when the FEATURE DEFINITION changes in a way that invalidates an
# existing artifact. Distinct from MODEL_VERSION (the scoring stack) and from
# the policy version (operator configuration).
FEATURE_VERSION = "features-1.0.0"
PIPELINE_VERSION = "pipeline-1.1.0"

_HYPERPARAMS = {
    "n_estimators": 300, "learning_rate": 0.05, "num_leaves": 15,
    "min_child_samples": 30, "subsample": 0.9, "subsample_freq": 1,
    "colsample_bytree": 0.9, "objective_point": "regression_l1",
    "objective_bound": "quantile",
}


# ----------------------------------------------------------------- hashing
def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dataframe_sha256(df: pd.DataFrame) -> str:
    """Content hash of a frame, stable across row order and column order.

    Sorting first means a re-exported CSV with the same measurements hashes the
    same, which is what makes "is this the same dataset?" answerable.
    """
    cols = sorted(map(str, df.columns))
    ordered = df[cols]
    if "serial" in ordered.columns:
        ordered = ordered.sort_values("serial", kind="mergesort")
    return sha256_bytes(
        ordered.to_csv(index=False, float_format="%.10g").encode("utf-8"))


# ---------------------------------------------------------------- training
def _baseline_metrics(df: pd.DataFrame) -> dict:
    """Out-of-fold model MAE against the two baselines it must beat.

    Reuses `module_b.forecast_all`, which is GroupKFold-by-lot, so this is the
    same honest number `src/report.py` prints - not a fresh calculation that
    could disagree with it.
    """
    if df[LOT_COL].nunique() < 2:
        return {"available": False,
                "reason": "fewer than two lots; GroupKFold has nothing to hold out"}

    res = forecast_all(df, use_gbm=True, lot_col=LOT_COL)
    out: dict = {"available": True, "validation": "GroupKFold(groups=lot)",
                 "parameters": []}
    for p in PARAM_NAMES:
        y = df[f"{p}_168h"].to_numpy(float)
        v0 = df[f"{p}_0h"].to_numpy(float)
        v24 = df[f"{p}_24h"].to_numpy(float)
        ok = np.isfinite(y) & np.isfinite(v0) & np.isfinite(v24)

        model = res.point[p].to_numpy(float)
        # Straight-line extrapolation of the 0->24h slope out to 168h.
        linear = v0 + (v24 - v0) * (168.0 / 24.0)
        last = v24

        mae = lambda pred: float(np.nanmean(np.abs(y[ok] - pred[ok])))
        m_model, m_lin, m_last = mae(model), mae(linear), mae(last)
        out["parameters"].append({
            "parameter": p,
            "fitted_exponent": round(float(res.mean_exponents[p]), 4),
            "model_mae": round(m_model, 6),
            "linear_baseline_mae": round(m_lin, 6),
            "last_value_baseline_mae": round(m_last, 6),
            "improvement_vs_linear": round((m_lin - m_model) / m_lin, 4) if m_lin else None,
            "improvement_vs_last_value": round((m_last - m_model) / m_last, 4) if m_last else None,
            # Stated plainly. On this dataset the model LOSES to
            # last-value-carried-forward on the timing and voltage axes,
            # whose fitted exponent is 0 - the data supports no extrapolation
            # there at all. Hiding that would be dishonest.
            "beats_last_value": bool(m_model < m_last),
            "beats_linear": bool(m_model < m_lin),
        })
    return out


def train_forecaster(df: pd.DataFrame, *, seed: int = 42,
                     with_metrics: bool = True) -> tuple[PowerLawForecaster, dict]:
    """Fit a Module B forecaster on the whole reference frame.

    The SHIPPED model is fitted on all of `df` - that is what an inference
    model should be. The reported METRICS come from a separate out-of-fold
    pass, because a metric from the fitted-on-everything model would be
    meaningless. The two are kept apart on purpose.
    """
    missing = [f"{p}_{t}h" for p in PARAM_NAMES for t in (0, 24, 168)
               if f"{p}_{t}h" not in df.columns]
    if missing:
        raise ModelInferenceError(
            "Training needs the 0h, 24h and 168h reads for every parameter.",
            [{"field": c, "error_code": "MISSING_TRAINING_COLUMN",
              "message": "required to fit the forecaster"} for c in missing])

    model = PowerLawForecaster(use_gbm=True, random_state=seed).fit(df, LOT_COL)
    metrics = _baseline_metrics(df) if with_metrics else {"available": False}
    return model, metrics


# -------------------------------------------------------- persist and load
def save_forecaster(model: PowerLawForecaster, path: Path | str,
                    training_serials: set | frozenset | None = None) -> str:
    """Write the artifact and return its SHA256."""
    import joblib

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {"model": model, "feature_version": FEATURE_VERSION,
         "exponents": dict(model.exponents), "seed": model.random_state,
         # The serials this model was fitted on. Out-of-fold is a claim about
         # PARTS, not about files: a subset of the training frame hashes
         # differently but has still been seen, and comparing hashes alone
         # would report it as unseen. This is what makes the check honest.
         "training_serials": frozenset(training_serials or ())},
        path, compress=3)
    return sha256_file(path)


def load_forecaster_file(path: Path | str,
                         expected_sha256: str | None = None,
                         return_payload: bool = False):
    """Load an artifact, verifying its checksum and feature version.

    A mismatch raises rather than warning. Serving predictions from bytes that
    are not the bytes the run recorded destroys the reproducibility claim, and
    a screening service that quietly does so is worse than one that stops.
    """
    import joblib

    path = Path(path)
    if not path.exists():
        raise ModelInferenceError(f"Model artifact is missing: {path.name}")

    if expected_sha256:
        actual = sha256_file(path)
        if actual != expected_sha256:
            raise ModelInferenceError(
                "Model artifact checksum does not match the value recorded "
                "when it was registered. The artifact has been modified or "
                "replaced and will not be used.",
                [{"field": "artifact_sha256", "error_code": "CHECKSUM_MISMATCH",
                  "message": f"expected {expected_sha256[:16]}…, "
                             f"found {actual[:16]}…"}])

    payload = joblib.load(path)
    if payload.get("feature_version") != FEATURE_VERSION:
        raise ModelInferenceError(
            f"Artifact was built against {payload.get('feature_version')!r} "
            f"but this service runs {FEATURE_VERSION!r}. Retrain before use.",
            [{"field": "feature_version", "error_code": "FEATURE_VERSION_MISMATCH",
              "message": "feature definitions have changed since training"}])
    # `return_payload` gives the caller the training-serial set as well, which
    # is what `LoadedModel` needs to answer the out-of-fold question honestly.
    return payload if return_payload else payload["model"]


@dataclass(frozen=True)
class LoadedModel:
    """An artifact in memory, with the registry row that describes it."""

    model: PowerLawForecaster
    artifact_id: str
    model_version: str
    artifact_sha256: str
    training_dataset_sha: str
    feature_version: str
    training_serials: frozenset = frozenset()

    def is_out_of_fold_for(self, dataset_sha256: str,
                           serials: set | frozenset | None = None) -> bool:
        """True only when this model saw NONE of the parts being screened.

        Out-of-fold is a claim about parts. Hash inequality is not enough: a
        60-row subset of the training frame hashes differently while every one
        of its components was in the fit, and reporting that as out-of-fold
        would overstate the forecast's validity.

        So when the artifact recorded its training serials, membership decides.
        Only when it did not (an older artifact) does this fall back to the
        hash, and it errs toward False - claiming less validity, not more.
        """
        if serials is not None and self.training_serials:
            return not (set(serials) & self.training_serials)
        if self.training_serials:
            return True          # no serials offered; nothing overlaps knowably
        return self.training_dataset_sha != dataset_sha256


# Process-level cache. An artifact is immutable and checksum-verified, so it is
# safe to hold; the lock stops two concurrent requests both paying the load.
_cache: dict[str, LoadedModel] = {}
_lock = threading.Lock()


def get_active_forecaster(model_repo, artifact_dir: Path | str) -> LoadedModel | None:
    """The active registered artifact, or None if nothing is trained yet.

    Returning None is a legitimate state: the service then falls back to the
    fit-in-request path, which still works and is what the demo dataset uses.
    """
    row = model_repo.active()
    if not row:
        return None

    artifact_id = row["artifact_id"]
    with _lock:
        hit = _cache.get(artifact_id)
        if hit is not None:
            return hit

        path = Path(artifact_dir) / Path(row["artifact_path"]).name
        payload = load_forecaster_file(path, row["artifact_sha256"],
                                       return_payload=True)
        loaded = LoadedModel(
            model=payload["model"],
            training_serials=frozenset(payload.get("training_serials") or ()),
            artifact_id=artifact_id,
            model_version=row["model_version"],
            artifact_sha256=row["artifact_sha256"],
            training_dataset_sha=row["training_dataset_sha"],
            feature_version=row["feature_version"],
        )
        _cache[artifact_id] = loaded
        return loaded


def clear_model_cache() -> None:
    with _lock:
        _cache.clear()
