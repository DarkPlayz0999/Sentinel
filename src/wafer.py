"""Wafer map - die grid coloured by screening risk.

The generator gives every part a wafer id and (x, y) die coordinates, so the
spatial view the blueprint lists as optional is available for free.

Two things it is good for:

    1. It is the most photogenic artefact in the demo. A grid of dies with a
       cluster of hot ones reads instantly, in a way a PR curve does not.
    2. Spatial clustering of defects is real in a fab - a scratch, a
       photolithography excursion, an edge effect - and "Good Die in a Bad
       Neighbourhood" screening exists because of it.

Honest caveat, stated here so nobody puts the wrong claim on a slide: the
generator draws (x, y) UNIFORMLY AT RANDOM and independently of a part's class,
so there is no spatial structure in this dataset to find. `spatial_clustering`
measures that rather than assuming it - it compares each flagged die's
neighbourhood against a permutation null, and on this data it reports no
clustering, which is the correct answer.

The view still earns its place: it is how an inspector would actually look at a
lot, and it is ready for real wafer data where the clustering is genuine.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["wafer_grid", "neighbour_risk", "spatial_clustering", "plot_wafer_map"]


def wafer_grid(df: pd.DataFrame, fused: pd.DataFrame, wafer: str,
               value: str = "risk_score") -> pd.DataFrame:
    """Dies of one wafer as a dense (y, x) grid of ``value``. NaN where empty."""
    sub = df[df.wafer == wafer]
    if sub.empty:
        raise KeyError(f"no dies on wafer {wafer!r}")
    v = fused.loc[sub.index, value]
    return (pd.DataFrame({"x": sub.x.to_numpy(), "y": sub.y.to_numpy(),
                          "v": v.to_numpy()})
            .pivot_table(index="y", columns="x", values="v", aggfunc="mean"))


def neighbour_risk(df: pd.DataFrame, fused: pd.DataFrame, radius: int = 3,
                   value: str = "risk_score") -> pd.Series:
    """Median risk of each die's neighbours within ``radius``, excluding itself.

    The "Good Die in a Bad Neighbourhood" statistic: a die whose own value is
    unremarkable but whose neighbourhood is hot is worth a second look.
    """
    out = pd.Series(np.nan, index=df.index, dtype=float)
    v = fused[value]
    for _, idx in df.groupby("wafer").groups.items():
        sub = df.loc[idx]
        xy = sub[["x", "y"]].to_numpy(float)
        vals = v.loc[idx].to_numpy(float)
        for k, i in enumerate(idx):
            d = np.abs(xy - xy[k]).max(axis=1)          # Chebyshev
            near = (d <= radius) & (d > 0)
            if near.any():
                out.loc[i] = float(np.median(vals[near]))
    return out


def spatial_clustering(df: pd.DataFrame, fused: pd.DataFrame,
                       verdict: str = "REJECT", radius: int = 3,
                       n_permutations: int = 200, seed: int = 0) -> dict:
    """Do flagged dies cluster on the wafer, or are they scattered?

    Statistic: the mean number of flagged neighbours a flagged die has, within
    ``radius``. Compared against a permutation null that reassigns the flags to
    random dies on the same wafers - preserving die positions, wafer sizes and
    the number of flags, and destroying only the spatial association.

    Returns the observed value, the null mean, an empirical p-value and a
    verdict string. Measuring this rather than asserting it is the point: on
    the shipped dataset the answer is "no clustering", because the generator
    places dies at random.
    """
    rng = np.random.default_rng(seed)
    flagged = (fused["verdict"] == verdict).to_numpy()

    def statistic(flags: np.ndarray) -> float:
        counts = []
        for _, idx in df.groupby("wafer").groups.items():
            pos = df.loc[idx, ["x", "y"]].to_numpy(float)
            f = flags[df.index.get_indexer(idx)]
            if f.sum() < 2:
                continue
            hot = pos[f]
            for k in range(len(hot)):
                d = np.abs(hot - hot[k]).max(axis=1)
                counts.append(int(((d <= radius) & (d > 0)).sum()))
        return float(np.mean(counts)) if counts else 0.0

    observed = statistic(flagged)
    null = np.empty(n_permutations)
    for j in range(n_permutations):
        shuffled = flagged.copy()
        rng.shuffle(shuffled)
        null[j] = statistic(shuffled)

    p = float((null >= observed).mean())
    return dict(
        observed=observed, null_mean=float(null.mean()),
        null_p95=float(np.quantile(null, 0.95)), p_value=p,
        n_flagged=int(flagged.sum()), radius=radius,
        clustered=bool(p < 0.05),
        verdict=("spatial clustering detected" if p < 0.05
                 else "no spatial clustering - flags are scattered, which is "
                      "the expected answer for randomly placed dies"),
    )


def plot_wafer_map(df: pd.DataFrame, fused: pd.DataFrame, wafer: str,
                   ax=None, value: str = "risk_score"):
    """Die grid coloured by risk, with rejected dies ringed."""
    import matplotlib.pyplot as plt

    grid = wafer_grid(df, fused, wafer, value)
    if ax is None:
        _, ax = plt.subplots(figsize=(6.0, 5.0))

    im = ax.imshow(grid.to_numpy(), origin="lower", cmap="magma",
                   vmin=0, vmax=100, interpolation="nearest",
                   extent=[grid.columns.min() - .5, grid.columns.max() + .5,
                           grid.index.min() - .5, grid.index.max() + .5])
    plt.colorbar(im, ax=ax, label="screening risk score", shrink=0.85)

    sub = df[df.wafer == wafer]
    rej = sub.index[fused.loc[sub.index, "verdict"] == "REJECT"]
    if len(rej):
        ax.scatter(df.loc[rej, "x"], df.loc[rej, "y"], s=48,
                   facecolors="none", edgecolors="cyan", linewidths=1.4,
                   label=f"REJECT ({len(rej)})")
        ax.legend(fontsize=8, loc="upper right")

    ax.set_title(f"Wafer {wafer} — {len(sub)} dies")
    ax.set_xlabel("die x")
    ax.set_ylabel("die y")
    return ax
