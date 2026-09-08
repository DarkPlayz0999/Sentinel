"""Tests for src/module_a.py."""

import numpy as np
import pandas as pd
import pytest

from src.features import PARAM_NAMES, PARAMS, build_features
from src.module_a import (
    DRIFT_AXES,
    dpat_score,
    mahalanobis_score,
    module_a_scores,
    pooled_evidence_contributions,
    pooled_evidence_score,
    static_limit_flags,
)


# ------------------------------------------------------------- L1: static
def test_static_limits_flag_a_breach_and_only_a_breach():
    df = pd.DataFrame({
        "serial": ["A", "B"], "lot": ["L01", "L01"],
        **{f"{p}_{t}h": [PARAMS[p]["usl"] * 0.5, PARAMS[p]["usl"] * 0.5]
           for p in PARAM_NAMES for t in (0, 24, 96, 168)},
    })
    df.loc[0, "Iddq_uA_168h"] = PARAMS["Iddq_uA"]["usl"] * 1.1

    out = static_limit_flags(df)
    assert out.loc[0, "static_Iddq_uA"] and out.loc[0, "static_any"]
    assert not out.loc[1, "static_any"]
    assert not out.loc[0, "static_Tpd_ns"]


def test_static_limits_catch_no_latent_defects(wide):
    """The problem statement, quantified. This is the demo's opening number."""
    flags = static_limit_flags(wide)["static_any"]
    latent = wide.is_latent_defect == 1
    assert int((flags & latent).sum()) == 0


# ------------------------------------------------------- L3: pooled evidence
def test_pooled_evidence_is_one_sided():
    """Higher is worse for every parameter here (rule 4), so a part drifting
    DOWN is not evidence of a defect and must contribute nothing."""
    feat = pd.DataFrame({a: [-5.0, 5.0, 0.0] for a in DRIFT_AXES})

    one_sided = pooled_evidence_score(feat)
    two_sided = pooled_evidence_score(feat, one_sided=False)

    assert one_sided.iloc[0] == pytest.approx(0.0)      # all four axes negative
    assert one_sided.iloc[1] == pytest.approx(4 * 25.0)
    assert two_sided.iloc[0] == pytest.approx(4 * 25.0)  # symmetric credits it


def test_pooled_evidence_contributions_sum_to_the_score():
    """Attribution is free: the contribution IS the squared z. explain.py
    depends on this holding exactly."""
    rng = np.random.default_rng(0)
    feat = pd.DataFrame(rng.normal(size=(50, 4)), columns=DRIFT_AXES)

    contrib = pooled_evidence_contributions(feat)
    np.testing.assert_allclose(contrib.sum(axis=1), pooled_evidence_score(feat))


def test_pooled_evidence_beats_worst_case_z_on_the_real_data(wide):
    """The measurement that decided what L3 ships. If a change makes this
    fail, the shipped score is no longer the best one available."""
    from src.evaluate import pr_auc

    feat = build_features(wide)
    y = wide.is_latent_defect.to_numpy()

    l2 = pr_auc(y, dpat_score(feat).fillna(0.0))
    l3 = pr_auc(y, pooled_evidence_score(feat).fillna(0.0))
    maha = pr_auc(y, mahalanobis_score(wide).fillna(0.0))

    assert l3 > l2, f"L3 {l3:.4f} no longer beats L2 {l2:.4f}"
    assert l3 >= maha - 0.005, (
        f"sum of squares {l3:.4f} has fallen behind MinCovDet {maha:.4f}; "
        "the ship decision assumed they tie"
    )


def test_pooled_evidence_refuses_an_hour_24_frame(wide):
    """L3 needs the drift view, which needs 168h. Module B's hour-24 path must
    get a clear error rather than a silently different score."""
    early = wide[["serial", "lot"]
                 + [f"{p}_{t}h" for p in PARAM_NAMES for t in (0, 24)]]
    feat = build_features(early)
    with pytest.raises(KeyError, match="hour-24"):
        pooled_evidence_score(feat)


# --------------------------------------------------------- L3 comparison
def test_mahalanobis_is_finite_per_lot_and_uses_no_labels(wide):
    m = mahalanobis_score(wide)
    assert m.notna().all()
    assert (m >= 0).all()

    # Fitting must not depend on the label column existing.
    stripped = wide.drop(columns=["is_latent_defect", "true_class"])
    pd.testing.assert_series_equal(m, mahalanobis_score(stripped))


# ------------------------------------------------------------- the bundle
def test_module_a_scores_emits_sub_scores_not_a_verdict(wide):
    """Rule 11: Module A never decides. Fusion weights named sub-scores."""
    s = module_a_scores(wide)
    assert set(s.columns) == {"l1_static", "l2_dpat_z", "l3_pooled",
                              "l3_maha_comparison"}
    assert not [c for c in s.columns if "verdict" in c or "reject" in c]
    assert s.index.equals(wide.index)
    assert s.notna().all().all()
