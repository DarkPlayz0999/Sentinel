"""Tests for src/explain.py.

Explainability is a third of the marking scheme, and the failure mode is subtle:
a reason code that is technically emitted but says the wrong thing, quotes a log
value, or claims something the data does not support.
"""

import re

import pytest

from src.features import PARAM_NAMES, PARAMS, build_features
from src.explain import (
    MODEL_VERSION,
    Thresholds,
    drift_plot,
    lot_reason_codes,
    part_report,
    reason_codes,
    reason_codes_for_part,
    top_contributions,
)
from src.fusion import bands_for_pda, fuse, lot_pda_status
from src.module_b import early_reject, forecast_all


@pytest.fixture(scope="module")
def scored(wide):
    feat = build_features(wide)
    mb = early_reject(wide, forecast_all(wide, use_gbm=False).upper)
    fused = fuse(wide, feat, mb)
    return wide, feat, mb, fused


# ------------------------------------------------------------ the contract
def test_every_code_quotes_a_value_and_a_lot_reference(scored):
    """Rule 12. A code without both numbers is not auditable."""
    wide, feat, mb, _ = scored
    rc = reason_codes(wide, feat, mb, index=wide.index[:400])
    assert len(rc) > 0
    assert rc.feature_value.notna().all()
    assert rc.lot_reference_value.notna().all()
    assert (rc.message.str.len() > 40).all()


def test_messages_quote_raw_units_never_log_values(scored):
    """The statistics run on log(x) for currents; the sentence must not.

    A part whose Iddq is 31.2 uA must read '31.2 uA', not '3.44'.
    """
    wide, feat, mb, _ = scored
    rc = reason_codes(wide, feat, mb, index=wide.index)
    r101 = rc[rc.code == "R-101"]
    assert len(r101) > 0

    for _, row in r101.head(30).iterrows():
        p = row.contributing_feature.replace("z_", "").replace("_level_168h", "")
        actual = float(wide.loc[wide.serial == row.serial, f"{p}_168h"].iloc[0])
        assert f"{actual:.4g}" in row.message, row.message
        assert PARAMS[p]["unit"] in row.message


def test_r101_only_fires_inside_the_datasheet_limit_wording(scored):
    """R-101's whole point is 'within the datasheet limit but abnormal for this
    lot'. If it fires on a part that actually breaches, the sentence is false."""
    wide, feat, mb, _ = scored
    rc = reason_codes(wide, feat, mb, index=wide.index)
    for _, row in rc[rc.code == "R-101"].iterrows():
        if "Within the datasheet limit" in row.message:
            p = row.contributing_feature.replace("z_", "").replace("_level_168h", "")
            v = float(wide.loc[wide.serial == row.serial, f"{p}_168h"].iloc[0])
            assert v <= PARAMS[p]["usl"], f"{row.serial} breaches {p} but claims it does not"


def test_r401_does_not_claim_a_correlation_break(scored):
    """Rule 13. The covariance is diagonal, so the pooled score fires on parts
    moderately elevated on several axes - a real reason, but not an impossible
    combination. Saying otherwise would be unsupported by the data."""
    wide, feat, mb, _ = scored
    rc = reason_codes(wide, feat, mb, index=wide.index)
    r401 = rc[rc.code == "R-401"]
    assert len(r401) > 0
    joined = " ".join(r401.message).lower()
    for banned in ("correlation break", "impossible combination",
                   "no healthy part", "inconsistent"):
        assert banned not in joined, f"R-401 claims {banned!r}, which rule 13 forbids"
    assert "jointly rare" in joined or "combined" in joined


def test_codes_fire_only_above_their_stated_thresholds(scored):
    wide, feat, mb, _ = scored
    t = Thresholds()
    rc = reason_codes(wide, feat, mb, t, index=wide.index)
    for _, row in rc.iterrows():
        if row.code == "R-101":
            assert row.feature_value > t.level_z
        elif row.code == "R-201":
            assert row.feature_value > t.early_z
        elif row.code == "R-501":
            assert row.feature_value > t.curvature
        elif row.code == "R-401":
            assert row.feature_value > t.pooled


def test_a_quiet_part_earns_no_codes(scored):
    """No code is the correct output for a part with nothing wrong."""
    wide, feat, mb, fused = scored
    quiet = fused.risk_score.idxmin()
    assert reason_codes_for_part(wide, feat, quiet, mb) == []


def test_raising_a_threshold_can_only_remove_codes(scored):
    wide, feat, mb, _ = scored
    idx = wide.index[:300]
    strict = Thresholds(level_z=99, early_z=99, curvature=99, pooled=1e9,
                        slope_ratio=1e9)
    assert len(reason_codes(wide, feat, mb, strict, index=idx)) == 0


# ------------------------------------------------------------- R-601 lot
def test_r601_fires_on_the_bad_lot_only(scored):
    wide, feat, mb, fused = scored
    tuned = fuse(wide, feat, mb, bands=bands_for_pda(fused.risk_score))
    codes = lot_reason_codes(lot_pda_status(tuned))
    assert "L04" in set(codes.lot)
    for _, row in codes.iterrows():
        assert "PDA" in row.message and "%" in row.message


# ------------------------------------------------------------ attribution
def test_top_contributions_are_exact_not_approximated(scored):
    """For the robust-z layers the contribution IS the squared z - it is the
    decision, not a surrogate for it."""
    wide, feat, mb, _ = scored
    i = feat.index[0]
    top = top_contributions(feat, i, n=5)
    assert len(top) == 5
    assert top.abs_z.is_monotonic_decreasing
    scored = top[top.in_pooled_score & (top.z > 0)]
    for _, row in scored.iterrows():
        assert row.contribution == pytest.approx(row.z**2)


# ---------------------------------------------------------------- report
def test_part_report_is_auditable(scored):
    wide, feat, mb, fused = scored
    i = fused.risk_score.idxmax()
    rep = part_report(wide, feat, i, fused, mb)

    assert rep["model_version"] == MODEL_VERSION
    assert re.match(r"\d{4}-\d{2}-\d{2}T", rep["generated_utc"])
    assert rep["serial"] and rep["lot"]
    assert rep["verdict"] in {"ACCEPT", "WATCH", "REJECT"}
    assert 0 <= rep["risk_score"] <= 100
    assert len(rep["measured"]) == len(PARAM_NAMES)
    for m in rep["measured"]:
        assert "lot_median_h168" in m and m["unit"]


def test_drift_plot_renders_without_a_display(scored):
    import matplotlib
    matplotlib.use("Agg")
    wide, feat, mb, fused = scored
    i = fused.risk_score.idxmax()
    ax = drift_plot(wide, i, "Iddq_uA", forecast_168=float(wide.at[i, "Iddq_uA_24h"]) * 1.2)
    labels = " ".join(t.get_text() for t in ax.get_legend().get_texts())
    assert "lot" in labels and "forecast" in labels
    assert ax.get_xticks().tolist() == [0, 24, 96, 168]
