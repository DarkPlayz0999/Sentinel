"""The agent team, phase 1: Data Quality -> (Anomaly || Forecast) -> Combine.

    START -> data_quality --valid--> anomaly  --\
                          \--------> forecast --+--> combine -> END
                           \--invalid--> quarantine -> END

Every agent calls code that already exists; nothing here computes a statistic:
  data_quality  backend.app.validation.validate_dataset + dataset hash re-check
  anomaly       src.features.build_features, src.module_a.module_a_scores
  forecast      src.pipeline.run_module_b (active model artifact if registered)
  combine       src.pipeline.combine + ScreeningService.persist_result

Guarantees:
  * Idempotent: one workflow per (dataset, policy, model, pipeline) key.
  * Checkpointed: LangGraph SqliteSaver, thread_id = workflow_id; a FAILED
    workflow resumes from the last completed agent.
  * Retries transient I/O errors (not logic errors); per-agent timeouts.
  * No agent releases or certifies a component. `combine` persists verdicts
    and flags human review; disposition is a human act.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from src.explain import Thresholds
from src.features import build_features
from src.fusion import RiskWeights
from src.module_a import module_a_scores, static_limit_flags
from src.pipeline import combine as fuse_results
from src.pipeline import run_module_b

from backend.app.agents.contracts import (
    AnomalyReport, CombineReport, DataQualityReport, Finding, ForecastReport,
    WorkflowState,
)
from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger, log_event
from backend.app.ml.inference import (
    FEATURE_VERSION, PIPELINE_VERSION, dataframe_sha256, get_active_forecaster,
)
from backend.app.repositories.repositories import (
    AgentRepository, AuditRepository, ModelRepository, utc_now,
)
from backend.app.services.dataset_service import DatasetService
from backend.app.services.screening_service import ScreeningService
from backend.app.validation.dataset_validator import validate_dataset

__all__ = ["submit", "execute", "build_graph", "AgentTimeout"]

log = get_logger("agents")

# ponytail: fixed per-agent budgets; move to Settings when an operator needs to tune them.
TIMEOUT_S = {"data_quality": 60, "anomaly": 300, "forecast": 900, "combine": 900,
             "quarantine": 30,
             # investigation team (investigation.py)
             "diagnostic": 120, "root_cause": 60, "qa_safety": 60, "report": 60,
             "explainer": 90}
# Transient only. A validation or logic error must fail fast, not loop.
RETRY = RetryPolicy(max_attempts=3, initial_interval=0.5,
                    retry_on=(OSError, sqlite3.OperationalError))


class AgentTimeout(RuntimeError):
    pass


# ------------------------------------------------------ in-process scratch
# Heavy objects (DataFrames, fitted models) stay out of the checkpointed state.
# If a workflow resumes in a fresh process the cache is empty and `_need()`
# recomputes deterministically from dataset_id.
_CACHE: dict[str, dict] = {}
_LOCK = threading.Lock()


def _scratch(wid: str) -> dict:
    with _LOCK:
        return _CACHE.setdefault(wid, {})


def _repo() -> AgentRepository:
    return AgentRepository(get_settings().sqlite_path)


def _frame(state: WorkflowState):
    sc = _scratch(state["workflow_id"])
    if "df" not in sc:
        sc["df"] = DatasetService().load_frame(state["dataset_id"])
    return sc["df"]


# ------------------------------------------------------------ the wrapper
def _agent(name: str, out_key: str | None):
    """Record the step, enforce the timeout, persist findings, emit events."""
    def deco(fn):
        # Deliberately unannotated: LangGraph reads a node's input schema from
        # this hint, and the wrapper serves more than one graph (the phase-1
        # team and the investigation team). Unannotated, each graph uses its
        # own state schema.
        def node(state) -> dict:
            wid = state["workflow_id"]
            repo = _repo()
            step_id, attempt = repo.start_step(wid, name)
            t0 = time.perf_counter()
            # ponytail: a timed-out thread cannot be killed in CPython; it is
            # abandoned and the workflow fails. Process isolation (Celery) is the upgrade.
            pool = ThreadPoolExecutor(max_workers=1)
            try:
                update = pool.submit(fn, state).result(timeout=TIMEOUT_S[name])
            except FutureTimeout:
                err = AgentTimeout(f"{name} exceeded {TIMEOUT_S[name]} s")
                repo.finish_step(step_id, wid, name, status="FAILED",
                                 duration_s=time.perf_counter() - t0, error=str(err))
                raise err from None
            except Exception as exc:
                repo.finish_step(step_id, wid, name, status="FAILED",
                                 duration_s=time.perf_counter() - t0,
                                 error=f"{type(exc).__name__}: {exc}")
                raise
            finally:
                pool.shutdown(wait=False)
            findings = [Finding(agent=name, **f).model_dump() for f in update.pop("_findings", [])]
            repo.add_findings(wid, name, findings)
            repo.finish_step(step_id, wid, name, status="COMPLETED",
                             duration_s=time.perf_counter() - t0,
                             output=update.get(out_key) if out_key else None)
            log_event("AGENT_STEP_COMPLETED", log, workflow_id=wid, agent=name,
                      attempt=attempt, findings=len(findings))
            return {**update, "findings": findings}
        node.__name__ = name
        return node
    return deco


# ---------------------------------------------------------------- agents
@_agent("data_quality", "data_quality")
def data_quality(state: WorkflowState) -> dict:
    ds = DatasetService().get(state["dataset_id"])
    df = _frame(state)
    rep = validate_dataset(df)
    hash_ok = dataframe_sha256(df) == ds["sha256"]
    # Only the built-in generator and the digital twin are KNOWN simulated. An
    # upload is not assumed experimental - that would be a claim this service
    # cannot verify.
    data_class = ("simulated" if ds.get("source") in ("builtin", "simulation")
                  else "unknown")
    _repo().update_workflow(state["workflow_id"], data_class=data_class)

    f = [dict(severity="error", code=x.error_code, message=x.message,
              data={"field": x.field, "count": x.count}) for x in rep.errors]
    f += [dict(severity="warning", code=x.error_code, message=x.message,
               data={"field": x.field, "count": x.count}) for x in rep.warnings]
    if not hash_ok:
        f.append(dict(severity="critical", code="DQ-HASH-MISMATCH",
                      message="The stored file no longer matches the SHA-256 recorded at "
                              "upload. It may have been altered; it will not be screened."))
    if data_class == "simulated":
        f.append(dict(severity="info", code="DQ-SIMULATED",
                      message="Built-in simulated dataset (seed 42). Results must be "
                              "labelled simulated and kept apart from experimental data."))
    report = DataQualityReport(
        valid=rep.ok and hash_ok, rows=rep.rows, lots=rep.lots,
        read_points=rep.read_points, module_b_available=rep.module_b_available,
        hash_verified=hash_ok, data_class=data_class, source=ds.get("source") or "upload",
        error_codes=[x.error_code for x in rep.errors],
        warning_codes=[x.error_code for x in rep.warnings])
    return {"data_quality": report.model_dump(), "_findings": f}


def _need_module_a(state: WorkflowState):
    sc = _scratch(state["workflow_id"])
    if "module_a" not in sc:
        df = _frame(state)
        sc["feat"] = build_features(df)
        sc["module_a"] = module_a_scores(df, sc["feat"])
    return sc["feat"], sc["module_a"]


@_agent("anomaly", "anomaly")
def anomaly(state: WorkflowState) -> dict:
    df = _frame(state)
    _, ma = _need_module_a(state)
    flags = static_limit_flags(df)
    th = Thresholds()
    static_n = int(flags["static_any"].sum())
    l2_n = int((ma["l2_dpat_z"] >= th.level_z).sum())
    l3 = ma["l3_pooled"]
    l3_n = int((l3 > th.pooled).sum()) if l3.notna().any() else None

    f = []
    if static_n:
        f.append(dict(severity="error", code="ANOM-STATIC-BREACH",
                      message=f"{static_n} parts breach a datasheet limit - hard reject, "
                              "independent of any score.", data={"count": static_n}))
    if l3_n:
        f.append(dict(severity="warning", code="ANOM-L3-POOLED",
                      message=f"{l3_n} parts exceed the pooled drift-evidence threshold "
                              f"({th.pooled}, chi-square 4 dof at 0.999) against their own lot.",
                      data={"count": l3_n, "threshold": th.pooled}))
    report = AnomalyReport(parts=len(df), static_breaches=static_n, l2_over_6_sigma=l2_n,
                           l3_over_threshold=l3_n, l3_threshold=th.pooled)
    return {"anomaly": report.model_dump(), "_findings": f}


def _need_module_b(state: WorkflowState):
    sc = _scratch(state["workflow_id"])
    if "module_b" not in sc:
        s = get_settings()
        df = _frame(state)
        loaded = get_active_forecaster(ModelRepository(s.sqlite_path), s.artifact_dir)
        sha = DatasetService().get(state["dataset_id"])["sha256"]
        oof = (loaded.is_out_of_fold_for(sha, set(df["serial"].astype(str)))
               if loaded else False)
        sc["loaded"] = loaded
        sc["module_b"] = run_module_b(
            df, target_reject=s.target_reject_rate,
            forecaster=loaded.model if loaded else None, forecaster_is_out_of_fold=oof)
    return sc["module_b"], sc["loaded"]


@_agent("forecast", "forecast")
def forecast(state: WorkflowState) -> dict:
    mb, loaded = _need_module_b(state)
    available = mb.module_b is not None
    n24 = int(mb.module_b["reject_at_24h"].sum()) if available else 0
    f = []
    if not available:
        f.append(dict(severity="warning", code="FC-UNAVAILABLE",
                      message="No forecast: the dataset lacks the reads Module B needs "
                              "and no trained model artifact is registered."))
    if n24:
        f.append(dict(severity="warning", code="FC-R301-EARLY-REJECT",
                      message=f"{n24} parts: forecast upper bound breaches the safety slope "
                              "from the 0 h and 24 h reads alone (R-301).",
                      data={"count": n24}))
    if available and not mb.out_of_fold:
        f.append(dict(severity="info", code="FC-IN-SAMPLE",
                      message="The forecaster saw these parts (or was fitted in-run). "
                              "Do not quote an MAE from this run."))
    report = ForecastReport(
        available=available, model_artifact_id=loaded.artifact_id if loaded else None,
        out_of_fold=mb.out_of_fold, reject_at_24h=n24,
        exponents={k: round(float(v), 4) for k, v in mb.exponents.items()},
        population_k=mb.population_k)
    return {"forecast": report.model_dump(), "_findings": f}


@_agent("combine", "result")
def combine(state: WorkflowState) -> dict:
    s = get_settings()
    df = _frame(state)
    feat, ma = _need_module_a(state)
    mb, loaded = _need_module_b(state)

    svc = ScreeningService(s)
    run_id = svc.create_run(state["dataset_id"], actor=state.get("actor"))
    _repo().update_workflow(state["workflow_id"], run_id=run_id)
    run = svc.start(run_id)
    t0 = time.perf_counter()
    try:
        res = fuse_results(df, feat, mb, module_a=ma, weights=RiskWeights(),
                           target_reject=s.target_reject_rate)
        svc.persist_result(run, df, res, loaded, t0)
    except Exception as exc:
        svc.fail(run, exc)
        raise

    done = svc.get_run(run_id)
    verdicts = {k: int(v) for k, v in (done.get("summary") or {}).items()}
    over = [l["lot"] for l in done["lot_summary"] if l["status"] == "LOT REVIEW"]
    flagged = verdicts.get("REJECT", 0) + verdicts.get("WATCH", 0)

    f = [dict(severity="warning", code="LOT-PDA",
              message=f"Lot {l['lot']}: {l['reject']}/{l['parts']} rejected "
                      f"({l['reject_fraction']:.1%}) exceeds the {l['pda_limit']:.0%} PDA.",
              data=l) for l in done["lot_summary"] if l["status"] == "LOT REVIEW"]
    if flagged or over:
        f.append(dict(severity="critical", code="HUMAN-REVIEW-REQUIRED",
                      message=f"{verdicts.get('REJECT', 0)} REJECT and {verdicts.get('WATCH', 0)} "
                              "WATCH await QA/MRB disposition. Agents never release or "
                              "certify a component.",
                      data={"run_id": run_id}))
    report = CombineReport(run_id=run_id, verdicts=verdicts, lots_over_pda=over,
                           human_review_required=bool(flagged or over))
    return {"result": report.model_dump(), "_findings": f}


@_agent("quarantine", None)
def quarantine(state: WorkflowState) -> dict:
    dq = state["data_quality"]
    codes = dq["error_codes"] + ([] if dq["hash_verified"] else ["DQ-HASH-MISMATCH"])
    return {"_findings": [dict(
        severity="critical", code="DQ-QUARANTINE",
        message=f"Dataset quarantined ({', '.join(codes)}). No screening run was "
                "created and no downstream agent ran.", data={"codes": codes})]}


def _route(state: WorkflowState):
    # A list fans out: anomaly and forecast run in the same superstep, in parallel.
    return ["anomaly", "forecast"] if state["data_quality"]["valid"] else "quarantine"


# ----------------------------------------------------------------- graph
def build_graph(checkpointer=None):
    g = StateGraph(WorkflowState)
    for name, fn in (("data_quality", data_quality), ("anomaly", anomaly),
                     ("forecast", forecast), ("combine", combine),
                     ("quarantine", quarantine)):
        g.add_node(name, fn, retry_policy=RETRY)
    g.add_edge(START, "data_quality")
    g.add_conditional_edges("data_quality", _route, ["anomaly", "forecast", "quarantine"])
    g.add_edge(["anomaly", "forecast"], "combine")   # waits for both
    g.add_edge("combine", END)
    g.add_edge("quarantine", END)
    return g.compile(checkpointer=checkpointer)


_GRAPHS: dict[str, object] = {}


def _graph():
    """One compiled graph per checkpoint file (tests use a temp DB each)."""
    path = str(Path(get_settings().sqlite_path).with_name("agent_checkpoints.db"))
    with _LOCK:
        if path not in _GRAPHS:
            conn = sqlite3.connect(path, check_same_thread=False)
            _GRAPHS[path] = build_graph(SqliteSaver(conn))
        return _GRAPHS[path]


# ----------------------------------------------------------------- runner
def idempotency_key(dataset_id: str) -> str:
    s = get_settings()
    ds = DatasetService(s).get(dataset_id)
    loaded = get_active_forecaster(ModelRepository(s.sqlite_path), s.artifact_dir)
    parts = [ds["sha256"], s.policy_fingerprint(),
             loaded.artifact_id if loaded else "fit-in-run", PIPELINE_VERSION, FEATURE_VERSION]
    return "idem-" + hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]


def submit(dataset_id: str, *, trigger: str = "manual",
           actor: str | None = None) -> tuple[dict, bool]:
    """Register a workflow. (workflow, created) - created=False means a duplicate."""
    wf, created = _repo().create_workflow(
        idempotency_key=idempotency_key(dataset_id), trigger=trigger,
        dataset_id=dataset_id, actor=actor)
    if created:
        AuditRepository(get_settings().sqlite_path).record(
            "AGENT_WORKFLOW_SUBMITTED", dataset_id=dataset_id, actor=actor,
            metadata={"workflow_id": wf["workflow_id"], "trigger": trigger})
    return wf, created


def execute(workflow_id: str, *, resume: bool = False) -> dict:
    """Run (or resume) a workflow to the end. Always leaves a terminal status."""
    repo = _repo()
    audit = AuditRepository(get_settings().sqlite_path)
    if not repo.claim(workflow_id, "FAILED" if resume else "QUEUED"):
        return repo.get_workflow(workflow_id)   # already running or finished
    wf = repo.get_workflow(workflow_id)
    config = {"configurable": {"thread_id": workflow_id}}
    graph = _graph()
    # Resume from the last checkpoint if one exists; otherwise start fresh.
    inp = None if graph.get_state(config).next else {
        "workflow_id": workflow_id, "dataset_id": wf["dataset_id"],
        "actor": wf.get("actor"), "findings": []}
    t0 = time.perf_counter()
    try:
        final = graph.invoke(inp, config)
        quarantined = not final["data_quality"]["valid"]
        status = "QUARANTINED" if quarantined else "COMPLETED"
        summary = {k: final.get(k) for k in ("data_quality", "anomaly", "forecast", "result")}
        repo.update_workflow(workflow_id, status=status, current_step=None,
                             completed_at=utc_now(),
                             duration_s=round(time.perf_counter() - t0, 3), summary=summary)
        audit.record(f"AGENT_WORKFLOW_{status}", dataset_id=wf["dataset_id"],
                     run_id=(final.get("result") or {}).get("run_id"), actor=wf.get("actor"),
                     metadata={"workflow_id": workflow_id})
    except Exception as exc:
        repo.update_workflow(workflow_id, status="FAILED", completed_at=utc_now(),
                             duration_s=round(time.perf_counter() - t0, 3),
                             error=f"{type(exc).__name__}: {exc}")
        audit.record("AGENT_WORKFLOW_FAILED", dataset_id=wf["dataset_id"],
                     actor=wf.get("actor"),
                     metadata={"workflow_id": workflow_id, "error_type": type(exc).__name__})
        log_event("AGENT_WORKFLOW_FAILED", log, workflow_id=workflow_id,
                  error_type=type(exc).__name__)
        raise
    finally:
        with _LOCK:
            _CACHE.pop(workflow_id, None)
    return repo.get_workflow(workflow_id)
