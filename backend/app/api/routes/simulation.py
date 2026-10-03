"""Digital twin endpoints: simulations, fault injection, the closed loop, experiments.

    GET  /v1/twin/board                        board, fault catalogue, detectability
    POST /v1/simulations                       create (VISIBLE or BLIND; sih_demo preset)
    POST /v1/simulations/{id}/faults           inject a fault before start
    POST /v1/simulations/{id}/start            run the burn-in (202 + job)
    POST /v1/simulations/{id}/step             advance one read point
    POST /v1/simulations/{id}/screen           send measurements to Sentinel + agents
    GET  /v1/simulations/{id}                  summary (truth withheld in BLIND)
    GET  /v1/simulations/{id}/boards           the lot, one row per board
    GET  /v1/simulations/{id}/components       component explorer for one board
    GET  /v1/simulations/{id}/timeline         everything the 3D view animates
    GET  /v1/simulations/{id}/candidates       replacement candidates, ranked
    POST /v1/simulations/{id}/replace          swap, rerun, re-screen
    GET  /v1/simulations/{id}/comparison       before / after
    POST /v1/simulations/{id}/boards/{serial}/decision   human disposition
    POST /v1/simulations/{id}/reveal           ground truth + benchmark (after predict)
    GET  /v1/simulations/{id}/events           SSE: live progress
    GET  /v1/simulations/{id}/audit            the complete trail
    POST /v1/experiments                       sweeps, Monte Carlo, OOD (202 + job)

Sentinel's own endpoints are reused, not duplicated: a simulated lot becomes
an ordinary dataset and screening run, readable through /v1/screening/... .
"""

from __future__ import annotations

import asyncio
import json
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.app.core.logging import get_logger, log_event
from backend.app.core.security import actor_from, require_api_key
from backend.app.schemas.common import ERROR_RESPONSES
from backend.app.schemas.simulation import (
    ExperimentCreate, FaultIn, ReplaceIn, SimulationCreate,
)
from backend.app.services.experiment_service import ExperimentService
from backend.app.services.simulation_service import SimulationService

router = APIRouter(prefix="/v1", tags=["simulation"], responses=ERROR_RESPONSES)
log = get_logger("api.simulation")


def _bg_execute(sid: str, job_id: str) -> None:
    """Background worker. The service persists FAILED / SIMULATION_FAILED itself."""
    try:
        SimulationService().execute(sid, job_id=job_id)
    except Exception as exc:  # noqa: BLE001 - state is already persisted
        log_event("BACKGROUND_SIMULATION_FAILED", log, simulation_id=sid,
                  error_type=type(exc).__name__)


def _bg_screen(sid: str) -> None:
    try:
        SimulationService().screen(sid)
    except Exception as exc:  # noqa: BLE001
        log_event("BACKGROUND_SIM_SCREEN_FAILED", log, simulation_id=sid,
                  error_type=type(exc).__name__)


def _bg_experiment(eid: str) -> None:
    try:
        ExperimentService().execute(eid)
    except Exception as exc:  # noqa: BLE001
        log_event("BACKGROUND_EXPERIMENT_FAILED", log, experiment_id=eid,
                  error_type=type(exc).__name__)


# ------------------------------------------------------------------ board
@router.get("/twin/board", summary="Reference board, fault catalogue and detectability")
async def board(board_id: str = "RB-1"):
    return SimulationService.catalogue(board_id)


# ------------------------------------------------------------ simulations
@router.get("/simulations", summary="Recent simulations")
async def list_simulations(limit: int = Query(50, le=500)):
    return SimulationService().list(limit)


@router.post("/simulations", status_code=201, summary="Create a simulated lot",
             description="Creates the lot and its faults. Pass `start=true` to begin the "
                         "burn-in immediately in the background.")
async def create_simulation(body: SimulationCreate, request: Request,
                            background: BackgroundTasks,
                            start: bool = Query(False),
                            _: None = Depends(require_api_key)):
    svc = SimulationService()
    actor = actor_from(request)
    sim = svc.create(body.model_dump(), actor=actor)
    if start:
        job_id = svc.queue(sim["simulation_id"], actor=actor)
        background.add_task(_bg_execute, sim["simulation_id"], job_id)
        sim = svc.get(sim["simulation_id"])
    return sim


@router.post("/simulations/{sid}/faults", summary="Inject a fault before the burn-in")
async def add_fault(sid: str, body: FaultIn, request: Request,
                    _: None = Depends(require_api_key)):
    return SimulationService().add_fault(sid, body.model_dump(), actor=actor_from(request))


@router.post("/simulations/{sid}/start", status_code=202,
             summary="Run the burn-in (background job; follow /events)")
async def start_simulation(sid: str, request: Request, background: BackgroundTasks,
                           sync: bool = Query(False, description="Run inline (tests, small lots)"),
                           _: None = Depends(require_api_key)):
    svc = SimulationService()
    job_id = svc.queue(sid, actor=actor_from(request))
    if sync:
        try:
            svc.execute(sid, job_id=job_id)
        except Exception:  # noqa: BLE001 - the failure is persisted and returned below
            pass
    else:
        background.add_task(_bg_execute, sid, job_id)
    sim = svc.get(sid)
    return {"simulation_id": sid, "status": sim["status"], "job_id": job_id}


@router.post("/simulations/{sid}/step", summary="Advance exactly one read point")
async def step_simulation(sid: str, _: None = Depends(require_api_key)):
    return SimulationService().step(sid)


@router.post("/simulations/{sid}/screen", status_code=202,
             summary="Send the measurements to Sentinel; agents investigate flags")
async def screen_simulation(sid: str, background: BackgroundTasks,
                            sync: bool = Query(False),
                            _: None = Depends(require_api_key)):
    svc = SimulationService()
    if sync:
        return svc.screen(sid)
    background.add_task(_bg_screen, sid)
    return svc.get(sid)


@router.get("/simulations/{sid}", summary="Simulation summary")
async def get_simulation(sid: str):
    return SimulationService().get(sid)


@router.get("/simulations/{sid}/boards", summary="Every board in the lot")
async def boards(sid: str):
    return SimulationService().boards(sid)


@router.get("/simulations/{sid}/components", summary="Component explorer for one board")
async def components(sid: str, serial: str = Query(...), t: float | None = Query(None)):
    return SimulationService().components(sid, serial, t)


@router.get("/simulations/{sid}/timeline", summary="Time series the 3D view animates")
async def timeline(sid: str, serial: str = Query(...), phase: str = Query("burn-in-1")):
    return SimulationService().timeline(sid, serial, phase)


@router.get("/simulations/{sid}/candidates", summary="Replacement candidates, ranked")
async def candidates(sid: str, serial: str = Query(...), component_id: str = Query(...)):
    return SimulationService().candidates(sid, serial, component_id)


@router.post("/simulations/{sid}/replace", summary="Replace a component, rerun, re-screen")
async def replace_component(sid: str, body: ReplaceIn, request: Request,
                            _: None = Depends(require_api_key)):
    return SimulationService().replace(sid, body.serial, body.component_id,
                                       body.candidate_id, actor=actor_from(request))


@router.get("/simulations/{sid}/comparison", summary="Before / after every replacement")
async def comparison(sid: str):
    return SimulationService().comparison(sid)


class DecisionIn(BaseModel):
    decision: Literal["SCRAP", "REWORK", "HOLD", "RELEASE_WITH_WAIVER"]
    note: str = Field("", max_length=500)


@router.post("/simulations/{sid}/boards/{serial}/decision",
             summary="Record a human disposition (the only way a board is dispositioned)")
async def decide(sid: str, serial: str, body: DecisionIn, request: Request,
                 _: None = Depends(require_api_key)):
    return SimulationService().decide(sid, serial, body.decision, body.note,
                                      actor=actor_from(request))


@router.post("/simulations/{sid}/reveal",
             summary="Open the ground truth and benchmark Sentinel (after it has predicted)")
async def reveal(sid: str, request: Request, _: None = Depends(require_api_key)):
    return SimulationService().reveal(sid, actor=actor_from(request))


@router.get("/simulations/{sid}/audit", summary="The complete audit trail")
async def audit(sid: str):
    return SimulationService().audit_trail(sid)


@router.get("/simulations/{sid}/events", summary="Server-Sent Events: live simulation progress")
async def events(sid: str, request: Request,
                 follow: bool = Query(True, description="False: send backlog and close"),
                 since: int = Query(0, description="Start after this event id"),
                 last_event_id: str | None = Header(None)):
    svc = SimulationService()
    svc.get(sid)                                   # 404 before streaming
    cursor = int(last_event_id) if last_event_id and last_event_id.isdigit() else since

    async def stream():
        nonlocal cursor
        idle = 0
        yield "retry: 2000\n\n"
        while True:
            rows = svc.events(sid, cursor)
            for r in rows:
                cursor = r["seq"]
                body = {"type": r["event_type"], "serial": r["board_serial"],
                        "component_id": r["component_id"], "payload": r["payload"],
                        "at": r["timestamp"]}
                yield f"id: {r['seq']}\nevent: {r['event_type']}\ndata: {json.dumps(body)}\n\n"
            if not follow or await request.is_disconnected():
                return
            idle = 0 if rows else idle + 1
            if idle and idle % 15 == 0:
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------ experiments
@router.post("/experiments", status_code=202,
             summary="Run a sweep, Monte Carlo campaign or OOD suite (background)")
async def create_experiment(body: ExperimentCreate, request: Request,
                            background: BackgroundTasks,
                            sync: bool = Query(False),
                            _: None = Depends(require_api_key)):
    svc = ExperimentService()
    exp = svc.create(body.model_dump(), actor=actor_from(request))
    if sync:
        return svc.execute(exp["experiment_id"])
    background.add_task(_bg_experiment, exp["experiment_id"])
    return exp


@router.get("/experiments", summary="Recent experiments")
async def list_experiments(limit: int = Query(50, le=500)):
    return ExperimentService().list(limit)


@router.get("/experiments/{eid}", summary="Experiment summary and metrics")
async def get_experiment(eid: str):
    return ExperimentService().get(eid)
