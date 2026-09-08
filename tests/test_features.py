"""Tests for src/features.py.

Required by the definition of done: features.py is one of the two modules every
other module trusts, because training and inference must compute features
identically.

The tests that matter most here are the domain ones - log transform on currents
only, statistics per lot, and robust rather than mean-based spread. Those are
the rules most likely to be violated by a well-meaning edit.
"""

import numpy as np
import pandas as pd
import pytest

from src.features import (
    PARAM_NAMES,
    build_features,
    dpat_limits,
    early_feature_names,
    feature_names,
    lot_reference_table,
    robust_sigma,
    robust_z,
    transform,
)


# ------------------------------------------------------------ robust stats
def test_robust_sigma_equals_sigma_for_normal_data():
    """1.4826 * MAD is a sigma-equivalent under normality. That constant is
    the whole reason MAD is usable as a drop-in for std."""
    rng = np.random.default_rng(0)
    s = pd.Series(rng.normal(0.0, 2.0, 200_000))
    assert robust_sigma(s) == pytest.approx(2.0, rel=0.02)


def test_robust_z_is_zero_at_the_median():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    assert robust_z(s).iloc[2] == pytest.approx(0.0)


def test_robust_z_resists_masking():
    """The failure mode robust statistics exist to prevent.

    One large outlier inflates a standard deviation enough to hide itself. The
    median and MAD have a 50% breakdown point, so the same outlier scores two
    orders of magnitude higher on the robust scale.
    """
    values = np.append(np.arange(100, dtype=float), 10_000.0)
    s = pd.Series(values)

    z_robust = robust_z(s).iloc[-1]
    z_mean = (values[-1] - values.mean()) / values.std(ddof=1)

    assert z_mean < 11.0          # masked: looks like an ordinary tail value
    assert z_robust > 250.0       # unmissable
    assert z_robust > 20 * z_mean


def test_robust_sigma_falls_back_to_iqr_never_to_std():
    """Rule 2: no std anywhere in a spread used for an outlier score.

    When more than half the lot shares one value MAD is 0, and the fallback is
    IQR/1.35. When there is no spread at all the honest answer is 0.0 - no
    evidence about which part is the outlier - not a std dominated by the one
    extreme value.
    """
    # Seven of twelve parts share one value, so MAD collapses - but the block
    # sits at the bottom of the range, so the quartiles still straddle real
    # spread and IQR/1.35 rescues the estimate.
    mad_zero = pd.Series([5.0] * 7 + [9.0, 10.0, 11.0, 12.0, 13.0])
    assert (mad_zero - mad_zero.median()).abs().median() == 0.0
    assert robust_sigma(mad_zero) == pytest.approx(5.25 / 1.35)

    degenerate = pd.Series([7.0] * 10)
    assert robust_sigma(degenerate) == 0.0
    assert (robust_z(degenerate) == 0).all()     # not NaN, not inf


def test_dpat_limits_are_median_plus_minus_k_robust_sigma():
    s = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0])
    lo, hi = dpat_limits(s, k=6.0)
    sigma = robust_sigma(s)
    assert lo == pytest.approx(12.0 - 6 * sigma)
    assert hi == pytest.approx(12.0 + 6 * sigma)


# --------------------------------------------------------- transform rule
def test_currents_are_logged_and_timing_is_not():
    """Rule 1. The single most consequential line in the module."""
    v = pd.Series([10.0, 20.0])

    assert transform(v, "Iddq_uA").tolist() == pytest.approx(np.log([10.0, 20.0]).tolist())
    assert transform(v, "Ileak_nA").tolist() == pytest.approx(np.log([10.0, 20.0]).tolist())
    assert transform(v, "Tpd_ns").tolist() == pytest.approx([10.0, 20.0])
    assert transform(v, "Vol_mV").tolist() == pytest.approx([10.0, 20.0])


def test_non_positive_current_becomes_nan_not_negative_infinity():
    out = transform(pd.Series([10.0, 0.0, -1.0]), "Iddq_uA")
    assert np.isfinite(out.iloc[0])
    assert out.iloc[1:].isna().all()


# ------------------------------------------------------------ test frames
def _linear_part(x0: float, A: float, n: float) -> dict[int, float]:
    """Noise-free readings of X(t) = x0 * (1 + A * (t/168)^n)."""
    return {t: x0 * (1.0 + A * (t / 168.0) ** n) for t in (0, 24, 96, 168)}


def _frame(specs: list[dict]) -> pd.DataFrame:
    """Build a wide burn-in frame from per-part specs.

    Each spec is {lot, and per-parameter (x0, A, n)}. Parameters not named get
    a flat, defect-free trace.
    """
    rows = []
    defaults = {"Iddq_uA": 10.0, "Ileak_nA": 20.0, "Tpd_ns": 3.2, "Vol_mV": 210.0}
    for i, spec in enumerate(specs):
        row = {"serial": f"T-{i:04d}", "lot": spec["lot"]}
        for p in PARAM_NAMES:
            x0, A, n = spec.get(p, (defaults[p], 0.0, 1.0))
            for t, v in _linear_part(x0, A, n).items():
                row[f"{p}_{t}h"] = v
        rows.append(row)
    return pd.DataFrame(rows)


# --------------------------------------------------------- per-lot rule
def test_statistics_are_computed_per_lot_not_globally():
    """Rule 3, and the entire reason dynamic limits beat static ones.

    Two lots with different process centring. The part sitting exactly at its
    own lot's median must score z = 0 even though it is far from the median of
    the two lots pooled together.
    """
    rng = np.random.default_rng(7)
    specs = []
    # Five nominal lots and one shifted lot, the shape of the real dataset.
    # Odd count per lot, so each lot median is an actual part rather than an
    # interpolation between two.
    centres = {"L01": 10.0, "L02": 10.0, "L03": 10.0,
               "L04": 13.0, "L05": 10.0, "L06": 10.0}
    for lot, centre in centres.items():
        for _ in range(61):
            specs.append({"lot": lot,
                          "Iddq_uA": (centre * float(rng.lognormal(0, 0.05)), 0.0, 1.0)})
    df = _frame(specs)

    feat = build_features(df)
    z = feat["z_Iddq_uA_level_0h"]

    median_parts = {}
    for lot in centres:
        idx = df.index[df.lot == lot]
        med = df.loc[idx, "Iddq_uA_0h"].median()
        at_median = idx[df.loc[idx, "Iddq_uA_0h"] == med][0]
        median_parts[lot] = at_median
        # Per lot, the median part is by definition unremarkable.
        assert z.loc[at_median] == pytest.approx(0.0, abs=1e-12)

    # Pooled, the statistics are dominated by the five nominal lots, so the
    # perfectly ordinary median part of L04 is condemned as a >3 sigma outlier
    # purely for belonging to a lot that was centred elsewhere. This is the
    # whole reason dynamic limits beat static ones.
    pooled = robust_z(transform(df["Iddq_uA_0h"], "Iddq_uA"))
    assert abs(pooled.loc[median_parts["L04"]]) > 3.0
    assert abs(pooled.loc[median_parts["L01"]]) < 1.0


def test_log_scale_makes_drift_comparable_across_shifted_lots():
    """A lot offset is multiplicative for currents. On the log scale it becomes
    an additive shift that the per-lot median removes exactly, so two parts
    that are equally abnormal *for their own lot* get the same z."""
    rng = np.random.default_rng(11)
    draws = rng.lognormal(0.0, 0.18, 200)

    specs = [{"lot": "L01", "Iddq_uA": (10.0 * d, 0.0, 1.0)} for d in draws]
    specs += [{"lot": "L02", "Iddq_uA": (12.2 * d, 0.0, 1.0)} for d in draws]  # L04-style shift
    df = _frame(specs)

    feat = build_features(df)
    z = feat["z_Iddq_uA_level_0h"].to_numpy()

    np.testing.assert_allclose(z[:200], z[200:], rtol=1e-9, atol=1e-9)


# ------------------------------------------------------------- curvature
@pytest.mark.parametrize("n", [0.5, 1.0, 1.3, 1.6])
def test_curvature_reads_out_the_degradation_exponent(n):
    """Closed form: with equal A across the lot the ratio depends only on n.

        ratio(n) = (1 - (96/168)^n) * (168/24)^n / 3

    Perfectly linear (n = 1) gives exactly 1.0. That is the point of
    normalising each window by its own width - the blueprint's raw ratio would
    score a linear part at 3.0 and fire R-501 on the whole lot.
    """
    expected = (1 - (96 / 168) ** n) * (168 / 24) ** n / 3

    # Tpd is not log-transformed, so the closed form holds exactly.
    specs = [{"lot": "L01", "Tpd_ns": (3.2, 0.10, n)} for _ in range(40)]
    feat = build_features(_frame(specs))

    assert feat["curv_Tpd_ns"].iloc[0] == pytest.approx(expected, rel=1e-6)


def test_curvature_separates_settling_from_accelerating_parts():
    """Healthy parts settle (n < 1), defects accelerate (n > 1)."""
    rng = np.random.default_rng(3)
    healthy = [{"lot": "L01", "Tpd_ns": (3.2, float(rng.uniform(0.02, 0.06)),
                                         float(rng.uniform(0.35, 0.75)))}
               for _ in range(100)]
    defects = [{"lot": "L01", "Tpd_ns": (3.2, float(rng.uniform(0.18, 1.10)),
                                         float(rng.uniform(0.80, 1.60)))}
               for _ in range(10)]
    feat = build_features(_frame(healthy + defects))
    curv = feat["curv_Tpd_ns"]

    assert curv.iloc[:100].max() < curv.iloc[100:].min()


def test_curvature_denominator_floor_stops_a_flat_part_exploding():
    """A part whose early window is pure noise must not manufacture a huge
    curvature just because it divided by something near zero."""
    rng = np.random.default_rng(5)
    specs = [{"lot": "L01", "Tpd_ns": (3.2, float(rng.normal(0.0, 1e-6)), 1.0)}
             for _ in range(200)]
    feat = build_features(_frame(specs))

    assert np.isfinite(feat["curv_Tpd_ns"]).all()
    assert feat["curv_Tpd_ns"].abs().max() < 50.0


# --------------------------------------------------------- missing reads
def test_dropped_96h_read_yields_nan_curvature_not_a_fabricated_zero():
    """~1.2% of parts lose their 96h read to a handler drop. Filling the gap
    with 0.0 would assert "this part shows no acceleration", which the data
    does not support. The part is judged on its other four views instead."""
    specs = [{"lot": "L01", "Tpd_ns": (3.2, 0.05, 0.6)} for _ in range(60)]
    df = _frame(specs)
    df.loc[0, "Tpd_ns_96h"] = np.nan

    feat = build_features(df)

    assert np.isnan(feat.loc[0, "z_Tpd_ns_curvature"])
    for view in ("level_0h", "level_168h", "early", "drift"):
        assert np.isfinite(feat.loc[0, f"z_Tpd_ns_{view}"])

    # skipna aggregation still produces a usable score for that part.
    assert np.isfinite(feat.filter(like="z_").abs().max(axis=1).loc[0])


# ------------------------------------------------- hour-24 inference path
def test_hour_24_frame_emits_only_early_features():
    """The same function serves training and Module B's hour-24 path. Anything
    outside early_feature_names() would leak the answer into the question."""
    specs = [{"lot": "L01", "Iddq_uA": (10.0, 0.05, 0.6)} for _ in range(50)]
    df = _frame(specs)
    early_df = df[["serial", "lot"] + [f"{p}_{t}h" for p in PARAM_NAMES for t in (0, 24)]]

    feat = build_features(early_df)

    assert set(feat.columns) == set(early_feature_names())
    assert not [c for c in feat.columns if "168" in c or "curv" in c or "drift" in c]


def test_full_frame_is_a_superset_of_the_hour_24_frame():
    specs = [{"lot": "L01", "Iddq_uA": (10.0, 0.05, 0.6)} for _ in range(50)]
    feat = build_features(_frame(specs))
    assert set(early_feature_names()) <= set(feat.columns)


# ------------------------------------------------------------- contracts
def test_feature_names_are_stable_and_ordered():
    specs = [{"lot": "L01"} for _ in range(30)]
    feat = build_features(_frame(specs))
    assert list(feat.columns) == feature_names(feat.columns)
    assert len(feat.columns) == 6 * len(PARAM_NAMES)


def test_output_is_indexed_like_the_input_and_carries_no_labels():
    specs = [{"lot": "L01"} for _ in range(20)]
    df = _frame(specs)
    df["is_latent_defect"] = 0
    df.index = range(100, 120)

    feat = build_features(df)

    assert feat.index.tolist() == df.index.tolist()
    assert "is_latent_defect" not in feat.columns
    assert not [c for c in feat.columns if not c.startswith(("z_", "curv_"))]


def test_missing_grouping_column_raises():
    df = _frame([{"lot": "L01"}] * 5).drop(columns=["lot"])
    with pytest.raises(KeyError, match="lot"):
        build_features(df)


def test_missing_0h_column_raises():
    df = _frame([{"lot": "L01"}] * 5).drop(columns=["Iddq_uA_0h"])
    with pytest.raises(KeyError, match="0h"):
        build_features(df)


def test_lot_reference_table_reports_raw_units_for_reason_codes():
    """Rule 12: an inspector reads "31.2 uA against a lot median of 10.4 uA".
    The z-score is computed on the log scale; the quoted number must not be."""
    specs = [{"lot": "L01", "Iddq_uA": (10.0, 0.0, 1.0)} for _ in range(30)]
    ref = lot_reference_table(_frame(specs))

    row = ref[(ref.parameter == "Iddq_uA") & (ref.hours == 0) & (ref.lot == "L01")]
    assert row["median"].iloc[0] == pytest.approx(10.0)   # not log(10)
    assert row["unit"].iloc[0] == "uA"
    assert row["usl"].iloc[0] == 50.0
