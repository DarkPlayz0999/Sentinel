"use client";

/**
 * Client for SENTINEL AI (/v1/ai). The model only WORDS what the screening
 * system computed: every answer carries its source (Mistral or the built-in
 * explainer), whether its numbers passed the check against the data, and the
 * exact facts it was built from.
 */

import { ApiError, getApiBase } from "@/lib/screen-api";

export type AiContext = "overview" | "lot" | "part" | "simulation" | "experiment" | "workflow" | "realdata";

export interface AiSubject {
  context: AiContext;
  id?: string | null;
  serial?: string | null;
  lot?: string | null;
}

export interface AiStatus {
  provider: string;
  model: string | null;
  enabled: boolean;
  data_leaves_machine: boolean;
  how_to_enable: string | null;
}

export interface AiText {
  kind: "summary" | "answer";
  context: AiContext | "investigation";
  subject: string;
  title: string;
  question: string | null;
  text: string;
  summary: string;
  next_steps: string[];
  source: "mistral" | "built-in";
  model: string | null;
  number_check: "passed" | "rejected" | "not needed";
  rejected_numbers: string[];
  note: string | null;
  facts: Record<string, unknown>;
  ai: AiStatus;
  generated_at: string;
  cached: boolean;
}

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
    throw new ApiError(`Cannot reach the SENTINEL service at ${base}.`, undefined,
      "Start it from the repository root:  uvicorn src.api:app --port 8000");
  }
  const json = await r.json().catch(() => null);
  if (!r.ok) throw new ApiError(json?.error?.message ?? `${path} returned ${r.status}`, r.status);
  return json as T;
}

const clean = (s: AiSubject) => ({
  context: s.context,
  id: s.id ?? undefined,
  serial: s.serial ?? undefined,
  lot: s.lot ?? undefined,
});

export const aiApi = {
  status: () => call<AiStatus>("GET", "/v1/ai/status"),
  summary: (s: AiSubject, refresh = false) =>
    call<AiText>("POST", "/v1/ai/summary", { ...clean(s), refresh }),
  ask: (s: AiSubject, question: string) =>
    call<AiText>("POST", "/v1/ai/ask", { ...clean(s), question }),
};
