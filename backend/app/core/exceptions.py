"""Domain exceptions and the one error envelope every endpoint returns.

A client must never receive a bare Python traceback or a FastAPI default body.
Every failure leaves this service as:

    {"error": {"code": "...", "message": "...", "details": [...],
               "request_id": "..."}}

`code` is a stable machine-readable string; `message` is written for an
engineer reading a screen; `details` carries per-field validation findings.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "SentinelError", "DatasetValidationError", "ScreeningError",
    "ModelInferenceError", "ReportGenerationError", "NotFoundError",
    "ConflictError", "PayloadTooLargeError", "AuthError",
    "error_envelope",
]


class SentinelError(Exception):
    """Base for everything this service raises deliberately.

    `status_code` is the HTTP status the API layer maps it to, so the mapping
    lives with the error rather than in a chain of isinstance checks.
    """

    code = "INTERNAL_ERROR"
    status_code = 500

    def __init__(self, message: str, details: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or []

    def envelope(self, request_id: str | None = None) -> dict:
        return error_envelope(self.code, self.message, self.details, request_id)


class DatasetValidationError(SentinelError):
    """The uploaded frame cannot be screened safely.

    Raised only for blocking ERRORS. Warnings never raise - they travel with
    the validation report so an operator can decide.
    """

    code = "DATASET_SCHEMA_INVALID"
    status_code = 422


class ScreeningError(SentinelError):
    code = "SCREENING_FAILED"
    status_code = 500


class ModelInferenceError(SentinelError):
    code = "MODEL_INFERENCE_FAILED"
    status_code = 500


class ReportGenerationError(SentinelError):
    code = "REPORT_GENERATION_FAILED"
    status_code = 500


class NotFoundError(SentinelError):
    code = "NOT_FOUND"
    status_code = 404


class ConflictError(SentinelError):
    """The resource exists but is not in a state that allows this operation."""

    code = "CONFLICT"
    status_code = 409


class PayloadTooLargeError(SentinelError):
    code = "PAYLOAD_TOO_LARGE"
    status_code = 413


class AuthError(SentinelError):
    code = "UNAUTHORIZED"
    status_code = 401


def error_envelope(code: str, message: str,
                   details: list[dict[str, Any]] | None = None,
                   request_id: str | None = None) -> dict:
    body: dict[str, Any] = {"code": code, "message": message,
                            "details": details or []}
    if request_id:
        body["request_id"] = request_id
    return {"error": body}
