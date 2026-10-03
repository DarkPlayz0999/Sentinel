"""The prepared NASA datasets, served to the web console.

    GET /v1/realdata              which datasets are prepared
    GET /v1/realdata/capacitors   curves, labels, evaluation
    GET /v1/realdata/mosfet       per-run medians, labels, evaluation

Read-only views of what src/realdata/*.py wrote to data/real/. Nothing is
computed here beyond grouping measured and already-derived values for charts:
every figure traces back to a prepared file and, through the prep script, to
the raw NASA file. When a dataset has not been prepared the endpoint says how
to prepare it instead of returning an empty page.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import APIRouter

from backend.app.core.config import REPO_ROOT
from backend.app.core.exceptions import NotFoundError
from backend.app.schemas.common import ERROR_RESPONSES

router = APIRouter(prefix="/v1/realdata", tags=["realdata"], responses=ERROR_RESPONSES)


def _root() -> Path:
    return Path(os.environ.get("SENTINEL_REAL_DATA_DIR", REPO_ROOT / "data" / "real"))


def _read_json(p: Path) -> dict | None:
    return json.loads(p.read_text()) if p.exists() else None


def _records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.replace({np.nan: None}).to_json(orient="records"))


HOW = {
    "capacitors": 'python -m src.realdata.nasa_capacitors --raw "<folder with ES10.mat ES12.mat ES14.mat>" '
                  "&& python -m src.realdata.evaluate capacitors",
    "mosfet": 'python -m src.realdata.nasa_mosfet --raw "<MOSFET_Thermal_Overstress_Aging_v0.zip>" '
              "&& python -m src.realdata.evaluate mosfet",
}


@router.get("", summary="Which real datasets are prepared")
def available():
    out = {}
    for name in ("capacitors", "mosfet"):
        meta = _read_json(_root() / name / "metadata.json")
        out[name] = ({"prepared": True, "source": meta.get("source"),
                      "prepared_utc": meta.get("prepared_utc"),
                      "evaluated": (_root() / name / "evaluation.json").exists()}
                     if meta else {"prepared": False, "how": HOW[name]})
    return out


@router.get("/capacitors", summary="Prepared NASA capacitor data: curves, labels, evaluation")
def capacitors():
    d = _root() / "capacitors"
    if not (d / "long.csv").exists():
        raise NotFoundError(f"Capacitor data not prepared. Run: {HOW['capacitors']}")
    long = pd.read_csv(d / "long.csv")
    meta = _read_json(d / "metadata.json") or {}
    series = {}
    for s, g in long.sort_values("day").groupby("serial"):
        series[s] = {
            "lot": g.lot.iloc[0], "stress_v": int(g.stress_v.iloc[0]),
            "day": g.day.tolist(),
            "c_loss_pct": (100 * g.c_loss_frac).round(3).tolist(),
            "esr_rise_pct": (100 * g.esr_rise_frac).round(3).tolist(),
            "tan_delta120": g.tan_delta120.round(5).tolist(),
        }
    return {"metadata": {k: v for k, v in meta.items() if k != "weekly_batch_medians"},
            "weekly_batch_medians": meta.get("weekly_batch_medians"),
            "truth": _records(pd.read_csv(d / "truth.csv")),
            "series": series,
            "evaluation": _read_json(d / "evaluation.json"),
            "excluded": _records(pd.read_csv(d / "excluded.csv")) if (d / "excluded.csv").stat().st_size > 2 else []}


@router.get("/mosfet", summary="Prepared NASA MOSFET data: per-run medians, labels, evaluation")
def mosfet():
    d = _root() / "mosfet"
    if not (d / "device_runs.csv").exists():
        raise NotFoundError(f"MOSFET data not prepared. Run: {HOW['mosfet']}")
    runs = pd.read_csv(d / "device_runs.csv")
    meta = _read_json(d / "metadata.json") or {}
    base = runs.sort_values("run").groupby("device").rds25_ohm.first()
    runs["rds25_rise_pct"] = 100 * (runs.rds25_ohm / runs.device.map(base) - 1)
    return {"metadata": {k: v for k, v in meta.items() if k != "excluded"},
            "excluded_files": len(meta.get("excluded", [])),
            "truth": _records(pd.read_csv(d / "truth.csv")),
            "runs": _records(runs.round(6)),
            "evaluation": _read_json(d / "evaluation.json")}
