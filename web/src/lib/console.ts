"use client";

/**
 * Decision Console data layer.
 *
 * Everything here reads /data/console.json, which is written by
 * web/scripts/export_lab_data.py from ONE call to src/pipeline.py::screen() -
 * the same function the FastAPI service and src/report.py call. No number in
 * the console is computed by a second implementation of anything in src/.
 *
 * What IS computed here: quantities that are pure functions of those rows -
 * lot envelopes, histograms, robust statistics, and the cost-policy sweep.
 * Deriving them in the browser keeps one source of truth; a second Python
 * exporter would be a second place for them to drift.
 *
 * All data is SIMULATED (seed 42). `meta.simulatedData` carries that flag and
 * the UI surfaces it - see <Provenance/> in components/ui/kit.tsx.
 */

import { useEffect, useState } from "react";

// ----------------------------------------------------------------- types
export type Verdict = "ACCEPT" | "WATCH" | "REJECT";
export type TrueClass = "healthy" | "latent" | "gross";

export interface ParamMeta {
  name: string;
  unit: string;
  usl: number;
  label: string;
  isCurrent: boolean;
}

export interface Meta {
  generatedFrom: string;
  generatedBy: string;
  modelVersion: string;
  simulatedData: boolean;
  readPoints: number[];
  stressTempC: number;
  params: ParamMeta[];
  subScores: string[];
  weights: Record<string, number>;
  bands: { watch: number; reject: number };
  pdaLimit: number;
  thresholds: Record<string, number>;
  costRatioDefault: number;
}

export interface Summary {
  parts: number; lots: number;
  healthy: number; latent: number; gross: number;
  reject: number; watch: number; accept: number;
  staticFlagged: number; staticRecall: number;
  rejectRecall: number; flaggedRecall: number;
  flaggedOverkill: number; rejectOverkill: number;
  fusedPrAuc: number; recallAt5: number; recallAt10: number;
  lotsBreachingPda: number;
}

export interface LotRef {
  median: number[];
  sigma168: number;
  usl: number;
  unit: string;
}

export interface Lot {
  lot: string; parts: number;
  healthy: number; latent: number; gross: number; latentRate: number;
  reject: number; watch: number; accept: number;
  rejectFrac: number; pdaStatus: string; meanRisk: number; staticFail: number;
  ref: Record<string, LotRef>;
}

/** One screened part. Short keys are the wire format; see the export script. */
export interface Part {
  s: string;                      // serial
  l: string;                      // lot
  w: string;                      // wafer
  x: number; y: number;           // die position
  m: (number | null)[][];         // [param][readPoint] raw measurement
  l2: number;                     // Module A L2 - worst-case robust |z|
  l3: number;                     // Module A L3 - one-sided pooled evidence
  dz: (number | null)[];          // per-param total-drift robust z
  cz: (number | null)[];          // per-param curvature ratio
  fc: number[] | null;            // Module B forecast of the 168h value
  wr: number | null;              // worst safety-slope ratio
  wp: string | null;              // which parameter carried it
  ss: number[];                   // five sub-scores, meta.subScores order
  r: number;                      // 0-100 screening risk score
  v: Verdict;
  st: number;                     // static datasheet breach at 168h
  tc: TrueClass;                  // SIMULATED ground truth - never a decision input
  y1: number;                     // is_latent_defect
}

export interface Reason {
  code: string;
  severity: "high" | "medium" | "low";
  message: string;
  feature: string;
  value: number;
  ref: number;
}

export interface ConsoleData {
  meta: Meta;
  summary: Summary;
  lots: Lot[];
  parts: Part[];
  reasons: Record<string, Reason[]>;
}

// ---------------------------------------------------------------- loading
let cache: Promise<ConsoleData> | null = null;

/** Fetch once per page load; every console screen shares the one payload. */
export function loadConsole(): Promise<ConsoleData> {
  if (!cache) {
    // Root-relative, NOT "data/console.json": a relative URL resolves against
    // the document path, so on /console/components it would request
    // /console/data/console.json and 404. If this app ever gains a basePath,
    // this is the one line that has to learn about it.
    cache = fetch("/data/console.json").then((r) => {
      if (!r.ok) {
        throw new Error(
          `console.json ${r.status} - run: python web/scripts/export_lab_data.py`
        );
      }
      return r.json() as Promise<ConsoleData>;
    });
  }
  return cache;
}

export function useConsole() {
  const [data, setData] = useState<ConsoleData | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    loadConsole()
      .then((d) => live && setData(d))
      .catch((e) => live && setError(String(e.message ?? e)));
    return () => {
      live = false;
    };
  }, []);
  return { data, error };
}

// ------------------------------------------------------------ statistics
/** Median of the finite values. Returns NaN on an empty sample. */
export function median(xs: number[]): number {
  const v = xs.filter(Number.isFinite).sort((a, b) => a - b);
  if (!v.length) return NaN;
  const h = v.length >> 1;
  return v.length % 2 ? v[h] : (v[h - 1] + v[h]) / 2;
}

export function quantile(xs: number[], q: number): number {
  const v = xs.filter(Number.isFinite).sort((a, b) => a - b);
  if (!v.length) return NaN;
  const pos = (v.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return lo === hi ? v[lo] : v[lo] + (v[hi] - v[lo]) * (pos - lo);
}

/**
 * 1.4826 * MAD - the spread estimator used everywhere in src/features.py.
 * Never std: a mean-based sigma is inflated by the outlier it is hunting.
 */
export function robustSigma(xs: number[]): number {
  const v = xs.filter(Number.isFinite);
  if (!v.length) return 0;
  const med = median(v);
  const mad = median(v.map((x) => Math.abs(x - med)));
  if (mad > 0) return 1.4826 * mad;
  const iqr = quantile(v, 0.75) - quantile(v, 0.25);
  return iqr > 0 ? iqr / 1.35 : 0;
}

/**
 * Upper robust bands (median + k·robust σ) of a lot, in the parameter's own
 * units. Currents are lognormal (rule 1), so for them the band is computed on
 * log(x) and mapped back with exp - a raw-unit σ on a lognormal lot is inflated
 * by the very tail it is meant to expose.
 */
export function lotBands(xs: number[], isCurrent: boolean, ks: number[] = [3, 6]) {
  const v = xs.filter((x) => Number.isFinite(x) && (!isCurrent || x > 0));
  const t = isCurrent ? v.map(Math.log) : v;
  const med = median(t);
  const s = robustSigma(t);
  const back = (y: number) => (isCurrent ? Math.exp(y) : y);
  return { median: back(med), bands: ks.map((k) => ({ k, x: back(med + k * s) })) };
}

export interface Bin { x: number; n: number }

export function histogram(xs: number[], lo: number, hi: number, bins: number): Bin[] {
  const out: Bin[] = Array.from({ length: bins }, (_, i) => ({
    x: lo + ((hi - lo) * i) / bins,
    n: 0,
  }));
  const w = (hi - lo) / bins;
  for (const v of xs) {
    if (!Number.isFinite(v)) continue;
    const i = Math.min(bins - 1, Math.max(0, Math.floor((v - lo) / w)));
    out[i].n += 1;
  }
  return out;
}

// ------------------------------------------------------------- selectors
export const paramIndex = (meta: Meta, name: string) =>
  meta.params.findIndex((p) => p.name === name);

export const measurement = (p: Part, pi: number, ri: number) => p.m[pi]?.[ri] ?? null;

export const partsInLot = (parts: Part[], lot: string) => parts.filter((p) => p.l === lot);

/**
 * Lot envelope for one parameter: the 5th / 50th / 95th percentile of the lot
 * at each read point. This is the band a part is judged against, and the band
 * drawn behind its trace - the same construction as explain.drift_plot().
 */
export function lotEnvelope(parts: Part[], lot: string, pi: number) {
  const rows = partsInLot(parts, lot);
  const at = (ri: number) =>
    rows.map((p) => measurement(p, pi, ri)).filter((v): v is number => v !== null);
  const idx = [0, 1, 2, 3];
  return {
    p05: idx.map((ri) => quantile(at(ri), 0.05)),
    p50: idx.map((ri) => median(at(ri))),
    p95: idx.map((ri) => quantile(at(ri), 0.95)),
  };
}

export const verdictOf = (risk: number, meta: Meta): Verdict =>
  risk >= meta.bands.reject ? "REJECT" : risk >= meta.bands.watch ? "WATCH" : "ACCEPT";

// ---------------------------------------------------- decision policy
export interface PolicyPoint {
  threshold: number;
  flagged: number;
  flaggedFraction: number;
  recall: number;
  overkill: number;      // among HEALTHY parts only - the honest number
  precision: number;
  cost: number;
  lotsBreaching: number;
}

/**
 * Cost-minimising operating point on the fused risk score, for a stated
 * C_FN / C_FP ratio.
 *
 * This is rule 7 of CLAUDE.md made interactive: the threshold minimises
 * `C_FN*FN + C_FP*FP`, and the ratio is a parameter the engineer sets, never a
 * magic number. Overkill is measured against HEALTHY parts only - flagging a
 * gross failure is correct behaviour, not over-rejection, and mixing the two
 * flatters the screen (src/evaluate.py says the same thing at more length).
 *
 * Thresholds are the distinct score values, so no operating point is invented
 * between two parts the score cannot separate.
 */
export function policySweep(parts: Part[], costRatio: number, pdaLimit: number): PolicyPoint {
  const rows = parts
    .map((p) => ({ r: p.r, latent: p.y1 === 1, healthy: p.tc === "healthy", lot: p.l }))
    .sort((a, b) => b.r - a.r);

  const nPos = rows.filter((x) => x.latent).length;
  const nHealthy = rows.filter((x) => x.healthy).length;
  const lotSize = new Map<string, number>();
  for (const p of parts) lotSize.set(p.l, (lotSize.get(p.l) ?? 0) + 1);

  let tp = 0, fp = 0, ok = 0;
  const lotHits = new Map<string, number>();
  let best: PolicyPoint | null = null;

  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    if (row.latent) tp++; else fp++;
    if (row.healthy) ok++;
    lotHits.set(row.lot, (lotHits.get(row.lot) ?? 0) + 1);

    // Only cut where the next score differs, so ties move together.
    if (i + 1 < rows.length && rows[i + 1].r === row.r) continue;

    const fn = nPos - tp;
    const cost = costRatio * fn + 1 * fp;
    if (best === null || cost < best.cost) {
      let breaching = 0;
      lotHits.forEach((hits, lot) => {
        if (hits / (lotSize.get(lot) ?? 1) > pdaLimit) breaching++;
      });
      best = {
        threshold: row.r,
        flagged: tp + fp,
        flaggedFraction: (tp + fp) / rows.length,
        recall: nPos ? tp / nPos : NaN,
        overkill: nHealthy ? ok / nHealthy : NaN,
        precision: tp + fp ? tp / (tp + fp) : 0,
        cost,
        lotsBreaching: breaching,
      };
    }
  }
  return (
    best ?? {
      threshold: 100, flagged: 0, flaggedFraction: 0, recall: 0,
      overkill: 0, precision: 0, cost: 0, lotsBreaching: 0,
    }
  );
}

/** Recall against the over-rejection budget. The curve that belongs on a slide. */
export function recallOverkillCurve(parts: Part[], steps = 120) {
  const rows = parts
    .map((p) => ({ r: p.r, latent: p.y1 === 1, healthy: p.tc === "healthy" }))
    .sort((a, b) => b.r - a.r);
  const nPos = rows.filter((x) => x.latent).length;
  const nHealthy = rows.filter((x) => x.healthy).length;

  const pts: { overkill: number; recall: number; threshold: number }[] = [];
  let tp = 0, ok = 0;
  const every = Math.max(1, Math.floor(rows.length / steps));
  for (let i = 0; i < rows.length; i++) {
    if (rows[i].latent) tp++;
    if (rows[i].healthy) ok++;
    if (i % every === 0 || i === rows.length - 1) {
      pts.push({
        overkill: nHealthy ? ok / nHealthy : 0,
        recall: nPos ? tp / nPos : 0,
        threshold: rows[i].r,
      });
    }
  }
  return pts;
}
