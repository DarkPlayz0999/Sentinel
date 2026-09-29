"""Typed settings, and the effective-configuration hash every run records.

Policy lives here, not scattered through the source. The parameter registry
(units, USLs, log-transform flags) deliberately stays in `src/features.py` -
rule 8 makes that the single definition and duplicating a datasheet limit into
a config file would be a second place for it to be wrong. What lives here is
everything an *operator* may legitimately change between runs: cost ratio, PDA
budget, band policy, upload limits, storage locations, auth.

Every screening run persists `Settings.policy_fingerprint()`, so a decision can
always be replayed against the configuration that produced it.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

__all__ = ["Settings", "get_settings", "REPO_ROOT"]

REPO_ROOT = Path(__file__).resolve().parents[3]


def _env_str(key: str, default: str) -> str:
    v = os.environ.get(key)
    return default if v is None or v == "" else v


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be a number, got {raw!r}") from exc


def _env_int(key: str, default: int) -> int:
    return int(_env_float(key, float(default)))


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Effective configuration for one process.

    Fields marked POLICY take part in the policy fingerprint: changing one
    changes screening decisions, so a run made under a different value is not
    comparable. Fields marked OPERATIONAL (paths, limits, auth) do not - they
    change how the service is deployed, not what it decides.
    """

    # ---- POLICY ------------------------------------------------------
    # Cost of a missed latent defect against a scrapped good part. A miss is a
    # dead satellite; an over-reject is a $40 component. Never a magic number:
    # it is an operator decision and it is recorded with every run.
    c_fn: float = 100.0
    c_fp: float = 1.0
    # Percent Defective Allowable. Above this fraction rejected, the lot goes
    # to engineering review rather than shipping.
    pda_limit: float = 0.05
    # REJECT band is sized to this fraction of the population, so the screen
    # stays inside the PDA budget instead of chasing the raw cost optimum.
    target_reject_rate: float = 0.05
    # Module B rejects on this predicted quantile, not the point estimate: a
    # part is pulled only when even its optimistic forecast breaches.
    module_b_quantile: float = 0.90
    # Mission length behind the Arrhenius safety-slope gate.
    mission_years: float = 7.0
    # A high-severity reason code escalates the verdict to at least WATCH.
    # Mirrors the existing hard override in src/fusion.fuse(), where a
    # datasheet breach forces REJECT regardless of the weighted score: the
    # screen may ADD rejections, never remove them. Without this a component
    # can carry a high-severity finding (R-301, its forecast breaching the
    # safety slope) and still be dispositioned ACCEPT because its other four
    # sub-scores are clean - measured at 12 of 2,100 on the shipped dataset.
    # Shipping a part while holding a safety finding about it is the escape
    # this project exists to stop. WATCH consumes no PDA budget, so the
    # escalation costs no lot disposition.
    escalate_on_high_severity: bool = True
    policy_version: str = "policy-1.1.0"

    # ---- OPERATIONAL -------------------------------------------------
    database_url: str = ""          # resolved in __post_init__
    artifact_dir: str = ""
    upload_dir: str = ""
    report_dir: str = ""
    max_upload_bytes: int = 64 * 1024 * 1024
    max_upload_rows: int = 500_000
    # Empty disables auth. Set SENTINEL_API_KEY to require an X-API-Key header
    # on mutating endpoints. See core/security.py for why this is opt-in.
    api_key: str = ""
    cors_origin_regex: str = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
    # In production, internal exception text never reaches a client.
    debug: bool = False
    log_level: str = "INFO"
    # Screen inline rather than in the background below this row count.
    sync_screen_max_rows: int = 5_000

    _policy_fields: tuple = field(
        default=(
            "c_fn", "c_fp", "pda_limit", "target_reject_rate",
            "module_b_quantile", "mission_years", "policy_version",
            "escalate_on_high_severity",
        ),
        repr=False,
        compare=False,
    )

    @classmethod
    def from_env(cls) -> "Settings":
        var = REPO_ROOT / "var"
        return cls(
            c_fn=_env_float("SENTINEL_C_FN", 100.0),
            c_fp=_env_float("SENTINEL_C_FP", 1.0),
            pda_limit=_env_float("SENTINEL_PDA_LIMIT", 0.05),
            target_reject_rate=_env_float("SENTINEL_TARGET_REJECT_RATE", 0.05),
            module_b_quantile=_env_float("SENTINEL_MODULE_B_QUANTILE", 0.90),
            mission_years=_env_float("SENTINEL_MISSION_YEARS", 7.0),
            escalate_on_high_severity=_env_bool(
                "SENTINEL_ESCALATE_ON_HIGH_SEVERITY", True),
            policy_version=_env_str("SENTINEL_POLICY_VERSION", "policy-1.1.0"),
            database_url=_env_str("SENTINEL_DATABASE_URL",
                                  f"sqlite:///{var / 'sentinel.db'}"),
            artifact_dir=_env_str("SENTINEL_ARTIFACT_DIR", str(var / "artifacts")),
            upload_dir=_env_str("SENTINEL_UPLOAD_DIR", str(var / "uploads")),
            report_dir=_env_str("SENTINEL_REPORT_DIR", str(REPO_ROOT / "reports")),
            max_upload_bytes=_env_int("SENTINEL_MAX_UPLOAD_BYTES", 64 * 1024 * 1024),
            max_upload_rows=_env_int("SENTINEL_MAX_UPLOAD_ROWS", 500_000),
            api_key=_env_str("SENTINEL_API_KEY", ""),
            cors_origin_regex=_env_str(
                "SENTINEL_CORS_ORIGIN_REGEX",
                r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"),
            debug=_env_bool("SENTINEL_DEBUG", False),
            log_level=_env_str("SENTINEL_LOG_LEVEL", "INFO"),
            sync_screen_max_rows=_env_int("SENTINEL_SYNC_SCREEN_MAX_ROWS", 5_000),
        )

    # ------------------------------------------------------------ paths
    @property
    def sqlite_path(self) -> Path:
        """Filesystem path behind a sqlite:/// URL.

        Only sqlite is implemented. The repository layer is the seam where a
        Postgres driver would slot in; this property is what would move.
        """
        url = self.database_url
        if not url.startswith("sqlite:///"):
            raise ValueError(
                f"only sqlite:/// URLs are implemented, got {url!r}. The "
                "repositories in backend/app/repositories are the seam where "
                "another engine would be added."
            )
        return Path(url[len("sqlite:///"):])

    def ensure_dirs(self) -> None:
        for p in (self.sqlite_path.parent, Path(self.artifact_dir),
                  Path(self.upload_dir), Path(self.report_dir)):
            p.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------- policy fingerprint
    def policy_dict(self) -> dict:
        """Exactly the values that can change a verdict."""
        d = asdict(self)
        return {k: d[k] for k in self._policy_fields}

    def policy_fingerprint(self) -> str:
        """Stable hash of the decision-affecting configuration.

        Recorded on every run. Two runs with different fingerprints are not
        comparable even on identical data, and the reproducibility endpoint
        reports it so a reviewer can tell.
        """
        blob = json.dumps(self.policy_dict(), sort_keys=True, separators=(",", ":"))
        return "cfg-" + hashlib.sha256(blob.encode()).hexdigest()[:16]

    def public_dict(self) -> dict:
        """Settings safe to return over HTTP. Secrets never appear."""
        d = asdict(self)
        d.pop("api_key", None)
        d.pop("_policy_fields", None)
        d["api_key_configured"] = bool(self.api_key)
        d["policy_fingerprint"] = self.policy_fingerprint()
        return d


_cached: Settings | None = None


def get_settings(refresh: bool = False) -> Settings:
    """Process-wide settings. `refresh=True` re-reads the environment (tests)."""
    global _cached
    if _cached is None or refresh:
        _cached = Settings.from_env()
    return _cached
