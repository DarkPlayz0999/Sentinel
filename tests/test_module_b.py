"""Tests for src/module_b.py."""

import numpy as np
import pandas as pd
import pytest

from src.features import PARAM_NAMES, PARAMS
from src.module_b import (
    PowerLawForecaster,
    arrhenius_af,
    early_reject,
    early_warning_score,
    equivalent_burnin_hours,
    fit_global_exponent,
    forecast_all,
    physics_forecast,
    safety_slope,
)


# ------------------------------------------------------------- Arrhenius
def test_arrhenius_reproduces_the_blueprint_acceleration_factor():
    """Ea = 0.7 eV, 25 C use, 125 C stress -> AF ~ 937, so 168 burn-in hours is
    about 18 years of field life. Both numbers are on the slide."""
    af = arrhenius_af()
    assert af == pytest.approx(937, rel=0.01)
    years = 168 * af / (365.25 * 24)
    assert years == pytest.approx(18.0, rel=0.02)


def test_equivalent_burnin_hours_shrinks_with_a_longer_mission():
    assert equivalent_burnin_hours(7.0) < equivalent_burnin_hours(14.0)
    assert equivalent_burnin_hours(7.0) == pytest.approx(65.5, rel=0.01)


# ---------------------------------------------------------- physics model
@pytest.mark.parametrize("n", [0.0, 0.4, 1.0, 1.6])
def test_physics_forecast_inverts_the_generating_power_law(n):
    """Given noise-free 0h and 24h reads from X(t) = X0(1 + A(t/168)^n) and the
    true n, the forecast must return the exact 168h value."""
    x0, A = 10.0, 0.35
    v24 = x0 * (1 + A * (24 / 168) ** n)
    v168 = x0 * (1 + A)
    assert physics_forecast([x0], [v24], n)[0] == pytest.approx(v168, rel=1e-9)


def test_exponent_zero_is_exactly_last_value_carried_forward():
    """The reason 0 is in the grid: it is a real hypothesis, not a degenerate
    one, and it is where Tpd_ns and Vol_mV land."""
    v0 = np.array([10.0, 3.2, 200.0])
    v24 = np.array([10.5, 3.25, 205.0])
    np.testing.assert_allclose(physics_forecast(v0, v24, 0.0), v24, rtol=1e-12)


def test_fit_global_exponent_recovers_a_known_exponent():
    rng = np.random.default_rng(0)
    x0 = rng.uniform(8, 12, 800)
    A = rng.uniform(0.02, 0.5, 800)
    true_n = 0.8
    v24 = x0 * (1 + A * (24 / 168) ** true_n)
    v168 = x0 * (1 + A)
    assert fit_global_exponent(x0, v24, v168) == pytest.approx(true_n, abs=0.06)


def test_forecast_beats_linear_extrapolation_on_the_currents(wide):
    """Linear extrapolation is exactly n = 1. The fitted exponent must beat it,
    which is the blueprint's 25-27% MAE claim."""
    for p in ("Iddq_uA", "Ileak_nA"):
        v0 = wide[f"{p}_0h"].to_numpy(float)
        v24 = wide[f"{p}_24h"].to_numpy(float)
        y = wide[f"{p}_168h"].to_numpy(float)
        n = fit_global_exponent(v0, v24, y)
        mae_fit = np.mean(np.abs(y - physics_forecast(v0, v24, n)))
        mae_lin = np.mean(np.abs(y - physics_forecast(v0, v24, 1.0)))
        assert mae_fit < 0.8 * mae_lin


# -------------------------------------------------------- no leakage, ever
def test_forecaster_never_reads_a_96h_or_168h_column(wide):
    """Module B's whole premise. Deleting the late columns must not change a
    single prediction - if it does, something is reading the answer."""
    m = PowerLawForecaster(use_gbm=False).fit(wide)
    full = m.predict(wide)

    early_only = wide.drop(columns=[f"{p}_{t}h" for p in PARAM_NAMES
                                    for t in (96, 168)])
    pd.testing.assert_frame_equal(full, m.predict(early_only))


def test_early_warning_score_needs_no_late_reads(wide):
    early_only = wide.drop(columns=[f"{p}_{t}h" for p in PARAM_NAMES
                                    for t in (96, 168)])
    pd.testing.assert_series_equal(early_warning_score(wide),
                                   early_warning_score(early_only))


def test_out_of_fold_forecasts_never_see_their_own_lot(wide):
    """Rule 6. The global exponent is a fitted quantity too, so it is re-fitted
    per fold - fitting it once on everything would leak each test lot's own
    168h values into its forecast."""
    res = forecast_all(wide, use_gbm=False, n_splits=6)
    assert res.point.notna().all().all()
    assert len(res.exponents_by_fold) == 6
    # Folds must actually differ, i.e. the exponent really was re-fitted.
    seen = {tuple(sorted(e.items())) for e in res.exponents_by_fold}
    assert len(seen) > 1


def test_gbm_stack_beats_physics_alone_on_the_currents(wide):
    res_p = forecast_all(wide, use_gbm=False)
    res_g = forecast_all(wide, use_gbm=True)
    for p in ("Iddq_uA", "Ileak_nA"):
        y = wide[f"{p}_168h"].to_numpy(float)
        mae_p = np.nanmean(np.abs(y - res_p.point[p].to_numpy()))
        mae_g = np.nanmean(np.abs(y - res_g.point[p].to_numpy()))
        assert mae_g < mae_p, f"{p}: GBM {mae_g:.4f} did not beat physics {mae_p:.4f}"


# ------------------------------------------------------------ safety slope
def test_safety_slope_keeps_the_two_gates_in_their_own_units(wide):
    """They are not min()'d into one number - that would compare uA/h against
    log-uA/h. Each is a ratio against its own limit, and the stricter decision
    wins."""
    res = forecast_all(wide, use_gbm=False)
    ss = safety_slope(wide, res.point, "Iddq_uA")

    assert {"mission_ratio", "population_ratio", "ratio"} <= set(ss.columns)
    np.testing.assert_allclose(
        ss.ratio, np.maximum(ss.mission_ratio, ss.population_ratio))


def test_mission_slope_is_looser_for_a_part_starting_further_from_the_usl(wide):
    """S_mission = (USL - V0)/T_eq, so more headroom means a laxer limit."""
    res = forecast_all(wide, use_gbm=False)
    ss = safety_slope(wide, res.point, "Iddq_uA")
    v0 = wide["Iddq_uA_0h"]
    low, high = v0.idxmin(), v0.idxmax()
    assert ss.at[low, "s_mission"] > ss.at[high, "s_mission"]


def test_population_slope_is_computed_on_the_log_scale_for_currents(wide):
    """Rule 1. On the raw scale a lognormal slope distribution is so
    heavy-tailed that median + 4.5 robust sigma sits near its own 90th
    percentile, and the gate rejects ~10% of every lot per parameter."""
    res = forecast_all(wide, use_gbm=False)
    ss = safety_slope(wide, res.point, "Iddq_uA")
    # log_slope must be the log-scale rate, not the raw one.
    assert (ss.log_slope.abs() < ss.slope.abs().max()).all()
    assert (ss.population_ratio > 1).mean() < 0.15


def test_early_reject_uses_the_upper_bound_and_is_more_conservative(wide):
    """The quantile bound exists so a part is rejected when even its optimistic
    forecast breaches. It may never reject FEWER parts than the point estimate."""
    res = forecast_all(wide, use_gbm=True)
    on_point = early_reject(wide, res.point).reject_at_24h.sum()
    on_upper = early_reject(wide, res.upper).reject_at_24h.sum()
    assert on_upper >= on_point


def test_early_reject_reports_which_parameter_drove_the_decision(wide):
    res = forecast_all(wide, use_gbm=False)
    rej = early_reject(wide, res.point)
    assert set(rej.worst_param.unique()) <= set(PARAM_NAMES)
    for i in rej.index[:200]:
        assert rej.at[i, "worst_ratio"] == pytest.approx(
            rej.at[i, rej.at[i, "worst_param"]])
