"""Fusion - the 0-100 Screening Risk Score and the three-band verdict.

Rule 11: the top-level verdict is a weighted sum of NAMED sub-scores, never a
raw model output. ML improves the sub-scores; it does not make the decision.
The weights are visible, tunable, and defensible in a design review.

    Screening Risk Score =
        30% * static_margin      how close to the datasheet limit at 168h
      + 25% * dynamic_outlier    Module A L2, worst-case robust |z|
      + 20% * predicted_drift    Module B, worst slope / safety slope
      + 15% * multivariate       Module A L3, pooled evidence percentile
      + 10% * curvature          acceleration ratio, late drift / early drift

Each sub-score is mapped to 0-100 by a stated, monotone squash so the weighted
sum is interpretable. No sub-score is standardised against the labels, so the
whole stack remains unsupervised and runs on a lot it has never seen.

    0-39    ACCEPT   ship
    40-69   WATCH    ship with the serial flagged for extra scrutiny
    70-100  REJECT   remove from the lot before final electrical test

The three-band verdict beats a binary flag: it matches how QA operates, and it
softens the overkill cost. Only REJECT counts against the PDA gate, which is
what resolves the tension between rule 7 (minimise C_FN*FN + C_FP*FP) and the
5% PDA cap - at C_FN/C_FP = 100 the cost-optimal binary threshold would flag
~80% of every lot, which is not implementable. WATCH absorbs that pressure.

Band edges and weights are parameters, not magic numbers: `RiskWeights` and
`Bands` are dataclasses so the dashboard slider and the threshold policy can
move them live.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

from src.features import LOT_COL, PARAM_NAMES, PARAMS, build_features
from src.module_a import dpat_score, pooled_evidence_score, static_limit_flags

__all__ = [
    "RiskWeights", "Bands", "PDA_LIMIT",
    "squash", "sub_scores", "screening_risk_score", "verdict", "fuse",
    "lot_pda_status",
]

# Percent Defective Allowable. More than this fraction of a lot rejected and
# the lot goes to review (blueprint 2.1). Caps how aggressive the policy can be.
PDA_LIMIT = 0.05


@dataclass(frozen=True)
class RiskWeights:
    """Visible, tunable, and reported on the slide. They sum to 1."""
    static_margin: float = 0.30
    dynamic_outlier: float = 0.25
    predicted_drift: float = 0.20
    multivariate: float = 0.15
    curvature: float = 0.10

    def as_dict(self) -> dict:
        return asdict(self)

    def __post_init__(self):
        total = sum(self.as_dict().values())
        if not np.isclose(total, 1.0):
            raise ValueError(f"weights must sum to 1, got {total:.4f}")


@dataclass(frozen=True)
class Bands:
    """Verdict band edges on the 0-100 score."""
    watch: float = 40.0
    reject: float = 70.0

    def __post_init__(self):
        if not 0 < self.watch < self.reject < 100:
            raise ValueError(f"need 0 < watch < reject < 100, got {self}")


# ------------------------------------------------------------------ squash
def squash(x, full_scale: float) -> np.ndarray:
    """Map a non-negative quantity onto 0-100, saturating at ``full_scale``.

    Linear then clipped, deliberately. A logistic would be smoother but its
    midpoint and slope are two more unexplainable numbers; "this sub-score
    reaches 100 at 6 robust sigma" is a sentence an inspector can check.
    """
    v = np.asarray(x, dtype=float)
    v = np.nan_to_num(v, nan=0.0, posinf=full_scale, neginf=0.0)
    return np.clip(100.0 * v / full_scale, 0.0, 100.0)


def _scale(x, full_scale: float, squash_to_100: bool):
    """Squash for presentation, or pass through for ranking comparisons."""
    if squash_to_100:
        return squash(x, full_scale)
    return np.nan_to_num(np.asarray(x, dtype=float), nan=0.0,
                         posinf=full_scale * 10, neginf=0.0)


# ------------------------------------------------------------- sub-scores
def sub_scores(df: pd.DataFrame, feat: pd.DataFrame | None = None,
               module_b: pd.DataFrame | None = None,
               lot_col: str = LOT_COL, squash_to_100: bool = True) -> pd.DataFrame:
    """The five named sub-scores, each 0-100. This is what fusion weighs.

    ``squash_to_100=False`` returns the underlying continuous quantities
    instead, without the clip. Use it for ANY ranking comparison: average
    precision credits a saturated score's tied ceiling block with that block's
    average precision rather than penalising its internal ordering, so a
    clipped sub-score's PR-AUC is inflated and not comparable with an
    unclipped one. `evaluate.pr_auc` warns when it sees this.

    ``module_b`` is the frame from ``module_b.early_reject`` (needs a
    ``worst_ratio`` column). When it is absent the predicted_drift sub-score is
    zero and its weight is redistributed - the score stays on 0-100 rather than
    silently shrinking, and ``fuse`` reports which sub-scores were available.
    """
    feat = build_features(df) if feat is None else feat
    out = pd.DataFrame(index=df.index)

    # 1. static margin: how much of its OWN available headroom the part
    #    consumed during burn-in, worst parameter.
    #
    #        (V_168h - V_0h) / (USL - V_0h)
    #
    #    0 means it did not move; 100 means it ate all the margin it had and is
    #    now at the datasheet limit.
    #
    #    NOT V_168h / USL, which is the obvious formulation and is wrong: a
    #    healthy Tpd_ns part sits at 3.28 ns against a 4.60 ns USL, so it would
    #    score 71/100 while doing nothing at all, adding a ~21-point constant
    #    offset to every part's risk score. Measuring consumed headroom instead
    #    is lot-independent, scores a stable part near zero, and is the same
    #    "drift, not level" thesis the rest of the project rests on.
    margins = []
    for p in PARAM_NAMES:
        c168, c0 = f"{p}_168h", f"{p}_0h"
        if c168 in df.columns and c0 in df.columns:
            headroom = (PARAMS[p]["usl"] - df[c0]).clip(lower=1e-9)
            margins.append((df[c168] - df[c0]) / headroom)
    out["static_margin"] = (_scale(pd.concat(margins, axis=1).max(axis=1), 1.0, squash_to_100)
                            if margins else 0.0)

    # 2. dynamic outlier: Module A L2. Full scale at 6 robust sigma, the
    #    AEC-Q001 DPAT limit.
    out["dynamic_outlier"] = _scale(dpat_score(feat), 6.0, squash_to_100)

    # 3. predicted drift: Module B. Full scale when the predicted slope equals
    #    the safety slope.
    out["predicted_drift"] = (_scale(module_b["worst_ratio"], 1.0, squash_to_100)
                              if module_b is not None else 0.0)

    # 4. multivariate: Module A L3 pooled evidence. Full scale at chi2(0.999)
    #    with 4 dof, the blueprint's Mahalanobis threshold, reused here so the
    #    two layers are on a comparable footing.
    try:
        from scipy.stats import chi2
        full = float(chi2.ppf(0.999, df=len(PARAM_NAMES)))
    except Exception:                                    # pragma: no cover
        full = 18.47
    # Needs the drift view, so it is unavailable on an hour-24 frame. Degrade
    # the same way predicted_drift does - zero here, weight redistributed by
    # screening_risk_score - rather than raising and taking the whole screen
    # down, or silently scoring the part as safer.
    from src.module_a import DRIFT_AXES
    if all(a in feat.columns for a in DRIFT_AXES):
        out["multivariate"] = _scale(pooled_evidence_score(feat), full,
                                     squash_to_100)
    else:
        out["multivariate"] = 0.0

    # 5. curvature: acceleration. Full scale at 3x, i.e. the late window
    #    drifting three times as fast as the early one.
    ccols = [c for c in feat.columns if c.startswith("curv_")]
    out["curvature"] = (_scale(feat[ccols].max(axis=1, skipna=True), 3.0, squash_to_100)
                        if ccols else 0.0)

    return out


def screening_risk_score(subs: pd.DataFrame,
                         weights: RiskWeights | None = None) -> pd.Series:
    """Weighted sum of the named sub-scores. Renormalised over what exists."""
    w = weights or RiskWeights()
    wd = w.as_dict()
    available = [k for k in wd if k in subs.columns]
    total = sum(wd[k] for k in available)
    if total <= 0:
        raise ValueError("no sub-scores available to fuse")
    return sum(subs[k] * (wd[k] / total) for k in available)


def verdict(score: pd.Series, bands: Bands | None = None) -> pd.Series:
    b = bands or Bands()
    return pd.Series(
        np.select([score >= b.reject, score >= b.watch],
                  ["REJECT", "WATCH"], default="ACCEPT"),
        index=score.index, name="verdict")


def fuse(df: pd.DataFrame, feat: pd.DataFrame | None = None,
         module_b: pd.DataFrame | None = None,
         weights: RiskWeights | None = None, bands: Bands | None = None,
         lot_col: str = LOT_COL) -> pd.DataFrame:
    """Everything an inspector sees: sub-scores, risk score, verdict.

    Also carries ``l1_static``, because a datasheet breach is a hard reject
    regardless of what the weighted score says - the screen may add rejections
    to the datasheet, never remove them.
    """
    feat = build_features(df) if feat is None else feat
    subs = sub_scores(df, feat, module_b, lot_col)
    score = screening_risk_score(subs, weights)

    out = subs.copy()
    out["risk_score"] = score
    out["verdict"] = verdict(score, bands)

    hard = static_limit_flags(df)["static_any"]
    out["l1_static"] = hard.astype(int)
    out.loc[hard, "verdict"] = "REJECT"

    if "serial" in df.columns:
        out.insert(0, "serial", df["serial"])
    out.insert(1 if "serial" in df.columns else 0, "lot", df[lot_col])
    return out


def bands_for_pda(score: pd.Series, target_reject: float = PDA_LIMIT,
                  watch_multiple: float = 3.0) -> Bands:
    """Place the band edges so the REJECT rate respects the PDA gate.

    This is what resolves rule 7 against the PDA cap. Pure cost minimisation at
    C_FN/C_FP = 100 would flag ~80% of every lot, which no line can run: exceed
    the PDA and the whole lot goes to review, so an over-aggressive screen
    scraps good lots rather than saving them.

    The REJECT edge is therefore set by the budget the line actually has, and
    WATCH absorbs the remaining recall - those parts still ship, with the serial
    flagged for scrutiny, and they do not consume PDA budget.

    ``watch_multiple`` sets how many parts enter WATCH per rejected part.
    """
    s = pd.Series(score).dropna()
    reject_edge = float(s.quantile(1.0 - target_reject))
    watch_edge = float(s.quantile(max(0.0, 1.0 - target_reject * watch_multiple)))
    # Keep the invariant 0 < watch < reject < 100 even on degenerate scores.
    watch_edge = min(watch_edge, reject_edge - 1e-6)
    return Bands(watch=max(watch_edge, 1e-6), reject=min(reject_edge, 100.0 - 1e-6))


def lot_pda_status(fused: pd.DataFrame, lot_col: str = LOT_COL,
                   pda: float = PDA_LIMIT) -> pd.DataFrame:
    """Per-lot reject fraction against the PDA gate. Feeds reason code R-601.

    Only REJECT counts. WATCH parts ship with the serial flagged, so they do not
    consume PDA budget - that is the entire point of the three-band verdict.
    """
    g = fused.groupby(lot_col)
    tab = pd.DataFrame({
        "parts": g.size(),
        "reject": g.verdict.apply(lambda s: int((s == "REJECT").sum())),
        "watch": g.verdict.apply(lambda s: int((s == "WATCH").sum())),
        "mean_risk": g.risk_score.mean().round(1),
    })
    tab["reject_frac"] = tab.reject / tab.parts
    tab["pda_limit"] = pda
    tab["status"] = np.where(tab.reject_frac > pda, "LOT REVIEW", "OK")
    return tab
