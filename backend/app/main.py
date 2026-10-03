"""The SENTINEL FastAPI application.

Two API surfaces, deliberately:

  LEGACY (unversioned)  /health  /part/{serial}  /part/{serial}/report
                        /lot/{id}  /lots  POST /screen
        Contracts unchanged, byte for byte. The web console and
        `tests/test_api.py` depend on them, and a refactor
        that silently changes a response is a refactor that breaks clients.
        Implemented in `backend/app/api/routes/legacy.py`, which now calls the
        service layer instead of holding logic itself.

  /v1                   datasets, screening runs, jobs, components, reports,
                        models, reproducibility
        Async-first, persisted, audited. This is the production path.

Every failure leaves through the handlers below in one envelope. Internal
exception text is only included when SENTINEL_DEBUG is set - in production a
client gets a code and a message, never a traceback.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.explain import MODEL_VERSION

from backend.app.api.routes import (agents, ai, datasets, health, legacy, models, realdata,
                                    reports, screening, simulation)
from backend.app.core.config import get_settings
from backend.app.core.exceptions import SentinelError, error_envelope
from backend.app.core.logging import configure_logging, get_logger, log_event, new_request_id
from backend.app.models.database_models import init_db

__all__ = ["create_app", "app"]

log = get_logger("api")

DESCRIPTION = """
Explainable latent-defect screening for high-reliability component burn-in.

Components are soaked at 125 °C and read at 0 / 24 / 96 / 168 h. Static
datasheet limits catch gross failures only — in the shipped dataset **100 % of
latent defects pass every static limit at 168 h**. SENTINEL screens each
component against *its own production lot* using robust statistics, forecasts
the 168 h value from the first 24 hours, and emits a numbered reason code in
engineering units for every flag.

**All shipped data is simulated** (`src/generate_burnin_dataset.py`, seed 42).
Known ground truth is what makes recall measurable; it is never an input to a
verdict.

### Where to start
1. `POST /v1/datasets/upload` — upload and validate a data log
2. `POST /v1/models/train` — train and register a forecaster (once)
3. `POST /v1/screening/runs` — start a run, poll `GET /v1/jobs/{job_id}`
4. `GET /v1/screening/runs/{run_id}/components/{serial}` — evidence and explanation
5. `GET /v1/screening/runs/{run_id}/reproducibility` — everything needed to replay it
"""

TAGS = [
    {"name": "health", "description": "Liveness, readiness, model and configuration status."},
    {"name": "datasets", "description": "Upload, validate and inspect burn-in data logs."},
    {"name": "screening", "description": "Screening runs, jobs, component results, audit trail."},
    {"name": "reports", "description": "Structured screening records and signed one-page PDFs."},
    {"name": "models", "description": "Model registry, training, and honest performance reporting."},
    {"name": "agents", "description": "Agent team: workflows, steps, findings, live event stream."},
    {"name": "simulation", "description": "Digital twin: simulated lots, fault injection, "
                                    "the closed loop, blind benchmark and experiments."},
    {"name": "ai", "description": "Plain-language summaries and questions (Mistral, optional). "
                            "Explains; never decides. Every number is checked against the data."},
    {"name": "realdata", "description": "Prepared NASA aging datasets (capacitors, MOSFETs): "
                                  "measured data, reshaped never re-measured."},
    {"name": "legacy", "description": "Original unversioned endpoints, contracts unchanged."},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    configure_logging(s.log_level)
    s.ensure_dirs()
    init_db(s.sqlite_path)
    log_event("SERVICE_STARTED", log, model_version=MODEL_VERSION,
              policy=s.policy_version, config_hash=s.policy_fingerprint(),
              auth_required=bool(s.api_key))
    yield
    log_event("SERVICE_STOPPED", log)


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="SENTINEL screening service",
        version=MODEL_VERSION,
        description=DESCRIPTION,
        openapi_tags=TAGS,
        lifespan=lifespan,
    )

    # Loopback by default. This service accepts uploads and has only a
    # single-key auth abstraction, so a wildcard origin would let any page the
    # operator has open drive it. Widen via SENTINEL_CORS_ORIGIN_REGEX behind a
    # real gateway.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=s.cors_origin_regex,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or new_request_id()
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    # ---------------------------------------------------- error handlers
    def _rid(request: Request) -> str | None:
        return getattr(request.state, "request_id", None)

    @app.exception_handler(SentinelError)
    async def _domain(request: Request, exc: SentinelError):
        log_event("REQUEST_FAILED", log, path=request.url.path,
                  code=exc.code, request_id=_rid(request))
        return JSONResponse(content=exc.envelope(_rid(request)),
                            status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _request_validation(request: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in e.get("loc", [])[1:]) or "body",
                    "error_code": str(e.get("type", "invalid")).upper(),
                    "message": e.get("msg", "invalid value")}
                   for e in exc.errors()]
        return JSONResponse(
            content=error_envelope(
                "REQUEST_INVALID", "The request could not be validated.",
                details, _rid(request)),
            status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        code = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND",
                405: "METHOD_NOT_ALLOWED", 413: "PAYLOAD_TOO_LARGE"}.get(
                    exc.status_code, "REQUEST_FAILED")
        return JSONResponse(
            content=error_envelope(code, str(exc.detail), [], _rid(request)),
            status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        """Last resort. The client never receives a traceback.

        The exception TYPE is logged and the message is withheld unless debug
        is on, because an internal message can quote uploaded process data or
        a filesystem path.
        """
        log_event("UNHANDLED_EXCEPTION", log, path=request.url.path,
                  error_type=type(exc).__name__, request_id=_rid(request))
        details = ([{"field": "server", "error_code": "UNHANDLED",
                     "message": f"{type(exc).__name__}: {exc}"}]
                   if get_settings().debug else [])
        return JSONResponse(
            content=error_envelope(
                "INTERNAL_ERROR",
                "The request failed inside the screening service.",
                details, _rid(request)),
            status_code=500)

    for r in (health.router, datasets.router, screening.router,
              reports.router, models.router, agents.router, simulation.router,
              ai.router, realdata.router, legacy.router):
        app.include_router(r)

    return app


app = create_app()
