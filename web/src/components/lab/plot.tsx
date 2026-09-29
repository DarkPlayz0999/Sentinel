"use client";

import { ReactNode } from "react";

/* Plot primitives. Inline SVG, no chart library: these are instrument traces,
 * and every tick, limit line and playhead here is positioned deliberately.
 * ponytail: recharts is in package.json but styling it into an oscilloscope
 * costs more code than drawing the four plots this page actually needs. */

export const scale = (v: number, d0: number, d1: number, r0: number, r1: number) =>
  r0 + ((v - d0) / (d1 - d0 || 1)) * (r1 - r0);

export function Frame({
  w, h, pad = [8, 10, 22, 34], children, caption,
}: {
  w: number; h: number; pad?: [number, number, number, number];
  children: ReactNode; caption?: string;
}) {
  const [pt, pr, pb, pl] = pad;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full" role="img" aria-label={caption}>
      {caption ? <title>{caption}</title> : null}
      <defs>
        <pattern id="gp" width="10" height="10" patternUnits="userSpaceOnUse">
          <path d="M10 0H0V10" fill="none" stroke="#0F1317" strokeOpacity="0.055" strokeWidth="1" />
        </pattern>
      </defs>
      <rect x={pl} y={pt} width={w - pl - pr} height={h - pt - pb} fill="#FCFCFB" />
      <rect x={pl} y={pt} width={w - pl - pr} height={h - pt - pb} fill="url(#gp)" />
      {children}
      <rect
        x={pl} y={pt} width={w - pl - pr} height={h - pt - pb}
        fill="none" stroke="#9CA2AB" strokeWidth="1"
      />
    </svg>
  );
}

export function Tick({ x, y, label, anchor = "middle" }: { x: number; y: number; label: string; anchor?: string }) {
  return (
    <text
      x={x} y={y} textAnchor={anchor as "middle"}
      className="fill-lab-faint font-mono"
      style={{ fontSize: 8.5 }}
    >
      {label}
    </text>
  );
}

/** A vertical limit line with a hanging tag - how a spec limit is drawn on a plot. */
export function LimitLine({
  x, top, bottom, label, color = "#A81E12", dashed = true, side = "right",
}: {
  x: number; top: number; bottom: number; label: string;
  color?: string; dashed?: boolean; side?: "left" | "right";
}) {
  return (
    <g>
      <line
        x1={x} x2={x} y1={top} y2={bottom}
        stroke={color} strokeWidth="1.25"
        strokeDasharray={dashed ? "4 3" : undefined}
      />
      <text
        x={side === "right" ? x + 4 : x - 4} y={top + 9}
        textAnchor={side === "right" ? "start" : "end"}
        className="font-mono" style={{ fontSize: 8, fill: color, letterSpacing: "0.06em" }}
      >
        {label}
      </text>
    </g>
  );
}

type Bin = { readonly x: number; readonly n: number };

/**
 * Two overlaid count histograms - population and the labelled defect subset -
 * with one limit line. Counts are real; see web/scripts/export_lab_data.py.
 */
export function Histogram({
  healthy, defect, lo, hi, limit, limitLabel, xLabel, ticks, w = 340, h = 168, limitSide = "right",
  shadeFrom,
}: {
  healthy: readonly Bin[]; defect: readonly Bin[];
  lo: number; hi: number; limit: number; limitLabel: string;
  xLabel: string; ticks: number[]; w?: number; h?: number;
  limitSide?: "left" | "right"; shadeFrom?: number;
}) {
  const pad: [number, number, number, number] = [10, 12, 26, 30];
  const [pt, pr, pb, pl] = pad;
  const x0 = pl, x1 = w - pr, y0 = pt, y1 = h - pb;
  const peak = Math.max(...healthy.map((b) => b.n), 1);
  const bw = (x1 - x0) / healthy.length;
  const yOf = (n: number) => y1 - Math.pow(n / peak, 0.62) * (y1 - y0);

  return (
    <Frame w={w} h={h} pad={pad} caption={xLabel}>
      {shadeFrom !== undefined && (
        <rect
          x={scale(shadeFrom, lo, hi, x0, x1)} y={y0}
          width={Math.max(0, x1 - scale(shadeFrom, lo, hi, x0, x1))}
          height={y1 - y0} fill="#A81E12" fillOpacity="0.055"
        />
      )}
      {healthy.map((b, i) =>
        b.n ? (
          <rect key={`h${i}`} x={x0 + i * bw + 0.6} y={yOf(b.n)}
            width={bw - 1.2} height={y1 - yOf(b.n)} fill="#12508C" fillOpacity="0.28" />
        ) : null
      )}
      {defect.map((b, i) =>
        b.n ? (
          <rect key={`d${i}`} x={x0 + i * bw + 0.6} y={yOf(b.n)}
            width={bw - 1.2} height={y1 - yOf(b.n)} fill="#A81E12" fillOpacity="0.9" />
        ) : null
      )}
      <LimitLine x={scale(limit, lo, hi, x0, x1)} top={y0} bottom={y1}
        label={limitLabel} side={limitSide} />
      {ticks.map((t) => (
        <g key={t}>
          <line x1={scale(t, lo, hi, x0, x1)} x2={scale(t, lo, hi, x0, x1)}
            y1={y1} y2={y1 + 3} stroke="#9CA2AB" />
          <Tick x={scale(t, lo, hi, x0, x1)} y={y1 + 12} label={String(t)} />
        </g>
      ))}
      <Tick x={(x0 + x1) / 2} y={h - 3} label={xLabel} />
    </Frame>
  );
}

/** A horizontal bar meter - sub-score contributions, z magnitudes. */
export function Bar({
  value, max, color = "#12508C", height = 6,
}: { value: number; max: number; color?: string; height?: number }) {
  const pct = Math.max(0, Math.min(1, value / max)) * 100;
  return (
    <div className="panel-sunk h-[8px] w-full rounded-none" style={{ height: height + 2 }}>
      <div
        className="h-full transition-[width] duration-700 ease-out"
        style={{ width: `${pct}%`, background: color }}
      />
    </div>
  );
}
