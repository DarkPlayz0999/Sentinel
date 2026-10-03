"""SENTINEL's methods on the prepared real data, scored by src/evaluate.py.

    python -m src.realdata.evaluate capacitors
    python -m src.realdata.evaluate mosfet

The question is the early-warning one: at an early read, among parts that have
NOT failed yet, which will fail later? Parts already past end-of-life at that
read are excluded from the scoring - any static limit catches them, and
counting them would flatter the method.

Scores use SENTINEL's building blocks, not new statistics:
    robust z   src.features.robust_z (median, 1.4826 * MAD) of each part's drift
               from its own baseline, against the population (same part number)
    pooled     sqrt(sum of squared positive z) - the L3 idea: evidence pooled
               across parameters, one-sided because higher drift is worse
    forecast   src.module_b.physics_forecast with the exponent fitted by
               fit_global_exponent on the OTHER stress lots (grouped hold-out)

Metrics: recall, precision, PR-AUC, confusion counts - via src/evaluate.py.
Plain accuracy is not reported (rule 5). With a handful of failures every
number carries a wide uncertainty; the report says how many parts each rests on.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from src.evaluate import pr_auc, screening_metrics
from src.features import robust_z
from src.module_b import fit_global_exponent, physics_forecast

REPO = Path(__file__).resolve().parents[2]
REAL = REPO / "data" / "real"


def _pooled(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    z = pd.DataFrame({c: robust_z(df[c]) for c in cols}).clip(lower=0).fillna(0.0)
    return np.sqrt((z ** 2).sum(axis=1))


def _score(y, flag, score) -> dict:
    y, flag = np.asarray(y, int), np.asarray(flag, int)
    m = screening_metrics(y, flag, beta=2.0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ap = pr_auc(y, score) if 0 < y.sum() < len(y) else float("nan")
    return {"parts": int(len(y)), "failing_later": int(y.sum()), "recall": m["recall"],
            "precision": m["precision"], "f2": m["f_beta"], "pr_auc": ap,
            "tp": m["tp"], "fp": m["fp"], "fn": m["fn"], "tn": m["tn"]}


# ------------------------------------------------------------- capacitors
def capacitors(z_flag: float = 3.0) -> dict:
    d = REAL / "capacitors"
    long = pd.read_csv(d / "long.csv")
    truth = pd.read_csv(d / "truth.csv").set_index("serial")
    base = long[long.pre_stress].groupby("serial")[["c120_uf", "esr_mohm", "tan_delta120", "z120_ohm"]].median()
    end_day = int(long.day.max())

    def at(day: int) -> pd.DataFrame:
        rows = []
        for s, g in long[long.day <= day].groupby("serial"):
            r = g.iloc[(g.day - day).abs().argmin()]
            rows.append({"serial": s, "lot": r.lot, "day": int(r.day), "c120_uf": r.c120_uf,
                         "esr_mohm": r.esr_mohm, "tan_delta120": r.tan_delta120, "z120_ohm": r.z120_ohm})
        return pd.DataFrame(rows).set_index("serial")

    out = {"dataset": "NASA capacitor electrical stress", "end_day": end_day,
           "flag_rule": f"pooled robust z >= {z_flag}", "by_read_day": {}}
    for day in (14, 35, 49):
        now = at(day)
        feats = pd.DataFrame({
            "c_loss": -np.log(now.c120_uf / base.c120_uf),           # higher = worse
            "esr_rise": np.log(now.esr_mohm / base.esr_mohm),
            "tand_rise": np.log(now.tan_delta120 / base.tan_delta120),
            "z_rise": np.log(now.z120_ohm / base.z120_ohm)}).loc[now.index]
        failed_by_now = truth.eol_day.notna() & (truth.eol_day <= day)
        keep = ~failed_by_now.reindex(now.index).fillna(False).to_numpy()
        y = truth.eol.reindex(now.index).to_numpy()[keep]
        pooled = _pooled(feats, list(feats.columns))
        pooled_lot = feats.groupby(now.lot).transform(robust_z).clip(lower=0).fillna(0)
        pooled_lot = np.sqrt((pooled_lot ** 2).sum(axis=1))

        # Module B idea: forecast the end-of-test capacitance from pre-stress and this read,
        # exponent fitted on the other two stress lots only.
        pred = pd.Series(np.nan, index=now.index)
        end = at(end_day)
        for lot in now.lot.unique():
            tr = now.lot != lot
            v0, ve, vend = base.c120_uf.loc[now.index], now.c120_uf, end.c120_uf.loc[now.index]
            n = fit_global_exponent(v0[tr], ve[tr], vend[tr]) if tr.any() else 1.0
            # physics_forecast extrapolates by (168/24); rescale to this read's fraction of the test
            frac = max(day, 1) / end_day
            a = (ve[~tr] / v0[~tr] - 1.0) / frac ** n
            pred[~tr] = v0[~tr] * (1.0 + a)
        pred_loss = 1 - pred / base.c120_uf.loc[now.index]

        k = keep
        out["by_read_day"][str(day)] = {
            "excluded_already_failed": sorted(now.index[~k].tolist()),
            "pooled_population": _score(y, (pooled.to_numpy()[k] >= z_flag), pooled.to_numpy()[k]),
            "pooled_within_stress_lot": _score(y, (pooled_lot.to_numpy()[k] >= z_flag), pooled_lot.to_numpy()[k]),
            "forecast_end_c_loss": _score(y, (pred_loss.to_numpy()[k] >= 0.20), pred_loss.to_numpy()[k]),
            "ranking": [{"serial": s, "pooled_z": round(float(pooled[s]), 2),
                         "forecast_end_c_loss_pct": round(100 * float(pred_loss[s]), 1),
                         "fails_later": int(truth.eol.get(s, 0)),
                         "eol_day": None if pd.isna(truth.eol_day.get(s)) else int(truth.eol_day[s])}
                        for s in pooled[k].sort_values(ascending=False).index[:6]],
        }
    return out


# ------------------------------------------------------------------ mosfet
def mosfet(z_flag: float = 3.0, early_runs: int = 1) -> dict:
    d = REAL / "mosfet"
    runs = pd.read_csv(d / "device_runs.csv")
    truth = pd.read_csv(d / "truth.csv").set_index("device")
    # Early read = the end of run `early_runs` (1 = the first run's own drift,
    # its last waveforms against its first). Devices need a later run to have
    # a "later" at all.
    rec = pd.read_csv(d / "records.csv", usecols=["device", "run", "hours", "rds25_ohm", "vth_est_v"])
    rows = []
    for dev, g in runs.sort_values("run").groupby("device"):
        if len(g) <= early_runs:
            continue
        r1 = rec[(rec.device == dev) & (rec.run <= early_runs)].sort_values("hours")
        k = max(5, len(r1) // 10)
        head, tail = r1.head(k), r1.tail(k)
        b = pd.Series({"rds25_ohm": head.rds25_ohm.median(), "vth_est_v": head.vth_est_v.median()})
        e = pd.Series({"rds25_ohm": tail.rds25_ohm.median(), "vth_est_v": tail.vth_est_v.median(),
                       "end_hours": float(r1.hours.max())})
        rows.append({"device": dev,
                     "rds_rise": np.log(e.rds25_ohm / b.rds25_ohm),
                     "vth_shift": (e.vth_est_v - b.vth_est_v) if pd.notna(e.vth_est_v) and pd.notna(b.vth_est_v) else np.nan,
                     "hours_at_read": float(e.end_hours)})
    f = pd.DataFrame(rows).set_index("device")
    if f.empty:
        return {"dataset": "NASA MOSFET thermal overstress", "note": "no device has enough runs"}
    eol_h = truth.eol_hours.reindex(f.index)
    already = eol_h.notna() & (eol_h <= f.hours_at_read)
    keep = ~already.to_numpy()
    y = truth.eol.reindex(f.index).fillna(0).astype(int).to_numpy()[keep]
    pooled = _pooled(f, [c for c in ("rds_rise", "vth_shift") if f[c].notna().any()])
    return {"dataset": "NASA MOSFET thermal overstress",
            "early_read": f"end of run {early_runs}: its last 10 % of waveforms against its first 10 %",
            "devices_scored": int(keep.sum()),
            "excluded_already_failed": sorted(f.index[~keep].tolist()),
            "pooled_population": _score(y, (pooled.to_numpy()[keep] >= z_flag), pooled.to_numpy()[keep]),
            "ranking": [{"device": s, "pooled_z": round(float(pooled[s]), 2),
                         "rds_rise_pct": round(100 * float(np.expm1(f.rds_rise[s])), 1),
                         "fails_later": int(truth.eol.get(s, 0))}
                        for s in pooled[keep].sort_values(ascending=False).index[:8]]}


def main(argv: list[str] | None = None) -> None:
    which = (argv or sys.argv[1:] or ["capacitors"])[0]
    res = capacitors() if which.startswith("cap") else mosfet()
    out = REAL / ("capacitors" if which.startswith("cap") else "mosfet") / "evaluation.json"
    out.write_text(json.dumps(res, indent=2, default=float))
    print(json.dumps(res, indent=2, default=float))
    print(f"\nwritten: {out}")


if __name__ == "__main__":
    main()
