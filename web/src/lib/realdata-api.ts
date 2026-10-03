"use client";

/** Client for the prepared NASA datasets (/v1/realdata). Read-only views of
 *  measured data; see src/realdata/ for how each file was prepared. */

import { ApiError, getApiBase } from "@/lib/screen-api";

export interface EvalScore {
  parts: number;
  failing_later: number;
  recall: number;
  precision: number;
  f2: number;
  pr_auc: number;
  tp: number;
  fp: number;
  fn: number;
  tn: number;
}

export interface CapTruth {
  serial: string;
  lot: string;
  stress_v: number;
  eol: number;
  eol_day: number | null;
  eol_by: string | null;
  last_day: number;
  c_loss_at_end_pct: number;
  esr_rise_at_end_pct: number;
}

export interface CapSeries {
  lot: string;
  stress_v: number;
  day: number[];
  c_loss_pct: number[];
  esr_rise_pct: number[];
  tan_delta120: number[];
}

export interface CapReadDay {
  excluded_already_failed: string[];
  pooled_population: EvalScore;
  pooled_within_stress_lot: EvalScore;
  forecast_end_c_loss: EvalScore;
  ranking: { serial: string; pooled_z: number; forecast_end_c_loss_pct: number; fails_later: number; eol_day: number | null }[];
}

export interface Capacitors {
  metadata: {
    source: string;
    capacitors: number;
    reads: number;
    excluded_reads: number;
    conditioning_days: number;
    eol_rule: Record<string, unknown>;
    prepared_utc: string;
    rule: string;
  };
  truth: CapTruth[];
  series: Record<string, CapSeries>;
  evaluation: { end_day: number; flag_rule: string; by_read_day: Record<string, CapReadDay> } | null;
}

export interface MosTruth {
  device: string;
  runs: number;
  hours: number;
  rds25_first_ohm: number;
  rds25_last_ohm: number;
  rds25_rise_pct: number;
  max_rise_pct: number;
  labelable: number;
  eol: number;
  eol_run: number | null;
  eol_hours: number | null;
  alpha_source: string;
}

export interface MosRun {
  device: string;
  run: number;
  start_hours: number;
  end_hours: number;
  waveforms: number;
  rds25_ohm: number;
  rds25_rise_pct: number;
  package_c: number | null;
  set_high_temp_c: number | null;
}

export interface Mosfet {
  metadata: { source: string; devices: number; waveforms: number; eol_rule: Record<string, unknown>; prepared_utc: string };
  excluded_files: number;
  truth: MosTruth[];
  runs: MosRun[];
  evaluation: {
    early_read?: string;
    devices_scored?: number;
    excluded_already_failed?: string[];
    pooled_population?: EvalScore;
    ranking?: { device: string; pooled_z: number; rds_rise_pct: number; fails_later: number }[];
    note?: string;
  } | null;
}

async function get<T>(path: string): Promise<T> {
  const base = getApiBase();
  let r: Response;
  try {
    r = await fetch(`${base}${path}`, { cache: "no-store" });
  } catch {
    throw new ApiError(`Cannot reach the SENTINEL service at ${base}.`, undefined,
      "Start it from the repository root:  uvicorn src.api:app --port 8000");
  }
  const j = await r.json().catch(() => null);
  if (!r.ok) throw new ApiError(j?.error?.message ?? `${path} returned ${r.status}`, r.status);
  return j as T;
}

export const realApi = {
  available: () => get<Record<string, { prepared: boolean; how?: string; evaluated?: boolean; source?: string }>>("/v1/realdata"),
  capacitors: () => get<Capacitors>("/v1/realdata/capacitors"),
  mosfet: () => get<Mosfet>("/v1/realdata/mosfet"),
};
