"""NASA MOSFET Thermal Overstress Aging -> a prepared dataset.

    python -m src.realdata.nasa_mosfet --raw "E:/.../MOSFET_Thermal_Overstress_Aging_v0.zip"

The zip is read in place (never extracted, never written). Each
Test_<N>_run_<k>.mat is one aging run k of device N and holds, per sample:
    transient    500-point switching waveforms at 2 us: gateSourceVoltage,
                 drainSourceVoltage, drainCurrent
    steadyState  packageTemperature, flangeTemperature, drainCurrent, ...
    pwmTempControllerState   the thermal-overstress set points of the run

Outputs (data/real/mosfet/):
    records.csv       one row per usable switching waveform
    device_runs.csv   one row per device per run: medians of the above
    truth.csv         per device: on-resistance rise, latch-up, the label
    excluded.csv      files and records not used, and why
    metadata.json     source, rules, data dictionary

Measured / derived per waveform (formula stated, nothing smoothed):
    rds_on_ohm   median of Vds / Id over samples with the gate fully on
                 (Vgs > 80 % of its maximum and Id > 30 % of its maximum)
    id_on_a, vds_on_v, vgs_on_v   medians over those same samples
    vth_est_v    Vgs at the first rising-edge sample where Id reaches 10 % of id_on
    package_c, flange_c   steady-state temperatures nearest in time
    offstate_high   gate off (Vgs < 1 V) while Id stays above 50 % of id_on for
                 more than 10 % of the waveform. RECORDED BUT NOT USED AS A LABEL:
                 in these files the drain-current channel commonly reads 0.2-0.3 A
                 with the gate off, from the first run of healthy devices, so this
                 cannot tell a latch-up from the measurement. Checked on the data,
                 not assumed.

Temperature correction: on-resistance rises with junction temperature on its
own, so heat would look like wear. Each device's temperature coefficient is
fitted on its FIRST run (log Rds vs package temperature, before the damage
accumulates) and rds25_ohm = rds_on * exp(-alpha * (T - 25)). If the first run
spans under 5 C the population median alpha is used; which one is recorded.

Label: a device is end-of-life when its temperature-corrected on-resistance
(median per run) is >= 20 % above its first run AND stays there on every later
run - the same persistence rule as the capacitors. The threshold is a stated
precursor choice (metadata.json). Devices with a single run cannot be labelled
on drift and are marked `labelable = 0`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import re
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

__all__ = ["main", "EOL_RDS_RISE"]

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "data" / "real" / "mosfet"
EOL_RDS_RISE = 0.20
NAME = re.compile(r"Test_(\d+)_run_(\d+)\.mat$", re.I)


def _waveform(tr, steady_t: np.ndarray, steady: list[dict]) -> dict | None:
    td = tr.timeDomain
    vgs = np.asarray(td.gateSourceVoltage, dtype=float)
    vds = np.asarray(td.drainSourceVoltage, dtype=float)
    idr = np.asarray(td.drainCurrent, dtype=float)
    if vgs.size < 20 or not (vgs.size == idr.size == vds.size):
        return None       # channels of different lengths: not trimmed, excluded
    on = (vgs > 0.8 * vgs.max()) & (idr > 0.3 * idr.max()) & (idr > 1e-3)
    if on.sum() < 10:
        return None
    id_on = float(np.median(idr[on]))
    rds = float(np.median(vds[on] / idr[on]))
    rising = np.flatnonzero((np.diff(vgs, prepend=vgs[0]) > 0) & (idr >= 0.1 * id_on))
    vth = float(vgs[rising[0]]) if rising.size else np.nan
    off_high = (vgs < 1.0) & (idr > 0.5 * id_on)
    t = float(tr.timeEpoch)
    j = int(np.clip(np.searchsorted(steady_t, t), 0, len(steady) - 1)) if len(steady) else None
    s = steady[j] if j is not None else {}
    return {"t_epoch": t, "rds_on_ohm": rds, "id_on_a": id_on,
            "vds_on_v": float(np.median(vds[on])), "vgs_on_v": float(np.median(vgs[on])),
            "vth_est_v": vth, "package_c": s.get("package_c", np.nan),
            "flange_c": s.get("flange_c", np.nan),
            "offstate_high": bool(off_high.mean() > 0.10)}


def extract(zpath: Path, limit: int | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    import scipy.io
    z = zipfile.ZipFile(zpath)
    names = sorted(n for n in z.namelist() if n.lower().endswith(".mat"))
    rows, excluded = [], []
    todo = []
    for n in names:
        base = n.rsplit("/", 1)[-1]
        m = NAME.search(base)
        if not m or "error" in base.lower():
            excluded.append({"file": base, "reason": "not a Test_N_run_K file" if not m
                             else "file name says the run had a setup error"})
            continue
        todo.append((n, int(m.group(1)), int(m.group(2))))
    todo.sort(key=lambda x: (x[1], x[2]))
    if limit:
        todo = todo[:limit]
    t0 = time.perf_counter()
    for i, (n, dev, run) in enumerate(todo, 1):
        try:
            mat = scipy.io.loadmat(io.BytesIO(z.read(n)), squeeze_me=True,
                                   struct_as_record=False)["measurement"]
        except Exception as exc:  # noqa: BLE001 - recorded, never silently skipped
            excluded.append({"file": n.rsplit("/", 1)[-1], "reason": f"unreadable: {type(exc).__name__}"})
            continue
        steady = []
        for ss in np.atleast_1d(mat.steadyState):
            try:
                steady.append({"t": float(ss.timeEpoch),
                               "package_c": float(ss.timeDomain.packageTemperature),
                               "flange_c": float(ss.timeDomain.flangeTemperature)})
            except (AttributeError, TypeError, ValueError):
                continue
        steady.sort(key=lambda d: d["t"])
        steady_t = np.array([d["t"] for d in steady])
        pwm = np.atleast_1d(mat.pwmTempControllerState)
        set_hi = float(getattr(pwm[0], "highTemp", np.nan)) if len(pwm) else np.nan
        bad = 0
        for tr in np.atleast_1d(mat.transient):
            try:
                w = _waveform(tr, steady_t, steady)
            except (AttributeError, TypeError, ValueError, IndexError):
                w = None
            if w is None:
                bad += 1
                continue
            rows.append({"device": f"T{dev:02d}", "test": dev, "run": run,
                         "set_high_temp_c": set_hi, **w, "measurement_source": "DATASET"})
        if bad:
            excluded.append({"file": n.rsplit("/", 1)[-1],
                             "reason": f"{bad} waveform(s) unusable: gate never fully on, "
                                       "or channels of different lengths"})
        el = time.perf_counter() - t0
        print(f"  [{i}/{len(todo)}] {n.rsplit('/', 1)[-1]}: {len(rows)} waveforms so far "
              f"({el:.0f} s)", flush=True)
    return pd.DataFrame(rows), pd.DataFrame(excluded)


def prepare(rec: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    rec = rec.sort_values(["device", "t_epoch"]).reset_index(drop=True)
    rec["hours"] = (rec["t_epoch"] - rec.groupby("device")["t_epoch"].transform("min")) * 24.0

    # ---- temperature coefficient per device, from its first run
    alphas, source = {}, {}
    for d, g in rec.groupby("device"):
        first = g[(g.run == g.run.min()) & g.package_c.notna() & (g.rds_on_ohm > 0)]
        if len(first) >= 20 and first.package_c.std() >= 5 / 4:   # >= ~5 C span
            a = np.polyfit(first.package_c, np.log(first.rds_on_ohm), 1)[0]
            if 0 < a < 0.03:
                alphas[d], source[d] = float(a), "own first run"
    pop = float(np.median(list(alphas.values()))) if alphas else 0.006
    for d in rec.device.unique():
        if d not in alphas:
            alphas[d], source[d] = pop, "population median"
    rec["alpha_per_c"] = rec.device.map(alphas)
    rec["rds25_ohm"] = rec.rds_on_ohm * np.exp(-rec.alpha_per_c * (rec.package_c.fillna(25) - 25))

    runs = (rec.groupby(["device", "run"])
               .agg(start_hours=("hours", "min"), end_hours=("hours", "max"),
                    waveforms=("rds_on_ohm", "size"),
                    rds_on_ohm=("rds_on_ohm", "median"), rds25_ohm=("rds25_ohm", "median"),
                    vth_est_v=("vth_est_v", "median"), id_on_a=("id_on_a", "median"),
                    package_c=("package_c", "median"), flange_c=("flange_c", "median"),
                    set_high_temp_c=("set_high_temp_c", "first"),
                    offstate_high_share=("offstate_high", "mean"))
               .reset_index())

    truth = []
    for d, g in runs.groupby("device"):
        g = g.sort_values("run")
        base = float(g.rds25_ohm.iloc[0])
        rise = (g.rds25_ohm / base - 1).to_numpy()
        # Persistent crossing: the first run from which the rise holds to the end.
        tail_all = np.logical_and.accumulate((rise >= EOL_RDS_RISE)[::-1])[::-1]
        labelable = len(g) >= 2
        eol = bool(labelable and tail_all.any())
        truth.append({"device": d, "runs": int(len(g)), "hours": round(float(g.end_hours.max()), 2),
                      "labelable": int(labelable),
                      "rds25_first_ohm": round(base, 5),
                      "rds25_last_ohm": round(float(g.rds25_ohm.iloc[-1]), 5),
                      "rds25_rise_pct": round(100 * float(rise[-1]), 2),
                      "max_rise_pct": round(100 * float(rise.max()), 2),
                      "eol": int(eol),
                      "eol_run": int(g.run.to_numpy()[tail_all.argmax()]) if eol else None,
                      "eol_hours": round(float(g.start_hours.to_numpy()[tail_all.argmax()]), 2) if eol else None,
                      "alpha_source": source[d]})
    return rec, runs, pd.DataFrame(truth), {"population_alpha_per_c": pop, "alpha_by_device": alphas}


DICTIONARY = {
    "device": "T<N> from Test_<N>", "run": "aging run k from run_<k>",
    "t_epoch": "MATLAB datenum of the waveform", "hours": "hours since the device's first waveform",
    "rds_on_ohm": "median Vds/Id with the gate fully on (Vgs > 80 % max, Id > 30 % max)",
    "rds25_ohm": "rds_on corrected to 25 C: rds_on * exp(-alpha * (package_c - 25))",
    "alpha_per_c": "temperature coefficient of log Rds, fitted on the device's first run",
    "vth_est_v": "Vgs at the first rising-edge sample where Id reaches 10 % of id_on",
    "id_on_a": "median drain current while on", "vds_on_v": "median Vds while on",
    "vgs_on_v": "median Vgs while on", "package_c": "package temperature, nearest steady-state sample",
    "flange_c": "flange temperature, nearest steady-state sample",
    "set_high_temp_c": "thermal-overstress upper set point of the run",
    "offstate_high": "gate off (< 1 V) while Id > 50 % of id_on for over 10 % of the waveform; "
                     "recorded, NOT a label (the current channel is not near zero when off)",
    "measurement_source": "DATASET: measured by NASA; nothing here is simulated",
}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--raw", default=os.environ.get("SENTINEL_NASA_MOSFET_ZIP", ""),
                    help="path to MOSFET_Thermal_Overstress_Aging_v0.zip")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--limit", type=int, default=None, help="only the first N files (a quick look)")
    ap.add_argument("--reuse-records", action="store_true",
                    help="re-label from an existing records.csv without re-reading the zip")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.reuse_records and (out / "records.csv").exists():
        rec = pd.read_csv(out / "records.csv")
        rec = rec.rename(columns={"latch_up": "offstate_high"})
        rec = rec[[c for c in rec.columns if c not in ("hours", "alpha_per_c", "rds25_ohm")]]
        excluded = pd.read_csv(out / "excluded.csv")
        print(f"reusing {len(rec):,} extracted waveforms (zip not re-read)")
    else:
        if not a.raw:
            raise SystemExit("give --raw <zip> or set SENTINEL_NASA_MOSFET_ZIP")
        print(f"reading {a.raw} in place (read-only)")
        rec, excluded = extract(Path(a.raw), a.limit)
    if rec.empty:
        raise SystemExit("no usable waveforms")
    rec, runs, truth, fit = prepare(rec)
    rec.to_csv(out / "records.csv", index=False)
    runs.to_csv(out / "device_runs.csv", index=False)
    truth.to_csv(out / "truth.csv", index=False)
    excluded.to_csv(out / "excluded.csv", index=False)
    meta = {"source": "NASA Prognostics Center of Excellence - MOSFET Thermal Overstress Aging",
            "prepared_by": "src/realdata/nasa_mosfet.py",
            "rule": "reshaped, never re-measured: every value is measured or derived by the stated formula",
            "devices": int(rec.device.nunique()), "waveforms": int(len(rec)),
            "excluded": excluded.to_dict("records"),
            "eol_rule": {"rds25_rise": EOL_RDS_RISE, "persistence": "must hold on every later run",
                         "latch_up": "not used: the off-state current channel reads 0.2-0.3 A on healthy devices"},
            "temperature_fit": fit, "dictionary": DICTIONARY,
            "prepared_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    (out / "metadata.json").write_text(json.dumps(meta, indent=2, default=float))
    print(f"\n{meta['devices']} devices, {meta['waveforms']} waveforms -> {out}")
    print(truth.to_string(index=False))


if __name__ == "__main__":
    main()
