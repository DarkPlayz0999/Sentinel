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
from src.module_b import (PowerLawForecaster, early_reject,
                          early_warning_score, forecast_all)

__all__ = ["ScreenResult", "screen", "load_wide", "DATA"]

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
    # False when the forecaster was fitted on the frame it predicts
    # (a single-lot inference call). A reported MAE requires True.
    forecast_out_of_fold: bool = True

    def part(self, serial: str):
        """Row index for a serial, or None."""
        hit = self.fused.index[self.fused.serial == serial]
        return None if len(hit) == 0 else hit[0]


def screen(df: pd.DataFrame, weights: RiskWeights | None = None,
           bands: Bands | None = None, target_reject: float | None = 0.05,
           use_gbm: bool = True, lot_col: str = LOT_COL) -> ScreenResult:
    """Run the full screen over a wide burn-in frame.

    ``target_reject`` places the verdict bands so the REJECT rate respects the
    PDA gate; pass ``bands`` explicitly to override, or ``target_reject=None``
    to keep the fixed 40/70 defaults.

    Module B is skipped when the frame has no 168h column - at hour 24 there is
    nothing to fit against - and the fused score redistributes its weight.
    """
    feat = build_features(df)
    has_late = all(f"{p}_168h" in df.columns for p in PARAM_NAMES)
    n_lots = df[lot_col].nunique()
    out_of_fold = False

    if has_late and n_lots >= 2:
        # Enough lots to hold one out: every part is forecast by a model that
        # never saw its lot, so the MAE from this is reportable (rule 6).
        r = forecast_all(df, use_gbm=use_gbm, lot_col=lot_col)
        point, upper, exps = r.point, r.upper, r.mean_exponents
        mb = early_reject(df, upper, lot_col=lot_col)
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
        mb = early_reject(df, upper, lot_col=lot_col)
    else:
        point = upper = pd.DataFrame(index=df.index)
        mb, exps = None, {}

    fused = fuse(df, feat, mb, weights, bands, lot_col)
    if bands is None and target_reject is not None:
        bands = bands_for_pda(fused.risk_score, target_reject)
        fused = fuse(df, feat, mb, weights, bands, lot_col)
    else:
        bands = bands or Bands()

    return ScreenResult(
        features=feat,
        module_a=module_a_scores(df, feat),
        forecast_point=point, forecast_upper=upper, module_b=mb,
        early_score=early_warning_score(df, lot_col),
        fused=fused, pda=lot_pda_status(fused, lot_col), bands=bands,
        exponents=exps, forecast_out_of_fold=out_of_fold,
    )


def reason_code_tables(df: pd.DataFrame, result: ScreenResult,
                       index=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Part-level codes (R-101..R-501) and lot-level codes (R-601)."""
    return (reason_codes(df, result.features, result.module_b, index=index),
            lot_reason_codes(result.pda))
