"""Agent team endpoints: submit, resume, inspect, and a live event stream.

The stream is Server-Sent Events over the `agent_events` table. Every event is
a row written in the same transaction as the state change it describes, so the
Agent Operations page shows only what the database holds - nothing synthesised.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse

from backend.app.agents import graph as agents
from backend.app.core.config import get_settings
from backend.app.core.exceptions import ConflictError, NotFoundError
from backend.app.core.logging import get_logger, log_event
from backend.app.core.security import actor_from, require_api_key
from backend.app.repositories.repositories import AgentRepository
from backend.app.schemas.common import ERROR_RESPONSES
from backend.app.services.dataset_service import DatasetService

router = APIRouter(prefix="/v1/agents", tags=["agents"], responses=ERROR_RESPONSES)
log = get_logger("api.agents")

AGENTS = ("data_quality", "anomaly", "forecast", "combine", "quarantine")


def _repo() -> AgentRepository:
    return AgentRepository(get_settings().sqlite_path)


def _run_in_background(workflow_id: str, resume: bool = False) -> None:
    """The workflow records FAILED itself before re-raising; swallow here only."""
    try:
        agents.execute(workflow_id, resume=resume)
    except Exception as exc:  # noqa: BLE001
        log_event("BACKGROUND_WORKFLOW_FAILED", log, workflow_id=workflow_id,
                  error_type=type(exc).__name__)


@router.post("/workflows", status_code=202, summary="Run the agent team on a dataset")
async def submit(request: Request, background: BackgroundTasks,
                 dataset_id: str = Query(...),
                 sync: bool = Query(False, description="Run inline (small datasets, tests)"),
                 _: None = Depends(require_api_key)):
    s = get_settings()
    ds = DatasetService(s).get(dataset_id)          # 404 before anything is created
    wf, created = agents.submit(dataset_id, trigger="manual", actor=actor_from(request))
    if created:
        if sync:
            if ds["row_count"] > s.sync_screen_max_rows:
                raise ConflictError("Dataset too large for sync=true; omit it.")
            try:
                agents.execute(wf["workflow_id"])
            except Exception:  # noqa: BLE001 - FAILED is persisted and returned below
                pass
        else:
            background.add_task(_run_in_background, wf["workflow_id"])
    return {"workflow": _repo().get_workflow(wf["workflow_id"]), "deduplicated": not created}


@router.post("/workflows/{workflow_id}/resume", status_code=202,
             summary="Resume a FAILED workflow from its last checkpoint")
async def resume(workflow_id: str, background: BackgroundTasks,
                 _: None = Depends(require_api_key)):
    wf = _repo().get_workflow(workflow_id)
    if not wf:
        raise NotFoundError(f"No workflow {workflow_id!r}.")
    if wf["status"] != "FAILED":
        raise ConflictError(f"Workflow is {wf['status']}; only FAILED can be resumed.")
    background.add_task(_run_in_background, workflow_id, True)
    return {"workflow": wf}


@router.get("/workflows", summary="Recent workflows")
async def list_workflows(limit: int = Query(50, le=500)):
    return _repo().list_workflows(limit)


@router.get("/workflows/{workflow_id}", summary="Workflow with its steps and findings")
async def get_workflow(workflow_id: str):
    repo = _repo()
    wf = repo.get_workflow(workflow_id)
    if not wf:
        raise NotFoundError(f"No workflow {workflow_id!r}.")
    return {**wf, "steps": repo.steps(workflow_id), "findings": repo.findings(workflow_id)}


@router.get("/status", summary="Each agent's most recent step, from the database")
async def agent_status():
    repo = _repo()
    wfs = repo.list_workflows(200)
    counts: dict[str, int] = {}
    for w in wfs:
        counts[w["status"]] = counts.get(w["status"], 0) + 1
    latest: dict[str, dict | None] = {a: None for a in AGENTS}
    for w in wfs:                                   # newest first
        for st in reversed(repo.steps(w["workflow_id"])):
            if latest.get(st["agent"]) is None:
                latest[st["agent"]] = {k: st[k] for k in (
                    "workflow_id", "status", "attempt", "started_at", "completed_at",
                    "duration_s", "error")}
        if all(latest.values()):
            break
    return {"workflow_counts": counts, "agents": latest}


@router.get("/events", summary="Server-Sent Events stream of agent state changes")
async def events(request: Request,
                 follow: bool = Query(True, description="False: send backlog and close"),
                 since: int | None = Query(None, description="Start after this event id"),
                 last_event_id: str | None = Header(None)):
    repo = _repo()
    cursor = since if since is not None else (
        int(last_event_id) if last_event_id and last_event_id.isdigit() else repo.last_seq())

    async def stream():
        nonlocal cursor
        idle = 0
        yield "retry: 3000\n\n"
        while True:
            rows = repo.events_after(cursor)
            for r in rows:
                cursor = r["seq"]
                body = {"workflow_id": r["workflow_id"], "kind": r["kind"],
                        "payload": r["payload"], "at": r["created_at"]}
                yield f"id: {r['seq']}\nevent: {r['kind']}\ndata: {json.dumps(body)}\n\n"
            if not follow or await request.is_disconnected():
                return
            idle = 0 if rows else idle + 1
            if idle and idle % 15 == 0:
                yield ": keep-alive\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
