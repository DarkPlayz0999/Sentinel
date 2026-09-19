"""SQLite schema and connection handling.

Why stdlib `sqlite3` and not an ORM: the schema is six tables with no
relationships more complex than a foreign key, the queries are
select-by-id and select-by-run, and every write is an append. An ORM would add
a dependency and a mapping layer to buy nothing. The REPOSITORY classes are
the abstraction (rule: API -> service -> repository -> database); swapping to
Postgres means reimplementing those, which is a contained, honest amount of
work and is where that seam belongs.

Concurrency: the API runs screening jobs in FastAPI's threadpool, so a
connection is opened per operation with `check_same_thread=False`, WAL enabled
for concurrent readers, and a busy timeout so a background write never makes a
reader fail outright.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

__all__ = ["SCHEMA_VERSION", "connect", "init_db", "row_to_dict", "dumps", "loads"]

SCHEMA_VERSION = 1

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);

-- An uploaded (or built-in) burn-in data log. `sha256` is the content hash
-- that makes a screening run reproducible; `stored_path` is a leaf name inside
-- the configured upload directory, never a client-supplied path.
CREATE TABLE IF NOT EXISTS datasets (
    dataset_id      TEXT PRIMARY KEY,
    filename        TEXT NOT NULL,
    stored_path     TEXT NOT NULL,
    sha256          TEXT NOT NULL,
    uploaded_at     TEXT NOT NULL,
    row_count       INTEGER NOT NULL,
    lot_count       INTEGER NOT NULL,
    read_points     TEXT NOT NULL,          -- JSON [0,24,96,168]
    schema_version  INTEGER NOT NULL,
    validation      TEXT NOT NULL,          -- JSON ValidationReport
    source          TEXT NOT NULL DEFAULT 'upload',
    adapter         TEXT,                   -- non-null when normalised by an adapter
    actor           TEXT
);
CREATE INDEX IF NOT EXISTS idx_datasets_sha ON datasets(sha256);

-- One execution of the screen. Everything needed to reproduce it is here.
CREATE TABLE IF NOT EXISTS screening_runs (
    run_id            TEXT PRIMARY KEY,
    dataset_id        TEXT NOT NULL REFERENCES datasets(dataset_id),
    dataset_sha256    TEXT NOT NULL,
    status            TEXT NOT NULL,        -- QUEUED RUNNING COMPLETED FAILED
    started_at        TEXT,
    completed_at      TEXT,
    duration_s        REAL,
    pipeline_version  TEXT NOT NULL,
    model_version     TEXT NOT NULL,
    feature_version   TEXT NOT NULL,
    policy_version    TEXT NOT NULL,
    config_hash       TEXT NOT NULL,
    config            TEXT NOT NULL,        -- JSON effective policy
    model_artifact_id TEXT,                 -- NULL when fitted in-run
    model_sha256      TEXT,
    forecast_out_of_fold INTEGER NOT NULL DEFAULT 0,
    module_b_available   INTEGER NOT NULL DEFAULT 0,
    bands             TEXT,                 -- JSON {watch, reject}
    summary           TEXT,                 -- JSON verdict counts
    row_count         INTEGER,
    error             TEXT,
    actor             TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_dataset ON screening_runs(dataset_id);
CREATE INDEX IF NOT EXISTS idx_runs_status  ON screening_runs(status);

-- Per-component outcome. One row per part per run.
CREATE TABLE IF NOT EXISTS component_results (
    run_id            TEXT NOT NULL REFERENCES screening_runs(run_id),
    serial            TEXT NOT NULL,
    lot               TEXT NOT NULL,
    wafer             TEXT,
    risk_score        REAL NOT NULL,
    verdict           TEXT NOT NULL,
    static_breach     INTEGER NOT NULL DEFAULT 0,
    module_a_score    REAL,                 -- L2 worst-case robust |z|
    module_a_pooled   REAL,                 -- L3 pooled evidence
    module_b_score    REAL,                 -- worst safety-slope ratio
    predicted_168h    TEXT,                 -- JSON per parameter
    prediction_upper  TEXT,                 -- JSON per parameter
    sub_scores        TEXT NOT NULL,        -- JSON five named sub-scores
    evidence          TEXT,                 -- JSON structured Module A/B evidence
    explanation       TEXT,                 -- JSON primary + supporting reasons
    reason_codes      TEXT NOT NULL,        -- JSON list
    PRIMARY KEY (run_id, serial)
);
CREATE INDEX IF NOT EXISTS idx_results_run_verdict ON component_results(run_id, verdict);
CREATE INDEX IF NOT EXISTS idx_results_run_risk    ON component_results(run_id, risk_score DESC);
CREATE INDEX IF NOT EXISTS idx_results_serial      ON component_results(serial);

-- Append-only. Nothing in this table is ever updated or deleted.
CREATE TABLE IF NOT EXISTS audit_events (
    event_id    TEXT PRIMARY KEY,
    run_id      TEXT,
    dataset_id  TEXT,
    serial      TEXT,
    event_type  TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    actor       TEXT,
    metadata    TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_run  ON audit_events(run_id);
CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_events(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_events(timestamp);

-- Background screening jobs.
CREATE TABLE IF NOT EXISTS jobs (
    job_id       TEXT PRIMARY KEY,
    job_type     TEXT NOT NULL,
    status       TEXT NOT NULL,             -- QUEUED RUNNING COMPLETED FAILED
    run_id       TEXT,
    dataset_id   TEXT,
    created_at   TEXT NOT NULL,
    started_at   TEXT,
    completed_at TEXT,
    error        TEXT,
    error_code   TEXT,
    progress     TEXT,
    actor        TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

-- A trained, persisted forecaster. Inference loads one of these instead of
-- refitting LightGBM on every request.
CREATE TABLE IF NOT EXISTS model_artifacts (
    artifact_id           TEXT PRIMARY KEY,
    model_version         TEXT NOT NULL,
    model_name            TEXT NOT NULL,
    model_type            TEXT NOT NULL,
    created_at            TEXT NOT NULL,
    training_dataset_sha  TEXT NOT NULL,
    training_rows         INTEGER,
    feature_version       TEXT NOT NULL,
    hyperparameters       TEXT NOT NULL,    -- JSON
    random_seed           INTEGER NOT NULL,
    metrics               TEXT,             -- JSON out-of-fold MAE vs baselines
    exponents             TEXT,             -- JSON fitted power-law exponents
    artifact_path         TEXT NOT NULL,
    artifact_sha256       TEXT NOT NULL,
    is_active             INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_artifacts_active ON model_artifacts(is_active);
"""


def dumps(obj: Any) -> str:
    """JSON for a TEXT column. Compact, and NaN never reaches the database."""
    def clean(o):
        if isinstance(o, float):
            return None if o != o or o in (float("inf"), float("-inf")) else o
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [clean(v) for v in o]
        return o
    return json.dumps(clean(obj), separators=(",", ":"), default=str)


def loads(raw: str | None, default: Any = None) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return None if row is None else {k: row[k] for k in row.keys()}


@contextmanager
def connect(db_path: Path | str) -> Iterator[sqlite3.Connection]:
    """A transactional connection. Commits on success, rolls back on error."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | str) -> None:
    """Create the schema if absent. Safe to call on every start."""
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SCHEMA_VERSION),))
