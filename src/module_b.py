"""Module B - drift forecasting from the first 24 hours.

Predicts Value_168h from Value_0h and Value_24h ONLY, then converts the
predicted slope into an early-reject decision at hour 24 - freeing 144 oven
hours per rejected part on a scarce, capacity-limiting resource.

The constraint is the point: two input points, one output 144 hours later. With
two points you cannot fit a two-parameter curve per part, so the shape is fitted
globally and the magnitude per part.

    1. physics baseline   X(t) = X0 * (1 + A * (t/168)^n)
                          One global exponent n* per parameter, fitted on the
                          training folds. Per part, A solves from the single
                          delta available:
                              A_i = (X24/X0 - 1) / (24/168)^n*
                              X_168 = X0 * (1 + A_i)
                          Defensible in a design review, needs no training
                          infrastructure, and yields a physical quantity you can
                          plot: healthy parts settle (n < 1), defects accelerate.
    2. learned residual   gradient-boosted regressor given the physics forecast
                          as an input feature, plus the lot-relative block from
                          features.build_forecast_features. Stacking beats
                          either alone.
    3. quantile bound     a second regressor at alpha=0.90. The point estimate
                          is what MAE is reported on; the REJECT decision is
                          made on the upper bound, so a part is rejected when
                          even its optimistic forecast breaches the safety
                          slope. Conservative without costing MAE.

Everything is fitted under GroupKFold(groups=lot) (rule 6). The global exponent
counts as a fitted quantity and is re-fitted per fold; leaving it fitted on all
data would leak the test lots' 168h values into their own forecast.

Safety slope (blueprint 8.4) - defined two independent ways, stricter wins:

    S_mission    = (USL - V_0) / (mission_hours / AF)
                   AF = exp((Ea/k) * (1/T_use - 1/T_stress)), Ea ~ 0.7 eV
                   At 25 C use / 125 C stress, AF ~ 938, so 168 burn-in hours
                   is roughly 18 years of field life.
    S_population = median(slope_lot) + 4.5 * 1.4826 * MAD(slope_lot)

(a) says this part will not survive the mission; (b) says this part is not like
its siblings. Either is grounds for rejection. They are separate gates, not
min()'d into one number - they are in different units.

MEASURED: the mission gate essentially never binds on this dataset (it fires on
0.0-0.1% of parts per parameter). 168 burn-in hours at AF ~937 is 18 years,
while a 7-year mission is only 65.5 equivalent hours, so a part would have to
drift catastrophically inside the burn-in to fail it. The population gate is
doing all the work, and its k is calibrated from a budget rather than left at
the blueprint's 4.5 - see `calibrate_population_k`.

Measured results, and what they mean for the pitch
--------------------------------------------------
FORECAST QUALITY is real. Out-of-fold MAE on Value_168h, GroupKFold by lot:

    param       physics   +GBM   linear   last-value   n*
    Iddq_uA      1.711    1.313   2.352     1.835      0.41
    Ileak_nA     3.389    2.595   4.559     3.598      0.41
    Tpd_ns       0.113    0.157   0.388     0.113      0.00
    Vol_mV       7.573    8.624  26.231     7.545      0.00

The power law beats linear extrapolation by 27% / 26% / 71% / 71%, reproducing
the blueprint's claim. It is beaten by plain last-value-carried-forward on
Tpd_ns and Vol_mV - which the blueprint also predicts, and which is the same
metrology limit as rule 14: their fitted exponent is 0, meaning the data
supports no extrapolation at all on those axes.

DETECTION QUALITY at hour 24 is weak, and the forecasting adds nothing to it:

    score                                        PR-AUC   R@5%   R@10%
    Module A L3, full 168h drift  [the ceiling]  0.4083   0.776  0.874
    hour-24 pooled z of the raw EARLY delta      0.1539   0.270  0.328
    Module B, pooled z of physics forecast       0.1532   0.264  0.328
    Module B, pooled z of GBM forecast           0.1427   0.195  0.310
    Module B, slope ratio vs the safety slope    0.1248   0.138  0.236

The raw early delta ranks defects as well as anything built on top of it. That
is not a bug: a forecast is a near-monotone function of the early delta plus
the level, and the level carries no defect information, so no model recovers
signal the 24h read does not contain.

So do NOT pitch Module B as an equally accurate screen made earlier. The honest
claim is a triage layer:

    at hour 24 you catch ~33% of latent defects at a 10% overkill budget,
    against ~87% at hour 168 - and you free 144 oven-hours on every part you
    pull.

That trade is defensible on its own, and it is the answer to the first question
a reliability engineer will ask. `early_warning_score` exposes the ranking that
actually performs best; `early_reject` implements the blueprint's safety-slope
rule, which is the auditable per-part decision R-301 quotes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.evaluate import grouped_folds
from src.features import (
    FORECAST_FEATURE_NAMES,
    LOT_COL,
    PARAM_NAMES,
    PARAMS,
    build_forecast_features,
    robust_sigma,
    transform,
)

__all__ = [
    "EA_EV", "K_EV_PER_K", "T_USE_C", "T_STRESS_C", "MISSION_YEARS",
    "arrhenius_af", "equivalent_burnin_hours",
    "fit_global_exponent", "physics_forecast",
    "PowerLawForecaster", "ForecastResult",
    "forecast_all", "safety_slope", "early_reject", "early_warning_score",
    "calibrate_population_k",
]

# Arrhenius constants. Ea = 0.7 eV is the conventional default for the mixed
# failure mechanisms burn-in precipitates; it belongs on the slide as an
# assumption, not buried as a magic number.
EA_EV = 0.7
K_EV_PER_K = 8.617e-5
T_USE_C = 25.0
T_STRESS_C = 125.0
MISSION_YEARS = 7.0

# The quantile the reject decision is made on. Not 0.5: a screen should reject
# when even the optimistic case breaches.
REJECT_QUANTILE = 0.90

# Population safety slope: how far above its lot's median drift rate a part may
# sit. 4.5 rather than 6 because this is a REJECT gate that fusion re-weights,
# not a standalone limit.
POPULATION_K = 4.5

# The blueprint searches n in [0.3, 2.0]. Widened to include 0.
#
# At n = 0 the model degenerates exactly to last-value-carried-forward:
# (24/168)^0 = 1, so A = V24/V0 - 1 and X_168 = V0 * (1 + A) = V24. That is a
# meaningful hypothesis, not a degenerate one - it says all the drift this part
# will show has already happened by hour 24, which for a settling part is close
# to true.
#
# It matters because the MAE-optimal exponent for Tpd_ns and Vol_mV sits AT the
# boundary: their optimum is n -> 0, and on the blueprint's grid the physics
# model is therefore beaten by plain last-value. With 0 in the grid the fit can
# express "no extrapolable signal on this axis" instead of being clamped at
# 0.30 and losing. n* = 0 is then a reportable diagnostic in its own right, and
# it is the metrology finding (rule 14) showing up again inside Module B: the
# amplification factor 1/(24/168)^n is 7x at n=1, and amplifying an early delta
# that is mostly ATE noise costs more MAE than the drift it recovers.
_EXPONENT_GRID = np.round(np.arange(0.0, 2.01, 0.02), 2)


# ------------------------------------------------------------- Arrhenius
def arrhenius_af(ea_ev: float = EA_EV, t_use_c: float = T_USE_C,
                 t_stress_c: float = T_STRESS_C) -> float:
    """Acceleration factor between stress and use temperature.

    AF = exp((Ea/k) * (1/T_use - 1/T_stress)), temperatures in kelvin.
    """
    t_use, t_stress = t_use_c + 273.15, t_stress_c + 273.15
    return float(np.exp((ea_ev / K_EV_PER_K) * (1.0 / t_use - 1.0 / t_stress)))


def equivalent_burnin_hours(mission_years: float = MISSION_YEARS, **kw) -> float:
    """Burn-in hours equivalent to the mission. Mission hours / AF."""
    return mission_years * 365.25 * 24.0 / arrhenius_af(**kw)


# --------------------------------------------------------- physics model
def physics_forecast(v0: np.ndarray, v24: np.ndarray, n: float) -> np.ndarray:
    """X_168 = X0 * (1 + A),  A = (X24/X0 - 1) / (24/168)^n.

    Raw scale, not log: the power law is written in the measured units, and the
    amplitude A is a relative quantity so it transfers across lots.
    """
    v0 = np.asarray(v0, dtype=float)
    v24 = np.asarray(v24, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(v0 != 0, v24 / v0 - 1.0, np.nan)
    a = ratio / (24.0 / 168.0) ** n
    return v0 * (1.0 + a)


def fit_global_exponent(v0, v24, v168, grid=_EXPONENT_GRID) -> float:
    """One exponent per parameter, chosen to minimise MAE on the training set.

    MAE rather than MSE because the organisers' metric is MAE and because the
    squared loss would let the handful of gross failures pick the exponent for
    the whole population.
    """
    v0, v24, v168 = (np.asarray(x, dtype=float) for x in (v0, v24, v168))
    ok = np.isfinite(v0) & np.isfinite(v24) & np.isfinite(v168) & (v0 > 0)
    if ok.sum() == 0:
        return 1.0
    best_n, best_mae = float(grid[0]), np.inf
    for n in grid:
        pred = physics_forecast(v0[ok], v24[ok], float(n))
        mae = float(np.nanmean(np.abs(v168[ok] - pred)))
        if mae < best_mae:
            best_mae, best_n = mae, float(n)
    return best_n


# --------------------------------------------------------- the forecaster
@dataclass
class PowerLawForecaster:
    """Physics baseline, optionally stacked with a gradient-boosted residual.

    ``use_gbm=False`` gives the pure physics model - the 20-minute version that
    needs no training infrastructure and is the honest baseline the learned
    model must beat.
    """
    use_gbm: bool = True
    quantile: float = REJECT_QUANTILE
    random_state: int = 42
    exponents: dict[str, float] = field(default_factory=dict)
    _mean_models: dict = field(default_factory=dict, repr=False)
    _q_models: dict = field(default_factory=dict, repr=False)

    # ---------------------------------------------------------------- fit
    def fit(self, df: pd.DataFrame, lot_col: str = LOT_COL) -> "PowerLawForecaster":
        for p in PARAM_NAMES:
            v0 = df[f"{p}_0h"].to_numpy(float)
            v24 = df[f"{p}_24h"].to_numpy(float)
            v168 = df[f"{p}_168h"].to_numpy(float)
            n = fit_global_exponent(v0, v24, v168)
            self.exponents[p] = n

            if not self.use_gbm:
                continue

            X, y = self._design(df, p, n, lot_col)
            ok = np.isfinite(y)
            if ok.sum() < 50:
                continue
            self._mean_models[p] = self._make(objective="regression_l1").fit(
                X[ok], y[ok])
            self._q_models[p] = self._make(
                objective="quantile", alpha=self.quantile).fit(X[ok], y[ok])
        return self

    def _make(self, **kw):
        from lightgbm import LGBMRegressor
        return LGBMRegressor(
            n_estimators=300, learning_rate=0.05, num_leaves=15,
            min_child_samples=30, subsample=0.9, subsample_freq=1,
            colsample_bytree=0.9, random_state=self.random_state,
            verbose=-1, **kw)

    def _design(self, df, p, n, lot_col=LOT_COL) -> tuple[pd.DataFrame, np.ndarray]:
        """Feature matrix for one parameter. Hour-24 inputs only.

        The physics forecast is included as a column: stacking - giving the ML
        model the physics answer and letting it correct the residual - almost
        always beats either alone.
        """
        F = build_forecast_features(df, p, lot_col)
        X = F[FORECAST_FEATURE_NAMES].copy()
        X["physics"] = physics_forecast(
            df[f"{p}_0h"].to_numpy(float), df[f"{p}_24h"].to_numpy(float), n)
        y = (df[f"{p}_168h"].to_numpy(float)
             if f"{p}_168h" in df.columns else np.full(len(df), np.nan))
        return X, y

    # ------------------------------------------------------------ predict
    def predict(self, df: pd.DataFrame, lot_col: str = LOT_COL) -> pd.DataFrame:
        """Point forecast of Value_168h, one column per parameter."""
        out = {}
        for p in PARAM_NAMES:
            n = self.exponents.get(p, 1.0)
            phys = physics_forecast(df[f"{p}_0h"].to_numpy(float),
                                    df[f"{p}_24h"].to_numpy(float), n)
            if self.use_gbm and p in self._mean_models:
                X, _ = self._design(df, p, n, lot_col)
                pred = self._mean_models[p].predict(X)
                # Physics is the fallback wherever the design matrix is unusable.
                out[p] = np.where(np.isfinite(pred), pred, phys)
            else:
                out[p] = phys
        return pd.DataFrame(out, index=df.index)

    def predict_upper(self, df: pd.DataFrame, lot_col: str = LOT_COL) -> pd.DataFrame:
        """Upper bound at ``self.quantile``. What the REJECT decision uses.

        Without a quantile model this falls back to the point estimate, which
        makes the screen less conservative - never more.
        """
        point = self.predict(df, lot_col)
        out = {}
        for p in PARAM_NAMES:
            if self.use_gbm and p in self._q_models:
                X, _ = self._design(df, p, self.exponents.get(p, 1.0), lot_col)
                q = self._q_models[p].predict(X)
                # An upper bound below the point estimate is not a bound.
                out[p] = np.maximum(q, point[p].to_numpy())
            else:
                out[p] = point[p].to_numpy()
        return pd.DataFrame(out, index=df.index)

    def physics_only(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame(
            {p: physics_forecast(df[f"{p}_0h"].to_numpy(float),
                                 df[f"{p}_24h"].to_numpy(float),
                                 self.exponents.get(p, 1.0))
             for p in PARAM_NAMES}, index=df.index)


# ---------------------------------------------------- honest cross-validation
@dataclass
class ForecastResult:
    """Out-of-fold forecasts. The only ones a reported MAE may come from."""
    point: pd.DataFrame
    upper: pd.DataFrame
    physics: pd.DataFrame
    exponents_by_fold: list[dict]

    @property
    def mean_exponents(self) -> dict:
        return {p: float(np.mean([e[p] for e in self.exponents_by_fold]))
                for p in PARAM_NAMES}


def forecast_all(df: pd.DataFrame, use_gbm: bool = True, n_splits: int = 6,
                 lot_col: str = LOT_COL) -> ForecastResult:
    """Out-of-fold 168h forecasts under GroupKFold(groups=lot).

    Every part is predicted by a model that never saw its lot - including the
    global exponent, which is re-fitted per fold. Fitting the exponent once on
    all the data would leak each test lot's own 168h values into its forecast
    and quietly flatter the MAE.
    """
    point = pd.DataFrame(index=df.index, columns=PARAM_NAMES, dtype=float)
    upper = pd.DataFrame(index=df.index, columns=PARAM_NAMES, dtype=float)
    phys = pd.DataFrame(index=df.index, columns=PARAM_NAMES, dtype=float)
    exps = []

    for train_idx, test_idx in grouped_folds(df[lot_col].to_numpy(), n_splits):
        tr, te = df.iloc[train_idx], df.iloc[test_idx]
        m = PowerLawForecaster(use_gbm=use_gbm).fit(tr, lot_col)
        exps.append(dict(m.exponents))
        point.iloc[test_idx] = m.predict(te, lot_col).to_numpy()
        upper.iloc[test_idx] = m.predict_upper(te, lot_col).to_numpy()
        phys.iloc[test_idx] = m.physics_only(te).to_numpy()

    return ForecastResult(point=point.astype(float), upper=upper.astype(float),
                          physics=phys.astype(float), exponents_by_fold=exps)


# ----------------------------------------------------------- safety slope
def safety_slope(df: pd.DataFrame, predicted_168: pd.DataFrame,
                 param: str, lot_col: str = LOT_COL,
                 mission_years: float = MISSION_YEARS,
                 k: float = POPULATION_K) -> pd.DataFrame:
    """Mission-based and population-based slopes, and the stricter of the two.

    Slopes are in raw datasheet units per burn-in hour, because the mission
    limit is expressed against the USL and an inspector reads uA, not log-uA.

    Returns per-part columns: ``slope`` (the predicted drift rate),
    ``s_mission``, ``s_population``, ``safety`` (the minimum), and ``ratio``
    (slope / safety) - the quantity reason code R-301 quotes.
    """
    usl = PARAMS[param]["usl"]
    v0 = df[f"{param}_0h"].to_numpy(float)
    pred = predicted_168[param].to_numpy(float)

    # ---- (a) mission test, on the RAW scale, because the USL is a raw number.
    slope = (pred - v0) / 168.0
    t_eq = equivalent_burnin_hours(mission_years)
    s_mission = np.maximum(usl - v0, 0.0) / t_eq
    with np.errstate(divide="ignore", invalid="ignore"):
        mission_ratio = np.where(s_mission > 0, slope / s_mission, np.inf)

    # ---- (b) population test, on the STATISTICS scale (rule 1).
    #
    # Computed on log(x) for currents. On the raw scale a lognormal slope
    # distribution is so heavy-tailed that median + 4.5 * robust sigma lands
    # near its own 90th percentile - MAD is robust enough to ignore the tail
    # entirely - and the gate then rejects ~10% of every lot per parameter.
    # Log-transforming first is the same fix as everywhere else in this repo.
    t0 = transform(df[f"{param}_0h"], param).to_numpy(float)
    t168 = transform(pd.Series(pred, index=df.index), param).to_numpy(float)
    tslope = pd.Series((t168 - t0) / 168.0, index=df.index)
    med = tslope.groupby(df[lot_col]).transform("median")
    sig = tslope.groupby(df[lot_col]).transform(robust_sigma)
    s_population = (med + k * sig)
    with np.errstate(divide="ignore", invalid="ignore"):
        population_ratio = np.where(
            (s_population - med) > 0,
            (tslope - med) / (s_population - med), np.inf)

    # The two tests live in different units, so they are NOT min()'d into one
    # number - that would be comparing uA/h with log-uA/h. They are independent
    # gates and the STRICTER DECISION wins: a part is rejected if either fires.
    # (a) says this part will not survive the mission; (b) says it is not like
    # its siblings.
    ratio = np.maximum(mission_ratio, population_ratio)

    return pd.DataFrame(dict(
        slope=slope, log_slope=tslope.to_numpy(),
        s_mission=s_mission, mission_ratio=mission_ratio,
        s_population=s_population.to_numpy(), population_ratio=population_ratio,
        ratio=ratio), index=df.index)


def early_warning_score(df: pd.DataFrame, lot_col: str = LOT_COL) -> pd.Series:
    """Best available hour-24 ranking of latent-defect risk.

    One-sided pooled evidence on the EARLY delta, mirroring Module A's L3 but
    using the only movement visible at hour 24. Measured to rank at least as
    well as anything built on the forecast (see the module docstring), so this
    is what fusion consumes for the hour-24 sub-score - not the forecast.

    Uses no 96h or 168h data, so it is implementable at hour 24.
    """
    from src.features import robust_z
    cols = {}
    for p in PARAM_NAMES:
        early = (transform(df[f"{p}_24h"], p) - transform(df[f"{p}_0h"], p))
        cols[p] = early.groupby(df[lot_col]).transform(robust_z)
    # One-sided: higher is worse for every parameter here (rule 4).
    z = pd.DataFrame(cols, index=df.index).clip(lower=0)
    return (z**2).sum(axis=1, skipna=True)


def calibrate_population_k(df: pd.DataFrame, forecast_upper: pd.DataFrame,
                           target_flag_rate: float = 0.05,
                           lot_col: str = LOT_COL,
                           grid=np.arange(4.5, 60.1, 0.5)) -> float:
    """Pick the population-gate k from a budget instead of a magic number.

    The blueprint fixes k at 4.5. On this dataset that gate fires on 25.8% of
    parts, because the predicted-slope distribution stays heavy-tailed even on
    the log scale and MAD is robust enough to ignore its tail - so median + 4.5
    robust sigma sits near the distribution's own 90th percentile rather than
    out in the tail. A reason code that fires on a quarter of the lot tells an
    inspector nothing, and it blows the PDA gate five times over.

    So k is derived the way every other threshold in this repo is (rule 7): from
    a stated budget. Returns the smallest k whose gate flags no more than
    ``target_flag_rate`` of the parts, defaulting to the 5% PDA allowance.

    Deliberately UNSUPERVISED - it targets a flagged fraction, not an overkill
    rate, so it needs no labels and is implementable on a lot you have never
    seen. Calibrating against overkill would need ground truth that does not
    exist at inference time.
    """
    for k in grid:
        rate = early_reject(df, forecast_upper, lot_col=lot_col,
                            k=float(k)).reject_at_24h.mean()
        if rate <= target_flag_rate:
            return float(k)
    return float(grid[-1])


def early_reject(df: pd.DataFrame, forecast_upper: pd.DataFrame,
                 lot_col: str = LOT_COL, **kw) -> pd.DataFrame:
    """The hour-24 decision: does any parameter breach its safety slope?

    Evaluated on the UPPER bound, so a part is rejected when even its
    optimistic-case forecast breaches. Returns per-parameter ratios, the worst
    ratio, and the boolean decision.
    """
    ratios = {}
    for p in PARAM_NAMES:
        ratios[p] = safety_slope(df, forecast_upper, p, lot_col, **kw)["ratio"]
    R = pd.DataFrame(ratios, index=df.index)
    out = R.copy()
    out["worst_ratio"] = R.max(axis=1)
    out["worst_param"] = R.idxmax(axis=1)
    out["reject_at_24h"] = out["worst_ratio"] > 1.0
    return out
