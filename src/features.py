"""Feature engineering - THE single definition of every feature.

Rule 8 of CLAUDE.md: feature logic lives only here. Training, evaluation, the
API and the dashboard all import from this module. A feature computed two ways
is a feature you cannot trust.

What this module produces
-------------------------
Robust z-scores computed **per lot**, on four named views per parameter:

    level       z of the value itself, at 0h and at 168h
                -> catches the brief's worked example: a 45 uA part in a lot
                   centred on 10 uA, comfortably inside a 50 uA datasheet limit
    early       z of (V_24h - V_0h)
                -> parts that start normal but move fast. The only drift view
                   available at hour 24, and the signal Module B is built on
    drift       z of (V_168h - V_0h)
                -> the classic delta criterion, made lot-relative
    curvature   z of the acceleration ratio (see below)
                -> healthy parts settle, defects accelerate. The cleanest
                   physical separator available

"level" is the one view that emits two columns (0h and 168h), because a part
can be born bad or become bad and those are different failure stories. Five
z-columns per parameter, twenty in total for the four-parameter dataset.

Domain invariants upheld here
-----------------------------
* Currents (Iddq_uA, Ileak_nA) are log-transformed before any statistic;
  timing/voltage (Tpd_ns, Vol_mV) are used raw. Leakage spans orders of
  magnitude, so a raw sigma is inflated by the lognormal tail and real outliers
  hide inside the widened limits (rule 1).
* Location is `median`, spread is `1.4826 * MAD`. Never mean/std (rule 2).
* Every statistic is computed within a lot, never globally (rule 3).
* z-scores are returned SIGNED. Higher is worse for every parameter in this
  dataset, so consumers may legitimately use one-sided logic (rule 4) - but
  that choice belongs to the scoring layer, not here, and the sign is needed to
  tell "abnormally high" from "abnormally low" in a reason code.

Two deliberate deviations from the blueprint, both documented at their
definitions below: the MAD fallback avoids std (rule 2), and the curvature
ratio is normalised per hour so that a perfectly linear part scores 1.0.

Availability
------------
`build_features` auto-detects which read points are present. Given only the 0h
and 24h columns it emits the level_0h and early views and omits the rest, so
the SAME function serves training on the full frame and Module B's hour-24
inference path. `early_feature_names()` lists what is computable at hour 24 -
use it to assert Module B never sees a 168h-derived column.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = [
    "PARAMS",
    "PARAM_NAMES",
    "TIMEPOINTS",
    "LOT_COL",
    "VIEWS",
    "robust_sigma",
    "robust_z",
    "dpat_limits",
    "transform",
    "build_features",
    "build_forecast_features",
    "FORECAST_FEATURE_NAMES",
    "feature_names",
    "early_feature_names",
    "lot_reference_table",
]

# --------------------------------------------------------------- registry
# The parameter contract. `is_current` drives the log transform; `usl` is the
# datasheet upper limit used by the L1 static layer and the static-margin
# sub-score. Every parameter in this dataset is higher-is-worse, so there is no
# lower spec limit to carry.
PARAMS: dict[str, dict] = {
    "Iddq_uA": dict(is_current=True, usl=50.0, unit="uA",
                    label="quiescent supply current"),
    "Ileak_nA": dict(is_current=True, usl=200.0, unit="nA",
                     label="junction leakage current"),
    "Tpd_ns": dict(is_current=False, usl=4.60, unit="ns",
                   label="propagation delay"),
    "Vol_mV": dict(is_current=False, usl=400.0, unit="mV",
                   label="output low voltage"),
}

PARAM_NAMES: list[str] = list(PARAMS)
TIMEPOINTS: tuple[int, ...] = (0, 24, 96, 168)
LOT_COL = "lot"

# The four named views, in the order they are emitted. `needs` lists the read
# points each one consumes - this is what makes hour-24 inference detectable
# rather than a silent source of leakage.
VIEWS: dict[str, tuple[int, ...]] = {
    "level_0h": (0,),
    "level_168h": (168,),
    "early": (0, 24),
    "drift": (0, 168),
    "curvature": (0, 24, 96, 168),
}

# Curvature denominators are floored at this multiple of the lot's own
# early-delta spread. See `_curvature_ratio`.
_CURV_FLOOR_MULT = 1.0


# ----------------------------------------------------------- robust stats
def robust_sigma(s: pd.Series) -> float:
    """Outlier-immune spread estimate. Equals sigma for normal data.

    Primary estimator is ``1.4826 * MAD``; the constant makes MAD a
    sigma-equivalent under normality. If MAD is exactly zero - which happens
    when more than half a lot shares one quantised value - fall back to
    ``IQR / 1.35``, the other consistent robust estimator.

    Deliberate deviation from the blueprint's reference snippet, which falls
    back to ``s.std()``. Rule 2 forbids std for spreads used in outlier scores,
    and the fallback fires exactly when the data is degenerate - precisely the
    case where a single extreme value would dominate a standard deviation.
    Returning 0.0 is the honest answer: a lot with no measurable spread offers
    no evidence about which of its parts is an outlier.
    """
    x = s.to_numpy(dtype=float)
    x = x[np.isfinite(x)]
    if x.size == 0:
        return 0.0
    med = np.median(x)
    mad = np.median(np.abs(x - med))
    if mad > 0:
        return float(1.4826 * mad)
    q75, q25 = np.percentile(x, [75, 25])
    iqr = q75 - q25
    return float(iqr / 1.35) if iqr > 0 else 0.0


def robust_z(s: pd.Series) -> pd.Series:
    """``(x - median) / (1.4826 * MAD)``, immune to the outliers it hunts.

    A mean/std z-score suffers masking: one large outlier inflates sigma enough
    to hide itself. The median and MAD both have a 50% breakdown point, so a
    lot would need to be half-defective before this estimator moved.

    Returns zeros when the lot has no measurable spread - no spread means no
    evidence, not infinite evidence. A part whose reading is missing stays NaN
    even on that path: "we did not measure this" and "this sits exactly at the
    lot median" are different claims, and only one of them is true.
    """
    sigma = robust_sigma(s)
    if sigma <= 0:
        return pd.Series(np.where(s.isna(), np.nan, 0.0),
                         index=s.index, dtype=float)
    return (s - s.median()) / sigma


def dpat_limits(s: pd.Series, k: float = 6.0) -> tuple[float, float]:
    """AEC-Q001 style Dynamic PAT limits: ``median +/- k * robust sigma``.

    k = 6 is the industry default. It is tuned downward (typically 4.5-6) on
    the false-negative-weighted metric, never left at 6 because 6 sounds right.
    """
    med = float(s.median())
    sigma = robust_sigma(s)
    return med - k * sigma, med + k * sigma


# ------------------------------------------------------------- transform
def transform(values: pd.Series, param: str) -> pd.Series:
    """Put a parameter on the scale its statistics are valid on.

    Currents are lognormal, so every statistic is taken on ``log(x)``. On that
    scale a difference is a log-ratio, which is what makes drift comparable
    across lots with different process centring. Timing and voltage are close
    enough to normal to use raw.

    Non-positive current readings cannot be logged. They do not occur in the
    generated data, but a real tester can emit a zero or a negative on a failed
    read, so they become NaN here rather than silently becoming -inf.
    """
    if not PARAMS[param]["is_current"]:
        return values.astype(float)
    v = values.astype(float)
    return pd.Series(np.where(v > 0, np.log(np.where(v > 0, v, np.nan)), np.nan),
                     index=v.index, dtype=float)


# ------------------------------------------------------------- curvature
def _curvature_ratio(early: pd.Series, late: pd.Series, lot: pd.Series) -> pd.Series:
    """Acceleration ratio: late-window drift rate over early-window drift rate.

    Physics. Under ``X(t) = X0 * (1 + A * (t/168)^n)`` the two window rates are
    a function of the exponent n alone - X0 and A cancel - so this ratio reads
    out the degradation exponent directly:

        n = 0.35  ->  0.11      healthy, settling hard
        n = 0.75  ->  0.49      healthy, upper end
        n = 1.00  ->  1.00      perfectly linear
        n = 1.30  ->  2.22
        n = 1.60  ->  4.79      latent defect, accelerating

    Deliberate deviation from the blueprint, which writes the ratio as the raw
    ``(V168 - V96) / (V24 - V0)`` and then sets reason code R-501 at "> 2". The
    windows are 72 h and 24 h wide, so that raw form scores a perfectly linear
    part at 3.0 and R-501 would fire on every part in the lot. Dividing each
    window by its own width fixes the scale: linear is 1.0, and "> 2" becomes
    the physically meaningful statement "the late window is drifting twice as
    fast as the early one". If R-501's threshold is retuned, retune it against
    this definition.

    Numerics. For a healthy part the early window is mostly measurement noise -
    1.5% ATE repeatability against a ~1% real movement - so the denominator
    crosses zero and a bare ratio explodes. It is floored at the lot's own
    early-delta spread, which is a direct estimate of that noise scale. The
    effect is that a part whose early window is indistinguishable from noise
    cannot manufacture a large curvature; it needs real early movement, or a
    large late movement, to score.
    """
    rate_early = early / 24.0
    rate_late = late / (168.0 - 96.0)

    # Per-lot noise floor for the denominator.
    floor = rate_early.groupby(lot).transform(
        lambda g: _CURV_FLOOR_MULT * robust_sigma(g)
    )
    # A degenerate lot (no measurable spread) gets a floor from the global
    # scale so the division stays finite.
    global_floor = _CURV_FLOOR_MULT * robust_sigma(rate_early)
    floor = floor.mask(floor <= 0, global_floor if global_floor > 0 else 1e-12)

    return rate_late / (rate_early.abs() + floor)


# ------------------------------------------------------------ the builder
def _present_hours(df: pd.DataFrame, param: str) -> set[int]:
    return {t for t in TIMEPOINTS if f"{param}_{t}h" in df.columns}


def build_features(df: pd.DataFrame, lot_col: str = LOT_COL) -> pd.DataFrame:
    """Build the per-lot robust-z feature frame.

    Parameters
    ----------
    df :
        Wide burn-in frame, one row per part, as written by
        ``generate_burnin_dataset.py``. Must contain ``lot_col`` and, for each
        parameter, at least the ``{PARAM}_0h`` column. Views whose read points
        are absent are silently omitted - that is what lets Module B call this
        with an hour-24 frame.
    lot_col :
        Grouping column. Every statistic is computed within it.

    Returns
    -------
    DataFrame indexed identically to ``df``, containing only engineered
    features - no labels, no raw values.

        z_{param}_level_0h      signed robust z of the 0h level
        z_{param}_level_168h    signed robust z of the 168h level
        z_{param}_early         signed robust z of (V_24h - V_0h)
        z_{param}_drift         signed robust z of (V_168h - V_0h)
        z_{param}_curvature     signed robust z of the acceleration ratio
        curv_{param}            the raw acceleration ratio, kept because reason
                                code R-501 must quote an actual number and the
                                caller cannot recompute it without the lot's
                                noise floor

    NaN is preserved, not filled. Roughly 1.2% of parts have a dropped 96h read
    and therefore no curvature; filling that with 0.0 would assert "this part
    shows no acceleration", which is a claim the data does not support. Scoring
    layers aggregate with skipna, so such a part is judged on its other views.
    """
    if lot_col not in df.columns:
        raise KeyError(
            f"build_features needs the grouping column {lot_col!r}; "
            f"got columns {list(df.columns)[:12]}..."
        )

    missing_base = [p for p in PARAM_NAMES if f"{p}_0h" not in df.columns]
    if missing_base:
        raise KeyError(
            f"missing required 0h columns for {missing_base}. Every parameter "
            "needs at least its 0h read to be featurised."
        )

    lot = df[lot_col]
    out: dict[str, pd.Series] = {}

    for p in PARAM_NAMES:
        have = _present_hours(df, p)

        # Transform once, on the scale the statistics are valid on.
        v = {t: transform(df[f"{p}_{t}h"], p) for t in sorted(have)}

        def z_by_lot(s: pd.Series) -> pd.Series:
            return s.groupby(lot).transform(robust_z)

        if 0 in have:
            out[f"z_{p}_level_0h"] = z_by_lot(v[0])
        if 168 in have:
            out[f"z_{p}_level_168h"] = z_by_lot(v[168])
        if {0, 24} <= have:
            out[f"z_{p}_early"] = z_by_lot(v[24] - v[0])
        if {0, 168} <= have:
            out[f"z_{p}_drift"] = z_by_lot(v[168] - v[0])
        if {0, 24, 96, 168} <= have:
            ratio = _curvature_ratio(v[24] - v[0], v[168] - v[96], lot)
            out[f"z_{p}_curvature"] = z_by_lot(ratio)
            out[f"curv_{p}"] = ratio

    feat = pd.DataFrame(out, index=df.index)
    return feat[feature_names(feat.columns)]


# --------------------------------------------------------- name helpers
def feature_names(available: pd.Index | list[str] | None = None) -> list[str]:
    """Canonical feature order. Frozen - half of all merge conflicts are names.

    Passing ``available`` filters to the columns actually built, preserving the
    canonical order.
    """
    names: list[str] = []
    for p in PARAM_NAMES:
        for view in VIEWS:
            names.append(f"z_{p}_{view}")
        names.append(f"curv_{p}")
    if available is None:
        return names
    have = set(available)
    return [n for n in names if n in have]


def early_feature_names() -> list[str]:
    """Features computable from 0h and 24h alone.

    Module B forecasts the 168h value from the first 24 hours; anything outside
    this list would leak the answer into the question. Assert against it rather
    than trusting a column-name convention.
    """
    early_views = [v for v, hours in VIEWS.items() if max(hours) <= 24]
    return [f"z_{p}_{v}" for p in PARAM_NAMES for v in early_views]


def build_forecast_features(df: pd.DataFrame, param: str,
                            lot_col: str = LOT_COL) -> pd.DataFrame:
    """Hour-24 feature block for one parameter, for Module B.

    Rule 8: Module B's inputs are defined here, not inside module_b.py, so the
    training path and the hour-24 inference path cannot drift apart.

    Every column is computable from the 0h and 24h reads alone. Nothing derived
    from 96h or 168h may ever appear here - that would leak the answer into the
    question. ``test_forecast_features_use_no_late_reads`` asserts it by
    rebuilding from a frame with the late columns deleted.

    Columns (all on the statistics scale - log for currents):

        v0, v24            absolute level; high starting leakage predicts high
                           absolute drift
        early              v24 - v0, the only movement visible at hour 24
        early_ratio        relative movement; generalises across lots where the
                           difference carries units
        z_v0, z_early      the same two, made lot-relative
        lot_med_v0         lot health: a part drifting at the lot average is
        lot_med_early      fine, the same drift in a tight lot is not
        lot_sigma_early
        early_over_lot     early delta in units of the lot's own spread
    """
    if param not in PARAMS:
        raise KeyError(f"unknown parameter {param!r}")
    for t in (0, 24):
        if f"{param}_{t}h" not in df.columns:
            raise KeyError(f"build_forecast_features needs {param}_{t}h")

    lot = df[lot_col]
    v0 = transform(df[f"{param}_0h"], param)
    v24 = transform(df[f"{param}_24h"], param)
    early = v24 - v0

    lot_sigma_early = early.groupby(lot).transform(robust_sigma)
    out = pd.DataFrame({
        "v0": v0,
        "v24": v24,
        "early": early,
        "early_ratio": v24 / v0.replace(0.0, np.nan),
        "z_v0": v0.groupby(lot).transform(robust_z),
        "z_early": early.groupby(lot).transform(robust_z),
        "lot_med_v0": v0.groupby(lot).transform("median"),
        "lot_med_early": early.groupby(lot).transform("median"),
        "lot_sigma_early": lot_sigma_early,
    }, index=df.index)
    out["early_over_lot"] = early / lot_sigma_early.replace(0.0, np.nan)
    return out


FORECAST_FEATURE_NAMES = [
    "v0", "v24", "early", "early_ratio", "z_v0", "z_early",
    "lot_med_v0", "lot_med_early", "lot_sigma_early", "early_over_lot",
]


def lot_reference_table(df: pd.DataFrame, lot_col: str = LOT_COL) -> pd.DataFrame:
    """Per-lot median and robust sigma for every parameter and read point.

    This is what a reason code quotes as the "lot reference value" (rule 12):
    an inspector needs "31.2 uA against a lot median of 10.4 uA", not a z-score
    on its own. Reported on the RAW scale, in datasheet units, because that is
    what is written on the traveller - even though the statistics behind the
    z-scores were computed on the log scale for currents.
    """
    rows = []
    for p in PARAM_NAMES:
        for t in sorted(_present_hours(df, p)):
            col = df[f"{p}_{t}h"]
            for lot_id, idx in df.groupby(lot_col).groups.items():
                s = col.loc[idx]
                rows.append(dict(
                    lot=lot_id, parameter=p, hours=t, unit=PARAMS[p]["unit"],
                    median=float(s.median()),
                    robust_sigma=robust_sigma(s),
                    usl=PARAMS[p]["usl"],
                    n=int(s.notna().sum()),
                ))
    return pd.DataFrame(rows)
