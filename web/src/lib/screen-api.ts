"use client";

/**
 * Client for the SENTINEL screening service (src/api.py).
 *
 * This is the ONE place in the web app that performs live inference. Everything
 * else renders a pre-screened export; this posts a CSV to POST /screen and the
 * verdicts come back from the same src/pipeline.py::screen() the dashboard and
 * src/report.py call.
 *
 * Deliberately NOT reimplemented in TypeScript. A second copy of the feature
 * logic in the browser would be a second definition of a feature (rule 8 of
 * CLAUDE.md) and the two would drift the first time a threshold moved. The
 * cost is that this page needs the API running; the page says so plainly when
 * it is not.
 */

export const DEFAULT_API = "http://localhost:8000";

const STORAGE_KEY = "sentinel.apiBase";

/** The operator can point the console at a different host; remembered locally. */
export function getApiBase(): string {
  if (typeof window === "undefined") return DEFAULT_API;
  try {
    return window.localStorage.getItem(STORAGE_KEY) || DEFAULT_API;
  } catch {
    return DEFAULT_API;
  }
}

export function setApiBase(url: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, url.replace(/\/+$/, ""));
  } catch {
    /* private window or blocked storage - the default still works */
  }
}

// ------------------------------------------------------------------ types
export interface ScreenVerdict {
  serial: string;
  lot: string;
  risk_score: number;
  verdict: "ACCEPT" | "WATCH" | "REJECT";
  sub_scores: Record<string, number>;
  reason_codes: {
    code: string;
    severity: string;
    message: string;
    contributing_feature: string;
    feature_value: number;
    lot_reference_value: number;
  }[];
  model_version: string;
  generated_utc: string;
}

export interface ScreenLot {
  lot: string;
  parts: number;
  reject: number;
  watch: number;
  reject_frac: number;
  pda_limit: number;
  status: string;
  mean_risk: number;
}

export interface ScreenResponse {
  model_version: string;
  generated_utc: string;
  parts: number;
  summary: Partial<Record<"ACCEPT" | "WATCH" | "REJECT", number>>;
  bands: { watch: number; reject: number };
  /** false when the forecaster was fitted on the frame it predicts */
  forecast_out_of_fold: boolean;
  module_b_available: boolean;
  lots_in_frame: number;
  read_points: number[];
  lots: ScreenLot[];
  verdicts: ScreenVerdict[];
}

export interface Health {
  status: string;
  model_version: string;
  simulated_data: boolean;
  dataset: { parts: number; lots: number } | null;
}

// ---------------------------------------------------------------- errors
export class ApiError extends Error {
  constructor(message: string, readonly status?: number, readonly hint?: string) {
    super(message);
    this.name = "ApiError";
  }
}

const OFFLINE_HINT =
  "Start the screening service from the repository root:  uvicorn src.api:app --port 8000";

export async function checkHealth(base = getApiBase()): Promise<Health> {
  try {
    const r = await fetch(`${base}/health`, { cache: "no-store" });
    if (!r.ok) throw new ApiError(`health ${r.status}`, r.status);
    return (await r.json()) as Health;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    throw new ApiError(`Cannot reach the screening service at ${base}.`, undefined, OFFLINE_HINT);
  }
}

/** POST the file to /screen. Rejects with a readable ApiError on any failure. */
export async function screenFile(file: File, base = getApiBase()): Promise<ScreenResponse> {
  const body = new FormData();
  body.append("file", file);

  let r: Response;
  try {
    r = await fetch(`${base}/screen`, { method: "POST", body });
  } catch {
    throw new ApiError(`Cannot reach the screening service at ${base}.`, undefined, OFFLINE_HINT);
  }

  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      if (j?.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* the body was not JSON; the status line is all we have */
    }
    throw new ApiError(
      detail,
      r.status,
      r.status === 422
        ? "The screen needs serial, lot, and the 0 h and 24 h reads for all four parameters."
        : undefined
    );
  }
  return (await r.json()) as ScreenResponse;
}

// ----------------------------------------------------------- file checks
export const REQUIRED_COLUMNS = [
  "serial",
  "lot",
  ...["Iddq_uA", "Ileak_nA", "Tpd_ns", "Vol_mV"].flatMap((p) => [`${p}_0h`, `${p}_24h`]),
];

export interface Preflight {
  ok: boolean;
  rows: number;
  columns: string[];
  missing: string[];
  readPoints: number[];
  error?: string;
}

/**
 * Read the header locally before uploading.
 *
 * Not a substitute for the server's validation - the server is the authority
 * and its 422 is rendered verbatim. This exists so an operator who dropped the
 * wrong file finds out in a millisecond instead of after a round trip, and so
 * the page can say which read points the frame contains before it is sent.
 */
export async function preflight(file: File): Promise<Preflight> {
  const head = await file.slice(0, 64 * 1024).text();
  const firstLine = head.split(/\r?\n/, 1)[0] ?? "";
  if (!firstLine.trim()) {
    return { ok: false, rows: 0, columns: [], missing: REQUIRED_COLUMNS, readPoints: [], error: "The file is empty." };
  }
  const columns = firstLine.split(",").map((c) => c.trim().replace(/^"|"$/g, ""));
  const missing = REQUIRED_COLUMNS.filter((c) => !columns.includes(c));
  const readPoints = [0, 24, 96, 168].filter((t) =>
    ["Iddq_uA", "Ileak_nA", "Tpd_ns", "Vol_mV"].every((p) => columns.includes(`${p}_${t}h`))
  );
  // Row count is exact for files we fully read, approximate for very large ones.
  const full = await file.text();
  const rows = full.split(/\r?\n/).filter((l) => l.trim()).length - 1;
  return { ok: missing.length === 0, rows, columns, missing, readPoints };
}
