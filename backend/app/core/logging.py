"""Structured logging.

One line per event, key=value, greppable. Screening runs log a start and a
completion with counts and duration; nothing logs a measurement, a serial list
or an uploaded file's contents by default - the payload is customer process
data and it does not belong in a log file.

Deliberately stdlib `logging` rather than structlog: the value here is the
event vocabulary and the discipline about what is NOT logged, and a dependency
adds neither.
"""

from __future__ import annotations

import logging
import sys
import time
import uuid
from contextlib import contextmanager
from typing import Any

__all__ = ["configure_logging", "get_logger", "log_event", "timed", "new_request_id"]

_CONFIGURED = False


def configure_logging(level: str = "INFO") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))
    root = logging.getLogger("sentinel")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str = "sentinel") -> logging.Logger:
    return logging.getLogger(name if name.startswith("sentinel") else f"sentinel.{name}")


def _fmt(value: Any) -> str:
    s = "-" if value is None else str(value)
    return f'"{s}"' if " " in s else s


def log_event(event: str, logger: logging.Logger | None = None,
              level: int = logging.INFO, **fields: Any) -> None:
    """Emit one structured event.

    Field values are stringified and quoted only when they contain a space, so
    the output stays scannable by eye and parseable by `cut`/`awk`.
    """
    log = logger or get_logger()
    pairs = " ".join(f"{k}={_fmt(v)}" for k, v in fields.items() if v is not None)
    log.log(level, f"{event} {pairs}".rstrip())


@contextmanager
def timed(event: str, logger: logging.Logger | None = None, **fields: Any):
    """Log `<event>_STARTED` / `<event>_COMPLETED` with a duration.

    On failure logs `<event>_FAILED` with the exception TYPE only - the message
    may quote uploaded data, and a log line is the wrong place for it.
    """
    log = logger or get_logger()
    t0 = time.perf_counter()
    log_event(f"{event}_STARTED", log, **fields)
    try:
        yield
    except Exception as exc:
        log_event(f"{event}_FAILED", log, level=logging.ERROR,
                  duration_s=round(time.perf_counter() - t0, 3),
                  error_type=type(exc).__name__, **fields)
        raise
    log_event(f"{event}_COMPLETED", log,
              duration_s=round(time.perf_counter() - t0, 3), **fields)


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]
