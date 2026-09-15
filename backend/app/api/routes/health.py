"""Health, liveness, readiness and model status.

Liveness and readiness are genuinely different questions and are answered
differently:

    /health/live   is the process running?              never touches the DB
    /health/ready  can it serve a screening request?    checks every dependency

A container orchestrator restarts on a failed liveness probe and removes from
the load balancer on a failed readiness probe; conflating them turns a missing
model artifact into a restart loop.

No secret, no filesystem path and no internal exception text appears in any of
these payloads.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from src.explain import MODEL_VERSION

from backend.app.core.config import get_settings
from backend.app.ml.inference import FEATURE_VERSION, PIPELINE_VERSION
from backend.app.models.database_models import connect
from backend.app.schemas.common import ReadinessResponse
from backend.app.services.model_service import ModelService

router = APIRouter(tags=["health"])


@router.get("/health/live", summary="Liveness probe")
async def live() -> dict:
    """Process is up. Deliberately checks nothing else."""
    return {"status": "alive"}


@router.get("/health/ready", response_model=ReadinessResponse,
            summary="Readiness probe")
async def ready() -> dict:
    """Can this instance actually serve a screening request?

    A missing model artifact is reported as `absent`, not as a failure: the
    service still screens by fitting in-request, more slowly. Only a broken
    database or unwritable storage makes it not ready.
    """
    s = get_settings()
    checks: dict[str, str] = {}

    try:
        with connect(s.sqlite_path) as c:
            c.execute("SELECT 1 FROM schema_meta LIMIT 1").fetchone()
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"

    for label, path in (("upload_dir", s.upload_dir),
                        ("artifact_dir", s.artifact_dir)):
        p = Path(path)
        checks[label] = "ok" if p.is_dir() and p.exists() else "missing"

    try:
        checks["model_artifact"] = "ok" if ModelService(s).active() else "absent"
    except Exception:
        checks["model_artifact"] = "error"

    hard = ("database", "upload_dir", "artifact_dir")
    return {"ready": all(checks[k] == "ok" for k in hard), "checks": checks}


@router.get("/health/models", summary="Model artifact status")
async def model_health() -> dict:
    """Which artifact is serving inference, and whether it loads cleanly.

    `loadable` is the useful field: the registry row can exist while the file
    on disk is missing or has been modified since it was checksummed, and this
    is where that shows up rather than in the middle of a screening run.
    """
    svc = ModelService()
    active = svc.active()
    if not active:
        return {
            "active_artifact": None,
            "loadable": False,
            "inference_mode": "fit-in-request",
            "note": ("No artifact registered. Screening still works but "
                     "refits the forecaster per request, which is slower and "
                     "not reproducible across restarts. Train one with "
                     "`python -m backend.train`."),
        }

    try:
        loaded = svc.loaded()
        loadable, detail = loaded is not None, None
    except Exception as exc:
        loadable, detail = False, type(exc).__name__

    return {
        "active_artifact": {
            "artifact_id": active["artifact_id"],
            "model_version": active["model_version"],
            "model_name": active["model_name"],
            "feature_version": active["feature_version"],
            "created_at": active["created_at"],
            "training_rows": active["training_rows"],
            "training_dataset_sha256": active["training_dataset_sha"],
            "artifact_sha256": active["artifact_sha256"],
            "random_seed": active["random_seed"],
        },
        "loadable": loadable,
        "failure_type": detail,
        "inference_mode": "artifact" if loadable else "degraded",
    }


@router.get("/v1/config", summary="Effective configuration (secrets excluded)")
async def config() -> dict:
    """The policy this instance is running, and its fingerprint.

    Every screening run records this fingerprint, so a decision can be matched
    to the configuration that produced it. `api_key` is never included - only
    whether one is configured.
    """
    s = get_settings()
    return {
        "policy": s.policy_dict(),
        "policy_fingerprint": s.policy_fingerprint(),
        "versions": {
            "model_version": MODEL_VERSION,
            "pipeline_version": PIPELINE_VERSION,
            "feature_version": FEATURE_VERSION,
            "policy_version": s.policy_version,
        },
        "limits": {
            "max_upload_bytes": s.max_upload_bytes,
            "max_upload_rows": s.max_upload_rows,
            "sync_screen_max_rows": s.sync_screen_max_rows,
        },
        "auth_required": bool(s.api_key),
        "simulated_data": True,
    }
