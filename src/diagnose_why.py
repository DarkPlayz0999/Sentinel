"""Why is recall stuck? Measures the two things that bound it.

    python -m src.diagnose_why

This is the script that stopped Module A from shipping a correlation detector
for a diagonal covariance. Run it after any change that moves recall, before
concluding anything about which model to build next.

It answers two questions with measurements rather than intuition:

1. Is there joint structure for a multivariate method to exploit?
   Spearman correlation of the delta vector among healthy parts, per lot. If
   this is diagonal, Mahalanobis degenerates to pooled marginal evidence and a
   plain sum of squares is the same statistic with nothing to estimate
   (rule 13).

2. Where is the recall actually going?
   Recall split by which parameter carries each defect, against that
   parameter's drift magnitude and the measurement noise it sits on. On this
   dataset the answer is metrology, not modelling: defects carried by the two
   parameters whose drift is scaled to 0.12 sit barely above a flat 1.5% ATE
   noise floor, and no detector recovers signal that was never measured
   (rule 14). src/sensitivity.py quantifies that directly.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.evaluate import pr_auc, recall_at_overkill
from src.features import PARAM_NAMES, PARAMS, build_features, robust_sigma
from src.generate_burnin_dataset import MEAS_NOISE
from src.module_a import (
    DRIFT_AXES,
    delta_vector,
    dpat_score,
    mahalanobis_score,
    pooled_evidence_score,
)

__all__ = [
    "delta_correlation",
    "max_offdiagonal_correlation",
    "correlation_null",
    "drift_vs_noise",
    "recall_by_carrying_parameter",
    "main",
]


def delta_correlation(df: pd.DataFrame, lot: str | None = None,
                      healthy_only: bool = True) -> pd.DataFrame:
    """Spearman correlation of the delta vector.

    Uses labels to restrict to healthy parts, which is legitimate here - this
    is an offline diagnostic, not a deployed model. Restricting matters:
    including defects induces correlation through the shared amplitude on the
    one or two parameters each defect affects, which would flatter the case for
    a multivariate method.
    """
    d = delta_vector(df)
    mask = pd.Series(True, index=df.index)
    if healthy_only and "true_class" in df.columns:
        mask &= df.true_class == "healthy"
    if lot is not None:
        mask &= df.lot == lot
    return d.loc[mask].corr(method="spearman")


def max_offdiagonal_correlation(df: pd.DataFrame, healthy_only: bool = True) -> float:
    """Worst |rho| off the diagonal, over every lot. The number in rule 13."""
    worst = 0.0
    for lot in df.lot.unique():
        c = delta_correlation(df, lot=lot, healthy_only=healthy_only).to_numpy()
        np.fill_diagonal(c, 0.0)
        worst = max(worst, float(np.nanmax(np.abs(c))))
    return worst


def correlation_null(df: pd.DataFrame, n_draws: int = 200,
                     seed: int = 0) -> np.ndarray:
    """Permutation null for `max_offdiagonal_correlation`.

    Shuffles each delta axis independently within each lot. That destroys any
    real dependence while preserving the marginals, the lot structure and the
    sample sizes, so the resulting distribution is what the statistic looks
    like when the true correlation is exactly zero.

    Needed because a raw threshold is not interpretable. With ~300 healthy
    parts per lot the standard error of a Spearman rho is ~0.056, and the
    statistic is a maximum over 6 lots x 6 pairs = 36 comparisons, so a value
    near 0.15 is the *expected* result under independence rather than evidence
    of structure. Compare the observation to this null, not to a constant.
    """
    rng = np.random.default_rng(seed)
    d = delta_vector(df)
    healthy = (df.true_class == "healthy"
               if "true_class" in df.columns else pd.Series(True, index=df.index))
    groups = df.groupby("lot").groups

    out = np.empty(n_draws)
    for k in range(n_draws):
        perm = d.copy()
        for _, idx in groups.items():
            for col in perm.columns:
                vals = perm.loc[idx, col].to_numpy().copy()
                rng.shuffle(vals)
                perm.loc[idx, col] = vals
        worst = 0.0
        for _, idx in groups.items():
            sub = perm.loc[idx[healthy.loc[idx]]]
            c = sub.corr(method="spearman").to_numpy()
            np.fill_diagonal(c, 0.0)
            worst = max(worst, float(np.nanmax(np.abs(c))))
        out[k] = worst
    return out


def drift_vs_noise(df: pd.DataFrame, noise: dict | None = None) -> pd.DataFrame:
    """Relative drift of latent defects per parameter, against the noise floor."""
    noise = noise or {p: MEAS_NOISE for p in PARAM_NAMES}
    latent = df.index[df.is_latent_defect == 1]
    rows = []
    for p in PARAM_NAMES:
        rel = ((df[f"{p}_168h"] - df[f"{p}_0h"]) / df[f"{p}_0h"]).loc[latent].abs()
        rows.append(dict(
            parameter=p,
            drift_scale=1.0 if PARAMS[p]["is_current"] else 0.12,
            noise=noise[p],
            median_drift=float(rel.median()),
            p90_drift=float(rel.quantile(0.90)),
            frac_above_2x_noise=float((rel > 2 * noise[p]).mean()),
        ))
    return pd.DataFrame(rows).set_index("parameter")


def recall_by_carrying_parameter(df: pd.DataFrame, score: pd.Series,
                                 threshold: float,
                                 feat: pd.DataFrame | None = None) -> pd.DataFrame:
    """Recall split by which parameter carries each defect's largest drift.

    The table to put in the deck: it says exactly where the screen is blind,
    and pairs with the sensitivity analysis to say why.
    """
    feat = build_features(df) if feat is None else feat
    latent = df.index[df.is_latent_defect == 1]
    carried = feat.loc[latent, list(DRIFT_AXES)].abs().idxmax(axis=1)
    carried = carried.str.replace("z_", "", regex=False).str.replace("_drift", "", regex=False)
    caught = score.loc[latent] >= threshold

    tab = pd.crosstab(carried, caught)
    for col in (False, True):
        if col not in tab.columns:
            tab[col] = 0
    tab = tab.rename(columns={False: "missed", True: "caught"})
    tab["recall"] = (tab.caught / (tab.caught + tab.missed)).round(3)
    tab["drift_scale"] = [1.0 if PARAMS[p]["is_current"] else 0.12 for p in tab.index]
    return tab[["missed", "caught", "recall", "drift_scale"]]


def main() -> None:
    data = Path(__file__).resolve().parent.parent / "data" / "burnin_wide.csv"
    if not data.exists():
        raise SystemExit(f"{data} not found. Run: python src/generate_burnin_dataset.py")

    df = pd.read_csv(data)
    feat = build_features(df)
    y = df.is_latent_defect.to_numpy()
    healthy = (df.true_class == "healthy").to_numpy()

    print("1. IS THERE JOINT STRUCTURE TO EXPLOIT?")
    print("   Spearman correlation of the delta vector, healthy parts, lot L01\n")
    print(delta_correlation(df, lot="L01").round(3).to_string())
    worst = max_offdiagonal_correlation(df)
    null = correlation_null(df, n_draws=200)
    p95 = float(np.quantile(null, 0.95))
    print(f"\n   worst |rho| off-diagonal across all six lots: {worst:.3f}")
    print("   permutation null (dependence destroyed by construction):")
    print(f"     mean {null.mean():.3f}   p95 {p95:.3f}   max {null.max():.3f}")
    verdict = ("INDISTINGUISHABLE FROM ZERO" if worst <= p95
               else "REAL STRUCTURE - revisit Module A L3 before shipping")
    print(f"   observed {worst:.3f} vs null p95 {p95:.3f}  ->  {verdict}")
    print("   -> a bare threshold would not be interpretable: with ~300 healthy")
    print("      parts per lot and 36 pairwise comparisons, ~0.15 is what")
    print("      independence itself produces. Mahalanobis has no correlation to")
    print("      exploit here; it pools marginal evidence, as a sum of squares")
    print("      also does - with nothing left to estimate.\n")

    print("=" * 78)
    print("2. WHERE IS THE RECALL GOING?\n")
    print(f"   relative drift of latent defects vs the {100*MEAS_NOISE:.1f}% noise floor")
    print(drift_vs_noise(df).round(3).to_string())

    score = dpat_score(feat)
    print(f"\n   recall by carrying parameter, at L2 |z| >= 4.5")
    print(recall_by_carrying_parameter(df, score, 4.5, feat).to_string())
    print("\n   -> the blind spot follows drift_scale, not the model. See")
    print("      src/sensitivity.py for what that costs in recall.\n")

    print("=" * 78)
    print("3. SCORE COMPARISON\n")
    pooled = pooled_evidence_score(feat)
    maha = mahalanobis_score(df)
    print(f"{'score':<44}{'PR-AUC':>9}{'R@5%':>8}{'R@10%':>8}")
    for name, s in [("L2 worst-case |z|, 20 features", score),
                    ("MinCovDet Mahalanobis (comparison)", maha),
                    ("L3 one-sided sum of squares (shipped)", pooled)]:
        v = s.fillna(0.0).to_numpy()
        print(f"{name:<44}{pr_auc(y, v):>9.4f}"
              f"{recall_at_overkill(y, v, 0.05, healthy)['recall']:>8.3f}"
              f"{recall_at_overkill(y, v, 0.10, healthy)['recall']:>8.3f}")


if __name__ == "__main__":
    main()
