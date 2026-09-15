"""The explanation engine.

THE INVARIANT THIS MODULE EXISTS FOR
------------------------------------
An explanation must explain the decision that was actually made. Before this
module, reason codes were emitted from independent fixed thresholds while the
verdict came from a weighted sum of sub-scores, so the two could disagree: a
REJECT could carry no reason at all, and the project's own worked example
(L04-0348) was rejected on drift while the only code that fired talked about
pooled multivariate evidence.

The fix is architectural, not cosmetic. The verdict IS
`sum(sub_score * weight)`, so the explanation is derived from those same
weighted contributions:

    sub-scores  ->  weighted contributions  ->  ranked decision path
                                                      |
                                    primary_reason <--+  (the top contributor)
                                    supporting_reasons

Rule-based reason codes (R-101...R-601) remain, and are attached as corroborating
detail with the threshold each one cleared. They are no longer the only source
of an explanation, so they can no longer be silent on a rejected part.

Guaranteed on every component:
  * verdict != ACCEPT  ->  `primary_reason` is not None
  * `primary_reason.contribution` is a real term of the risk score
  * every number carries its parameter, its unit and its lot reference
"""

from __future__ import annotations

import math

import pandas as pd

from src.explain import ReasonCode, Thresholds, reason_codes_for_part
from src.features import PARAMS
from src.fusion import RiskWeights

from backend.app.services.evidence_service import DPAT_LIMIT_SIGMA

__all__ = ["build_explanation", "SUB_SCORE_TITLES", "EXPLANATION_VERSION"]

EXPLANATION_VERSION = "explain-2.0.0"

SUB_SCORE_TITLES = {
    "static_margin": "Datasheet headroom consumed",
    "dynamic_outlier": "Lot-relative parametric anomaly",
    "predicted_drift": "Forecast drift against the safety slope",
    "multivariate": "Pooled cross-parameter drift evidence",
    # Neutral: the title must not assert acceleration when the ratio
    # says the part is settling. The message carries the direction.
    "curvature": "Degradation curvature (late vs early drift rate)",
}

# The reason code each sub-score corresponds to, when one exists. Used to link
# a decision-path entry to the rule that articulates it.
SUB_SCORE_CODES = {
    # static_margin deliberately has NO code. R-101 is the 168h LEVEL anomaly,
    # which is a different claim from "consumed its headroom", and labelling a
    # contribution with a code that means something else - and did not fire -
    # is the exact failure this module exists to stop.
    "static_margin": None,
    "dynamic_outlier": "R-102",
    "predicted_drift": "R-301",
    "multivariate": "R-401",
    "curvature": "R-501",
}


def _f(v) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if not math.isfinite(x) else round(x, 4)


def _fmt(v: float | None, unit: str) -> str:
    return "unknown" if v is None else f"{v:.4g} {unit}"


# --------------------------------------------------- per-sub-score narrators
def _static_margin_detail(ev: dict) -> dict:
    rows = [r for r in ev["static"]["per_parameter"]
            if r.get("margin_consumed") is not None]
    if not rows:
        return {}
    w = max(rows, key=lambda r: r["margin_consumed"])
    return {
        "parameter": w["parameter"],
        "unit": w["unit"],
        "observed": w["value_168h"],
        "value_0h": w["value_0h"],
        "usl": w["usl"],
        "margin_consumed": w["margin_consumed"],
        "message": (
            f"{w['parameter']} consumed {w['margin_consumed'] * 100:.1f}% of "
            f"its available datasheet headroom during burn-in "
            f"({_fmt(w['value_0h'], w['unit'])} to "
            f"{_fmt(w['value_168h'], w['unit'])} against a "
            f"{_fmt(w['usl'], w['unit'])} limit)."),
    }


def _dynamic_outlier_detail(ev: dict) -> dict:
    lr = ev["lot_relative"]
    worst = lr.get("worst") or {}
    param = worst.get("parameter")
    if not param:
        return {}
    unit = PARAMS.get(param, {}).get("unit", "")
    per = next((r for r in lr["per_parameter"] if r["parameter"] == param), {})
    view = worst.get("view") or "drift"
    readable_view = {
        "level_0h": "incoming level at 0 h",
        "level_168h": "level at 168 h",
        "early": "0 to 24 h movement",
        "drift": "0 to 168 h drift",
        "curvature": "acceleration ratio",
    }.get(view, view)
    return {
        "parameter": param,
        "unit": unit,
        "view": view,
        "z_score": worst.get("z"),
        "observed": per.get("observed_drift") if view == "drift"
        else per.get("lot_median_168h"),
        "lot_median": per.get("lot_median_drift") if view == "drift"
        else per.get("lot_median_168h"),
        "robust_sigma": per.get("lot_robust_sigma_168h"),
        "dpat_limit_sigma": DPAT_LIMIT_SIGMA,
        "message": (
            f"{param} is {worst.get('z', float('nan')):.1f} robust sigma from "
            f"its lot on the {readable_view}, against a Dynamic PAT limit of "
            f"{DPAT_LIMIT_SIGMA:.0f} sigma. The reference is this lot's own "
            f"median and 1.4826*MAD, not the datasheet."),
    }


def _predicted_drift_detail(ev: dict) -> dict:
    mb = ev.get("module_b") or {}
    if not mb.get("available"):
        return {}
    ss = mb.get("safety_slope") or {}
    ratio, param = ss.get("worst_ratio"), ss.get("worst_parameter")
    if ratio is None or param is None:
        return {}
    unit = PARAMS.get(param, {}).get("unit", "")
    fc = (mb.get("forecast") or {}).get("upper_bound", {}) or {}
    return {
        "parameter": param,
        "unit": unit,
        "slope_ratio": ratio,
        "gate": 1.0,
        "forecast_168h_upper": fc.get(param),
        "is_prediction": True,
        "message": (
            f"The forecast 168 h {param}, predicted from the 0 h and 24 h "
            f"reads alone, implies a drift rate {ratio:.2f}x the safety "
            f"slope. This is a PREDICTION, not a measurement."),
    }


def _multivariate_detail(ev: dict) -> dict:
    mv = ev["multivariate"]
    if mv.get("score") is None:
        return {}
    top = [t for t in mv.get("contributions", []) if (t.get("z") or 0) > 0][:2]
    named = ", ".join(f"{t['parameter']} {t['z']:.1f} sigma" for t in top)
    return {
        "score": mv["score"],
        "threshold": mv["threshold"],
        "top_axes": top,
        "message": (
            f"Combined drift evidence across parameters is {mv['score']:.1f} "
            f"against a {mv['threshold']:.1f} threshold"
            + (f" ({named})." if named else ".")
            + " Individually ordinary, jointly rare for this lot."),
    }


def _curvature_detail(ev: dict) -> dict:
    w = (ev.get("curvature") or {}).get("worst")
    if not w or w.get("ratio") is None:
        return {}
    ratio = w["ratio"]
    # The sentence has to match the number. A ratio under 1.0 means the part is
    # SETTLING, and calling that "accelerating" would be false on a signed
    # record even though the term still contributes to the score.
    if ratio > 2.0:
        verdict = (f"degradation is accelerating rather than settling: the "
                   f"late window is drifting {ratio:.1f}x as fast as the "
                   f"early one")
    elif ratio > 1.0:
        verdict = (f"the late window is drifting {ratio:.1f}x as fast as the "
                   f"early one - faster than linear, below the 2.0 gate")
    else:
        verdict = (f"the late window is drifting {ratio:.1f}x the early rate, "
                   f"so the part is settling rather than accelerating")
    return {
        "parameter": w["parameter"],
        "ratio": ratio,
        "threshold": 2.0,
        "accelerating": bool(ratio > 1.0),
        "message": f"{w['parameter']}: {verdict}.",
    }


_NARRATORS = {
    "static_margin": _static_margin_detail,
    "dynamic_outlier": _dynamic_outlier_detail,
    "predicted_drift": _predicted_drift_detail,
    "multivariate": _multivariate_detail,
    "curvature": _curvature_detail,
}


# ------------------------------------------------------------------ build
def build_explanation(df: pd.DataFrame, feat: pd.DataFrame, i, *,
                      sub_scores: dict, risk_score: float, verdict: str,
                      evidence: dict,
                      module_b: pd.DataFrame | None = None,
                      weights: RiskWeights | None = None,
                      thresholds: Thresholds | None = None,
                      bands: dict | None = None) -> dict:
    """Assemble the structured explanation for one component.

    `evidence` is the combined Module A payload plus a "module_b" key, so the
    narrators read the same numbers the API returns rather than recomputing
    anything.
    """
    w = (weights or RiskWeights()).as_dict()

    # ---- the decision path: the actual terms of the weighted sum
    available = {k: v for k, v in sub_scores.items() if k in w and v is not None}
    total_weight = sum(w[k] for k in available) or 1.0
    path = []
    for name, value in available.items():
        weight = w[name] / total_weight          # renormalised over what exists
        path.append({
            "sub_score": name,
            "title": SUB_SCORE_TITLES.get(name, name),
            "value": _f(value),
            "weight": round(weight, 4),
            "contribution": _f(float(value) * weight),
            "reason_code": SUB_SCORE_CODES.get(name),
        })
    path.sort(key=lambda e: e["contribution"] or 0.0, reverse=True)
    for rank, entry in enumerate(path, start=1):
        entry["rank"] = rank

    # ---- rule-based codes, as corroborating detail
    t = thresholds or Thresholds()
    codes: list[ReasonCode] = reason_codes_for_part(df, feat, i, module_b, t)
    code_payload = [{
        **c.as_dict(),
        "threshold": _f(getattr(t, {
            "R-101": "level_z", "R-102": "drift_z", "R-201": "early_z",
            "R-301": "slope_ratio", "R-401": "pooled", "R-501": "curvature",
        }.get(c.code, "level_z"), None)),
    } for c in codes]
    by_code = {c["code"]: c for c in code_payload}

    # ---- primary and supporting reasons, derived FROM the decision path
    def reason_for(entry: dict) -> dict | None:
        name = entry["sub_score"]
        detail = _NARRATORS[name](evidence) if name in _NARRATORS else {}
        if not detail:
            return None
        related = entry.get("reason_code")
        fired = by_code.get(related or "")
        return {
            # Only name a code that actually fired. `related_code` names the
            # rule this sub-score corresponds to when it did not, so the link
            # is still visible without asserting a trigger that never happened.
            "code": related if fired else None,
            "related_code": related,
            "code_fired": fired is not None,
            "title": entry["title"],
            "sub_score": name,
            "sub_score_value": entry["value"],
            "weight": entry["weight"],
            "contribution": entry["contribution"],
            "contribution_share": _f((entry["contribution"] or 0) / risk_score)
            if risk_score else None,
            **detail,
            # When the matching rule also fired, quote its inspector sentence
            # verbatim so the signed record and the API agree word for word.
            "reason_code_message": fired["message"] if fired else None,
        }

    reasons = [r for r in (reason_for(e) for e in path) if r]
    # A term that contributed nothing did not drive the decision and must not
    # be presented as though it did.
    material = [r for r in reasons if (r["contribution"] or 0) > 0.5]

    primary = material[0] if material else (reasons[0] if reasons else None)
    supporting = [r for r in material[1:]] if material else []

    # ---- THE INVARIANT
    if verdict != "ACCEPT" and primary is None:
        # Unreachable on real data: a non-ACCEPT verdict means the weighted sum
        # cleared a band, so some term was non-zero. Kept as a loud failure
        # rather than a silent one, because shipping a REJECT with no reason is
        # exactly what this module exists to prevent.
        top = path[0] if path else None
        primary = {
            "code": None,
            "code_fired": False,
            "title": "Unattributed risk",
            "sub_score": top["sub_score"] if top else None,
            "sub_score_value": top["value"] if top else None,
            "contribution": top["contribution"] if top else None,
            "message": (
                f"Verdict {verdict} at risk {risk_score:.1f} could not be "
                "attributed to a named sub-score. This indicates a defect in "
                "the screening service and the component must be reviewed "
                "manually."),
            "integrity_warning": True,
        }

    return {
        "explanation_version": EXPLANATION_VERSION,
        "verdict": verdict,
        "risk_score": _f(risk_score),
        "bands": bands or {},
        "decision_path": path,
        "primary_reason": primary,
        "supporting_reasons": supporting,
        "reason_codes": code_payload,
        "method": (
            "The verdict is a weighted sum of named sub-scores. This "
            "explanation is derived from those same weighted contributions, "
            "ranked, so it always describes the decision that was made."),
    }
