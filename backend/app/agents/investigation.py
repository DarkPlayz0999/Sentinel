"""The investigation team: runs ONLY after Sentinel flags a board.

    Sentinel flag -> diagnostic -> root_cause -> qa_safety -> report -> explainer -> END

  diagnostic  src.twin.diagnose on every flagged board: fault-dictionary match
              of Sentinel's lot-relative drift evidence and the IR map;
              neighbours, electrical dependencies, thermal relationships.
  root_cause  ranked hypotheses for the board Sentinel ranked first, each with
              an evidence score (a similarity, NOT a probability).
  qa_safety   data sufficiency, engineering limits, model uncertainty,
              conflicting evidence, simulation validity.
  report      the structured investigation report, and the
              HUMAN-REVIEW-REQUIRED finding. No agent releases a part.
  explainer   the AI agent (Mistral, optional): the report in plain language,
              every number checked against the report before it is kept.

Isolation from ground truth
---------------------------
Every input here is observed: the frame Sentinel screened (re-read from its
dataset, hash-verified at upload), Sentinel's own persisted component results,
and the IR camera. The ground-truth repository is never opened on this path;
tests/test_twin_service.py makes it raise to prove that.

Only the explainer uses a language model, and only to WORD what the four
agents before it computed; it cannot change a score, a verdict or a finding.
"""

from __future__ import annotations

import hashlib
import time

from langgraph.graph import END, START, StateGraph

from backend.app.agents.contracts import (
    DiagnosticReport, Hypothesis, InvestigationReport, InvestigationState,
    QACheck, QASafetyReport, RootCauseReport,
)
from backend.app.agents.graph import RETRY, _agent, _repo
from backend.app.core.logging import get_logger, log_event
from backend.app.repositories.repositories import AuditRepository, utc_now
from backend.app.core.config import get_settings

__all__ = ["build_investigation_graph", "investigate", "MAX_BOARDS"]

log = get_logger("agents.investigation")

MAX_BOARDS = 5          # flagged boards diagnosed per investigation, highest risk first
WEAK_EVIDENCE = 50.0    # below this the best match is reported as weak


def _svc():
    # Local import: the simulation service imports this module to run it.
    from backend.app.services.simulation_service import SimulationService
    return SimulationService()


# ------------------------------------------------------------------ agents
@_agent("diagnostic", "diagnostic")
def diagnostic(state: InvestigationState) -> dict:
    from src.twin.diagnose import board_evidence, diagnose

    svc = _svc()
    run = svc.runs.get(state["simulation_id"])
    cfg = svc.config_of(run)
    frame, ir = svc.observed_evidence(state["simulation_id"], state["dataset_id"])
    ev = board_evidence(frame, ir)
    boards = {}
    findings = []
    for serial in state["serials"][:MAX_BOARDS]:
        d = diagnose(serial, frame, ev, board_id=cfg.board_id,
                     stress_temp_c=cfg.stress_temp_c, read_temp_c=cfg.read_temp_c)
        boards[serial] = d
        top = d["hypotheses"][0] if d["hypotheses"] else None
        if top and top["evidence_score"] > 0:
            findings.append(dict(
                severity="warning", code="DIAG-SUSPECT",
                message=(f"{serial}: the observed pattern best matches {top['component_id']} "
                         f"{top['fault_type'].replace('_', ' ').lower()} (evidence score "
                         f"{top['evidence_score']:.0f} of 100 - a similarity, not a probability)."),
                data={"serial": serial, "component_id": top["component_id"],
                      "fault_type": top["fault_type"], "evidence_score": top["evidence_score"]}))
            if top["evidence_score"] < WEAK_EVIDENCE:
                findings.append(dict(
                    severity="warning", code="DIAG-WEAK-MATCH",
                    message=f"{serial}: no fault signature explains the evidence well "
                            f"(best {top['evidence_score']:.0f}). Treat the suspect as unconfirmed.",
                    data={"serial": serial}))
        if d["ambiguity_group"]:
            findings.append(dict(
                severity="warning", code="DIAG-AMBIGUOUS",
                message=(f"{serial}: {', '.join(d['ambiguity_group'])} produce the same "
                         "signature on every ATE parameter and on the IR map. The screen "
                         "cannot separate them; a bench test after removal can."),
                data={"serial": serial, "group": d["ambiguity_group"],
                      "tests": d["discriminating_tests"]}))
        if d["hot_components"]:
            findings.append(dict(
                severity="info", code="DIAG-THERMAL",
                message=(f"{serial}: IR shows {', '.join(d['hot_components'])} running hotter "
                         "than the same position on its sibling boards (>= 3 robust sigma)."),
                data={"serial": serial, "hot": d["hot_components"]}))
    focus = state["serials"][0]
    fd = boards[focus]
    report = DiagnosticReport(boards=boards, focus_serial=focus,
                              suspect_component=fd["suspect_component"],
                              ambiguity_group=fd["ambiguity_group"])
    return {"diagnostic": report.model_dump(), "_findings": findings}


@_agent("root_cause", "root_cause")
def root_cause(state: InvestigationState) -> dict:
    diag = state["diagnostic"]
    focus = diag["focus_serial"]
    d = diag["boards"][focus]
    seen, hyps = set(), []
    for h in d["hypotheses"]:
        key = (h["component_id"], h["fault_type"])
        if key in seen or h["evidence_score"] <= 0:
            continue
        seen.add(key)
        hyps.append(Hypothesis(rank=len(hyps) + 1, component_id=h["component_id"],
                               fault_type=h["fault_type"], mechanism=h["mechanism"],
                               evidence_score=h["evidence_score"],
                               implied_severity=h["implied_severity"],
                               signature=h["signature"]))
        if len(hyps) == 5:
            break
    lines = "; ".join(f"{h.rank}. {h.component_id} {h.fault_type.replace('_', ' ').lower()} "
                      f"- evidence {h.evidence_score:.0f}" for h in hyps[:3])
    report = RootCauseReport(focus_serial=focus, hypotheses=hyps)
    return {"root_cause": report.model_dump(),
            "_findings": [dict(severity="info", code="RC-HYPOTHESES",
                               message=f"{focus}: {lines}. Scores are similarities, not probabilities.",
                               data={"serial": focus})]}


@_agent("qa_safety", "qa_safety")
def qa_safety(state: InvestigationState) -> dict:
    svc = _svc()
    diag = state["diagnostic"]
    focus = diag["focus_serial"]
    d = diag["boards"][focus]
    comp = svc.screening.get_component(state["run_id"], focus)
    run = svc.screening.get_run(state["run_id"])
    frame, _ = svc.observed_evidence(state["simulation_id"], state["dataset_id"])
    row = frame.loc[frame["serial"] == focus].iloc[0]
    reads = [c for c in frame.columns if c.endswith("h") and "_" in c]
    missing = [c for c in reads if row[c] != row[c]]
    checks: list[QACheck] = []

    checks.append(QACheck(
        check="data sufficiency",
        status="WARN" if missing else "PASS",
        detail=(f"{len(missing)} of {len(reads)} reads missing ({', '.join(missing)}); "
                "lot statistics for those views rest on fewer reads."
                if missing else f"All {len(reads)} ATE reads present for {focus}.")))
    breach = bool(comp.get("static_breach"))
    checks.append(QACheck(
        check="engineering limits",
        status="FAIL" if breach else "PASS",
        detail=("A datasheet limit is breached: hard reject regardless of any score."
                if breach else
                "Passes every datasheet limit. A static test would ship this board - "
                "the flag rests on lot-relative evidence.")))
    oof = bool(run.get("forecast_out_of_fold"))
    checks.append(QACheck(
        check="model uncertainty",
        status="PASS" if oof else "WARN",
        detail=("Module B forecast came from a model that never saw this lot."
                if oof else
                "Module B was fitted on this lot (no trained artifact, or it saw these "
                "boards). Its forecast informs the verdict; its error is not quotable.")))
    carriers = set(d.get("carrier_parameters") or [])
    top = d["hypotheses"][0] if d["hypotheses"] else None
    top_moves = {s.split(" ")[0] for s in (top["signature"] if top else [])}
    conflicts = []
    if d["ambiguity_group"]:
        conflicts.append(f"{len(d['ambiguity_group'])} components share the top signature")
    if carriers and top and not (carriers & top_moves):
        conflicts.append(f"Sentinel's carrier parameter(s) {', '.join(sorted(carriers))} "
                         "are not moved by the top hypothesis")
    checks.append(QACheck(
        check="conflicting evidence", status="WARN" if conflicts else "PASS",
        detail="; ".join(conflicts) if conflicts else
        "The top hypothesis moves the parameters Sentinel flagged, and no other "
        "component matches equally well."))
    weak = (top is None) or top["evidence_score"] < WEAK_EVIDENCE
    checks.append(QACheck(
        check="insufficient evidence", status="WARN" if weak else "PASS",
        detail=("No hypothesis explains the evidence well; do not act on the suspect "
                "without a bench test." if weak else
                f"Best evidence score {top['evidence_score']:.0f} of 100.")))
    ev = svc.runs.get(state["simulation_id"])
    err = ev.get("error") if ev else None
    checks.append(QACheck(
        check="simulation validity",
        status="FAIL" if err else "INFO",
        detail=("The simulation recorded a solver failure: " + str(err.get("message"))
                if err else
                "Measurements are SIMULATED (provenance PHYSICS_MODEL, MNA solver). "
                "Results must be labelled simulated and kept apart from experimental data.")))
    checks.append(QACheck(
        check="score semantics", status="INFO",
        detail="Evidence scores are cosine similarities x 100, not calibrated "
               "probabilities. The ranking score of a replacement is not a health estimate."))

    status = "REVIEW" if any(c.status in ("WARN", "FAIL") for c in checks) else "PASS"
    report = QASafetyReport(status=status, checks=checks)
    f = [dict(severity="warning" if c.status == "WARN" else
              "error" if c.status == "FAIL" else "info",
              code="QA-" + c.check.upper().replace(" ", "-"), message=c.detail,
              data={"serial": focus, "status": c.status})
         for c in checks if c.status != "PASS"]
    return {"qa_safety": report.model_dump(), "_findings": f}


@_agent("report", "report")
def report(state: InvestigationState) -> dict:
    svc = _svc()
    diag, rc, qa = state["diagnostic"], state["root_cause"], state["qa_safety"]
    focus = diag["focus_serial"]
    d = diag["boards"][focus]
    comp = svc.screening.get_component(state["run_id"], focus)
    expl = comp.get("explanation") or {}
    primary = expl.get("primary_reason")
    top = rc["hypotheses"][0] if rc["hypotheses"] else None

    actions = []
    if top and not d["ambiguity_group"]:
        actions.append(f"Replace {top['component_id']} on {focus} with the top-ranked "
                       "candidate and rerun the burn-in to confirm.")
    elif d["ambiguity_group"]:
        actions.append("Separate the ambiguity group with a bench test before replacing: "
                       + "; ".join(f"{t['component_id']}: {t['test']}"
                                   for t in d["discriminating_tests"]))
    if top:
        from src.twin.diagnose import BENCH_TEST
        from src.twin.board import get_board
        kind = get_board().get(top["component_id"]).kind
        actions.append(f"After removal, confirm with: {BENCH_TEST[kind]}.")
    actions.append("Disposition is a human decision (QA/MRB). No agent releases or "
                   "certifies a component.")

    driver = ""
    if primary:
        fired = primary.get("code") if primary.get("code_fired") else None
        driver = (f", driven mainly by this board's {str(primary.get('title', '')).lower()} "
                  "against the other boards in its lot" + (f" ({fired})" if fired else ""))
    summary = (f"Sentinel scored {focus} {comp['risk_score']:.1f} of 100 ({comp['verdict']})"
               + driver + ". "
               + (f"The observed evidence best matches {top['component_id']} "
                  f"{top['fault_type'].replace('_', ' ').lower()} (evidence score "
                  f"{top['evidence_score']:.0f})." if top else
                  "No fault signature matched the evidence.")
               + (f" QA/safety review: {qa['status']}." if qa else ""))
    rep = InvestigationReport(
        simulation_id=state["simulation_id"], focus_serial=focus,
        verdict=comp["verdict"], risk_score=float(comp["risk_score"]),
        primary_reason=primary, suspect_component=top["component_id"] if top else None,
        suspect_fault_type=top["fault_type"] if top else None,
        evidence_score=top["evidence_score"] if top else None,
        ambiguity_group=d["ambiguity_group"], discriminating_tests=d["discriminating_tests"],
        qa_status=qa["status"], recommended_actions=actions, summary=summary,
        disclaimers=["SIMULATED DATA - accelerated simulation time, not a validated burn-in.",
                     "Evidence scores are similarities, not probabilities.",
                     "Not flight certified, not space qualified; decision support only."])
    return {"report": rep.model_dump(),
            "_findings": [dict(severity="critical", code="HUMAN-REVIEW-REQUIRED",
                               message=f"{focus} awaits QA/MRB disposition. {summary}",
                               data={"serial": focus, "run_id": state["run_id"]})]}


@_agent("explainer", "explanation")
def explainer(state: InvestigationState) -> dict:
    """The AI agent: words the report for a non-expert. Decides nothing.

    Mistral when MISTRAL_API_KEY is set, otherwise the built-in wording. Every
    number in the AI text is checked against the report; one invented number
    and the AI text is discarded (backend/app/ai/narrator.py).
    """
    from backend.app.ai.narrator import narrate_sheet
    rep, rc, qa = state["report"], state["root_cause"], state["qa_safety"]
    sheet = {"context": "investigation", "subject": rep["focus_serial"],
             "title": f"Investigation of board {rep['focus_serial']}",
             "facts": {
                 "data": "SIMULATED digital-twin lot",
                 "board": rep["focus_serial"], "sentinel_verdict": rep["verdict"],
                 "risk_score": round(rep["risk_score"], 1),
                 "report_summary": rep["summary"],
                 "suspect_component": rep["suspect_component"],
                 "suspect_fault_type": rep["suspect_fault_type"],
                 "evidence_score_out_of_100": rep["evidence_score"],
                 "evidence_score_meaning": "a similarity between observed and modelled patterns, NOT a probability",
                 "other_hypotheses": [{"component": h["component_id"], "fault": h["fault_type"],
                                       "evidence_score": h["evidence_score"]}
                                      for h in rc["hypotheses"][1:4]],
                 "ambiguity_group": rep["ambiguity_group"],
                 "qa_safety_status": qa["status"],
                 "qa_checks": [{"check": c["check"], "status": c["status"], "meaning": c["detail"]}
                               for c in qa["checks"]],
                 "what_the_verdict_is_based_on": (
                     "this board's own ATE measurements compared with the other boards in the same "
                     "lot; the risk score is a weighted sum of named sub-scores"),
                 "recommended_actions": rep["recommended_actions"]}}
    out = narrate_sheet("summary", sheet)
    by = (f"Mistral ({out['model']}), number check passed" if out["source"] == "mistral"
          else "the built-in explainer")
    expl = {"plain_summary": out["text"], "source": out["source"], "model": out["model"],
            "number_check": out["number_check"], "note": out["note"]}
    return {"explanation": expl,
            "_findings": [dict(severity="info", code="AI-EXPLANATION",
                               message=f"Plain-language explanation written by {by}."
                                       + (f" {out['note']}" if out["note"] else ""),
                               data={"source": out["source"], "number_check": out["number_check"]})]}


# ------------------------------------------------------------------- graph
def build_investigation_graph():
    g = StateGraph(InvestigationState)
    for name, fn in (("diagnostic", diagnostic), ("root_cause", root_cause),
                     ("qa_safety", qa_safety), ("report", report), ("explainer", explainer)):
        g.add_node(name, fn, retry_policy=RETRY)
    g.add_edge(START, "diagnostic")
    g.add_edge("diagnostic", "root_cause")
    g.add_edge("root_cause", "qa_safety")
    g.add_edge("qa_safety", "report")
    g.add_edge("report", "explainer")
    g.add_edge("explainer", END)
    return g.compile()


_GRAPH = None


def investigate(simulation_id: str, dataset_id: str, run_id: str, serials: list[str],
                *, actor: str | None = None) -> dict:
    """Run the investigation for the flagged boards. Returns the final state.

    Recorded as an `agent_workflows` row (trigger `sentinel_alert`), so its
    steps and findings appear on the Agent operations page beside phase 1.
    """
    global _GRAPH
    if not serials:
        raise ValueError("the investigation runs only when Sentinel flagged a board")
    repo = _repo()
    key = "inv-" + hashlib.sha256(f"{simulation_id}|{run_id}|{','.join(serials)}".encode()
                                  ).hexdigest()[:24]
    wf, created = repo.create_workflow(idempotency_key=key, trigger="sentinel_alert",
                                       dataset_id=dataset_id, actor=actor)
    wid = wf["workflow_id"]
    if not created and wf["status"] == "COMPLETED":
        return {"workflow_id": wid, **(wf.get("summary") or {})}
    if not repo.claim(wid, "QUEUED"):
        return {"workflow_id": wid, **(wf.get("summary") or {})}
    repo.update_workflow(wid, data_class="simulated", run_id=run_id)
    if _GRAPH is None:
        _GRAPH = build_investigation_graph()
    t0 = time.perf_counter()
    audit = AuditRepository(get_settings().sqlite_path)
    try:
        final = _GRAPH.invoke({"workflow_id": wid, "simulation_id": simulation_id,
                               "dataset_id": dataset_id, "run_id": run_id,
                               "serials": serials, "actor": actor, "findings": []})
        summary = {k: final.get(k) for k in ("root_cause", "qa_safety", "report", "explanation")}
        repo.update_workflow(wid, status="COMPLETED", current_step=None,
                             completed_at=utc_now(),
                             duration_s=round(time.perf_counter() - t0, 3), summary=summary)
        audit.record("INVESTIGATION_COMPLETED", dataset_id=dataset_id, run_id=run_id,
                     actor=actor, metadata={"workflow_id": wid,
                                            "simulation_id": simulation_id})
    except Exception as exc:
        repo.update_workflow(wid, status="FAILED", completed_at=utc_now(),
                             duration_s=round(time.perf_counter() - t0, 3),
                             error=f"{type(exc).__name__}: {exc}")
        log_event("INVESTIGATION_FAILED", log, workflow_id=wid,
                  error_type=type(exc).__name__)
        raise
    return {"workflow_id": wid, **final}
