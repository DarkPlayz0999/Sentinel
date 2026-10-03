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

-- ---------------------------------------------------------------- agents
-- One execution of the agent team on one dataset. `idempotency_key` is the
-- hash of everything that decides the outcome (dataset, policy, model,
-- pipeline); a second request with the same key returns this workflow.
CREATE TABLE IF NOT EXISTS agent_workflows (
    workflow_id      TEXT PRIMARY KEY,
    idempotency_key  TEXT NOT NULL,
    trigger          TEXT NOT NULL,        -- manual | dataset_uploaded | ...
    dataset_id       TEXT NOT NULL REFERENCES datasets(dataset_id),
    data_class       TEXT,                 -- simulated | experimental | unknown
    run_id           TEXT,                 -- screening run, once combined
    status           TEXT NOT NULL,        -- QUEUED RUNNING COMPLETED QUARANTINED FAILED
    current_step     TEXT,
    created_at       TEXT NOT NULL,
    started_at       TEXT,
    completed_at     TEXT,
    duration_s       REAL,
    summary          TEXT,                 -- JSON
    error            TEXT,
    actor            TEXT
);
CREATE INDEX IF NOT EXISTS idx_wf_key    ON agent_workflows(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_wf_status ON agent_workflows(status);

-- One attempt of one agent. A retried agent has several rows.
CREATE TABLE IF NOT EXISTS agent_steps (
    step_id      TEXT PRIMARY KEY,
    workflow_id  TEXT NOT NULL REFERENCES agent_workflows(workflow_id),
    agent        TEXT NOT NULL,
    status       TEXT NOT NULL,            -- RUNNING COMPLETED FAILED
    attempt      INTEGER NOT NULL,
    started_at   TEXT NOT NULL,
    completed_at TEXT,
    duration_s   REAL,
    output       TEXT,                     -- JSON typed agent report
    error        TEXT
);
CREATE INDEX IF NOT EXISTS idx_steps_wf ON agent_steps(workflow_id);

CREATE TABLE IF NOT EXISTS agent_findings (
    finding_id   TEXT PRIMARY KEY,
    workflow_id  TEXT NOT NULL REFERENCES agent_workflows(workflow_id),
    agent        TEXT NOT NULL,
    severity     TEXT NOT NULL,            -- info warning error critical
    code         TEXT NOT NULL,
    message      TEXT NOT NULL,
    data         TEXT,                     -- JSON
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_findings_wf ON agent_findings(workflow_id);

-- Append-only change feed behind the SSE stream. The integer id is the
-- stream cursor (Last-Event-ID), so a reconnecting client misses nothing.
CREATE TABLE IF NOT EXISTS agent_events (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id  TEXT NOT NULL,
    kind         TEXT NOT NULL,            -- workflow | step | finding
    payload      TEXT NOT NULL,            -- JSON
    created_at   TEXT NOT NULL
);

-- ------------------------------------------------------------- digital twin
-- One simulated lot of boards (src/twin). Every table below carries the
-- simulation id, a timestamp, the twin software version and the random seed,
-- so any row can be traced back to the run that produced it and replayed.
CREATE TABLE IF NOT EXISTS simulation_runs (
    simulation_id    TEXT PRIMARY KEY,
    created_at       TEXT NOT NULL,
    updated_at       TEXT,
    status           TEXT NOT NULL,        -- CREATED QUEUED RUNNING SIMULATED SCREENING
                                           -- SCREENED INVESTIGATED FAILED SIMULATION_FAILED
    mode             TEXT NOT NULL,        -- VISIBLE | BLIND
    board_id         TEXT NOT NULL,
    lot_id           TEXT NOT NULL,
    boards           INTEGER NOT NULL,
    random_seed      INTEGER NOT NULL,
    config           TEXT NOT NULL,        -- JSON SimConfig without faults
    options          TEXT NOT NULL,        -- JSON: solver, auto_screen, monitor_z, label
    sim_time_h       REAL NOT NULL DEFAULT 0,
    software_version TEXT NOT NULL,
    model_version    TEXT NOT NULL,
    dataset_id       TEXT,                 -- Sentinel dataset of the observed frame
    run_id           TEXT,                 -- Sentinel screening run
    workflow_id      TEXT,                 -- phase-1 agent workflow
    investigation_id TEXT,                 -- investigation agent workflow
    focus_serial     TEXT,                 -- the board Sentinel ranked first
    investigation    TEXT,                 -- JSON report
    job_id           TEXT,
    revealed_at      TEXT,
    error            TEXT,                 -- JSON, e.g. a SIMULATION_FAILED record
    actor            TEXT
);

CREATE TABLE IF NOT EXISTS simulation_components (
    simulation_id    TEXT NOT NULL REFERENCES simulation_runs(simulation_id),
    phase            TEXT NOT NULL,        -- burn-in-1 | rework-N
    board_serial     TEXT NOT NULL,
    component_id     TEXT NOT NULL,
    component_model  TEXT NOT NULL,
    kind             TEXT NOT NULL,
    as_built         TEXT NOT NULL,        -- JSON: ground truth
    state            TEXT NOT NULL,        -- JSON per read point: ground truth
    timestamp        TEXT NOT NULL,
    software_version TEXT NOT NULL,
    random_seed      INTEGER NOT NULL,
    PRIMARY KEY (simulation_id, phase, board_serial, component_id)
);

-- OBSERVED values only: ATE reads (component_id NULL) and IR camera reads.
CREATE TABLE IF NOT EXISTS simulation_measurements (
    simulation_id      TEXT NOT NULL REFERENCES simulation_runs(simulation_id),
    phase              TEXT NOT NULL,
    board_serial       TEXT NOT NULL,
    component_id       TEXT,
    time_h             REAL NOT NULL,
    parameter          TEXT NOT NULL,
    value              REAL,
    unit               TEXT NOT NULL,
    measurement_source TEXT NOT NULL,      -- SPICE PHYSICS_MODEL SYNTHETIC DATASET
    solver             TEXT,
    timestamp          TEXT NOT NULL,
    software_version   TEXT NOT NULL,
    random_seed        INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_simmeas ON simulation_measurements(simulation_id, board_serial);

CREATE TABLE IF NOT EXISTS simulation_faults (
    fault_id         TEXT PRIMARY KEY,
    simulation_id    TEXT NOT NULL REFERENCES simulation_runs(simulation_id),
    board_serial     TEXT NOT NULL,
    board_index      INTEGER NOT NULL,
    component_id     TEXT NOT NULL,
    fault_type       TEXT NOT NULL,
    severity         REAL NOT NULL,
    start_h          REAL NOT NULL,
    growth_rate      REAL NOT NULL,
    source           TEXT NOT NULL,        -- injected | hidden-random | replacement part
    timestamp        TEXT NOT NULL,
    software_version TEXT NOT NULL,
    random_seed      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_simfaults ON simulation_faults(simulation_id);

-- Kept apart from everything Sentinel or the agents read. Written once, read
-- only by reveal/benchmark after a prediction exists.
CREATE TABLE IF NOT EXISTS simulation_ground_truth (
    simulation_id    TEXT NOT NULL REFERENCES simulation_runs(simulation_id),
    phase            TEXT NOT NULL,
    board_serial     TEXT NOT NULL,
    component_id     TEXT,                 -- faulty component(s), comma-joined
    is_faulty        INTEGER NOT NULL,
    truth            TEXT NOT NULL,        -- JSON
    timestamp        TEXT NOT NULL,
    software_version TEXT NOT NULL,
    random_seed      INTEGER NOT NULL,
    PRIMARY KEY (simulation_id, phase, board_serial)
);

CREATE TABLE IF NOT EXISTS simulation_events (
    seq              INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id    TEXT NOT NULL,
    timestamp        TEXT NOT NULL,
    event_type       TEXT NOT NULL,
    board_serial     TEXT,
    component_id     TEXT,
    payload          TEXT NOT NULL,        -- JSON
    software_version TEXT NOT NULL,
    random_seed      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_simevents ON simulation_events(simulation_id, seq);

CREATE TABLE IF NOT EXISTS simulation_predictions (
    prediction_id    TEXT PRIMARY KEY,
    simulation_id    TEXT NOT NULL REFERENCES simulation_runs(simulation_id),
    phase            TEXT NOT NULL,
    read_h           INTEGER NOT NULL,     -- last read point the screen saw
    board_serial     TEXT NOT NULL,
    component_id     TEXT,                 -- suspect component, once diagnosed
    run_id           TEXT,
    dataset_id       TEXT,
    risk_score       REAL NOT NULL,
    verdict          TEXT NOT NULL,
    reason_codes     TEXT NOT NULL,        -- JSON
    model_version    TEXT NOT NULL,
    timestamp        TEXT NOT NULL,
    software_version TEXT NOT NULL,
    random_seed      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_simpred ON simulation_predictions(simulation_id, phase, read_h);

CREATE TABLE IF NOT EXISTS simulation_replacements (
    replacement_id   TEXT PRIMARY KEY,
    simulation_id    TEXT NOT NULL REFERENCES simulation_runs(simulation_id),
    phase            TEXT NOT NULL,        -- rework-N
    board_serial     TEXT NOT NULL,
    component_id     TEXT NOT NULL,
    candidate_id     TEXT NOT NULL,
    reel             TEXT NOT NULL,
    candidate        TEXT NOT NULL,        -- JSON public view: criteria and score
    hidden           TEXT NOT NULL,        -- JSON ground truth of the new part
    before           TEXT,                 -- JSON
    after            TEXT,                 -- JSON
    removed_bench    TEXT,                 -- JSON bench measurement of the pulled part
    outcome          TEXT,                 -- after-rerun verdict
    run_id           TEXT,
    dataset_id       TEXT,
    timestamp        TEXT NOT NULL,
    model_version    TEXT NOT NULL,
    software_version TEXT NOT NULL,
    random_seed      INTEGER NOT NULL,
    actor            TEXT
);
CREATE INDEX IF NOT EXISTS idx_simrepl ON simulation_replacements(simulation_id);

CREATE TABLE IF NOT EXISTS simulation_experiments (
    experiment_id    TEXT PRIMARY KEY,
    created_at       TEXT NOT NULL,
    completed_at     TEXT,
    status           TEXT NOT NULL,        -- QUEUED RUNNING COMPLETED FAILED
    kind             TEXT NOT NULL,
    spec             TEXT NOT NULL,        -- JSON
    random_seed      INTEGER NOT NULL,
    runs             INTEGER NOT NULL,
    progress         TEXT,                 -- JSON {done, total, cell}
    summary          TEXT,                 -- JSON
    artifact_path    TEXT,                 -- the benchmark dataset CSV
    job_id           TEXT,
    error            TEXT,
    model_version    TEXT NOT NULL,
    software_version TEXT NOT NULL,
    actor            TEXT
);
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


# The twin's tables are additive (CREATE ... IF NOT EXISTS inside SCHEMA), so
# an existing database gains them on the next start without a migration.


def init_db(db_path: Path | str) -> None:
    """Create the schema if absent. Safe to call on every start."""
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SCHEMA_VERSION),))
