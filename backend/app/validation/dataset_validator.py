"""Dataset validation: machine-readable findings, errors block, warnings do not.

Design rules, in order of importance:

1. NEVER silently repair dangerous data. A negative leakage current is a
   broken measurement, not a zero. This module reports; it does not coerce.
2. The parameter registry is `src.features.PARAMS` (rule 8). Units, USLs and
   the log-transform flag are read from it, never re-declared here - a second
   copy of a datasheet limit is a second place for it to be wrong.
3. Requirements follow what the PIPELINE actually needs, not an idealised
   schema. `src/pipeline.screen()` needs `serial`, `lot` and every parameter's
   0h read; it needs 24h for Module B's forecast features; 96h is genuinely
   optional (the generator drops ~1.2% of them as handler drops) and 168h
   being absent is a legitimate hour-24 triage frame, not an error.

Severity contract:
    ERROR   - screening is refused. The frame cannot be scored safely.
    WARNING - screening proceeds. The operator is told what was odd.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from src.features import LOT_COL, PARAM_NAMES, PARAMS, TIMEPOINTS

__all__ = [
    "Finding", "ValidationReport", "validate_dataset",
    "REQUIRED_ID_COLUMNS", "required_columns", "optional_columns",
    "MIN_LOT_POPULATION",
]

# Robust statistics need a population to be robust *against*. Below this the
# per-lot median and MAD are estimated from too few parts to mean anything, so
# the screen still runs but every lot-relative number is suspect.
MIN_LOT_POPULATION = 30

# Above this fraction of missing readings on one parameter, the lot statistics
# behind that parameter stop being trustworthy.
MAX_MISSING_FRACTION = 0.25

REQUIRED_ID_COLUMNS = ("serial", LOT_COL)

# Read points the pipeline requires to produce any verdict at all.
REQUIRED_HOURS = (0,)
# Read points Module B's forecast needs. Absent -> hour-24 path unavailable.
FORECAST_HOURS = (0, 24)

# Physically impossible or clearly mis-scaled readings, per parameter. These
# are sanity rails, NOT spec limits: the USL is a pass/fail threshold and a
# part above it is a legitimate gross failure the screen must see. A value
# beyond this multiple of the USL is a units or decimal-point mistake.
IMPLAUSIBLE_USL_MULTIPLE = 20.0


@dataclass(frozen=True)
class Finding:
    """One machine-readable validation result."""

    field: str
    error_code: str
    message: str
    severity: str = "error"          # "error" | "warning"
    count: int | None = None
    examples: list = field(default_factory=list)

    def as_dict(self) -> dict:
        d = asdict(self)
        return {k: v for k, v in d.items() if v not in (None, [])}


@dataclass
class ValidationReport:
    rows: int = 0
    lots: int = 0
    columns: list[str] = field(default_factory=list)
    read_points: list[int] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def module_b_available(self) -> bool:
        """Module B needs a 168h target to fit against, and 0h+24h to predict from."""
        return 168 in self.read_points and set(FORECAST_HOURS) <= set(self.read_points)

    def as_dict(self) -> dict:
        return {
            "status": "validated" if self.ok else "rejected",
            "rows": self.rows,
            "lots": self.lots,
            "read_points": self.read_points,
            "module_b_available": self.module_b_available,
            "errors": [f.as_dict() for f in self.errors],
            "warnings": [f.as_dict() for f in self.warnings],
        }


def required_columns() -> list[str]:
    """Minimum columns for any verdict: identity plus every parameter at 0h."""
    return list(REQUIRED_ID_COLUMNS) + [f"{p}_{t}h" for p in PARAM_NAMES
                                        for t in REQUIRED_HOURS]


def optional_columns() -> list[str]:
    return [f"{p}_{t}h" for p in PARAM_NAMES for t in TIMEPOINTS
            if t not in REQUIRED_HOURS] + ["wafer", "x", "y"]


def _present_read_points(df: pd.DataFrame) -> list[int]:
    """Read points where EVERY parameter has a column - a partial read point
    cannot be used, because the lot statistics would be built on a subset."""
    return [t for t in TIMEPOINTS
            if all(f"{p}_{t}h" in df.columns for p in PARAM_NAMES)]


def validate_dataset(df: pd.DataFrame, *,
                     min_lot_population: int = MIN_LOT_POPULATION) -> ValidationReport:
    """Validate a wide burn-in frame. Never mutates `df`."""
    rep = ValidationReport(rows=int(len(df)), columns=[str(c) for c in df.columns])
    add = rep.findings.append

    # ---------------------------------------------------------- structural
    if len(df) == 0:
        add(Finding("file", "EMPTY_DATASET", "The file contains no data rows."))
        return rep

    missing = [c for c in required_columns() if c not in df.columns]
    if missing:
        add(Finding(
            ", ".join(missing), "MISSING_REQUIRED_COLUMNS",
            "Required burn-in measurements or identifiers are missing. The "
            "screen needs serial, lot and the 0 h read for every parameter.",
            examples=missing))
        # Without identity or the 0h baseline nothing further is meaningful.
        return rep

    known = set(required_columns()) | set(optional_columns()) | {
        "true_class", "is_latent_defect", "static_fail_168h"}
    unexpected = [str(c) for c in df.columns if c not in known]
    if unexpected:
        add(Finding(
            ", ".join(unexpected[:8]), "UNEXPECTED_COLUMNS",
            f"{len(unexpected)} column(s) are not part of the burn-in schema "
            "and will be ignored by the screen.",
            severity="warning", count=len(unexpected), examples=unexpected[:8]))

    rep.read_points = _present_read_points(df)
    if not set(FORECAST_HOURS) <= set(rep.read_points):
        add(Finding(
            "24h", "NO_FORECAST_READS",
            "No complete 24 h read point. Module B cannot forecast and the "
            "predicted-drift sub-score will be unavailable; its weight is "
            "redistributed rather than scored as zero.",
            severity="warning"))
    if 168 not in rep.read_points:
        add(Finding(
            "168h", "NO_FINAL_READ",
            "No complete 168 h read point. This is an hour-24 triage frame: "
            "Module B and the 168 h-derived sub-scores are unavailable.",
            severity="warning"))
    if 96 not in rep.read_points:
        add(Finding(
            "96h", "NO_MID_READ",
            "No complete 96 h read point. Curvature (acceleration) cannot be "
            "computed, so reason code R-501 cannot fire.",
            severity="warning"))

    # ------------------------------------------------------------ identity
    serial = df["serial"]
    if serial.isna().any():
        n = int(serial.isna().sum())
        add(Finding("serial", "MISSING_SERIAL",
                    f"{n} row(s) have no component serial.", count=n))
    dup = serial[serial.duplicated(keep=False) & serial.notna()]
    if len(dup):
        uniq = sorted(map(str, dup.unique()))
        add(Finding("serial", "DUPLICATE_SERIAL",
                    f"{len(uniq)} serial(s) appear more than once. Each row "
                    "must be one component.",
                    count=len(uniq), examples=uniq[:8]))

    lots = df[LOT_COL]
    if lots.isna().any():
        n = int(lots.isna().sum())
        add(Finding(LOT_COL, "MISSING_LOT",
                    f"{n} row(s) have no lot identifier. Every statistic in "
                    "this system is computed within a lot, so a part with no "
                    "lot cannot be screened.", count=n))
    rep.lots = int(lots.nunique(dropna=True))

    counts = lots.value_counts(dropna=True)
    small = counts[counts < min_lot_population]
    if len(small):
        add(Finding(
            LOT_COL, "INSUFFICIENT_LOT_POPULATION",
            f"{len(small)} lot(s) have fewer than {min_lot_population} "
            "components. Robust per-lot statistics are unreliable at this "
            "size and every lot-relative score from them is suspect.",
            severity="warning", count=len(small),
            examples=[f"{k}:{int(v)}" for k, v in small.head(8).items()]))

    # -------------------------------------------------------- measurements
    for p in PARAM_NAMES:
        cfg = PARAMS[p]
        usl = float(cfg["usl"])
        for t in TIMEPOINTS:
            col = f"{p}_{t}h"
            if col not in df.columns:
                continue
            raw = df[col]

            # Non-numeric: pandas keeps an object column if any cell is text.
            coerced = pd.to_numeric(raw, errors="coerce")
            bad = coerced.isna() & raw.notna()
            if bad.any():
                add(Finding(
                    col, "INVALID_NUMERIC",
                    f"{int(bad.sum())} non-numeric measurement(s) found.",
                    count=int(bad.sum()),
                    examples=[str(v) for v in raw[bad].head(5).tolist()]))

            v = coerced.to_numpy(dtype=float)
            finite = np.isfinite(v)

            if np.isinf(coerced.to_numpy(dtype=float)).any():
                n = int(np.isinf(coerced.to_numpy(dtype=float)).sum())
                add(Finding(col, "NON_FINITE_VALUE",
                            f"{n} infinite measurement(s) found.", count=n))

            # Every parameter here is a magnitude - a negative reading is a
            # broken measurement, and for the lognormal currents it cannot be
            # log-transformed at all.
            neg = finite & (v < 0)
            if neg.any():
                code = "NEGATIVE_CURRENT" if cfg["is_current"] else "NEGATIVE_VALUE"
                add(Finding(
                    col, code,
                    f"{int(neg.sum())} negative measurement(s). "
                    + ("Currents are log-transformed before any statistic, so "
                       "a non-positive reading cannot be scored."
                       if cfg["is_current"] else
                       "This parameter is a magnitude and cannot be negative."),
                    count=int(neg.sum()),
                    examples=[round(float(x), 4) for x in v[neg][:5]]))

            zero = finite & (v == 0) & cfg["is_current"]
            if zero.any():
                add(Finding(
                    col, "ZERO_CURRENT",
                    f"{int(zero.sum())} zero current reading(s). These become "
                    "missing on the log scale rather than being scored.",
                    severity="warning", count=int(zero.sum())))

            implausible = finite & (v > usl * IMPLAUSIBLE_USL_MULTIPLE)
            if implausible.any():
                add(Finding(
                    col, "IMPLAUSIBLE_VALUE",
                    f"{int(implausible.sum())} reading(s) exceed "
                    f"{IMPLAUSIBLE_USL_MULTIPLE:.0f}x the {usl} "
                    f"{cfg['unit']} datasheet limit, which indicates a units "
                    "or decimal-point error rather than a failing part.",
                    count=int(implausible.sum()),
                    examples=[round(float(x), 4) for x in v[implausible][:5]]))

            miss = float(np.mean(~finite))
            if t in REQUIRED_HOURS and miss > 0:
                add(Finding(
                    col, "MISSING_REQUIRED_MEASUREMENT",
                    f"{int((~finite).sum())} row(s) have no {t} h reading. "
                    "The 0 h baseline is required for every parameter.",
                    count=int((~finite).sum())))
            elif miss > MAX_MISSING_FRACTION:
                add(Finding(
                    col, "EXCESSIVE_MISSINGNESS",
                    f"{miss:.1%} of {t} h readings are missing, above the "
                    f"{MAX_MISSING_FRACTION:.0%} tolerance. Lot statistics "
                    "built on this parameter are unreliable.",
                    severity="warning", count=int((~finite).sum())))

    # Two rows identical across every measurement is a duplicated export.
    meas_cols = [f"{p}_{t}h" for p in PARAM_NAMES for t in TIMEPOINTS
                 if f"{p}_{t}h" in df.columns]
    if meas_cols:
        dup_meas = int(df.duplicated(subset=meas_cols, keep=False).sum())
        if dup_meas:
            add(Finding(
                "measurements", "DUPLICATE_MEASUREMENTS",
                f"{dup_meas} row(s) share an identical measurement vector, "
                "which usually means the export was concatenated twice.",
                severity="warning", count=dup_meas))

    return rep
