"""FastAPI service - compatibility shim.

    uvicorn src.api:app --reload
    open http://127.0.0.1:8000/docs

The application moved to `backend/app/main.py` when the service grew a
persistence layer, a job system and an audit trail. This module stays because
`uvicorn src.api:app`, the run scripts and `tests/test_api.py` all reference it,
and breaking a documented entry point to tidy an import path is not a trade
worth making.

The legacy endpoints it used to define are unchanged and now live in
`backend/app/api/routes/legacy.py`:

    GET  /health            GET  /lot/{lot_id}
    GET  /part/{serial}     GET  /lots
    GET  /part/{serial}/report
    POST /screen

The same application also serves the versioned `/v1` surface - dataset upload
and validation, screening runs and jobs, structured Module A/B evidence,
explanations, reports, the model registry and reproducibility metadata.
"""

from __future__ import annotations

from backend.app.main import app, create_app

__all__ = ["app", "create_app"]
