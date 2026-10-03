"""Blind benchmark: Sentinel's prediction against the simulator's ground truth.

Order of operations is the whole point:

    1. simulate                      truth stays inside the SimResult
    2. screen the observed frame     Sentinel sees serial, lot, 16 ATE columns
    3. diagnose flagged boards       observed data only
    4. THEN open the truth and score

Every metric goes through src/evaluate.py (CLAUDE.md: one scorer, one truth).
Plain accuracy is refused there on purpose and is absent here: with a few
percent of boards faulty, "all good" would score in the high nineties.

A board counts as FLAGGED when its verdict is not ACCEPT: WATCH holds the
serial for review, so it is not an escape. REJECT-only numbers are reported
alongside, because only REJECT consumes the lot's PDA budget.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from src.evaluate import (pr_auc, recall_at_overkill, regression_metrics,
                          screening_metrics)
from src.explain import Thresholds, reason_codes_for_part
from src.features import PARAM_NAMES
from src.pipeline import screen

__all__ = ["sentinel_predictions", "score", "OVERKILL_BUDGET"]

OVERKILL_BUDGET = 0.05


def sentinel_predictions(frame: pd.DataFrame, *, forecaster=None,
                         forecaster_is_out_of_fold: bool = True,
                         escalate: bool = True, target_reject: float = 0.05) -> dict:
    """Run the existing pipeline exactly as the screening service does.

    ``escalate`` mirrors ScreeningService._apply_escalation: an ACCEPT that
    carries a high-severity reason code becomes WATCH. The service's policy is
    applied here too, so a benchmark number and a service verdict agree.
    """
    res = screen(frame, target_reject=target_reject, forecaster=forecaster,
                 forecaster_is_out_of_fold=forecaster_is_out_of_fold)
    verdict = res.fused["verdict"].astype(str).copy()
    if escalate:
        th = Thresholds()
        for i in verdict.index[verdict == "ACCEPT"]:
            codes = reason_codes_for_part(frame, res.features, i, res.module_b, th)
            if any(c.severity == "high" for c in codes):
                verdict.at[i] = "WATCH"
    table = pd.DataFrame({"serial": frame["serial"].to_numpy(),
                          "risk_score": res.fused["risk_score"].to_numpy(float),
                          "verdict": verdict.to_numpy()}, index=frame.index)
    return {"table": table, "result": res}


def score(pred: pd.DataFrame, truth: pd.DataFrame, *, budget: float = OVERKILL_BUDGET,
          forecast_out_of_fold: bool = False) -> dict:
    """Score predictions against truth. Both frames keyed by `serial`.

    ``pred`` columns: risk_score, verdict, and optionally detect_h,
    suspect_component, components_ranked (list), forecast_<P>, upper_<P>.
    ``truth`` is SimResult.truth_frame() (possibly concatenated over runs).
    """
    df = truth.merge(pred, on="serial", how="inner", validate="one_to_one")
    y = df["is_faulty"].to_numpy(int)
    flagged = (df["verdict"] != "ACCEPT").to_numpy(int)
    rejected = (df["verdict"] == "REJECT").to_numpy(int)
    risk = df["risk_score"].to_numpy(float)
    healthy = y == 0

    m_flag = screening_metrics(y, flagged, beta=2.0, healthy_mask=healthy)
    m_rej = screening_metrics(y, rejected, beta=2.0, healthy_mask=healthy)
    f1 = screening_metrics(y, flagged, beta=1.0, healthy_mask=healthy)["f_beta"]

    notes = []
    if y.sum() and (~healthy).sum() < len(y):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            ap = pr_auc(y, risk)
        if caught:
            notes.append(str(caught[0].message))
        at_budget = recall_at_overkill(y, risk, budget, healthy)
    else:
        ap, at_budget = float("nan"), {}

    tp_mask = (y == 1) & (flagged == 1)
    out = {
        "boards": int(len(df)),
        "faulty_boards": int(y.sum()),
        "confusion": {"tp": m_flag["tp"], "fp": m_flag["fp"],
                      "fn": m_flag["fn"], "tn": m_flag["tn"]},
        "recall": m_flag["recall"],
        "precision": m_flag["precision"],
        "f1": f1,
        "f2": m_flag["f_beta"],
        "false_negative_rate": (m_flag["fn"] / max(m_flag["tp"] + m_flag["fn"], 1)),
        "false_positive_rate": (m_flag["fp"] / max(m_flag["fp"] + m_flag["tn"], 1)),
        "pr_auc": ap,
        "recall_at_overkill": at_budget,
        "reject_only": {k: m_rej[k] for k in ("recall", "precision", "f_beta",
                                               "tp", "fp", "fn", "tn")},
        "counts": {"injected": int(y.sum()), "detected": int(tp_mask.sum()),
                   "missed": int(((y == 1) & (flagged == 0)).sum()),
                   "incorrectly_flagged": int(((y == 0) & (flagged == 1)).sum())},
        "notes": notes,
        "accuracy": "not reported - see src/evaluate.accuracy (rule 5)",
    }

    # ---- recall where recall is possible, and recall per fault type
    if "detectable" in df.columns:
        obs_mask = (y == 1) & (df["detectable"].to_numpy(int) == 1)
        out["recall_observable_faults"] = (float(flagged[obs_mask].mean())
                                           if obs_mask.any() else float("nan"))
        out["counts"]["unobservable_faults"] = int(((y == 1) & ~obs_mask).sum())
    if y.any():
        f = df.loc[y == 1].assign(_flag=flagged[y == 1])
        by = (f.groupby(["fault_components", "fault_types"], sort=True)
               .agg(n=("_flag", "size"), detected=("_flag", "sum"),
                    mean_severity=("max_severity", "mean")).reset_index())
        out["by_fault_type"] = [
            {"component": r.fault_components, "fault_type": r.fault_types,
             "n": int(r.n), "detected": int(r.detected),
             "recall": float(r.detected / r.n),
             "mean_severity": round(float(r.mean_severity), 3)}
            for r in by.itertuples()]

    # ---- detection delay: earliest read hour at which the board was flagged
    if "detect_h" in df.columns and tp_mask.any():
        d = df.loc[tp_mask, "detect_h"].astype(float)
        out["detection_delay_h"] = {"mean": float(d.mean()), "median": float(d.median()),
                                    "by_read": {str(int(h)): int((d == h).sum())
                                                for h in sorted(d.dropna().unique())}}
        out["counts"]["average_detection_h"] = float(d.mean())

    # ---- localisation, on boards that were both faulty and flagged
    if "components_ranked" in df.columns and tp_mask.any():
        top1 = top3 = 0
        rows = df.loc[tp_mask]
        for _, r in rows.iterrows():
            truth_c = set(str(r["fault_components"]).split(",")) - {""}
            ranked = list(r["components_ranked"] or [])
            top1 += int(bool(ranked) and ranked[0] in truth_c)
            top3 += int(bool(truth_c & set(ranked[:3])))
        out["localization"] = {"evaluated": int(len(rows)),
                               "top1": top1 / len(rows), "top3": top3 / len(rows)}

    # ---- Module B forecast error, only when the forecaster never saw these parts
    fc = [p for p in PARAM_NAMES if f"forecast_{p}" in df.columns]
    if fc:
        fe = {}
        for p in fc:
            obs = df[f"obs_{p}_168h"].to_numpy(float)
            point = df[f"forecast_{p}"].to_numpy(float)
            rm = regression_metrics(obs, point)
            ok = np.isfinite(obs) & np.isfinite(df[f"upper_{p}"].to_numpy(float))
            cover = float(np.mean(obs[ok] <= df[f"upper_{p}"].to_numpy(float)[ok])) if ok.any() else float("nan")
            rmse = float(np.sqrt(np.nanmean((obs - point) ** 2)))
            fe[p] = {"mae": rm["mae"], "normalised_mae": rm["normalised_mae"],
                     "rmse": rmse, "upper_coverage": cover,
                     "drift_error": float(np.nanmedian(np.abs(
                         (point - df[f"obs_{p}_0h"].to_numpy(float))
                         - (obs - df[f"obs_{p}_0h"].to_numpy(float)))))
                     if f"obs_{p}_0h" in df.columns else None}
        out["forecast"] = {"out_of_fold": bool(forecast_out_of_fold), "by_parameter": fe,
                           "note": (None if forecast_out_of_fold else
                                    "in-sample forecast: do not quote this MAE")}

    fn = df.loc[(y == 1) & (flagged == 0)]
    out["false_negatives"] = [
        {"serial": r["serial"], "components": r["fault_components"],
         "fault_types": r["fault_types"], "severity": round(float(r["max_severity"]), 3),
         "risk_score": round(float(r["risk_score"]), 1)}
        for _, r in fn.head(50).iterrows()]
    fp = df.loc[(y == 0) & (flagged == 1)].sort_values("risk_score", ascending=False)
    out["false_positives"] = [
        {"serial": r["serial"], "verdict": r["verdict"],
         "risk_score": round(float(r["risk_score"]), 1)} for _, r in fp.head(50).iterrows()]
    return out
