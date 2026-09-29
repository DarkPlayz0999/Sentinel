"use client";

/**
 * Client for the agent team (/v1/agents). Every value the Agent Operations
 * page shows comes from these endpoints, which read the database. When the
 * service is unreachable the page says so; it never fills in numbers.
 */

import { useEffect, useRef, useState } from "react";
import { ApiError, getApiBase } from "@/lib/screen-api";

export type WorkflowStatus = "QUEUED" | "RUNNING" | "COMPLETED" | "QUARANTINED" | "FAILED";
export type StepStatus = "RUNNING" | "COMPLETED" | "FAILED";
export type AgentName = "data_quality" | "anomaly" | "forecast" | "combine" | "quarantine";

export interface Workflow {
  workflow_id: string;
  trigger: string;
  dataset_id: string;
  data_class: string | null;
  run_id: string | null;
  status: WorkflowStatus;
  current_step: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  duration_s: number | null;
  error: string | null;
  actor: string | null;
  summary: {
    data_quality?: { valid: boolean; rows: number; lots: number; hash_verified: boolean; data_class: string };
    anomaly?: { parts: number; static_breaches: number; l2_over_6_sigma: number; l3_over_threshold: number | null };
    forecast?: { available: boolean; out_of_fold: boolean; reject_at_24h: number; model_artifact_id: string | null };
    result?: { run_id: string; verdicts: Record<string, number>; lots_over_pda: string[]; human_review_required: boolean };
  } | null;
}

export interface Step {
  step_id: string;
  agent: AgentName;
  status: StepStatus;
  attempt: number;
  started_at: string;
  completed_at: string | null;
  duration_s: number | null;
  error: string | null;
}

export interface Finding {
  finding_id: string;
  agent: AgentName;
  severity: "info" | "warning" | "error" | "critical";
  code: string;
  message: string;
  created_at: string;
}

export interface WorkflowDetail extends Workflow {
  steps: Step[];
  findings: Finding[];
}

export interface AgentStatus {
  workflow_counts: Partial<Record<WorkflowStatus, number>>;
  agents: Record<AgentName, (Omit<Step, "step_id" | "agent"> & { workflow_id: string }) | null>;
}

export interface Dataset {
  dataset_id: string;
  filename: string;
  row_count: number;
  source?: string;
}

export interface AgentEvent {
  id: number;
  workflow_id: string;
  kind: "workflow" | "step" | "finding";
  payload: Record<string, unknown>;
  at: string;
}

async function get<T>(path: string): Promise<T> {
  const base = getApiBase();
  let r: Response;
  try {
    r = await fetch(`${base}${path}`, { cache: "no-store" });
  } catch {
    throw new ApiError(`Cannot reach the screening service at ${base}.`);
  }
  if (!r.ok) throw new ApiError(`${path} returned ${r.status}`, r.status);
  return (await r.json()) as T;
}

async function post<T>(path: string): Promise<T> {
  const base = getApiBase();
  const r = await fetch(`${base}${path}`, { method: "POST" });
  const body = await r.json().catch(() => null);
  if (!r.ok) throw new ApiError(body?.error?.message ?? `${path} returned ${r.status}`, r.status);
  return body as T;
}

export const agentsApi = {
  status: () => get<AgentStatus>("/v1/agents/status"),
  workflows: () => get<Workflow[]>("/v1/agents/workflows?limit=50"),
  workflow: (id: string) => get<WorkflowDetail>(`/v1/agents/workflows/${id}`),
  datasets: () => get<Dataset[]>("/v1/datasets?limit=50"),
  submit: (datasetId: string) =>
    post<{ workflow: Workflow; deduplicated: boolean }>(
      `/v1/agents/workflows?dataset_id=${encodeURIComponent(datasetId)}`),
  resume: (id: string) => post<{ workflow: Workflow }>(`/v1/agents/workflows/${id}/resume`),
};

/** Subscribes to the SSE stream. `connected` reflects the real socket state. */
export function useAgentEvents(onEvent: (e: AgentEvent) => void) {
  const [connected, setConnected] = useState(false);
  const cb = useRef(onEvent);
  cb.current = onEvent;

  useEffect(() => {
    const es = new EventSource(`${getApiBase()}/v1/agents/events`);
    const handle = (m: MessageEvent) => {
      try {
        cb.current({ id: Number(m.lastEventId), ...JSON.parse(m.data) });
      } catch {
        /* malformed frame: ignore rather than render a guess */
      }
    };
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);   // EventSource reconnects on its own
    for (const k of ["workflow", "step", "finding"]) es.addEventListener(k, handle);
    return () => es.close();
  }, []);

  return connected;
}
