"""Module A - dynamic outlier detection.

Flags parts that are abnormal relative to their own lot, not relative to the
datasheet. Layers, each independently runnable and independently demonstrable:

    L1  static datasheet limits   the baseline we exist to beat. Kept in the
                                  pipeline forever - the demo needs to show it
                                  catching none of the latent defects.
    L2  Dynamic PAT               worst-case |robust z| across parameters and
                                  views, computed per lot by src.features.
    L3  pooled evidence           one-sided sum of squared robust z over the
                                  four drift axes. See below.

Every layer emits a sub-score. None of them emits a verdict - the verdict is
assembled in src.fusion from named, weighted sub-scores (rule 11).

Why L3 is a sum of squares and not a Mahalanobis distance
--------------------------------------------------------
The blueprint specifies robust Mahalanobis (MinCovDet) on the delta vector, on
the reasoning that a part can sit inside limits on every axis and still be an
impossible combination - "Iddq rising while propagation delay is flat".

That mechanism does not exist in this dataset. The delta-vector covariance is
diagonal: max off-diagonal Spearman |rho| among healthy parts is ~0.1, because
the generator draws an independent drift amplitude for every unaffected
parameter (rule 13; measured by src/diagnose_why.py). Of the misses that
Mahalanobis rescues, ZERO have every marginal |z| below 2.0 - it is not finding
parts that are quiet on each axis, it is finding parts that are moderately
elevated on two or three at once.

So Mahalanobis here is pooling marginal evidence, and with a diagonal
covariance the plain sum of squared marginal z is the same statistic without
the fitted covariance. Measured on the full dataset:

    score                                   PR-AUC   R@5%    R@10%
    L2 worst-case |z|, 20 features          0.3889   0.764   0.839
    MinCovDet Mahalanobis, 4-d delta        0.4038   0.776   0.874
    sum of squared z, 4 drift axes          0.4026   0.770   0.868
    ONE-SIDED sum of squares, 4 drift axes  0.4083   0.776   0.874   <- shipped

The one-sided form wins because higher is worse for every parameter in this
dataset (rule 4): a part drifting DOWN on a leakage current is not a defect,
and squaring a two-sided z credits it as if it were.

Ship the sum of squares because it ties or beats Mahalanobis and an inspector
can read it: "2.8 sigma on Iddq and 2.6 sigma on Tpd - neither trips its own
limit, but jointly that is a 1-in-500 part for this lot." MinCovDet stays in
the module as a comparison row, and it is the right generalisation for real fab
data where parameters genuinely do correlate - it simply has nothing extra to
exploit here.

Adding the early, curvature or 168h-level axes to the sum makes it worse
(0.378-0.403); the four drift axes alone carry the signal.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.covariance import MinCovDet

from src.features import (
    LOT_COL,
    PARAM_NAMES,
    PARAMS,
    build_features,
    robust_z,
    transform,
)

__all__ = [
    "DRIFT_AXES",
    "static_limit_flags",
    "dpat_score",
    "pooled_evidence_score",
    "mahalanobis_score",
    "delta_vector",
    "module_a_scores",
]

# L3 operates on the total-drift view only. Established empirically - see the
# table in the module docstring.
DRIFT_AXES = tuple(f"z_{p}_drift" for p in PARAM_NAMES)


# --------------------------------------------------------------- L1: static
def static_limit_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Datasheet USL breach at any read point, per parameter and overall.

    The layer we exist to beat. On this dataset it catches 0 of 174 latent
    defects, which is the problem statement quantified - keep it in the
    pipeline so the demo can show exactly that.

    Higher is worse for every parameter here, so there is no LSL to check
    (rule 4).
    """
    out = pd.DataFrame(index=df.index)
    for p in PARAM_NAMES:
        usl = PARAMS[p]["usl"]
        cols = [f"{p}_{t}h" for t in (0, 24, 96, 168) if f"{p}_{t}h" in df.columns]
        out[f"static_{p}"] = (df[cols] > usl).any(axis=1)
    out["static_any"] = out.any(axis=1)
    return out


# ----------------------------------------------------------------- L2: DPAT
def dpat_score(feat: pd.DataFrame, views: tuple[str, ...] | None = None) -> pd.Series:
    """Worst-case |robust z| across parameters and views.

    skipna is deliberate: a part with a dropped 96h read has no curvature and
    must still be scored on its remaining views rather than falling out of the
    screen.
    """
    cols = [c for c in feat.columns if c.startswith("z_")]
    if views is not None:
        cols = [c for c in cols if any(c.endswith(f"_{v}") for v in views)]
    if not cols:
        raise ValueError(f"no z-columns matched views={views}")
    return feat[cols].abs().max(axis=1, skipna=True)


# -------------------------------------------------------- L3: pooled evidence
def pooled_evidence_score(feat: pd.DataFrame,
                          axes: tuple[str, ...] = DRIFT_AXES,
                          one_sided: bool = True) -> pd.Series:
    """One-sided sum of squared robust z over the drift axes.

    Under a diagonal covariance this is the Mahalanobis distance with the
    fitted covariance replaced by the identity - the same pooling of marginal
    evidence, with nothing left to estimate and every term readable on its own.

    ``one_sided`` clips negative z to zero before squaring: higher is worse for
    every parameter in this dataset, so a downward drift is not evidence of a
    defect (rule 4). Set it False to reproduce the symmetric variant.

    The per-axis contributions are exactly the terms of the sum, so attribution
    is free - explain.py can rank them without SHAP.
    """
    missing = [a for a in axes if a not in feat.columns]
    if missing:
        raise KeyError(
            f"pooled_evidence_score needs {missing}; the drift view requires "
            "both the 0h and 168h reads, so this layer cannot run on an "
            "hour-24 frame."
        )
    z = feat[list(axes)]
    z = z.clip(lower=0) if one_sided else z
    # skipna: an absent axis contributes no evidence rather than killing the row
    return (z**2).sum(axis=1, skipna=True)


def pooled_evidence_contributions(feat: pd.DataFrame,
                                  axes: tuple[str, ...] = DRIFT_AXES,
                                  one_sided: bool = True) -> pd.DataFrame:
    """Per-axis terms of ``pooled_evidence_score``. Attribution, for free.

    Returns an empty frame (right index, no columns) when the drift view is
    absent, so an hour-24 caller gets "no contributions to report" rather than
    a KeyError. The reason-code engine reads this on every part.
    """
    present = [a for a in axes if a in feat.columns]
    if not present:
        return pd.DataFrame(index=feat.index)
    z = feat[present]
    z = z.clip(lower=0) if one_sided else z
    return (z**2).fillna(0.0)


# ---------------------------------------------- L3 comparison: Mahalanobis
def delta_vector(df: pd.DataFrame) -> pd.DataFrame:
    """[d log Iddq, d log Ileak, d Tpd, d Vol] over 0h -> 168h.

    On the statistics scale, so the current axes are log-ratios.
    """
    return pd.DataFrame(
        {p: transform(df[f"{p}_168h"], p) - transform(df[f"{p}_0h"], p)
         for p in PARAM_NAMES},
        index=df.index,
    )


def mahalanobis_score(df: pd.DataFrame, lot_col: str = LOT_COL,
                      random_state: int = 42) -> pd.Series:
    """Robust Mahalanobis distance on the delta vector, MinCovDet, per lot.

    Kept as the comparison row for L3, not as the shipped score.

    Fitted on ALL parts in the lot, not on healthy parts only. Fitting on the
    healthy subset would use labels that do not exist at inference time; it
    inflates the score and is not implementable. MinCovDet is robust enough to
    absorb the contamination - even L04 is only 18.6% defective, well inside
    the estimator's breakdown point.
    """
    delta = delta_vector(df)
    out = pd.Series(np.nan, index=df.index, dtype=float)
    for _, idx in df.groupby(lot_col).groups.items():
        X = delta.loc[idx].to_numpy(dtype=float)
        ok = np.isfinite(X).all(axis=1)
        mcd = MinCovDet(random_state=random_state).fit(X[ok])
        out.loc[np.asarray(idx)[ok]] = mcd.mahalanobis(X[ok])
    return out


# ------------------------------------------------------------------ bundle
def module_a_scores(df: pd.DataFrame, feat: pd.DataFrame | None = None,
                    with_mahalanobis: bool = True) -> pd.DataFrame:
    """All Module A sub-scores, one row per part.

    Sub-scores, not a verdict. src.fusion owns the weighting and the
    ACCEPT/WATCH/REJECT bands (rule 11).
    """
    feat = build_features(df) if feat is None else feat
    out = pd.DataFrame(index=df.index)
    out["l1_static"] = static_limit_flags(df)["static_any"].astype(int)
    out["l2_dpat_z"] = dpat_score(feat)

    # L3 needs the drift view, so it is unavailable on an hour-24 frame. Report
    # NaN there rather than raising: L1 and L2 still have something to say, and
    # a caller that mistakes a missing layer for a zero score would read the
    # part as safer than the evidence supports.
    have_drift = all(a in feat.columns for a in DRIFT_AXES)
    out["l3_pooled"] = pooled_evidence_score(feat) if have_drift else np.nan
    if with_mahalanobis:
        out["l3_maha_comparison"] = (
            mahalanobis_score(df) if f"{PARAM_NAMES[0]}_168h" in df.columns
            else np.nan)
    return out
