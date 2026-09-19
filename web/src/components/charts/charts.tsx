"use client";

/* Engineering charts. Each answers exactly one question, named in its
 * docstring. Colour: cobalt is the lot, stamp inks are verdicts and limits,
 * ink is the reference the part is judged against. */

import { FS, Frame, LimitLine, Tick, fmtTick, scale, ticksFor } from "@/components/charts/plot";
import { UNIT_LABEL } from "@/components/ui/kit";
import { C, VERDICT_COLOR } from "@/lib/theme";
import type { Bin } from "@/lib/console";

const u = (s: string) => UNIT_LABEL[s] ?? s;

/* =====================================================================
 * A. LOT DISTRIBUTION
 * "Where does this component sit inside its own lot's population?"
 * ===================================================================== */
export function LotDistribution({
  bins, defectBins, lo, hi, param, unitName, usl, med, bands = [], marker, markerLabel,
  w = 620, h = 250,
}: {
  bins: Bin[]; defectBins?: Bin[]; lo: number; hi: number;
  param: string; unitName: string; usl?: number; med: number;
  bands?: { k: number; x: number }[];
  marker?: number; markerLabel?: string; w?: number; h?: number;
}) {
  const pad: [number, number, number, number] = [26, 18, 50, 16];
  const [pt, pr, pb, pl] = pad;
  const x0 = pl, x1 = w - pr, y0 = pt, y1 = h - pb;
  const peak = Math.max(...bins.map((b) => b.n), 1);
  const bw = (x1 - x0) / bins.length;
  // A lognormal lot has one tall bin and a long tail; a linear count axis
  // would flatten the tail - the part of the lot that matters - into nothing.
  const yOf = (n: number) => y1 - Math.pow(n / peak, 0.62) * (y1 - y0);
  const X = (v: number) => scale(v, lo, hi, x0, x1);

  return (
    <Frame w={w} h={h} pad={pad} caption={`Lot distribution of ${param}`}>
      {bands.map((b) => {
        const a = X(b.x);
        if (!Number.isFinite(a) || a > x1 || a < x0) return null;
        return (
          <g key={b.k}>
            <line x1={a} x2={a} y1={y0} y2={y1} stroke={C.cobalt} strokeOpacity="0.55" strokeDasharray="3 3" />
            <text x={a + 4} y={y0 + 13} fontSize={FS} fill={C.cobalt}>+{b.k}σ</text>
          </g>
        );
      })}

      {bins.map((b, i) =>
        b.n ? (
          <rect key={`p${i}`} x={x0 + i * bw + 0.5} y={yOf(b.n)} width={Math.max(0.8, bw - 1)}
            height={y1 - yOf(b.n)} fill={C.cobalt} fillOpacity="0.3" />
        ) : null
      )}
      {defectBins?.map((b, i) =>
        b.n ? (
          <rect key={`d${i}`} x={x0 + i * bw + 0.5} y={yOf(b.n)} width={Math.max(0.8, bw - 1)}
            height={y1 - yOf(b.n)} fill={C.reject} fillOpacity="0.85" />
        ) : null
      )}

      <line x1={X(med)} x2={X(med)} y1={y0 - 8} y2={y1} stroke={C.ink} strokeWidth="1.5" />
      <text x={X(med)} y={y0 - 12} textAnchor="middle" fontSize={FS} fontWeight={600} fill={C.ink}>
        Lot median {med.toFixed(2)}
      </text>

      {usl !== undefined && usl <= hi && (
        <LimitLine x={X(usl)} top={y0} bottom={y1}
          label={`Datasheet limit ${usl} ${u(unitName)}`} side={X(usl) > x1 - 150 ? "left" : "right"} />
      )}

      {marker !== undefined && Number.isFinite(marker) && (
        <g>
          <line x1={X(marker)} x2={X(marker)} y1={y0} y2={y1 + 8} stroke={C.reject} strokeWidth="2" />
          <circle cx={X(marker)} cy={y1 + 8} r="4.5" fill={C.reject} />
          <text x={Math.min(Math.max(X(marker), x0 + 60), x1 - 60)} y={y1 + 26} textAnchor="middle"
            fontSize={FS + 1} fontWeight={700} fill={C.reject}>
            {markerLabel ?? `${fmtTick(marker)} ${u(unitName)}`}
          </text>
        </g>
      )}

      {ticksFor(lo, hi).map((t) => (
        <g key={t}>
          <line x1={X(t)} x2={X(t)} y1={y1} y2={y1 + 4} stroke={C.rule} />
          {marker === undefined && <Tick x={X(t)} y={y1 + 17} label={fmtTick(t)} />}
        </g>
      ))}
      <Tick x={(x0 + x1) / 2} y={h - 4}
        label={`${param} at 168 h (${u(unitName)}). Bar height is component count.`} />
    </Frame>
  );
}

/* =====================================================================
 * B. BURN-IN TRAJECTORY
 * "Where is this component heading by 168 h, and how does that compare
 *  with the lot it came from?"
 * ===================================================================== */
export function Trajectory({
  hours, values, envelope, usl, forecast, unitName, w = 620, h = 260,
}: {
  hours: number[];
  values: (number | null)[];
  envelope?: { p05: number[]; p50: number[]; p95: number[] };
  usl?: number;
  forecast?: number | null;
  unitName: string;
  w?: number; h?: number;
}) {
  const pad: [number, number, number, number] = [14, 74, 40, 48];
  const [pt, pr, pb, pl] = pad;
  const x0 = pl, x1 = w - pr, y0 = pt, y1 = h - pb;

  const finite = (xs: (number | null)[]) =>
    xs.filter((v): v is number => v !== null && Number.isFinite(v));
  const pool = [
    ...finite(values),
    ...(envelope ? [...envelope.p05, ...envelope.p95] : []),
    ...(forecast != null ? [forecast] : []),
  ];
  let lo = Math.min(...pool);
  let hi = Math.max(...pool);
  // Keep the limit in frame only when it is within reach; otherwise the trace
  // collapses into a flat line at the bottom of an empty plot.
  if (usl !== undefined && hi > usl * 0.55) hi = Math.max(hi, usl * 1.02);
  const padY = (hi - lo) * 0.12 || 1;
  lo -= padY; hi += padY;

  const X = (t: number) => scale(t, 0, 168, x0, x1);
  const Y = (v: number) => scale(v, lo, hi, y1, y0);
  const path = (xs: number[], ys: number[]) =>
    xs.map((t, i) => `${i ? "L" : "M"}${X(t).toFixed(2)},${Y(ys[i]).toFixed(2)}`).join(" ");

  const measured = values
    .map((v, i) => (v !== null && Number.isFinite(v) ? { t: hours[i], v } : null))
    .filter((p): p is { t: number; v: number } => p !== null);
  const last = measured[measured.length - 1];

  return (
    <Frame w={w} h={h} pad={pad} caption={`Burn-in trajectory of ${unitName}`}>
      {envelope && (
        <>
          <path
            d={`${path(hours, envelope.p95)} ${hours.slice().reverse()
              .map((t, i) => `L${X(t)},${Y(envelope.p05[hours.length - 1 - i])}`).join(" ")} Z`}
            fill={C.cobalt} fillOpacity="0.14"
          />
          <path d={path(hours, envelope.p50)} fill="none" stroke={C.cobalt} strokeWidth="1.25"
            strokeDasharray="5 3" />
          <text x={x1 + 6} y={Y(envelope.p50[envelope.p50.length - 1]) + 4} fontSize={FS} fill={C.cobalt}>
            Lot median
          </text>
        </>
      )}

      {hours.map((t) => (
        <line key={t} x1={X(t)} x2={X(t)} y1={y0} y2={y1} stroke={C.rule} strokeDasharray="1 3" />
      ))}

      {usl !== undefined && usl <= hi && usl >= lo && (
        <g>
          <line x1={x0} x2={x1} y1={Y(usl)} y2={Y(usl)} stroke={C.reject} strokeWidth="1.5" />
          <text x={x1 + 6} y={Y(usl) + 4} fontSize={FS} fontWeight={600} fill={C.reject}>
            Limit {usl}
          </text>
        </g>
      )}

      {/* Measured and forecast must never share a stroke - that is the point of Module B. */}
      {forecast != null && Number.isFinite(forecast) && measured.length > 1 && (
        <g>
          <path d={`M${X(measured[1].t)},${Y(measured[1].v)} L${X(168)},${Y(forecast)}`}
            fill="none" stroke={C.watch} strokeWidth="2" strokeDasharray="6 4" />
          <path d={`M${X(168) - 5},${Y(forecast)} l5,-5 l5,5 l-5,5 Z`} fill={C.watch} />
          <text x={x1 + 6} y={Y(forecast) + (last && Math.abs(Y(forecast) - Y(last.v)) < 14 ? 16 : 4)}
            fontSize={FS} fontWeight={600} fill={C.watch}>
            Forecast
          </text>
        </g>
      )}

      <path d={path(measured.map((p) => p.t), measured.map((p) => p.v))}
        fill="none" stroke={C.reject} strokeWidth="2.25" />
      {measured.map((p) => (
        <circle key={p.t} cx={X(p.t)} cy={Y(p.v)} r="3.5" fill={C.sheet} stroke={C.reject} strokeWidth="2" />
      ))}

      {ticksFor(lo, hi, 4).map((t) => (
        <g key={t}>
          <line x1={x0 - 4} x2={x0} y1={Y(t)} y2={Y(t)} stroke={C.rule} />
          <Tick x={x0 - 7} y={Y(t) + 4} label={fmtTick(t)} anchor="end" />
        </g>
      ))}
      {hours.map((t) => (
        <Tick key={`x${t}`} x={X(t)} y={y1 + 17} label={`${t} h`} />
      ))}
      <Tick x={(x0 + x1) / 2} y={h - 4} label={`Hours at 125 °C. Values in ${u(unitName)}.`} />
    </Frame>
  );
}

/* =====================================================================
 * C. RISK COMPOSITION
 * "What evidence produced this risk score?"
 * ===================================================================== */
export function RiskComposition({
  subScores, values, weights, total, w = 620, h = 210,
}: {
  subScores: string[]; values: number[]; weights: Record<string, number>; total: number;
  w?: number; h?: number;
}) {
  const pad: [number, number, number, number] = [10, 60, 44, 128];
  const [pt, pr, pb, pl] = pad;
  const x0 = pl, x1 = w - pr, y0 = pt, y1 = h - pb;
  const rowH = (y1 - y0) / subScores.length;
  const X = (v: number) => scale(v, 0, 100, x0, x1);
  const label = (s: string) => s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

  return (
    <Frame w={w} h={h} pad={pad} caption="Risk score composition">
      {[0, 25, 50, 75, 100].map((g) => (
        <g key={g}>
          <line x1={X(g)} x2={X(g)} y1={y0} y2={y1} stroke={C.rule} strokeOpacity={g ? 0.7 : 1} />
          <Tick x={X(g)} y={y1 + 16} label={String(g)} />
        </g>
      ))}
      {subScores.map((name, i) => {
        const v = values[i] ?? 0;
        const wt = weights[name] ?? 0;
        const cy = y0 + i * rowH + rowH / 2;
        const bh = Math.min(16, rowH - 8);
        // Pale bar = the raw sub-score (the evidence); solid = what reached the
        // total after its fixed policy weight.
        return (
          <g key={name}>
            <text x={x0 - 8} y={cy + 4} textAnchor="end" fontSize={FS + 1} fill={C.graphite}>
              {label(name)}
            </text>
            <rect x={x0} y={cy - bh / 2} width={Math.max(0, X(v) - x0)} height={bh} fill={C.cobalt} fillOpacity="0.22" />
            <rect x={x0} y={cy - bh / 2} width={Math.max(0, X(v * wt) - x0)} height={bh} fill={C.cobalt} />
            <text x={Math.min(X(v) + 6, x1 - 4)} y={cy + 4} textAnchor={X(v) + 6 > x1 - 24 ? "end" : "start"}
              fontSize={FS} fontWeight={700} fill={C.ink}>
              {v.toFixed(0)}
            </text>
            <text x={x1 + 8} y={cy + 4} fontSize={FS} fill={C.mute}>×{(wt * 100).toFixed(0)}%</text>
          </g>
        );
      })}
      <Tick x={x0} y={h - 4} anchor="start"
        label={`Pale: sub-score. Solid: weighted contribution. Total ${total.toFixed(1)} of 100.`} />
    </Frame>
  );
}

/* =====================================================================
 * D. RECALL vs OVERKILL
 * "What does more detection cost in good silicon?"
 * ===================================================================== */
export function RecallOverkill({
  points, mark, w = 620, h = 250,
}: {
  points: { overkill: number; recall: number }[];
  mark?: { overkill: number; recall: number };
  w?: number; h?: number;
}) {
  const pad: [number, number, number, number] = [14, 20, 42, 46];
  const [pt, pr, pb, pl] = pad;
  const x0 = pl, x1 = w - pr, y0 = pt, y1 = h - pb;
  const X = (v: number) => scale(Math.min(v, 0.3), 0, 0.3, x0, x1);
  const Y = (v: number) => scale(v, 0, 1, y1, y0);
  const d = points.filter((p) => p.overkill <= 0.3)
    .map((p, i) => `${i ? "L" : "M"}${X(p.overkill).toFixed(2)},${Y(p.recall).toFixed(2)}`).join(" ");

  return (
    <Frame w={w} h={h} pad={pad} caption="Recall against the overkill budget">
      {[0, 0.25, 0.5, 0.75, 1].map((g) => (
        <g key={g}>
          <line x1={x0} x2={x1} y1={Y(g)} y2={Y(g)} stroke={C.rule} strokeOpacity="0.8" />
          <Tick x={x0 - 7} y={Y(g) + 4} label={`${(g * 100).toFixed(0)}%`} anchor="end" />
        </g>
      ))}
      {[0.05, 0.1].map((b) => (
        <g key={b}>
          <line x1={X(b)} x2={X(b)} y1={y0} y2={y1} stroke={C.pass} strokeDasharray="3 3" />
          <text x={X(b) + 5} y={y1 - 8} fontSize={FS} fill={C.pass}>{b * 100}% budget</text>
        </g>
      ))}
      <path d={d} fill="none" stroke={C.cobalt} strokeWidth="2.25" />
      {mark && (
        <g>
          <circle cx={X(mark.overkill)} cy={Y(mark.recall)} r="5" fill={C.reject} />
          <circle cx={X(mark.overkill)} cy={Y(mark.recall)} r="9.5" fill="none" stroke={C.reject} strokeOpacity="0.45" />
        </g>
      )}
      {[0, 0.1, 0.2, 0.3].map((t) => (
        <Tick key={t} x={X(t)} y={y1 + 17} label={`${(t * 100).toFixed(0)}%`} />
      ))}
      <Tick x={(x0 + x1) / 2} y={h - 4}
        label="Across: healthy parts scrapped (overkill). Up: latent defects caught (recall)." />
    </Frame>
  );
}

/* =====================================================================
 * E. RISK SCORE HISTOGRAM with the verdict band edges
 * "Where do the three bands cut the population?"
 * ===================================================================== */
export function ScoreBands({
  bins, watch, reject, threshold, w = 620, h = 210,
}: {
  bins: Bin[]; watch: number; reject: number; threshold?: number; w?: number; h?: number;
}) {
  const pad: [number, number, number, number] = [26, 14, threshold !== undefined ? 50 : 34, 14];
  const [pt, pr, pb, pl] = pad;
  const x0 = pl, x1 = w - pr, y0 = pt, y1 = h - pb;
  const peak = Math.max(...bins.map((b) => b.n), 1);
  const bw = (x1 - x0) / bins.length;
  const yOf = (n: number) => y1 - Math.pow(n / peak, 0.6) * (y1 - y0);
  const X = (v: number) => scale(v, 0, 100, x0, x1);
  const tone = (x: number) => (x >= reject ? C.reject : x >= watch ? C.watch : C.pass);

  return (
    <Frame w={w} h={h} pad={pad} caption="Screening risk score distribution">
      {bins.map((b, i) =>
        b.n ? (
          <rect key={i} x={x0 + i * bw + 0.5} y={yOf(b.n)} width={Math.max(0.8, bw - 1)}
            height={y1 - yOf(b.n)} fill={tone(b.x + bw / 2)} fillOpacity={b.x >= watch ? 0.9 : 0.45} />
        ) : null
      )}
      {[
        { v: watch, c: C.watch, l: `Watch from ${watch.toFixed(1)}` },
        { v: reject, c: C.reject, l: `Reject from ${reject.toFixed(1)}` },
      ].map((b) => (
        <g key={b.l}>
          <line x1={X(b.v)} x2={X(b.v)} y1={y0 - 16} y2={y1} stroke={b.c} strokeWidth="1.5" />
          <text x={X(b.v) + 5} y={y0 - 6} fontSize={FS} fontWeight={600} fill={b.c}>{b.l}</text>
        </g>
      ))}
      {threshold !== undefined && (
        <g>
          <line x1={X(threshold)} x2={X(threshold)} y1={y0} y2={y1 + 22} stroke={C.ink} strokeWidth="1.75" strokeDasharray="4 3" />
          <text x={X(threshold)} y={y1 + 36} textAnchor="middle" fontSize={FS} fontWeight={700} fill={C.ink}>
            Cost-optimal cut {threshold.toFixed(1)}
          </text>
        </g>
      )}
      {[0, 25, 50, 75, 100].map((t) => (
        <Tick key={t} x={X(t)} y={y1 + 16} label={String(t)} />
      ))}
    </Frame>
  );
}

/* =====================================================================
 * F. LOT BAR - reject fraction against the PDA gate, one row per lot
 * "Which lot is misbehaving?"
 * ===================================================================== */
export function PdaBars({
  lots, limit, w = 440, h = 210,
}: {
  lots: { lot: string; rejectFrac: number; breach: boolean }[];
  limit: number; w?: number; h?: number;
}) {
  const pad: [number, number, number, number] = [24, 56, 10, 46];
  const [pt, pr, pb, pl] = pad;
  const x0 = pl, x1 = w - pr, y0 = pt, y1 = h - pb;
  const maxV = Math.max(limit * 2, ...lots.map((l) => l.rejectFrac)) * 1.1;
  const rowH = (y1 - y0) / lots.length;
  const X = (v: number) => scale(v, 0, maxV, x0, x1);

  return (
    <Frame w={w} h={h} pad={pad} caption="Reject fraction per lot against the PDA gate">
      {lots.map((l, i) => {
        const cy = y0 + i * rowH + rowH / 2;
        const bh = Math.min(16, rowH - 8);
        return (
          <g key={l.lot}>
            <text x={x0 - 8} y={cy + 4} textAnchor="end" fontSize={FS + 1} fontWeight={600} fill={C.ink}>{l.lot}</text>
            <rect x={x0} y={cy - bh / 2} width={Math.max(1, X(l.rejectFrac) - x0)} height={bh}
              fill={l.breach ? C.reject : C.cobalt} fillOpacity={l.breach ? 0.9 : 0.5} />
            <text x={X(l.rejectFrac) + 6} y={cy + 4} fontSize={FS} fontWeight={600}
              fill={l.breach ? C.reject : C.graphite}>
              {(l.rejectFrac * 100).toFixed(1)}%
            </text>
          </g>
        );
      })}
      <line x1={X(limit)} x2={X(limit)} y1={y0 - 10} y2={y1} stroke={C.reject} strokeWidth="1.5" strokeDasharray="4 3" />
      <text x={X(limit)} y={y0 - 12} textAnchor="middle" fontSize={FS} fontWeight={700} fill={C.reject}>
        PDA gate {(limit * 100).toFixed(0)}%
      </text>
    </Frame>
  );
}

/* =====================================================================
 * G. WAFER MAP - die grid coloured by verdict
 * "Do the flags cluster anywhere on the wafer?"
 *
 * Honest caveat, carried from src/wafer.py: the generator draws (x, y)
 * uniformly at random and independently of class, so there is NO spatial
 * structure in this dataset to find. The view is here because it is how an
 * inspector looks at a lot, and it is ready for real wafer data.
 * ===================================================================== */
export function WaferMap({
  dies, selected, onSelect, size = 320,
}: {
  dies: { x: number; y: number; r: number; v: "ACCEPT" | "WATCH" | "REJECT"; s: string }[];
  selected?: string;
  onSelect?: (serial: string) => void;
  size?: number;
}) {
  const span = Math.max(60, ...dies.map((d) => Math.max(d.x, d.y) + 1));
  const cell = (size - 8) / span;
  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="block h-auto w-full" role="img" aria-label="Wafer map">
      {/* ponytail: the generator places dies on a square grid, so the field is
          drawn square; a round wafer outline would misstate the data. */}
      <rect x="0.75" y="0.75" width={size - 1.5} height={size - 1.5} rx="6" fill={C.well} stroke={C.rule} strokeWidth="1.5" />
      {dies.map((d) => (
        <rect
          key={d.s}
          x={4 + d.x * cell} y={4 + d.y * cell}
          width={Math.max(2.8, cell * 0.92)} height={Math.max(2.8, cell * 0.92)}
          fill={VERDICT_COLOR[d.v]}
          fillOpacity={d.v === "ACCEPT" ? 0.28 : 0.95}
          stroke={d.s === selected ? C.ink : "none"}
          strokeWidth={d.s === selected ? 1.5 : 0}
          onClick={onSelect ? () => onSelect(d.s) : undefined}
          style={onSelect ? { cursor: "pointer" } : undefined}
        >
          <title>{`${d.s}: risk ${d.r.toFixed(1)}, ${d.v.toLowerCase()}`}</title>
        </rect>
      ))}
    </svg>
  );
}
