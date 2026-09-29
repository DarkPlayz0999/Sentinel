"""One call that runs the whole screen. Imported by the API, the dashboard and
the demo script so all three report identical numbers.

    from src.pipeline import screen
    result = screen(df)

Nothing here computes a feature or a metric of its own - it wires together
features.py, module_a.py, module_b.py, fusion.py and explain.py in the one
order they are meant to run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.explain import lot_reason_codes, reason_codes
from src.features import LOT_COL, PARAM_NAMES, build_features
from src.fusion import Bands, RiskWeights, bands_for_pda, fuse, lot_pda_status
from src.module_a import module_a_scores
from src.module_b import (PowerLawForecaster, calibrate_population_k,
                          early_reject, early_warning_score, forecast_all)

__all__ = ["ScreenResult", "ModuleBResult", "screen", "run_module_b",
           "combine", "load_wide", "DATA"]

DATA = Path(__file__).resolve().parent.parent / "data" / "burnin_wide.csv"


def load_wide(path: Path | str | None = None) -> pd.DataFrame:
    p = Path(DATA if path is None else path)
    if not p.exists():
        raise SystemExit(
            f"{p} not found. Run:  python src/generate_burnin_dataset.py")
    return pd.read_csv(p)


@dataclass
class ScreenResult:
    """Everything the dashboard, the API and the report generator need."""
    features: pd.DataFrame
    module_a: pd.DataFrame
    forecast_point: pd.DataFrame
    forecast_upper: pd.DataFrame
    module_b: pd.DataFrame
    early_score: pd.Series
    fused: pd.DataFrame
    pda: pd.DataFrame
    bands: Bands
    exponents: dict = field(default_factory=dict)
    # Population-gate k behind R-301, calibrated to the PDA budget
    # rather than left at the blueprint's 4.5 (which fires on 26%).
    population_k: float | None = None
    # False when the forecaster was fitted on the frame it predicts
    # (a single-lot inference call). A reported MAE requires True.
    forecast_out_of_fold: bool = True

    def part(self, serial: str):
        """Row index for a serial, or None."""
        hit = self.fused.index[self.fused.serial == serial]
        return None if len(hit) == 0 else hit[0]


def screen(df: pd.DataFrame, weights: RiskWeights | None = None,
           bands: Bands | None = None, target_reject: float | None = 0.05,
           use_gbm: bool = True, lot_col: str = LOT_COL,
           forecaster: "PowerLawForecaster | None" = None,
           forecaster_is_out_of_fold: bool = True) -> ScreenResult:
    """Run the full screen over a wide burn-in frame.

    ``target_reject`` places the verdict bands so the REJECT rate respects the
    PDA gate; pass ``bands`` explicitly to override, or ``target_reject=None``
    to keep the fixed 40/70 defaults.

    Module B is skipped when the frame has no 168h column - at hour 24 there is
    nothing to fit against - and the fused score redistributes its weight.

    ``forecaster`` supplies an ALREADY-FITTED Module B model. Pass one and no
    training happens in this call: the service loads a versioned artifact once
    at startup instead of re-running a six-fold cross-validated LightGBM fit on
    every request. Two consequences worth stating:

      * A pre-fitted model only needs the 0h and 24h reads to predict, so an
        hour-24 triage frame CAN get a Module B forecast - something the
        fit-in-request path cannot do, because it has no 168h target to fit on.
      * ``forecaster_is_out_of_fold`` is the caller's assertion that this model
        never saw these parts. The caller knows (it compares the frame's hash
        against the artifact's training hash); this function cannot. It is
        recorded, not inferred, and a reported MAE depends on it.

    Passing ``forecaster=None`` reproduces the previous behaviour exactly.
    """
    feat = build_features(df)
    mb = run_module_b(df, target_reject=target_reject, use_gbm=use_gbm,
                      lot_col=lot_col, forecaster=forecaster,
                      forecaster_is_out_of_fold=forecaster_is_out_of_fold)
    return combine(df, feat, mb, weights=weights, bands=bands,
                   target_reject=target_reject, lot_col=lot_col)


@dataclass
class ModuleBResult:
    """Module B's output, before fusion. `module_b` is None when no forecast ran."""
    point: pd.DataFrame
    upper: pd.DataFrame
    module_b: pd.DataFrame | None
    exponents: dict
    population_k: float | None
    out_of_fold: bool


def run_module_b(df: pd.DataFrame, *, target_reject: float | None = 0.05,
                 use_gbm: bool = True, lot_col: str = LOT_COL,
                 forecaster: "PowerLawForecaster | None" = None,
                 forecaster_is_out_of_fold: bool = True) -> ModuleBResult:
    """Module B on its own: forecast, upper bound, safety-slope decision.

    Split out of `screen()` so the Forecast agent calls exactly this, in
    parallel with Module A. `screen()` still calls it - one definition.
    """
    n_lots = df[lot_col].nunique()
    has_late = all(f"{p}_168h" in df.columns for p in PARAM_NAMES)
    has_early = all(f"{p}_{t}h" in df.columns
                    for p in PARAM_NAMES for t in (0, 24))
    out_of_fold = False

    if forecaster is not None and has_early:
        # Inference path: predict only. No fit, no cross-validation.
        point = forecaster.predict(df, lot_col)
        upper = forecaster.predict_upper(df, lot_col)
        exps = dict(forecaster.exponents)
        out_of_fold = bool(forecaster_is_out_of_fold)
    elif has_late and n_lots >= 2:
        # Enough lots to hold one out: every part is forecast by a model that
        # never saw its lot, so the MAE from this is reportable (rule 6).
        r = forecast_all(df, use_gbm=use_gbm, lot_col=lot_col)
        point, upper, exps = r.point, r.upper, r.mean_exponents
        out_of_fold = True
    elif has_late:
        # A single lot - the normal production case, screening one lot at a
        # time. GroupKFold has nothing to hold out, so the forecaster is fitted
        # on the frame it predicts. That is fine for INFERENCE and invalid for
        # a reported MAE, so `forecast_out_of_fold` records it and evaluation
        # must refuse to quote a metric when it is False.
        m = PowerLawForecaster(use_gbm=use_gbm).fit(df, lot_col)
        point, upper, exps = (m.predict(df, lot_col), m.predict_upper(df, lot_col),
                              dict(m.exponents))
    else:
        empty = pd.DataFrame(index=df.index)
        return ModuleBResult(empty, empty, None, {}, None, False)

    pop_k = calibrate_population_k(df, upper, target_reject or 0.05, lot_col)
    mb = early_reject(df, upper, lot_col=lot_col, k=pop_k)
    return ModuleBResult(point, upper, mb, exps, pop_k, out_of_fold)


def combine(df: pd.DataFrame, feat: pd.DataFrame, mb: ModuleBResult, *,
            module_a: pd.DataFrame | None = None,
            weights: RiskWeights | None = None, bands: Bands | None = None,
            target_reject: float | None = 0.05,
            lot_col: str = LOT_COL) -> ScreenResult:
    """Fuse Module A features and Module B output into verdicts and lot status.

    `module_a` may be passed in when the caller (the Anomaly agent) already
    computed it; it is recomputed otherwise.
    """
    fused = fuse(df, feat, mb.module_b, weights, bands, lot_col)
    if bands is None and target_reject is not None:
        bands = bands_for_pda(fused.risk_score, target_reject)
        fused = fuse(df, feat, mb.module_b, weights, bands, lot_col)
    else:
        bands = bands or Bands()

    return ScreenResult(
        features=feat,
        module_a=module_a if module_a is not None else module_a_scores(df, feat),
        forecast_point=mb.point, forecast_upper=mb.upper, module_b=mb.module_b,
        early_score=early_warning_score(df, lot_col),
        fused=fused, pda=lot_pda_status(fused, lot_col), bands=bands,
        exponents=mb.exponents, forecast_out_of_fold=mb.out_of_fold,
        population_k=mb.population_k,
    )


def reason_code_tables(df: pd.DataFrame, result: ScreenResult,
                       index=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Part-level codes (R-101..R-501) and lot-level codes (R-601)."""
    return (reason_codes(df, result.features, result.module_b, index=index),
            lot_reason_codes(result.pda))
