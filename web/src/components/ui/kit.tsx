"use client";

import { ReactNode } from "react";
import { cn } from "@/lib/utils";
import type { Verdict } from "@/lib/console";

/* Instrument primitives.
 *
 * Hard corners, hairline rules, one weight of shadow at most. Every number on
 * screen is monospace and tabular so columns of readings line up the way they
 * do on a tester printout. Colour carries STATUS and nothing else - there is no
 * decorative hue anywhere in this file. */

// ------------------------------------------------------------ formatting
export const UNIT_LABEL: Record<string, string> = {
  uA: "µA", nA: "nA", ns: "ns", mV: "mV", sigma: "σ",
};

export const unit = (u: string) => UNIT_LABEL[u] ?? u;

/** Fixed significant digits, never scientific - an inspector reads a traveller. */
export function num(v: number | null | undefined, dp = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return v.toFixed(dp);
}

export const pct = (v: number, dp = 1) =>
  Number.isFinite(v) ? `${(v * 100).toFixed(dp)}%` : "—";

export const sigma = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined || !Number.isFinite(v) ? "—" : `${v.toFixed(dp)}σ`;

// ---------------------------------------------------------------- panels
export function Panel({
  children, className, sunk = false,
}: { children: ReactNode; className?: string; sunk?: boolean }) {
  return <div className={cn(sunk ? "panel-sunk" : "panel", className)}>{children}</div>;
}

export function PanelHead({
  title, meta, right, className,
}: { title: string; meta?: string; right?: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-lab-hair px-3 py-2",
        className
      )}
    >
      <span className="font-mono text-[10px] font-bold uppercase tracking-label text-lab-ink">
        {title}
      </span>
      {meta && <span className="label">{meta}</span>}
      {right && <span className="ml-auto">{right}</span>}
    </div>
  );
}

/** A titled block on the page. Rule above, label left, note right. */
export function SectionHead({
  index, title, note,
}: { index: string; title: string; note?: string }) {
  return (
    <div className="mb-5 flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-lab-rule pb-2">
      <span className="font-mono text-[10px] font-bold tracking-label text-sig-blue">{index}</span>
      <h2 className="font-mono text-[11px] font-bold uppercase tracking-label text-lab-ink">
        {title}
      </h2>
      {note && <span className="label ml-auto hidden sm:block">{note}</span>}
    </div>
  );
}

// ------------------------------------------------------------ key/value
export function Field({
  k, v, tone, mono = true, sub,
}: { k: string; v: ReactNode; tone?: string; mono?: boolean; sub?: string }) {
  return (
    <div className="min-w-0">
      <div className="label">{k}</div>
      <div
        className={cn(
          "mt-0.5 truncate text-[12px] font-medium",
          mono && "readout",
          tone ?? "text-lab-ink"
        )}
      >
        {v}
      </div>
      {sub && <div className="mt-0.5 font-mono text-[9px] text-lab-faint">{sub}</div>}
    </div>
  );
}

/** A large instrument readout: label, big number, unit, optional footnote. */
export function Stat({
  k, v, u, sub, tone, trend,
}: {
  k: string; v: ReactNode; u?: string; sub?: string; tone?: string; trend?: ReactNode;
}) {
  return (
    <div className="panel-sunk px-3 py-2.5">
      <div className="label">{k}</div>
      <div className="mt-1 flex items-baseline gap-1.5">
        <span className={cn("readout text-[20px] font-semibold leading-none", tone ?? "text-lab-ink")}>
          {v}
        </span>
        {u && <span className="font-mono text-[10px] text-lab-faint">{u}</span>}
        {trend}
      </div>
      {sub && <div className="mt-1.5 font-mono text-[9px] leading-tight text-lab-faint">{sub}</div>}
    </div>
  );
}

// ----------------------------------------------------------- status bits
export const VERDICT_TONE: Record<Verdict, { fg: string; bg: string; bd: string; dot: string }> = {
  ACCEPT: { fg: "text-sig-green", bg: "bg-sig-green/[0.08]", bd: "border-sig-green/35", dot: "bg-sig-green" },
  WATCH: { fg: "text-sig-amber", bg: "bg-sig-amber/[0.09]", bd: "border-sig-amber/40", dot: "bg-sig-amber" },
  REJECT: { fg: "text-sig-red", bg: "bg-sig-red/[0.08]", bd: "border-sig-red/35", dot: "bg-sig-red" },
};

export function VerdictChip({ v, size = "sm" }: { v: Verdict; size?: "sm" | "lg" }) {
  const t = VERDICT_TONE[v];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 border font-mono font-bold uppercase tracking-label",
        t.fg, t.bg, t.bd,
        size === "lg" ? "px-2.5 py-1 text-[11px]" : "px-1.5 py-[3px] text-[9px]"
      )}
    >
      <span className={cn("inline-block h-[5px] w-[5px] rounded-full", t.dot)} />
      {v}
    </span>
  );
}

export function Led({ tone = "green", pulse = true }: { tone?: "green" | "amber" | "red"; pulse?: boolean }) {
  const c = { green: "#186B45", amber: "#9A5B06", red: "#A81E12" }[tone];
  return (
    <span
      className={cn("inline-block h-[7px] w-[7px] rounded-full", pulse && "animate-led")}
      style={{ background: c, boxShadow: `0 0 0 2px ${c}22` }}
    />
  );
}

export function SeverityTag({ s }: { s: string }) {
  const tone =
    s === "high" ? "text-sig-red border-sig-red/35 bg-sig-red/[0.07]"
      : s === "medium" ? "text-sig-amber border-sig-amber/40 bg-sig-amber/[0.08]"
        : "text-lab-dim border-lab-rule bg-lab-sunk";
  return (
    <span className={cn("border px-1.5 py-[2px] font-mono text-[9px] font-bold uppercase tracking-label", tone)}>
      {s}
    </span>
  );
}

// ------------------------------------------------------------- meters
/** Horizontal bar meter. Used for sub-score contributions and z magnitudes. */
export function Meter({
  value, max, color = "#12508C", height = 7, track = true,
}: { value: number; max: number; color?: string; height?: number; track?: boolean }) {
  const w = Math.max(0, Math.min(1, (value || 0) / max)) * 100;
  return (
    <div
      className={cn("w-full", track && "panel-sunk")}
      style={{ height }}
      role="presentation"
    >
      <div
        className="h-full transition-[width] duration-500 ease-out"
        style={{ width: `${w}%`, background: color }}
      />
    </div>
  );
}

// --------------------------------------------------------- disclosures
/**
 * Rule 20.10: simulated data must be distinguishable from live inference.
 * This note appears on every screen that renders screening output.
 */
export function ProvenanceNote({
  modelVersion, source, className,
}: { modelVersion: string; source: string; className?: string }) {
  return (
    <p className={cn("font-mono text-[9px] leading-relaxed text-lab-faint", className)}>
      <span className="font-bold text-lab-dim">SIMULATED DATA.</span>{" "}
      Generated by <code>src/generate_burnin_dataset.py</code> at seed 42 and screened by{" "}
      <code>src/pipeline.py</code> ({modelVersion}). Source: {source}. Known ground truth is
      what lets recall be measured; it is never an input to a verdict.
    </p>
  );
}

/** A short, dismissible-free caption that says what a chart answers. */
export function ChartNote({ children }: { children: ReactNode }) {
  return (
    <p className="mt-2 border-t border-lab-hair pt-2 font-mono text-[9px] leading-relaxed text-lab-faint">
      {children}
    </p>
  );
}

// ------------------------------------------------------------- flow tape
/** The process tape: COMPONENT → BURN-IN → READ POINTS → ANALYSIS → VERDICT. */
export function FlowTape({
  steps, className,
}: { steps: { k: string; v: string; tone?: string }[]; className?: string }) {
  return (
    <ol className={cn("grid gap-px bg-lab-rule", className)}>
      {steps.map((s) => (
        <li key={s.k} className="bg-lab-card px-3 py-2">
          <div className="label">{s.k}</div>
          <div className={cn("readout mt-1 text-[11px] font-semibold", s.tone ?? "text-lab-ink")}>
            {s.v}
          </div>
        </li>
      ))}
    </ol>
  );
}
