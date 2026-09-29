"""Structured Module A and Module B evidence for one component.

Two rules this module exists to enforce:

1. A score on its own is not evidence. Every number here is reported with the
   threshold it was judged against, the parameter it came from, and the lot
   reference value it was measured relative to - in datasheet units.
2. OBSERVED and FORECAST are never mixed. Module B's payload separates the
   measured 0 h / 24 h reads from the predicted 168 h value, and labels the
   prediction with its quantile. A forecast presented as a measurement is the
   single most dangerous thing this service could return.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from src.features import LOT_COL, PARAM_NAMES, PARAMS, robust_sigma
from src.module_a import (
    DRIFT_AXES, pooled_evidence_contributions, static_limit_flags,
)

__all__ = ["module_a_evidence", "module_b_evidence", "POOLED_THRESHOLD",
           "DPAT_LIMIT_SIGMA"]

# AEC-Q001 Dynamic PAT limit. The industry gate this project extends.
DPAT_LIMIT_SIGMA = 6.0

# chi2(0.999) with 4 degrees of freedom - one per drift axis.
try:  # pragma: no cover - scipy is pinned, this is belt and braces
    from scipy.stats import chi2 as _chi2
    POOLED_THRESHOLD = float(_chi2.ppf(0.999, df=len(PARAM_NAMES)))
except Exception:  # pragma: no cover
    POOLED_THRESHOLD = 18.47

_VIEWS = ("level_0h", "level_168h", "early", "drift", "curvature")


def _f(v) -> float | None:
    """Finite float or None. NaN must never reach a JSON payload as NaN."""
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if not math.isfinite(x) else round(x, 6)


# ===================================================================== A
def module_a_evidence(df: pd.DataFrame, feat: pd.DataFrame, i,
                      static_flags: pd.DataFrame | None = None) -> dict:
    """Layered anomaly evidence: L1 static, L2 lot-relative, L3 pooled."""
    row = df.loc[i]
    lot = row[LOT_COL]
    lot_rows = df[df[LOT_COL] == lot]
    flags = static_limit_flags(df) if static_flags is None else static_flags

    # ---------------------------------------------------------- L1 static
    per_param_static = []
    for p in PARAM_NAMES:
        cfg = PARAMS[p]
        usl = float(cfg["usl"])
        v0 = _f(row.get(f"{p}_0h"))
        v168 = _f(row.get(f"{p}_168h"))
        headroom = (usl - v0) if v0 is not None else None
        per_param_static.append({
            "parameter": p,
            "label": cfg["label"],
            "unit": cfg["unit"],
            "usl": usl,
            "value_0h": v0,
            "value_168h": v168,
            # Share of its OWN available headroom the part consumed during
            # burn-in. Not value/USL - a healthy Tpd part sits at 71% of its
            # USL while doing nothing at all.
            "margin_consumed": _f((v168 - v0) / headroom)
            if (v168 is not None and headroom not in (None, 0)) else None,
            "breach": bool(v168 is not None and v168 > usl),
        })
    static_breach = bool(flags.at[i, "static_any"]) if i in flags.index else False

    # ----------------------------------------------- L2 lot-relative (DPAT)
    z_cols = [c for c in feat.columns if c.startswith("z_")]
    zrow = feat.loc[i, z_cols].astype(float)
    abs_z = zrow.abs()
    worst_col = str(abs_z.idxmax()) if len(abs_z.dropna()) else None
    worst_param, worst_view = None, None
    if worst_col:
        stem = worst_col[2:]
        for v in sorted(_VIEWS, key=len, reverse=True):
            if stem.endswith(f"_{v}"):
                worst_param, worst_view = stem[: -len(v) - 1], v
                break

    per_param_dynamic = []
    for p in PARAM_NAMES:
        entry: dict = {"parameter": p, "unit": PARAMS[p]["unit"]}
        for v in _VIEWS:
            entry[v] = _f(feat.get(f"z_{p}_{v}", pd.Series(dtype=float)).get(i))
        c0, c168 = f"{p}_0h", f"{p}_168h"
        if c0 in df.columns and c168 in df.columns:
            entry["lot_median_168h"] = _f(lot_rows[c168].median())
            entry["lot_robust_sigma_168h"] = _f(robust_sigma(lot_rows[c168]))
            entry["lot_median_drift"] = _f((lot_rows[c168] - lot_rows[c0]).median())
            entry["observed_drift"] = _f(_f(row.get(c168)) - _f(row.get(c0))
                                         if row.get(c168) == row.get(c168)
                                         and row.get(c0) == row.get(c0) else None)
        per_param_dynamic.append(entry)

    l2 = _f(abs_z.max(skipna=True))

    # -------------------------------------------------- L3 pooled evidence
    contrib = pooled_evidence_contributions(feat)
    pooled_total, pooled_terms = None, []
    if i in contrib.index and len(contrib.columns):
        terms = contrib.loc[i]
        pooled_total = _f(terms.sum())
        total = float(terms.sum()) or 1.0
        for axis in DRIFT_AXES:
            if axis not in terms.index:
                continue
            sq = float(terms[axis])
            pooled_terms.append({
                "axis": axis,
                "parameter": axis[2:-6],          # z_<param>_drift
                "z": _f(math.sqrt(sq)) if sq > 0 else 0.0,
                "squared_contribution": _f(sq),
                "share": _f(sq / total),
            })
        pooled_terms.sort(key=lambda t: t["squared_contribution"] or 0, reverse=True)

    # ----------------------------------------------------------- curvature
    curv = [{
        "parameter": p,
        "ratio": _f(feat.get(f"curv_{p}", pd.Series(dtype=float)).get(i)),
        "z": _f(feat.get(f"z_{p}_curvature", pd.Series(dtype=float)).get(i)),
    } for p in PARAM_NAMES]
    worst_curv = max((c for c in curv if c["ratio"] is not None),
                     key=lambda c: c["ratio"], default=None)

    return {
        "static": {
            "verdict": "BREACH" if static_breach else "PASS",
            "breach": static_breach,
            "per_parameter": per_param_static,
            "note": ("Datasheet upper limit at any read point. This is the "
                     "layer the screen exists to beat, not the verdict."),
        },
        "lot_relative": {
            "score": l2,
            "metric": "worst-case |robust z| across parameters and views",
            "dpat_limit_sigma": DPAT_LIMIT_SIGMA,
            "exceeds_dpat_limit": bool(l2 is not None and l2 >= DPAT_LIMIT_SIGMA),
            "worst": {
                "feature": worst_col,
                "parameter": worst_param,
                "view": worst_view,
                "z": _f(abs_z.max(skipna=True)),
                "signed_z": _f(zrow.get(worst_col)) if worst_col else None,
            },
            "per_parameter": per_param_dynamic,
            "note": ("Location is the lot median, spread is 1.4826*MAD. "
                     "Statistics for currents are taken on log(x)."),
        },
        "multivariate": {
            "score": pooled_total,
            "metric": "one-sided sum of squared robust z over the four drift axes",
            "threshold": round(POOLED_THRESHOLD, 3),
            "threshold_basis": "chi2(0.999), 4 degrees of freedom",
            "exceeds": bool(pooled_total is not None
                            and pooled_total > POOLED_THRESHOLD),
            "contributions": pooled_terms,
            "note": ("Pools marginal evidence across axes. The delta-vector "
                     "covariance in this dataset is diagonal, so this is not "
                     "correlation-break detection."),
        },
        "curvature": {
            "worst": worst_curv,
            "per_parameter": curv,
            "threshold": 2.0,
            "note": ("Late-window drift rate over early-window rate, each "
                     "normalised per hour. 1.0 is perfectly linear; below 1.0 "
                     "the part is settling."),
        },
    }


# ===================================================================== B
def module_b_evidence(df: pd.DataFrame, i,
                      forecast_point: pd.DataFrame | None,
                      forecast_upper: pd.DataFrame | None,
                      module_b: pd.DataFrame | None,
                      *, quantile: float = 0.90,
                      out_of_fold: bool = False,
                      population_k: float | None = None) -> dict:
    """Early-drift forecast evidence, with OBSERVED and FORECAST separated."""
    row = df.loc[i]

    observed = {}
    for t in (0, 24, 96, 168):
        col_present = all(f"{p}_{t}h" in df.columns for p in PARAM_NAMES)
        if not col_present:
            continue
        observed[f"{t}h"] = {p: _f(row.get(f"{p}_{t}h")) for p in PARAM_NAMES}

    if module_b is None or forecast_point is None or i not in forecast_point.index:
        return {
            "available": False,
            "reason_unavailable": (
                "Module B forecasts the 168 h value and needs a 168 h column "
                "to fit against. This frame has none, so the predicted-drift "
                "sub-score is unavailable and its weight is redistributed "
                "rather than scored as zero."),
            "inputs_used": ["0h", "24h"],
            "observed": observed,
            "forecast": None,
            "safety_slope": None,
            "early_reject": None,
            "forecast_out_of_fold": False,
        }

    point = {p: _f(forecast_point.at[i, p]) for p in PARAM_NAMES
             if p in forecast_point.columns}
    upper = ({p: _f(forecast_upper.at[i, p]) for p in PARAM_NAMES
              if p in forecast_upper.columns}
             if forecast_upper is not None and i in forecast_upper.index else {})

    per_param_ratio = {p: _f(module_b.at[i, p]) for p in PARAM_NAMES
                       if p in module_b.columns}
    worst_param = (str(module_b.at[i, "worst_param"])
                   if "worst_param" in module_b.columns else None)
    worst_ratio = _f(module_b.at[i, "worst_ratio"]) if "worst_ratio" in module_b.columns else None

    return {
        "available": True,
        "inputs_used": ["0h", "24h"],
        "leakage_guard": (
            "The forecast is computed from the 0 h and 24 h reads only. No "
            "96 h or 168 h measurement, and no label, enters its features."),
        "observed": observed,
        "forecast": {
            "target": "168h",
            "point_estimate": point,
            "upper_bound": upper,
            "upper_bound_quantile": quantile,
            "is_prediction": True,
            "note": ("These are PREDICTED values, not measurements. The reject "
                     "gate is applied to the upper bound so a component is "
                     "pulled only when even its optimistic case breaches."),
        },
        "safety_slope": {
            "worst_parameter": worst_param,
            "worst_ratio": worst_ratio,
            "gate": 1.0,
            "exceeds_gate": bool(worst_ratio is not None and worst_ratio > 1.0),
            "per_parameter_ratio": per_param_ratio,
            "population_k": _f(population_k),
            "gates": {
                "mission": ("(USL - V0) / (mission_hours / AF), Arrhenius "
                            "Ea=0.7 eV at 25/125 C. Measured to bind on "
                            "0.0-0.1% of parts."),
                "population": ("lot median drift rate + k * robust sigma, on "
                               "the log scale for currents. k is calibrated "
                               "from the PDA budget, not fixed."),
            },
            "note": ("The two gates are in different units and are not "
                     "combined into one number; the stricter decision wins."),
        },
        "early_reject": bool(module_b.at[i, "reject_at_24h"])
        if "reject_at_24h" in module_b.columns else None,
        "forecast_out_of_fold": bool(out_of_fold),
        "forecast_validity_note": (
            "Out-of-fold: every component was forecast by a model that never "
            "saw its own lot, so a reported MAE from this run is valid."
            if out_of_fold else
            "In-fold: this frame had too few lots for GroupKFold to hold one "
            "out, so the forecaster was fitted on the frame it predicts. "
            "Valid for screening; NOT valid for quoting forecast accuracy."),
    }
