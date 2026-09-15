"""Repositories - the only code in the service that knows SQL.

One class per aggregate. Services call these; routes never do. This is the
seam where another database engine would be implemented, and the reason the
rest of the backend has no `sqlite3` import in it.

`AuditRepository` is append-only by construction: it exposes `record()` and
readers, and no update or delete. An audit trail you can edit is not one.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from backend.app.models.database_models import (
    connect, dumps, loads, row_to_dict,
)

__all__ = [
    "utc_now", "new_id",
    "DatasetRepository", "ScreeningRepository", "ComponentRepository",
    "AuditRepository", "JobRepository", "ModelRepository",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class _Repo:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)

    def _all(self, sql: str, params: Iterable = ()) -> list[dict]:
        with connect(self.db_path) as c:
            return [row_to_dict(r) for r in c.execute(sql, tuple(params))]

    def _one(self, sql: str, params: Iterable = ()) -> dict | None:
        with connect(self.db_path) as c:
            return row_to_dict(c.execute(sql, tuple(params)).fetchone())

    def _exec(self, sql: str, params: Iterable = ()) -> None:
        with connect(self.db_path) as c:
            c.execute(sql, tuple(params))


# --------------------------------------------------------------- datasets
class DatasetRepository(_Repo):
    def create(self, *, filename: str, stored_path: str, sha256: str,
               row_count: int, lot_count: int, read_points: list[int],
               schema_version: int, validation: dict, source: str = "upload",
               adapter: str | None = None, actor: str | None = None) -> str:
        dataset_id = new_id("ds")
        self._exec(
            """INSERT INTO datasets(dataset_id, filename, stored_path, sha256,
               uploaded_at, row_count, lot_count, read_points, schema_version,
               validation, source, adapter, actor)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (dataset_id, filename, stored_path, sha256, utc_now(), row_count,
             lot_count, dumps(read_points), schema_version, dumps(validation),
             source, adapter, actor))
        return dataset_id

    def get(self, dataset_id: str) -> dict | None:
        row = self._one("SELECT * FROM datasets WHERE dataset_id = ?", (dataset_id,))
        if row:
            row["read_points"] = loads(row["read_points"], [])
            row["validation"] = loads(row["validation"], {})
        return row

    def find_by_sha(self, sha256: str) -> dict | None:
        """Content-addressed lookup, so re-uploading the same file is cheap
        and two runs on identical bytes share a dataset id."""
        return self._one(
            "SELECT * FROM datasets WHERE sha256 = ? ORDER BY uploaded_at LIMIT 1",
            (sha256,))

    def list(self, limit: int = 50) -> list[dict]:
        return self._all(
            """SELECT dataset_id, filename, sha256, uploaded_at, row_count,
                      lot_count, source, adapter
               FROM datasets ORDER BY uploaded_at DESC LIMIT ?""", (limit,))


# --------------------------------------------------------- screening runs
class ScreeningRepository(_Repo):
    def create(self, *, dataset_id: str, dataset_sha256: str,
               pipeline_version: str, model_version: str, feature_version: str,
               policy_version: str, config_hash: str, config: dict,
               actor: str | None = None) -> str:
        run_id = new_id("run")
        self._exec(
            """INSERT INTO screening_runs(run_id, dataset_id, dataset_sha256,
               status, pipeline_version, model_version, feature_version,
               policy_version, config_hash, config, actor)
               VALUES(?,?,?,'QUEUED',?,?,?,?,?,?,?)""",
            (run_id, dataset_id, dataset_sha256, pipeline_version, model_version,
             feature_version, policy_version, config_hash, dumps(config), actor))
        return run_id

    def mark_running(self, run_id: str) -> None:
        self._exec(
            "UPDATE screening_runs SET status='RUNNING', started_at=? WHERE run_id=?",
            (utc_now(), run_id))

    def mark_completed(self, run_id: str, *, duration_s: float, bands: dict,
                       summary: dict, row_count: int,
                       forecast_out_of_fold: bool, module_b_available: bool,
                       model_artifact_id: str | None,
                       model_sha256: str | None) -> None:
        self._exec(
            """UPDATE screening_runs
               SET status='COMPLETED', completed_at=?, duration_s=?, bands=?,
                   summary=?, row_count=?, forecast_out_of_fold=?,
                   module_b_available=?, model_artifact_id=?, model_sha256=?
               WHERE run_id=?""",
            (utc_now(), duration_s, dumps(bands), dumps(summary), row_count,
             int(forecast_out_of_fold), int(module_b_available),
             model_artifact_id, model_sha256, run_id))

    def mark_failed(self, run_id: str, error: str) -> None:
        self._exec(
            """UPDATE screening_runs SET status='FAILED', completed_at=?, error=?
               WHERE run_id=?""", (utc_now(), error[:2000], run_id))

    def get(self, run_id: str) -> dict | None:
        row = self._one("SELECT * FROM screening_runs WHERE run_id=?", (run_id,))
        if row:
            row["config"] = loads(row["config"], {})
            row["bands"] = loads(row["bands"], {})
            row["summary"] = loads(row["summary"], {})
            row["forecast_out_of_fold"] = bool(row["forecast_out_of_fold"])
            row["module_b_available"] = bool(row["module_b_available"])
        return row

    def list(self, limit: int = 50) -> list[dict]:
        rows = self._all(
            """SELECT run_id, dataset_id, status, started_at, completed_at,
                      duration_s, row_count, summary, model_version, policy_version
               FROM screening_runs ORDER BY COALESCE(started_at, run_id) DESC
               LIMIT ?""", (limit,))
        for r in rows:
            r["summary"] = loads(r["summary"], {})
        return rows


# ----------------------------------------------------- component results
class ComponentRepository(_Repo):
    def bulk_insert(self, run_id: str, rows: list[dict]) -> int:
        """One executemany per run. 2,100 parts is a single statement."""
        payload = [
            (run_id, r["serial"], r["lot"], r.get("wafer"),
             float(r["risk_score"]), r["verdict"], int(r.get("static_breach", 0)),
             r.get("module_a_score"), r.get("module_a_pooled"),
             r.get("module_b_score"),
             dumps(r.get("predicted_168h")), dumps(r.get("prediction_upper")),
             dumps(r["sub_scores"]), dumps(r.get("evidence")),
             dumps(r.get("explanation")), dumps(r.get("reason_codes", [])))
            for r in rows
        ]
        with connect(self.db_path) as c:
            c.executemany(
                """INSERT OR REPLACE INTO component_results(
                       run_id, serial, lot, wafer, risk_score, verdict,
                       static_breach, module_a_score, module_a_pooled,
                       module_b_score, predicted_168h, prediction_upper,
                       sub_scores, evidence, explanation, reason_codes)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", payload)
        return len(payload)

    @staticmethod
    def _hydrate(row: dict) -> dict:
        for k in ("predicted_168h", "prediction_upper", "sub_scores",
                  "evidence", "explanation", "reason_codes"):
            row[k] = loads(row.get(k))
        row["static_breach"] = bool(row.get("static_breach"))
        return row

    def get(self, run_id: str, serial: str) -> dict | None:
        row = self._one(
            "SELECT * FROM component_results WHERE run_id=? AND serial=?",
            (run_id, serial))
        return self._hydrate(row) if row else None

    def list(self, run_id: str, *, verdict: str | None = None,
             lot: str | None = None, limit: int = 200,
             offset: int = 0) -> list[dict]:
        sql = ["SELECT * FROM component_results WHERE run_id=?"]
        params: list[Any] = [run_id]
        if verdict:
            sql.append("AND verdict=?")
            params.append(verdict)
        if lot:
            sql.append("AND lot=?")
            params.append(lot)
        sql.append("ORDER BY risk_score DESC LIMIT ? OFFSET ?")
        params += [limit, offset]
        return [self._hydrate(r) for r in self._all(" ".join(sql), params)]

    def count(self, run_id: str) -> int:
        row = self._one(
            "SELECT COUNT(*) AS n FROM component_results WHERE run_id=?", (run_id,))
        return int(row["n"]) if row else 0

    def lot_summary(self, run_id: str) -> list[dict]:
        return self._all(
            """SELECT lot,
                      COUNT(*) AS parts,
                      SUM(verdict='REJECT') AS reject,
                      SUM(verdict='WATCH')  AS watch,
                      SUM(verdict='ACCEPT') AS accept,
                      ROUND(AVG(risk_score), 2) AS mean_risk
               FROM component_results WHERE run_id=?
               GROUP BY lot ORDER BY lot""", (run_id,))


# ------------------------------------------------------------- audit log
class AuditRepository(_Repo):
    """Append-only. There is deliberately no update or delete method."""

    def record(self, event_type: str, *, run_id: str | None = None,
               dataset_id: str | None = None, serial: str | None = None,
               actor: str | None = None, metadata: dict | None = None) -> str:
        event_id = new_id("evt")
        self._exec(
            """INSERT INTO audit_events(event_id, run_id, dataset_id, serial,
               event_type, timestamp, actor, metadata) VALUES(?,?,?,?,?,?,?,?)""",
            (event_id, run_id, dataset_id, serial, event_type, utc_now(),
             actor, dumps(metadata or {})))
        return event_id

    def for_run(self, run_id: str, limit: int = 200) -> list[dict]:
        rows = self._all(
            """SELECT * FROM audit_events WHERE run_id=?
               ORDER BY timestamp, event_id LIMIT ?""", (run_id, limit))
        for r in rows:
            r["metadata"] = loads(r["metadata"], {})
        return rows

    def for_serial(self, serial: str, limit: int = 100) -> list[dict]:
        rows = self._all(
            """SELECT * FROM audit_events WHERE serial=?
               ORDER BY timestamp DESC LIMIT ?""", (serial, limit))
        for r in rows:
            r["metadata"] = loads(r["metadata"], {})
        return rows


# ------------------------------------------------------------------ jobs
class JobRepository(_Repo):
    def create(self, job_type: str, *, dataset_id: str | None = None,
               run_id: str | None = None, actor: str | None = None) -> str:
        job_id = new_id("job")
        self._exec(
            """INSERT INTO jobs(job_id, job_type, status, run_id, dataset_id,
               created_at, actor) VALUES(?,?,'QUEUED',?,?,?,?)""",
            (job_id, job_type, run_id, dataset_id, utc_now(), actor))
        return job_id

    def mark_running(self, job_id: str) -> None:
        self._exec("UPDATE jobs SET status='RUNNING', started_at=? WHERE job_id=?",
                   (utc_now(), job_id))

    def mark_completed(self, job_id: str, run_id: str | None = None) -> None:
        self._exec(
            """UPDATE jobs SET status='COMPLETED', completed_at=?,
               run_id=COALESCE(?, run_id) WHERE job_id=?""",
            (utc_now(), run_id, job_id))

    def mark_failed(self, job_id: str, error: str, error_code: str) -> None:
        self._exec(
            """UPDATE jobs SET status='FAILED', completed_at=?, error=?,
               error_code=? WHERE job_id=?""",
            (utc_now(), error[:2000], error_code, job_id))

    def get(self, job_id: str) -> dict | None:
        return self._one("SELECT * FROM jobs WHERE job_id=?", (job_id,))

    def list(self, limit: int = 50) -> list[dict]:
        return self._all(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))


# -------------------------------------------------------- model registry
class ModelRepository(_Repo):
    def create(self, *, model_version: str, model_name: str, model_type: str,
               training_dataset_sha: str, training_rows: int,
               feature_version: str, hyperparameters: dict, random_seed: int,
               metrics: dict | None, exponents: dict | None,
               artifact_path: str, artifact_sha256: str,
               activate: bool = True) -> str:
        artifact_id = new_id("mdl")
        with connect(self.db_path) as c:
            if activate:
                c.execute("UPDATE model_artifacts SET is_active = 0")
            c.execute(
                """INSERT INTO model_artifacts(artifact_id, model_version,
                   model_name, model_type, created_at, training_dataset_sha,
                   training_rows, feature_version, hyperparameters, random_seed,
                   metrics, exponents, artifact_path, artifact_sha256, is_active)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (artifact_id, model_version, model_name, model_type, utc_now(),
                 training_dataset_sha, training_rows, feature_version,
                 dumps(hyperparameters), random_seed, dumps(metrics),
                 dumps(exponents), artifact_path, artifact_sha256, int(activate)))
        return artifact_id

    @staticmethod
    def _hydrate(row: dict | None) -> dict | None:
        if not row:
            return None
        for k in ("hyperparameters", "metrics", "exponents"):
            row[k] = loads(row.get(k))
        row["is_active"] = bool(row["is_active"])
        return row

    def active(self) -> dict | None:
        return self._hydrate(self._one(
            "SELECT * FROM model_artifacts WHERE is_active=1 "
            "ORDER BY created_at DESC LIMIT 1"))

    def get(self, artifact_id: str) -> dict | None:
        return self._hydrate(self._one(
            "SELECT * FROM model_artifacts WHERE artifact_id=?", (artifact_id,)))

    def list(self, limit: int = 20) -> list[dict]:
        return [self._hydrate(r) for r in self._all(
            "SELECT * FROM model_artifacts ORDER BY created_at DESC LIMIT ?",
            (limit,))]
