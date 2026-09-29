"""Model registry, training and honest performance reporting."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from backend.app.core.config import get_settings
from backend.app.core.exceptions import NotFoundError
from backend.app.core.security import actor_from, require_api_key
from backend.app.schemas.common import ERROR_RESPONSES
from backend.app.services.dataset_service import DatasetService
from backend.app.services.model_service import ModelService

router = APIRouter(prefix="/v1/models", tags=["models"], responses=ERROR_RESPONSES)


@router.get(
    "/performance",
    summary="Module B forecast accuracy against its baselines",
    description=(
        "Per-parameter MAE on the 168 h value, measured out-of-fold under "
        "`GroupKFold(groups=lot)`, against two baselines: linear "
        "extrapolation of the 0→24 h slope, and last-value-carried-forward "
        "from the 24 h read.\n\n"
        "**This endpoint reports where the model loses.** On the shipped "
        "dataset Module B is beaten by last-value-carried-forward on `Tpd_ns` "
        "and `Vol_mV`, whose MAE-optimal power-law exponent is 0 — the data "
        "supports no extrapolation on those axes. `beats_last_value` states "
        "that per parameter rather than reporting an average that hides it."),
)
async def performance() -> dict:
    return ModelService().performance()


@router.get("", summary="Registered model artifacts")
async def list_models(limit: int = Query(20, le=100)) -> list[dict]:
    return ModelService().list(limit)


@router.get("/active", summary="The artifact currently serving inference")
async def active_model() -> dict:
    row = ModelService().active()
    if not row:
        raise NotFoundError(
            "No model artifact is registered. Train one with "
            "`python -m backend.train`, or POST /v1/models/train.")
    return row


@router.post(
    "/train",
    status_code=201,
    summary="Train and register a Module B forecaster",
    description=(
        "Fits the power-law + gradient-boosted forecaster on a registered "
        "dataset, measures it out-of-fold against both baselines, writes a "
        "checksummed joblib artifact and activates it.\n\n"
        "Training is **never** triggered by a screening request. Separating "
        "the two is what makes inference fast and a run reproducible: a screen "
        "loads this artifact instead of refitting, so two identical requests "
        "are served by the same model."),
)
async def train_model(
    request: Request,
    dataset_id: str = Query(..., description="Dataset to train on; needs 0h, 24h and 168h reads"),
    seed: int = Query(42, description="Recorded in the artifact for reproducibility"),
    _: None = Depends(require_api_key),
) -> dict:
    settings = get_settings()
    df = DatasetService(settings).load_frame(dataset_id)
    return ModelService(settings).train(df, seed=seed, actor=actor_from(request))


@router.get("/{artifact_id}", summary="One registered artifact")
async def get_model(artifact_id: str) -> dict:
    return ModelService().get(artifact_id)
