import { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { C, VERDICT_COLOR } from "@/lib/theme";
import type { Verdict } from "@/lib/console";

/* Interface primitives.
 *
 * Colour carries status and nothing else. Every figure is tabular. The verdict
 * is drawn as an inspector's stamp - the one place in the product that is set
 * in capitals, because that is how a QA stamp reads on a traveller. */

// ------------------------------------------------------------ formatting
export const UNIT_LABEL: Record<string, string> = {
  uA: "µA", nA: "nA", ns: "ns", mV: "mV", sigma: "σ",
};

export const unit = (u: string) => UNIT_LABEL[u] ?? u;

/** Fixed decimals, never scientific - an inspector reads a traveller. */
export function num(v: number | null | undefined, dp = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return v.toFixed(dp);
}

export const pct = (v: number, dp = 1) =>
  Number.isFinite(v) ? `${(v * 100).toFixed(dp)}%` : "—";

export const sigma = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined || !Number.isFinite(v) ? "—" : `${v.toFixed(dp)}σ`;

export const verdictText: Record<Verdict, string> = {
  ACCEPT: "text-pass", WATCH: "text-watch", REJECT: "text-reject",
};

// ------------------------------------------------------------- headings
/** The page title. Expanded Archivo - the plate on the front of the chamber. */
export function PageHead({
  title, lede, right,
}: { title: string; lede?: ReactNode; right?: ReactNode }) {
  return (
    <header className="mb-7 flex flex-wrap items-end gap-x-8 gap-y-3">
      <div className="min-w-0 flex-1">
        <h1 className="wide text-2xl font-extrabold tracking-[-0.01em] sm:text-3xl">{title}</h1>
        {lede && <p className="mt-2 max-w-prose text-base text-graphite">{lede}</p>}
      </div>
      {right}
    </header>
  );
}

/** A titled section inside a page. */
export function SectionTitle({
  title, note, id,
}: { title: string; note?: ReactNode; id?: string }) {
  return (
    <div id={id} className="mb-4 mt-12 flex scroll-mt-6 flex-wrap items-baseline gap-x-4 gap-y-1 first:mt-0">
      <h2 className="wide text-xl font-bold">{title}</h2>
      {note && <p className="text-sm text-graphite">{note}</p>}
    </div>
  );
}

// ---------------------------------------------------------------- cards
export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("card", className)}>{children}</div>;
}

export function CardHead({
  title, meta, right,
}: { title: ReactNode; meta?: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-hair px-4 py-3">
      <h3 className="text-sm font-bold">{title}</h3>
      {meta && <span className="text-sm text-graphite">{meta}</span>}
      {right && <span className="ml-auto">{right}</span>}
    </div>
  );
}

/** A chart in a card: title, the figure, and one sentence on what it answers. */
export function Figure({
  title, meta, right, note, children, className,
}: {
  title: ReactNode; meta?: ReactNode; right?: ReactNode; note?: ReactNode;
  children: ReactNode; className?: string;
}) {
  return (
    <Card className={cn("min-w-0", className)}>
      <CardHead title={title} meta={meta} right={right} />
      <div className="px-4 pt-3">{children}</div>
      {note ? <Note className="px-4 pb-4">{note}</Note> : <div className="pb-3" />}
    </Card>
  );
}

/** A caption: what the chart or table answers, in a sentence. */
export function Note({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cn("mt-3 max-w-prose text-sm text-graphite", className)}>{children}</p>;
}

// ------------------------------------------------------------ key/value
export function Stat({
  k, v, sub, tone,
}: { k: string; v: ReactNode; sub?: ReactNode; tone?: string }) {
  return (
    <div className="min-w-0 px-4 py-3">
      <div className="text-sm text-graphite">{k}</div>
      <div className={cn("mt-1 text-2xl font-bold leading-none", tone)}>{v}</div>
      {sub && <div className="mt-1.5 text-xs text-mute">{sub}</div>}
    </div>
  );
}

/** A row of stats inside one card, divided by rules. */
export function StatRow({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <Card className={cn("grid divide-hair max-sm:divide-y sm:divide-x", className)}>{children}</Card>
  );
}

export function Field({
  k, v, tone,
}: { k: string; v: ReactNode; tone?: string }) {
  return (
    <div className="min-w-0">
      <div className="text-xs text-graphite">{k}</div>
      <div className={cn("mt-0.5 truncate text-sm font-semibold", tone)}>{v}</div>
    </div>
  );
}

/** Label left, value right, hairline under. For evidence registers. */
export function Row({ k, v, tone }: { k: ReactNode; v: ReactNode; tone?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-hair py-2 last:border-0">
      <span className="text-sm text-graphite">{k}</span>
      <span className={cn("text-right text-sm font-semibold", tone)}>{v}</span>
    </div>
  );
}

// -------------------------------------------------------------- status
/** The verdict, as an inspector's stamp: double rule, capitals, stamp ink. */
export function Stamp({ v, size = "sm" }: { v: Verdict | "PASS" | "BREACH"; size?: "sm" | "lg" }) {
  const color =
    v === "PASS" ? C.pass : v === "BREACH" ? C.reject : VERDICT_COLOR[v];
  return (
    <span
      className={cn(
        "wide inline-block whitespace-nowrap font-extrabold uppercase leading-none",
        size === "lg" ? "px-2.5 py-1.5 text-sm tracking-[0.08em]" : "px-1.5 py-[3px] text-[11px] tracking-[0.06em]"
      )}
      style={{ color, border: `${size === "lg" ? 3 : 2}px double ${color}` }}
    >
      {v}
    </span>
  );
}

export function Dot({ color, className }: { color: string; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn("inline-block h-2 w-2 shrink-0 rounded-full", className)}
      style={{ background: color }}
    />
  );
}

const SEVERITY: Record<string, { color: string; label: string }> = {
  high: { color: C.reject, label: "High" },
  medium: { color: C.watch, label: "Medium" },
  low: { color: C.mute, label: "Low" },
};

export function Severity({ s }: { s: string }) {
  const t = SEVERITY[s] ?? SEVERITY.low;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-semibold" style={{ color: t.color }}>
      <Dot color={t.color} />
      {t.label}
    </span>
  );
}

/** Horizontal bar meter: sub-score contributions, risk, reject fraction. */
export function Meter({
  value, max, color = C.cobalt, height = 6,
}: { value: number; max: number; color?: string; height?: number }) {
  const w = Math.max(0, Math.min(1, (value || 0) / max)) * 100;
  return (
    <div className="w-full overflow-hidden rounded-full bg-hair" style={{ height }} role="presentation">
      <div className="h-full rounded-full" style={{ width: `${w}%`, background: color }} />
    </div>
  );
}

/** Risk number with its meter, coloured by verdict. Used in every register. */
export function Risk({ r, v }: { r: number; v: Verdict }) {
  return (
    <span className="flex items-center gap-2.5">
      <span className={cn("w-9 text-right font-semibold", verdictText[v])}>{num(r, 1)}</span>
      <span className="w-16"><Meter value={r} max={100} height={5} color={VERDICT_COLOR[v]} /></span>
    </span>
  );
}

// ------------------------------------------------------------- notices
const NOTICE = {
  info: C.cobalt, warn: C.watch, danger: C.reject, pass: C.pass,
} as const;

/** A callout with a coloured edge. The title says what happened. */
export function Notice({
  tone = "info", title, children, className,
}: { tone?: keyof typeof NOTICE; title?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div
      className={cn("rounded-card border border-rule bg-sheet px-4 py-3", className)}
      style={{ borderLeft: `4px solid ${NOTICE[tone]}` }}
    >
      {title && <div className="text-sm font-bold" style={{ color: NOTICE[tone] }}>{title}</div>}
      <div className={cn("text-sm text-ink", title && "mt-1")}>{children}</div>
    </div>
  );
}

// ------------------------------------------------------------ reasons
export interface ReasonView {
  code: string;
  severity: string;
  message: string;
  feature?: string;
  value?: number;
  ref?: number;
  gate?: number;
  title?: string;
}

/** One reason code as an inspector reads it: code, severity, the sentence,
 *  and the observed value against the lot reference. */
export function ReasonCode({ r }: { r: ReasonView }) {
  return (
    <li className="py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="rounded-ctl bg-ink px-1.5 py-0.5 text-xs font-bold text-sheet">{r.code}</span>
        <Severity s={r.severity} />
        {r.title && <span className="text-sm font-semibold">{r.title}</span>}
      </div>
      <p className="mt-1.5 max-w-prose text-[15px] leading-6">{r.message}</p>
      {(r.value !== undefined || r.feature) && (
        <p className="mt-1 text-xs text-graphite">
          {r.feature && <>Gate: {r.feature}. </>}
          {r.value !== undefined && <>Observed {num(r.value, 3)}</>}
          {r.ref !== undefined && <>, lot reference {num(r.ref, 3)}</>}
          {r.gate !== undefined && Number.isFinite(r.gate) && <>, trigger {num(r.gate, 2)}</>}
          {r.value !== undefined && "."}
        </p>
      )}
    </li>
  );
}

// ------------------------------------------------------------ sequence
/** An ordered process. Only for content that really is a sequence. */
export function Steps({
  steps, className,
}: { steps: { k: string; v: ReactNode; tone?: string }[]; className?: string }) {
  return (
    <ol className={cn("space-y-0", className)}>
      {steps.map((s, i) => (
        <li key={s.k} className="relative grid grid-cols-[22px_1fr] gap-3 pb-3 last:pb-0">
          {i < steps.length - 1 && (
            <span aria-hidden className="absolute left-[10px] top-6 h-[calc(100%-18px)] w-px bg-rule" />
          )}
          <span className="grid h-[22px] w-[22px] place-items-center rounded-full border border-rule bg-sheet text-xs font-semibold text-graphite">
            {i + 1}
          </span>
          <div className="min-w-0 pt-0.5">
            <div className="text-xs text-graphite">{s.k}</div>
            <div className={cn("text-sm font-semibold", s.tone)}>{s.v}</div>
          </div>
        </li>
      ))}
    </ol>
  );
}

// --------------------------------------------------------- disclosures
/**
 * Simulated data must be distinguishable from live inference. This note
 * appears on every screen that renders screening output.
 */
export function Provenance({
  modelVersion, source, className,
}: { modelVersion: string; source: string; className?: string }) {
  return (
    <p className={cn("mt-10 max-w-prose text-xs text-mute", className)}>
      <strong className="font-semibold text-graphite">Simulated data.</strong> Generated by{" "}
      <code>src/generate_burnin_dataset.py</code> at seed 42 and screened by{" "}
      <code>src/pipeline.py</code> ({modelVersion}) from {source}. Known ground truth makes recall
      measurable; it is never an input to a verdict.
    </p>
  );
}
