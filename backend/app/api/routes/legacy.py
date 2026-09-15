"""The original unversioned endpoints. Contracts unchanged.

    GET  /health
    GET  /part/{serial}
    GET  /part/{serial}/report
    GET  /lot/{lot_id}
    GET  /lots
    POST /screen

These are kept byte-compatible on purpose. The Streamlit dashboard, the web
console's Screen page and `tests/test_api.py` all consume them, and a
"cleaner" response shape is not worth breaking a working client for. The
production path is `/v1`; this surface is preserved, not extended.

What DID change is what sits behind them: the request handlers no longer hold
screening logic, and `POST /screen` uses a trained model artifact when one is
registered instead of refitting LightGBM inside the request.

One deliberate restriction on that optimisation, stated because it looks
arbitrary otherwise: the artifact is used only when the uploaded frame carries
all four 168 h columns. A pre-fitted model CAN forecast from an hour-24 frame -
that is a real capability and `/v1` uses it - but doing so here would change
this endpoint's long-standing behaviour, where an hour-24 frame returns
`predicted_drift = 0` with its weight redistributed. Clients rely on that.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from functools import lru_cache

import pandas as pd
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from src.explain import MODEL_VERSION, lot_reason_codes, part_report, reason_codes_for_part
from src.features import PARAM_NAMES
from src.pipeline import load_wide, screen

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger, log_event
from backend.app.ml.inference import (
    PIPELINE_VERSION, dataframe_sha256, get_active_forecaster)
from backend.app.repositories.repositories import ModelRepository

router = APIRouter(tags=["legacy"])
log = get_logger("api.legacy")


# ------------------------------------------------------------- schemas
class Verdict(BaseModel):
    # `model_version` is a traceability field, not a pydantic model attribute.
    model_config = ConfigDict(protected_namespaces=())

    serial: str
    lot: str
    risk_score: float = Field(..., ge=0, le=100)
    verdict: str
    sub_scores: dict
    reason_codes: list[dict]
    model_version: str
    generated_utc: str


class LotSummary(BaseModel):
    lot: str
    parts: int
    reject: int
    watch: int
    reject_fraction: float
    pda_limit: float
    status: str
    mean_risk: float
    reason_codes: list[dict]


# --------------------------------------------------------------- state
@lru_cache(maxsize=1)
def _default():
    """The shipped dataset, screened once and cached.

    Cached because an uncached screen refits a cross-validated forecast per
    request, which would make the demo look broken.
    """
    df = load_wide()
    return df, screen(df)


def _forecaster_for(df: pd.DataFrame):
    """The registered artifact, when it is safe to use on this frame.

    Returns (model, is_out_of_fold). See the module docstring for why an
    hour-24 frame deliberately does not get one here.
    """
    if not all(f"{p}_168h" in df.columns for p in PARAM_NAMES):
        return None, False
    s = get_settings()
    try:
        loaded = get_active_forecaster(ModelRepository(s.sqlite_path), s.artifact_dir)
    except Exception as exc:
        # A broken artifact must not take the endpoint down - fall back to
        # fitting in-request. Log the message too: a silent fallback here once
        # masked a real bug by returning a plausible-looking answer computed
        # the slow way, and "it still worked" is how that kind of defect
        # survives to production.
        log_event("ARTIFACT_LOAD_FAILED", log, error_type=type(exc).__name__,
                  detail=str(exc)[:200])
        return None, False
    if not loaded:
        return None, False
    # Do NOT assert out-of-fold. The shipped artifact is trained on the whole
    # burn-in dataset, so an uploaded subset of it has been seen even though it
    # hashes differently. Ask the artifact which parts it was fitted on.
    serials = set(df["serial"].astype(str)) if "serial" in df.columns else None
    oof = loaded.is_out_of_fold_for(dataframe_sha256(df), serials)
    return loaded.model, oof


def _verdict_payload(df: pd.DataFrame, res, i) -> dict:
    row = res.fused.loc[i]
    codes = reason_codes_for_part(df, res.features, i, res.module_b)
    return dict(
        serial=str(row.serial), lot=str(row.lot),
        risk_score=round(float(row.risk_score), 1),
        verdict=str(row.verdict),
        sub_scores={k: round(float(row[k]), 1) for k in
                    ("static_margin", "dynamic_outlier", "predicted_drift",
                     "multivariate", "curvature")},
        reason_codes=[c.as_dict() for c in codes],
        model_version=MODEL_VERSION,
        generated_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


# ------------------------------------------------------------ endpoints
@router.get("/health", summary="Service health and loaded dataset")
def health() -> dict:
    try:
        df, res = _default()
        loaded = dict(parts=len(df), lots=int(df.lot.nunique()),
                      bands=dict(watch=round(res.bands.watch, 1),
                                 reject=round(res.bands.reject, 1)))
    except SystemExit:
        loaded = None
    return dict(status="ok", model_version=MODEL_VERSION, dataset=loaded,
                simulated_data=True, pipeline_version=PIPELINE_VERSION)


@router.get("/part/{serial}", response_model=Verdict,
            summary="Verdict, sub-scores and reason codes for one component")
def get_part(serial: str) -> dict:
    df, res = _default()
    i = res.part(serial)
    if i is None:
        raise HTTPException(404, f"serial {serial!r} not found")
    return _verdict_payload(df, res, i)


@router.get("/part/{serial}/report",
            summary="Auditable record: measured values against lot statistics")
def get_part_report(serial: str) -> dict:
    df, res = _default()
    i = res.part(serial)
    if i is None:
        raise HTTPException(404, f"serial {serial!r} not found")
    return part_report(df, res.features, i, res.fused, res.module_b)


@router.get("/lot/{lot_id}", response_model=LotSummary,
            summary="Lot summary with PDA status")
def get_lot(lot_id: str) -> dict:
    df, res = _default()
    if lot_id not in res.pda.index:
        raise HTTPException(404, f"lot {lot_id!r} not found")
    r = res.pda.loc[lot_id]
    codes = lot_reason_codes(res.pda)
    return dict(
        lot=lot_id, parts=int(r.parts), reject=int(r.reject),
        watch=int(r.watch), reject_fraction=round(float(r.reject_frac), 4),
        pda_limit=float(r.pda_limit), status=str(r.status),
        mean_risk=float(r.mean_risk),
        reason_codes=codes[codes.lot == lot_id].to_dict("records"),
    )


@router.get("/lots", summary="Per-lot disposition for the shipped dataset")
def list_lots() -> list[dict]:
    _, res = _default()
    return res.pda.reset_index().to_dict("records")


@router.post("/screen", summary="Batch screen an uploaded wide-format CSV")
async def screen_csv(file: UploadFile = File(...)) -> dict:
    """Screen a CSV synchronously and return every verdict.

    Accepts an hour-24 frame (no 96h/168h columns): Module B is skipped and the
    fused score redistributes its weight rather than silently scoring the part
    as safer.

    For production use prefer `POST /v1/screening/runs`, which persists the run,
    records an audit trail and does not hold the connection open.
    """
    raw = await file.read()
    s = get_settings()
    if len(raw) > s.max_upload_bytes:
        raise HTTPException(
            413, f"upload exceeds the {s.max_upload_bytes} byte limit")
    try:
        df = pd.read_csv(io.BytesIO(raw))
    except Exception as exc:
        raise HTTPException(400, f"could not parse CSV: {exc}") from exc

    missing = [c for c in ("serial", "lot") if c not in df.columns]
    missing += [f"{p}_{t}h" for p in PARAM_NAMES for t in (0, 24)
                if f"{p}_{t}h" not in df.columns]
    if missing:
        raise HTTPException(422, f"missing required columns: {missing}")

    forecaster, oof = _forecaster_for(df)
    res = screen(df, forecaster=forecaster, forecaster_is_out_of_fold=oof)
    verdicts = [_verdict_payload(df, res, i) for i in df.index]

    log_event("LEGACY_SCREEN", log, rows=len(df),
              artifact="yes" if forecaster is not None else "no")
    return dict(
        model_version=MODEL_VERSION,
        generated_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        parts=len(df),
        summary=res.fused.verdict.value_counts().to_dict(),
        bands=dict(watch=round(res.bands.watch, 1),
                   reject=round(res.bands.reject, 1)),
        # Screening-integrity flags the web console renders.
        forecast_out_of_fold=bool(res.forecast_out_of_fold),
        module_b_available=res.module_b is not None,
        lots_in_frame=int(df["lot"].nunique()),
        read_points=[t for t in (0, 24, 96, 168)
                     if all(f"{p}_{t}h" in df.columns for p in PARAM_NAMES)],
        lots=res.pda.reset_index().to_dict("records"),
        verdicts=verdicts,
    )
