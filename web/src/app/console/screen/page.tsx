"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ScoreBands } from "@/components/charts/charts";
import {
  Card, CardHead, Dot, Figure, Notice, PageHead, ReasonCode, Risk, SectionTitle, Stamp, Stat,
  StatRow, num, pct,
} from "@/components/ui/kit";
import { histogram } from "@/lib/console";
import {
  ApiError, DEFAULT_API, Health, Preflight, REQUIRED_COLUMNS, ScreenResponse,
  ScreenVerdict, checkHealth, getApiBase, preflight, screenFile, setApiBase,
} from "@/lib/screen-api";
import { C } from "@/lib/theme";
import { cn } from "@/lib/utils";

/* SCREEN - upload a burn-in data log and run the real screen over it.
 *
 * The only screen in the console that performs LIVE INFERENCE. The file is
 * posted to POST /screen, which calls the same src/pipeline.py::screen() as
 * the dashboard and src/report.py. Nothing is scored in the browser.
 *
 * Beyond "upload", the page's job is to make the integrity of the run legible:
 * which read points the frame carried, whether Module B could run, whether the
 * forecast was out-of-fold, and where the bands landed for THIS population. */

const SAMPLES = [
  { file: "burnin_two_lots_168h.csv", label: "Two lots, all read points",
    note: "700 parts at 0, 24, 96 and 168 h. Two lots, so the forecast is out-of-fold." },
  { file: "burnin_small_168h.csv", label: "One lot, 60 parts",
    note: "A fast round trip for a demo laptop. One lot, so the forecast is in-fold." },
  { file: "burnin_hour24_triage.csv", label: "Hour-24 triage frame",
    note: "0 h and 24 h reads only. Module B and the 168 h sub-scores are unavailable." },
];

type HealthState = "ok" | "down" | "checking";
const HEALTH = {
  ok: { c: C.pass, t: "Connected" },
  down: { c: C.reject, t: "Not reachable" },
  checking: { c: C.watch, t: "Checking" },
} as const;

export default function ScreenPage() {
  const [base, setBase] = useState(DEFAULT_API);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthState, setHealthState] = useState<HealthState>("checking");
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
      setPre({ ok: false, rows: 0, columns: [], missing: [], readPoints: [], error: "The file could not be read." });
    }
  }, []);

  const clear = () => { setFile(null); setPre(null); setResult(null); setErr(null); };

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

  const loadSample = useCallback(async (name: string) => {
    setErr(null);
    try {
      const r = await fetch(`/samples/${name}`);
      if (!r.ok) throw new Error(`sample ${r.status}`);
      await accept(new File([await r.blob()], name, { type: "text/csv" }));
    } catch {
      setErr(new ApiError(`The sample file ${name} could not be loaded.`));
    }
  }, [accept]);

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
  const canRun = !!file && !busy && healthState === "ok" && !isPdf && (pre ? pre.ok : true);
  const hs = HEALTH[healthState];

  return (
    <>
      <PageHead
        title="Screen a data log"
        lede="Upload a burn-in data log and run the real screen on it. This is live inference; every other screen in the console reads a pre-screened export."
      />

      {/* ------------------------------------------------- service status */}
      <Card className="mb-4 flex flex-wrap items-end gap-x-6 gap-y-3 px-4 py-3">
        <div>
          <div className="text-xs text-graphite">Screening service</div>
          <div className="mt-0.5 flex items-center gap-2 text-sm font-semibold" style={{ color: hs.c }}>
            <Dot color={hs.c} />
            {hs.t}
          </div>
        </div>
        <label className="min-w-[220px] flex-1">
          <span className="mb-1 block text-xs text-graphite">Service address</span>
          <input value={base} onChange={(e) => setBase(e.target.value)} onBlur={() => setApiBase(base)}
            spellCheck={false} className="input w-full" />
        </label>
        {health?.model_version && (
          <div>
            <div className="text-xs text-graphite">Model</div>
            <div className="mt-0.5 text-sm font-semibold">{health.model_version}</div>
          </div>
        )}
        <button onClick={() => void ping(base)} className="btn-quiet">Check again</button>
      </Card>

      {healthState === "down" && (
        <Notice tone="danger" title="The screening service is not running" className="mb-4">
          This page runs the real pipeline, not a copy of it in the browser, so it needs the
          service. Start it from the repository root with{" "}
          <code>uvicorn src.api:app --port 8000</code>, then check again. Every other console
          screen works without it.
        </Notice>
      )}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        {/* ------------------------------------------------------ dropzone */}
        <Card className="p-5">
          <h2 className="text-sm font-bold">Data log</h2>
          <p className="text-sm text-graphite">A CSV with one row per component.</p>

          <div
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              const f = e.dataTransfer.files?.[0];
              if (f) void accept(f);
            }}
            onClick={() => inputRef.current?.click()}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
            role="button"
            tabIndex={0}
            className={cn(
              "mt-4 cursor-pointer rounded-card border-2 border-dashed px-4 py-10 text-center transition-colors",
              dragging ? "border-cobalt bg-cobalt/[0.05]" : "border-rule bg-well hover:border-graphite"
            )}
          >
            <input ref={inputRef} type="file" accept=".csv,text/csv,.txt" className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) void accept(f); }} />
            <p className="text-base font-semibold">Drop a CSV here, or choose a file</p>
            <p className="mt-1 text-sm text-graphite">Nothing is uploaded until you run the screen.</p>
          </div>

          {file && (
            <div className="mt-4 rounded-card border border-rule px-4 py-3">
              <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                <span className="font-semibold">{file.name}</span>
                <span className="text-sm text-graphite">
                  {(file.size / 1024).toFixed(0)} KB
                  {pre && !pre.error ? `, ${pre.rows.toLocaleString()} components, ${pre.columns.length} columns` : ""}
                </span>
                <button onClick={clear} className="ml-auto text-sm text-graphite hover:text-reject">Remove</button>
              </div>

              {isPdf ? (
                <p className="mt-2 text-sm text-reject">
                  A PDF holds no measurements the screen can read. Export the data log from your
                  tester as CSV and upload that instead.
                </p>
              ) : pre?.error ? (
                <p className="mt-2 text-sm text-reject">{pre.error}</p>
              ) : pre?.ok ? (
                <p className="mt-2 text-sm">
                  <span className="font-semibold text-pass">All required columns present.</span>{" "}
                  <span className="text-graphite">Read points: {pre.readPoints.map((t) => `${t} h`).join(", ")}.</span>
                  {!pre.readPoints.includes(168) && (
                    <span className="text-watch"> No 168 h reads, so Module B will be skipped.</span>
                  )}
                </p>
              ) : pre ? (
                <p className="mt-2 text-sm text-reject">
                  Missing required columns: <span className="break-words">{pre.missing.join(", ")}</span>
                </p>
              ) : null}
            </div>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button onClick={() => void run()} disabled={!canRun} className="btn-primary px-5">
              {busy ? "Screening…" : "Run screen"}
            </button>
            {busy && (
              <span className="text-sm text-graphite">
                Fitting the forecaster and fusing sub-scores, a few seconds per lot.
              </span>
            )}
            {!busy && file && healthState !== "ok" && (
              <span className="text-sm text-graphite">Start the screening service to run this file.</span>
            )}
          </div>

          {err && (
            <Notice tone="danger" title={`Screen failed${err.status ? ` (HTTP ${err.status})` : ""}`} className="mt-4">
              <p className="break-words">{err.message}</p>
              {err.hint && <p className="mt-1 text-graphite">{err.hint}</p>}
            </Notice>
          )}
        </Card>

        {/* -------------------------------------------------- format + samples */}
        <Card className="p-5">
          <h2 className="text-sm font-bold">Try a sample log</h2>
          <ul className="mt-3 divide-y divide-hair">
            {SAMPLES.map((s) => (
              <li key={s.file} className="flex items-start justify-between gap-3 py-2.5">
                <div className="min-w-0">
                  <button onClick={() => void loadSample(s.file)} className="link text-left text-sm">{s.label}</button>
                  <p className="text-xs text-graphite">{s.note}</p>
                </div>
                <a href={`/samples/${s.file}`} download className="shrink-0 text-xs text-graphite hover:text-ink">
                  Download
                </a>
              </li>
            ))}
          </ul>

          <h2 className="mt-5 text-sm font-bold">Expected format</h2>
          <p className="mt-1 text-sm text-graphite">
            Columns are named <code>{"{PARAMETER}_{HOURS}h"}</code>, the shape every tester data log
            exports.
          </p>
          <pre className="mt-2 overflow-x-auto rounded-ctl bg-well px-3 py-2 font-mono text-xs leading-5">
{`serial,lot,Iddq_uA_0h,Iddq_uA_24h,…
L04-0348,L04,21.9368,24.4758,…`}
          </pre>
          <p className="mt-3 text-xs text-graphite">Required columns</p>
          <div className="mt-1 flex flex-wrap gap-1">
            {REQUIRED_COLUMNS.map((c) => <code key={c} className="text-xs">{c}</code>)}
          </div>
          <p className="mt-3 text-xs text-graphite">
            The 96 h and 168 h columns are optional. Without 168 h the frame is an hour-24 triage
            run: Module B and the 168 h sub-scores are unavailable, and their weight is
            redistributed instead of scored as zero.
          </p>
        </Card>
      </div>

      {/* ============================================================ result */}
      {result && (
        <>
          <SectionTitle
            title="Screening result"
            note={`${result.parts.toLocaleString()} components, ${result.model_version}, ${result.generated_utc}`}
          />

          <Notice tone="info" title="How to read this run" className="mb-4">
            <ul className="space-y-1.5">
              <li>
                <strong>Read points:</strong> {result.read_points.map((t) => `${t} h`).join(", ")}.
                {!result.module_b_available && (
                  <span className="text-watch"> There is no 168 h column, so Module B was skipped and the predicted-drift, static-margin and multivariate sub-scores are unavailable. Their weight is redistributed.</span>
                )}
              </li>
              <li>
                <strong>Forecast validation:</strong>{" "}
                {result.forecast_out_of_fold ? (
                  <span className="text-pass">
                    out-of-fold. With {result.lots_in_frame} lots, every part was forecast by a model
                    that never saw its lot, so an MAE from this run is valid.
                  </span>
                ) : (
                  <span className="text-watch">
                    in-fold. With {result.lots_in_frame} lot{result.lots_in_frame === 1 ? "" : "s"},
                    there was nothing to hold out, so the forecaster was fitted on the frame it
                    predicts. Valid for screening; not valid for quoting forecast accuracy.
                  </span>
                )}
              </li>
              <li>
                <strong>Bands:</strong> watch from {num(result.bands.watch, 1)}, reject from{" "}
                {num(result.bands.reject, 1)}. Recomputed for this population against the 5% PDA
                budget, so they will not match the shipped dataset.
              </li>
            </ul>
          </Notice>

          <StatRow className="grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
            <Stat k="Components" v={result.parts.toLocaleString()} />
            <Stat k="Accept" v={result.summary.ACCEPT ?? 0} tone="text-pass" />
            <Stat k="Watch" v={result.summary.WATCH ?? 0} tone="text-watch" />
            <Stat k="Reject" v={result.summary.REJECT ?? 0} tone="text-reject" />
            <Stat k="Lots" v={result.lots_in_frame} />
            <Stat
              k="Lots over the gate"
              v={`${result.lots.filter((l) => l.status !== "OK").length} of ${result.lots.length}`}
              tone={result.lots.some((l) => l.status !== "OK") ? "text-reject" : "text-pass"}
            />
          </StatRow>

          <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
            <Figure title="Risk score distribution" meta="bands placed on this population"
              note="Only reject consumes the PDA budget. Watch parts ship with the serial flagged.">
              <ScoreBands bins={scoreBins} watch={result.bands.watch} reject={result.bands.reject} />
            </Figure>
            <Card className="overflow-x-auto">
              <CardHead title="Lot disposition" />
              <table className="tbl min-w-[380px]">
                <thead>
                  <tr><th>Lot</th><th className="n">Parts</th><th className="n">Watch</th><th className="n">Reject</th><th className="n">Share</th><th>PDA gate</th></tr>
                </thead>
                <tbody>
                  {result.lots.map((l) => (
                    <tr key={l.lot}>
                      <td className="font-semibold">{l.lot}</td>
                      <td className="n">{l.parts}</td>
                      <td className="n text-watch">{l.watch}</td>
                      <td className="n text-reject">{l.reject}</td>
                      <td className="n">{pct(l.reject_frac, 1)}</td>
                      <td className={l.status === "OK" ? "text-pass" : "font-semibold text-reject"}>
                        {l.status === "OK" ? "Within" : "Review"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </div>

          {/* ------------------------------------------------- verdict table */}
          <Card className="mt-4 overflow-x-auto">
            <CardHead
              title="Component verdicts"
              meta="Highest risk first. Select a row for its reason codes."
              right={
                <div role="group" aria-label="Filter by decision" className="flex gap-1">
                  {(["ALL", "REJECT", "WATCH", "ACCEPT"] as const).map((f) => (
                    <button
                      key={f}
                      onClick={() => { setFilter(f); setLimit(80); }}
                      aria-pressed={filter === f}
                      className={cn("rounded-ctl px-2.5 py-1 text-xs font-semibold transition-colors",
                        filter === f ? "bg-ink text-sheet" : "text-graphite hover:bg-well")}
                    >
                      {f === "ALL" ? "All" : f[0] + f.slice(1).toLowerCase()}
                    </button>
                  ))}
                </div>
              }
            />
            <table className="tbl min-w-[800px]">
              <thead>
                <tr>
                  <th>Component</th><th>Lot</th><th>Risk</th>
                  <th className="n">Static margin</th><th className="n">Dynamic</th>
                  <th className="n">Predicted drift</th><th className="n">Multivariate</th>
                  <th className="n">Codes</th><th>Decision</th>
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, limit).map((v) => (
                  <VerdictRow key={v.serial} v={v} open={open === v.serial}
                    onToggle={() => setOpen(open === v.serial ? null : v.serial)} />
                ))}
              </tbody>
            </table>
            {rows.length > limit && (
              <div className="border-t border-hair px-4 py-3 text-center">
                <button onClick={() => setLimit((l) => l + 200)} className="btn-quiet">
                  Show 200 more ({(rows.length - limit).toLocaleString()} left)
                </button>
              </div>
            )}
          </Card>

          <p className="mt-3 max-w-prose text-xs text-mute">
            These verdicts came from <code>POST /screen</code> on the uploaded file, through the same{" "}
            <code>src/pipeline.py::screen()</code> behind the dashboard and <code>src/report.py</code>.
            Uploaded files are held in memory for the request and not stored.
          </p>
        </>
      )}
    </>
  );
}

/* One verdict row, expanding to its reason codes. */
function VerdictRow({ v, open, onToggle }: { v: ScreenVerdict; open: boolean; onToggle: () => void }) {
  return (
    <>
      <tr onClick={onToggle} className={cn("cursor-pointer", open && "bg-well")}>
        <td>
          <button onClick={(e) => { e.stopPropagation(); onToggle(); }} aria-expanded={open}
            className="font-semibold">
            <span aria-hidden className="mr-1.5 inline-block w-3 text-mute">{open ? "−" : "+"}</span>
            {v.serial}
          </button>
        </td>
        <td className="text-graphite">{v.lot}</td>
        <td><Risk r={v.risk_score} v={v.verdict} /></td>
        {["static_margin", "dynamic_outlier", "predicted_drift", "multivariate"].map((k) => (
          <td key={k} className="n text-graphite">{num(v.sub_scores?.[k], 1)}</td>
        ))}
        <td className={cn("n", v.reason_codes.length ? "font-semibold text-reject" : "text-mute")}>
          {v.reason_codes.length || "—"}
        </td>
        <td><Stamp v={v.verdict} /></td>
      </tr>
      {open && (
        <tr className="bg-well">
          <td colSpan={9} className="px-5 py-1">
            {v.reason_codes.length === 0 ? (
              <p className="py-3 text-sm text-graphite">
                No reason code fired: every rule threshold is above this component&rsquo;s values.
              </p>
            ) : (
              <ul className="divide-y divide-hair">
                {v.reason_codes.map((c, i) => (
                  <ReasonCode key={`${c.code}-${i}`} r={{
                    code: c.code, severity: c.severity, message: c.message,
                    feature: c.contributing_feature, value: c.feature_value, ref: c.lot_reference_value,
                  }} />
                ))}
              </ul>
            )}
          </td>
        </tr>
      )}
    </>
  );
}
