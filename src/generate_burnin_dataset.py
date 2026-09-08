"""
CLEANSCREEN / BURN-IN ANOMALY DETECTION -- Synthetic Dataset Generator
=====================================================================
Creates a realistic Environmental Stress Screening (ESS) burn-in dataset
for developing Module A (dynamic outlier detection) and Module B (drift
prediction).

Physics baked in
----------------
* Parametric values are LOGNORMAL for currents (Iddq, leakage) and
  NORMAL for timing/voltage parameters -- this is what real ATE data
  looks like, and it is why plain mean +/- 3 sigma fails.
* Degradation follows a power law:  X(t) = X0 * (1 + A * (t/168)^n)
  - healthy parts: tiny A, sub-linear n (settling / burn-in relaxation)
  - latent defects: large A, super-linear n (accelerating degradation)
* Lot-to-lot offsets exist, so a STATIC limit tuned on lot 1 is wrong
  for lot 4. This is the whole point of Dynamic PAT.
* Measurement noise + a few missing 96h readings (handler drops).

Ground truth
------------
  true_class: 'healthy' | 'latent' | 'gross'
  is_latent_defect: 1 for 'latent' (the parts that PASS static limits at
                    168h but are degrading abnormally) -- THIS is the
                    label the anomaly detector is scored on.
  'gross' parts breach the datasheet limit by 168h; any dumb static
  check catches them, so they are not the interesting class.

Usage:  python generate_burnin_dataset.py
Output: data/burnin_wide.csv, data/burnin_long.csv,
        data/public_train.csv, data/hidden_test.csv, data/ground_truth.csv
"""

from pathlib import Path

import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)
TIMEPOINTS = [0, 24, 96, 168]          # hours at 125 C, per MIL-STD-883 M1015
OUTDIR = Path(__file__).resolve().parent.parent / "data"

# ---------------------------------------------------------------- parameters
# name: (distribution, lot-median, log-sigma or sigma, datasheet USL, unit,
#        higher_is_worse)
PARAMS = {
    "Iddq_uA":   dict(dist="lognormal", center=10.0, spread=0.18, usl=50.0,  unit="uA"),
    "Ileak_nA":  dict(dist="lognormal", center=20.0, spread=0.25, usl=200.0, unit="nA"),
    "Tpd_ns":    dict(dist="normal",    center=3.20, spread=0.075, usl=4.60, unit="ns"),
    "Vol_mV":    dict(dist="normal",    center=210.0, spread=11.0, usl=400.0, unit="mV"),
}

N_LOTS = 6
PARTS_PER_LOT = 350
MEAS_NOISE = 0.015          # 1.5% ATE repeatability
MISSING_96H_RATE = 0.012

# Per-parameter ATE repeatability, defaulting to the flat MEAS_NOISE above.
# The flat value is a simplification: on a real tester, relative repeatability
# on timing and voltage is far better than on currents, which span decades.
# `build(noise=...)` overrides it so src/sensitivity.py can quantify how much
# of the recall ceiling is metrology rather than algorithm - WITHOUT touching
# the committed dataset. Calling build() with no arguments reproduces
# data/*.csv byte for byte; tests/test_generator.py asserts exactly that.
def default_noise() -> dict:
    return {p: MEAS_NOISE for p in PARAMS}


def lot_profile(lot_id):
    """Each lot has its own process centering and spread. Lot 4 is the
    'bad wafer lot': shifted centre, wider spread, 3x latent rate."""
    if lot_id == 4:
        return dict(center_mult=1.22, spread_mult=1.45, latent_rate=0.18, gross_rate=0.045)
    center_mult = float(RNG.normal(1.0, 0.06))
    return dict(center_mult=center_mult, spread_mult=float(RNG.normal(1.0, 0.08)),
                latent_rate=0.055, gross_rate=0.025)


def draw_class(prof):
    u = RNG.random()
    if u < prof["gross_rate"]:
        return "gross"
    if u < prof["gross_rate"] + prof["latent_rate"]:
        return "latent"
    return "healthy"


def drift_coeffs(cls):
    """Return (A, n) of X(t) = X0 * (1 + A*(t/168)**n)."""
    if cls == "healthy":
        # heavy right tail: ~10% of good parts are naturally "wide" and will
        # look suspicious. This overlap is what creates false positives and
        # is the reason a naive 3-sigma rule scraps good silicon.
        base = abs(RNG.normal(0.03, 0.030))
        if RNG.random() < 0.10:
            base += RNG.uniform(0.05, 0.20)
        return base, RNG.uniform(0.35, 0.75)
    if cls == "latent":
        # overlaps the healthy tail at the low end -> genuinely hard
        return RNG.uniform(0.18, 1.10), RNG.uniform(0.80, 1.60)
    return RNG.uniform(2.5, 6.0), RNG.uniform(1.0, 2.0)   # gross


def baseline_value(p, prof):
    cfg = PARAMS[p]
    c = cfg["center"] * prof["center_mult"]
    s = cfg["spread"] * prof["spread_mult"]
    if cfg["dist"] == "lognormal":
        return float(RNG.lognormal(np.log(c), s))
    return float(RNG.normal(c, s))


def build(outdir=None, noise: dict | None = None, seed: int = 42,
          verbose: bool = True):
    """Generate the dataset.

    Arguments exist only so the sensitivity analysis can re-run the physics
    under a different metrology assumption. Defaults reproduce the committed
    CSVs exactly: the RNG is re-seeded here so repeated calls in one process
    stay deterministic, and `RNG.normal(0, scale)` consumes the same draws
    whatever the scale, so changing a noise value cannot shift the stream for
    any other parameter.
    """
    global RNG
    RNG = np.random.default_rng(seed)
    outdir = Path(OUTDIR if outdir is None else outdir)
    noise = {**default_noise(), **(noise or {})}

    rows = []
    for lot_id in range(1, N_LOTS + 1):
        prof = lot_profile(lot_id)
        for i in range(PARTS_PER_LOT):
            serial = f"L{lot_id:02d}-{i+1:04d}"
            cls = draw_class(prof)
            # One degradation amplitude per part, applied to the affected
            # parameters only.
            #
            # NOTE, corrected: an earlier comment here claimed the parameters
            # end up correlated and that this is what makes multivariate
            # detection pay off. They do not, and it is not. Every unaffected
            # parameter below draws its OWN independent drift_coeffs("healthy"),
            # and healthy parts draw all four independently, so the delta
            # vector has a diagonal covariance (max off-diagonal |rho| ~ 0.1,
            # measured). Adding a shared common-mode health factor does not
            # fix it - the per-parameter modulation and the 1-2 affected
            # parameters swamp the shared term.
            #
            # Consequence for Module A: multivariate methods still help here,
            # but by POOLING MARGINAL EVIDENCE across axes, not by detecting a
            # correlation break. See rule 13 in CLAUDE.md, and
            # src/diagnose_why.py which measures this.
            A_part, n_part = drift_coeffs(cls)
            # A real defect mechanism shows up in ONE or TWO parameters, not
            # all four, so a detector that only watches Iddq misses half the
            # population.
            affected = (list(PARAMS) if cls == "gross"
                        else list(RNG.choice(list(PARAMS),
                                             size=int(RNG.integers(1, 3)),
                                             replace=False)))
            rec = dict(serial=serial, lot=f"L{lot_id:02d}",
                       wafer=f"W{RNG.integers(1, 6):02d}",
                       x=int(RNG.integers(0, 60)), y=int(RNG.integers(0, 60)),
                       true_class=cls,
                       is_latent_defect=int(cls == "latent"))
            for p, cfg in PARAMS.items():
                x0 = baseline_value(p, prof)
                # timing/voltage params drift less than currents
                scale = 1.0 if cfg["dist"] == "lognormal" else 0.12
                if p in affected:
                    A_p, n_p = A_part, n_part
                else:
                    A_p, n_p = drift_coeffs("healthy")
                A = A_p * scale * float(RNG.normal(1.0, 0.25))
                n = n_p * float(RNG.normal(1.0, 0.10))
                for t in TIMEPOINTS:
                    true_v = x0 * (1.0 + A * (t / 168.0) ** n)
                    meas = true_v * (1.0 + RNG.normal(0.0, noise[p]))
                    if t == 96 and RNG.random() < MISSING_96H_RATE:
                        meas = np.nan
                    rec[f"{p}_{t}h"] = round(meas, 4) if meas == meas else np.nan
            rows.append(rec)

    df = pd.DataFrame(rows)

    # a real screen removes hard failures; mark whether static limits catch it
    static_fail = np.zeros(len(df), dtype=bool)
    for p, cfg in PARAMS.items():
        static_fail |= (df[f"{p}_168h"] > cfg["usl"]).fillna(False).values
    df["static_fail_168h"] = static_fail.astype(int)

    outdir.mkdir(parents=True, exist_ok=True)
    df.to_csv(outdir / "burnin_wide.csv", index=False)

    # long / tidy format for time-series work
    long_rows = []
    for _, r in df.iterrows():
        for t in TIMEPOINTS:
            row = dict(serial=r.serial, lot=r.lot, wafer=r.wafer, hours=t)
            for p in PARAMS:
                row[p] = r[f"{p}_{t}h"]
            long_rows.append(row)
    pd.DataFrame(long_rows).to_csv(outdir / "burnin_long.csv", index=False)

    # ---- competition-style split: public train (labels+168h) / hidden test
    idx = RNG.permutation(len(df))
    n_train = int(0.6 * len(df))
    train, test = df.iloc[idx[:n_train]].copy(), df.iloc[idx[n_train:]].copy()

    train.to_csv(outdir / "public_train.csv", index=False)

    hidden_cols = [c for c in test.columns
                   if c.endswith("_168h") or c in ("true_class", "is_latent_defect",
                                                   "static_fail_168h")]
    test.drop(columns=hidden_cols).to_csv(outdir / "hidden_test.csv", index=False)
    test[["serial"] + hidden_cols].to_csv(outdir / "ground_truth.csv", index=False)

    # ---- sanity report
    if not verbose:
        return df
    print(f"parts: {len(df)}   lots: {N_LOTS}")
    print(df.true_class.value_counts().to_string())
    n_latent = int(df.is_latent_defect.sum())
    escapes = int(((df.is_latent_defect == 1) & (df.static_fail_168h == 0)).sum())
    print(f"\nlatent defects: {n_latent}")
    print(f"latent defects that PASS static datasheet limits at 168h: "
          f"{escapes} ({100*escapes/n_latent:.1f}%)  <-- the escapes to catch")
    for p, cfg in PARAMS.items():
        col = df[f"{p}_0h"]
        print(f"  {p:10s} 0h median={col.median():8.3f}  "
              f"168h median={df[f'{p}_168h'].median():8.3f}  USL={cfg['usl']}")
    print(f"\nwritten to {outdir}")


if __name__ == "__main__":
    build()
