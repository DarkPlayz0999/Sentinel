"use client";

/**
 * Client for the digital twin (/v1/simulations, /v1/experiments, /v1/twin).
 *
 * The browser simulates nothing and decides nothing. Every number the lab
 * shows comes from these endpoints: the engine in src/twin generates the
 * measurements, Sentinel (src/pipeline via the service) screens them, and the
 * agents investigate. In BLIND mode the API itself withholds ground truth,
 * so the page cannot leak it by accident.
 */

import { useEffect, useRef, useState } from "react";
import { ApiError, getApiBase } from "@/lib/screen-api";

export type Mode = "VISIBLE" | "BLIND";
export type SimStatus =
  | "CREATED" | "PAUSED" | "QUEUED" | "RUNNING" | "SIMULATED" | "SCREENING"
  | "SCREENED" | "INVESTIGATED" | "FAILED" | "SIMULATION_FAILED";
export type Verdict = "ACCEPT" | "WATCH" | "REJECT";

export interface BoardComponent {
  component_id: string;
  type: string;
  component_model: string;
  label: string;
  part_number: string;
  nominal: Record<string, number>;
  units: Record<string, string>;
  param_labels: Record<string, string>;
  position_mm: [number, number];
  size_mm: [number, number, number];
  theta_c_per_w: number;
  nets: string[];
  ratings: Record<string, number>;
}

export interface FaultModel {
  fault_type: string;
  kind: string;
  mechanism: string;
  intermittent: boolean;
  effects: { param: string; mode: string; full_scale: number }[];
}

export interface Catalogue {
  board: {
    board_id: string;
    name: string;
    size_mm: [number, number];
    components: BoardComponent[];
    nets: Record<string, string[]>;
  };
  faults: Record<string, FaultModel[]>;
  detectability: Record<string, Record<string, string[]>>;
  key_params: Record<string, string[]>;
  replaceable_kinds: string[];
  sih_demo: Record<string, number | string>;
  ngspice: boolean;
  time_base: string;
}

export interface SimFault {
  board_serial: string;
  board_index: number;
  component_id: string;
  fault_type: string;
  severity: number;
  start_h: number;
  growth_rate: number;
  source: string;
}

export interface Hypothesis {
  rank: number;
  component_id: string;
  fault_type: string;
  mechanism: string;
  evidence_score: number;
  implied_severity: number;
  signature: string[];
}

export interface QACheck {
  check: string;
  status: "PASS" | "WARN" | "FAIL" | "INFO";
  detail: string;
}

export interface BoardDiagnosis {
  suspect_component: string | null;
  components_ranked: string[];
  hypotheses: (Hypothesis & { similarity_to_top: number; note: string | null })[];
  ambiguity_group: string[];
  discriminating_tests: { component_id: string; test: string }[];
  observed: { ate_view: string; ate_drift_z: Record<string, number>; ir_rise_z: Record<string, number> };
  carrier_parameters: string[];
  hot_components: string[];
  neighbours: string[];
  electrical_dependencies: string[];
}

export interface Investigation {
  report: {
    focus_serial: string;
    verdict: Verdict;
    risk_score: number;
    primary_reason: Record<string, unknown> | null;
    suspect_component: string | null;
    suspect_fault_type: string | null;
    evidence_score: number | null;
    ambiguity_group: string[];
    discriminating_tests: { component_id: string; test: string }[];
    qa_status: string;
    recommended_actions: string[];
    summary: string;
    disclaimers: string[];
  };
  root_cause: { focus_serial: string; hypotheses: Hypothesis[]; score_kind: string } | null;
  explanation?: { plain_summary: string; source: "mistral" | "built-in"; model: string | null; number_check: string; note: string | null } | null;
  qa_safety: { status: string; checks: QACheck[] } | null;
  boards: Record<string, BoardDiagnosis>;
}

export interface Simulation {
  simulation_id: string;
  created_at: string;
  status: SimStatus;
  mode: Mode;
  board_id: string;
  lot_id: string;
  boards: number;
  random_seed: number;
  config: {
    stress_temp_c: number;
    read_temp_c: number;
    checkpoints: number[];
    dt_h: number;
    noise: Record<string, unknown>;
  };
  options: { solver: string; auto_screen: boolean; monitor_z: number; label: string; scenario: string };
  sim_time_h: number;
  software_version: string;
  model_version: string;
  dataset_id: string | null;
  run_id: string | null;
  workflow_id: string | null;
  investigation_id: string | null;
  focus_serial: string | null;
  investigation: Investigation | null;
  revealed_at: string | null;
  error: Record<string, unknown> | null;
  time_base: string;
  truth_visible: boolean;
  faults: SimFault[] | { hidden: true; count: string };
  verdicts: Record<Verdict, number> | null;
  interim_screens: number[];
  replacements: number;
}

export interface LotBoard {
  serial: string;
  index: number;
  latest: Record<string, number | null> | null;
  risk_score: number | null;
  verdict: Verdict | null;
  suspect_component: string | null;
  is_faulty?: number;
}

export interface Timeline {
  serial: string;
  phase: string;
  hours: number[];
  time_base: string;
  truth_visible: boolean;
  observed: {
    ir_temp_c: Record<string, (number | null)[]>;
    /** Lot median IR reading per position and hour (observed). */
    ir_lot_median_c: Record<string, (number | null)[]>;
    rail_v: (number | null)[];
    ate: Record<string, { time_h: number; value: number | null }[]>;
  };
  provenance: Record<string, { measurement_source: string; solver: string }>;
  truth?: {
    components: Record<string, {
      values: Record<string, (number | null)[]>;
      temp_c: (number | null)[] | null;
      health: (number | null)[] | null;
      stress: (number | null)[] | null;
      power_w: (number | null)[] | null;
    }>;
    nodes: Record<string, (number | null)[]>;
    ate_true: Record<string, (number | null)[]>;
    faults: { component_id: string; fault_type: string; severity: number; start_h: number }[];
    glitches: { component_id: string; read_h: number }[];
  };
}

export interface ReasonCodeRow {
  code: string;
  severity: string;
  message: string;
  contributing_feature?: string;
  feature_value?: number;
  lot_reference_value?: number;
}

export interface ComponentsView {
  serial: string;
  time_h: number;
  truth_visible: boolean;
  verdict: Verdict | null;
  risk_score: number | null;
  reason_codes: ReasonCodeRow[];
  forecast: { predicted_168h: Record<string, number> | null; upper_168h: Record<string, number> | null } | null;
  components: (BoardComponent & {
    status: string;
    anomaly_score: number | null;
    failure_probability: null;
    observed: { ir_temp_c: number | null };
    truth?: {
      values: Record<string, number | null>;
      temperature_c: number | null;
      health: number | null;
      degradation: number | null;
      stress: number | null;
    };
  })[];
}

export interface Candidate {
  candidate_id: string;
  reel: string;
  reel_label: string;
  inspection: Record<string, number>;
  criteria: Record<string, number>;
  penalties: Record<string, number>;
  ranking_score: number;
  score_kind: string;
}

export interface Offer {
  serial: string;
  component_id: string;
  criteria_weights: Record<string, number>;
  criteria_full_scale: Record<string, number>;
  score_kind: string;
  candidates: Candidate[];
}

export interface Replacement {
  replacement_id: string;
  phase: string;
  board_serial: string;
  component_id: string;
  candidate_id: string;
  reel: string;
  candidate: Candidate;
  before: {
    risk_score: number | null;
    verdict: Verdict | null;
    reason_codes: string[];
    ate_168h: Record<string, number | null>;
    ir_temp_c: number | null;
    bench_removed_part: Record<string, number>;
  };
  after: {
    component_id: string;
    risk_score: number;
    verdict: Verdict;
    reason_codes: string[];
    ate_168h: Record<string, number | null>;
    ir_temp_c: number | null;
    incoming_inspection: Record<string, number>;
  };
  outcome: Verdict;
  truth?: {
    truth_before: Record<string, number | null>;
    truth_after: Record<string, number | null>;
    latent_fault: Record<string, unknown> | null;
  };
}

export interface Benchmark {
  boards: number;
  faulty_boards: number;
  confusion: { tp: number; fp: number; fn: number; tn: number };
  recall: number;
  precision: number;
  f1: number;
  f2: number;
  false_negative_rate: number;
  false_positive_rate: number;
  pr_auc: number;
  recall_at_overkill: { budget: number; recall: number; overkill_rate: number; feasible: boolean };
  reject_only: { recall: number; precision: number; f_beta: number; tp: number; fp: number; fn: number; tn: number };
  counts: { injected: number; detected: number; missed: number; incorrectly_flagged: number; unobservable_faults?: number; average_detection_h?: number };
  recall_observable_faults?: number;
  by_fault_type?: { component: string; fault_type: string; n: number; detected: number; recall: number; mean_severity: number }[];
  detection_delay_h?: { mean: number; median: number; by_read: Record<string, number> };
  localization?: { evaluated: number; top1: number; top3: number };
  forecast?: {
    out_of_fold: boolean;
    by_parameter: Record<string, { mae: number; normalised_mae: number; rmse: number; upper_coverage: number; drift_error: number | null }>;
    note: string | null;
  };
  false_negatives: { serial: string; components: string; fault_types: string; severity: number; risk_score: number }[];
  false_positives: { serial: string; verdict: string; risk_score: number }[];
  accuracy: string;
  notes: string[];
}

export interface Reveal {
  simulation_id: string;
  revealed_at: string;
  faults: SimFault[];
  faulty_boards: { serial: string; components: string; fault_types: string; severity: number; detectable: boolean; sentinel_verdict: Verdict | null }[];
  benchmark: Benchmark;
  replacements: { board_serial: string; replaced: string; was_the_faulty_part: boolean; outcome: Verdict; new_part_latent_fault: Record<string, unknown> | null }[];
  operating_point: string;
}

export interface SimEvent {
  id: number;
  type: string;
  serial: string | null;
  component_id: string | null;
  payload: Record<string, unknown>;
  at: string;
}

export interface Experiment {
  experiment_id: string;
  created_at: string;
  completed_at: string | null;
  status: "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED";
  kind: "esr_sweep" | "monte_carlo" | "ood";
  random_seed: number;
  runs: number;
  progress: { done: number; total: number; cell: string } | null;
  spec?: Record<string, unknown>;
  artifact_path?: string | null;
  error?: string | null;
  headline?: Record<string, number> | null;
  summary?: {
    runs: number;
    boards_scored: number;
    duration_s: number;
    overall: Benchmark;
    by_cell: Record<string, Benchmark & { esr_target_ohm?: number; stress_temp_c?: number; true_esr_168h_median_ohm?: number; mean_risk_faulty?: number }>;
    forecaster: { trained_on_lots: number; note: string };
    operating_point: string;
  } | null;
}

// ------------------------------------------------------------------ fetch
async function call<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  const base = getApiBase();
  let r: Response;
  try {
    r = await fetch(`${base}${path}`, {
      method,
      cache: "no-store",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(
      `Cannot reach the screening service at ${base}.`,
      undefined,
      "Start it from the repository root:  uvicorn src.api:app --port 8000",
    );
  }
  const json = await r.json().catch(() => null);
  if (!r.ok) {
    const msg = json?.error?.message ?? json?.detail ?? `${path} returned ${r.status}`;
    throw new ApiError(typeof msg === "string" ? msg : JSON.stringify(msg), r.status);
  }
  return json as T;
}

const q = (o: Record<string, string | number | undefined>) =>
  Object.entries(o)
    .filter(([, v]) => v !== undefined)
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
    .join("&");

export const simApi = {
  catalogue: () => call<Catalogue>("GET", "/v1/twin/board"),
  list: () => call<(Pick<Simulation, "simulation_id" | "created_at" | "status" | "mode" | "lot_id" | "boards" | "random_seed" | "sim_time_h" | "focus_serial"> & { label: string; scenario: string })[]>("GET", "/v1/simulations?limit=30"),
  create: (body: Record<string, unknown>, start = false) =>
    call<Simulation>("POST", `/v1/simulations?start=${start}`, body),
  addFault: (sid: string, body: Record<string, unknown>) =>
    call<Simulation>("POST", `/v1/simulations/${sid}/faults`, body),
  start: (sid: string) => call<{ status: SimStatus; job_id: string }>("POST", `/v1/simulations/${sid}/start`),
  step: (sid: string) => call<Simulation>("POST", `/v1/simulations/${sid}/step`),
  screen: (sid: string) => call<Simulation>("POST", `/v1/simulations/${sid}/screen`),
  get: (sid: string) => call<Simulation>("GET", `/v1/simulations/${sid}`),
  boards: (sid: string) =>
    call<{ time_h: number | null; reads: number[]; truth_visible: boolean; boards: LotBoard[] }>(
      "GET", `/v1/simulations/${sid}/boards`),
  components: (sid: string, serial: string, t?: number) =>
    call<ComponentsView>("GET", `/v1/simulations/${sid}/components?${q({ serial, t })}`),
  timeline: (sid: string, serial: string, phase = "burn-in-1") =>
    call<Timeline>("GET", `/v1/simulations/${sid}/timeline?${q({ serial, phase })}`),
  candidates: (sid: string, serial: string, component_id: string) =>
    call<Offer>("GET", `/v1/simulations/${sid}/candidates?${q({ serial, component_id })}`),
  replace: (sid: string, serial: string, component_id: string, candidate_id: string) =>
    call<{ replacements: Replacement[]; truth_visible: boolean }>(
      "POST", `/v1/simulations/${sid}/replace`, { serial, component_id, candidate_id }),
  comparison: (sid: string) =>
    call<{ replacements: Replacement[]; truth_visible: boolean }>("GET", `/v1/simulations/${sid}/comparison`),
  decide: (sid: string, serial: string, decision: string, note: string) =>
    call<{ recorded: boolean }>("POST", `/v1/simulations/${sid}/boards/${serial}/decision`, { decision, note }),
  reveal: (sid: string) => call<Reveal>("POST", `/v1/simulations/${sid}/reveal`),
  audit: (sid: string) => call<{ events: { seq: number; event_type: string; timestamp: string; board_serial: string | null; component_id: string | null; payload: Record<string, unknown> }[] }>(
    "GET", `/v1/simulations/${sid}/audit`),
  experiments: () => call<Experiment[]>("GET", "/v1/experiments?limit=30"),
  experiment: (eid: string) => call<Experiment>("GET", `/v1/experiments/${eid}`),
  runExperiment: (body: Record<string, unknown>) => call<Experiment>("POST", "/v1/experiments", body),
};

/** Live simulation events over SSE. `connected` is the real socket state. */
export function useSimEvents(sid: string | null, onEvent: (e: SimEvent) => void) {
  const [connected, setConnected] = useState(false);
  const cb = useRef(onEvent);
  cb.current = onEvent;

  useEffect(() => {
    if (!sid) return;
    const es = new EventSource(`${getApiBase()}/v1/simulations/${sid}/events?since=0`);
    const handle = (m: MessageEvent) => {
      try {
        cb.current({ id: Number(m.lastEventId), ...JSON.parse(m.data) });
      } catch {
        /* malformed frame: ignore rather than render a guess */
      }
    };
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = handle;
    const types = [
      "SIMULATION_CREATED", "SIMULATION_QUEUED", "FAULT_INJECTED", "CHECKPOINT_REACHED",
      "THRESHOLD_CROSSED", "BURN_IN_COMPLETE", "SENTINEL_INTERIM_SCREEN", "MEASUREMENTS_SENT",
      "SENTINEL_RESULT", "SENTINEL_FLAGGED", "DIAGNOSIS_COMPLETE", "SPICE_UNAVAILABLE",
      "SPICE_CROSSCHECK", "SPICE_CROSSCHECK_FAILED", "REPLACEMENT_SELECTED", "RERUN_COMPLETED",
      "GROUND_TRUTH_REVEALED", "HUMAN_DISPOSITION", "SIMULATION_FAILED", "SIMULATION_ERROR",
    ];
    for (const t of types) es.addEventListener(t, handle);
    return () => es.close();
  }, [sid]);

  return connected;
}

/** Linear interpolation of a sampled series at hour t (a drawing convenience). */
export function sampleAt(hours: number[], ys: (number | null)[] | null | undefined, t: number): number | null {
  if (!ys || !hours.length) return null;
  if (t <= hours[0]) return ys[0];
  for (let i = 1; i < hours.length; i++) {
    if (t <= hours[i]) {
      const a = ys[i - 1];
      const b = ys[i];
      if (a == null || b == null) return b ?? a;
      const f = (t - hours[i - 1]) / (hours[i] - hours[i - 1]);
      return a + f * (b - a);
    }
  }
  return ys[ys.length - 1];
}
