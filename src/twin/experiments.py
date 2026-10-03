"""Experiment generator: sweeps, Monte Carlo campaigns, out-of-distribution suite.

    python -m src.twin.experiments --kind monte_carlo --seed 42 --runs 200
    python -m src.twin.experiments --kind esr_sweep   --seed 42 --runs 36
    python -m src.twin.experiments --kind ood         --seed 42 --runs 42

Every run is a blind benchmark (benchmark.py): simulate a lot, hand Sentinel
only the observed frame, screen it at 24, 96 and 168 h, diagnose the flagged
boards, and only then open the truth. Each row of the output is one board:
its run seed, its truth, Sentinel's prediction and the agent diagnosis - a
benchmark dataset anyone can re-score.

Reproducibility: run seeds are derived from `--seed` through a
numpy SeedSequence, so `--seed 42 --runs 1000` always produces the same 1000
lots, and run i is the same lot whether you ask for 10 runs or 1000.

Module B needs a trained forecaster to forecast from the first 24 hours. It is
fitted ONCE per experiment on separate training lots (their own seeds, never
evaluated) and then applied to every evaluation lot, so the forecast error is
out-of-fold by construction - the same lot-grouped discipline as rule 6. In the
OOD suite it is trained on in-distribution lots only; that is what makes an
OOD score honest.
"""

from __future__ import annotations

import argparse
import itertools
import json
import time
import warnings
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from src.features import PARAM_NAMES
from src.module_b import PowerLawForecaster

from src.twin import TWIN_VERSION
from src.twin.benchmark import score, sentinel_predictions
from src.twin.board import get_board
from src.twin.diagnose import board_evidence, diagnose
from src.twin.engine import NoiseConfig, SimConfig, simulate
from src.twin.faults import FaultSpec, fault_models_for

__all__ = ["ExperimentSpec", "OOD_SCENARIOS", "run_experiment", "evaluate_lot",
           "random_faults", "train_forecaster", "KINDS"]

KINDS = ("esr_sweep", "monte_carlo", "ood")

# In-distribution fault ranges. The OOD suite departs from these on purpose.
ID_SEVERITY = (0.2, 1.2)
ID_START = (0.0, 96.0)
ID_GROWTH = (0.0, 0.03)


@dataclass(frozen=True)
class ExperimentSpec:
    kind: str = "monte_carlo"
    runs: int = 20
    seed: int = 42
    boards: int = 200
    fault_rate: float = 0.06
    train_lots: int = 4
    name: str = ""
    esr_targets_ohm: tuple[float, ...] = (0.2, 0.4, 0.8, 1.2, 1.6, 2.0)
    stress_temps_c: tuple[float, ...] = (25.0, 85.0, 125.0)
    scenarios: tuple[str, ...] = ()

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        if not 1 <= self.runs <= 5000:
            raise ValueError("runs must lie in [1, 5000]")
        if not 30 <= self.boards <= 2000:
            raise ValueError("boards per lot must lie in [30, 2000] (Sentinel "
                             "needs >= 30 parts per lot for lot statistics)")
        if not 0.0 < self.fault_rate <= 0.5:
            raise ValueError("fault_rate must lie in (0, 0.5]")

    def as_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------ faults
def random_faults(rng: np.random.Generator, boards: int, rate: float, *,
                  board_id: str = "RB-1", severity=ID_SEVERITY, start=ID_START,
                  growth=ID_GROWTH, combined: bool = False,
                  only: tuple[str, str] | None = None) -> tuple[FaultSpec, ...]:
    """Pick faulty boards and give each a random catalogue fault."""
    board = get_board(board_id)
    k = max(1, int(round(rate * boards)))
    chosen = sorted(rng.choice(boards, size=k, replace=False).tolist())
    comps = [c for c in board.simulated]
    out = []
    for b in chosen:
        for _ in range(2 if combined else 1):
            if only:
                cid, ft = only
            else:
                c = comps[int(rng.integers(len(comps)))]
                models = fault_models_for(c.kind)
                cid, ft = c.component_id, models[int(rng.integers(len(models)))].fault_type
            out.append(FaultSpec(cid, ft, severity=float(rng.uniform(*severity)),
                                 start_h=float(rng.uniform(*start)),
                                 growth_rate=float(rng.uniform(*growth)), board=int(b)))
    return tuple(out)


# ------------------------------------------------------------- scenarios
def _mc_config(rng: np.random.Generator, base: SimConfig) -> SimConfig:
    """A Monte Carlo lot: every nuisance factor drawn from a stated range."""
    noise = rng.uniform(0.010, 0.025)
    return replace(
        base,
        stress_temp_c=float(rng.uniform(115, 135)),
        spread_mult=float(rng.uniform(0.8, 1.3)),
        lot_shift={"U001.iddq": float(rng.uniform(0.85, 1.2)),
                   "Q001.r_ch": float(rng.uniform(0.92, 1.08)),
                   "U001.t_int": float(rng.uniform(0.98, 1.02)),
                   "Q001.i_off": float(rng.uniform(0.8, 1.25))},
        noise=NoiseConfig(current_noise=noise, voltage_noise=noise, timing_noise=noise,
                          temperature_noise_c=float(rng.uniform(0.3, 1.0))))


OOD_SCENARIOS: dict[str, dict] = {
    "in_distribution": {},
    "higher_temperature": {"config": {"stress_temp_c": 150.0}},
    "different_lot_distribution": {"config": {
        "lot_shift": {"U001.iddq": 1.35, "Q001.r_ch": 1.08, "U001.t_int": 1.03,
                      "Q001.i_off": 1.4}, "spread_mult": 1.5}},
    "higher_sensor_noise": {"config": {"noise": NoiseConfig(
        current_noise=0.035, voltage_noise=0.035, timing_noise=0.035,
        temperature_noise_c=1.5)}},
    "unseen_fault_severity": {"severity": (0.08, 0.2)},
    "different_component_values": {"config": {"nominal_overrides": {
        "U001.t_int": 1.4e-9, "U001.iddq": 20e-6, "Q001.r_ch": 7.5, "C001.esr": 0.06}}},
    "combined_faults": {"combined": True},
}


def _run_seeds(seed: int, n: int, stream: int) -> list[int]:
    ss = np.random.SeedSequence([seed, stream])
    return [int(s) for s in ss.generate_state(n, dtype=np.uint32)]


# -------------------------------------------------------------- forecaster
def train_forecaster(seed: int, lots: int, boards: int) -> PowerLawForecaster:
    """Fit Module B on dedicated in-distribution training lots.

    Their seeds come from a separate stream (stream 1) from every evaluation
    lot (stream 2+), so no evaluated board was ever seen in training.
    """
    frames = []
    for i, s in enumerate(_run_seeds(seed, lots, stream=1)):
        rng = np.random.default_rng(s)
        cfg = SimConfig(boards=boards, seed=s, lot_id=f"TRN{i + 1:02d}",
                        faults=random_faults(rng, boards, 0.06))
        frames.append(simulate(cfg).sentinel_frame())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return PowerLawForecaster(use_gbm=True).fit(pd.concat(frames, ignore_index=True))


# ------------------------------------------------------------------- a lot
def evaluate_lot(cfg: SimConfig, forecaster: PowerLawForecaster | None,
                 *, diagnose_flagged: bool = True) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """One blind run. Returns (predictions, truth, info)."""
    result = simulate(cfg)
    frame = result.sentinel_frame()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        final = sentinel_predictions(frame, forecaster=forecaster)
        detect = pd.Series(np.nan, index=frame.index)
        for h in (24, 96):
            interim = result.sentinel_frame(upto_h=h)
            v = sentinel_predictions(interim, forecaster=forecaster)["table"]["verdict"]
            detect = detect.where(detect.notna(), np.where(v != "ACCEPT", float(h), np.nan))
        v168 = final["table"]["verdict"]
        detect = detect.where(detect.notna(), np.where(v168 != "ACCEPT", 168.0, np.nan))

    pred = final["table"].copy()
    pred["detect_h"] = detect.to_numpy()
    res = final["result"]
    for p in PARAM_NAMES:
        if p in res.forecast_point.columns:
            pred[f"forecast_{p}"] = res.forecast_point[p].to_numpy(float)
            pred[f"upper_{p}"] = res.forecast_upper[p].to_numpy(float)

    pred["suspect_component"] = None
    pred["components_ranked"] = [[] for _ in range(len(pred))]
    if diagnose_flagged:
        ev = board_evidence(frame, result.ir_rise())
        for i in pred.index[pred["verdict"] != "ACCEPT"]:
            d = diagnose(pred.at[i, "serial"], frame, ev, board_id=cfg.board_id,
                         stress_temp_c=cfg.stress_temp_c, read_temp_c=cfg.read_temp_c)
            pred.at[i, "suspect_component"] = d["suspect_component"]
            pred.at[i, "components_ranked"] = d["components_ranked"][:5]
    truth = result.truth_frame()
    info = {"lot_id": cfg.lot_id, "seed": cfg.seed, "faults": len(result.faults),
            "forecast_out_of_fold": res.forecast_out_of_fold}
    return pred, truth, info


# -------------------------------------------------------------- campaigns
def _cells(spec: ExperimentSpec) -> list[dict]:
    if spec.kind == "esr_sweep":
        esr0 = get_board().get("C001").params["esr"].nominal
        return [{"cell": f"ESR {esr:.2f} ohm @ {t:.0f} C", "esr_target_ohm": esr,
                 "stress_temp_c": t, "severity": max(0.0, (esr / esr0 - 1.0) / 19.0)}
                for esr, t in itertools.product(spec.esr_targets_ohm, spec.stress_temps_c)]
    if spec.kind == "ood":
        names = spec.scenarios or tuple(OOD_SCENARIOS)
        unknown = [n for n in names if n not in OOD_SCENARIOS]
        if unknown:
            raise ValueError(f"unknown OOD scenarios {unknown}; known: {list(OOD_SCENARIOS)}")
        return [{"cell": n} for n in names]
    return [{"cell": "monte_carlo"}]


def run_experiment(spec: ExperimentSpec,
                   progress: Callable[[int, int, str], None] | None = None) -> dict:
    """Run a whole campaign. Returns {'summary': ..., 'rows': DataFrame}."""
    t0 = time.perf_counter()
    cells = _cells(spec)
    per_cell = max(1, spec.runs // len(cells))
    total = per_cell * len(cells)
    forecaster = train_forecaster(spec.seed, spec.train_lots, spec.boards)
    seeds = _run_seeds(spec.seed, total, stream=2)

    rows, done = [], 0
    for ci, cell in enumerate(cells):
        for r in range(per_cell):
            s = seeds[done]
            rng = np.random.default_rng(s)
            lot = f"X{ci + 1:02d}R{r + 1:03d}"
            base = SimConfig(boards=spec.boards, seed=s, lot_id=lot)
            kw: dict = {}
            if spec.kind == "monte_carlo":
                cfg = _mc_config(rng, base)
            elif spec.kind == "esr_sweep":
                cfg = replace(base, stress_temp_c=cell["stress_temp_c"])
                kw = {"only": ("C001", "ESR_INCREASE"), "start": (0.0, 0.0),
                      "growth": (0.01, 0.01),
                      "severity": (cell["severity"], cell["severity"])}
            else:
                sc = OOD_SCENARIOS[cell["cell"]]
                cfg = replace(base, **sc.get("config", {}))
                if "severity" in sc:
                    kw["severity"] = sc["severity"]
                if sc.get("combined"):
                    kw["combined"] = True
            cfg = replace(cfg, faults=random_faults(rng, spec.boards, spec.fault_rate, **kw))
            pred, truth, info = evaluate_lot(cfg, forecaster)
            m = truth.merge(pred, on="serial")
            m["run"] = done + 1
            m["run_seed"] = s
            m["cell"] = cell["cell"]
            if spec.kind == "esr_sweep":
                m["esr_target_ohm"] = cell["esr_target_ohm"]
                m["stress_temp_c"] = cell["stress_temp_c"]
                res = simulate(cfg)       # deterministic: the same lot again, for truth ESR
                k = res.grid_index(168.0)
                m["true_esr_168h_ohm"] = res.values["C001.esr"][:, k]
            rows.append(m)
            done += 1
            if progress:
                progress(done, total, cell["cell"])

    data = pd.concat(rows, ignore_index=True)
    groups = {}
    for name, g in data.groupby("cell", sort=False):
        s = _score_rows(g)
        if spec.kind == "esr_sweep":
            faulty = g[g.is_faulty == 1]
            s["esr_target_ohm"] = float(g["esr_target_ohm"].iloc[0])
            s["stress_temp_c"] = float(g["stress_temp_c"].iloc[0])
            s["true_esr_168h_median_ohm"] = float(faulty["true_esr_168h_ohm"].median())
            s["mean_risk_faulty"] = float(faulty["risk_score"].mean())
        groups[str(name)] = s
    overall = _score_rows(data)

    summary = {
        "spec": spec.as_dict(), "software_version": TWIN_VERSION,
        "runs": total, "boards_scored": int(len(data)),
        "duration_s": round(time.perf_counter() - t0, 2),
        "forecaster": {"trained_on_lots": spec.train_lots, "use_gbm": True,
                       "note": "fitted on separate in-distribution lots; out-of-fold for every evaluated board"},
        "overall": overall, "by_cell": groups,
        "operating_point": ("flagged = verdict WATCH or REJECT; REJECT band sized to "
                            "the 5% PDA budget per lot; overkill budget 5% of healthy boards"),
    }
    return {"summary": summary, "rows": data}


_TRUTH_COLS = {"serial", "board", "is_faulty", "fault_components", "fault_types",
               "max_severity", "detectable"} | {f"true_{p}_168h" for p in PARAM_NAMES} | {
    f"obs_{p}_168h" for p in PARAM_NAMES} | {f"obs_{p}_0h" for p in PARAM_NAMES}


def _score_rows(rows: pd.DataFrame) -> dict:
    """Score pooled board rows. Serials repeat across runs, so key on run too."""
    keyed = rows.assign(serial=rows["serial"] + "#" + rows["run"].astype(str))
    truth = keyed[[c for c in keyed.columns if c in _TRUTH_COLS]]
    pred = keyed[["serial"] + [c for c in keyed.columns
                               if c not in _TRUTH_COLS and c not in ("cell", "run", "run_seed",
                                                                     "esr_target_ohm",
                                                                     "stress_temp_c",
                                                                     "true_esr_168h_ohm")]]
    return score(pred, truth, forecast_out_of_fold=True)


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    return str(o)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--kind", choices=KINDS, default="monte_carlo")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--boards", type=int, default=200)
    ap.add_argument("--fault-rate", type=float, default=0.06)
    ap.add_argument("--out", default=str(Path("var") / "experiments"))
    a = ap.parse_args(argv)
    spec = ExperimentSpec(kind=a.kind, runs=a.runs, seed=a.seed, boards=a.boards,
                          fault_rate=a.fault_rate)

    def prog(i, n, cell):
        print(f"\r  run {i}/{n}  {cell:<40}", end="", flush=True)

    print(f"{spec.kind}: {spec.runs} runs, seed {spec.seed}, {spec.boards} boards/lot "
          "(ACCELERATED SIMULATION TIME)")
    out = run_experiment(spec, prog)
    print()
    s = out["summary"]
    outdir = Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)
    stem = f"{spec.kind}_seed{spec.seed}_runs{s['runs']}"
    rows = out["rows"].copy()
    rows["components_ranked"] = rows["components_ranked"].apply(lambda v: ",".join(v or []))
    rows.to_csv(outdir / f"{stem}.csv", index=False)
    (outdir / f"{stem}.json").write_text(json.dumps(s, indent=2, default=_json_default))
    o = s["overall"]
    print(f"  boards {s['boards_scored']}  faulty {o['faulty_boards']}  "
          f"recall {o['recall']:.3f}  precision {o['precision']:.3f}  F2 {o['f2']:.3f}  "
          f"PR-AUC {o['pr_auc']:.3f}")
    if "localization" in o:
        print(f"  localisation top-1 {o['localization']['top1']:.3f}  "
              f"top-3 {o['localization']['top3']:.3f}")
    for name, g in s["by_cell"].items():
        if len(s["by_cell"]) > 1:
            print(f"  {name:<40} recall {g['recall']:.3f}  FPR {g['false_positive_rate']:.3f}  "
                  f"PR-AUC {g['pr_auc']:.3f}")
    print(f"  written: {outdir / (stem + '.csv')}  ({s['duration_s']} s)")


if __name__ == "__main__":
    main()
