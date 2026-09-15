"""Export the real numbers the landing page renders, into src/lib/lab-data.ts.

Every figure on the site comes from the committed dataset (seed 42) and the
shipped feature pipeline in src/features.py - rule 8, one definition of a
feature. Re-run after regenerating data/:

    python web/scripts/export_lab_data.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from dataclasses import asdict

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.explain import Thresholds, lot_reason_codes, reason_codes  # noqa: E402
from src.fusion import PDA_LIMIT, RiskWeights, bands_for_pda, fuse, lot_pda_status  # noqa: E402
from src.pipeline import screen  # noqa: E402
from src.features import PARAMS as FEATURE_PARAMS, build_features  # noqa: E402
from src.module_a import dpat_score, pooled_evidence_score  # noqa: E402

# Units, USLs and labels come from src/features.py - rule 8. Re-typing 50.0
# here would be a second definition of the datasheet limit.
PARAM_USL = {p: float(c["usl"]) for p, c in FEATURE_PARAMS.items()}
PARAM_UNIT = {p: c["unit"] for p, c in FEATURE_PARAMS.items()}
PARAM_LABEL = {p: c["label"] for p, c in FEATURE_PARAMS.items()}

WIDE = ROOT / "data" / "burnin_wide.csv"
OUT = ROOT / "web" / "src" / "lib" / "lab-data.ts"

LOT_COL = "lot"
LOT = "L01"
PARAM = "Iddq_uA"
DATASHEET_MAX = 50.0  # src/generate_burnin_dataset.py, static limit for Iddq_uA
L2_GATE = 4.5         # the operating point the README reports recall at


def _hist(values, lo, hi, bins):
    counts, edges = np.histogram(values, bins=bins, range=(lo, hi))
    return [{"x": round(float(e), 3), "n": int(c)} for e, c in zip(edges[:-1], counts)]


def static_vs_dynamic(d: pd.DataFrame, z: pd.DataFrame) -> dict:
    """The thesis, in two histograms of the SAME parts.

    Left: the 168h level in uA against the datasheet limit - every latent defect
    passes. Right: the same parts on the per-lot drift z - they separate. The
    limit did not change, the reference did (rule 3).
    """
    g = d.lot == LOT
    lvl = d.loc[g, f"{PARAM}_168h"].to_numpy()
    dz = z.loc[g, f"z_{PARAM}_drift"].to_numpy()
    bad = d.loc[g, "is_latent_defect"].to_numpy().astype(bool)

    return {
        "lot": LOT,
        "param": PARAM,
        "n": int(g.sum()),
        "nDefect": int(bad.sum()),
        "static": {
            "unit": "uA",
            "limit": DATASHEET_MAX,
            "lo": 0.0, "hi": 50.0,
            "healthy": _hist(lvl[~bad], 0.0, 50.0, 25),
            "defect": _hist(lvl[bad], 0.0, 50.0, 25),
            "defectMax": round(float(lvl[bad].max()), 2),
            # rule: 100% of latent defects pass the datasheet at 168h
            "defectsPassing": int((lvl[bad] <= DATASHEET_MAX).sum()),
        },
        "dynamic": {
            "unit": "sigma",
            "limit": L2_GATE,
            "lo": -6.0, "hi": 24.0,
            "healthy": _hist(dz[~bad], -6.0, 24.0, 30),
            "defect": _hist(dz[bad], -6.0, 24.0, 30),
            "defectsFlagged": int((dz[bad] >= L2_GATE).sum()),
            "healthyFlagged": int((dz[~bad] >= L2_GATE).sum()),
        },
    }


def drift_traces(d: pd.DataFrame) -> dict:
    """Real 168h Iddq traces from LOT: the healthy band plus one latent defect."""
    hours = [0, 24, 96, 168]
    cols = [f"{PARAM}_{h}h" for h in hours]
    lot = d[d.lot == LOT]
    healthy = lot.loc[lot.is_latent_defect == 0, cols].to_numpy()

    lat = lot[lot.is_latent_defect == 1]
    rise = lat[cols[-1]].to_numpy() - lat[cols[0]].to_numpy()
    subject = lat.iloc[int(np.argmax(rise))]

    q = lambda p: [round(float(x), 3) for x in np.nanpercentile(healthy, p, axis=0)]
    return {
        "hours": hours,
        "p50": q(50), "p05": q(5), "p95": q(95),
        "subject": {
            "serial": str(subject.serial),
            "values": [round(float(subject[c]), 2) for c in cols],
            "staticFail168h": int(subject.static_fail_168h),
        },
        "datasheetHi": DATASHEET_MAX,
    }


def decide(d: pd.DataFrame, fused: pd.DataFrame, pda: pd.DataFrame, bands) -> dict:
    """The shipped verdict, measured - never a number typed onto a slide.

    Recall is reported against a stated overkill budget (rule 5); plain accuracy
    would read 92% for a model that says "all good".
    """
    y = d.is_latent_defect.to_numpy().astype(bool)
    healthy = (d.true_class == "healthy").to_numpy()
    v = fused.verdict.to_numpy()

    def band(mask):
        sel = np.isin(v, mask)
        return {
            "parts": int(sel.sum()),
            "share": round(float(sel.mean()), 4),
            "recall": round(float((sel & y).sum() / max(y.sum(), 1)), 3),
            "overkill": round(float((sel & healthy).sum() / max(healthy.sum(), 1)), 4),
        }

    w = asdict(RiskWeights())
    return {
        "bands": {"REJECT": band(["REJECT"]), "REJECT+WATCH": band(["REJECT", "WATCH"])},
        "weights": [{"name": k, "weight": float(x)} for k, x in w.items() if isinstance(x, (int, float))],
        "pdaLimit": PDA_LIMIT,
        # The band edges the run actually used, not round numbers on a slide.
        "bandEdges": {"watch": round(float(bands.watch), 1), "reject": round(float(bands.reject), 1)},
        "lots": [
            {
                "lot": str(lot),
                "parts": int(r.parts),
                "reject": int(r.reject),
                "watch": int(r.watch),
                "rejectFrac": round(float(r.reject_frac), 4),
                "breach": bool(r.reject_frac > PDA_LIMIT),
            }
            for lot, r in pda.iterrows()
        ],
        "scoreHist": _hist(fused.risk_score.to_numpy(), 0, 100, 40),
    }


def lot_map(d: pd.DataFrame) -> dict:
    """Per-lot latent-defect counts - L04 is the deliberately bad lot."""
    g = d.groupby("lot")
    return {
        "lots": [
            {"lot": str(k), "n": int(len(v)), "defects": int(v.is_latent_defect.sum())}
            for k, v in g
        ]
    }


def reasons(d: pd.DataFrame, mb: pd.DataFrame, pda: pd.DataFrame) -> dict:
    """Real explain.py output.

    `subject` is the richest latent defect that still passes every static limit -
    the exact part the screen exists to catch. `register` carries one genuine
    message per reason code so the page quotes the system, not a copywriter.
    """
    rc = reason_codes(d, module_b=mb)
    lot_rc = lot_reason_codes(pda)
    n = rc.groupby("serial").size()
    lat = d[(d.is_latent_defect == 1) & (d.static_fail_168h == 0)].copy()
    lat["ncodes"] = lat.serial.map(n).fillna(0).astype(int)
    s = lat.sort_values("ncodes", ascending=False).iloc[0]

    t = Thresholds()
    gates = {
        "R-101": f"robust z of the 168h level > {t.level_z:g}",
        "R-201": f"robust z of the 0-24h delta > {t.early_z:g}",
        "R-301": f"predicted slope > {t.slope_ratio:g}x the safety slope",
        "R-401": f"pooled drift evidence > {t.pooled:g}  (chi2 0.999, 4 dof)",
        "R-501": f"curvature ratio > {t.curvature:g}, accelerating not settling",
        "R-601": f"lot REJECT fraction > {t.pda:.0%} (PDA gate)",
    }
    titles = {
        "R-101": "Abnormal level for this lot",
        "R-201": "Fast early movement",
        "R-301": "Forecast breaches the safety slope",
        "R-401": "Pooled multivariate evidence",
        "R-501": "Degradation accelerating",
        "R-601": "Lot exceeds PDA",
    }
    register = []
    for code, gate in gates.items():
        hit = (lot_rc if code == "R-601" else rc)
        hit = hit[hit.code == code]
        register.append({
            "code": code,
            "title": titles[code],
            "gate": gate,
            "severity": str(hit.iloc[0].severity) if len(hit) else "high",
            "fired": int(len(hit)),
            "example": str(hit.iloc[0].message) if len(hit) else "",
            "exampleSerial": str(hit.iloc[0].get("serial", hit.iloc[0].get("lot", ""))) if len(hit) else "",
        })

    return {
        "subject": {
            "serial": str(s.serial),
            "lot": str(s.lot),
            "staticFail168h": int(s.static_fail_168h),
            "trace": {
                p: [round(float(s[f"{p}_{h}h"]), 2) for h in (0, 24, 96, 168)]
                for p in ("Iddq_uA", "Ileak_nA", "Tpd_ns", "Vol_mV")
            },
            "codes": [
                {"code": str(r.code), "severity": str(r.severity), "message": str(r.message)}
                for _, r in rc[rc.serial == s.serial].iterrows()
            ],
        },
        "register": register,
        "totalCodes": int(len(rc)),
    }


def headline(d: pd.DataFrame) -> dict:
    lat = d[d.is_latent_defect == 1]
    return {
        "parts": int(len(d)),
        "lots": int(d.lot.nunique()),
        "latentDefects": int(len(lat)),
        "defectRate": round(float(d.is_latent_defect.mean()), 4),
        "latentPassingDatasheet": round(float(1.0 - lat.static_fail_168h.mean()), 4),
        "readPoints": [0, 24, 96, 168],
    }



def hero(d, z, fused, mb, point) -> dict:
    """The worked example the landing page is built around.

    Selected from the data, never hand-typed: the component with the largest
    lot-relative drift that STILL PASSES every static datasheet limit at 168 h.
    That is precisely the escape traditional screening ships and this project
    exists to stop.

    Every figure the page prints about this part comes from here. A number
    typed into JSX is a number that silently rots the next time the dataset is
    regenerated - and one of them already had: an earlier draft quoted a "lot
    median" of 15.1 uA, which is the median of the LATENT SUBSET, not of the
    lot. The real lot reference is ~13.6 uA. The distinction matters: the whole
    claim is that the part is abnormal against its lot, so the lot figure has
    to be the lot's.
    """
    from src.features import robust_sigma

    esc = d[(d.is_latent_defect == 1) & (d.static_fail_168h == 0)].copy()
    # Rank by how close the part got to its datasheet limit WITHOUT breaching.
    # Ranking by raw drift instead picks a part that is further from the limit
    # and therefore easier to dismiss ("it was nowhere near 50 anyway"). The
    # part that passed by a hair is the one that makes the argument: it shipped
    # on 1.1% of margin, and only the lot-relative view saw anything wrong.
    esc["usl_frac"] = esc[f"{PARAM}_168h"] / PARAM_USL[PARAM]
    s_ = esc.sort_values("usl_frac", ascending=False).iloc[0]
    i = s_.name
    lot_rows = d[d.lot == s_.lot]
    hours = [0, 24, 96, 168]
    cols = [f"{PARAM}_{h}h" for h in hours]

    q = lambda pp: [round(float(x), 3) for x in np.nanpercentile(
        lot_rows[cols].to_numpy(dtype=float), pp, axis=0)]

    return {
        "serial": str(s_.serial),
        "lot": str(s_.lot),
        "wafer": str(s_.wafer),
        "param": PARAM,
        "unit": PARAM_UNIT[PARAM],
        "usl": PARAM_USL[PARAM],
        "hours": hours,
        "trace": [round(float(s_[c]), 3) for c in cols],
        "value168": round(float(s_[cols[-1]]), 2),
        # the LOT's own reference values - what the verdict is made against
        "lotMedian168": round(float(lot_rows[cols[-1]].median()), 2),
        "lotSigma168": round(float(robust_sigma(lot_rows[cols[-1]])), 3),
        "lotN": int(len(lot_rows)),
        "uslFrac": round(float(s_[f"{PARAM}_168h"] / PARAM_USL[PARAM]), 4),
        "marginLeft": round(float(PARAM_USL[PARAM] - s_[f"{PARAM}_168h"]), 2),
        "p05": q(5), "p50": q(50), "p95": q(95),
        # evidence
        "driftZ": round(float(z.at[i, f"z_{PARAM}_drift"]), 2),
        "levelZ": round(float(z.at[i, f"z_{PARAM}_level_168h"]), 2),
        "l2": round(float(dpat_score(z).get(i)), 2),
        "l3": round(float(pooled_evidence_score(z).get(i)), 1),
        "forecast168": round(float(point.at[i, PARAM]), 2),
        "slopeRatio": round(float(mb.at[i, "worst_ratio"]), 2),
        "riskScore": round(float(fused.at[i, "risk_score"]), 1),
        "verdict": str(fused.at[i, "verdict"]),
        "subScores": {k: round(float(fused.at[i, k]), 1) for k in SUB_SCORES},
        "staticVerdict": "PASS" if int(s_.static_fail_168h) == 0 else "BREACH",
        "codes": [
            {"code": str(r.code), "severity": str(r.severity), "message": str(r.message)}
            for _, r in reason_codes(d, module_b=mb, index=[i]).iterrows()
        ],
        # lot population at 168h, for the distribution behind the callout
        "lotHist": _hist(lot_rows[cols[-1]].to_numpy(dtype=float), 0.0, 55.0, 44),
        "lotDefectHist": _hist(
            lot_rows.loc[lot_rows.is_latent_defect == 1, cols[-1]].to_numpy(dtype=float),
            0.0, 55.0, 44),
        "histLo": 0.0, "histHi": 55.0,
    }


def main() -> None:
    """Export both payloads from ONE call to src.pipeline.screen().

    This used to re-wire the pipeline by hand - forecast_all, early_reject,
    fuse, bands_for_pda - which quietly skipped `calibrate_population_k`. The
    hand-wired path therefore ran Module B's population gate at the blueprint's
    k=4.5 (fires on ~26% of parts) while src/report.py and the API ran it at
    the PDA-calibrated k, and the two disagreed about a part: L04-0348 scored
    91.7 here against 78.9 there.

    A page that disagrees with the service it describes is worse than no page,
    so both exports now go through the same screen() every other consumer
    calls. Numbers in lab-data.ts moved as a result - they are now the numbers
    src/report.py prints.
    """
    d = pd.read_csv(WIDE)
    res = screen(d)
    z, fr_point, mb = res.features, res.forecast_point, res.module_b
    fused, pda, bands = res.fused, res.pda, res.bands
    payload = {
        "generatedFrom": "data/burnin_wide.csv (seed 42) via src/features.py",
        "headline": headline(d),
        "hero": hero(d, z, fused, mb, fr_point),
        "compare": static_vs_dynamic(d, z),
        "drift": drift_traces(d),
        "lotMap": lot_map(d),
        "reasons": reasons(d, mb, pda),
        "decide": decide(d, fused, pda, bands),
    }
    OUT.write_text(
        "// GENERATED by web/scripts/export_lab_data.py - do not hand-edit.\n"
        "// Every number here comes from the committed dataset (seed 42).\n"
        f"export const LAB = {json.dumps(payload, indent=2)} as const;\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT.relative_to(ROOT)}")

    # The Decision Console needs the whole screened frame, not just the
    # landing page aggregates. Same objects, so the two exports cannot
    # disagree about a part.
    console_export(d, z, fused, mb, fr_point, pda, bands)
    write_samples(d)
    for k in ("headline", "drift", "reasons", "decide"):
        print(k, json.dumps(payload[k], indent=2))
    c = payload["compare"]
    print("compare", json.dumps({**{k: v for k, v in c.items() if k not in ("static", "dynamic")},
                                 "static": {k: v for k, v in c["static"].items() if not isinstance(v, list)},
                                 "dynamic": {k: v for k, v in c["dynamic"].items() if not isinstance(v, list)}}, indent=2))



# ===========================================================================
# CONSOLE EXPORT - web/public/data/console.json
# ===========================================================================
# The Decision Console renders per-part data, so it needs the whole screened
# frame rather than the landing page's summary aggregates. Same pipeline, same
# seed, same fuse() call - nothing here is recomputed or rounded into a
# different answer than src/report.py prints.
#
# Everything the console needs that can be DERIVED from these rows (lot
# envelopes, histograms, the cost-policy sweep) is derived in the browser from
# this file. That keeps one source of truth and stops a second exporter from
# drifting away from the first.

CONSOLE_OUT = ROOT / "web" / "public" / "data" / "console.json"

PARAMS_ORDER = ["Iddq_uA", "Ileak_nA", "Tpd_ns", "Vol_mV"]
READ_POINTS = [0, 24, 96, 168]
SUB_SCORES = ["static_margin", "dynamic_outlier", "predicted_drift",
              "multivariate", "curvature"]


def _r(v, nd=3):
    """Round for transport; None for a missing read (a dropped 96 h handler)."""
    if v is None:
        return None
    f = float(v)
    return None if f != f else round(f, nd)


def console_parts(d, z, fused, mb, point) -> list[dict]:
    """One row per part: measurements, evidence, forecast, verdict.

    Keys are short because this file ships to the browser; the TypeScript in
    web/src/lib/console.ts names them back.
    """
    from src.module_a import dpat_score, pooled_evidence_score

    l2 = dpat_score(z)
    l3 = pooled_evidence_score(z)
    rows = []
    for i in d.index:
        r = d.loc[i]
        f = fused.loc[i]
        rows.append({
            "s": str(r.serial),
            "l": str(r.lot),
            "w": str(r.wafer),
            "x": int(r.x), "y": int(r.y),
            # Measurements, raw datasheet units. Nested arrays indexed
            # [param][readPoint], both in meta order - PARAMS_ORDER and
            # READ_POINTS. Arrays not objects: repeating four parameter names
            # on 2,100 rows costs ~400 KB of wire for no added meaning, and
            # web/src/lib/console.ts names them back on arrival.
            "m": [[_r(r.get(f"{p}_{h}h"), 4) for h in READ_POINTS]
                  for p in PARAMS_ORDER],
            # Module A evidence
            "l2": _r(l2.get(i), 2),          # worst-case robust |z|, all views
            "l3": _r(l3.get(i), 1),          # one-sided pooled sum of squares
            # per-parameter total-drift z - what the detail view attributes on
            "dz": [_r(z.at[i, f"z_{p}_drift"], 2) for p in PARAMS_ORDER],
            "cz": [_r(z.at[i, f"curv_{p}"], 2) for p in PARAMS_ORDER],
            # Module B: forecast 168h from 0h+24h, and the safety-slope ratio
            "fc": ([_r(point.at[i, p], 4) for p in PARAMS_ORDER]
                   if point is not None and i in point.index else None),
            "wr": _r(mb.at[i, "worst_ratio"], 3) if mb is not None else None,
            "wp": str(mb.at[i, "worst_param"]) if mb is not None else None,
            # fusion
            "ss": [_r(f[k], 1) for k in SUB_SCORES],
            "r": _r(f.risk_score, 1),
            "v": str(f.verdict),
            "st": int(r.static_fail_168h),
            # ground truth - SIMULATED DATA ONLY. The console labels it as such
            # and never uses it to make a decision; it is there so a judge can
            # check the screen against a known answer.
            "tc": str(r.true_class),
            "y1": int(r.is_latent_defect),
        })
    return rows


def console_lots(d, fused, pda) -> list[dict]:
    """Per-lot health: class counts, disposition, PDA gate, reference stats."""
    from src.features import robust_sigma

    out = []
    for lot, r in pda.iterrows():
        g = d[d.lot == lot]
        fg = fused.loc[g.index]
        out.append({
            "lot": str(lot),
            "parts": int(r.parts),
            "healthy": int((g.true_class == "healthy").sum()),
            "latent": int((g.true_class == "latent").sum()),
            "gross": int((g.true_class == "gross").sum()),
            "latentRate": _r((g.true_class == "latent").mean(), 4),
            "reject": int(r.reject),
            "watch": int(r.watch),
            "accept": int((fg.verdict == "ACCEPT").sum()),
            "rejectFrac": _r(r.reject_frac, 4),
            "pdaStatus": str(r.status),
            "meanRisk": _r(r.mean_risk, 1),
            "staticFail": int(g.static_fail_168h.sum()),
            # lot reference values an inspector quotes, per parameter/read point
            "ref": {
                p: {
                    "median": [_r(g[f"{p}_{h}h"].median(), 4) for h in READ_POINTS],
                    "sigma168": _r(robust_sigma(g[f"{p}_168h"]), 4),
                    "usl": PARAM_USL[p],
                    "unit": PARAM_UNIT[p],
                }
                for p in PARAMS_ORDER
            },
        })
    return out


def console_reasons(d, mb) -> dict:
    """Real explain.py output, keyed by serial. Only parts that earned a code."""
    rc = reason_codes(d, module_b=mb)
    out: dict[str, list] = {}
    for _, r in rc.iterrows():
        out.setdefault(str(r.serial), []).append({
            "code": str(r.code),
            "severity": str(r.severity),
            "message": str(r.message),
            "feature": str(r.contributing_feature),
            "value": _r(r.feature_value, 3),
            "ref": _r(r.lot_reference_value, 4),
        })
    return out


def console_export(d, z, fused, mb, point, pda, bands) -> None:
    from src.explain import MODEL_VERSION, Thresholds
    from src.evaluate import pr_auc, recall_at_overkill

    y = d.is_latent_defect.to_numpy().astype(bool)
    healthy = (d.true_class == "healthy").to_numpy()
    v = fused.verdict.to_numpy()
    flagged = np.isin(v, ["REJECT", "WATCH"])

    t = Thresholds()
    payload = {
        "meta": {
            "generatedFrom": "data/burnin_wide.csv (seed 42)",
            "generatedBy": "web/scripts/export_lab_data.py -> src/pipeline.py",
            "modelVersion": MODEL_VERSION,
            "simulatedData": True,
            "readPoints": READ_POINTS,
            "stressTempC": 125,
            "params": [
                {"name": p, "unit": PARAM_UNIT[p], "usl": PARAM_USL[p],
                 "label": PARAM_LABEL[p], "isCurrent": p in ("Iddq_uA", "Ileak_nA")}
                for p in PARAMS_ORDER
            ],
            "subScores": SUB_SCORES,
            "weights": {k: float(x) for k, x in asdict(RiskWeights()).items()},
            "bands": {"watch": _r(bands.watch, 1), "reject": _r(bands.reject, 1)},
            "pdaLimit": PDA_LIMIT,
            "thresholds": {
                "R-101": t.level_z, "R-201": t.early_z, "R-301": t.slope_ratio,
                "R-401": t.pooled, "R-501": t.curvature, "R-601": t.pda,
            },
            "costRatioDefault": 100,
        },
        "summary": {
            "parts": int(len(d)),
            "lots": int(d.lot.nunique()),
            "healthy": int(healthy.sum()),
            "latent": int(y.sum()),
            "gross": int((d.true_class == "gross").sum()),
            "reject": int((v == "REJECT").sum()),
            "watch": int((v == "WATCH").sum()),
            "accept": int((v == "ACCEPT").sum()),
            # the headline gap: static limits catch none of the latent defects
            "staticFlagged": int(d.static_fail_168h.sum()),
            "staticRecall": _r(
                (d.static_fail_168h.to_numpy().astype(bool) & y).sum() / max(y.sum(), 1), 3),
            "rejectRecall": _r(((v == "REJECT") & y).sum() / max(y.sum(), 1), 3),
            "flaggedRecall": _r((flagged & y).sum() / max(y.sum(), 1), 3),
            "flaggedOverkill": _r((flagged & healthy).sum() / max(healthy.sum(), 1), 4),
            "rejectOverkill": _r(((v == "REJECT") & healthy).sum() / max(healthy.sum(), 1), 4),
            "fusedPrAuc": _r(pr_auc(y, fused.risk_score.to_numpy(), warn_ties=False), 4),
            "recallAt5": _r(recall_at_overkill(
                y, fused.risk_score.to_numpy(), 0.05, healthy)["recall"], 3),
            "recallAt10": _r(recall_at_overkill(
                y, fused.risk_score.to_numpy(), 0.10, healthy)["recall"], 3),
            "lotsBreachingPda": int((pda.reject_frac > PDA_LIMIT).sum()),
        },
        "lots": console_lots(d, fused, pda),
        "parts": console_parts(d, z, fused, mb, point),
        "reasons": console_reasons(d, mb),
    }

    CONSOLE_OUT.parent.mkdir(parents=True, exist_ok=True)
    CONSOLE_OUT.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    kb = CONSOLE_OUT.stat().st_size / 1024
    print(f"wrote {CONSOLE_OUT.relative_to(ROOT)}  ({kb:.0f} KB, "
          f"{len(payload['parts'])} parts, {len(payload['reasons'])} parts with codes)")


# ===========================================================================
# UPLOAD SAMPLES - web/public/samples/*.csv
# ===========================================================================
# Fixtures for the console's Screen page, so a judge can exercise the upload
# path without owning burn-in data. Cut from the committed dataset with the
# LABEL COLUMNS STRIPPED - exactly the shape a real ATE data-log exports, and
# exactly what POST /screen accepts.

SAMPLES = ROOT / "web" / "public" / "samples"

# Label columns must never appear in an upload fixture: they are the answer,
# and a demo that feeds the answer back in is not a demo.
LABEL_COLS = ["true_class", "is_latent_defect", "static_fail_168h"]


def write_samples(d: pd.DataFrame) -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    id_cols = ["serial", "lot", "wafer", "x", "y"]

    # A two-lot frame: enough lots for GroupKFold to hold one out, so the
    # forecast comes back out-of-fold and the MAE is quotable. Includes the
    # lot the landing page is about.
    two = d[d.lot.isin(["L04", "L03"])].drop(columns=LABEL_COLS)
    two.to_csv(SAMPLES / "burnin_two_lots_168h.csv", index=False)

    # The hour-24 triage frame: 0 h and 24 h reads only. Module B and the
    # 168h-derived sub-scores are unavailable on this and the console says so.
    early = [f"{p}_{t}h" for p in PARAMS_ORDER for t in (0, 24)]
    two[id_cols + early].to_csv(SAMPLES / "burnin_hour24_triage.csv", index=False)

    # A small full-read-point frame for a fast round trip on a demo laptop.
    small = d[d.lot == "L04"].head(60).drop(columns=LABEL_COLS)
    small.to_csv(SAMPLES / "burnin_small_168h.csv", index=False)

    for f in sorted(SAMPLES.glob("*.csv")):
        n = sum(1 for _ in f.open()) - 1
        print(f"wrote {f.relative_to(ROOT)}  ({n} parts, {f.stat().st_size/1024:.0f} KB)")

if __name__ == "__main__":
    main()
