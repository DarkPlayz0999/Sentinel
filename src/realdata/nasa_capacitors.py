"""NASA Capacitor Electrical Stress (ES10 / ES12 / ES14) -> a prepared dataset.

    python -m src.realdata.nasa_capacitors --raw "E:/.../12. Capacitor Electrical Stress"

Raw layout (MATLAB v7.3 / HDF5): ES<V>/EIS_Data/ES<V>C<n>/EIS_Measurement/Data
holds one cell per EIS read; each cell holds several frequency sweeps; each
sweep is a matrix whose rows are freq/Hz (0), Re(Z)/ohm (1), -Im(Z)/ohm (2),
|Z|/ohm (3), Phase(Z)/deg (4), ..., Cs/uF (8). Zero-frequency rows are padding.
ES<V>/EIS_Data/EIS_Reference_Table row 0 holds the date of each read.

Outputs (data/real/capacitors/):
    long.csv          one row per capacitor per EIS read, every parameter
    wide.csv          one row per capacitor at chosen read days (Sentinel-style)
    truth.csv         end-of-life labels, kept apart from the measurements
    excluded.csv      reads that could not be used, and why
    metadata.json     where it came from, the rules applied, the data dictionary

Derived quantities (all from measured values, formula stated):
    esr_mohm          min Re(Z) over f >= 1 kHz            (the ESR plateau)
    esr120_mohm       Re(Z) at the sweep point nearest 120 Hz
    c120_uf, c1k_uf   Cs nearest 120 Hz / 1 kHz
    z120_ohm          |Z| nearest 120 Hz
    phase120_deg      Phase(Z) nearest 120 Hz
    tan_delta120      Re(Z) / -Im(Z) at 120 Hz  (dissipation factor)
Each is the median over the sweeps of that read (repeat sweeps of one read).

Stress transient: reads on days 0-1 are the pre-stress baseline. From day 2
every stressed capacitor jumps - ESR roughly doubles and capacitance drops
12-15 % - then ESR relaxes for the rest of the test while capacitance partly
recovers (ES10/ES12) or keeps falling (ES14). The batch-median ESR peaks in
weeks 1-3 and is back on its slow trend by week 5, so `conditioning` is True
for reads before CONDITIONING_DAYS = 35. One rule for every capacitor, chosen
from the raw curves (the weekly medians are stored in metadata.json) before
any screening result was looked at. It is flagged, never removed.

End-of-life (industry criterion for aluminium electrolytics, applied to the
measured values): capacitance at 120 Hz down >= 20 % from the pre-stress
baseline, OR ESR up >= 100 %, AND it must PERSIST: `eol_day` is the first read
after which that criterion, on its own, holds on every later read. Without persistence the
stress transient alone would mark nearly every capacitor end-of-life by day 2
and then "recover" it - a label nobody could act on.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

__all__ = ["extract", "prepare", "main", "CONDITIONING_DAYS"]

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "data" / "real" / "capacitors"
LOTS = ("ES10", "ES12", "ES14")
CONDITIONING_DAYS = 35
EOL_C_LOSS = 0.20
EOL_ESR_RISE = 1.00
WIDE_DAYS = (0, 2, 14, 35, 70, 140, 226)    # read days carried into wide.csv


def _at(freq: np.ndarray, target: float) -> int:
    return int(np.argmin(np.abs(freq - target)))


def _sweep_params(m: np.ndarray) -> dict | None:
    """Parameters of one frequency sweep, or None if it is padding."""
    if m.ndim != 2 or m.shape[0] < 9:
        return None
    freq = m[0]
    ok = freq > 0
    if ok.sum() < 5:
        return None
    f, rez, mimz, zmag, ph, cs = (m[i][ok] for i in (0, 1, 2, 3, 4, 8))
    hi = f >= 1000
    i120, i1k = _at(f, 120.0), _at(f, 1000.0)
    return {
        "esr_mohm": 1000 * float(np.min(rez[hi])) if hi.any() else np.nan,
        "esr120_mohm": 1000 * float(rez[i120]),
        "c120_uf": float(cs[i120]),
        "c1k_uf": float(cs[i1k]),
        "z120_ohm": float(zmag[i120]),
        "phase120_deg": float(ph[i120]),
        "tan_delta120": float(rez[i120] / mimz[i120]) if mimz[i120] > 0 else np.nan,
        "f120_actual_hz": float(f[i120]),
    }


def extract(raw: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read every EIS read of every capacitor. Returns (long, excluded)."""
    import h5py
    rows, excluded = [], []
    for lot in LOTS:
        path = raw / f"{lot}.mat"
        with h5py.File(path, "r") as f:
            table = f[f"{lot}/EIS_Data/EIS_Reference_Table"]
            dates = []
            for k in range(table.shape[1]):
                s = "".join(chr(c) for c in np.array(f[table[0, k]]).ravel(order="F")).strip()
                try:
                    dates.append(dt.datetime.strptime(s, "%m/%d/%Y"))
                except ValueError:
                    dates.append(None)
            d0 = next(d for d in dates if d)
            caps = sorted(k for k in f[f"{lot}/EIS_Data"].keys() if k.startswith(lot + "C"))
            for cap in caps:
                g = f[f"{lot}/EIS_Data/{cap}/EIS_Measurement"]
                for k in range(g["Data"].shape[0]):
                    sweeps = []
                    for r in np.array(f[g["Data"][k, 0]]).ravel():
                        p = _sweep_params(np.array(f[r]))
                        if p:
                            sweeps.append(p)
                    day = (dates[k] - d0).days if k < len(dates) and dates[k] else None
                    if not sweeps or day is None:
                        excluded.append({"serial": cap, "lot": lot, "read_index": k,
                                         "reason": "no usable sweep" if not sweeps else "no date"})
                        continue
                    med = {key: float(np.nanmedian([s[key] for s in sweeps])) for key in sweeps[0]}
                    rows.append({"serial": cap, "lot": lot, "stress_v": int(lot[2:]),
                                 "read_index": k, "day": int(day), "n_sweeps": len(sweeps),
                                 **med, "measurement_source": "DATASET"})
        print(f"  {lot}: {len(caps)} capacitors", flush=True)
    return pd.DataFrame(rows), pd.DataFrame(excluded)


def prepare(long: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Add conditioning flag and labels; build wide.csv and truth.csv."""
    long = long.sort_values(["serial", "day", "read_index"]).reset_index(drop=True)
    long["pre_stress"] = long["day"] <= 1
    long["conditioning"] = long["day"] < CONDITIONING_DAYS
    # Baseline = median of the pre-stress reads (days 0-1) of each capacitor.
    first = long[long.pre_stress].groupby("serial")[["c120_uf", "esr_mohm"]].median()
    long["c_loss_frac"] = 1 - long["c120_uf"] / long["serial"].map(first["c120_uf"])
    long["esr_rise_frac"] = long["esr_mohm"] / long["serial"].map(first["esr_mohm"]) - 1
    long["eol_now"] = (long["c_loss_frac"] >= EOL_C_LOSS) | (long["esr_rise_frac"] >= EOL_ESR_RISE)

    def persistent_from(g: pd.DataFrame, mask: np.ndarray):
        """First read day from which `mask` holds on every later read, else None."""
        tail_all = np.logical_and.accumulate(mask[::-1])[::-1]
        return int(g.day.to_numpy()[tail_all.argmax()]) if tail_all.any() else None

    truth = []
    for s, g in long.groupby("serial"):
        # Each criterion must persist ON ITS OWN, so a transient in one cannot
        # be stitched to a later crossing of the other.
        by_c = persistent_from(g, (g.c_loss_frac >= EOL_C_LOSS).to_numpy())
        by_esr = persistent_from(g, (g.esr_rise_frac >= EOL_ESR_RISE).to_numpy())
        days = [d for d in (by_c, by_esr) if d is not None]
        last = g.iloc[-1]
        truth.append({"serial": s, "lot": g.lot.iloc[0], "stress_v": int(g.stress_v.iloc[0]),
                      "eol": int(bool(days)),
                      "eol_day": min(days) if days else None,
                      "eol_by": ("capacitance" if by_c is not None and (by_esr is None or by_c <= by_esr)
                                 else "esr" if by_esr is not None else None),
                      "last_day": int(last.day),
                      "c_loss_at_end_pct": round(100 * float(last.c_loss_frac), 2),
                      "esr_rise_at_end_pct": round(100 * float(last.esr_rise_frac), 2)})
    truth = pd.DataFrame(truth)

    params = ["esr_mohm", "esr120_mohm", "c120_uf", "c1k_uf", "z120_ohm", "phase120_deg",
              "tan_delta120"]
    wide_rows = []
    for s, g in long.groupby("serial"):
        row = {"serial": s, "lot": g.lot.iloc[0], "stress_v": int(g.stress_v.iloc[0])}
        for d in WIDE_DAYS:
            r = g.iloc[(g.day - d).abs().argmin()]
            for p in params:
                row[f"{p}_{d}d"] = r[p]
            row[f"actual_day_{d}d"] = int(r.day)
        wide_rows.append(row)
    return long, pd.DataFrame(wide_rows), truth


DICTIONARY = {
    "serial": "capacitor ID from the raw file, e.g. ES14C8",
    "lot": "stress group = raw file (ES10 / ES12 / ES14)",
    "stress_v": "electrical stress voltage in volts, from the file name",
    "read_index": "position of the EIS read in the raw file",
    "day": "days since the first EIS read of that file (dates have day resolution)",
    "n_sweeps": "frequency sweeps in this read (the median over them is reported)",
    "esr_mohm": "ESR, milliohm: minimum Re(Z) over frequencies >= 1 kHz",
    "esr120_mohm": "Re(Z) at the sweep point nearest 120 Hz, milliohm",
    "c120_uf": "series capacitance Cs nearest 120 Hz, microfarad",
    "c1k_uf": "series capacitance Cs nearest 1 kHz, microfarad",
    "z120_ohm": "|Z| nearest 120 Hz, ohm",
    "phase120_deg": "phase of Z nearest 120 Hz, degrees",
    "tan_delta120": "dissipation factor Re(Z) / -Im(Z) at 120 Hz",
    "f120_actual_hz": "the sweep frequency actually used for the 120 Hz values",
    "pre_stress": "True for reads on days 0-1, before the stress transient",
    "conditioning": f"True for reads before day {CONDITIONING_DAYS} (the stress transient)",
    "c_loss_frac": "1 - c120 / median pre-stress c120 of that capacitor",
    "esr_rise_frac": "esr / median pre-stress esr of that capacitor - 1",
    "eol_now": f"c_loss_frac >= {EOL_C_LOSS} or esr_rise_frac >= {EOL_ESR_RISE} on this read",
    "measurement_source": "DATASET: measured by NASA; nothing here is simulated",
}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--raw", default=os.environ.get("SENTINEL_NASA_CAP_DIR", ""),
                    help="folder holding ES10.mat, ES12.mat, ES14.mat")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--reuse-long", action="store_true",
                    help="re-label from an existing long.csv without re-reading the raw files")
    a = ap.parse_args(argv)
    if not a.raw and not a.reuse_long:
        raise SystemExit("give --raw <folder with ES10.mat ...> or set SENTINEL_NASA_CAP_DIR")
    raw, out = Path(a.raw), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"reading {raw} (read-only)")
    if a.reuse_long and (out / "long.csv").exists():
        cols = pd.read_csv(out / "long.csv")
        long = cols[[c for c in cols.columns if c not in (
            "pre_stress", "conditioning", "c_loss_frac", "esr_rise_frac", "eol_now")]]
        excluded = pd.read_csv(out / "excluded.csv") if (out / "excluded.csv").stat().st_size > 2 else pd.DataFrame()
        print("reusing the extracted reads in long.csv (raw files not re-read)")
    else:
        long, excluded = extract(raw)
    long, wide, truth = prepare(long)
    long.to_csv(out / "long.csv", index=False)
    wide.to_csv(out / "wide.csv", index=False)
    truth.to_csv(out / "truth.csv", index=False)
    excluded.to_csv(out / "excluded.csv", index=False)
    meta = {"source": "NASA Prognostics Center of Excellence - Capacitor Electrical Stress",
            "raw_files": [f"{l}.mat" for l in LOTS], "prepared_by": "src/realdata/nasa_capacitors.py",
            "rule": "reshaped, never re-measured: every value is measured or derived by the stated formula",
            "capacitors": int(long.serial.nunique()), "reads": int(len(long)),
            "excluded_reads": int(len(excluded)), "conditioning_days": CONDITIONING_DAYS,
            "eol_rule": {"capacitance_loss": EOL_C_LOSS, "esr_rise": EOL_ESR_RISE,
                         "baseline": "median of pre-stress reads (days 0-1)",
                         "persistence": "must hold on every read to the end of the test"},
            "weekly_batch_medians": {
                f"{lot}": {str(int(w)): {"esr_mohm": round(float(v.esr_mohm), 1),
                                         "c120_uf": round(float(v.c120_uf), 1)}
                           for w, v in grp.groupby((grp.day // 7) * 7)[["esr_mohm", "c120_uf"]].median().iterrows()}
                for lot, grp in long.groupby("lot")},
            "wide_days": list(WIDE_DAYS), "dictionary": DICTIONARY,
            "prepared_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    (out / "metadata.json").write_text(json.dumps(meta, indent=2))
    print(f"\n{meta['capacitors']} capacitors, {meta['reads']} reads, "
          f"{meta['excluded_reads']} excluded -> {out}")
    print(truth.to_string(index=False))


if __name__ == "__main__":
    main()
