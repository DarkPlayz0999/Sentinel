import { ReactNode } from "react";
import { C } from "@/lib/theme";

/* Plot primitives. Inline SVG, no chart library: every tick, limit line and
 * marker on an instrument plot is placed deliberately, and bending a generic
 * chart library into that shape costs more code than drawing it. */

export const scale = (v: number, d0: number, d1: number, r0: number, r1: number) =>
  r0 + ((v - d0) / (d1 - d0 || 1)) * (r1 - r0);

/** Axis label size in viewBox units. Charts render at ~1:1 in their cards,
 *  so this is close to real pixels - never below 11. */
export const FS = 11;

export function Frame({
  w, h, pad, children, caption,
}: {
  w: number; h: number; pad: [number, number, number, number];
  children: ReactNode; caption?: string;
}) {
  const [pt, pr, pb, pl] = pad;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="block h-auto w-full" role="img" aria-label={caption}>
      {caption ? <title>{caption}</title> : null}
      <rect x={pl} y={pt} width={w - pl - pr} height={h - pt - pb} fill={C.well} />
      {children}
    </svg>
  );
}

export function Tick({
  x, y, label, anchor = "middle", color = C.mute,
}: { x: number; y: number; label: string; anchor?: "start" | "middle" | "end"; color?: string }) {
  return (
    <text x={x} y={y} textAnchor={anchor} fontSize={FS} fill={color}>
      {label}
    </text>
  );
}

/** A vertical limit line with its label hanging at the top. */
export function LimitLine({
  x, top, bottom, label, color = C.reject, dashed = false, side = "right",
}: {
  x: number; top: number; bottom: number; label: string;
  color?: string; dashed?: boolean; side?: "left" | "right";
}) {
  return (
    <g>
      <line x1={x} x2={x} y1={top} y2={bottom} stroke={color} strokeWidth="1.5"
        strokeDasharray={dashed ? "4 3" : undefined} />
      <text x={side === "right" ? x + 5 : x - 5} y={top + 13}
        textAnchor={side === "right" ? "start" : "end"} fontSize={FS} fontWeight={600} fill={color}>
        {label}
      </text>
    </g>
  );
}

/** Round tick values across a domain. */
export function ticksFor(lo: number, hi: number, n = 5): number[] {
  const span = hi - lo;
  if (!(span > 0)) return [lo];
  const raw = span / n;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? mag * 10;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) {
    out.push(Math.round(v * 1e6) / 1e6);
  }
  return out;
}

export const fmtTick = (v: number) =>
  Math.abs(v) >= 10 ? v.toFixed(0) : Math.abs(v) >= 1 ? v.toFixed(1) : v.toFixed(2);
