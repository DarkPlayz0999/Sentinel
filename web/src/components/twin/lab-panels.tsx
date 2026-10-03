"use client";

import { ReactNode, useState } from "react";
import { Card, CardHead, Meter, Notice, Stamp, num, pct } from "@/components/ui/kit";
import type {
  Benchmark, Candidate, Hypothesis, LotBoard, QACheck, Replacement, SimEvent, Verdict,
} from "@/lib/sim-api";
import { C, VERDICT_COLOR } from "@/lib/theme";
import { cn } from "@/lib/utils";

/* Panels for the fault-injection lab and the benchmark page.
 * Every value rendered here arrives from the API. Where a number is a model
 * output rather than a measurement, the panel says so next to it. */

export const GLYPH: Record<string, string> = { ACCEPT: "●", OK: "●", WATCH: "▲", REJECT: "■" };
export const UNITS: Record<string, string> = { Iddq_uA: "µA", Ileak_nA: "nA", Tpd_ns: "ns", Vol_mV: "mV" };
export const PARAM_LABEL: Record<string, string> = {
  Iddq_uA: "Supply current (Iddq)", Ileak_nA: "Output leakage (Ileak)",
  Tpd_ns: "Propagation delay (Tpd)", Vol_mV: "Output-low voltage (Vol)",
};

/** SI value in an engineer's unit: 1.2e-5 A -> "12.0 µA". */
export function si(v: number | null | undefined, unit: string): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const map: Record<string, [number, string][]> = {
    A: [[1e-3, "mA"], [1e-6, "µA"], [1e-9, "nA"]],
    F: [[1e-6, "µF"], [1e-9, "nF"], [1e-12, "pF"]],
    s: [[1e-9, "ns"]],
  };
  const steps = map[unit];
  if (steps) {
    for (const [f, u] of steps) {
      if (Math.abs(v) >= f * 0.999 || f === steps[steps.length - 1][0]) {
        const x = v / f;
        return `${x.toFixed(Math.abs(x) >= 100 ? 0 : Math.abs(x) >= 10 ? 1 : 2)} ${u}`;
      }
    }
  }
  if (unit === "ohm") return v >= 1000 ? `${(v / 1000).toFixed(1)} kΩ` : `${v.toFixed(v < 1 ? 3 : 1)} Ω`;
  if (unit === "V") return `${v.toFixed(3)} V`;
  return `${v.toPrecision(3)} ${unit}`;
}

// ------------------------------------------------------------ small bits
export function Chip({ children, tone = "ink" }: { children: ReactNode; tone?: "ink" | "copper" | "reject" | "pass" }) {
  const color = { ink: C.ink, copper: C.copper, reject: C.reject, pass: C.pass }[tone];
  return (
    <span className="wide inline-flex items-center whitespace-nowrap rounded-ctl border px-2 py-1 text-[11px] font-bold tracking-wide"
      style={{ color, borderColor: color }}>
      {children}
    </span>
  );
}

export function Btn({
  children, onClick, disabled, kind = "primary", className, title,
}: {
  children: ReactNode; onClick?: () => void; disabled?: boolean;
  kind?: "primary" | "secondary" | "danger" | "copper"; className?: string; title?: string;
}) {
  const style = {
    primary: "bg-ink text-sheet hover:opacity-90",
    secondary: "border border-rule bg-sheet text-ink hover:bg-well",
    danger: "bg-reject text-white hover:opacity-90",
    copper: "bg-copper text-white hover:opacity-90",
  }[kind];
  return (
    <button type="button" onClick={onClick} disabled={disabled} title={title}
      className={cn("rounded-ctl px-3.5 py-2 text-sm font-bold disabled:cursor-not-allowed disabled:opacity-40", style, className)}>
      {children}
    </button>
  );
}

export function KV({ k, v, tone, sub }: { k: ReactNode; v: ReactNode; tone?: string; sub?: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-hair py-1.5 text-sm last:border-0">
      <span className="text-graphite">{k}</span>
      <span className={cn("text-right font-semibold tabular-nums", tone)}>
        {v}
        {sub && <span className="block text-xs font-normal text-mute">{sub}</span>}
      </span>
    </div>
  );
}

/** Tiny line of one series over hours, with a marker at the current hour. */
export function Sparkline({
  hours, ys, t, color = C.cobalt, height = 44, fmt = (v: number) => v.toFixed(1), label,
}: {
  hours: number[]; ys: (number | null)[]; t?: number; color?: string; height?: number;
  fmt?: (v: number) => string; label: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const pts = hours.map((h, i) => [h, ys[i]] as const).filter((p): p is readonly [number, number] => p[1] != null);
  if (pts.length < 2) return <div className="text-xs text-mute">no series yet</div>;
  const W = 260;
  const lo = Math.min(...pts.map((p) => p[1]));
  const hi = Math.max(...pts.map((p) => p[1]));
  const span = hi - lo || 1;
  const x = (h: number) => (h / 168) * (W - 8) + 4;
  const y = (v: number) => height - 6 - ((v - lo) / span) * (height - 14);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join("");
  const hp = hover != null ? pts[hover] : null;
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${height}`} className="w-full" role="img" aria-label={label}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          const h = ((e.clientX - r.left) / r.width) * 168;
          let best = 0;
          pts.forEach((p, i) => { if (Math.abs(p[0] - h) < Math.abs(pts[best][0] - h)) best = i; });
          setHover(best);
        }}>
        <line x1={4} x2={W - 4} y1={height - 6} y2={height - 6} stroke={C.hair} strokeWidth={1} />
        <path d={d} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {t != null && <line x1={x(t)} x2={x(t)} y1={2} y2={height - 6} stroke={C.copper} strokeWidth={1.5} />}
        {hp && <circle cx={x(hp[0])} cy={y(hp[1])} r={4} fill={color} stroke={C.sheet} strokeWidth={2} />}
      </svg>
      <div className="flex justify-between text-[11px] text-mute">
        <span>{fmt(lo)}</span>
        {hp ? <span className="font-semibold text-ink">{hp[0].toFixed(0)} h: {fmt(hp[1])}</span> : <span>{label}</span>}
        <span>{fmt(hi)}</span>
      </div>
    </div>
  );
}

// ------------------------------------------------------- closed loop
export interface LoopStep { k: string; done: boolean; active?: boolean; note?: string }

export function ClosedLoop({ steps }: { steps: LoopStep[] }) {
  return (
    <ol className="flex flex-wrap gap-1.5" aria-label="Closed-loop progress">
      {steps.map((s, i) => (
        <li key={s.k}
          className={cn("flex items-center gap-1.5 rounded-ctl border px-2 py-1 text-xs font-semibold",
            s.done ? "border-pass/40 bg-pass/10 text-pass" : s.active ? "border-copper bg-copper/10 text-copper" : "border-rule text-mute")}
          title={s.note}>
          <span aria-hidden>{s.done ? "✓" : s.active ? "◐" : "○"}</span>
          <span>{i + 1}. {s.k}</span>
        </li>
      ))}
    </ol>
  );
}

// ------------------------------------------------------------ the lot
export function LotStrip({
  boards, selected, focus, onPick,
}: { boards: LotBoard[]; selected: string | null; focus: string | null; onPick: (s: string) => void }) {
  return (
    <div className="grid gap-[3px]" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(16px, 1fr))" }}>
      {boards.map((b) => {
        const v = b.verdict;
        const color = v ? VERDICT_COLOR[v] : C.rule;
        const isSel = b.serial === selected;
        const isFocus = b.serial === focus;
        return (
          <button key={b.serial} type="button" onClick={() => onPick(b.serial)}
            title={`${b.serial}${v ? ` - ${v}, risk ${num(b.risk_score, 1)}` : ""}${b.is_faulty ? " - injected fault (truth)" : ""}`}
            aria-label={`${b.serial} ${v ?? "not screened"}`}
            className={cn("relative grid aspect-square place-items-center rounded-[3px] text-[10px] leading-none",
              isSel ? "ring-2 ring-[#5BD7E0]" : isFocus ? "ring-2 ring-copper" : "")}
            style={{ background: v ? `${color}22` : C.well, color }}>
            {v ? GLYPH[v] : "·"}
            {b.is_faulty ? <span className="absolute right-0 top-0 h-1.5 w-1.5 rounded-full bg-reject" aria-hidden /> : null}
          </button>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------- hypotheses
export function HypothesisList({ hyps, onPick }: { hyps: Hypothesis[]; onPick?: (cid: string) => void }) {
  return (
    <ol className="space-y-2">
      {hyps.map((h) => (
        <li key={`${h.component_id}${h.fault_type}`}>
          <button type="button" onClick={() => onPick?.(h.component_id)} className="w-full text-left">
            <div className="flex items-baseline justify-between gap-2 text-sm">
              <span><strong>{h.rank}. {h.component_id}</strong> {h.fault_type.replace(/_/g, " ").toLowerCase()}</span>
              <span className="tabular-nums font-semibold">{h.evidence_score.toFixed(0)}</span>
            </div>
            <Meter value={h.evidence_score} max={100} color={h.rank === 1 ? C.reject : C.cobalt} />
            {h.signature?.length > 0 && (
              <p className="mt-0.5 text-xs text-mute">moves: {h.signature.join(", ")}</p>
            )}
          </button>
        </li>
      ))}
    </ol>
  );
}

const QA_COLOR: Record<string, string> = { PASS: C.pass, WARN: C.watch, FAIL: C.reject, INFO: C.cobalt };

export function QAList({ checks }: { checks: QACheck[] }) {
  return (
    <ul className="divide-y divide-hair">
      {checks.map((c) => (
        <li key={c.check} className="py-2 text-sm">
          <span className="mr-2 text-xs font-bold" style={{ color: QA_COLOR[c.status] }}>{c.status}</span>
          <strong className="capitalize">{c.check}</strong>
          <p className="mt-0.5 text-graphite">{c.detail}</p>
        </li>
      ))}
    </ul>
  );
}

// -------------------------------------------------------- replacement
const CRITERIA: Record<string, string> = {
  tolerance_used_pct: "Tolerance band used",
  predicted_drift_pct: "Predicted 168 h drift (model)",
  operating_temp_c: "Operating temperature",
  electrical_stress_pct: "Electrical stress",
  historical_defect_pct: "Reel defect history",
};
const CRIT_UNIT: Record<string, string> = {
  tolerance_used_pct: "%", predicted_drift_pct: "%", operating_temp_c: " °C",
  electrical_stress_pct: "%", historical_defect_pct: "%",
};

export function CandidateTable({
  cands, onFit, busy,
}: { cands: Candidate[]; onFit: (id: string) => void; busy: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[420px] text-sm">
        <thead>
          <tr className="border-b border-rule text-left text-xs text-graphite">
            <th className="py-1.5 pr-2 font-semibold">Criterion</th>
            {cands.map((c) => <th key={c.candidate_id} className="py-1.5 pr-2 text-right font-semibold">{c.candidate_id}</th>)}
          </tr>
        </thead>
        <tbody>
          {Object.keys(CRITERIA).map((k) => (
            <tr key={k} className="border-b border-hair">
              <td className="py-1.5 pr-2 text-graphite">{CRITERIA[k]}</td>
              {cands.map((c) => (
                <td key={c.candidate_id} className="py-1.5 pr-2 text-right tabular-nums">
                  {num(c.criteria[k], k === "operating_temp_c" ? 1 : 1)}{CRIT_UNIT[k]}
                  <span className="block text-[11px] text-mute">−{num(c.penalties[k], 1)}</span>
                </td>
              ))}
            </tr>
          ))}
          <tr>
            <td className="py-2 pr-2 font-bold">Ranking score</td>
            {cands.map((c) => (
              <td key={c.candidate_id} className="py-2 pr-2 text-right text-lg font-bold tabular-nums">{c.ranking_score.toFixed(1)}</td>
            ))}
          </tr>
          <tr>
            <td className="pr-2 text-xs text-mute">Source</td>
            {cands.map((c) => <td key={c.candidate_id} className="pr-2 text-right text-xs text-mute">{c.reel_label}</td>)}
          </tr>
          <tr>
            <td />
            {cands.map((c, i) => (
              <td key={c.candidate_id} className="pt-2 text-right">
                <Btn kind={i === 0 ? "copper" : "secondary"} disabled={busy} onClick={() => onFit(c.candidate_id)}>
                  Fit & rerun
                </Btn>
              </td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}

export function BeforeAfter({ r, keyParams }: { r: Replacement; keyParams: string[] }) {
  const rows: [string, ReactNode, ReactNode][] = [
    ["Verdict", r.before.verdict ? <Stamp v={r.before.verdict} /> : "—", <Stamp key="a" v={r.after.verdict} />],
    ["Risk score", num(r.before.risk_score, 1), num(r.after.risk_score, 1)],
    [`${r.component_id} IR at 168 h`, `${num(r.before.ir_temp_c, 2)} °C`, `${num(r.after.ir_temp_c, 2)} °C`],
    ...Object.keys(r.before.ate_168h).map((p) => [
      `${p.split("_")[0]} at 168 h`,
      `${num(r.before.ate_168h[p], 3)} ${UNITS[p] ?? ""}`,
      `${num(r.after.ate_168h[p], 3)} ${UNITS[p] ?? ""}`,
    ] as [string, ReactNode, ReactNode]),
    ...keyParams.filter((p) => r.before.bench_removed_part[p] != null).map((p) => [
      `${p} (bench / incoming)`,
      fmtParam(p, r.before.bench_removed_part[p]),
      fmtParam(p, r.after.incoming_inspection[p]),
    ] as [string, ReactNode, ReactNode]),
  ];
  return (
    <div>
      <table className="w-full table-fixed text-xs">
        <colgroup><col className="w-[44%]" /><col className="w-[28%]" /><col className="w-[28%]" /></colgroup>
        <thead>
          <tr className="border-b border-rule text-left text-graphite">
            <th className="py-1.5 font-semibold">Observed</th>
            <th className="py-1.5 text-right font-semibold">Before<span className="block font-normal">{r.component_id}</span></th>
            <th className="py-1.5 text-right font-semibold">After<span className="block font-normal">{r.after.component_id}</span></th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([k, a, b]) => (
            <tr key={k} className="border-b border-hair align-top">
              <td className="py-1.5 pr-2 text-graphite">{k}</td>
              <td className="py-1.5 text-right tabular-nums">{a}</td>
              <td className="py-1.5 pl-1 text-right font-semibold tabular-nums">{b}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function fmtParam(p: string, v: number | null | undefined): string {
  const unit = { esr: "ohm", capacitance: "F", leakage: "A", resistance: "ohm", r_contact: "ohm",
    vth: "V", r_ch: "ohm", i_off: "A", iddq: "A", t_int: "s", vth_int: "V", vsupply: "V", ripple: "V" }[p] ?? "";
  return si(v ?? null, unit);
}

// ---------------------------------------------------------- benchmark
export function Metric({ k, v, sub, tone }: { k: string; v: string; sub?: string; tone?: string }) {
  return (
    <div className="rounded-card border border-rule bg-sheet px-3 py-2.5">
      <div className="text-xs text-graphite">{k}</div>
      <div className={cn("wide mt-0.5 text-xl font-bold tabular-nums", tone)}>{v}</div>
      {sub && <div className="text-[11px] text-mute">{sub}</div>}
    </div>
  );
}

export function BenchmarkView({ b, compact = false }: { b: Benchmark; compact?: boolean }) {
  const c = b.confusion;
  return (
    <div className="space-y-4">
      <div className={cn("grid grid-cols-2 gap-2", !compact && "sm:grid-cols-4")}>
        <Metric k="Recall (escapes caught)" v={pct(b.recall)} sub={`${c.tp} of ${c.tp + c.fn} faulty boards`} tone="text-ink" />
        <Metric k="Precision" v={pct(b.precision)} sub={`${c.fp} good boards flagged`} />
        <Metric k="F2 (recall-weighted)" v={num(b.f2, 3)} />
        <Metric k="PR-AUC" v={num(b.pr_auc, 3)} sub="ranking by risk score" />
        <Metric k="False-negative rate" v={pct(b.false_negative_rate)} tone={b.false_negative_rate > 0 ? "text-reject" : "text-pass"} />
        <Metric k="False-positive rate" v={pct(b.false_positive_rate)} />
        <Metric k="Recall at 5 % overkill" v={b.recall_at_overkill?.feasible ? pct(b.recall_at_overkill.recall) : "—"} />
        {b.recall_observable_faults != null && Number.isFinite(b.recall_observable_faults) ? (
          <Metric k="Recall, observable faults" v={pct(b.recall_observable_faults)} sub={`${b.counts.unobservable_faults ?? 0} faults move no channel`} />
        ) : (
          <Metric k="REJECT-only recall" v={pct(b.reject_only.recall)} />
        )}
      </div>

      <div className={cn("grid gap-4", !compact && "sm:grid-cols-2")}>
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-mute">Confusion matrix (boards)</p>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-graphite">
                <th />
                <th className="py-1 text-right font-semibold">Flagged</th>
                <th className="py-1 text-right font-semibold">Accepted</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              <tr className="border-t border-hair">
                <td className="py-1 text-graphite">Faulty</td>
                <td className="py-1 text-right font-bold text-pass">{c.tp} TP</td>
                <td className="py-1 text-right font-bold text-reject">{c.fn} FN</td>
              </tr>
              <tr className="border-t border-hair">
                <td className="py-1 text-graphite">Healthy</td>
                <td className="py-1 text-right">{c.fp} FP</td>
                <td className="py-1 text-right">{c.tn} TN</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div className="text-sm">
          {b.localization && (
            <KV k="Localisation top-1 / top-3" v={`${pct(b.localization.top1, 0)} / ${pct(b.localization.top3, 0)}`}
              sub={`${b.localization.evaluated} flagged faulty boards diagnosed`} />
          )}
          {b.detection_delay_h && (
            <KV k="Detection read (mean)" v={`${num(b.detection_delay_h.mean, 0)} h`}
              sub={Object.entries(b.detection_delay_h.by_read).map(([h, n]) => `${n} at ${h} h`).join(", ")} />
          )}
          <KV k="Injected / detected / missed" v={`${b.counts.injected} / ${b.counts.detected} / ${b.counts.missed}`} />
          <KV k="Incorrectly flagged" v={b.counts.incorrectly_flagged} />
          <KV k="Plain accuracy" v="not reported" sub="rule 5: 'all good' would score in the 90s" />
        </div>
      </div>

      {!compact && b.forecast && (
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-mute">
            Module B forecast of the 168 h read {b.forecast.out_of_fold ? "(out-of-fold)" : "(in-sample - not quotable)"}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[420px] text-sm tabular-nums">
              <thead>
                <tr className="border-b border-rule text-xs text-graphite">
                  <th className="py-1 text-left font-semibold">Parameter</th>
                  <th className="py-1 text-right font-semibold">MAE</th>
                  <th className="py-1 text-right font-semibold">RMSE</th>
                  <th className="py-1 text-right font-semibold">Normalised MAE</th>
                  <th className="py-1 text-right font-semibold">Upper-bound coverage</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(b.forecast.by_parameter).map(([p, m]) => (
                  <tr key={p} className="border-b border-hair">
                    <td className="py-1">{PARAM_LABEL[p] ?? p}</td>
                    <td className="py-1 text-right">{num(m.mae, 3)} {UNITS[p]}</td>
                    <td className="py-1 text-right">{num(m.rmse, 3)}</td>
                    <td className="py-1 text-right">{pct(m.normalised_mae, 2)}</td>
                    <td className="py-1 text-right">{pct(m.upper_coverage, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!compact && b.by_fault_type && b.by_fault_type.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-mute">Recall by injected fault</p>
          <div className="max-h-[320px] overflow-auto">
            <table className="w-full min-w-[420px] text-sm tabular-nums">
              <thead className="sticky top-0 bg-sheet">
                <tr className="border-b border-rule text-xs text-graphite">
                  <th className="py-1 text-left font-semibold">Component</th>
                  <th className="py-1 text-left font-semibold">Fault</th>
                  <th className="py-1 text-right font-semibold">n</th>
                  <th className="py-1 text-right font-semibold">Caught</th>
                  <th className="w-24 py-1 pl-2 text-left font-semibold">Recall</th>
                </tr>
              </thead>
              <tbody>
                {[...b.by_fault_type].sort((a, z) => a.recall - z.recall).map((r) => (
                  <tr key={`${r.component}${r.fault_type}`} className="border-b border-hair">
                    <td className="py-1">{r.component}</td>
                    <td className="py-1">{r.fault_type.replace(/_/g, " ").toLowerCase()}</td>
                    <td className="py-1 text-right">{r.n}</td>
                    <td className="py-1 text-right">{r.detected}</td>
                    <td className="py-1 pl-2">
                      <div className="flex items-center gap-2">
                        <span className="w-10 text-right">{pct(r.recall, 0)}</span>
                        <span className="w-12"><Meter value={r.recall} max={1} color={C.cobalt} /></span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!compact && b.false_negatives.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer font-semibold">Missed boards ({b.false_negatives.length} shown)</summary>
          <ul className="mt-2 space-y-1 text-graphite">
            {b.false_negatives.map((f) => (
              <li key={f.serial}>{f.serial}: {f.components} {f.fault_types.toLowerCase()} at severity {f.severity}, risk {f.risk_score}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

// ------------------------------------------------------------- events
const EVENT_TONE: Record<string, string> = {
  THRESHOLD_CROSSED: C.watch, SENTINEL_FLAGGED: C.reject, DIAGNOSIS_COMPLETE: C.reject,
  SIMULATION_FAILED: C.reject, SIMULATION_ERROR: C.reject, SPICE_CROSSCHECK_FAILED: C.reject,
  GROUND_TRUTH_REVEALED: C.copper, RERUN_COMPLETED: C.pass, SENTINEL_RESULT: C.cobalt,
};

export function describe(e: SimEvent): string {
  const p = e.payload as Record<string, unknown>;
  switch (e.type) {
    case "CHECKPOINT_REACHED": return `Read point ${p.time_h} h: ${p.boards} boards measured`;
    case "THRESHOLD_CROSSED": return `${e.serial}: ${p.channel} at ${p.z} σ (monitor ≥ ${p.monitor_z}) at ${p.time_h} h`;
    case "BURN_IN_COMPLETE": return "Burn-in complete (168 simulated hours)";
    case "MEASUREMENTS_SENT": return `Sent ${p.rows} boards to Sentinel: serial, lot and ATE reads only`;
    case "SENTINEL_RESULT": {
      const v = p.verdicts as Record<string, number>;
      return `Sentinel: ${v.REJECT} REJECT, ${v.WATCH} WATCH, ${v.ACCEPT} ACCEPT`;
    }
    case "SENTINEL_FLAGGED": return `${e.serial} flagged ${p.verdict}, risk ${p.risk_score} (${(p.codes as string[]).join(", ") || "weighted score"})`;
    case "SENTINEL_INTERIM_SCREEN": return `Interim screen at ${p.time_h} h (monitor trigger): ${p.flagged} flagged`;
    case "DIAGNOSIS_COMPLETE": return `Agents: ${e.serial} suspect ${p.suspect_component} (evidence ${num(p.evidence_score as number, 0)}), QA ${p.qa_status}`;
    case "SPICE_UNAVAILABLE": return "ngspice not installed: DC reads from the built-in MNA solver";
    case "SPICE_CROSSCHECK": return `ngspice cross-check: max difference ${pct(p.max_relative_difference as number, 4)}`;
    case "REPLACEMENT_SELECTED": return `${e.serial}: fitting ${p.candidate_id} in place of ${e.component_id}`;
    case "RERUN_COMPLETED": {
      const a = p.after as Record<string, unknown>;
      const b = p.before as Record<string, unknown>;
      return `${e.serial} rerun: ${b.verdict} ${num(b.risk_score as number, 1)} → ${a.verdict} ${num(a.risk_score as number, 1)}`;
    }
    case "GROUND_TRUTH_REVEALED": return "Ground truth revealed";
    case "HUMAN_DISPOSITION": return `${e.serial}: human disposition ${p.decision}`;
    case "SIMULATION_CREATED": return `Lot ${p.lot_id} created: ${p.boards} boards, ${p.mode}`;
    case "FAULT_INJECTED": return p.hidden ? "Fault injected (hidden)" : `Fault injected: ${p.component_id} ${p.fault_type}`;
    default: return e.type.replace(/_/g, " ").toLowerCase();
  }
}

export function EventLog({ events }: { events: SimEvent[] }) {
  return (
    <ol className="max-h-[300px] space-y-1 overflow-y-auto text-xs">
      {[...events].reverse().map((e) => (
        <li key={e.id} className="flex gap-2">
          <span className="w-14 shrink-0 tabular-nums text-mute">{e.at?.slice(11, 19)}</span>
          <span className="shrink-0" style={{ color: EVENT_TONE[e.type] ?? C.mute }}>●</span>
          <span className="text-ink">{describe(e)}</span>
        </li>
      ))}
    </ol>
  );
}

export function StatusGlyph({ s }: { s: string }) {
  const color = s === "REJECT" ? C.reject : s === "WATCH" ? C.watch : C.pass;
  return <span style={{ color }} className="font-bold">{GLYPH[s] ?? "●"} {s}</span>;
}

export { Card, CardHead, Notice };
export type { Verdict };
