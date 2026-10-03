"use client";

import { useMemo, useRef, useState } from "react";
import { C } from "@/lib/theme";

/* A multi-series line chart for measured degradation curves.
 *
 * One y-axis. Background series are thin; highlighted series (the parts that
 * reached end of life) are drawn heavier and direct-labelled at their end, so
 * identity never rests on colour alone. Thresholds are dashed reference lines
 * with a text label; a shaded band marks a named time window. Hovering finds
 * the nearest measured point and shows it - the chart draws only measured
 * points joined by straight segments, nothing is smoothed. */

export interface Series {
  id: string;
  color: string;
  points: [number, number][];
  strong?: boolean;
  endLabel?: string;
}

export function LineChart({
  series, xLabel, yLabel, thresholds = [], band, legend = [], height = 300,
  fmtX = (v) => v.toFixed(0), fmtY = (v) => v.toFixed(1), unitY = "", ariaLabel,
}: {
  series: Series[];
  xLabel: string;
  yLabel: string;
  thresholds?: { y: number; label: string }[];
  band?: { x0: number; x1: number; label: string };
  legend?: { label: string; color: string }[];
  height?: number;
  fmtX?: (v: number) => string;
  fmtY?: (v: number) => string;
  unitY?: string;
  ariaLabel: string;
}) {
  const W = 760, L = 52, R = 96, T = 14, B = 38;
  const H = height;
  const ref = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<{ s: Series; p: [number, number] } | null>(null);

  const { x0, x1, y0, y1 } = useMemo(() => {
    const xs = series.flatMap((s) => s.points.map((p) => p[0]));
    const ys = series.flatMap((s) => s.points.map((p) => p[1])).concat(thresholds.map((t) => t.y));
    const lo = Math.min(0, ...ys);
    const hi = Math.max(...ys);
    const pad = (hi - lo) * 0.06 || 1;
    return { x0: Math.min(...xs), x1: Math.max(...xs), y0: lo - (lo < 0 ? pad : 0), y1: hi + pad };
  }, [series, thresholds]);

  const x = (v: number) => L + ((v - x0) / (x1 - x0 || 1)) * (W - L - R);
  const y = (v: number) => T + (1 - (v - y0) / (y1 - y0 || 1)) * (H - T - B);
  const ticks = (a: number, b: number, n = 5) => {
    const step = Math.pow(10, Math.floor(Math.log10((b - a) / n || 1)));
    const nice = [1, 2, 2.5, 5, 10].map((m) => m * step).find((s) => (b - a) / s <= n) ?? step * 10;
    const out = [];
    for (let v = Math.ceil(a / nice) * nice; v <= b + 1e-9; v += nice) out.push(+v.toFixed(10));
    return out;
  };

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = ref.current?.getBoundingClientRect();
    if (!r) return;
    const mx = ((e.clientX - r.left) / r.width) * W;
    const my = ((e.clientY - r.top) / r.height) * H;
    let best: { s: Series; p: [number, number]; d: number } | null = null;
    for (const s of series) {
      for (const p of s.points) {
        const d = (x(p[0]) - mx) ** 2 + (y(p[1]) - my) ** 2;
        if (!best || d < best.d) best = { s, p, d };
      }
    }
    setHover(best && best.d < 900 ? { s: best.s, p: best.p } : null);
  };

  const ordered = [...series].sort((a, b) => Number(!!a.strong) - Number(!!b.strong));

  // Tick labels stay short so they never run into the axis title (5000 % -> 5k %).
  const yTicks = ticks(y0, y1);
  const tickStep = yTicks.length > 1 ? yTicks[1] - yTicks[0] : 1;
  const fmtTick = (v: number) =>
    Math.abs(v) >= 1000 ? `${+(v / 1000).toFixed(1)}k` : tickStep >= 1 ? v.toFixed(0) : fmtY(v);

  // End labels: place each one, nudging it up or down in 12 px steps until it
  // clears the labels already placed (and the threshold labels). A label with
  // no free slot nearby is left to the hover tooltip rather than overprinted.
  const endLabels = useMemo(() => {
    const boxes: { x: number; y: number; w: number }[] = thresholds.map((t) => ({ x: W - R + 4, y: y(t.y), w: 6.2 * t.label.length }));
    const out: { id: string; x: number; y: number; text: string }[] = [];
    const strong = series.filter((s) => s.strong && s.endLabel && s.points.length)
      .map((s) => ({ s, last: s.points[s.points.length - 1] }))
      .sort((a, b) => y(a.last[1]) - y(b.last[1]));
    for (const { s, last } of strong) {
      const lx = x(last[0]) + 5, w = 7 * (s.endLabel as string).length;
      for (const dy of [0, -12, 12, -24, 24, -36, 36]) {
        const ly = y(last[1]) + dy;
        if (ly < T + 4 || ly > H - B) continue;
        if (boxes.every((b) => lx + w < b.x || b.x + b.w < lx || Math.abs(ly - b.y) >= 12)) {
          boxes.push({ x: lx, y: ly, w });
          out.push({ id: s.id, x: lx, y: ly, text: s.endLabel as string });
          break;
        }
      }
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [series, thresholds, x0, x1, y0, y1, H]);

  return (
    <div>
      {legend.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-4 text-xs text-graphite" aria-label="Legend">
          {legend.map((l) => (
            <span key={l.label} className="flex items-center gap-1.5">
              <span className="h-0.5 w-4" style={{ background: l.color }} />{l.label}
            </span>
          ))}
        </div>
      )}
      <div className="relative overflow-x-auto">
        <svg ref={ref} viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[520px]" role="img" aria-label={ariaLabel}
          onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
          {band && (
            <g>
              <rect x={x(band.x0)} y={T} width={Math.max(0, x(band.x1) - x(band.x0))} height={H - T - B}
                fill={C.well} />
              <text x={x(band.x0) + 4} y={T + 12} fontSize={10.5} fill={C.mute}>{band.label}</text>
            </g>
          )}
          {yTicks.map((v) => (
            <g key={`y${v}`}>
              <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke={C.hair} />
              <text x={L - 6} y={y(v) + 4} textAnchor="end" fontSize={11} fill={C.mute}>{fmtTick(v)}{unitY}</text>
            </g>
          ))}
          {ticks(x0, x1, 7).map((v) => (
            <text key={`x${v}`} x={x(v)} y={H - B + 16} textAnchor="middle" fontSize={11} fill={C.mute}>{fmtX(v)}</text>
          ))}
          <text x={(L + W - R) / 2} y={H - 4} textAnchor="middle" fontSize={11} fill={C.graphite}>{xLabel}</text>
          <text x={12} y={T + (H - T - B) / 2} transform={`rotate(-90 12 ${T + (H - T - B) / 2})`}
            textAnchor="middle" fontSize={11} fill={C.graphite}>{yLabel}</text>

          {thresholds.map((t) => (
            <g key={t.label}>
              <line x1={L} x2={W - R} y1={y(t.y)} y2={y(t.y)} stroke={C.ink} strokeWidth={1.25} strokeDasharray="6 4" />
              <text x={W - R + 4} y={y(t.y) + 4} fontSize={10.5} fill={C.ink}>{t.label}</text>
            </g>
          ))}

          {ordered.map((s) => {
            const d = s.points.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join("");
            return (
              <g key={s.id} opacity={hover && hover.s.id !== s.id && !s.strong ? 0.45 : 1}>
                <path d={d} fill="none" stroke={s.color} strokeWidth={s.strong ? 2.25 : 1.1}
                  strokeLinejoin="round" strokeLinecap="round" opacity={s.strong ? 1 : 0.75} />
              </g>
            );
          })}
          {endLabels.map((l) => (
            <text key={`lab${l.id}`} x={l.x} y={l.y + 4} fontSize={10.5} fill={C.ink} fontWeight={700}>{l.text}</text>
          ))}
          {hover && (
            <circle cx={x(hover.p[0])} cy={y(hover.p[1])} r={4.5} fill={hover.s.color} stroke={C.sheet} strokeWidth={2} />
          )}
        </svg>
        {hover && (
          <div className="pointer-events-none absolute rounded-ctl border border-rule bg-sheet px-2 py-1 text-xs shadow"
            style={{ left: `${(x(hover.p[0]) / W) * 100}%`, top: `${(y(hover.p[1]) / H) * 100}%`, transform: "translate(-50%, -135%)" }}>
            <strong>{hover.s.id}</strong> · {xLabel.split(" ")[0].toLowerCase()} {fmtX(hover.p[0])}: {fmtY(hover.p[1])}{unitY}
          </div>
        )}
      </div>
    </div>
  );
}
