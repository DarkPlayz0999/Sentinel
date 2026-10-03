"""Fault localisation: which component on a flagged board is the likely cause?

Method: a fault dictionary, the classical test-engineering technique
---------------------------------------------------------------------
Sentinel says WHICH BOARD is abnormal and WHICH ATE PARAMETERS carried the
evidence. It does not - and with four board-level observables cannot - say
which component did it. That is the diagnostic step.

  1. Signatures. For every (component, fault type) in the catalogue, run the
     board's own circuit and thermal model twice on nominal parts - once
     healthy, once with that fault at a reference severity - and record how
     each observable moves: the four ATE parameters (on Sentinel's transform
     scale: log for currents, raw for timing/voltage) and the temperature of
     every part the IR camera sees. This is computed from the model, never
     from ground truth.
  2. Evidence. For the flagged board, take Sentinel's own lot-relative drift
     z-scores (src/features.py, the `drift` view; `early` at hour 24) and the
     lot-relative z of each part's IR temperature rise over the soak. Small
     values are shrunk toward zero (soft threshold) so noise on the
     unaffected axes does not dilute the match.
  3. Match. Each signature is put in the same units (divided by the lot's
     robust spread of that drift) and compared with the evidence by cosine
     similarity. The evidence score is 100 * max(0, cos). The implied severity
     is the projection of the evidence on the signature.

What the score is NOT
---------------------
An evidence score is a similarity, not a probability. It is not calibrated,
and two faults with the same signature get the same score - that is an
AMBIGUITY GROUP, reported as such with the bench test that would separate it.
Four ATE observables cannot tell a leaking C001 from a leaking C002 from a
leaky U001: all three only raise Iddq. Saying so is the honest answer.

Only observed data enters here: the frame Sentinel was given, and the IR
readings. The function never receives a SimResult's truth fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import pandas as pd

from src.features import PARAM_NAMES, build_features, robust_sigma, robust_z, transform

from src.twin.board import Board, get_board
from src.twin.engine import ate_read, thermal_state
from src.twin.faults import CATALOGUE, FaultSpec, apply_effects

__all__ = ["Signature", "fault_dictionary", "board_evidence", "diagnose",
           "detectability", "BENCH_TEST", "S_REF"]

S_REF = 0.5            # reference severity the signatures are computed at
ATE_SHRINK = 1.0       # soft threshold on ATE drift z
IR_SHRINK = 2.0        # soft threshold on IR z (the camera is noisier)
AMBIGUITY_POINTS = 5.0
AMBIGUITY_COS = 0.97

# The bench test that confirms each kind of hypothesis once the part is out.
BENCH_TEST = {
    "capacitor": "LCR meter (C, ESR at 100 kHz) and a DC leakage test of the removed capacitor",
    "resistor": "4-wire resistance measurement, in circuit at TP001/TP002 or on the bench",
    "mosfet": "curve-tracer check of Vth, Rds(on) and off-state leakage",
    "ic": "IDDQ and delay re-test of the device on a known-good socket",
    "connector": "4-wire contact-resistance check of each pin",
    "power_rail": "scope the rail at TP002 under the burn-in load: ripple and sag",
}


@dataclass(frozen=True)
class Signature:
    component_id: str
    kind: str
    fault_type: str
    mechanism: str
    ate: dict[str, float]      # change on Sentinel's transform scale
    ir: dict[str, float]       # temperature change, C


def _nominal_params(board: Board, rows: int) -> dict[str, np.ndarray]:
    out = {}
    for c in board.simulated:
        for name, p in c.params.items():
            out[f"{c.component_id}.{name}"] = np.full(rows, p.nominal, dtype=float)
        if c.theta_c_per_w > 0:
            out[f"{c.component_id}.theta"] = np.full(rows, c.theta_c_per_w, dtype=float)
    return out


# Faults whose effect is stochastic per read; a single seeded run would give a
# noisy signature, so these use the static (steady-state) signature instead.
_STATIC_ONLY = {"VOLTAGE_INSTABILITY"}


def _static_signatures(board: Board, hyps, stress_temp_c: float, read_temp_c: float):
    rows = len(hyps) + 1                      # row 0 is the healthy reference
    params = _nominal_params(board, rows)
    sag = np.zeros(rows)
    for i, (c, m) in enumerate(hyps, start=1):
        d = np.asarray(S_REF)
        for e in m.effects:
            key = f"{c.component_id}.{e.param}"
            params[key][i] = apply_effects(params[key][i:i + 1], [e], d)[0]
        if m.fault_type == "VOLTAGE_INSTABILITY":
            sag[i] = params["PR001.sag"][i] * 0.8      # E|z| for a unit normal
    temps, _ = thermal_state(board, params, stress_temp_c)
    obs, _ = ate_read(params, read_temp_c, sag)
    out = {}
    for i, (c, m) in enumerate(hyps, start=1):
        ate = {}
        for p in PARAM_NAMES:
            t = transform(pd.Series(obs[p][[0, i]]), p).to_numpy()
            ate[p] = float(t[1] - t[0])
        out[(c.component_id, m.fault_type)] = (
            ate, {cid: float(temps[cid][i] - temps[cid][0]) for cid in temps})
    return out


@lru_cache(maxsize=16)
def fault_dictionary(board_id: str = "RB-1", stress_temp_c: float = 125.0,
                     read_temp_c: float = 125.0) -> tuple[Signature, ...]:
    """Every (component, fault) signature on this board, from the model alone.

    A signature is the difference between a faulted and an unfaulted run of
    the SAME nominal board through the full soak, noise switched off: the
    change in 0 h -> 168 h drift of each ATE parameter (Sentinel's transform
    scale, the quantity its `drift` view scores) and of each part's
    temperature rise. Running the engine rather than a steady-state formula
    keeps second-order physics in the signature - an ESR fault heats its
    capacitor, and the hotter dielectric then leaks faster.

    Intermittent faults (random per read) and rail sag use the steady-state
    signature at the reference severity instead.
    """
    from dataclasses import replace
    from src.twin.engine import NoiseConfig, SimConfig, simulate
    board = get_board(board_id)
    hyps = [(c, m) for c in board.simulated for m in CATALOGUE if m.kind == c.kind]
    static = _static_signatures(board, hyps, stress_temp_c, read_temp_c)
    cfg = SimConfig(board_id=board_id, boards=2, seed=0, stress_temp_c=stress_temp_c,
                    read_temp_c=read_temp_c, noise=NoiseConfig(0, 0, 0, 0, 0, 0),
                    spread_mult=0.0, healthy_wide_rate=0.0)

    def drift(res):
        j = res.read_hours.index(168.0)
        ate = {p: float(transform(pd.Series([res.ate_obs[p][0, j]]), p).iloc[0]
                        - transform(pd.Series([res.ate_obs[p][0, 0]]), p).iloc[0])
               for p in PARAM_NAMES}
        return ate, {cid: float(t[0, -1] - t[0, 0]) for cid, t in res.temps.items()}

    clean_ate, clean_ir = drift(simulate(cfg))
    out = []
    for c, m in hyps:
        if m.intermittent or m.fault_type in _STATIC_ONLY:
            ate, ir = static[(c.component_id, m.fault_type)]
        else:
            spec = FaultSpec(c.component_id, m.fault_type, S_REF, 24.0, 0.01, board=0)
            f_ate, f_ir = drift(simulate(replace(cfg, faults=(spec,))))
            ate = {p: f_ate[p] - clean_ate[p] for p in PARAM_NAMES}
            ir = {cid: f_ir[cid] - clean_ir[cid] for cid in f_ir}
        out.append(Signature(c.component_id, c.kind, m.fault_type, m.mechanism, ate, ir))
    return tuple(out)


# Smallest change that counts as "this fault moves this channel": roughly one
# robust sigma of healthy drift at the default metrology.
_VISIBLE = {"Iddq_uA": 0.03, "Ileak_nA": 0.03, "Tpd_ns": 0.02, "Vol_mV": 2.0}
_VISIBLE_IR_C = 0.5


def detectability(board_id: str = "RB-1") -> dict[str, dict[str, list[str]]]:
    """Which channels each fault moves, at the reference severity.

    {component_id: {fault_type: [channels]}}. An empty list means the fault
    has no modelled effect on any ATE parameter or on the IR map of this
    board - Sentinel cannot see it, and the injection form says so up front
    rather than letting a benchmark discover it.
    """
    out: dict[str, dict[str, list[str]]] = {}
    for s in fault_dictionary(board_id):
        ch = [p for p in PARAM_NAMES if abs(s.ate[p]) >= _VISIBLE[p]]
        ch += [f"IR {c}" for c, dt in s.ir.items() if abs(dt) >= _VISIBLE_IR_C]
        out.setdefault(s.component_id, {})[s.fault_type] = ch
    return out


def _shrink(z: np.ndarray, k: float) -> np.ndarray:
    return np.sign(z) * np.maximum(np.abs(z) - k, 0.0)


def board_evidence(frame: pd.DataFrame, ir_rise: pd.DataFrame | None
                   ) -> dict[str, pd.DataFrame]:
    """Lot-relative evidence for every board, from observed data only.

    ``frame`` is exactly what Sentinel was given. ``ir_rise`` is the IR
    camera's temperature rise over the soak, one column per tracked part,
    indexed like ``frame``. Returns z-scores and the lot spreads needed to put
    a signature on the same scale.
    """
    feat = build_features(frame)
    view = "drift" if all(f"z_{p}_drift" in feat.columns for p in PARAM_NAMES) else "early"
    ate_z = pd.DataFrame({p: feat[f"z_{p}_{view}"] for p in PARAM_NAMES}, index=frame.index)
    late = 168 if view == "drift" else 24
    spread = {}
    for p in PARAM_NAMES:
        d = (transform(frame[f"{p}_{late}h"], p) - transform(frame[f"{p}_0h"], p))
        spread[p] = robust_sigma(d) or 1.0
    ir_z = pd.DataFrame(index=frame.index)
    ir_spread = {}
    if ir_rise is not None:
        for cid in ir_rise.columns:
            ir_z[cid] = robust_z(ir_rise[cid])
            ir_spread[cid] = robust_sigma(ir_rise[cid]) or 1.0
    return {"ate_z": ate_z.fillna(0.0), "ir_z": ir_z.fillna(0.0), "view": view,
            "ate_spread": spread, "ir_spread": ir_spread}


def diagnose(serial: str, frame: pd.DataFrame, evidence: dict, *,
             board_id: str = "RB-1", stress_temp_c: float = 125.0,
             read_temp_c: float = 125.0, top: int = 8) -> dict:
    """Ranked component hypotheses for one flagged board."""
    board = get_board(board_id)
    idx = frame.index[frame["serial"] == serial]
    if len(idx) == 0:
        raise KeyError(f"{serial} is not in the screened frame")
    i = idx[0]
    ate_z = evidence["ate_z"].loc[i]
    ir_z = evidence["ir_z"].loc[i] if len(evidence["ir_z"].columns) else pd.Series(dtype=float)
    ir_ids = list(evidence["ir_z"].columns)

    obs = np.concatenate([_shrink(ate_z[list(PARAM_NAMES)].to_numpy(float), ATE_SHRINK),
                          _shrink(ir_z[ir_ids].to_numpy(float), IR_SHRINK)])
    obs_norm = float(np.linalg.norm(obs))

    sigs = fault_dictionary(board_id, float(round(stress_temp_c / 5.0) * 5.0),
                            float(round(read_temp_c / 5.0) * 5.0))
    scored = []
    for s in sigs:
        pred = np.concatenate([
            [s.ate[p] / evidence["ate_spread"][p] for p in PARAM_NAMES],
            [s.ir.get(c, 0.0) / evidence["ir_spread"].get(c, 1.0) for c in ir_ids]])
        pn = float(np.linalg.norm(pred))
        if pn < 1e-9 or obs_norm < 1e-9:
            cos, sev = 0.0, 0.0
        else:
            cos = float(obs @ pred / (obs_norm * pn))
            sev = float(S_REF * (obs @ pred) / (pn * pn))
        score = 100.0 * max(cos, 0.0)
        note = None
        if score > 0 and (sev > 3.0 or sev < 0.02):
            score *= 0.5
            note = ("implied severity outside the modelled range - the pattern "
                    "fits, the magnitude does not")
        scored.append({"s": s, "pred": pred, "score": score, "cos": cos,
                       "implied_severity": sev, "note": note})

    # Equal scores mean equal signatures. Break the tie by parsimony - the
    # hypothesis needing the least extreme degradation to explain the evidence
    # - never by component name, which would bias localisation toward "C".
    def parsimony(h):
        sev = h["implied_severity"]
        return abs(np.log(sev / S_REF)) if sev > 0 else np.inf

    scored.sort(key=lambda h: (-round(h["score"], 1), parsimony(h),
                               h["s"].component_id, h["s"].fault_type))
    best = scored[0]

    def moved(sig: Signature) -> list[str]:
        out = []
        for p in PARAM_NAMES:
            if abs(sig.ate[p] / evidence["ate_spread"][p]) >= 0.5:
                out.append(f"{p} {'up' if sig.ate[p] > 0 else 'down'}")
        for c, dt in sig.ir.items():
            if abs(dt) >= 0.5:
                out.append(f"{c} {'hotter' if dt > 0 else 'cooler'} by {abs(dt):.1f} C")
        return out

    hyps = []
    for rank, h in enumerate(scored[:top], start=1):
        s = h["s"]
        pn = np.linalg.norm(h["pred"]) or 1.0
        bn = np.linalg.norm(best["pred"]) or 1.0
        same_as_best = float(h["pred"] @ best["pred"] / (pn * bn))
        hyps.append({
            "rank": rank, "component_id": s.component_id, "kind": s.kind,
            "fault_type": s.fault_type, "mechanism": s.mechanism,
            "evidence_score": round(h["score"], 1),
            "implied_severity": round(h["implied_severity"], 3),
            "signature": moved(s),
            "similarity_to_top": round(same_as_best, 3),
            "note": h["note"],
        })

    top_score = hyps[0]["evidence_score"] if hyps else 0.0
    group = [h for h in hyps if h["evidence_score"] >= top_score - AMBIGUITY_POINTS
             and h["similarity_to_top"] >= AMBIGUITY_COS]
    group_components = sorted({h["component_id"] for h in group})

    # One row per component, strongest mechanism first: what "top-k" means.
    by_component: list[dict] = []
    for h in hyps:
        if h["component_id"] not in {x["component_id"] for x in by_component}:
            by_component.append(h)

    suspect = hyps[0]["component_id"] if hyps and top_score > 0 else None
    observed = {
        "ate_view": evidence["view"],
        "ate_drift_z": {p: round(float(ate_z[p]), 2) for p in PARAM_NAMES},
        "ir_rise_z": {c: round(float(ir_z[c]), 2) for c in ir_ids},
    }
    carriers = [p for p in PARAM_NAMES if ate_z[p] >= 3.0]
    hot = [c for c in ir_ids if ir_z[c] >= 3.0]
    return {
        "serial": serial,
        "suspect_component": suspect,
        "hypotheses": hyps,
        "components_ranked": [h["component_id"] for h in by_component],
        "ambiguity_group": group_components if len(group_components) > 1 else [],
        "discriminating_tests": (
            [{"component_id": c, "test": BENCH_TEST[board.get(c).kind]}
             for c in group_components] if len(group_components) > 1 else []),
        "observed": observed,
        "carrier_parameters": carriers,
        "hot_components": hot,
        "neighbours": board.neighbours(suspect) if suspect else [],
        "electrical_dependencies": board.electrical_neighbours(suspect) if suspect else [],
        "method": ("fault-dictionary match of lot-relative ATE drift and IR "
                   "evidence against model signatures at severity "
                   f"{S_REF}; evidence scores are cosine similarities x 100, "
                   "not probabilities"),
    }
