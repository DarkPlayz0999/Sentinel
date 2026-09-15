"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ScoreBands } from "@/components/charts/charts";
import {
  ChartNote, Led, Meter, Panel, PanelHead, SectionHead, SeverityTag, Stat,
  VerdictChip, num, pct,
} from "@/components/ui/kit";
import { histogram } from "@/lib/console";
import {
  ApiError, DEFAULT_API, Health, Preflight, REQUIRED_COLUMNS, ScreenResponse,
  ScreenVerdict, checkHealth, getApiBase, preflight, screenFile, setApiBase,
} from "@/lib/screen-api";
import { cn } from "@/lib/utils";

/* SCREEN — upload a burn-in data log and run the real screen over it.
 *
 * This is the only screen in the console that performs LIVE INFERENCE. The
 * file is posted to POST /screen in src/api.py, which calls the same
 * src/pipeline.py::screen() as the dashboard and src/report.py. Nothing is
 * scored in the browser.
 *
 * The page's job beyond "upload" is to make the integrity of the run legible:
 * which read points the frame carried, whether Module B could run, whether the
 * forecast was out-of-fold, and where the verdict bands landed for THIS
 * population rather than the shipped one. */

const SAMPLES = [
  {
    file: "burnin_two_lots_168h.csv",
    label: "Two lots · all read points",
    note: "700 components, 0/24/96/168 h. Two lots, so the forecast is out-of-fold.",
  },
  {
    file: "burnin_small_168h.csv",
    label: "Single lot · 60 components",
    note: "Fast round trip for a demo laptop. One lot, so the forecast is in-fold.",
  },
  {
    file: "burnin_hour24_triage.csv",
    label: "Hour-24 triage frame",
    note: "0 h and 24 h reads only. Module B and the 168 h sub-scores are unavailable.",
  },
];

function StatusDot({ state }: { state: "ok" | "down" | "checking" }) {
  return <Led tone={state === "ok" ? "green" : state === "down" ? "red" : "amber"} />;
}

export default function ScreenPage() {
  const [base, setBase] = useState(DEFAULT_API);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthState, setHealthState] = useState<"ok" | "down" | "checking">("checking");
  const [file, setFile] = useState<File | null>(null);
  const [pre, setPre] = useState<Preflight | null>(null);
  const [result, setResult] = useState<ScreenResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const [dragging, setDragging] = useState(false);
  const [filter, setFilter] = useState<"ALL" | "REJECT" | "WATCH" | "ACCEPT">("ALL");
  const [limit, setLimit] = useState(80);
  const [open, setOpen] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => setBase(getApiBase()), []);

  const ping = useCallback(async (b: string) => {
    setHealthState("checking");
    try {
      setHealth(await checkHealth(b));
      setHealthState("ok");
    } catch {
      setHealth(null);
      setHealthState("down");
    }
  }, []);

  useEffect(() => {
    if (base) void ping(base);
  }, [base, ping]);

  const accept = useCallback(async (f: File) => {
    setErr(null);
    setResult(null);
    setFile(f);
    setPre(null);
    try {
      setPre(await preflight(f));
    } catch {
      setPre({ ok: false, rows: 0, columns: [], missing: [], readPoints: [], error: "Could not read the file." });
    }
  }, []);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const f = e.dataTransfer.files?.[0];
      if (f) void accept(f);
    },
    [accept]
  );

  const run = useCallback(async () => {
    if (!file) return;
    setBusy(true);
    setErr(null);
    setResult(null);
    try {
      setResult(await screenFile(file, base));
      setLimit(80);
      setFilter("ALL");
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError(String(e)));
    } finally {
      setBusy(false);
    }
  }, [file, base]);

  const loadSample = useCallback(
    async (name: string) => {
      setErr(null);
      try {
        const r = await fetch(`/samples/${name}`);
        if (!r.ok) throw new Error(`sample ${r.status}`);
        const blob = await r.blob();
        await accept(new File([blob], name, { type: "text/csv" }));
      } catch {
        setErr(new ApiError(`Could not load the sample file ${name}.`));
      }
    },
    [accept]
  );

  const rows = useMemo(() => {
    if (!result) return [];
    const v = filter === "ALL" ? result.verdicts : result.verdicts.filter((x) => x.verdict === filter);
    return [...v].sort((a, b) => b.risk_score - a.risk_score);
  }, [result, filter]);

  const scoreBins = useMemo(
    () => (result ? histogram(result.verdicts.map((v) => v.risk_score), 0, 100, 44) : []),
    [result]
  );

  const isPdf = !!file && /\.pdf$/i.test(file.name);

  return (
    <div className="space-y-6">
      <SectionHead
        index="00"
        title="Screen a burn-in data log"
        note="live inference — the only screen in this console that is not a pre-computed export"
      />

      {/* ------------------------------------------------- service status */}
      <Panel className="flex flex-wrap items-end gap-x-5 gap-y-3 px-3 py-2.5">
        <div className="flex items-center gap-2">
          <StatusDot state={healthState} />
          <div>
            <div className="label">Screening service</div>
            <div
              className={cn(
                "readout text-[11px] font-semibold",
                healthState === "ok" ? "text-sig-green" : healthState === "down" ? "text-sig-red" : "text-sig-amber"
              )}
            >
              {healthState === "ok" ? "CONNECTED" : healthState === "down" ? "UNREACHABLE" : "CHECKING…"}
            </div>
          </div>
        </div>

        <label className="min-w-[210px] flex-1">
          <span className="label mb-1 block">Endpoint</span>
          <input
            value={base}
            onChange={(e) => setBase(e.target.value)}
            onBlur={() => setApiBase(base)}
            spellCheck={false}
            className="readout w-full border border-lab-rule bg-lab-card px-2 py-1.5 text-[11px] text-lab-ink outline-none focus:border-sig-blue"
          />
        </label>

        {health?.model_version && (
          <div>
            <div className="label">Model</div>
            <div className="readout text-[11px] text-lab-ink">{health.model_version}</div>
          </div>
        )}
        <button
          onClick={() => void ping(base)}
          className="border border-lab-rule bg-lab-card px-2.5 py-1.5 font-mono text-[9px] uppercase tracking-label text-lab-dim hover:bg-lab-panel"
        >
          Re-check
        </button>
      </Panel>

      {healthState === "down" && (
        <div className="panel border-l-[3px] border-l-sig-red px-4 py-3">
          <div className="font-mono text-[10px] font-bold uppercase tracking-label text-sig-red">
            Screening service not running
          </div>
          <p className="mt-1.5 font-mono text-[10px] leading-relaxed text-lab-dim">
            This page runs the real pipeline rather than a copy of it in the browser, so it needs
            the service. From the repository root:
          </p>
          <pre className="readout mt-2 overflow-x-auto border border-lab-rule bg-lab-panel px-3 py-2 text-[10.5px] text-lab-ink">
uvicorn src.api:app --port 8000
          </pre>
          <p className="mt-2 font-mono text-[9px] text-lab-faint">
            Every other console screen reads a pre-screened export and works without it.
          </p>
        </div>
      )}

      <div className="grid gap-px bg-lab-rule xl:grid-cols-[minmax(0,1fr)_minmax(0,400px)]">
        {/* ------------------------------------------------------ dropzone */}
        <div className="bg-lab-card p-4">
          <PanelHead title="Data log" meta="wide-format CSV, one row per component" className="-mx-4 -mt-4 mb-4 px-4" />

          <div
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            onClick={() => inputRef.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
            className={cn(
              "cursor-pointer border border-dashed px-4 py-8 text-center transition-colors",
              dragging ? "border-sig-blue bg-sig-blue/[0.05]" : "border-lab-rule bg-lab-panel hover:bg-lab-sunk"
            )}
          >
            <input
              ref={inputRef}
              type="file"
              accept=".csv,text/csv,.txt"
              className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) void accept(f); }}
            />
            <div className="font-mono text-[11px] font-semibold uppercase tracking-label text-lab-ink">
              Drop a CSV data log here
            </div>
            <div className="mt-1.5 font-mono text-[9.5px] text-lab-faint">
              or click to choose a file · nothing is uploaded until you run the screen
            </div>
          </div>

          {file && (
            <div className="mt-3 border border-lab-rule bg-lab-panel px-3 py-2.5">
              <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                <span className="readout text-[11px] font-semibold text-lab-ink">{file.name}</span>
                <span className="font-mono text-[9px] text-lab-faint">
                  {(file.size / 1024).toFixed(0)} KB
                  {pre ? ` · ${pre.rows.toLocaleString()} components · ${pre.columns.length} columns` : ""}
                </span>
                <button
                  onClick={(e) => { e.stopPropagation(); setFile(null); setPre(null); setResult(null); setErr(null); }}
                  className="ml-auto font-mono text-[9px] uppercase tracking-label text-lab-dim hover:text-sig-red"
                >
                  Clear
                </button>
              </div>

              {isPdf && (
                <p className="mt-2 border-l-[3px] border-l-sig-red bg-sig-red/[0.05] px-2.5 py-2 font-mono text-[9.5px] leading-relaxed text-lab-ink">
                  <span className="font-bold text-sig-red">PDF is not a measurement format.</span>{" "}
                  The screen needs numeric parametric readings per component per read point. Export
                  the data log from your ATE as CSV — that is what every tester emits — and upload
                  that instead.
                </p>
              )}

              {pre && !isPdf && (
                <div className="mt-2">
                  {pre.error ? (
                    <p className="font-mono text-[9.5px] text-sig-red">{pre.error}</p>
                  ) : pre.ok ? (
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                      <span className="font-mono text-[9.5px] font-bold text-sig-green">
                        ✓ Required columns present
                      </span>
                      <span className="font-mono text-[9.5px] text-lab-dim">
                        read points: {pre.readPoints.map((t) => `${t}h`).join(" · ")}
                      </span>
                      {!pre.readPoints.includes(168) && (
                        <span className="font-mono text-[9.5px] text-sig-amber">
                          hour-24 frame — Module B will be skipped
                        </span>
                      )}
                    </div>
                  ) : (
                    <div>
                      <div className="font-mono text-[9.5px] font-bold text-sig-red">
                        Missing required columns
                      </div>
                      <div className="readout mt-1 break-words font-mono text-[9.5px] text-lab-dim">
                        {pre.missing.join(", ")}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          <div className="mt-3 flex flex-wrap items-center gap-2.5">
            <button
              onClick={() => void run()}
              disabled={!file || busy || healthState !== "ok" || isPdf || (pre ? !pre.ok : false)}
              className="border border-lab-ink bg-lab-ink px-4 py-2 font-mono text-[11px] uppercase tracking-label text-lab-panel transition-opacity hover:opacity-85 disabled:cursor-not-allowed disabled:opacity-35"
            >
              {busy ? "Screening…" : "Run screen"}
            </button>
            {busy && (
              <span className="flex items-center gap-2">
                <Led tone="amber" />
                <span className="font-mono text-[9.5px] text-lab-dim">
                  Fitting the forecaster and fusing sub-scores — a few seconds per lot.
                </span>
              </span>
            )}
          </div>

          {err && (
            <div className="mt-3 border-l-[3px] border-l-sig-red bg-sig-red/[0.05] px-3 py-2.5">
              <div className="font-mono text-[10px] font-bold uppercase tracking-label text-sig-red">
                Screen failed{err.status ? ` · HTTP ${err.status}` : ""}
              </div>
              <p className="readout mt-1.5 break-words text-[10.5px] leading-relaxed text-lab-ink">
                {err.message}
              </p>
              {err.hint && (
                <p className="mt-1.5 font-mono text-[9.5px] leading-relaxed text-lab-faint">{err.hint}</p>
              )}
            </div>
          )}
        </div>

        {/* -------------------------------------------------- format + samples */}
        <div className="bg-lab-card p-4">
          <PanelHead title="Expected format" className="-mx-4 -mt-4 mb-3 px-4" />
          <p className="font-mono text-[9.5px] leading-relaxed text-lab-dim">
            One row per component. Columns are <code>{"{PARAMETER}_{HOURS}h"}</code> — the shape
            every ATE data-log exports.
          </p>
          <div className="mt-2.5 overflow-x-auto border border-lab-rule bg-lab-panel px-3 py-2">
            <code className="readout whitespace-pre text-[9.5px] leading-relaxed text-lab-ink">
              {`serial,lot,Iddq_uA_0h,Iddq_uA_24h,…\nL04-0348,L04,21.9368,24.4758,…`}
            </code>
          </div>

          <div className="mt-3">
            <div className="label mb-1.5">Required</div>
            <div className="flex flex-wrap gap-1">
              {REQUIRED_COLUMNS.map((c) => (
                <span key={c} className="readout border border-lab-rule bg-lab-panel px-1.5 py-[2px] text-[9px] text-lab-dim">
                  {c}
                </span>
              ))}
            </div>
            <p className="mt-2 font-mono text-[9px] leading-relaxed text-lab-faint">
              <code>_96h</code> and <code>_168h</code> are optional. Without <code>_168h</code>{" "}
              the frame is an hour-24 triage run: Module B and the 168 h sub-scores are
              unavailable and their weight is redistributed rather than scored as zero.
            </p>
          </div>

          <div className="mt-4">
            <div className="label mb-1.5">Sample data logs</div>
            <ul className="space-y-1.5">
              {SAMPLES.map((s) => (
                <li key={s.file} className="border border-lab-rule bg-lab-panel px-2.5 py-2">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <button
                      onClick={() => void loadSample(s.file)}
                      className="font-mono text-[10px] font-semibold text-sig-blue hover:underline"
                    >
                      {s.label}
                    </button>
                    <a
                      href={`/samples/${s.file}`}
                      download
                      className="ml-auto font-mono text-[9px] uppercase tracking-label text-lab-dim hover:text-lab-ink"
                    >
                      ↓ CSV
                    </a>
                  </div>
                  <p className="mt-1 font-mono text-[8.5px] leading-tight text-lab-faint">{s.note}</p>
                </li>
              ))}
            </ul>
            <p className="mt-2 font-mono text-[8.5px] leading-relaxed text-lab-faint">
              Cut from the committed dataset with the label columns stripped, so they are the same
              shape as a real data log. Regenerated by{" "}
              <code>python web/scripts/export_lab_data.py</code>.
            </p>
          </div>
        </div>
      </div>

      {/* ============================================================ result */}
      {result && (
        <>
          <SectionHead
            index="00·R"
            title="Screening result"
            note={`${result.parts.toLocaleString()} components · ${result.model_version} · ${result.generated_utc}`}
          />

          {/* integrity banner - how these numbers must be read */}
          <div className="panel border-l-[3px] border-l-sig-blue px-4 py-3">
            <div className="font-mono text-[10px] font-bold uppercase tracking-label text-lab-ink">
              Run integrity
            </div>
            <ul className="mt-2 space-y-1.5">
              <li className="font-mono text-[9.5px] leading-relaxed text-lab-dim">
                <span className="font-bold text-lab-ink">Read points:</span>{" "}
                {result.read_points.map((t) => `${t}h`).join(" · ")}
                {!result.module_b_available && (
                  <span className="text-sig-amber">
                    {" "}— no 168 h column, so Module B was skipped and the predicted-drift,
                    static-margin and multivariate sub-scores are unavailable. Their weight is
                    redistributed across what remains.
                  </span>
                )}
              </li>
              <li className="font-mono text-[9.5px] leading-relaxed text-lab-dim">
                <span className="font-bold text-lab-ink">Forecast validation:</span>{" "}
                {result.forecast_out_of_fold ? (
                  <span className="text-sig-green">
                    out-of-fold — {result.lots_in_frame} lots, so every component was forecast by a
                    model that never saw its own lot. A reported MAE from this run would be valid.
                  </span>
                ) : (
                  <span className="text-sig-amber">
                    in-fold — this frame has {result.lots_in_frame} lot
                    {result.lots_in_frame === 1 ? "" : "s"}, so GroupKFold had nothing to hold out
                    and the forecaster was fitted on the frame it predicts. Valid for screening,{" "}
                    <strong>not valid for quoting a forecast accuracy</strong>.
                  </span>
                )}
              </li>
              <li className="font-mono text-[9.5px] leading-relaxed text-lab-dim">
                <span className="font-bold text-lab-ink">Verdict bands:</span> WATCH ≥{" "}
                {num(result.bands.watch, 1)} · REJECT ≥ {num(result.bands.reject, 1)} — recomputed
                for <em>this</em> population against the 5% PDA budget, so they will not match the
                shipped dataset&rsquo;s bands.
              </li>
            </ul>
          </div>

          <div className="grid grid-cols-2 gap-px bg-lab-rule sm:grid-cols-3 lg:grid-cols-6">
            <Stat k="Components" v={result.parts.toLocaleString()} />
            <Stat k="Accept" v={result.summary.ACCEPT ?? 0} tone="text-sig-green" />
            <Stat k="Watch" v={result.summary.WATCH ?? 0} tone="text-sig-amber" />
            <Stat k="Reject" v={result.summary.REJECT ?? 0} tone="text-sig-red" />
            <Stat k="Lots" v={result.lots_in_frame} />
            <Stat
              k="Lots over PDA"
              v={`${result.lots.filter((l) => l.status !== "OK").length} / ${result.lots.length}`}
              tone={result.lots.some((l) => l.status !== "OK") ? "text-sig-red" : "text-sig-green"}
            />
          </div>

          <div className="grid gap-px bg-lab-rule lg:grid-cols-[minmax(0,1fr)_minmax(0,460px)]">
            <Panel className="border-0 p-4">
              <PanelHead title="Risk score distribution" meta="bands placed on this population" className="-mx-4 -mt-4 mb-3 px-4" />
              <ScoreBands bins={scoreBins} watch={result.bands.watch} reject={result.bands.reject} />
              <ChartNote>
                Only REJECT consumes PDA budget. WATCH components ship with the serial flagged.
              </ChartNote>
            </Panel>

            <Panel className="overflow-x-auto border-0">
              <PanelHead title="Lot disposition" />
              <table className="w-full min-w-[380px] border-collapse">
                <thead>
                  <tr className="border-b border-lab-rule bg-lab-panel">
                    {["Lot", "Parts", "Watch", "Reject", "Reject %", "PDA"].map((h) => (
                      <th key={h} className="px-2.5 py-2 text-left font-mono text-[9px] uppercase tracking-label text-lab-faint">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.lots.map((l) => (
                    <tr key={l.lot} className="border-b border-lab-hair">
                      <td className="readout px-2.5 py-1.5 text-[11px] font-semibold">{l.lot}</td>
                      <td className="readout px-2.5 py-1.5 text-[10px]">{l.parts}</td>
                      <td className="readout px-2.5 py-1.5 text-[10px] text-sig-amber">{l.watch}</td>
                      <td className="readout px-2.5 py-1.5 text-[10px] text-sig-red">{l.reject}</td>
                      <td className="readout px-2.5 py-1.5 text-[10px]">{pct(l.reject_frac, 1)}</td>
                      <td className="px-2.5 py-1.5">
                        <span className={cn(
                          "font-mono text-[9px] font-bold uppercase tracking-label",
                          l.status === "OK" ? "text-sig-green" : "text-sig-red"
                        )}>
                          {l.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          </div>

          {/* ------------------------------------------------- verdict table */}
          <Panel className="overflow-x-auto">
            <PanelHead
              title="Component verdicts"
              meta="highest risk first · click a row for its reason codes"
              right={
                <span className="flex gap-1">
                  {(["ALL", "REJECT", "WATCH", "ACCEPT"] as const).map((f) => (
                    <button
                      key={f}
                      onClick={() => { setFilter(f); setLimit(80); }}
                      className={cn(
                        "border px-2 py-[3px] font-mono text-[9px] uppercase tracking-label transition-colors",
                        filter === f
                          ? "border-lab-ink bg-lab-ink text-lab-panel"
                          : "border-lab-rule bg-lab-card text-lab-dim hover:bg-lab-panel"
                      )}
                    >
                      {f}
                    </button>
                  ))}
                </span>
              }
            />
            <table className="w-full min-w-[760px] border-collapse">
              <thead>
                <tr className="border-b border-lab-rule bg-lab-panel">
                  {["Component", "Lot", "Risk", "Static margin", "Dynamic", "Pred. drift", "Multivariate", "Codes", "Decision"].map((h) => (
                    <th key={h} className="px-2.5 py-2 text-left font-mono text-[9px] uppercase tracking-label text-lab-faint">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, limit).map((v) => (
                  <VerdictRow key={v.serial} v={v} open={open === v.serial} onToggle={() => setOpen(open === v.serial ? null : v.serial)} />
                ))}
              </tbody>
            </table>
            {rows.length > limit && (
              <div className="border-t border-lab-hair px-3 py-2.5 text-center">
                <button
                  onClick={() => setLimit((l) => l + 200)}
                  className="border border-lab-rule bg-lab-card px-3 py-1.5 font-mono text-[10px] uppercase tracking-label text-lab-ink hover:bg-lab-panel"
                >
                  Show 200 more — {(rows.length - limit).toLocaleString()} remaining
                </button>
              </div>
            )}
          </Panel>

          <p className="font-mono text-[9px] leading-relaxed text-lab-faint">
            <span className="font-bold text-lab-dim">Live inference.</span> These verdicts were
            produced by <code>POST /screen</code> on the uploaded file — the same{" "}
            <code>src/pipeline.py::screen()</code> behind the dashboard and{" "}
            <code>src/report.py</code>. Nothing on this page was scored in the browser. Uploaded
            files are held in memory for the request and are not stored.
          </p>
        </>
      )}
    </div>
  );
}

/* One verdict row, expanding to its reason codes. */
function VerdictRow({ v, open, onToggle }: { v: ScreenVerdict; open: boolean; onToggle: () => void }) {
  const sub = (k: string) => v.sub_scores?.[k];
  return (
    <>
      <tr
        onClick={onToggle}
        className={cn("cursor-pointer border-b border-lab-hair hover:bg-lab-panel", open && "bg-lab-panel")}
      >
        <td className="readout px-2.5 py-[5px] text-[11px] font-semibold text-lab-ink">
          <span className="mr-1.5 text-lab-faint">{open ? "▾" : "▸"}</span>
          {v.serial}
        </td>
        <td className="readout px-2.5 py-[5px] text-[10px] text-lab-dim">{v.lot}</td>
        <td className="px-2.5 py-[5px]">
          <div className="flex items-center gap-2">
            <span className="readout w-8 text-[10px] font-semibold">{num(v.risk_score, 1)}</span>
            <span className="w-[68px]">
              <Meter
                value={v.risk_score}
                max={100}
                height={4}
                color={v.verdict === "REJECT" ? "#A81E12" : v.verdict === "WATCH" ? "#9A5B06" : "#186B45"}
              />
            </span>
          </div>
        </td>
        {["static_margin", "dynamic_outlier", "predicted_drift", "multivariate"].map((k) => (
          <td key={k} className="readout px-2.5 py-[5px] text-[10px] text-lab-dim">
            {num(sub(k), 1)}
          </td>
        ))}
        <td className="readout px-2.5 py-[5px] text-[10px]">
          {v.reason_codes.length ? (
            <span className="font-semibold text-sig-red">{v.reason_codes.length}</span>
          ) : (
            <span className="text-lab-faint">—</span>
          )}
        </td>
        <td className="px-2.5 py-[5px]">
          <VerdictChip v={v.verdict} />
        </td>
      </tr>
      {open && (
        <tr className="border-b border-lab-hair bg-lab-panel">
          <td colSpan={9} className="px-4 py-3">
            {v.reason_codes.length === 0 ? (
              <p className="font-mono text-[10px] text-lab-dim">
                No reason code fired — every rule threshold is above this component&rsquo;s values.
              </p>
            ) : (
              <ul className="space-y-2">
                {v.reason_codes.map((c, i) => (
                  <li key={`${c.code}-${i}`} className="border border-lab-rule bg-lab-card px-3 py-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="readout border border-lab-ink bg-lab-ink px-1.5 py-[2px] text-[9.5px] font-bold text-lab-panel">
                        {c.code}
                      </span>
                      <SeverityTag s={c.severity} />
                      <span className="font-mono text-[8.5px] text-lab-faint">
                        {c.contributing_feature} · observed {num(c.feature_value, 3)} · lot reference{" "}
                        {num(c.lot_reference_value, 3)}
                      </span>
                    </div>
                    <p className="mt-1.5 text-[11.5px] leading-relaxed text-lab-ink">{c.message}</p>
                  </li>
                ))}
              </ul>
            )}
          </td>
        </tr>
      )}
    </>
  );
}
