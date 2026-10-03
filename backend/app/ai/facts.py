"""Fact sheets: what the AI is allowed to know, per page of the product.

Each builder returns {"context", "subject", "title", "facts"}. `facts` is a
small JSON-safe dict built ONLY from values the API already serves to the
browser - so the model can never see more than the page shows. In particular a
BLIND simulation's fact sheet is built from SimulationService.get(), which
withholds the fault and every internal value until the reveal.

Numbers are rounded here, once, so the model quotes the same figures the page
shows and the number check has a fixed reference.
"""

from __future__ import annotations

import math
from typing import Any

from src.explain import MODEL_VERSION
from src.features import PARAMS

from backend.app.core.exceptions import NotFoundError

__all__ = ["build", "CONTEXTS", "CONSTANTS"]

CONSTANTS = {
    "read_points_h": [0, 24, 96, 168],
    "burn_in_temperature_c": 125,
    "datasheet_limits": {p: c["usl"] for p, c in PARAMS.items()},
    "pda_budget_percent": 5,
    "model_version": MODEL_VERSION,
    "glossary": {
        "Iddq": "quiescent supply current - the current a chip draws while idle",
        "Ileak": "leakage current - current that leaks through where it should not",
        "Tpd": "propagation delay - how long a signal takes to pass through the chip",
        "Vol": "output-low voltage - how close to zero volts the output gets when switched low",
        "ESR": "equivalent series resistance of a capacitor - rises as it wears out",
        "lot / batch": "parts made together; SENTINEL compares each part with its own batch",
        "drift": "how much a reading changed during the burn-in soak",
        "robust sigma": "a measure of how far a part sits from its batch; 3 or more is unusual",
        "PDA": "the most a batch may reject (5%) before the whole batch goes to review",
        "WATCH": "ships, but the serial is flagged for a second look",
        "REJECT": "pulled from the lot, with a written reason",
        "evidence score": "how closely the observed pattern matches a fault's modelled pattern (0-100); not a probability",
        "recall": "share of the truly faulty boards or parts that SENTINEL flagged",
        "precision": "share of SENTINEL's flags that were truly faulty",
        "false positive": "a good part flagged by mistake (overkill)",
        "false negative": "a faulty part SENTINEL missed (an escape)",
        "localisation top1": "share of caught faulty boards where the agents named the faulty component first",
        "detection delay": "the earliest read (24, 96 or 168 h) at which a faulty board was flagged",
    },
}

LABEL = {p: f"{c['label']} ({p.split('_')[1]})" for p, c in PARAMS.items()}


def _r(v: Any, sig: int = 4) -> Any:
    """Round to `sig` significant figures; recurse into containers."""
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, float):
        if not math.isfinite(v):
            return None
        if v == 0:
            return 0.0
        return round(v, max(0, sig - 1 - int(math.floor(math.log10(abs(v))))))
    if isinstance(v, dict):
        return {k: _r(x, sig) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_r(x, sig) for x in v]
    return v


def _codes(codes: list[dict], n: int = 4) -> list[dict]:
    out = []
    for c in codes[:n]:
        out.append({k: c.get(k) for k in ("code", "severity", "message") if c.get(k) is not None})
    return out


# ---------------------------------------------------------- shipped dataset
def _shipped():
    from backend.app.api.routes.legacy import _default   # cached screen of data/
    return _default()


def overview() -> dict:
    df, res = _shipped()
    f = res.fused
    counts = f.verdict.value_counts().to_dict()
    pda = res.pda
    passes = f[f.l1_static == 0].sort_values("risk_score", ascending=False).head(5)
    return {
        "title": "Screening results for the built-in burn-in dataset",
        "facts": _r({
            "data": ("the simulated burn-in dataset that comes with SENTINEL (seed 42): parts on a "
                     "test floor after a week-long burn-in soak; none of them has been shipped"),
            "parts": int(len(df)), "lots": int(df.lot.nunique()),
            "verdicts": {k: int(v) for k, v in counts.items()},
            # Totals people ask for, computed here so the model never has to add.
            "flagged_total_watch_plus_reject": int(counts.get("WATCH", 0) + counts.get("REJECT", 0)),
            "reject_percent_of_all_parts": 100 * counts.get("REJECT", 0) / len(df),
            "watch_percent_of_all_parts": 100 * counts.get("WATCH", 0) / len(df),
            "reject_band_starts_at_risk": res.bands.reject, "watch_band_starts_at_risk": res.bands.watch,
            "lots_over_pda": [str(l) for l in pda.index[pda.status == "LOT REVIEW"]],
            "worst_lot": {"lot": str(pda.reject_frac.idxmax()),
                          "reject_percent": 100 * float(pda.reject_frac.max())},
            "flagged_parts_a_datasheet_test_would_have_passed": [
                {"serial": r.serial, "lot": r.lot, "risk_score": r.risk_score, "verdict": r.verdict}
                for r in passes.itertuples()],
            "parts_breaking_a_datasheet_limit": int(f.l1_static.sum()),
            "how_the_flags_arise": (
                f"A datasheet test catches only the {int(f.l1_static.sum())} parts that break a "
                "limit. Every other WATCH or REJECT comes from a part behaving unlike the other "
                "parts in its own batch, which a datasheet test cannot see."),
            "constants": CONSTANTS,
        }),
    }


def lot(lot_id: str) -> dict:
    from src.explain import lot_reason_codes
    df, res = _shipped()
    if lot_id not in res.pda.index:
        raise NotFoundError(f"No lot {lot_id!r}.")
    r = res.pda.loc[lot_id]
    codes = lot_reason_codes(res.pda)
    f = res.fused[res.fused.lot == lot_id].sort_values("risk_score", ascending=False)
    return {"title": f"Batch {lot_id}", "facts": _r({
        "lot": lot_id, "parts": int(r.parts), "reject": int(r.reject), "watch": int(r.watch),
        "reject_percent": 100 * float(r.reject_frac), "pda_limit_percent": 100 * float(r.pda_limit),
        "status": str(r.status), "mean_risk": float(r.mean_risk),
        "top_parts": [{"serial": x.serial, "risk_score": x.risk_score, "verdict": x.verdict}
                      for x in f.head(5).itertuples()],
        "lot_reason_codes": codes[codes.lot == lot_id][["code", "message"]].to_dict("records"),
        "constants": CONSTANTS})}


def part(serial: str) -> dict:
    from backend.app.api.routes.legacy import _verdict_payload
    df, res = _shipped()
    i = res.part(serial)
    if i is None:
        raise NotFoundError(f"No part {serial!r}.")
    v = _verdict_payload(df, res, i)
    lot_id = v["lot"]
    lot_rows = df[df.lot == lot_id]
    meas = {}
    for p in PARAMS:
        meas[LABEL[p]] = {
            "reads": {f"{h}h": float(df.at[i, f"{p}_{h}h"]) for h in (0, 24, 96, 168)
                      if f"{p}_{h}h" in df.columns},
            "lot_median_168h": float(lot_rows[f"{p}_168h"].median()),
            "datasheet_limit": PARAMS[p]["usl"]}
    return {"title": f"Part {serial}", "facts": _r({
        "serial": serial, "lot": lot_id, "verdict": v["verdict"], "risk_score": v["risk_score"],
        "sub_scores_0_to_100": v["sub_scores"], "reason_codes": _codes(v["reason_codes"]),
        "measurements": meas, "passes_datasheet": not bool(res.fused.at[i, "l1_static"]),
        "constants": CONSTANTS})}


# ------------------------------------------------------------ digital twin
def simulation(sid: str, serial: str | None = None) -> dict:
    from backend.app.services.simulation_service import SimulationService
    svc = SimulationService()
    s = svc.get(sid)                       # BLIND-safe: truth withheld until reveal
    inv = s.get("investigation") or {}
    rep = inv.get("report") or {}
    focus = serial or s.get("focus_serial")
    facts: dict = {
        "data": "SIMULATED digital-twin lot, accelerated simulation time",
        "lot": s["lot_id"], "boards": s["boards"], "mode": s["mode"],
        "ground_truth_visible": s["truth_visible"], "status": s["status"],
        "simulated_hours": s["sim_time_h"], "soak_temperature_c": s["config"]["stress_temp_c"],
        "sentinel_verdicts": s.get("verdicts"),
        "board_ranked_first_by_sentinel": s.get("focus_serial"),
    }
    if s["truth_visible"] and isinstance(s.get("faults"), list):
        facts["injected_faults"] = [{k: f[k] for k in ("board_serial", "component_id", "fault_type",
                                                       "severity")} for f in s["faults"][:6]]
    else:
        facts["injected_faults"] = "hidden until the reveal (blind evaluation)"
    if rep:
        facts["investigation"] = {
            "summary": rep.get("summary"), "suspect_component": rep.get("suspect_component"),
            "suspect_fault_type": rep.get("suspect_fault_type"),
            "evidence_score_out_of_100": rep.get("evidence_score"),
            "evidence_score_meaning": "a similarity between the observed pattern and the fault's modelled pattern, NOT a probability",
            "ambiguity_group": rep.get("ambiguity_group"), "qa_safety": rep.get("qa_status"),
            "recommended_actions": rep.get("recommended_actions")}
        rc = (inv.get("root_cause") or {}).get("hypotheses") or []
        facts["top_hypotheses"] = [{"component": h["component_id"], "fault": h["fault_type"],
                                    "evidence_score": h["evidence_score"]} for h in rc[:3]]
    if focus and s["status"] in ("SCREENED", "INVESTIGATED"):
        try:
            cv = svc.components(sid, focus)
            facts["board"] = {
                "serial": focus, "verdict": cv.get("verdict"), "risk_score": cv.get("risk_score"),
                "reason_codes": _codes(cv.get("reason_codes") or []),
                "parts_the_agents_marked": {c["component_id"]: c["status"] for c in cv["components"]
                                            if c["status"] != "OK"}}
        except NotFoundError:
            pass
    reps = svc.comparison(sid)["replacements"]
    if reps:
        r = reps[-1]
        facts["replacement"] = {
            "board": r["board_serial"], "replaced": r["component_id"], "new_part": r["candidate_id"],
            "before": {"verdict": r["before"]["verdict"], "risk_score": r["before"]["risk_score"],
                       "ir_temperature_c": r["before"]["ir_temp_c"]},
            "after": {"verdict": r["after"]["verdict"], "risk_score": r["after"]["risk_score"],
                      "ir_temperature_c": r["after"]["ir_temp_c"]}}
    if s.get("revealed_at"):
        rv = svc.reveal(sid)
        b = rv["benchmark"]
        facts["after_reveal"] = {
            "faulty_boards": rv["faulty_boards"][:6],
            "recall": b["recall"], "precision": b["precision"],
            "false_positive_rate": b["false_positive_rate"],
            "localisation_top1": (b.get("localization") or {}).get("top1"),
            "replacements": rv["replacements"][:3],
            "operating_point": rv["operating_point"]}
    facts["constants"] = CONSTANTS
    return {"title": f"Simulation {s['lot_id']}", "facts": _r(facts)}


def experiment(eid: str | None = None) -> dict:
    from backend.app.services.experiment_service import ExperimentService
    svc = ExperimentService()
    if not eid:
        done = [e for e in svc.list(50) if e["status"] == "COMPLETED"]
        if not done:
            raise NotFoundError("No completed experiment yet.")
        eid = done[0]["experiment_id"]
    e = svc.get(eid)
    s = e.get("summary") or {}
    o = s.get("overall") or {}
    keep = ("recall", "recall_observable_faults", "precision", "f2", "pr_auc",
            "false_positive_rate", "false_negative_rate")
    cells = {name: {k: b.get(k) for k in keep} | {
        "top1_localisation": (b.get("localization") or {}).get("top1")}
        for name, b in list((s.get("by_cell") or {}).items())[:21]}
    return {"title": f"Benchmark campaign {e['kind']}", "facts": _r({
        "data": "SIMULATED blind benchmark: many lots, faults hidden from Sentinel until scored",
        "kind": e["kind"], "status": e["status"], "runs": e["runs"], "seed": e["random_seed"],
        "boards_scored": s.get("boards_scored"),
        "overall": {k: o.get(k) for k in keep} | {
            "confusion": o.get("confusion"), "localisation": o.get("localization"),
            "detection_delay_h": o.get("detection_delay_h")},
        "by_scenario_or_sweep_point": cells, "operating_point": s.get("operating_point"),
        "plain_accuracy": "deliberately not reported (it would look high even if nothing were caught)",
        "constants": CONSTANTS})}


def workflow(wid: str | None = None) -> dict:
    from backend.app.core.config import get_settings
    from backend.app.repositories.repositories import AgentRepository
    repo = AgentRepository(get_settings().sqlite_path)
    if not wid:
        wfs = repo.list_workflows(20)
        if not wfs:
            raise NotFoundError("No agent workflow yet.")
        wid = wfs[0]["workflow_id"]
    wf = repo.get_workflow(wid)
    if not wf:
        raise NotFoundError(f"No workflow {wid!r}.")
    steps = repo.steps(wid)
    fnd = repo.findings(wid)
    return {"title": f"Agent workflow {wid}", "facts": _r({
        "trigger": wf["trigger"], "status": wf["status"], "data_class": wf.get("data_class"),
        "duration_s": wf.get("duration_s"),
        "agents": [{"agent": x["agent"], "status": x["status"], "seconds": x["duration_s"]}
                   for x in steps],
        "findings": [{"agent": x["agent"], "severity": x["severity"], "code": x["code"],
                      "message": x["message"]} for x in fnd[:10]],
        "summary": {k: v for k, v in (wf.get("summary") or {}).items()
                    if k in ("data_quality", "anomaly", "forecast", "result")},
        "constants": CONSTANTS})}


def realdata(which: str | None = None) -> dict:
    """The prepared NASA datasets: labels and the early-warning evaluation."""
    from backend.app.api.routes import realdata as rd
    which = which or "capacitors"
    data = rd.capacitors() if which == "capacitors" else rd.mosfet()
    truth = data["truth"]
    ev = data.get("evaluation") or {}
    facts: dict = {
        "data": ("REAL measured data from NASA (not simulated), prepared by a script that "
                 "reshapes but never changes the measurements"),
        "dataset": data["metadata"].get("source"),
    }
    if which == "capacitors":
        failed = [t for t in truth if t["eol"]]
        early = [t["serial"] for t in failed if (t["eol_day"] or 0) < 14]
        later = [t["serial"] for t in failed if (t["eol_day"] or 0) >= 14]
        facts |= {
            "capacitors": len(truth), "reads": data["metadata"].get("reads"),
            "test_days": max(t["last_day"] for t in truth),
            "test_conditions": "electrical overstress at 10, 12 and 14 volts; temperature not given in the files",
            "stress_voltages_v": sorted({t["stress_v"] for t in truth}),
            "end_of_life_rule": "capacitance down 20 % or ESR doubled from the pre-stress read, and it must persist",
            "reached_end_of_life_total": len(failed),
            "reached_end_of_life": [{"capacitor": t["serial"], "stress_v": t["stress_v"],
                                     "day": t["eol_day"], "by": t["eol_by"]} for t in failed],
            "failed_within_the_first_days": early,
            "failed_later_in_the_test": later,
            "stress_transient": "days 0-35 in every capacitor: ESR jumps when the stress starts, then relaxes",
            "early_warning_question": ("at an early read (day 14, 35 or 49), among capacitors that have not "
                                       "failed yet, which will fail later"),
            # Results as plain sentences, written here from the evaluation file,
            # so the model does not have to interpret metric tables.
            "results_in_words": [_cap_sentence(day, r) for day, r in (ev.get("by_read_day") or {}).items()],
            "caution": (f"the evaluation only covers the {len(later)} capacitors that fail after the early "
                        f"reads ({', '.join(later)}); the {len(early)} that failed in the first days are "
                        "excluded because any limit check catches them"),
        }
    else:
        pp = (ev or {}).get("pooled_population") or {}
        n_fail = pp.get("failing_later", 0)
        facts |= {
            "devices": len(truth),
            "end_of_life_rule": ("on-resistance at 25 C up 20 % or more over the device's first run, "
                                 "and staying there on every later run"),
            "results_in_words": [
                (f"At the end of each device's first run, the early score flagged {pp.get('tp', 0)} of the "
                 f"{n_fail} devices that fail later, and {pp.get('fp', 0)} devices that do not fail.")
                if pp else "No early-warning evaluation yet.",
                (f"Its ranking quality (PR-AUC) is {pp.get('pr_auc', 0):.2f}; guessing at random would give "
                 f"about {n_fail / max(pp.get('parts', 1), 1):.2f}, so the early signal is weak on this data.")
                if pp else "",
            ],
            "devices_with_two_or_more_runs": sum(1 for t in truth if t["labelable"]),
            "reached_end_of_life": [t["device"] for t in truth if t["eol"]],
            "why_no_latch_up_label": "the current channel reads 0.2-0.3 A with the gate off even on healthy devices",
            "evaluation": {k: ev.get(k) for k in ("early_read", "devices_scored", "pooled_population")},
        }
    # A glossary for THIS page only: the general one names Iddq, Vol and the
    # simulated burn-in, none of which apply to NASA's capacitors or MOSFETs.
    facts["glossary"] = {
        "ESR": "equivalent series resistance of a capacitor - rises as it wears out",
        "capacitance loss": "how much of its original capacitance a capacitor has lost",
        "on-resistance (Rds on)": "resistance of a MOSFET when switched on - rises as it wears out",
        "end of life": "the wear level at which a part is considered worn out, by the rule stated",
        "flagged": "picked out by SENTINEL's early score as likely to fail",
        "PR-AUC": "how well the early score ranks the parts that fail above those that do not (1 = perfect)",
    }
    return {"title": f"Real NASA data - {which}", "facts": _r(facts)}


def _cap_sentence(day: str, r: dict) -> str:
    fc, pp = r["forecast_end_c_loss"], r["pooled_population"]
    caught = [x["serial"] for x in r.get("ranking", [])
              if x["fails_later"] and x["forecast_end_c_loss_pct"] >= 20]
    return (f"At day {day}: the forecast flagged {fc['tp']} of the {fc['failing_later']} capacitors "
            f"that fail later" + (f" ({', '.join(caught)})" if caught else "")
            + f" and {fc['fp']} capacitors that do not fail; the drift score flagged {pp['tp']} of them "
            f"and {pp['fp']} that do not fail.")


CONTEXTS = {"overview": overview, "lot": lot, "part": part, "simulation": simulation,
            "experiment": experiment, "workflow": workflow, "realdata": realdata}


def build(context: str, **ids) -> dict:
    if context not in CONTEXTS:
        raise NotFoundError(f"Unknown AI context {context!r}; known: {sorted(CONTEXTS)}.")
    fn = CONTEXTS[context]
    args = {k: v for k, v in ids.items() if v not in (None, "")}
    if context == "lot":
        out = fn(args["lot"])
    elif context == "part":
        out = fn(args["serial"])
    elif context == "simulation":
        out = fn(args["id"], args.get("serial"))
    elif context in ("experiment", "workflow", "realdata"):
        out = fn(args.get("id"))
    else:
        out = fn()
    subject = ids.get("id") or ids.get("serial") or ids.get("lot") or "all"
    return {"context": context, "subject": str(subject), **out}
