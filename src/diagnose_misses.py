"""Why did the screen miss these parts? Run this before proposing a new model.

    python -m src.diagnose_misses [n]

Prints, for the n lowest-scoring latent defects, every raw parameter at all
four read points, the lot median for each, and every robust z - then sorts them
into buckets, because each bucket implies a different lever.

    (a) subtle on every axis      the part genuinely barely moved. No
                                  reweighting finds it, univariate or
                                  multivariate: there is no signal in the reads.
    (b) masked by a wide lot      it DID move - it would be an outlier in a
                                  typical lot - but its own lot's robust sigma
                                  on that axis is inflated, dividing the z down.
                                  Lever: lot-health-aware normalisation.
    (c) correlation break         quiet on every single axis, yet the joint
                                  delta vector is one no healthy part produces.
                                  Lever: a genuinely multivariate method.

Bucket (c) is defined STRICTLY: a high joint distance AND every marginal
|z| below `QUIET_Z`. The loose definition - "Mahalanobis fires" - is circular,
since it only asks whether Mahalanobis fires. Under the strict test this
dataset has essentially no bucket (c) at all (rule 13), which is why Module A's
L3 ships a sum of squares rather than a covariance model. The count of parts
Mahalanobis would rescue is reported separately, as its own number, because it
is real and actionable even though it is not evidence of a correlation break.

The discriminator
-----------------
For each feature f, statistics taken per lot:

    centred   = f - median_lot(f)
    z_lot     = centred / sigma_lot(f)             <- what features.py emits
    sigma_typ = median over lots of sigma_lot(f)   <- a normal lot's spread
    z_pooled  = centred / sigma_typ                <- same numerator, typical
                                                      denominator

so z_pooled asks "how far from its own lot's centre is this part, in the units
a NORMAL lot would use", and z_pooled / z_lot is exactly the inflation factor
of that lot on that axis. Both are unsupervised, so anything found here is
implementable at inference time.
"""

from __future__ import annotations

import sys

import pandas as pd
from scipy.stats import chi2

from src.features import (
    LOT_COL,
    PARAM_NAMES,
    VIEWS,
    build_features,
    robust_sigma,
    transform,
)
from src.module_a import dpat_score, mahalanobis_score

__all__ = [
    "Z_REAL", "INFLATION", "QUIET_Z", "MAHA_P",
    "view_series", "pooled_z", "lot_inflation", "bucket_misses",
    "format_part_detail", "main",
]

# Stated here rather than buried: the bucket counts move with them, and a
# reader must be able to argue with the choice.
Z_REAL = 4.0      # |z_pooled| at which a part is "really moving" for a normal lot
INFLATION = 1.25  # sigma_lot / sigma_typ at which a lot counts as wide on an axis
QUIET_Z = 2.0     # every marginal below this = the joint distance is doing the work
MAHA_P = 0.99     # chi2 quantile, 4 dof


def view_series(df: pd.DataFrame, p: str, view: str,
                lot_col: str = LOT_COL) -> pd.Series:
    """The raw pre-z quantity behind each named view, on the statistics scale."""
    v = {t: transform(df[f"{p}_{t}h"], p) for t in (0, 24, 96, 168)}
    if view == "level_0h":
        return v[0]
    if view == "level_168h":
        return v[168]
    if view == "early":
        return v[24] - v[0]
    if view == "drift":
        return v[168] - v[0]
    if view == "curvature":
        rate_e, rate_l = (v[24] - v[0]) / 24.0, (v[168] - v[96]) / 72.0
        floor = rate_e.groupby(df[lot_col]).transform(robust_sigma)
        floor = floor.mask(floor <= 0, robust_sigma(rate_e) or 1e-12)
        return rate_l / (rate_e.abs() + floor)
    raise ValueError(f"unknown view {view!r}")


def _lot_stats(f: pd.Series, lot: pd.Series):
    med = f.groupby(lot).transform("median")
    sig = f.groupby(lot).transform(robust_sigma)
    typ = f.groupby(lot).apply(robust_sigma).median()
    return med, sig, (typ if typ and typ > 0 else 1.0)


def pooled_z(df: pd.DataFrame, views=tuple(VIEWS),
             lot_col: str = LOT_COL) -> pd.DataFrame:
    """Lot-centred deviation measured in a TYPICAL lot's spread units."""
    lot = df[lot_col]
    out = {}
    for p in PARAM_NAMES:
        for view in views:
            f = view_series(df, p, view, lot_col)
            med, _, typ = _lot_stats(f, lot)
            out[f"{p}_{view}"] = (f - med) / typ
    return pd.DataFrame(out, index=df.index)


def lot_inflation(df: pd.DataFrame, views=tuple(VIEWS),
                  lot_col: str = LOT_COL) -> pd.DataFrame:
    """sigma_lot / sigma_typical, per part and axis. >1 means a wide lot."""
    lot = df[lot_col]
    out = {}
    for p in PARAM_NAMES:
        for view in views:
            f = view_series(df, p, view, lot_col)
            _, sig, typ = _lot_stats(f, lot)
            out[f"{p}_{view}"] = sig / typ
    return pd.DataFrame(out, index=df.index)


def bucket_misses(df: pd.DataFrame, index=None, feat: pd.DataFrame | None = None,
                  lot_col: str = LOT_COL) -> pd.DataFrame:
    """Assign each part in ``index`` to bucket (a), (b) or (c).

    Precedence is (b) then (c) then (a): if a part's movement is real and
    would be visible in a normal lot, the cheap lever is lot-aware
    normalisation, not a multivariate model. ``maha_rescues`` is reported
    independently of the bucket, because Mahalanobis firing is not the same
    claim as a correlation break.
    """
    feat = build_features(df) if feat is None else feat
    idx = df.index if index is None else pd.Index(index)

    zp = pooled_z(df, lot_col=lot_col)
    infl = lot_inflation(df, lot_col=lot_col)
    maha = mahalanobis_score(df, lot_col=lot_col)
    thresh = chi2.ppf(MAHA_P, df=len(PARAM_NAMES))

    rows = []
    for i in idx:
        z = zp.loc[i].abs()
        axis, zmax = z.idxmax(), float(z.max())
        inflation = float(infl.loc[i, axis])
        m = float(maha.loc[i])
        quiet = bool((z < QUIET_Z).all())

        if zmax >= Z_REAL and inflation >= INFLATION:
            b = "b"
        elif m > thresh and quiet:
            b = "c"          # STRICT: joint distance with every margin quiet
        else:
            b = "a"

        rows.append(dict(
            serial=df.at[i, "serial"], lot=df.at[i, lot_col], bucket=b,
            dominant_axis=axis, z_pooled=zmax, inflation=inflation,
            mahalanobis=m, all_margins_quiet=quiet,
            maha_rescues=bool(m > thresh),
        ))
    return pd.DataFrame(rows, index=idx)


def format_part_detail(df: pd.DataFrame, feat: pd.DataFrame, i,
                       score: pd.Series, zp: pd.DataFrame,
                       lot_col: str = LOT_COL) -> str:
    """Raw reads, lot medians and every robust z, for one part."""
    r = df.loc[i]
    lot_rows = df[df[lot_col] == r[lot_col]]
    lines = [
        f"{'param':<10}{'0h':>10}{'24h':>10}{'96h':>10}{'168h':>10}{'drift%':>9}"
        f" | {'lotmed0h':>10}{'lotmed168h':>11} | "
        + "".join(f"{v:>9}" for v in VIEWS) + f"{'zpool':>7}"
    ]
    for p in PARAM_NAMES:
        vals = [r[f"{p}_{t}h"] for t in (0, 24, 96, 168)]
        dpct = 100 * (vals[3] - vals[0]) / vals[0]
        zs = [feat.loc[i, f"z_{p}_{v}"] for v in VIEWS]
        zpm = zp.loc[i, [f"{p}_{v}" for v in VIEWS]].abs().max()
        lines.append(
            f"{p:<10}"
            + "".join(f"{v:>10.3f}" if v == v else f"{'--':>10}" for v in vals)
            + f"{dpct:>+8.1f}%"
            + f" | {lot_rows[f'{p}_0h'].median():>10.3f}"
              f"{lot_rows[f'{p}_168h'].median():>11.3f} | "
            + "".join(f"{z:>+9.2f}" if z == z else f"{'--':>9}" for z in zs)
            + f"{zpm:>7.1f}"
        )
    return "\n".join(lines)


def main(n: int = 20) -> None:
    from pathlib import Path
    data = Path(__file__).resolve().parent.parent / "data" / "burnin_wide.csv"
    if not data.exists():
        raise SystemExit(f"{data} not found. Run: python src/generate_burnin_dataset.py")

    df = pd.read_csv(data)
    feat = build_features(df)
    score = dpat_score(feat)
    zp = pooled_z(df)

    latent = df.index[df.is_latent_defect == 1]
    worst = score.loc[latent].sort_values().index[:n]
    buckets = bucket_misses(df, worst, feat)

    print(f"{n} lowest-scoring latent defects, by L2 worst-case |robust z|")
    print(f"thresholds: z_pooled >= {Z_REAL}, inflation >= {INFLATION}, "
          f"all margins < {QUIET_Z}, maha > chi2({MAHA_P},4)"
          f" = {chi2.ppf(MAHA_P, 4):.2f}\n")

    for rank, i in enumerate(worst, 1):
        b = buckets.loc[i]
        print(f"--- {rank:>2}/{n}  {b.serial}  lot {b.lot}  score {score[i]:.2f}"
              f"  -> bucket ({b.bucket})")
        print(format_part_detail(df, feat, i, score, zp))
        print(f"{'':<10}dominant {b.dominant_axis}  z_pooled {b.z_pooled:.1f}  "
              f"inflation {b.inflation:.2f}x  maha {b.mahalanobis:.1f}"
              f"{'  [margins quiet]' if b.all_margins_quiet else ''}\n")

    names = {"a": "(a) subtle on every axis - no signal to find",
             "b": "(b) masked by a wide lot - inflated denominator",
             "c": "(c) correlation break - genuinely multivariate"}
    print("=" * 92)
    print(f"BUCKET COUNTS over the {n} lowest-scoring latent defects\n")
    for k in "abc":
        print(f"  {names[k]:<56}{int((buckets.bucket == k).sum()):>3} / {n}")
    print(f"\n  reported separately: Mahalanobis would flag       "
          f"{int(buckets.maha_rescues.sum()):>3} / {n}")
    print("  (not the same claim as (c) - see the module docstring)")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 20)
