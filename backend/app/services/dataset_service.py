"""Dataset ingestion: receive bytes, validate, hash, store, register.

Order matters and is deliberate:

    size check -> parse -> validate -> hash -> store -> register

Nothing is written to disk and no dataset row is created until validation
passes. An invalid upload leaves no trace but an audit event, which is what
"do not run the ML pipeline until validation passes" requires.

Storage is content-addressed: the file lands at `<sha256>.csv` inside the
configured upload directory. A client filename never reaches the filesystem -
it is recorded in the database as a label only. Re-uploading identical bytes
returns the existing dataset instead of duplicating it.
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

from backend.app.core.config import Settings, get_settings
from backend.app.core.exceptions import DatasetValidationError, NotFoundError
from backend.app.core.logging import get_logger, log_event
from backend.app.core.security import enforce_upload_size, safe_filename
from backend.app.ml.inference import dataframe_sha256
from backend.app.models.database_models import SCHEMA_VERSION
from backend.app.repositories.repositories import (
    AuditRepository, DatasetRepository,
)
from backend.app.validation.dataset_validator import (
    ValidationReport, validate_dataset,
)

__all__ = ["DatasetService"]

log = get_logger("dataset")


class DatasetService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.settings.ensure_dirs()
        db = self.settings.sqlite_path
        self.datasets = DatasetRepository(db)
        self.audit = AuditRepository(db)

    # ------------------------------------------------------------- parse
    def parse_csv(self, raw: bytes) -> pd.DataFrame:
        """Parse uploaded bytes into a frame, with a readable failure.

        `low_memory=False` so pandas does not infer a column's dtype from the
        first chunk alone - a text value late in a numeric column would
        otherwise change the dtype silently and hide from the validator.
        """
        enforce_upload_size(len(raw), self.settings)
        if not raw.strip():
            raise DatasetValidationError(
                "The uploaded file is empty.",
                [{"field": "file", "error_code": "EMPTY_FILE",
                  "message": "no bytes received"}])
        try:
            df = pd.read_csv(io.BytesIO(raw), low_memory=False)
        except Exception as exc:
            raise DatasetValidationError(
                "The file could not be parsed as CSV.",
                [{"field": "file", "error_code": "MALFORMED_CSV",
                  "message": str(exc)[:300]}]) from exc

        if len(df) > self.settings.max_upload_rows:
            raise DatasetValidationError(
                f"The file has {len(df):,} rows; the limit is "
                f"{self.settings.max_upload_rows:,}.",
                [{"field": "file", "error_code": "TOO_MANY_ROWS",
                  "message": f"max {self.settings.max_upload_rows} rows"}])
        return df

    # ---------------------------------------------------------- validate
    @staticmethod
    def validate(df: pd.DataFrame) -> ValidationReport:
        return validate_dataset(df)

    # ------------------------------------------------------------ ingest
    def ingest(self, raw: bytes, filename: str | None, *,
               actor: str | None = None, source: str = "upload",
               adapter: str | None = None) -> dict:
        """Full ingestion. Raises DatasetValidationError on any blocking error."""
        label = safe_filename(filename)
        df = self.parse_csv(raw)
        report = self.validate(df)

        if not report.ok:
            self.audit.record(
                "DATASET_REJECTED", actor=actor,
                metadata={"filename": label, "rows": report.rows,
                          "error_codes": [f.error_code for f in report.errors]})
            log_event("DATASET_REJECTED", log, filename=label, rows=report.rows,
                      errors=len(report.errors))
            raise DatasetValidationError(
                "The dataset cannot be screened: "
                f"{len(report.errors)} blocking validation error(s).",
                [f.as_dict() for f in report.errors])

        # Hash the PARSED frame, not the raw bytes: two exports of the same
        # measurements differing only in row order or float formatting are the
        # same dataset, and a screening run on either is the same run.
        sha = dataframe_sha256(df)
        existing = self.datasets.find_by_sha(sha)
        if existing:
            self.audit.record("DATASET_DEDUPLICATED",
                              dataset_id=existing["dataset_id"], actor=actor,
                              metadata={"filename": label, "sha256": sha})
            log_event("DATASET_DEDUPLICATED", log,
                      dataset_id=existing["dataset_id"], sha256=sha[:16])
            out = dict(report.as_dict())
            out.update(dataset_id=existing["dataset_id"], sha256=sha,
                       filename=existing["filename"], deduplicated=True)
            return out

        stored = f"{sha}.csv"
        (Path(self.settings.upload_dir) / stored).write_bytes(raw)

        dataset_id = self.datasets.create(
            filename=label, stored_path=stored, sha256=sha,
            row_count=report.rows, lot_count=report.lots,
            read_points=report.read_points, schema_version=SCHEMA_VERSION,
            validation=report.as_dict(), source=source, adapter=adapter,
            actor=actor)

        self.audit.record("DATASET_UPLOADED", dataset_id=dataset_id, actor=actor,
                          metadata={"filename": label, "sha256": sha,
                                    "rows": report.rows, "lots": report.lots,
                                    "warnings": len(report.warnings)})
        log_event("DATASET_UPLOADED", log, dataset_id=dataset_id,
                  rows=report.rows, lots=report.lots, sha256=sha[:16],
                  warnings=len(report.warnings))

        out = dict(report.as_dict())
        out.update(dataset_id=dataset_id, sha256=sha, filename=label,
                   deduplicated=False)
        return out

    # ------------------------------------------------------------ access
    def get(self, dataset_id: str) -> dict:
        row = self.datasets.get(dataset_id)
        if not row:
            raise NotFoundError(f"No dataset with id {dataset_id!r}.")
        return row

    def load_frame(self, dataset_id: str) -> pd.DataFrame:
        """Re-read the stored bytes for a dataset.

        The path is rebuilt from the configured directory plus the stored leaf
        name; the database value is never used as a path directly, so a row
        edited to contain a traversal cannot escape the upload directory.
        """
        row = self.get(dataset_id)
        path = Path(self.settings.upload_dir) / Path(row["stored_path"]).name
        if not path.exists():
            raise NotFoundError(
                f"The stored file for dataset {dataset_id!r} is missing.")
        return pd.read_csv(path, low_memory=False)

    def register_local_frame(self, df: pd.DataFrame, label: str, *,
                             actor: str | None = None,
                             source: str = "builtin") -> dict:
        """Register a frame this process already holds (the shipped dataset).

        Used so the built-in demo dataset participates in the same run,
        audit and reproducibility machinery as an upload, rather than being a
        special case that bypasses it.
        """
        raw = df.to_csv(index=False).encode("utf-8")
        return self.ingest(raw, label, actor=actor, source=source)

    def list(self, limit: int = 50) -> list[dict]:
        return self.datasets.list(limit)
