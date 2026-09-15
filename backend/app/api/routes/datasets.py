"""Dataset upload and inspection.

Routes contain no business logic: each one parses the request, calls a service
and shapes the response. Validation, hashing, storage and audit all live in
`services/dataset_service.py`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Request, UploadFile

from backend.app.core.security import actor_from, require_api_key
from backend.app.schemas.common import ERROR_RESPONSES
from backend.app.schemas.screening import DatasetSummary, DatasetUploadResponse
from backend.app.services.dataset_service import DatasetService

router = APIRouter(prefix="/v1/datasets", tags=["datasets"],
                   responses=ERROR_RESPONSES)


@router.post(
    "/upload",
    response_model=DatasetUploadResponse,
    status_code=201,
    summary="Upload and validate a burn-in data log",
    description=(
        "Accepts a wide-format CSV: one row per component, columns named "
        "`{PARAMETER}_{HOURS}h` — the shape every ATE data-log exports.\n\n"
        "**Required:** `serial`, `lot`, and the `0h` read for all four "
        "parameters.\n\n"
        "**Optional:** `24h` (needed for the Module B forecast), `96h` (needed "
        "for the curvature view), `168h` (absent means an hour-24 triage "
        "frame), plus `wafer`, `x`, `y`.\n\n"
        "The screening pipeline is **not** run here. Validation must pass "
        "first; a frame with any blocking error is rejected with 422 and "
        "nothing is stored. Warnings do not block and are returned with the "
        "response.\n\n"
        "Uploads are content-addressed by the hash of the parsed frame, so "
        "re-uploading identical measurements returns the existing "
        "`dataset_id` with `deduplicated: true` rather than creating a copy."),
)
async def upload_dataset(
    request: Request,
    file: UploadFile = File(..., description="Wide-format burn-in CSV"),
    _: None = Depends(require_api_key),
) -> dict:
    raw = await file.read()
    return DatasetService().ingest(
        raw, file.filename, actor=actor_from(request))


@router.get("", response_model=list[DatasetSummary],
            summary="List registered datasets")
async def list_datasets(limit: int = 50) -> list[dict]:
    return DatasetService().list(limit)


@router.get("/{dataset_id}", summary="Dataset detail with its validation report")
async def get_dataset(dataset_id: str) -> dict:
    row = DatasetService().get(dataset_id)
    # The on-disk location is an internal detail and never leaves the process.
    return {k: v for k, v in row.items() if k != "stored_path"}
