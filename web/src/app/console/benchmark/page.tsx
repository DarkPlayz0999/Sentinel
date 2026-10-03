"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Card, CardHead, Notice, PageHead, num, pct } from "@/components/ui/kit";
import { BenchmarkView, Btn, Chip } from "@/components/twin/lab-panels";
import { AiSummary } from "@/components/ai/ai-summary";
import { Benchmark, Experiment, simApi } from "@/lib/sim-api";
import { ApiError } from "@/lib/screen-api";
import { C } from "@/lib/theme";
import { cn } from "@/lib/utils";

/* BLIND BENCHMARK - the only place simulator-based performance is claimed.
 *
 * Each campaign simulates many lots, gives Sentinel only the observed frame,
 * screens it at 24, 96 and 168 h, diagnoses the flags, and only then opens
 * the ground truth. Every metric is computed by src/evaluate.py. Plain
 * accuracy is never shown (CLAUDE.md rule 5), and every number is printed
 * with its operating point. */

const KINDS = [
  { k: "monte_carlo", t: "Monte Carlo campaign", d: "Every fault in the catalogue; noise, temperature, lot centring and spread drawn per lot." },
  { k: "esr_sweep", t: "Capacitor ESR sweep", d: "C001 ESR degradation from 0.2 to 2.0 Ω, soaked at 25, 85 and 125 °C." },
  { k: "ood", t: "Out-of-distribution suite", d: "Hotter soak, shifted lots, noisier tester, subtler faults, a different part variant, combined faults." },
] as const;

// Chamber temperature is an ordered magnitude: one hue, light -> dark.
const TEMP_RAMP = ["#9DC0DD", "#5B92BE", "#2A5C85"];

export default function BenchmarkPage() {
  const [list, setList] = useState<Experiment[]>([]);
  const [sel, setSel] = useState<Experiment | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [kind, setKind] = useState<string>("monte_carlo");
  const [runs, setRuns] = useState(20);
  const [seed, setSeed] = useState(42);
  const [boards, setBoards] = useState(200);
  const [rate, setRate] = useState(0.06);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const l = await simApi.experiments();
      setList(l);
      setErr(null);
      return l;
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
      return [];
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const active = list.some((e) => e.status === "RUNNING" || e.status === "QUEUED");
  useEffect(() => {
    if (!active) return;
    const h = setInterval(async () => {
      await load();
      if (sel) setSel(await simApi.experiment(sel.experiment_id).catch(() => sel));
    }, 2000);
    return () => clearInterval(h);
  }, [active, load, sel]);

  const open = async (id: string) => {
    window.history.replaceState(null, "", `?exp=${id}`);
    setSel(await simApi.experiment(id));
  };

  const run = async () => {
    setBusy(true);
    try {
      const e = await simApi.runExperiment({ kind, runs, seed, boards, fault_rate: rate });
      await load();
      setSel(e);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHead
        title="Blind benchmark"
        lede="Thousands of simulated boards, faults the screen cannot see, and a score computed only after Sentinel has committed. This page is the evidence behind any claim the digital twin makes about Sentinel."
        right={<Chip tone="copper">ACCELERATED SIMULATION TIME</Chip>}
      />
      {err && <Notice tone="danger" title="Service error" className="mb-4">{err}</Notice>}

      <div className="grid gap-6 lg:grid-cols-[340px_minmax(0,1fr)]">
        <div className="space-y-4">
          <Card>
            <CardHead title="New campaign" />
            <div className="space-y-3 p-4 text-sm">
              {KINDS.map((k) => (
                <button key={k.k} type="button" onClick={() => setKind(k.k)}
                  className={cn("block w-full rounded-ctl border px-3 py-2 text-left", kind === k.k ? "border-ink bg-ink text-sheet" : "border-rule")}>
                  <span className="block font-bold">{k.t}</span>
                  <span className="text-xs opacity-80">{k.d}</span>
                </button>
              ))}
              <label className="block text-xs text-graphite">Runs (lots): {runs}
                <input type="range" min={3} max={120} value={runs} onChange={(e) => setRuns(+e.target.value)} className="w-full accent-[#9C4F1F]" />
              </label>
              <label className="block text-xs text-graphite">Boards per lot: {boards}
                <input type="range" min={60} max={400} step={20} value={boards} onChange={(e) => setBoards(+e.target.value)} className="w-full accent-[#9C4F1F]" />
              </label>
              <label className="block text-xs text-graphite">Faulty boards per lot: {pct(rate, 0)}
                <input type="range" min={0.02} max={0.2} step={0.01} value={rate} onChange={(e) => setRate(+e.target.value)} className="w-full accent-[#9C4F1F]" />
              </label>
              <label className="block text-xs text-graphite">Seed
                <input type="number" value={seed} onChange={(e) => setSeed(+e.target.value)} className="mt-1 block w-28 rounded-ctl border border-rule px-2 py-1.5 text-sm text-ink" />
              </label>
              <Btn kind="copper" disabled={busy} onClick={run}>Run the campaign</Btn>
              <p className="text-xs text-graphite">
                Same numbers from the command line:{" "}
                <code className="break-all">python -m src.twin.experiments --kind {kind} --seed {seed} --runs {runs} --boards {boards}</code>
              </p>
            </div>
          </Card>

          <Card>
            <CardHead title="Campaigns" />
            <ul className="divide-y divide-hair">
              {list.length === 0 && <li className="px-4 py-3 text-sm text-graphite">None yet.</li>}
              {list.map((e) => (
                <li key={e.experiment_id}>
                  <button type="button" onClick={() => open(e.experiment_id)}
                    className={cn("w-full px-4 py-2.5 text-left text-sm hover:bg-well", sel?.experiment_id === e.experiment_id && "bg-well")}>
                    <div className="flex items-center justify-between gap-2">
                      <strong>{KINDS.find((k) => k.k === e.kind)?.t ?? e.kind}</strong>
                      <span className="text-xs font-bold text-graphite">{e.status}</span>
                    </div>
                    <div className="text-xs text-graphite">
                      seed {e.random_seed} · {e.runs} runs
                      {e.progress && e.status !== "COMPLETED" ? ` · ${e.progress.done}/${e.progress.total}` : ""}
                      {e.headline ? ` · recall ${pct(e.headline.recall)} · PR-AUC ${num(e.headline.pr_auc, 3)}` : ""}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
        </div>

        <div className="min-w-0 space-y-4">
          {!sel && (
            <Notice>Run a campaign or open one from the list. A 20-lot Monte Carlo campaign of 200 boards takes about a minute.</Notice>
          )}
          {sel && sel.status !== "COMPLETED" && (
            <Card>
              <CardHead title={`${sel.kind} · ${sel.status}`} />
              <div className="p-4 text-sm">
                {sel.progress ? `Run ${sel.progress.done} of ${sel.progress.total} (${sel.progress.cell})` : "Queued…"}
                {sel.error && <p className="mt-2 text-reject">{sel.error}</p>}
              </div>
            </Card>
          )}
          {sel?.summary && <Results e={sel} />}
        </div>
      </div>

      <p className="mt-10 max-w-prose text-xs text-mute">
        Simulated research benchmark: it measures Sentinel against the twin&apos;s own physics, not against flight
        hardware. In-distribution and out-of-distribution scores are reported side by side; a simulator that only
        reproduces its training distribution cannot demonstrate generalisation. Physical qualification remains separate.{" "}
        <Link href="/console/lab" className="underline underline-offset-2">Open the fault-injection lab →</Link>
      </p>
    </>
  );
}

function Results({ e }: { e: Experiment }) {
  const s = e.summary!;
  const cells = Object.entries(s.by_cell);
  return (
    <>
      <AiSummary subject={{ context: "experiment", id: e.experiment_id }} title="What this campaign shows, in plain language" />
      <Card>
        <CardHead title="Overall" meta={`${s.runs} lots · ${s.boards_scored.toLocaleString()} boards · ${s.duration_s} s`} />
        <div className="p-4">
          <p className="mb-3 text-xs text-graphite">Operating point: {s.operating_point}. Module B: {s.forecaster.note}.</p>
          <BenchmarkView b={s.overall} />
        </div>
      </Card>

      {e.kind === "esr_sweep" && <SweepChart cells={cells} />}
      {e.kind === "ood" && <OodChart cells={cells} />}

      {cells.length > 1 && (
        <Card>
          <CardHead title={e.kind === "ood" ? "In-distribution vs out-of-distribution" : "Every cell"} />
          <div className="overflow-x-auto p-4">
            <table className="w-full min-w-[640px] text-sm tabular-nums">
              <thead>
                <tr className="border-b border-rule text-left text-xs text-graphite">
                  <th className="py-1.5 font-semibold">{e.kind === "ood" ? "Scenario" : "Cell"}</th>
                  <th className="py-1.5 text-right font-semibold">Recall</th>
                  <th className="py-1.5 text-right font-semibold">Recall, observable</th>
                  <th className="py-1.5 text-right font-semibold">Precision</th>
                  <th className="py-1.5 text-right font-semibold">F2</th>
                  <th className="py-1.5 text-right font-semibold">PR-AUC</th>
                  <th className="py-1.5 text-right font-semibold">FPR</th>
                  <th className="py-1.5 text-right font-semibold">Top-1</th>
                </tr>
              </thead>
              <tbody>
                {cells.map(([name, b]) => (
                  <tr key={name} className={cn("border-b border-hair", name === "in_distribution" && "bg-well font-semibold")}>
                    <td className="py-1.5">{name.replace(/_/g, " ")}</td>
                    <td className="py-1.5 text-right">{pct(b.recall)}</td>
                    <td className="py-1.5 text-right">{b.recall_observable_faults != null ? pct(b.recall_observable_faults) : "—"}</td>
                    <td className="py-1.5 text-right">{pct(b.precision)}</td>
                    <td className="py-1.5 text-right">{num(b.f2, 3)}</td>
                    <td className="py-1.5 text-right">{num(b.pr_auc, 3)}</td>
                    <td className="py-1.5 text-right">{pct(b.false_positive_rate)}</td>
                    <td className="py-1.5 text-right">{b.localization ? pct(b.localization.top1, 0) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </>
  );
}

// ------------------------------------------------------------- charts
type Cell = [string, Benchmark & { esr_target_ohm?: number; stress_temp_c?: number; true_esr_168h_median_ohm?: number }];

/** Recall against the ESR the fault reaches, one line per soak temperature. */
function SweepChart({ cells }: { cells: Cell[] }) {
  const [hover, setHover] = useState<{ x: number; y: number; t: string } | null>(null);
  const temps = useMemo(() => [...new Set(cells.map(([, b]) => b.stress_temp_c!))].sort((a, b) => a - b), [cells]);
  const esrs = useMemo(() => [...new Set(cells.map(([, b]) => b.esr_target_ohm!))].sort((a, b) => a - b), [cells]);
  const W = 640, H = 280, L = 48, R = 70, T = 16, B = 40;
  const x = (v: number) => L + ((v - esrs[0]) / (esrs[esrs.length - 1] - esrs[0] || 1)) * (W - L - R);
  const y = (v: number) => T + (1 - v) * (H - T - B);
  const floor = cells.reduce((a, [, b]) => a + b.false_positive_rate, 0) / Math.max(cells.length, 1);
  return (
    <Card>
      <CardHead title="Detection vs ESR degradation" meta="recall of the injected C001 fault, flagged = WATCH or REJECT" />
      <div className="p-4">
        <div className="mb-2 flex flex-wrap gap-4 text-xs text-graphite" aria-label="Legend">
          {temps.map((t, i) => (
            <span key={t} className="flex items-center gap-1.5">
              <span className="h-0.5 w-4" style={{ background: TEMP_RAMP[i % TEMP_RAMP.length] }} />soak {t} °C
            </span>
          ))}
        </div>
        <div className="relative overflow-x-auto">
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[480px]" role="img" aria-label="Recall against target ESR per soak temperature">
            {[0, 0.25, 0.5, 0.75, 1].map((v) => (
              <g key={v}>
                <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke={C.hair} />
                <text x={L - 8} y={y(v) + 4} textAnchor="end" fontSize={11} fill={C.mute}>{Math.round(v * 100)}%</text>
              </g>
            ))}
            {esrs.map((e) => (
              <text key={e} x={x(e)} y={H - B + 18} textAnchor="middle" fontSize={11} fill={C.mute}>{e.toFixed(1)} Ω</text>
            ))}
            {/* Chance floor: the share of HEALTHY boards the policy flags anyway. */}
            <line x1={L} x2={W - R} y1={y(floor)} y2={y(floor)} stroke={C.copper} strokeWidth={1.5} strokeDasharray="5 4" />
            <text x={L + 4} y={y(floor) - 5} fontSize={11} fill={C.graphite}>healthy boards flagged anyway ({pct(floor, 0)})</text>
            <text x={(L + W - R) / 2} y={H - 4} textAnchor="middle" fontSize={11} fill={C.graphite}>C001 ESR target at 168 h (nominal 0.12 Ω)</text>
            {temps.map((t, i) => {
              const pts = esrs.map((e) => {
                const cell = cells.find(([, b]) => b.esr_target_ohm === e && b.stress_temp_c === t);
                return cell ? ([e, cell[1].recall] as const) : null;
              }).filter((p): p is readonly [number, number] => p != null);
              const color = TEMP_RAMP[i % TEMP_RAMP.length];
              const d = pts.map((p, j) => `${j ? "L" : "M"}${x(p[0])},${y(p[1])}`).join("");
              const last = pts[pts.length - 1];
              return (
                <g key={t}>
                  <path d={d} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" />
                  {pts.map((p) => (
                    <circle key={p[0]} cx={x(p[0])} cy={y(p[1])} r={4.5} fill={color} stroke={C.sheet} strokeWidth={2}
                      onMouseEnter={() => setHover({ x: x(p[0]), y: y(p[1]), t: `${t} °C, ESR ${p[0].toFixed(1)} Ω: recall ${pct(p[1])}` })}
                      onMouseLeave={() => setHover(null)} />
                  ))}
                  {last && <text x={x(last[0]) + 8} y={y(last[1]) + 4} fontSize={11} fill={C.graphite}>{t} °C</text>}
                </g>
              );
            })}
          </svg>
          {hover && (
            <div className="pointer-events-none absolute rounded-ctl border border-rule bg-sheet px-2 py-1 text-xs shadow"
              style={{ left: `${(hover.x / W) * 100}%`, top: `${(hover.y / H) * 100}%`, transform: "translate(-50%, -130%)" }}>
              {hover.t}
            </div>
          )}
        </div>
        <p className="mt-2 text-sm text-graphite">
          Recall at or near the dashed line is no better than the flag rate on healthy boards. At 25 °C and 85 °C the
          fault barely develops in 168 hours - which is exactly why burn-in is run hot. Low ESR targets move
          propagation delay less than the tester&apos;s 1.5 % repeatability, so recall there is bounded by metrology,
          not by the model. Each point is {cells[0]?.[1].faulty_boards ?? "—"} injected boards; small cells are noisy.
        </p>
      </div>
    </Card>
  );
}

/** Recall per scenario, one bar each; the in-distribution bar is the reference. */
function OodChart({ cells }: { cells: Cell[] }) {
  const [hover, setHover] = useState<string | null>(null);
  const ref = cells.find(([n]) => n === "in_distribution")?.[1].recall ?? null;
  return (
    <Card>
      <CardHead title="Recall, in-distribution vs out-of-distribution" meta="forecaster trained on in-distribution lots only" />
      <div className="space-y-2 p-4">
        {cells.map(([name, b]) => (
          <div key={name} className="grid grid-cols-[180px_minmax(0,1fr)_64px] items-center gap-3 text-sm"
            onMouseEnter={() => setHover(name)} onMouseLeave={() => setHover(null)}>
            <span className={cn(name === "in_distribution" && "font-bold")}>{name.replace(/_/g, " ")}</span>
            <div className="relative h-4 rounded-sm bg-hair">
              <div className="h-full rounded-sm" style={{ width: `${b.recall * 100}%`, background: name === "in_distribution" ? C.ink : C.cobalt }} />
              {ref != null && <div className="absolute top-[-3px] h-[22px] w-0.5 bg-copper" style={{ left: `${ref * 100}%` }} aria-hidden />}
            </div>
            <span className="text-right tabular-nums">{pct(b.recall)}</span>
            {hover === name && (
              <span className="col-span-3 -mt-1 text-xs text-graphite">
                precision {pct(b.precision)} · PR-AUC {num(b.pr_auc, 3)} · FPR {pct(b.false_positive_rate)}
                {b.localization ? ` · top-1 localisation ${pct(b.localization.top1, 0)}` : ""}
              </span>
            )}
          </div>
        ))}
        <p className="pt-1 text-xs text-graphite">Copper tick: the in-distribution recall. Hover a row for its other metrics; the table below lists every one.</p>
      </div>
    </Card>
  );
}

