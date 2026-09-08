"""
Baseline for both modules. Run AFTER generate_burnin_dataset.py.
Deliberately simple and fully explainable -- this is your Hour-6 checkpoint,
and the number every fancier model must beat.

Module A: Dynamic PAT (robust z on log-scale) + delta-drift z, per lot.
Module B: Power-law extrapolation of 168h from 0h and 24h only.
"""
import numpy as np
import pandas as pd
from sklearn.metrics import (precision_score, recall_score, fbeta_score,
                             average_precision_score, mean_absolute_error)

PARAMS = ["Iddq_uA", "Ileak_nA", "Tpd_ns", "Vol_mV"]
LOGP = {"Iddq_uA": True, "Ileak_nA": True, "Tpd_ns": False, "Vol_mV": False}
df = pd.read_csv("data/burnin_wide.csv")


def robust_z(s: pd.Series) -> pd.Series:
    """(x - median) / (1.4826 * MAD). The 1.4826 makes it a sigma-equivalent
    for normal data. Immune to the outliers it is trying to find."""
    med = s.median()
    mad = (s - med).abs().median()
    sigma = 1.4826 * mad if mad > 0 else s.std(ddof=1)
    return (s - med) / (sigma if sigma > 0 else 1.0)


# ---------------------------------------------------------------- MODULE A
feat = pd.DataFrame(index=df.index)
for p in PARAMS:
    v0, v24, v168 = [df[f"{p}_{t}h"] for t in (0, 24, 168)]
    if LOGP[p]:
        v0, v24, v168 = np.log(v0), np.log(v24), np.log(v168)
    for lot, g in df.groupby("lot"):
        i = g.index
        feat.loc[i, f"z_{p}_0h"] = robust_z(v0.loc[i])
        feat.loc[i, f"z_{p}_168h"] = robust_z(v168.loc[i])
        feat.loc[i, f"z_{p}_delta"] = robust_z((v24 - v0).loc[i])
        feat.loc[i, f"z_{p}_drift"] = robust_z((v168 - v0).loc[i])

# DPAT verdict: worst-case |z| across all parameters and views
score_A = feat.abs().max(axis=1)
y = df.is_latent_defect.values

for thr in (4.5, 6.0, 8.0):
    pred = (score_A > thr).astype(int)
    print(f"DPAT |z|>{thr}:  recall={recall_score(y, pred):.3f}  "
          f"precision={precision_score(y, pred, zero_division=0):.3f}  "
          f"F2={fbeta_score(y, pred, beta=2, zero_division=0):.3f}  "
          f"flagged={pred.sum()} ({100*pred.mean():.1f}% overkill budget)")
print(f"PR-AUC (ranking quality) = {average_precision_score(y, score_A):.3f}")

static = df.static_fail_168h.values
print(f"\nStatic datasheet limits alone: recall on latent defects = "
      f"{recall_score(y, static):.3f}  <-- the gap we exist to close")

# ---------------------------------------------------------------- MODULE B
# X(t) = X0 * (1 + A*(t/168)^n).  Fit ONE global n on training parts that
# have 168h; then per part A = (V24/V0 - 1)/(24/168)^n  ->  V168 = V0*(1+A).
print("\n--- Module B: power-law extrapolation, inputs = 0h and 24h only ---")
for p in PARAMS:
    v0, v24, v168 = [df[f"{p}_{t}h"].values for t in (0, 24, 168)]
    ok = (v0 > 0) & np.isfinite(v24)
    best_n, best_mae = None, np.inf
    for n in np.arange(0.3, 2.01, 0.05):
        A = (v24[ok] / v0[ok] - 1) / (24 / 168) ** n
        mae = mean_absolute_error(v168[ok], v0[ok] * (1 + A))
        if mae < best_mae:
            best_mae, best_n = mae, n
    naive = mean_absolute_error(v168[ok], v0[ok] + (v24[ok] - v0[ok]) * 7)  # linear
    hold = mean_absolute_error(v168[ok], v24[ok])                          # last value
    print(f"{p:10s} n*={best_n:.2f}  MAE={best_mae:.4f}   "
          f"(linear {naive:.4f} | last-value {hold:.4f})")
