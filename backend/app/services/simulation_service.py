"""Digital twin orchestration: the closed loop, end to end.

    create -> burn-in (checkpoints, monitoring) -> measurements -> Sentinel
      -> agents (phase 1) -> investigation (only if flagged) -> 3D highlight
      -> replacement -> rerun -> before/after -> reveal ground truth -> benchmark

Sentinel is not re-implemented anywhere on this path. The observed frame is
registered as an ordinary dataset (source `simulation`) and screened by the
existing agent workflow and ScreeningService, exactly as an uploaded CSV would
be. What the twin adds is the measurements going in and the 3D/diagnostic
context coming out.

Blind mode
----------
In BLIND mode the API withholds, until reveal: the injected faults, every
internal parameter, health, stress and the noise-free observables. It shows
only what a test floor could observe - ATE reads, IR camera, rail monitor -
plus Sentinel's verdicts and the agents' conclusions. Ground truth is read
only in `reveal()`, which refuses to run before Sentinel has predicted.

Determinism
-----------
Results are recomputed from the stored config and seed on a cache miss, and
the engine is deterministic, so a restarted server shows the same lot. The
database holds the audit record: what was measured, predicted and decided.
"""

from __future__ import annotations

import threading
import zlib
from collections import OrderedDict
from dataclasses import replace

import numpy as np
import pandas as pd

from src.explain import MODEL_VERSION
from src.features import PARAM_NAMES, PARAMS as SENTINEL_PARAMS, robust_z, transform

from src.twin import TWIN_VERSION
from src.twin.board import KEY_PARAMS, REPLACEABLE_KINDS, get_board
from src.twin.circuit import SimulationFailed, find_ngspice, run_ngspice
from src.twin.diagnose import detectability
from src.twin.engine import (OBSERVABLES, NoiseConfig, SimConfig, SimResult, Swap,
                             ate_read, simulate)
from src.twin.faults import FaultSpec, catalogue_dict
from src.twin.benchmark import score
from src.twin import replace as twin_replace

from backend.app.core.config import Settings, get_settings
from backend.app.core.exceptions import ConflictError, NotFoundError, ScreeningError
from backend.app.core.logging import get_logger, log_event
from backend.app.repositories.repositories import AuditRepository, JobRepository
from backend.app.repositories.simulation import (
    GroundTruthRepository, SimulationRepository,
)
from backend.app.services.dataset_service import DatasetService
from backend.app.services.screening_service import ScreeningService

__all__ = ["SimulationService", "SIH_DEMO"]

log = get_logger("simulation")

# The primary SIH demonstration: a capacitor develops ESR degradation during
# accelerated burn-in and stays inside the datasheet the whole time.
SIH_DEMO = {"component_id": "C001", "fault_type": "ESR_INCREASE", "severity": 0.8,
            "start_h": 24.0, "growth_rate": 0.015}

_CACHE: "OrderedDict[tuple, SimResult]" = OrderedDict()
_CACHE_MAX = 8
_LOCK = threading.Lock()
PHASE1 = "burn-in-1"


def _cache_get(key):
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
    return None


def _cache_put(key, value):
    with _LOCK:
        _CACHE[key] = value
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)


def _f(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return round(x, 6) if np.isfinite(x) else None


def _crc(*parts) -> int:
    return zlib.crc32("|".join(str(p) for p in parts).encode())


class SimulationService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.settings.ensure_dirs()
        db = self.settings.sqlite_path
        self.runs = SimulationRepository(db)
        self.jobs = JobRepository(db)
        self.audit = AuditRepository(db)
        self.datasets = DatasetService(self.settings)
        self.screening = ScreeningService(self.settings)

    # ================================================================ config
    def _run(self, sid: str) -> dict:
        run = self.runs.get(sid)
        if not run:
            raise NotFoundError(f"No simulation with id {sid!r}.")
        return run

    def config_of(self, run: dict) -> SimConfig:
        faults = tuple(FaultSpec(f["component_id"], f["fault_type"], f["severity"],
                                 f["start_h"], f["growth_rate"], board=f["board_index"])
                       for f in self.runs.faults(run["simulation_id"])
                       if f["source"] != "replacement part")
        return replace(SimConfig.from_dict(run["config"]), faults=faults)

    def _event(self, run: dict, event_type: str, payload: dict | None = None, **kw) -> None:
        self.runs.event(run["simulation_id"], event_type, payload, seed=run["random_seed"],
                        version=TWIN_VERSION, **kw)

    def visible(self, run: dict) -> bool:
        """May truth be shown? Always in VISIBLE mode; in BLIND only after reveal."""
        return run["mode"] == "VISIBLE" or bool(run.get("revealed_at"))

    def result(self, sid: str, run: dict | None = None) -> SimResult:
        run = run or self._run(sid)
        key = (sid, PHASE1)
        hit = _cache_get(key)
        if hit is not None:
            return hit
        res = simulate(self.config_of(run))
        if run["options"].get("solver") == "ngspice":
            res = self._spice_lot(run, res)
        _cache_put(key, res)
        return res

    # ================================================================ create
    def create(self, req: dict, *, actor: str | None = None) -> dict:
        board = get_board(req.get("board_id", "RB-1"))
        seed = int(req.get("seed", 42))
        boards = int(req.get("boards", 200))
        mode = req.get("mode", "VISIBLE")
        faults_in = list(req.get("faults") or [])
        hidden = req.get("hidden_faults")
        if req.get("scenario") == "sih_demo":
            mode = "BLIND"
            faults_in = [dict(SIH_DEMO)]
            hidden = None

        from src.twin.faults import get_model
        rng = np.random.default_rng([seed, 90210])
        resolved: list[dict] = []
        for f in faults_in:
            if not board.has(f["component_id"]):
                raise ConflictError(f"{board.board_id} has no component {f['component_id']!r}.")
            b = f.get("board")
            b = int(rng.integers(boards)) if b is None else int(b)
            try:
                get_model(board.get(f["component_id"]).kind, f["fault_type"])
                spec = FaultSpec(f["component_id"], f["fault_type"],
                                 float(f.get("severity", 0.6)), float(f.get("start_h", 24.0)),
                                 float(f.get("growth_rate", 0.004)), board=b)
            except ValueError as exc:
                raise ConflictError(str(exc)) from exc
            if b >= boards:
                raise ConflictError(f"board index {b} is outside a lot of {boards}.")
            resolved.append({**spec.as_dict(), "source": "injected"})
        if hidden:
            det = detectability(board.board_id)
            pool = [(c.component_id, ft) for c in board.simulated
                    for ft, ch in det[c.component_id].items()
                    if (not hidden.get("observable_only", True) or ch)
                    and (not hidden.get("component_ids") or c.component_id in hidden["component_ids"])]
            if not pool:
                raise ConflictError("No fault in the catalogue matches the hidden-fault filter.")
            idx = rng.choice(boards, size=min(int(hidden.get("count", 1)), boards), replace=False)
            for b in sorted(int(x) for x in idx):
                cid, ft = pool[int(rng.integers(len(pool)))]
                lo, hi = hidden.get("severity", (0.4, 1.0))
                s0, s1 = hidden.get("start_h", (0.0, 72.0))
                g0, g1 = hidden.get("growth_rate", (0.004, 0.02))
                spec = FaultSpec(cid, ft, float(rng.uniform(lo, hi)), float(rng.uniform(s0, s1)),
                                 float(rng.uniform(g0, g1)), board=b)
                resolved.append({**spec.as_dict(), "source": "hidden-random"})

        n_prev = len(self.runs.list(10_000))
        lot_id = f"SIM{n_prev + 1:04d}"
        noise = req.get("noise") or {}
        cfg = SimConfig(board_id=board.board_id, boards=boards, seed=seed, lot_id=lot_id,
                        stress_temp_c=float(req.get("stress_temp_c", 125.0)),
                        read_temp_c=float(req.get("read_temp_c", 125.0)),
                        noise=NoiseConfig(**{k: v for k, v in noise.items()}),
                        faults=tuple(FaultSpec(**{k: v for k, v in f.items() if k != "source"})
                                     for f in resolved))
        config = cfg.as_dict()
        config.pop("faults")
        options = {"solver": req.get("solver", "auto"),
                   "auto_screen": bool(req.get("auto_screen", True)),
                   "monitor_z": float(req.get("monitor_z", 4.5)),
                   "label": req.get("label", ""), "scenario": req.get("scenario", "custom")}
        sid = self.runs.create(mode=mode, board_id=board.board_id, lot_id=lot_id,
                               boards=boards, seed=seed, config=config, options=options,
                               software_version=TWIN_VERSION, model_version=MODEL_VERSION,
                               actor=actor)
        self.runs.add_faults(sid, [{**f, "serial": f"{lot_id}-B{f['board'] + 1:03d}"}
                                   for f in resolved], seed=seed, version=TWIN_VERSION)
        run = self._run(sid)
        self._event(run, "SIMULATION_CREATED", {
            "mode": mode, "boards": boards, "board_id": board.board_id, "lot_id": lot_id,
            "faults_injected": len(resolved) if mode == "VISIBLE" else "hidden",
            "time_base": "ACCELERATED SIMULATION TIME"})
        self.audit.record("SIMULATION_CREATED", actor=actor,
                          metadata={"simulation_id": sid, "mode": mode, "seed": seed})
        log_event("SIMULATION_CREATED", log, simulation_id=sid, mode=mode, boards=boards)
        return self.get(sid)

    def add_fault(self, sid: str, f: dict, *, actor: str | None = None) -> dict:
        """Inject one more fault before the burn-in starts."""
        from src.twin.faults import get_model
        run = self._run(sid)
        if run["status"] != "CREATED":
            raise ConflictError(f"Simulation is {run['status']}; faults are injected before start.")
        board = get_board(run["board_id"])
        if not board.has(f["component_id"]):
            raise ConflictError(f"{board.board_id} has no component {f['component_id']!r}.")
        n = len(self.runs.faults(sid))
        b = f.get("board")
        if b is None:
            b = int(np.random.default_rng([run["random_seed"], 90210, n]).integers(run["boards"]))
        if not 0 <= int(b) < run["boards"]:
            raise ConflictError(f"board index {b} is outside a lot of {run['boards']}.")
        try:
            get_model(board.get(f["component_id"]).kind, f["fault_type"])
            spec = FaultSpec(f["component_id"], f["fault_type"], float(f.get("severity", 0.6)),
                             float(f.get("start_h", 24.0)), float(f.get("growth_rate", 0.004)),
                             board=int(b))
        except ValueError as exc:
            raise ConflictError(str(exc)) from exc
        self.runs.add_faults(sid, [{**spec.as_dict(), "source": "injected",
                                    "serial": f"{run['lot_id']}-B{int(b) + 1:03d}"}],
                             seed=run["random_seed"], version=TWIN_VERSION)
        with _LOCK:
            _CACHE.pop((sid, PHASE1), None)
        self._event(run, "FAULT_INJECTED",
                    spec.as_dict() if run["mode"] == "VISIBLE" else {"hidden": True},
                    component_id=f["component_id"] if run["mode"] == "VISIBLE" else None)
        return self.get(sid)

    # ============================================================ run / step
    def queue(self, sid: str, *, actor: str | None = None) -> str:
        run = self._run(sid)
        if not self.runs.claim(sid, ("CREATED", "PAUSED"), "QUEUED"):
            raise ConflictError(f"Simulation is {run['status']}; only CREATED or PAUSED can start.")
        job_id = self.jobs.create("SIMULATION", actor=actor)
        self.runs.update(sid, job_id=job_id)
        self._event(run, "SIMULATION_QUEUED", {"job_id": job_id})
        return job_id

    def execute(self, sid: str, *, job_id: str | None = None) -> dict:
        """Run the burn-in to 168 h, then screen if auto_screen. Background worker."""
        run = self._run(sid)
        if job_id:
            self.jobs.mark_running(job_id)
        self.runs.update(sid, status="RUNNING")
        try:
            res = self.result(sid, run)
            for h in self._remaining(run):
                self._checkpoint(run, res, h)
                run = self._run(sid)
            self._finish_burn_in(run, res)
            if run["options"].get("auto_screen", True):
                self.screen(sid)
            if job_id:
                self.jobs.mark_completed(job_id)
        except SimulationFailed as exc:
            self.runs.update(sid, status="SIMULATION_FAILED", error=exc.as_dict())
            self._event(run, "SIMULATION_FAILED", exc.as_dict())
            if job_id:
                self.jobs.mark_failed(job_id, str(exc), "SIMULATION_FAILED")
            raise
        except Exception as exc:
            self.runs.update(sid, status="FAILED",
                             error={"message": f"{type(exc).__name__}: {exc}"})
            self._event(run, "SIMULATION_ERROR", {"error_type": type(exc).__name__,
                                                  "message": str(exc)[:500]})
            if job_id:
                self.jobs.mark_failed(job_id, str(exc), "SIMULATION_ERROR")
            raise
        return self.get(sid)

    def _remaining(self, run: dict) -> list[int]:
        return [int(h) for h in run["config"]["checkpoints"]
                if h > run["sim_time_h"] or (h == 0 and not self._has_reads(run))]

    def _has_reads(self, run: dict) -> bool:
        return bool(self.runs.measurements(run["simulation_id"], limit=1))

    def step(self, sid: str) -> dict:
        """Advance exactly one read point, synchronously (interactive stepping)."""
        run = self._run(sid)
        if run["status"] not in ("CREATED", "PAUSED"):
            raise ConflictError(f"Simulation is {run['status']}; step needs CREATED or PAUSED.")
        todo = self._remaining(run)
        if not todo:
            raise ConflictError("The burn-in is already complete.")
        res = self.result(sid, run)
        self._checkpoint(run, res, todo[0])
        run = self._run(sid)
        if len(todo) == 1:
            self._finish_burn_in(run, res)
            if run["options"].get("auto_screen", True):
                self.screen(sid)
        else:
            self.runs.update(sid, status="PAUSED")
        return self.get(sid)

    def _checkpoint(self, run: dict, res: SimResult, h: int) -> None:
        """Persist one read point: ATE reads, IR camera, rail; then monitor."""
        sid, seed = run["simulation_id"], run["random_seed"]
        j = res.read_hours.index(float(h))
        k = res.grid_index(float(h))
        rows = []
        for i, s in enumerate(res.serials):
            for p in OBSERVABLES:
                v = res.ate_obs[p][i, j]
                rows.append({"serial": s, "time_h": h, "parameter": p, "value": _f(v),
                             "unit": SENTINEL_PARAMS[p]["unit"],
                             "measurement_source": res.provenance[p]["measurement_source"],
                             "solver": res.provenance[p]["solver"]})
            for c, arr in res.ir_obs.items():
                rows.append({"serial": s, "component_id": c, "time_h": h,
                             "parameter": "ir_temp_c", "value": _f(arr[i, k]), "unit": "C",
                             "measurement_source": "PHYSICS_MODEL", "solver": "lumped-thermal"})
            rows.append({"serial": s, "time_h": h, "parameter": "rail_v",
                         "value": _f(res.rail_obs[i, k]), "unit": "V",
                         "measurement_source": "PHYSICS_MODEL", "solver": "delay-model"})
        self.runs.add_measurements(sid, PHASE1, rows, seed=seed, version=TWIN_VERSION)
        self.runs.update(sid, sim_time_h=float(h))
        self._event(run, "CHECKPOINT_REACHED", {
            "time_h": h, "boards": res.n, "reads": len(rows),
            "time_base": "ACCELERATED SIMULATION TIME"})
        crossings = self._monitor(run, res, h)
        if (crossings and 0 < h < 168 and run["options"].get("auto_screen", True)):
            self._interim_screen(run, res, h, crossings)

    def _monitor(self, run: dict, res: SimResult, h: int) -> list[dict]:
        """Continuous monitoring on OBSERVED data: lot-relative drift so far.

        Uses src.features.transform/robust_z so the monitor's statistic is the
        same kind Sentinel uses. It triggers, it never decides.
        """
        if h == 0:
            return []
        zmax = run["options"].get("monitor_z", 4.5)
        j = res.read_hours.index(float(h))
        hits = []
        for p in OBSERVABLES:
            d = transform(pd.Series(res.ate_obs[p][:, j]), p) - transform(pd.Series(res.ate_obs[p][:, 0]), p)
            z = robust_z(d).to_numpy()
            for i in np.flatnonzero(np.nan_to_num(z) >= zmax):
                hits.append({"serial": res.serials[i], "channel": p, "z": round(float(z[i]), 2)})
        rise = res.ir_rise(upto_h=float(h))
        for c in rise.columns:
            z = robust_z(rise[c]).to_numpy()
            for i in np.flatnonzero(np.nan_to_num(z) >= zmax):
                hits.append({"serial": res.serials[i], "channel": f"IR {c}",
                             "component_id": c, "z": round(float(z[i]), 2)})
        hits.sort(key=lambda x: -x["z"])
        for x in hits[:12]:
            self._event(run, "THRESHOLD_CROSSED", {**x, "time_h": h, "monitor_z": zmax},
                        serial=x["serial"], component_id=x.get("component_id"))
        return hits

    def _finish_burn_in(self, run: dict, res: SimResult) -> None:
        """Write component states and ground truth once the soak is complete."""
        sid, seed = run["simulation_id"], run["random_seed"]
        idx = [res.grid_index(float(h)) for h in run["config"]["checkpoints"]]
        comps = []
        for i, s in enumerate(res.serials):
            for c in res.board.simulated:
                cid = c.component_id
                comps.append({
                    "serial": s, "component_id": cid, "model": c.model, "kind": c.kind,
                    "as_built": {p: _f(res.as_built[f"{cid}.{p}"][i]) for p in c.params},
                    "state": {
                        "read_h": run["config"]["checkpoints"],
                        "values": {p: [_f(res.values[f"{cid}.{p}"][i, k]) for k in idx]
                                   for p in c.params},
                        "temp_c": ([_f(res.temps[cid][i, k]) for k in idx]
                                   if cid in res.temps else None),
                        "health": ([_f(res.health[cid][i, k]) for k in idx]
                                   if cid in res.health else None),
                        "stress": ([_f(res.stress[cid][i, k]) for k in idx]
                                   if cid in res.stress else None)}})
        self.runs.replace_components(sid, PHASE1, comps, seed=seed, version=TWIN_VERSION)
        truth = res.truth_frame()
        gl = {}
        for g in res.glitches:
            gl.setdefault(g["board"], []).append(g)
        gt_rows = []
        for r in truth.itertuples():
            gt_rows.append({"serial": r.serial, "component_id": r.fault_components or None,
                            "is_faulty": r.is_faulty,
                            "truth": {"faults": [f for f in res.faults if f["board"] == r.board],
                                      "detectable": bool(r.detectable),
                                      "true_168h": {p: getattr(r, f"true_{p}_168h") for p in PARAM_NAMES},
                                      "glitches": gl.get(r.board, [])}})
        GroundTruthRepository(self.settings.sqlite_path).write(
            sid, PHASE1, gt_rows, seed=seed, version=TWIN_VERSION)
        self.runs.update(sid, status="SIMULATED", sim_time_h=168.0)
        self._event(run, "BURN_IN_COMPLETE", {"time_h": 168, "boards": res.n,
                                              "time_base": "ACCELERATED SIMULATION TIME"})

    # ================================================================= screen
    def _register(self, frame: pd.DataFrame, label: str, actor: str | None) -> str:
        return self.datasets.register_local_frame(frame, label, actor=actor,
                                                  source="simulation")["dataset_id"]

    def _interim_screen(self, run: dict, res: SimResult, h: int, crossings: list[dict]) -> None:
        """A threshold crossed mid-soak: screen what has been measured so far."""
        frame = res.sentinel_frame(upto_h=float(h))
        ds = self._register(frame, f"{run['lot_id']}_{h}h.csv", run.get("actor"))
        rid = self.screening.create_run(ds, actor=run.get("actor"))
        self.screening.execute(rid)
        comps = self.screening.list_components(rid, limit=100_000)
        self.runs.add_predictions(run["simulation_id"], PHASE1, h, [
            {"serial": c["serial"], "risk_score": c["risk_score"], "verdict": c["verdict"],
             "reason_codes": c["reason_codes"]} for c in comps],
            run_id=rid, dataset_id=ds, model_version=MODEL_VERSION,
            seed=run["random_seed"], version=TWIN_VERSION)
        flagged = [c for c in comps if c["verdict"] != "ACCEPT"]
        self._event(run, "SENTINEL_INTERIM_SCREEN", {
            "time_h": h, "run_id": rid, "trigger": "THRESHOLD_CROSSED",
            "crossings": len(crossings), "flagged": len(flagged),
            "top": [{"serial": c["serial"], "risk_score": round(c["risk_score"], 1),
                     "verdict": c["verdict"]} for c in flagged[:5]]})

    def screen(self, sid: str) -> dict:
        """Send the observed frame to Sentinel through the phase-1 agent team,
        then run the investigation team if anything was flagged."""
        from backend.app.agents import graph as agents
        from backend.app.agents.investigation import investigate

        run = self._run(sid)
        if run["status"] not in ("SIMULATED", "SCREENED", "INVESTIGATED", "FAILED"):
            raise ConflictError(f"Simulation is {run['status']}; screening needs the full burn-in.")
        res = self.result(sid, run)
        self.runs.update(sid, status="SCREENING")
        frame = res.sentinel_frame()
        ds = self._register(frame, f"{run['lot_id']}.csv", run.get("actor"))
        self._event(run, "MEASUREMENTS_SENT", {
            "dataset_id": ds, "rows": len(frame), "columns": list(frame.columns),
            "note": "serial, lot and observed ATE reads only - no component, fault or truth"})

        wf, created = agents.submit(ds, trigger="simulation", actor=run.get("actor"))
        if created or wf["status"] in ("QUEUED", "FAILED"):
            wf = agents.execute(wf["workflow_id"], resume=wf["status"] == "FAILED")
        if wf["status"] != "COMPLETED":
            self.runs.update(sid, status="FAILED", workflow_id=wf["workflow_id"],
                             error={"message": f"agent workflow {wf['status']}"})
            raise ScreeningError(f"Agent workflow {wf['workflow_id']} ended {wf['status']}.")
        run_id = (wf.get("summary") or {}).get("result", {}).get("run_id") or wf.get("run_id")
        comps = self.screening.list_components(run_id, limit=100_000)
        self.runs.add_predictions(sid, PHASE1, 168, [
            {"serial": c["serial"], "risk_score": c["risk_score"], "verdict": c["verdict"],
             "reason_codes": c["reason_codes"]} for c in comps],
            run_id=run_id, dataset_id=ds, model_version=MODEL_VERSION,
            seed=run["random_seed"], version=TWIN_VERSION)
        counts = {v: sum(1 for c in comps if c["verdict"] == v) for v in ("ACCEPT", "WATCH", "REJECT")}
        flagged = [c for c in comps if c["verdict"] != "ACCEPT"]   # already highest risk first
        focus = flagged[0]["serial"] if flagged else None
        self.runs.update(sid, status="SCREENED", dataset_id=ds, run_id=run_id,
                         workflow_id=wf["workflow_id"], focus_serial=focus)
        self._event(run, "SENTINEL_RESULT", {"run_id": run_id, "workflow_id": wf["workflow_id"],
                                             "verdicts": counts, "focus_serial": focus})
        for c in flagged[:5]:
            self._event(run, "SENTINEL_FLAGGED", {
                "risk_score": round(c["risk_score"], 1), "verdict": c["verdict"],
                "codes": [r["code"] for r in c["reason_codes"]]}, serial=c["serial"])

        if flagged:
            inv = investigate(sid, ds, run_id, [c["serial"] for c in flagged],
                              actor=run.get("actor"))
            rep = inv.get("report") or {}
            diag = (inv.get("diagnostic") or {}).get("boards", {})
            for serial, d in diag.items():
                self.runs.set_suspect(sid, PHASE1, 168, serial, d.get("suspect_component"))
            self.runs.update(sid, status="INVESTIGATED", investigation_id=inv["workflow_id"],
                             investigation={
                                 "report": rep, "root_cause": inv.get("root_cause"),
                                 "explanation": inv.get("explanation"),
                                 "qa_safety": inv.get("qa_safety"),
                                 "boards": {s: {k: d[k] for k in (
                                     "suspect_component", "components_ranked", "hypotheses",
                                     "ambiguity_group", "discriminating_tests", "observed",
                                     "carrier_parameters", "hot_components", "neighbours",
                                     "electrical_dependencies")} for s, d in diag.items()}})
            self._event(run, "DIAGNOSIS_COMPLETE", {
                "workflow_id": inv["workflow_id"], "focus_serial": focus,
                "suspect_component": rep.get("suspect_component"),
                "evidence_score": rep.get("evidence_score"),
                "ambiguity_group": rep.get("ambiguity_group"),
                "qa_status": rep.get("qa_status")},
                serial=focus, component_id=rep.get("suspect_component"))
            if run["options"].get("solver") in ("auto", "ngspice"):
                self._spice_check(self._run(sid), res, focus)
        return self.get(sid)

    # ============================================================ ngspice
    def _spice_solver(self, run: dict, serial: str):
        def solve(name, netlist, values):
            sol, _ = run_ngspice(netlist, {k: float(np.ravel(v)[0]) for k, v in values.items()},
                                 board=serial, simulation_id=run["simulation_id"])
            return {k: np.asarray([v]) for k, v in sol.items()}
        return solve

    def _spice_check(self, run: dict, res: SimResult, serial: str) -> None:
        """Cross-check one board's 168 h DC reads against a local ngspice."""
        if not find_ngspice():
            self._event(run, "SPICE_UNAVAILABLE", {
                "note": "ngspice not found; DC reads come from the built-in MNA solver "
                        "(provenance PHYSICS_MODEL). Set SENTINEL_NGSPICE to enable SPICE."},
                serial=serial)
            return
        i, k = res.board_row(serial), res.grid_index(168.0)
        params = {key: np.asarray([v[i, k]]) for key, v in res.values.items()}
        try:
            mna, _ = ate_read(params, res.config.read_temp_c)
            spice, _ = ate_read(params, res.config.read_temp_c,
                                solve=self._spice_solver(run, serial))
        except SimulationFailed as exc:
            self._event(run, "SPICE_CROSSCHECK_FAILED", exc.as_dict(), serial=serial)
            if run["options"].get("solver") == "ngspice":
                self.runs.update(run["simulation_id"], status="SIMULATION_FAILED",
                                 error=exc.as_dict())
            return
        diff = {p: abs(spice[p][0] - mna[p][0]) / max(abs(mna[p][0]), 1e-12)
                for p in ("Iddq_uA", "Ileak_nA", "Vol_mV")}
        self.runs.add_measurements(run["simulation_id"], "spice-check", [
            {"serial": serial, "time_h": 168, "parameter": p, "value": _f(spice[p][0]),
             "unit": SENTINEL_PARAMS[p]["unit"], "measurement_source": "SPICE",
             "solver": "ngspice"} for p in diff], seed=run["random_seed"], version=TWIN_VERSION)
        self._event(run, "SPICE_CROSSCHECK", {
            "max_relative_difference": max(diff.values()),
            "by_parameter": diff, "note": "noise-free DC reads, ngspice vs built-in MNA"},
            serial=serial)

    def _spice_lot(self, run: dict, res: SimResult) -> SimResult:
        """solver=ngspice: every DC read of every board through ngspice.

        Observed values are rescaled by the SPICE/MNA ratio of the noise-free
        value, so the tester noise realisation is unchanged and only the
        solver differs. A failure stops the run as SIMULATION_FAILED.
        """
        for j, h in enumerate(res.read_hours):
            k = res.grid_index(h)
            for i, s in enumerate(res.serials):
                params = {key: np.asarray([v[i, k]]) for key, v in res.values.items()}
                mna, _ = ate_read(params, res.config.read_temp_c)
                spice, _ = ate_read(params, res.config.read_temp_c,
                                    solve=self._spice_solver(run, s))
                for p in ("Iddq_uA", "Ileak_nA", "Vol_mV"):
                    ratio = spice[p][0] / mna[p][0] if mna[p][0] else 1.0
                    res.ate_obs[p][i, j] *= ratio
        for p in ("Iddq_uA", "Ileak_nA", "Vol_mV"):
            res.provenance[p] = {**res.provenance[p], "measurement_source": "SPICE",
                                 "solver": "ngspice"}
        return res

    # ======================================================= investigation
    def observed_evidence(self, sid: str, dataset_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
        """What the diagnostic agent may see: Sentinel's frame and the IR camera."""
        frame = self.datasets.load_frame(dataset_id)
        res = self.result(sid)
        ir = res.ir_rise()
        pos = [res.board_row(s) for s in frame["serial"]]
        ir = ir.iloc[pos].set_axis(frame.index)
        return frame, ir

    # ========================================================= replacement
    def _reel_history(self) -> dict[str, float]:
        """Each reel's recorded defect rate, updated by observed rework outcomes."""
        prior_n = 100.0
        out = {}
        reps = self.runs.replacements()
        for reel, rp in twin_replace.REELS.items():
            mine = [r for r in reps if r["reel"] == reel and r.get("outcome")]
            bad = sum(1 for r in mine if r["outcome"] != "ACCEPT")
            out[reel] = round(100.0 * (rp["history_pct"] / 100.0 * prior_n + bad)
                              / (prior_n + len(mine)), 2)
        return out

    def candidates(self, sid: str, serial: str, component_id: str) -> dict:
        run = self._run(sid)
        if run["status"] not in ("SCREENED", "INVESTIGATED"):
            raise ConflictError("Candidates are offered after Sentinel has screened the lot.")
        res = self.result(sid, run)
        if serial not in res.serials:
            raise NotFoundError(f"No board {serial!r} in {sid}.")
        comp = get_board(run["board_id"]).get(component_id)
        if comp.kind not in REPLACEABLE_KINDS:
            raise ConflictError(f"{component_id} is a {comp.kind}: it is repaired, not "
                                "swapped from a reel. Check the regulator and the rail.")
        cands = twin_replace.candidates(res, serial, component_id, history=self._reel_history())
        return {"serial": serial, "component_id": component_id,
                "criteria_weights": twin_replace.WEIGHTS,
                "criteria_full_scale": twin_replace.FULL_SCALE,
                "score_kind": "ranking score - not a health estimate or a survival probability",
                "candidates": [c.public() for c in cands]}

    def _observed_board(self, res: SimResult, row: int, j_end: int, k_end: int,
                        component_id: str) -> dict:
        return {"ate_168h": {p: _f(res.ate_obs[p][row, j_end]) for p in OBSERVABLES},
                "ir_temp_c": (_f(res.ir_obs[component_id][row, k_end])
                              if component_id in res.ir_obs else None)}

    def replace(self, sid: str, serial: str, component_id: str, candidate_id: str, *,
                actor: str | None = None) -> dict:
        run = self._run(sid)
        offer = self.candidates(sid, serial, component_id)
        res = self.result(sid, run)
        cands = twin_replace.candidates(res, serial, component_id, history=self._reel_history())
        chosen = next((c for c in cands if c.candidate_id == candidate_id), None)
        if chosen is None:
            raise NotFoundError(f"No candidate {candidate_id!r}; offered: "
                                f"{[c['candidate_id'] for c in offer['candidates']]}.")
        board = get_board(run["board_id"])
        comp = board.get(component_id)
        n_prev = sum(1 for r in self.runs.replacements(sid) if r["board_serial"] == serial)
        phase = f"rework-{n_prev + 1}"
        row = res.board_row(serial)
        board_index = int(res.board_index[row])
        cfg = self.config_of(run)

        self._event(run, "REPLACEMENT_SELECTED", {
            "candidate_id": candidate_id, "reel": chosen.reel,
            "ranking_score": chosen.ranking_score, "phase": phase},
            serial=serial, component_id=component_id)
        swap = Swap(board=board_index, component_id=component_id, values=chosen.values,
                    fault=chosen.latent_fault, at_h=168.0,
                    seed_key=_crc(candidate_id, phase))
        rw = simulate(cfg, swap=swap, only_board=board_index)
        _cache_put((sid, phase), rw)

        # ---- the pulled part goes to the bench: an OBSERVED measurement
        k_end = res.grid_index(168.0)
        j_end = res.read_hours.index(168.0)
        removed_vals = {p: float(res.values[f"{component_id}.{p}"][row, k_end]) for p in comp.params}
        bench = twin_replace.bench_measure(
            removed_vals, comp.kind,
            np.random.default_rng(_crc(run["random_seed"], board_index, phase, "bench")))

        # ---- rerun the screen: the lot with this board's second soak in place
        lot = res.sentinel_frame()
        new_row = rw.sentinel_frame(offset_h=168.0)
        for c in new_row.columns:
            if c not in ("serial", "lot"):
                lot.loc[lot["serial"] == serial, c] = float(new_row[c].iloc[0])
        ds = self._register(lot, f"{run['lot_id']}_{phase}_{serial}.csv", actor)
        rid = self.screening.create_run(ds, actor=actor)
        self.screening.execute(rid)
        after_c = self.screening.get_component(rid, serial)
        before_p = next((p for p in self.runs.predictions(sid, phase=PHASE1, read_h=168)
                         if p["board_serial"] == serial), None)

        k2 = rw.grid_index(336.0)
        j2 = rw.read_hours.index(336.0)
        before = {"serial": serial, "component_id": component_id,
                  "risk_score": before_p["risk_score"] if before_p else None,
                  "verdict": before_p["verdict"] if before_p else None,
                  "reason_codes": [r["code"] for r in (before_p or {}).get("reason_codes", [])],
                  **self._observed_board(res, row, j_end, k_end, component_id),
                  "bench_removed_part": bench}
        after = {"serial": serial, "component_id": f"{component_id}-R",
                 "candidate_id": candidate_id,
                 "risk_score": after_c["risk_score"], "verdict": after_c["verdict"],
                 "reason_codes": [r["code"] for r in after_c.get("reason_codes", [])],
                 **self._observed_board(rw, 0, j2, k2, component_id),
                 "incoming_inspection": chosen.inspection}
        truth_before = {p: _f(res.values[f"{component_id}.{p}"][row, k_end]) for p in comp.params}
        truth_after = {p: _f(rw.values[f"{component_id}.{p}"][0, k2]) for p in comp.params}

        # ---- persist: measurements of the second soak, truth, prediction, replacement
        rows = []
        for jj, h in enumerate(rw.read_hours):
            if h < 168.0 or jj < len(cfg.checkpoints):
                continue
            for p in OBSERVABLES:
                rows.append({"serial": serial, "time_h": h - 168.0, "parameter": p,
                             "value": _f(rw.ate_obs[p][0, jj]), "unit": SENTINEL_PARAMS[p]["unit"],
                             "measurement_source": rw.provenance[p]["measurement_source"],
                             "solver": rw.provenance[p]["solver"]})
        self.runs.add_measurements(sid, phase, rows, seed=run["random_seed"], version=TWIN_VERSION)
        GroundTruthRepository(self.settings.sqlite_path).write(sid, phase, [{
            "serial": serial, "component_id": component_id,
            "is_faulty": int(bool(chosen.latent_fault) or any(
                f["board"] == board_index and f["component_id"] != component_id
                for f in res.faults)),
            "truth": {"new_part": {k: _f(v) for k, v in chosen.values.items()},
                      "new_part_latent_fault": chosen.latent_fault.as_dict() if chosen.latent_fault else None,
                      "removed_part_at_168h": truth_before,
                      "new_part_at_168h_of_rerun": truth_after}}],
            seed=run["random_seed"], version=TWIN_VERSION)
        self.runs.add_predictions(sid, phase, 168, [{
            "serial": serial, "risk_score": after_c["risk_score"], "verdict": after_c["verdict"],
            "reason_codes": after_c.get("reason_codes", [])}], run_id=rid, dataset_id=ds,
            model_version=MODEL_VERSION, seed=run["random_seed"], version=TWIN_VERSION)
        rep_id = self.runs.add_replacement(sid, {
            "phase": phase, "serial": serial, "component_id": component_id,
            "candidate_id": candidate_id, "reel": chosen.reel, "candidate": chosen.public(),
            "hidden": {"values": chosen.values,
                       "latent_fault": chosen.latent_fault.as_dict() if chosen.latent_fault else None,
                       "truth_before": truth_before, "truth_after": truth_after},
            "before": before, "after": after, "removed_bench": bench,
            "outcome": after_c["verdict"], "run_id": rid, "dataset_id": ds},
            seed=run["random_seed"], version=TWIN_VERSION, model_version=MODEL_VERSION,
            actor=actor)
        self._event(run, "RERUN_COMPLETED", {
            "phase": phase, "run_id": rid, "before": {"risk_score": before["risk_score"],
                                                      "verdict": before["verdict"]},
            "after": {"risk_score": after["risk_score"], "verdict": after["verdict"]}},
            serial=serial, component_id=component_id)
        self.audit.record("SIMULATION_REPLACEMENT", run_id=rid, serial=serial, actor=actor,
                          metadata={"simulation_id": sid, "replacement_id": rep_id,
                                    "component_id": component_id, "candidate_id": candidate_id,
                                    "outcome": after_c["verdict"]})
        return self.comparison(sid)

    def comparison(self, sid: str) -> dict:
        run = self._run(sid)
        show = self.visible(run)
        out = []
        for r in self.runs.replacements(sid):
            item = {k: r[k] for k in ("replacement_id", "phase", "board_serial", "component_id",
                                      "candidate_id", "reel", "candidate", "before", "after",
                                      "removed_bench", "outcome", "run_id", "timestamp")}
            if show:
                item["truth"] = r["hidden"]
            out.append(item)
        return {"simulation_id": sid, "replacements": out, "truth_visible": show}

    # ============================================================== reads
    def get(self, sid: str) -> dict:
        run = self._run(sid)
        show = self.visible(run)
        faults = self.runs.faults(sid)
        out = {k: run[k] for k in (
            "simulation_id", "created_at", "updated_at", "status", "mode", "board_id",
            "lot_id", "boards", "random_seed", "config", "options", "sim_time_h",
            "software_version", "model_version", "dataset_id", "run_id", "workflow_id",
            "investigation_id", "focus_serial", "investigation", "job_id", "revealed_at",
            "error")}
        out["time_base"] = "ACCELERATED SIMULATION TIME"
        out["truth_visible"] = show
        out["faults"] = ([{k: f[k] for k in ("board_serial", "board_index", "component_id",
                                             "fault_type", "severity", "start_h",
                                             "growth_rate", "source")} for f in faults]
                         if show else {"hidden": True, "count": "hidden until reveal"})
        preds = self.runs.predictions(sid, phase=PHASE1, read_h=168)
        out["verdicts"] = {v: sum(1 for p in preds if p["verdict"] == v)
                           for v in ("ACCEPT", "WATCH", "REJECT")} if preds else None
        out["interim_screens"] = sorted({p["read_h"] for p in self.runs.predictions(sid, phase=PHASE1)
                                         if p["read_h"] != 168})
        out["replacements"] = len(self.runs.replacements(sid))
        return out

    def list(self, limit: int = 50) -> list[dict]:
        return [{k: r[k] for k in ("simulation_id", "created_at", "status", "mode", "lot_id",
                                   "boards", "random_seed", "sim_time_h", "focus_serial")}
                | {"label": (r.get("options") or {}).get("label", ""),
                   "scenario": (r.get("options") or {}).get("scenario", "custom")}
                for r in self.runs.list(limit)]

    def boards(self, sid: str) -> dict:
        """The lot at a glance: every board's latest observed reads and verdict."""
        run = self._run(sid)
        show = self.visible(run)
        t = run["sim_time_h"]
        have = self._has_reads(run)
        res = self.result(sid, run)
        reads = [h for h in run["config"]["checkpoints"] if h <= t] if have else []
        preds = {p["board_serial"]: p for p in self.runs.predictions(sid, phase=PHASE1, read_h=168)}
        faulty = res.faulty_boards() if show else set()
        rows = []
        for i, s in enumerate(res.serials):
            j = res.read_hours.index(float(reads[-1])) if reads else None
            p = preds.get(s)
            row = {"serial": s, "index": i,
                   "latest": ({q: _f(res.ate_obs[q][i, j]) for q in OBSERVABLES} if j is not None else None),
                   "risk_score": _f(p["risk_score"]) if p else None,
                   "verdict": p["verdict"] if p else None,
                   "suspect_component": p.get("component_id") if p else None}
            if show:
                row["is_faulty"] = int(i in faulty)
            rows.append(row)
        return {"simulation_id": sid, "time_h": t if have else None,
                "reads": reads, "truth_visible": show, "boards": rows}

    def timeline(self, sid: str, serial: str, phase: str = PHASE1) -> dict:
        """Everything the 3D view animates for one board, up to the current time."""
        run = self._run(sid)
        show = self.visible(run)
        if phase == PHASE1:
            res, offset = self.result(sid, run), 0.0
            t_max = run["sim_time_h"] if self._has_reads(run) else -1.0
        else:
            res = _cache_get((sid, phase))
            if res is None:
                raise NotFoundError(f"Phase {phase!r} is not available (rerun it to rebuild).")
            offset, t_max = 168.0, 168.0
        if serial not in res.serials:
            raise NotFoundError(f"No board {serial!r} in {sid}.")
        i = res.board_row(serial)
        k0 = res.grid_index(offset)
        ks = [k for k in range(k0, len(res.grid)) if res.grid[k] - offset <= t_max + 1e-9]
        hours = [float(res.grid[k] - offset) for k in ks]
        # The lot's median IR reading at each position and hour: the reference
        # the lot-relative thermal view subtracts. Observed data, all boards.
        lot_res = self.result(sid, run)
        lot_k = [k - k0 for k in ks]
        ir_med = {c: [_f(v) for v in np.median(lot_res.ir_obs[c][:, lot_k], axis=0)]
                  for c in lot_res.ir_obs}
        out = {"simulation_id": sid, "serial": serial, "phase": phase, "hours": hours,
               "time_base": "ACCELERATED SIMULATION TIME", "truth_visible": show,
               "observed": {
                   "ir_temp_c": {c: [_f(v) for v in res.ir_obs[c][i, ks]] for c in res.ir_obs},
                   "ir_lot_median_c": ir_med,
                   "rail_v": [_f(v) for v in res.rail_obs[i, ks]],
                   "ate": {p: [{"time_h": h - offset, "value": _f(res.ate_obs[p][i, j])}
                               for j, h in enumerate(res.read_hours)
                               if offset <= h <= offset + 168 and h - offset <= t_max]
                           for p in OBSERVABLES}},
               "provenance": res.provenance}
        if show:
            comps = {}
            for c in res.board.simulated:
                cid = c.component_id
                comps[cid] = {
                    "values": {p: [_f(v) for v in res.values[f"{cid}.{p}"][i, ks]] for p in c.params},
                    "temp_c": [_f(v) for v in res.temps[cid][i, ks]] if cid in res.temps else None,
                    "health": [_f(v) for v in res.health[cid][i, ks]] if cid in res.health else None,
                    "stress": [_f(v) for v in res.stress[cid][i, ks]] if cid in res.stress else None,
                    "power_w": [_f(v) for v in res.power[cid][i, ks]] if cid in res.power else None}
            b = int(res.board_index[i])
            out["truth"] = {"components": comps,
                            "nodes": {n: [_f(v) for v in arr[i, ks]] for n, arr in res.nodes.items()},
                            "ate_true": {p: [_f(v) for v in res.ate_true[p][i, ks]] for p in OBSERVABLES},
                            "faults": [f for f in res.faults if f["board"] == b],
                            "glitches": [g for g in res.glitches if g["board"] == b]}
        return out

    def components(self, sid: str, serial: str, t: float | None = None) -> dict:
        """Component explorer: every part's digital state on one board at hour t.

        `status` is the investigation's conclusion (observed evidence), never
        simulator truth. `failure_probability` is null on purpose: nothing
        here is calibrated to be a probability. Truth fields appear only when
        truth is visible.
        """
        run = self._run(sid)
        show = self.visible(run)
        res = self.result(sid, run)
        if serial not in res.serials:
            raise NotFoundError(f"No board {serial!r} in {sid}.")
        i = res.board_row(serial)
        t_now = run["sim_time_h"] if self._has_reads(run) else 0.0
        t = t_now if t is None else min(float(t), t_now)
        k = res.grid_index(round(t / res.config.dt_h) * res.config.dt_h)
        inv = (run.get("investigation") or {}).get("boards", {}).get(serial) or {}
        scores: dict[str, float] = {}
        for h in inv.get("hypotheses", []):
            scores[h["component_id"]] = max(scores.get(h["component_id"], 0.0), h["evidence_score"])
        pred = next((p for p in self.runs.predictions(sid, phase=PHASE1, read_h=168)
                     if p["board_serial"] == serial), None)
        forecast = None
        if run.get("run_id"):
            c = self.screening.get_component(run["run_id"], serial)
            forecast = {"predicted_168h": c.get("predicted_168h"),
                        "upper_168h": c.get("prediction_upper")}
        suspect = inv.get("suspect_component")
        group = set(inv.get("ambiguity_group") or [])
        out = []
        for c in res.board.components:
            cid = c.component_id
            status = "OK"
            if cid == suspect:
                status = (pred or {}).get("verdict") or "WATCH"
            elif cid in group:
                status = "WATCH"
            item = {**c.as_dict(), "status": status,
                    "anomaly_score": scores.get(cid),
                    "anomaly_score_kind": "evidence score from the diagnostic agent (similarity x 100)",
                    "failure_probability": None,
                    "observed": {"ir_temp_c": _f(res.ir_obs[cid][i, k]) if cid in res.ir_obs else None}}
            if show and c.params:
                item["truth"] = {
                    "values": {p: _f(res.values[f"{cid}.{p}"][i, k]) for p in c.params},
                    "temperature_c": _f(res.temps[cid][i, k]) if cid in res.temps else None,
                    "health": _f(res.health[cid][i, k]) if cid in res.health else None,
                    "degradation": (_f(1.0 - res.health[cid][i, k]) if cid in res.health else None),
                    "stress": _f(res.stress[cid][i, k]) if cid in res.stress else None}
            out.append(item)
        return {"simulation_id": sid, "serial": serial, "time_h": t, "truth_visible": show,
                "verdict": (pred or {}).get("verdict"), "risk_score": (pred or {}).get("risk_score"),
                "reason_codes": (pred or {}).get("reason_codes", []), "forecast": forecast,
                "components": out}

    def decide(self, sid: str, serial: str, decision: str, note: str, *,
               actor: str | None = None) -> dict:
        """Record a human disposition. The only place a board is dispositioned."""
        run = self._run(sid)
        if serial not in self.result(sid, run).serials:
            raise NotFoundError(f"No board {serial!r} in {sid}.")
        self._event(run, "HUMAN_DISPOSITION", {"decision": decision, "note": note,
                                               "actor": actor}, serial=serial)
        self.audit.record("SIMULATION_DISPOSITION", serial=serial, actor=actor,
                          metadata={"simulation_id": sid, "decision": decision, "note": note})
        return {"simulation_id": sid, "serial": serial, "decision": decision, "recorded": True}

    def events(self, sid: str, after: int = 0, limit: int = 500) -> list[dict]:
        self._run(sid)
        return self.runs.events_after(sid, after, limit)

    def audit_trail(self, sid: str) -> dict:
        run = self._run(sid)
        out = {"simulation_id": sid, "events": self.runs.events_after(sid, 0, 5000)}
        if run.get("run_id"):
            out["sentinel_audit"] = self.screening.audit_trail(run["run_id"], 500)
        out["replacements"] = self.comparison(sid)["replacements"]
        return out

    # ============================================================= reveal
    def reveal(self, sid: str, *, actor: str | None = None) -> dict:
        """Open the ground truth and score Sentinel against it.

        Refused until a final prediction exists: the whole value of a blind
        benchmark is that the prediction was made first.
        """
        run = self._run(sid)
        preds = self.runs.predictions(sid, phase=PHASE1, read_h=168)
        if not preds:
            raise ConflictError("Ground truth opens only after Sentinel has made its "
                                "168 h prediction. Screen the lot first.")
        if not run.get("revealed_at"):
            from backend.app.repositories.repositories import utc_now
            self.runs.update(sid, revealed_at=utc_now())
            self._event(run, "GROUND_TRUTH_REVEALED", {"actor": actor})
            self.audit.record("SIMULATION_TRUTH_REVEALED", actor=actor,
                              metadata={"simulation_id": sid})
            run = self._run(sid)

        res = self.result(sid, run)
        truth = res.truth_frame()
        pred = pd.DataFrame({"serial": [p["board_serial"] for p in preds],
                             "risk_score": [p["risk_score"] for p in preds],
                             "verdict": [p["verdict"] for p in preds]})
        # Detection hour: the earliest screen (interim or final) that flagged it.
        detect = {}
        for p in sorted(self.runs.predictions(sid, phase=PHASE1), key=lambda x: x["read_h"]):
            if p["verdict"] != "ACCEPT" and p["board_serial"] not in detect:
                detect[p["board_serial"]] = float(p["read_h"])
        pred["detect_h"] = pred["serial"].map(detect)
        boards = ((run.get("investigation") or {}).get("boards") or {})
        pred["components_ranked"] = pred["serial"].map(
            lambda s: (boards.get(s) or {}).get("components_ranked") or [])
        bench = score(pred, truth, forecast_out_of_fold=False)
        bench["localization_note"] = ("localisation scored on flagged faulty boards the "
                                      "investigation team diagnosed (the top "
                                      "flagged boards, highest risk first)")
        bench.pop("forecast", None)
        faults = [{k: f[k] for k in ("board_serial", "component_id", "fault_type", "severity",
                                     "start_h", "growth_rate", "source")}
                  for f in self.runs.faults(sid)]
        repl = []
        truth_rows = {r["board_serial"]: r for r in GroundTruthRepository(
            self.settings.sqlite_path).read(sid, PHASE1)}
        for r in self.runs.replacements(sid):
            t = truth_rows.get(r["board_serial"], {})
            true_c = set((t.get("component_id") or "").split(",")) - {""}
            repl.append({"board_serial": r["board_serial"], "replaced": r["component_id"],
                         "was_the_faulty_part": r["component_id"] in true_c,
                         "outcome": r["outcome"],
                         "new_part_latent_fault": (r["hidden"] or {}).get("latent_fault")})
        return {"simulation_id": sid, "revealed_at": run["revealed_at"], "faults": faults,
                "faulty_boards": [
                    {"serial": r.serial, "components": r.fault_components,
                     "fault_types": r.fault_types, "severity": round(r.max_severity, 3),
                     "detectable": bool(r.detectable),
                     "sentinel_verdict": pred.loc[pred.serial == r.serial, "verdict"].iloc[0]
                     if (pred.serial == r.serial).any() else None}
                    for r in truth[truth.is_faulty == 1].itertuples()],
                "benchmark": bench, "replacements": repl,
                "operating_point": "flagged = WATCH or REJECT at 168 h; REJECT band sized "
                                   "to the 5 % PDA budget"}

    # =========================================================== catalogue
    @staticmethod
    def catalogue(board_id: str = "RB-1") -> dict:
        board = get_board(board_id)
        return {"board": board.as_dict(), "faults": catalogue_dict(),
                "detectability": detectability(board_id),
                "key_params": KEY_PARAMS, "replaceable_kinds": list(REPLACEABLE_KINDS),
                "sih_demo": SIH_DEMO, "ngspice": find_ngspice() is not None,
                "time_base": "ACCELERATED SIMULATION TIME"}
