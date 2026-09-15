"""Screening runs, jobs, components and reproducibility."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request

from backend.app.core.config import get_settings
from backend.app.core.exceptions import ConflictError, NotFoundError
from backend.app.core.logging import get_logger, log_event
from backend.app.core.security import actor_from, require_api_key
from backend.app.repositories.repositories import JobRepository
from backend.app.schemas.common import ERROR_RESPONSES
from backend.app.schemas.screening import (
    ComponentResult, JobResponse, RunSummary,
)
from backend.app.services.dataset_service import DatasetService
from backend.app.services.screening_service import ScreeningService

router = APIRouter(prefix="/v1", tags=["screening"], responses=ERROR_RESPONSES)
log = get_logger("api.screening")


def _run_in_background(run_id: str, job_id: str) -> None:
    """Executed in FastAPI's threadpool.

    Exceptions are swallowed HERE and only here: the service has already
    recorded FAILED on both the run and the job before re-raising, so the
    state is persisted and there is no HTTP response left to carry the error.
    Letting it propagate would only produce an unattributed traceback in the
    server log.
    """
    try:
        ScreeningService().execute(run_id, job_id=job_id)
    except Exception as exc:  # noqa: BLE001 - see docstring
        log_event("BACKGROUND_SCREEN_FAILED", log, run_id=run_id,
                  job_id=job_id, error_type=type(exc).__name__)


@router.post(
    "/screening/runs",
    response_model=JobResponse,
    status_code=202,
    summary="Start a screening run on a registered dataset",
    description=(
        "Creates a screening run and returns a job immediately.\n\n"
        "**Asynchronous is the production path.** A 2,100-component screen "
        "takes a few seconds with a trained model artifact and considerably "
        "longer without one; holding an HTTP request open for it is not a "
        "production design. Poll `GET /v1/jobs/{job_id}` for status, then read "
        "`GET /v1/screening/runs/{run_id}`.\n\n"
        "Pass `sync=true` to execute inline and receive the finished run "
        "instead — intended for small demo frames, and refused above "
        "`SENTINEL_SYNC_SCREEN_MAX_ROWS` rows."),
)
async def start_run(
    request: Request,
    background: BackgroundTasks,
    dataset_id: str = Query(..., description="A dataset registered via /v1/datasets/upload"),
    sync: bool = Query(False, description="Execute inline instead of queueing"),
    _: None = Depends(require_api_key),
):
    settings = get_settings()
    svc = ScreeningService(settings)
    actor = actor_from(request)

    ds = DatasetService(settings).get(dataset_id)
    run_id = svc.create_run(dataset_id, actor=actor)
    jobs = JobRepository(settings.sqlite_path)
    job_id = jobs.create("SCREENING", dataset_id=dataset_id, run_id=run_id,
                         actor=actor)

    if sync:
        if ds["row_count"] > settings.sync_screen_max_rows:
            raise ConflictError(
                f"This dataset has {ds['row_count']:,} rows, above the "
                f"{settings.sync_screen_max_rows:,}-row synchronous limit. "
                "Omit `sync=true` and poll the job instead.")
        svc.execute(run_id, job_id=job_id)
    else:
        background.add_task(_run_in_background, run_id, job_id)

    return jobs.get(job_id)


@router.get("/jobs/{job_id}", response_model=JobResponse,
            summary="Job status")
async def get_job(job_id: str):
    job = JobRepository(get_settings().sqlite_path).get(job_id)
    if not job:
        raise NotFoundError(f"No job with id {job_id!r}.")
    return job


@router.get("/jobs", response_model=list[JobResponse], summary="Recent jobs")
async def list_jobs(limit: int = 50):
    return JobRepository(get_settings().sqlite_path).list(limit)


@router.get("/screening/runs", response_model=list[dict],
            summary="Recent screening runs")
async def list_runs(limit: int = 50):
    return ScreeningService().runs.list(limit)


@router.get("/screening/runs/{run_id}", response_model=RunSummary,
            summary="Screening run summary with per-lot disposition")
async def get_run(run_id: str):
    return ScreeningService().get_run(run_id)


@router.get(
    "/screening/runs/{run_id}/components",
    response_model=list[ComponentResult],
    summary="Component results for a run, highest risk first",
)
async def list_components(
    run_id: str,
    verdict: str | None = Query(None, description="ACCEPT | WATCH | REJECT"),
    lot: str | None = Query(None, examples=["L04"]),
    limit: int = Query(200, le=2000),
    offset: int = 0,
):
    rows = ScreeningService().list_components(
        run_id, verdict=verdict, lot=lot, limit=limit, offset=offset)
    return [{**r, "run_id": run_id} for r in rows]


@router.get(
    "/screening/runs/{run_id}/components/{serial}",
    response_model=ComponentResult,
    summary="One component: structured Module A/B evidence and its explanation",
    description=(
        "Returns the persisted result, including `evidence` (layered Module A "
        "findings and the Module B forecast, with OBSERVED and FORECAST kept "
        "separate) and `explanation` (the ranked decision path, a "
        "`primary_reason` derived from the largest weighted contribution, and "
        "the rule-based reason codes that fired).\n\n"
        "A component whose verdict is not ACCEPT always has a "
        "`primary_reason`."),
)
async def get_component(run_id: str, serial: str):
    return {**ScreeningService().get_component(run_id, serial), "run_id": run_id}


@router.get("/screening/runs/{run_id}/audit",
            summary="Append-only audit trail for a run")
async def get_audit(run_id: str, limit: int = Query(200, le=2000)):
    return ScreeningService().audit_trail(run_id, limit)


@router.get(
    "/screening/runs/{run_id}/reproducibility",
    summary="Everything needed to reproduce this run",
    description=(
        "Dataset SHA256, model artifact id and SHA256, training-dataset hash, "
        "random seed, hyperparameters, pipeline/feature/policy versions and "
        "the effective configuration hash. Two runs agreeing on all of these "
        "produce identical decisions; two that differ are not comparable."),
)
async def get_reproducibility(run_id: str):
    return ScreeningService().reproducibility(run_id)
