"""Baseline security: API-key abstraction, safe filenames, upload limits.

Scope, stated honestly: this is a single-key shared-secret gate suitable for a
lab workstation or a demo box behind a firewall. It is NOT an identity system -
there are no users, roles, sessions or per-actor permissions, so the audit
trail records an `actor` string that is asserted by the caller, not proven.
A flight-lot deployment terminates this behind a real authenticating gateway
and passes an authenticated principal down.

Auth is OPT-IN (`SENTINEL_API_KEY` unset disables it) because the default
deployment is loopback-only and the existing test suite and the local UI must
keep working with no credential. When the key IS set it is required on every
mutating endpoint.
"""

from __future__ import annotations

import hmac
import re
import unicodedata
from pathlib import Path

from fastapi import Header, Request

from backend.app.core.config import Settings, get_settings
from backend.app.core.exceptions import AuthError, PayloadTooLargeError

__all__ = ["require_api_key", "safe_filename", "enforce_upload_size", "actor_from"]

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str | None, fallback: str = "upload.csv") -> str:
    """Reduce a client-supplied filename to a harmless leaf name.

    Strips any directory component, normalises unicode, collapses everything
    outside [A-Za-z0-9._-], and refuses names that would traverse. The result
    is only ever used as a leaf inside the configured upload directory - no
    client string is allowed to influence a path prefix.
    """
    if not name:
        return fallback
    leaf = Path(str(name)).name
    leaf = unicodedata.normalize("NFKD", leaf).encode("ascii", "ignore").decode()
    leaf = _SAFE.sub("_", leaf).strip("._-")
    if not leaf or leaf in {".", ".."}:
        return fallback
    return leaf[:120]


def enforce_upload_size(n_bytes: int, settings: Settings | None = None) -> None:
    s = settings or get_settings()
    if n_bytes > s.max_upload_bytes:
        raise PayloadTooLargeError(
            f"Upload is {n_bytes / 1e6:.1f} MB; the limit is "
            f"{s.max_upload_bytes / 1e6:.0f} MB.",
            [{"field": "file", "error_code": "FILE_TOO_LARGE",
              "message": f"max {s.max_upload_bytes} bytes"}],
        )


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """FastAPI dependency. No-op when no key is configured.

    Compared with `hmac.compare_digest` so the check does not leak the key
    through response timing.
    """
    configured = get_settings().api_key
    if not configured:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, configured):
        raise AuthError("A valid X-API-Key header is required for this operation.")


def actor_from(request: Request | None, x_actor: str | None = None) -> str:
    """Best-effort actor label for the audit trail.

    ASSERTED, NOT AUTHENTICATED - see the module docstring. Recorded so a run
    can be traced to a caller in a cooperative environment; it is not evidence.
    """
    if x_actor:
        return safe_filename(x_actor, fallback="unknown")[:64]
    if request is not None and request.client:
        return f"ip:{request.client.host}"
    return "unknown"
