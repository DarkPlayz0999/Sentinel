"""Screening reports: the structured record, and the signed one-page PDF."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse

from backend.app.core.security import actor_from, require_api_key
from backend.app.schemas.common import ERROR_RESPONSES
from backend.app.services.report_service import ReportService

router = APIRouter(prefix="/v1/screening/runs", tags=["reports"],
                   responses=ERROR_RESPONSES)


@router.get(
    "/{run_id}/components/{serial}/record",
    summary="Structured screening record for one component",
    description=(
        "The full auditable record as JSON, read straight from persisted run "
        "data: measurements source and hash, Module A evidence, Module B "
        "forecast, the explanation, reason codes, lot disposition and the "
        "complete provenance block (model version and checksum, pipeline, "
        "feature and policy versions, configuration hash).\n\n"
        "This is what a UI should render. The PDF below exists for the paper "
        "test traveller."),
)
async def get_record(run_id: str, serial: str) -> dict:
    return ReportService().record(run_id, serial)


@router.get(
    "/{run_id}/components/{serial}/report.pdf",
    response_class=FileResponse,
    summary="Signed one-page screening report (PDF)",
    description=(
        "Renders the one-page report a QA engineer attaches to a test "
        "traveller.\n\n"
        "The run is **replayed** from the stored dataset under the exact model "
        "artifact it recorded, and every regenerated verdict is compared "
        "against the persisted result before anything is rendered. If the "
        "replay does not reproduce the run, the report is refused with a "
        "`RUN_NOT_REPRODUCIBLE` error rather than issuing a document that "
        "disagrees with the record it cites."),
)
async def get_report_pdf(run_id: str, serial: str, request: Request,
                         _: None = Depends(require_api_key)) -> FileResponse:
    path = ReportService().build(run_id, serial, actor=actor_from(request))
    return FileResponse(
        path, media_type="application/pdf",
        # Only the leaf name is exposed; the storage layout is not a client's
        # business and a path here would leak the deployment structure.
        filename=f"SENTINEL_{serial}_{run_id[:12]}.pdf")
