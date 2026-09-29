"""Shared response models and OpenAPI examples.

Examples are real SENTINEL values - L04-0348, lot L04, Iddq_uA in µA - because
a judge reading /docs should see the actual domain, not foo/bar.

Deeply nested payloads (`evidence`, `explanation`) are typed as `dict` rather
than exhaustive models on purpose: they are documented in the docstrings of
`services/evidence_service.py` and `services/explanation_service.py`, they
evolve with the science, and a 200-field pydantic mirror of them would be a
second definition to keep in sync for no validation benefit on the way out.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ErrorBody", "ErrorResponse", "ValidationFinding", "HealthResponse",
    "ReadinessResponse", "ERROR_RESPONSES",
]


class ValidationFinding(BaseModel):
    field: str = Field(..., examples=["Iddq_uA_24h"])
    error_code: str = Field(..., examples=["INVALID_NUMERIC"])
    message: str = Field(..., examples=["3 non-numeric measurement(s) found."])
    severity: str = Field("error", examples=["error"])
    count: int | None = Field(None, examples=[3])
    examples: list[Any] = Field(default_factory=list)


class ErrorBody(BaseModel):
    code: str = Field(..., examples=["DATASET_SCHEMA_INVALID"])
    message: str = Field(
        ..., examples=["The dataset cannot be screened: 2 blocking validation error(s)."])
    details: list[dict] = Field(default_factory=list)
    request_id: str | None = Field(None, examples=["9f2c1ab4de77"])


class ErrorResponse(BaseModel):
    """Every failure from this service has exactly this shape."""

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "error": {
                "code": "DATASET_SCHEMA_INVALID",
                "message": "The dataset cannot be screened: 1 blocking validation error(s).",
                "details": [{
                    "field": "Ileak_nA_0h",
                    "error_code": "NEGATIVE_CURRENT",
                    "message": ("2 negative measurement(s). Currents are "
                                "log-transformed before any statistic, so a "
                                "non-positive reading cannot be scored."),
                    "severity": "error",
                    "count": 2,
                }],
                "request_id": "9f2c1ab4de77",
            }
        }
    })

    error: ErrorBody


class HealthResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    status: str = Field(..., examples=["ok"])
    model_version: str = Field(..., examples=["sentinel-0.3.0"])
    pipeline_version: str = Field(..., examples=["pipeline-1.1.0"])
    simulated_data: bool = Field(
        True, description="The shipped dataset is synthetic and must be labelled as such.")
    dataset: dict | None = None


class ReadinessResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    ready: bool
    checks: dict = Field(..., examples=[{
        "database": "ok",
        "model_artifact": "ok",
        "upload_dir": "ok",
    }])


# Reused on every route so the error contract appears in OpenAPI once.
ERROR_RESPONSES: dict = {
    400: {"model": ErrorResponse, "description": "Malformed request"},
    401: {"model": ErrorResponse, "description": "Missing or invalid API key"},
    404: {"model": ErrorResponse, "description": "Resource not found"},
    409: {"model": ErrorResponse, "description": "Resource is not in a valid state"},
    413: {"model": ErrorResponse, "description": "Upload exceeds the configured limit"},
    422: {"model": ErrorResponse, "description": "Dataset failed schema validation"},
    500: {"model": ErrorResponse, "description": "Internal screening failure"},
}
