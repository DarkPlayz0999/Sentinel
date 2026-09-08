"""Tests for src/fusion.py."""

import numpy as np
import pandas as pd
import pytest

from src.features import PARAMS, build_features
from src.fusion import (
    PDA_LIMIT,
    Bands,
    RiskWeights,
    bands_for_pda,
    fuse,
    lot_pda_status,
    screening_risk_score,
    squash,
    sub_scores,
    verdict,
)


# ---------------------------------------------------------------- contracts
def test_weights_must_sum_to_one():
    RiskWeights()                                   # default is valid
    with pytest.raises(ValueError, match="sum to 1"):
        RiskWeights(static_margin=0.9)


def test_bands_must_be_ordered():
    Bands()
    with pytest.raises(ValueError, match="watch < reject"):
        Bands(watch=80.0, reject=40.0)


def test_squash_is_monotone_and_bounded():
    x = np.array([-5.0, 0.0, 1.0, 3.0, 6.0, 100.0])
    s = squash(x, 6.0)
    assert s.min() >= 0 and s.max() <= 100
    assert (np.diff(s) >= 0).all()
    assert squash([6.0], 6.0)[0] == pytest.approx(100.0)
    assert squash([3.0], 6.0)[0] == pytest.approx(50.0)


def test_squash_maps_nan_to_zero_not_to_a_flag_value():
    assert squash([np.nan], 6.0)[0] == 0.0


# ------------------------------------------------------------- sub-scores
def test_static_margin_measures_consumed_headroom_not_absolute_level():
    """The bug this replaced: V_168h / USL scores a healthy Tpd_ns part at
    71/100 for standing still, adding a ~21-point constant offset to every
    part. Consumed headroom scores a stable part at zero."""
    n = 40
    rows = {"serial": [f"S{i}" for i in range(n)], "lot": ["L01"] * n}
    for p, base in (("Iddq_uA", 10.0), ("Ileak_nA", 20.0),
                    ("Tpd_ns", 3.2), ("Vol_mV", 210.0)):
        for t in (0, 24, 96, 168):
            rows[f"{p}_{t}h"] = [base] * n
    df = pd.DataFrame(rows)

    # A part that did not move at all.
    assert sub_scores(df)["static_margin"].iloc[0] == pytest.approx(0.0)

    # A part that consumed exactly half its Tpd headroom.
    df2 = df.copy()
    half = 3.2 + 0.5 * (PARAMS["Tpd_ns"]["usl"] - 3.2)
    df2.loc[0, "Tpd_ns_168h"] = half
    assert sub_scores(df2)["static_margin"].iloc[0] == pytest.approx(50.0, abs=0.5)


def test_sub_scores_are_all_on_0_100_when_squashed(wide):
    s = sub_scores(wide)
    assert set(s.columns) == {"static_margin", "dynamic_outlier",
                              "predicted_drift", "multivariate", "curvature"}
    assert (s.to_numpy() >= 0).all() and (s.to_numpy() <= 100).all()


def test_unsquashed_sub_scores_preserve_ranking(wide):
    """squash_to_100=False exists for ranking comparisons. It must be a
    monotone view of the same quantity, or the comparison is meaningless."""
    feat = build_features(wide)
    sq = sub_scores(wide, feat)
    raw = sub_scores(wide, feat, squash_to_100=False)
    for c in ("dynamic_outlier", "multivariate", "curvature"):
        order_sq = sq[c].rank(method="min")
        order_raw = raw[c].rank(method="min")
        # Squashing may create ties at the ceiling but must never re-order.
        merged = pd.DataFrame({"sq": order_sq, "raw": order_raw}).sort_values("raw")
        assert (merged.sq.diff().dropna() >= 0).all()


def test_predicted_drift_is_zero_without_module_b(wide):
    s = sub_scores(wide, module_b=None)
    assert (s["predicted_drift"] == 0).all()


def test_missing_sub_score_redistributes_weight_instead_of_shrinking(wide):
    """Otherwise a part scored without Module B would silently look safer."""
    subs = sub_scores(wide, module_b=None)
    full = screening_risk_score(subs)
    without = screening_risk_score(subs.drop(columns=["predicted_drift"]))
    assert without.max() > full.max()          # weight went to the others
    assert (without <= 100.0001).all()


# ---------------------------------------------------------------- verdicts
def test_verdict_bands_are_applied_at_the_stated_edges():
    s = pd.Series([0.0, 39.9, 40.0, 69.9, 70.0, 100.0])
    v = verdict(s, Bands(watch=40, reject=70)).tolist()
    assert v == ["ACCEPT", "ACCEPT", "WATCH", "WATCH", "REJECT", "REJECT"]


def test_a_datasheet_breach_is_always_a_reject(wide):
    """The screen may add rejections to the datasheet, never remove them."""
    fused = fuse(wide)
    hard = fused.l1_static == 1
    assert hard.sum() > 0
    assert (fused.loc[hard, "verdict"] == "REJECT").all()


def test_fuse_carries_serial_and_lot_for_the_audit_trail(wide):
    fused = fuse(wide)
    assert list(fused.columns[:2]) == ["serial", "lot"]
    assert fused.index.equals(wide.index)


# --------------------------------------------------------------- PDA gate
def test_bands_for_pda_hits_the_reject_budget(wide):
    fused = fuse(wide)
    b = bands_for_pda(fused.risk_score, target_reject=0.05)
    retuned = fuse(wide, bands=b)
    frac = (retuned.verdict == "REJECT").mean()
    assert frac == pytest.approx(0.05, abs=0.02)


def test_watch_absorbs_recall_without_consuming_pda_budget(wide):
    """The point of three bands. REJECT stays inside the PDA gate while
    REJECT-or-WATCH catches far more."""
    fused = fuse(wide)
    b = bands_for_pda(fused.risk_score, target_reject=0.05)
    retuned = fuse(wide, bands=b)
    y = wide.is_latent_defect.to_numpy() == 1

    r = (retuned.verdict == "REJECT").to_numpy()
    rw = retuned.verdict.isin(["REJECT", "WATCH"]).to_numpy()

    assert (r & y).sum() / y.sum() < (rw & y).sum() / y.sum()
    assert lot_pda_status(retuned).reject_frac.median() <= PDA_LIMIT


def test_pda_status_flags_only_the_bad_lot(wide):
    """L04 has 3x the defect rate. It should be the lot that goes to review,
    and the healthy lots should not - that is the blueprint's worked example."""
    fused = fuse(wide)
    tab = lot_pda_status(fuse(wide, bands=bands_for_pda(fused.risk_score)))
    assert tab.loc["L04", "status"] == "LOT REVIEW"
    assert (tab.drop(index="L04").status == "OK").sum() >= 4


def test_pda_counts_reject_only_not_watch(wide):
    fused = fuse(wide)
    tab = lot_pda_status(fused)
    np.testing.assert_array_equal(
        tab.reject.to_numpy(),
        fused[fused.verdict == "REJECT"].groupby("lot").size()
             .reindex(tab.index, fill_value=0).to_numpy())
