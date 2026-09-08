"""Tests for src/diagnose_misses.py and src/diagnose_why.py.

These two scripts stopped Module A from shipping a correlation detector for a
diagonal covariance. The tests below exist so that conclusion cannot be
silently lost - either by someone changing the generator, or by someone
re-reading the blueprint and rebuilding the thing it recommends.
"""

import numpy as np
import pandas as pd

from src.diagnose_misses import (
    bucket_misses,
    lot_inflation,
    pooled_z,
    view_series,
)
from src.diagnose_why import (
    correlation_null,
    delta_correlation,
    drift_vs_noise,
    max_offdiagonal_correlation,
    recall_by_carrying_parameter,
)
from src.features import PARAM_NAMES, build_features
from src.module_a import dpat_score


# ------------------------------------------------- the finding that matters
def test_delta_vector_covariance_is_diagonal(wide):
    """Rule 13, locked down.

    If this ever fails, the dataset has changed and the "no correlation break"
    conclusion must be re-derived BEFORE anyone reintroduces a covariance-based
    detector on the strength of the blueprint's recommendation.

    Calibrated against a permutation null rather than a bare threshold. With
    ~300 healthy parts per lot the standard error of a Spearman rho is ~0.056,
    and the statistic is a maximum over 36 pairwise comparisons, so the
    observed ~0.15 is what independence itself produces - a fixed cutoff would
    encode that coincidence instead of testing it.
    """
    observed = max_offdiagonal_correlation(wide)
    null = correlation_null(wide, n_draws=60, seed=0)
    p95 = float(np.quantile(null, 0.95))

    assert observed <= p95, (
        f"max off-diagonal |rho| is {observed:.3f}, above the permutation-null "
        f"p95 of {p95:.3f}. The delta vector now carries real joint structure - "
        "re-run src/diagnose_why.py and revisit Module A's L3 before claiming "
        "anything about correlation breaks."
    )


def test_correlation_must_be_measured_on_healthy_parts_only(wide):
    """Including defects induces correlation through the shared amplitude on
    the parameters each defect affects. Measuring it that way would flatter the
    case for a multivariate method - which is the mistake this guards."""
    healthy = delta_correlation(wide, lot="L04", healthy_only=True).to_numpy()
    everyone = delta_correlation(wide, lot="L04", healthy_only=False).to_numpy()
    for c in (healthy, everyone):
        np.fill_diagonal(c, 0.0)
    assert np.abs(everyone).max() > np.abs(healthy).max()


# --------------------------------------------------------- bucket semantics
def test_bucket_c_requires_every_margin_to_be_quiet():
    """The strict definition. "Mahalanobis fires" is circular - it only asks
    whether Mahalanobis fires - so (c) additionally demands that no single axis
    explains the flag."""
    rng = np.random.default_rng(0)
    n = 300
    rows = {"serial": [f"S{i:04d}" for i in range(n)], "lot": ["L01"] * n}
    for p in PARAM_NAMES:
        base = 10.0 if p == "Iddq_uA" else 3.2
        v0 = rng.normal(base, base * 0.05, n)
        rows.update({f"{p}_{t}h": v0 * (1 + 0.01 * t / 168) for t in (0, 24, 96, 168)})
    df = pd.DataFrame(rows)

    # One part with a single loud axis: high joint distance, but explained.
    df.loc[0, "Iddq_uA_168h"] = df.loc[0, "Iddq_uA_0h"] * 3.0

    b = bucket_misses(df, [0])
    assert not b.loc[0, "all_margins_quiet"]
    assert b.loc[0, "bucket"] != "c", (
        "a part whose flag is explained by one axis is not a correlation break"
    )


def test_bucket_b_needs_both_real_movement_and_a_wide_lot(wide):
    """Precedence check: (b) fires only when the part would be an outlier in a
    normal lot AND its own lot is wide on that axis."""
    latent = wide.index[wide.is_latent_defect == 1]
    b = bucket_misses(wide, latent[:120])
    for _, r in b[b.bucket == "b"].iterrows():
        assert r.z_pooled >= 4.0 and r.inflation >= 1.25


def test_buckets_are_exhaustive_and_exclusive(wide):
    b = bucket_misses(wide, wide.index[wide.is_latent_defect == 1][:80])
    assert set(b.bucket) <= {"a", "b", "c"}
    assert len(b) == 80


def test_maha_rescues_is_reported_separately_from_bucket_c(wide):
    """The two numbers must not be conflated: on this dataset Mahalanobis
    rescues many parts while bucket (c) stays near-empty, and that gap is the
    whole finding."""
    latent = wide.index[wide.is_latent_defect == 1]
    b = bucket_misses(wide, latent)
    assert int(b.maha_rescues.sum()) > int((b.bucket == "c").sum())


# ------------------------------------------------------- the discriminator
def test_pooled_z_and_lot_inflation_are_consistent(wide):
    """z_pooled / z_lot must equal sigma_lot / sigma_typ by construction."""
    feat = build_features(wide)
    zp = pooled_z(wide, views=("drift",))
    infl = lot_inflation(wide, views=("drift",))

    for p in PARAM_NAMES:
        ratio = (zp[f"{p}_drift"] / feat[f"z_{p}_drift"]).replace(
            [np.inf, -np.inf], np.nan).dropna()
        expected = infl[f"{p}_drift"].loc[ratio.index]
        np.testing.assert_allclose(ratio, expected, rtol=1e-9)


def test_view_series_matches_the_feature_module(wide):
    """The diagnostic must reproduce features.py exactly, or it is diagnosing
    a different pipeline than the one that ships."""
    from src.features import robust_z
    feat = build_features(wide)
    for p in PARAM_NAMES:
        for view in ("level_0h", "early", "drift"):
            f = view_series(wide, p, view)
            z = f.groupby(wide.lot).transform(robust_z)
            np.testing.assert_allclose(z, feat[f"z_{p}_{view}"], rtol=1e-9)


# ----------------------------------------------------------- the deck table
def test_recall_by_carrying_parameter_shows_the_metrology_blind_spot(wide):
    """Rule 14. The table that goes in the deck: recall follows drift_scale,
    not the model."""
    feat = build_features(wide)
    tab = recall_by_carrying_parameter(wide, dpat_score(feat), 4.5, feat)

    assert list(tab.columns) == ["missed", "caught", "recall", "drift_scale"]
    currents = tab[tab.drift_scale == 1.0].recall
    timing = tab[tab.drift_scale == 0.12].recall
    assert timing.max() < currents.min(), (
        "the timing/voltage blind spot has closed - re-check rule 14 and the "
        "sensitivity slide before claiming it is a metrology limit"
    )


def test_drift_vs_noise_shows_timing_sits_near_the_noise_floor(wide):
    t = drift_vs_noise(wide)
    assert t.loc["Iddq_uA", "frac_above_2x_noise"] > 0.7
    assert t.loc["Tpd_ns", "frac_above_2x_noise"] < 0.6
