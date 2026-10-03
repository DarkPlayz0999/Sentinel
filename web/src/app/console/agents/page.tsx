"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Card, CardHead, Notice, PageHead, Stamp } from "@/components/ui/kit";
import { AiSummary } from "@/components/ai/ai-summary";
import {
  AgentEvent, AgentName, AgentStatus, Dataset, Step, Workflow, WorkflowDetail, agentsApi,
  useAgentEvents,
} from "@/lib/agents-api";
import { getApiBase } from "@/lib/screen-api";
import { C } from "@/lib/theme";
import { cn } from "@/lib/utils";

/* AGENT OPERATIONS - what the agent team is doing, straight from the database.
 *
 * Every figure here is read from /v1/agents/*. Live updates arrive over SSE and
 * trigger a re-read; the stream never carries numbers the tables don't hold.
 * Agents flag and record. Release is a human decision and has no button here. */

const PIPELINE: { key: AgentName; label: string; role: string }[] = [
  { key: "data_quality", label: "Data Quality", role: "schema · units · hash · provenance" },
  { key: "anomaly", label: "Anomaly", role: "Module A · lot-relative outliers" },
  { key: "forecast", label: "Forecast", role: "Module B · 168 h from 0 h + 24 h" },
  { key: "combine", label: "Combine", role: "fusion · verdicts · PDA · persist" },
];

const INVESTIGATION: { key: AgentName; label: string; role: string }[] = [
  { key: "diagnostic", label: "Diagnostic", role: "fault dictionary · IR map · neighbours" },
  { key: "root_cause", label: "Root cause", role: "ranked hypotheses · evidence scores" },
  { key: "qa_safety", label: "QA / Safety", role: "limits · uncertainty · conflicts" },
  { key: "report", label: "Report", role: "investigation record · human review" },
  { key: "explainer", label: "Explainer (AI)", role: "plain language · numbers checked" },
];

const STATUS_COLOR: Record<string, string> = {
  COMPLETED: C.pass, RUNNING: C.cobalt, QUEUED: C.mute, FAILED: C.reject,
  QUARANTINED: C.watch,
};
const SEVERITY_COLOR: Record<string, string> = {
  critical: C.reject, error: C.reject, warning: C.watch, info: C.cobalt,
};

function Pill({ s }: { s: string }) {
  const color = STATUS_COLOR[s] ?? C.mute;
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-bold" style={{ color }}>
      <span className={cn("h-2 w-2 rounded-full", s === "RUNNING" && "animate-pulse")} style={{ background: color }} />
      {s}
    </span>
  );
}

const secs = (v: number | null | undefined) => (v == null ? "—" : `${v.toFixed(v < 10 ? 2 : 1)} s`);

function lastStep(steps: Step[], agent: AgentName) {
  return [...steps].reverse().find((s) => s.agent === agent);
}

/** DQ -> (Anomaly || Forecast) -> Combine, each node coloured by its real step. */
function Pipeline({ wf }: { wf: WorkflowDetail }) {
  const node = (key: AgentName, label: string, role: string) => {
    const st = lastStep(wf.steps, key);
    const status = st?.status ?? (wf.status === "QUARANTINED" && key !== "data_quality" ? "SKIPPED" : "PENDING");
    const color = STATUS_COLOR[status] ?? C.rule;
    return (
      <div className="min-w-0 flex-1 rounded-card border-2 bg-sheet px-3 py-2" style={{ borderColor: color }}>
        <div className="flex flex-wrap items-baseline justify-between gap-x-2">
          <span className="text-sm font-bold">{label}</span>
          <span className="text-xs font-bold" style={{ color }}>{status}</span>
        </div>
        <div className="mt-0.5 text-xs text-graphite">{role}</div>
        <div className="mt-1 font-mono text-xs text-graphite">
          {st ? `${secs(st.duration_s)} · attempt ${st.attempt}` : "not run"}
        </div>
        {st?.error && <div className="mt-1 text-xs text-reject">{st.error}</div>}
      </div>
    );
  };
  const arrow = <div className="self-center px-1 text-graphite" aria-hidden>→</div>;
  if (wf.trigger === "sentinel_alert") {
    // The investigation team: runs only after Sentinel flags a board. Numbered
    // rather than arrowed so five steps wrap cleanly in a narrow column.
    return (
      <ol className="grid gap-2 sm:grid-cols-2 2xl:grid-cols-5">
        {INVESTIGATION.map((a, i) => (
          <li key={a.key} className="flex min-w-0">
            {node(a.key, `${i + 1}. ${a.label}`, a.role)}
          </li>
        ))}
      </ol>
    );
  }
  return (
    <div className="flex flex-col gap-2 lg:flex-row">
      {node("data_quality", PIPELINE[0].label, PIPELINE[0].role)}
      {arrow}
      <div className="flex flex-1 flex-col gap-2">
        {node("anomaly", PIPELINE[1].label, PIPELINE[1].role)}
        {node("forecast", PIPELINE[2].label, PIPELINE[2].role)}
      </div>
      {arrow}
      {wf.status === "QUARANTINED"
        ? node("quarantine", "Quarantine", "data held · nothing downstream ran")
        : node("combine", PIPELINE[3].label, PIPELINE[3].role)}
    </div>
  );
}

/** One readable line per stream event; the raw payload stays one click away. */
function describeEvent(e: AgentEvent): string {
  const p = e.payload as Record<string, unknown>;
  if (e.kind === "step") {
    const d = typeof p.duration_s === "number" ? ` in ${secs(p.duration_s as number)}` : "";
    const a = p.attempt ? ` (attempt ${p.attempt})` : "";
    return `${String(p.agent)} ${String(p.status).toLowerCase()}${d}${a}${p.error ? ` - ${String(p.error)}` : ""}`;
  }
  if (e.kind === "finding") return `${String(p.agent)} recorded ${String(p.count)} finding${p.count === 1 ? "" : "s"}`;
  if (p.status) {
    const trig = p.trigger ? ` (${String(p.trigger)})` : "";
    const d = typeof p.duration_s === "number" ? ` in ${secs(p.duration_s as number)}` : "";
    return `workflow ${String(p.status).toLowerCase()}${trig}${d}`;
  }
  const keys = Object.keys(p);
  return keys.includes("run_id") ? `workflow linked to run ${String(p.run_id)}`
    : keys.includes("current_step") ? `workflow now at ${String(p.current_step ?? "end")}`
    : `workflow updated (${keys.join(", ")})`;
}

function Summary({ wf }: { wf: WorkflowDetail }) {
  const s = wf.summary;
  if (!s) return null;
  const cells: [string, string][] = [];
  if (s.data_quality) cells.push(["Rows / lots", `${s.data_quality.rows} / ${s.data_quality.lots}`],
    ["Data class", s.data_quality.data_class], ["Hash verified", s.data_quality.hash_verified ? "yes" : "NO"]);
  if (s.anomaly) cells.push(["Static breaches", String(s.anomaly.static_breaches)],
    ["L3 over threshold", String(s.anomaly.l3_over_threshold ?? "—")]);
  if (s.forecast) cells.push(["Reject at 24 h (R-301)", String(s.forecast.reject_at_24h)],
    ["Forecast out-of-fold", s.forecast.out_of_fold ? "yes" : "no"]);
  if (s.result) cells.push(...Object.entries(s.result.verdicts).map(([k, v]) => [k, String(v)] as [string, string]),
    ["Lots over PDA", s.result.lots_over_pda.join(", ") || "none"]);
  return (
    <div className="grid grid-cols-2 border-l border-t border-hair sm:grid-cols-3 lg:grid-cols-5">
      {cells.map(([k, v]) => (
        <div key={k} className="border-b border-r border-hair px-3 py-2">
          <div className="text-xs text-graphite">{k}</div>
          <div className="mt-0.5 font-mono text-sm font-semibold">{v}</div>
        </div>
      ))}
    </div>
  );
}

export default function AgentsPage() {
  const [status, setStatus] = useState<AgentStatus | null>(null);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [selected, setSelected] = useState<string | null>(() =>
    typeof window === "undefined" ? null : new URLSearchParams(window.location.search).get("wf"));
  const [detail, setDetail] = useState<WorkflowDetail | null>(null);
  const [dataset, setDataset] = useState("");
  const [error, setError] = useState<string | null>(null);
  // Informational, and deliberately NOT cleared by a refresh: a message that
  // appears and vanishes on every re-read makes the page jump.
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [tick, setTick] = useState(0);            // bump to re-read the open workflow
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  /* Two separate jobs, on purpose.
   *
   * refreshList re-reads the status strip and the workflow list. It NEVER
   * changes which workflow is open, except to open the newest one when none
   * is. An earlier version also re-selected inside the refresh; a click on
   * "Run workflow" then left two refreshes in flight with different
   * selections, each undoing the other forever - hundreds of requests a
   * minute and a page flipping between two heights.
   *
   * The open workflow's detail is loaded by its own effect, keyed on the
   * selection, and a response for a workflow no longer selected is dropped. */
  const refreshList = useCallback(async () => {
    try {
      const [st, wfs] = await Promise.all([agentsApi.status(), agentsApi.workflows()]);
      setStatus(st);
      setWorkflows(wfs);
      setError(null);
      setSelected((cur) => cur ?? wfs[0]?.workflow_id ?? null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    refreshList();
  }, [refreshList]);

  useEffect(() => {
    if (!selected) return;
    let alive = true;
    agentsApi.workflow(selected)
      .then((d) => { if (alive) setDetail(d); })
      .catch((e) => { if (alive) setError((e as Error).message); });
    return () => { alive = false; };
  }, [selected, tick]);

  useEffect(() => {
    agentsApi.datasets().then((d) => {
      setDatasets(d);
      setDataset((cur) => cur || d[0]?.dataset_id || "");
    }).catch(() => undefined);
  }, []);

  // Coalesce bursts of events into one re-read of the list and the open workflow.
  const connected = useAgentEvents((e) => {
    setEvents((prev) => (prev.some((x) => x.id === e.id) ? prev : [e, ...prev].slice(0, 40)));
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      refreshList();
      setTick((t) => t + 1);
    }, 400);
  });

  const open = (id: string) => {
    setSelected(id);
    setNotice(null);
    window.history.replaceState(null, "", `?wf=${id}`);
  };

  const run = async () => {
    setBusy(true);
    setNotice(null);
    try {
      const r = await agentsApi.submit(dataset);
      open(r.workflow.workflow_id);
      if (r.deduplicated) {
        setNotice(`This dataset was already analysed with the same policy and model, so the existing workflow ${r.workflow.workflow_id} is shown instead of running it again.`);
      }
      await refreshList();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const resume = async (id: string) => {
    try {
      await agentsApi.resume(id);
      await refreshList();
      setTick((t) => t + 1);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div>
      <PageHead
        title="Agent operations"
        lede="The agent team, live from the screening service. Agents validate, detect, forecast and record; they never release or certify a component."
        right={
          <span className="flex items-center gap-2 text-sm text-graphite">
            <span className="h-2 w-2 rounded-full" style={{ background: connected ? C.pass : C.reject }} />
            {connected ? "Live stream connected" : "Stream disconnected"} · <code>{getApiBase()}</code>
          </span>
        }
      />

      {error && <Notice tone="warn" className="mb-5" title="Service message">{error}</Notice>}
      {notice && <Notice tone="info" className="mb-5" title="Already analysed">{notice}</Notice>}

      {/* agent status: both teams, each agent's most recent step */}
      {[
        { title: "Screening team", note: "runs on every batch Sentinel screens",
          agents: [...PIPELINE, { key: "quarantine" as AgentName, label: "Quarantine", role: "invalid data path" }] },
        { title: "Investigation team", note: "runs only when Sentinel flags a board",
          agents: INVESTIGATION },
      ].map((team) => (
        <section key={team.title} className="mb-5">
          <h2 className="mb-2 text-sm font-bold">
            {team.title} <span className="font-normal text-graphite">· {team.note}</span>
          </h2>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
            {team.agents.map((a) => {
              const st = status?.agents[a.key];
              return (
                <Card key={a.key} className="min-w-0 p-3">
                  <div className="text-sm font-bold">{a.label}</div>
                  <div className="text-xs text-graphite">{a.role}</div>
                  <div className="mt-2">{st ? <Pill s={st.status} /> : <span className="text-xs text-mute">no runs yet</span>}</div>
                  {st && (
                    <div className="mt-1 truncate font-mono text-xs text-graphite" title={st.completed_at ?? st.started_at}>
                      {secs(st.duration_s)} · {(st.completed_at ?? st.started_at).slice(11, 19)}
                    </div>
                  )}
                </Card>
              );
            })}
          </div>
        </section>
      ))}

      <div className="grid gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
        <div className="min-w-0 space-y-4">
          <Card>
            <CardHead title="Run the agent team" />
            <div className="space-y-3 p-4">
              <select
                className="w-full rounded-ctl border border-rule bg-sheet px-2 py-1.5 text-sm"
                value={dataset}
                onChange={(e) => setDataset(e.target.value)}
                aria-label="Dataset"
              >
                {datasets.length === 0 && <option value="">No datasets registered</option>}
                {datasets.map((d) => (
                  <option key={d.dataset_id} value={d.dataset_id}>
                    {d.filename} · {d.row_count} rows
                  </option>
                ))}
              </select>
              <button
                onClick={run}
                disabled={!dataset || busy}
                className="w-full rounded-ctl bg-ink px-3 py-2 text-sm font-bold text-sheet disabled:opacity-40"
              >
                {busy ? "Submitting…" : "Run workflow"}
              </button>
              <p className="text-xs text-graphite">Same dataset, policy and model returns the existing workflow (idempotent).</p>
            </div>
          </Card>

          <Card>
            <CardHead
              title="Workflows"
              meta={status && Object.entries(status.workflow_counts).map(([k, v]) => `${v} ${k.toLowerCase()}`).join(" · ")}
            />
            <ul className="max-h-[420px] divide-y divide-hair overflow-y-auto">
              {workflows.length === 0 && <li className="p-4 text-sm text-graphite">No workflows yet.</li>}
              {workflows.map((w) => (
                <li key={w.workflow_id}>
                  <button
                    onClick={() => open(w.workflow_id)}
                    className={cn("w-full px-4 py-2.5 text-left hover:bg-well", selected === w.workflow_id && "bg-well")}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-xs">{w.workflow_id}</span>
                      <Pill s={w.status} />
                    </div>
                    <div className="mt-0.5 text-xs text-graphite">
                      {w.trigger} · {w.created_at} · {secs(w.duration_s)}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
        </div>

        <div className="min-w-0 space-y-4">
          {detail ? (
            <>
              <Card>
                <CardHead
                  title={<span className="break-all font-mono">{detail.workflow_id}</span>}
                  meta={<span className="break-all">{`${detail.trigger} · dataset ${detail.dataset_id}${detail.run_id ? ` · run ${detail.run_id}` : ""}`}</span>}
                  right={
                    detail.status === "FAILED" ? (
                      <button onClick={() => resume(detail.workflow_id)} className="rounded-ctl border border-ink px-2.5 py-1 text-xs font-bold">
                        Resume from checkpoint
                      </button>
                    ) : <Pill s={detail.status} />
                  }
                />
                <div className="space-y-4 p-4">
                  <AiSummary subject={{ context: "workflow", id: detail.workflow_id }} watch={detail.status}
                    title="What the agents did, in plain language" compact />
                  <Pipeline wf={detail} />
                  {detail.error && <Notice tone="danger" title="Workflow failed">{detail.error}</Notice>}
                  {detail.summary?.result?.human_review_required && (
                    <Notice tone="warn" title="Human review required">
                      Flagged parts await QA/MRB disposition. No component has been released.{" "}
                      {Object.entries(detail.summary.result.verdicts).map(([k, v]) => (
                        <span key={k} className="mr-2 inline-flex items-center gap-1"><Stamp v={k as "ACCEPT"} /> {v}</span>
                      ))}
                    </Notice>
                  )}
                  <Summary wf={detail} />
                </div>
              </Card>

              <Card>
                <CardHead title="Findings" meta={`${detail.findings.length} recorded`} />
                <ul className="divide-y divide-hair">
                  {detail.findings.length === 0 && <li className="p-4 text-sm text-graphite">No findings.</li>}
                  {detail.findings.map((f) => (
                    <li key={f.finding_id} className="flex flex-wrap gap-x-3 gap-y-1 px-4 py-2.5 sm:flex-nowrap">
                      <span className="w-16 shrink-0 text-xs font-bold uppercase" style={{ color: SEVERITY_COLOR[f.severity] }}>{f.severity}</span>
                      <span className="w-24 shrink-0 text-xs text-graphite">{f.agent}</span>
                      <span className="min-w-0 break-words text-sm">
                        <code className="mr-2 text-xs">{f.code}</code>{f.message}
                      </span>
                    </li>
                  ))}
                </ul>
              </Card>
            </>
          ) : (
            <Card className="grid min-h-[240px] place-items-center p-8 text-sm text-graphite">
              {error ? "The agent service is not reachable. Start it with: uvicorn src.api:app --port 8000" : "Select or run a workflow."}
            </Card>
          )}

          <Card>
            <CardHead title="Live event stream" meta="from the agent_events table, newest first" />
            <ul className="max-h-[260px] divide-y divide-hair overflow-y-auto font-mono text-xs">
              {events.length === 0 && (
                <li className="p-4 text-graphite">
                  {connected ? "No agent activity yet. Run a workflow or a simulation and it appears here live." : "Connecting to the event stream…"}
                </li>
              )}
              {events.map((e) => (
                <li key={e.id} className="px-4 py-1.5">
                  <details>
                    <summary className="cursor-pointer list-none">
                      <span className="text-graphite">#{e.id} {e.at?.slice(11, 19)}</span>{" "}
                      <span className="font-bold">{describeEvent(e)}</span>{" "}
                      <span className="text-graphite">{e.workflow_id}</span>
                    </summary>
                    <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-ctl bg-well p-2 text-[11px]">
                      {JSON.stringify(e.payload, null, 2)}
                    </pre>
                  </details>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
}
