"""Replacement candidates and their explicit, measurable ranking.

When a component is judged bad the rework technician pulls a replacement from
stock. The twin models three stock reels of the same part number with
different histories, draws candidates from them, and ranks the candidates on
criteria a reliability engineer can check line by line:

    tolerance_used_pct       incoming inspection: the worst parameter's distance
                             from nominal, as a percentage of its own 3-sigma
                             tolerance band (relative for normal parameters,
                             log-ratio for lognormal ones like leakage)
    predicted_drift_pct      the reel's median healthy aging amplitude,
                             Arrhenius-scaled to this socket's temperature.
                             A MODEL prediction from population data, not a
                             measurement of this part.
    operating_temp_c         thermal model: this part fitted into this board
    electrical_stress_pct    dissipation (or voltage) over the part's rating
    historical_defect_pct    the reel's recorded latent-defect rate, updated
                             with every rework outcome the twin has recorded

    ranking score = 100 - sum(weight * normalised penalty)

The score is a RANKING SCORE. It is not a health estimate and not a
probability of survival: nothing in this repo has been calibrated to make it
one. Every candidate also carries hidden truth - its own as-built values and,
at the reel's latent rate, its own latent defect - which only the rerun
reveals. A replacement can fail. That is the point of rerunning.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

import numpy as np

from src.twin.board import KEY_PARAMS, REPLACEABLE_KINDS, get_board
from src.twin.engine import SimResult, thermal_state, _af
from src.twin.faults import FaultSpec, fault_models_for

__all__ = ["REELS", "WEIGHTS", "Candidate", "candidates", "bench_measure"]

# Stock reels. `latent_rate` is hidden truth; `history_pct` is what the
# stores record says - the ranking may use only the latter.
REELS = {
    "A": dict(label="Reel A - qualified supplier, 2 years clean history",
              center=1.00, spread=1.0, aging=0.020, latent_rate=0.01, history_pct=1.2),
    "B": dict(label="Reel B - second source, same part number",
              center=1.03, spread=1.0, aging=0.030, latent_rate=0.03, history_pct=3.5),
    "C": dict(label="Reel C - broker stock, date code unknown",
              center=0.97, spread=1.5, aging=0.050, latent_rate=0.08, history_pct=9.0),
}

WEIGHTS = {"tolerance_used_pct": 0.30, "predicted_drift_pct": 0.30,
           "operating_temp_c": 0.15, "electrical_stress_pct": 0.15,
           "historical_defect_pct": 0.10}
# Value of each criterion at which its penalty saturates (penalty = 1).
FULL_SCALE = {"tolerance_used_pct": 100.0, "predicted_drift_pct": 20.0,
              "operating_temp_c": 40.0, "electrical_stress_pct": 100.0,
              "historical_defect_pct": 10.0}
BENCH_NOISE = 0.01


@dataclass
class Candidate:
    candidate_id: str
    reel: str
    reel_label: str
    inspection: dict            # observed incoming-inspection values
    criteria: dict              # the five criteria
    penalties: dict             # weighted penalty per criterion
    ranking_score: float
    # hidden truth, never serialised to a client before the rerun
    values: dict
    latent_fault: FaultSpec | None

    def public(self) -> dict:
        return {"candidate_id": self.candidate_id, "reel": self.reel,
                "reel_label": self.reel_label, "inspection": self.inspection,
                "criteria": self.criteria, "penalties": self.penalties,
                "ranking_score": self.ranking_score,
                "score_kind": "ranking score (not a health or survival probability)"}


def _seed(*parts) -> int:
    return zlib.crc32("|".join(str(p) for p in parts).encode())


def bench_measure(values: dict, kind: str, rng: np.random.Generator) -> dict:
    """A bench measurement of a loose part: key parameters, 1 % instrument noise."""
    return {p: float(values[p]) * (1.0 + BENCH_NOISE * rng.standard_normal())
            for p in KEY_PARAMS.get(kind, ()) if p in values}


def candidates(result: SimResult, serial: str, component_id: str, *,
               count: int = 3, history: dict[str, float] | None = None) -> list[Candidate]:
    """Replacement candidates for one component on one board, best first.

    Deterministic in (simulation seed, board index, component). ``history`` lets the
    service fold recorded rework outcomes into each reel's defect rate.
    """
    board = get_board(result.config.board_id)
    comp = board.get(component_id)
    if comp.kind not in REPLACEABLE_KINDS:
        raise ValueError(f"{component_id} is a {comp.kind}; it is repaired, not "
                         "swapped from a reel")
    row = result.board_row(serial)
    # Keyed on the seed and the board's INDEX, not its serial: the serial
    # carries the lot number, which differs between two runs of one config.
    board_index = int(result.board_index[row]) if result.board_index is not None else row
    rng = np.random.default_rng(_seed(result.config.seed, board_index, component_id, "reels"))
    k_end = result.grid_index(168.0)
    # The board as it stands at the end of burn-in, to fit candidates into.
    fitted = {k: np.asarray([v[row, k_end]]) for k, v in result.values.items()}
    temp_socket = float(result.temps[component_id][row, k_end]) if component_id in result.temps else result.config.stress_temp_c
    history = history or {}

    out: list[Candidate] = []
    reels = list(REELS)
    for j in range(count):
        reel = reels[j % len(reels)]
        rp = REELS[reel]
        vals = {}
        for name, p in comp.params.items():
            z = rng.standard_normal()
            s = p.spread * rp["spread"]
            nominal = p.nominal * (rp["center"] if p.dist != "fixed" else 1.0)
            if p.dist == "normal":
                vals[name] = nominal * (1.0 + s * z)
            elif p.dist == "lognormal":
                vals[name] = nominal * float(np.exp(s * z))
            else:
                vals[name] = nominal
        latent = None
        if rng.random() < rp["latent_rate"]:
            models = [m for m in fault_models_for(comp.kind) if not m.intermittent]
            m = models[int(rng.integers(len(models)))]
            latent = FaultSpec(component_id, m.fault_type,
                               severity=float(rng.uniform(0.3, 0.9)),
                               start_h=float(rng.uniform(0, 72)),
                               growth_rate=float(rng.uniform(0.002, 0.02)))
        inspection = bench_measure(vals, comp.kind, rng)

        dev = 0.0
        for p, v in inspection.items():
            par = comp.params[p]
            if par.spread <= 0:
                continue
            d = (abs(np.log(v / par.nominal)) if par.dist == "lognormal"
                 else abs(v / par.nominal - 1.0))
            dev = max(dev, d / (3.0 * par.spread) * 100.0)
        trial = {k: v.copy() for k, v in fitted.items()}
        for name, v in vals.items():
            trial[f"{component_id}.{name}"] = np.asarray([v])
        if f"{component_id}.theta" in trial:
            trial[f"{component_id}.theta"] = np.asarray([comp.theta_c_per_w])
        temps, power = thermal_state(board, trial, result.config.stress_temp_c)
        t_op = float(temps[component_id][0]) if component_id in temps else temp_socket
        af = float(_af(np.asarray([t_op]), 125.0, result.config.ea_ev)[0])
        drift = rp["aging"] * af * 100.0
        if "power_w" in comp.ratings and component_id in power:
            stress = float(power[component_id][0]) / comp.ratings["power_w"] * 100.0
        elif "voltage_v" in comp.ratings:
            stress = 3.3 / comp.ratings["voltage_v"] * 100.0
        else:
            stress = 0.0
        hist = history.get(reel, rp["history_pct"])
        criteria = {"tolerance_used_pct": round(dev, 2),
                    "predicted_drift_pct": round(drift, 3),
                    "operating_temp_c": round(t_op, 2),
                    "electrical_stress_pct": round(stress, 2),
                    "historical_defect_pct": round(hist, 2)}
        penalty_in = dict(criteria)
        # Temperature is penalised above the chamber, not from absolute zero.
        penalty_in["operating_temp_c"] = max(0.0, t_op - result.config.stress_temp_c)
        penalties = {k: round(100.0 * WEIGHTS[k] * min(1.0, max(0.0, penalty_in[k]) / FULL_SCALE[k]), 2)
                     for k in WEIGHTS}
        score = round(100.0 - sum(penalties.values()), 1)
        out.append(Candidate(f"{component_id}-{reel}{j + 1}", reel, rp["label"],
                             {k: round(v, 12) for k, v in inspection.items()},
                             criteria, penalties, score, vals, latent))
    out.sort(key=lambda c: -c.ranking_score)
    return out
