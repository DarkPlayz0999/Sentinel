"use client";

/* Engineering charts.
 *
 * Inline SVG on top of the Frame/scale/Tick/LimitLine primitives already in
 * components/lab/plot.tsx. recharts is in package.json; it is not used here
 * for the same reason plot.tsx gives - every tick, limit line and callout on
 * an instrument plot is placed deliberately, and styling a generic chart
 * library into looking like a tester printout costs more code than drawing it.
 *
 * Each chart answers exactly one engineering question, named in its docstring.
 * None of them is decorative. */

import { Frame, LimitLine, Tick, scale } from "@/components/lab/plot";
import { UNIT_LABEL } from "@/components/ui/kit";
import type { Bin } from "@/lib/console";

const INK = "#0F1317";
const DIM = "#59616D";
const FAINT = "#8C939E";
const RULE = "#9CA2AB";
const BLUE = "#12508C";
const GREEN = "#186B45";
const AMBER = "#9A5B06";
const RED = "#A81E12";

const u = (s: string) => UNIT_LABEL[s] ?? s;

/** Pick ~5 round tick values across a domain. */
function ticksFor(lo: number, hi: number, n = 5): number[] {
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

const fmtTick = (v: number) =>
  Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(0) : v.toFixed(1);

/* =====================================================================
 * A. LOT DISTRIBUTION
 * "Where does this component sit inside its own lot's population?"
 * ===================================================================== */
export function LotDistribution({
  bins,
  defectBins,
  lo,
  hi,
  unitName,
  usl,
  med,
  sig,
  marker,
  markerLabel,
  sigmaBands = [3, 6],
  w = 560,
  h = 232,
}: {
  bins: Bin[];
  defectBins?: Bin[];
  lo: number;
  hi: number;
  unitName: string;
  usl?: number;
  med: number;
  sig: number;
  marker?: number;
  markerLabel?: string;
  sigmaBands?: number[];
  w?: number;
  h?: number;
}) {
  const pad: [number, number, number, number] = [14, 16, 42, 40];
  const [pt, pr, pb, pl] = pad;
  const x0 = pl, x1 = w - pr, y0 = pt, y1 = h - pb;
  const peak = Math.max(...bins.map((b) => b.n), 1);
  const bw = (x1 - x0) / bins.length;
  // sqrt-ish compression: a lognormal lot has one tall bin and a long tail,
  // and a linear count axis would flatten the tail into invisibility.
  const yOf = (n: number) => y1 - Math.pow(n / peak, 0.62) * (y1 - y0);
  const X = (v: number) => scale(v, lo, hi, x0, x1);

  return (
    <Frame w={w} h={h} pad={pad} caption={`Lot distribution, ${unitName}`}>
      {/* robust sigma bands - the reference the screen actually judges against */}
      {sigmaBands.map((k) => {
        const a = X(med + k * sig);
        if (!Number.isFinite(a) || a > x1) return null;
        return (
          <g key={k}>
            <line x1={a} x2={a} y1={y0} y2={y1} stroke={BLUE} strokeOpacity="0.45"
              strokeWidth="1" strokeDasharray="2 3" />
            <text x={a + 3} y={y0 + 10} className="font-mono"
              style={{ fontSize: 8, fill: BLUE, fillOpacity: 0.75 }}>
              +{k}σ
            </text>
          </g>
        );
      })}

      {/* lot population */}
      {bins.map((b, i) =>
        b.n ? (
          <rect key={`p${i}`} x={x0 + i * bw + 0.5} y={yOf(b.n)}
            width={Math.max(0.8, bw - 1)} height={y1 - yOf(b.n)}
            fill={BLUE} fillOpacity="0.26" />
        ) : null
      )}
      {/* labelled latent-defect subset, where ground truth is shown */}
      {defectBins?.map((b, i) =>
        b.n ? (
          <rect key={`d${i}`} x={x0 + i * bw + 0.5} y={yOf(b.n)}
            width={Math.max(0.8, bw - 1)} height={y1 - yOf(b.n)}
            fill={RED} fillOpacity="0.82" />
        ) : null
      )}

      {/* lot median - the dynamic reference */}
      <line x1={X(med)} x2={X(med)} y1={y0} y2={y1} stroke={INK} strokeWidth="1.25" />
      <text x={X(med)} y={y0 - 4} textAnchor="middle" className="font-mono"
        style={{ fontSize: 8.5, fill: INK, letterSpacing: "0.06em" }}>
        LOT MEDIAN {fmtTick(med)}
      </text>

      {usl !== undefined && usl <= hi && (
        <LimitLine x={X(usl)} top={y0} bottom={y1}
          label={`USL ${usl} ${u(unitName)}`} side={X(usl) > x1 - 70 ? "left" : "right"} />
      )}

      {/* the selected component */}
      {marker !== undefined && Number.isFinite(marker) && (
        <g>
          <line x1={X(marker)} x2={X(marker)} y1={y0} y2={y1 + 6}
            stroke={RED} strokeWidth="1.5" />
          <circle cx={X(marker)} cy={y1 + 6} r="4" fill={RED} />
          <text x={X(marker)} y={y1 + 22} textAnchor="middle" className="font-mono"
            style={{ fontSize: 9, fill: RED, fontWeight: 700 }}>
            {markerLabel ?? `${fmtTick(marker)} ${u(unitName)}`}
          </text>
        </g>
      )}

      {ticksFor(lo, hi).map((t) => (
        <g key={t}>
          <line x1={X(t)} x2={X(t)} y1={y1} y2={y1 + 3} stroke={RULE} />
          <Tick x={X(t)} y={y1 + 12} label={fmtTick(t)} />
        </g>
      ))}
      <text x={(x0 + x1) / 2} y={h - 4} textAnchor="middle" className="font-mono"
        style={{ fontSize: 8.5, fill: FAINT, letterSpacing: "0.1em" }}>
        {unitName.replace(/_/g, " ")} ({u(unitName)}) — COMPONENT COUNT ON Y
      </text>
    </Frame>
  );
}

/* =====================================================================
 * B. BURN-IN TRAJECTORY
 * "Where is this component heading by 168 h, and how does that compare
 *  with the lot it came from?"
 * ===================================================================== */
export function Trajectory({
  hours,
  values,
  envelope,
  usl,
  forecast,
  unitName,
  serial,
  drawn = true,
  w = 560,
  h = 244,
}: {
  hours: number[];
  values: (number | null)[];
  envelope?: { p05: number[]; p50: number[]; p95: number[] };
  usl?: number;
  forecast?: number | null;
  unitName: string;
  serial?: string;
  drawn?: boolean;
  w?: number;
  h?: number;
}) {
  const pad: [number, number, number, number] = [14, 58, 34, 46];
  const [pt, pr, pb, pl] = pad;
  const x0 = pl, x1 = w - pr, y0 = pt, y1 = h - pb;

  const finite = (xs: (number | null)[]) => xs.filter((v): v is number => v !== null && Number.isFinite(v));
  const pool = [
    ...finite(values),
    ...(envelope ? [...envelope.p05, ...envelope.p95] : []),
    ...(forecast != null ? [forecast] : []),
  ];
  let lo = Math.min(...pool);
  let hi = Math.max(...pool);
  // Keep the USL in frame only when it is within reach; otherwise the trace
  // collapses into a flat line at the bottom of a mostly empty plot.
  if (usl !== undefined && hi > usl * 0.55) hi = Math.max(hi, usl * 1.02);
  const padY = (hi - lo) * 0.14 || 1;
  lo -= padY; hi += padY;

  const X = (t: number) => scale(t, 0, 168, x0, x1);
  const Y = (v: number) => scale(v, lo, hi, y1, y0);

  const path = (xs: number[], ys: number[]) =>
    xs.map((t, i) => `${i ? "L" : "M"}${X(t).toFixed(2)},${Y(ys[i]).toFixed(2)}`).join(" ");

  const measured = values
    .map((v, i) => (v !== null && Number.isFinite(v) ? { t: hours[i], v } : null))
    .filter((p): p is { t: number; v: number } => p !== null);

  return (
    <Frame w={w} h={h} pad={pad} caption={`Burn-in trajectory, ${unitName}`}>
      {/* lot 5th-95th percentile envelope */}
      {envelope && (
        <>
          <path
            d={`${path(hours, envelope.p95)} L${X(hours[hours.length - 1])},${Y(
              envelope.p05[envelope.p05.length - 1]
            )} ${hours
              .slice()
              .reverse()
              .map((t, i) => `L${X(t)},${Y(envelope.p05[hours.length - 1 - i])}`)
              .join(" ")} Z`}
            fill={BLUE}
            fillOpacity="0.13"
          />
          <path d={path(hours, envelope.p50)} fill="none" stroke={BLUE}
            strokeWidth="1.1" strokeDasharray="5 3" strokeOpacity="0.85" />
        </>
      )}

      {/* read-point rules */}
      {hours.map((t) => (
        <line key={t} x1={X(t)} x2={X(t)} y1={y0} y2={y1}
          stroke={RULE} strokeOpacity="0.4" strokeWidth="0.75" strokeDasharray="1 3" />
      ))}

      {usl !== undefined && usl <= hi && usl >= lo && (
        <g>
          <line x1={x0} x2={x1} y1={Y(usl)} y2={Y(usl)} stroke={RED} strokeWidth="1.25" />
          <text x={x1 + 4} y={Y(usl) + 3} className="font-mono"
            style={{ fontSize: 8, fill: RED, letterSpacing: "0.05em" }}>
            USL {usl}
          </text>
        </g>
      )}

      {/* forecast: 24h -> predicted 168h, dashed. MEASURED vs FORECAST must
          never be the same stroke - that is the whole point of Module B. */}
      {forecast != null && Number.isFinite(forecast) && measured.length > 1 && (
        <g>
          <path
            d={`M${X(measured[1].t)},${Y(measured[1].v)} L${X(168)},${Y(forecast)}`}
            fill="none" stroke={AMBER} strokeWidth="1.6" strokeDasharray="5 4"
          />
          <path d={`M${X(168) - 4.5},${Y(forecast)} l4.5,-4.5 l4.5,4.5 l-4.5,4.5 Z`}
            fill={AMBER} />
          <text x={X(168) + 4} y={Y(forecast) - 7} className="font-mono"
            style={{ fontSize: 8, fill: AMBER, fontWeight: 700 }}>
            FCST
          </text>
        </g>
      )}

      {/* the measured trace */}
      <path
        d={path(measured.map((p) => p.t), measured.map((p) => p.v))}
        fill="none" stroke={RED} strokeWidth="1.9"
        strokeDasharray={drawn ? undefined : "600"}
        className={drawn ? undefined : "animate-trace"}
      />
      {measured.map((p) => (
        <circle key={p.t} cx={X(p.t)} cy={Y(p.v)} r="3.1" fill="#FFFFFF"
          stroke={RED} strokeWidth="1.6" />
      ))}

      {/* y ticks */}
      {ticksFor(lo, hi, 4).map((t) => (
        <g key={t}>
          <line x1={x0 - 3} x2={x0} y1={Y(t)} y2={Y(t)} stroke={RULE} />
          <text x={x0 - 5} y={Y(t) + 3} textAnchor="end" className="font-mono"
            style={{ fontSize: 8.5, fill: FAINT }}>
            {fmtTick(t)}
          </text>
        </g>
      ))}
      {hours.map((t) => (
        <g key={`x${t}`}>
          <line x1={X(t)} x2={X(t)} y1={y1} y2={y1 + 3} stroke={RULE} />
          <Tick x={X(t)} y={y1 + 12} label={`${t}h`} />
        </g>
      ))}
      <text x={(x0 + x1) / 2} y={h - 3} textAnchor="middle" className="font-mono"
        style={{ fontSize: 8, fill: FAINT, letterSpacing: "0.1em" }}>
        BURN-IN HOURS AT 125 °C {serial ? `· ${serial}` : ""} · {u(unitName)}
      </text>
    </Frame>
  );
}

/* =====================================================================
 * C. RISK COMPOSITION
 * "What evidence produced this risk score?"
 * ===================================================================== */
export function RiskComposition({
  subScores,
  values,
  weights,
  total,
  w = 560,
  h = 176,
}: {
  subScores: string[];
  values: number[];
  weights: Record<string, number>;
  total: number;
  w?: number;
  h?: number;
}) {
  const pad: [number, number, number, number] = [16, 54, 26, 108];
  const [pt, pr, pb, pl] = pad;
  const x0 = pl, x1 = w - pr, y0 = pt, y1 = h - pb;
  const rows = subScores.length;
  const rowH = (y1 - y0) / rows;
  const X = (v: number) => scale(v, 0, 100, x0, x1);

  return (
    <Frame w={w} h={h} pad={pad} caption="Risk score composition">
      {[0, 25, 50, 75, 100].map((g) => (
        <g key={g}>
          <line x1={X(g)} x2={X(g)} y1={y0} y2={y1} stroke={RULE}
            strokeOpacity={g === 0 ? 0.7 : 0.3} strokeWidth="0.75" />
          <Tick x={X(g)} y={y1 + 11} label={String(g)} />
        </g>
      ))}

      {subScores.map((name, i) => {
        const v = values[i] ?? 0;
        const wt = weights[name] ?? 0;
        const cy = y0 + i * rowH + rowH / 2;
        const bh = Math.min(13, rowH - 6);
        // Weighted contribution is what actually reaches the total; the pale
        // bar behind is the raw sub-score, so an inspector can see both the
        // evidence and the weight it was given.
        return (
          <g key={name}>
            <text x={x0 - 6} y={cy + 3} textAnchor="end" className="font-mono"
              style={{ fontSize: 8.5, fill: DIM, letterSpacing: "0.04em" }}>
              {name.replace(/_/g, " ")}
            </text>
            <rect x={x0} y={cy - bh / 2} width={Math.max(0, X(v) - x0)} height={bh}
              fill={BLUE} fillOpacity="0.22" />
            <rect x={x0} y={cy - bh / 2} width={Math.max(0, X(v * wt) - x0)} height={bh}
              fill={BLUE} />
            <text x={X(v) + 5} y={cy + 3} className="font-mono"
              style={{ fontSize: 8.5, fill: INK, fontWeight: 600 }}>
              {v.toFixed(0)}
            </text>
            <text x={x1 + 6} y={cy + 3} className="font-mono"
              style={{ fontSize: 8, fill: FAINT }}>
              ×{(wt * 100).toFixed(0)}%
            </text>
          </g>
        );
      })}
      <text x={x0} y={h - 3} className="font-mono"
        style={{ fontSize: 8, fill: FAINT, letterSpacing: "0.08em" }}>
        PALE = SUB-SCORE · SOLID = WEIGHTED CONTRIBUTION · TOTAL {total.toFixed(1)}/100
      </text>
    </Frame>
  );
}

/* =====================================================================
 * D. RECALL vs OVERKILL
 * "What does more detection cost in good silicon?"
 * ===================================================================== */
export function RecallOverkill({
  points,
  mark,
  w = 560,
  h = 224,
}: {
  points: { overkill: number; recall: number }[];
  mark?: { overkill: number; recall: number };
  w?: number;
  h?: number;
}) {
  const pad: [number, number, number, number] = [14, 18, 34, 42];
  const [pt, pr, pb, pl] = pad;
  const x0 = pl, x1 = w - pr, y0 = pt, y1 = h - pb;
  const X = (v: number) => scale(Math.min(v, 0.3), 0, 0.3, x0, x1);
  const Y = (v: number) => scale(v, 0, 1, y1, y0);

  const d = points
    .filter((p) => p.overkill <= 0.3)
    .map((p, i) => `${i ? "L" : "M"}${X(p.overkill).toFixed(2)},${Y(p.recall).toFixed(2)}`)
    .join(" ");

  return (
    <Frame w={w} h={h} pad={pad} caption="Recall against the over-rejection budget">
      {[0, 0.25, 0.5, 0.75, 1].map((g) => (
        <g key={g}>
          <line x1={x0} x2={x1} y1={Y(g)} y2={Y(g)} stroke={RULE}
            strokeOpacity="0.3" strokeWidth="0.75" />
          <text x={x0 - 5} y={Y(g) + 3} textAnchor="end" className="font-mono"
            style={{ fontSize: 8.5, fill: FAINT }}>
            {g.toFixed(2)}
          </text>
        </g>
      ))}
      {[0.05, 0.1].map((b) => (
        <g key={b}>
          <line x1={X(b)} x2={X(b)} y1={y0} y2={y1} stroke={GREEN}
            strokeOpacity="0.5" strokeWidth="1" strokeDasharray="3 3" />
          <text x={X(b) + 3} y={y0 + 9} className="font-mono"
            style={{ fontSize: 7.5, fill: GREEN }}>
            {b * 100}% budget
          </text>
        </g>
      ))}
      <path d={d} fill="none" stroke={BLUE} strokeWidth="1.8" />
      {mark && (
        <g>
          <circle cx={X(mark.overkill)} cy={Y(mark.recall)} r="4.5" fill={RED} />
          <circle cx={X(mark.overkill)} cy={Y(mark.recall)} r="8" fill="none"
            stroke={RED} strokeWidth="1" strokeOpacity="0.5" />
        </g>
      )}
      {[0, 0.1, 0.2, 0.3].map((t) => (
        <g key={t}>
          <line x1={X(t)} x2={X(t)} y1={y1} y2={y1 + 3} stroke={RULE} />
          <Tick x={X(t)} y={y1 + 12} label={`${(t * 100).toFixed(0)}%`} />
        </g>
      ))}
      <text x={(x0 + x1) / 2} y={h - 3} textAnchor="middle" className="font-mono"
        style={{ fontSize: 8, fill: FAINT, letterSpacing: "0.1em" }}>
        OVERKILL — HEALTHY PARTS SCRAPPED · Y: LATENT-DEFECT RECALL
      </text>
    </Frame>
  );
}

/* =====================================================================
 * E. RISK SCORE HISTOGRAM with the verdict band edges
 * "Where do the three bands cut the population?"
 * ===================================================================== */
export function ScoreBands({
  bins, watch, reject, threshold, w = 560, h = 176,
}: {
  bins: Bin[]; watch: number; reject: number; threshold?: number; w?: number; h?: number;
}) {
  const pad: [number, number, number, number] = [16, 14, 32, 34];
  const [pt, pr, pb, pl] = pad;
  const x0 = pl, x1 = w - pr, y0 = pt, y1 = h - pb;
  const peak = Math.max(...bins.map((b) => b.n), 1);
  const bw = (x1 - x0) / bins.length;
  const yOf = (n: number) => y1 - Math.pow(n / peak, 0.6) * (y1 - y0);
  const X = (v: number) => scale(v, 0, 100, x0, x1);

  return (
    <Frame w={w} h={h} pad={pad} caption="Screening risk score distribution">
      <rect x={X(0)} y={y0} width={X(watch) - X(0)} height={y1 - y0}
        fill={GREEN} fillOpacity="0.05" />
      <rect x={X(watch)} y={y0} width={X(reject) - X(watch)} height={y1 - y0}
        fill={AMBER} fillOpacity="0.07" />
      <rect x={X(reject)} y={y0} width={x1 - X(reject)} height={y1 - y0}
        fill={RED} fillOpacity="0.07" />

      {bins.map((b, i) =>
        b.n ? (
          <rect key={i} x={x0 + i * bw + 0.4} y={yOf(b.n)}
            width={Math.max(0.8, bw - 0.8)} height={y1 - yOf(b.n)}
            fill={INK} fillOpacity="0.42" />
        ) : null
      )}

      {[
        { v: watch, c: AMBER, l: `WATCH ${watch.toFixed(1)}` },
        { v: reject, c: RED, l: `REJECT ${reject.toFixed(1)}` },
      ].map((b) => (
        <g key={b.l}>
          <line x1={X(b.v)} x2={X(b.v)} y1={y0} y2={y1} stroke={b.c} strokeWidth="1.3" />
          <text x={X(b.v) + 3} y={y0 + 9} className="font-mono"
            style={{ fontSize: 7.5, fill: b.c, fontWeight: 700 }}>
            {b.l}
          </text>
        </g>
      ))}
      {threshold !== undefined && (
        <g>
          <line x1={X(threshold)} x2={X(threshold)} y1={y0} y2={y1 + 5}
            stroke={INK} strokeWidth="1.5" strokeDasharray="3 2" />
          <text x={X(threshold)} y={y1 + 20} textAnchor="middle" className="font-mono"
            style={{ fontSize: 8, fill: INK, fontWeight: 700 }}>
            policy {threshold.toFixed(1)}
          </text>
        </g>
      )}
      {[0, 25, 50, 75, 100].map((t) => (
        <g key={t}>
          <line x1={X(t)} x2={X(t)} y1={y1} y2={y1 + 3} stroke={RULE} />
          <Tick x={X(t)} y={y1 + 11} label={String(t)} />
        </g>
      ))}
    </Frame>
  );
}

/* =====================================================================
 * F. LOT BAR — reject fraction against the PDA gate, one row per lot
 * "Which lot is misbehaving?"
 * ===================================================================== */
export function PdaBars({
  lots, limit, w = 560, h = 168,
}: {
  lots: { lot: string; rejectFrac: number; breach: boolean }[];
  limit: number; w?: number; h?: number;
}) {
  const pad: [number, number, number, number] = [14, 40, 28, 40];
  const [pt, pr, pb, pl] = pad;
  const x0 = pl, x1 = w - pr, y0 = pt, y1 = h - pb;
  const maxV = Math.max(limit * 2, ...lots.map((l) => l.rejectFrac)) * 1.1;
  const rowH = (y1 - y0) / lots.length;
  const X = (v: number) => scale(v, 0, maxV, x0, x1);

  return (
    <Frame w={w} h={h} pad={pad} caption="Per-lot reject fraction against the PDA gate">
      {lots.map((l, i) => {
        const cy = y0 + i * rowH + rowH / 2;
        const bh = Math.min(14, rowH - 5);
        return (
          <g key={l.lot}>
            <text x={x0 - 6} y={cy + 3} textAnchor="end" className="font-mono"
              style={{ fontSize: 9, fill: INK, fontWeight: 600 }}>
              {l.lot}
            </text>
            <rect x={x0} y={cy - bh / 2} width={Math.max(0.5, X(l.rejectFrac) - x0)}
              height={bh} fill={l.breach ? RED : BLUE} fillOpacity={l.breach ? 0.85 : 0.45} />
            <text x={X(l.rejectFrac) + 5} y={cy + 3} className="font-mono"
              style={{ fontSize: 8.5, fill: l.breach ? RED : DIM, fontWeight: 600 }}>
              {(l.rejectFrac * 100).toFixed(1)}%
            </text>
          </g>
        );
      })}
      <line x1={X(limit)} x2={X(limit)} y1={y0} y2={y1} stroke={RED}
        strokeWidth="1.3" strokeDasharray="4 3" />
      <text x={X(limit)} y={y0 - 4} textAnchor="middle" className="font-mono"
        style={{ fontSize: 8, fill: RED, fontWeight: 700 }}>
        PDA {(limit * 100).toFixed(0)}%
      </text>
    </Frame>
  );
}

/* =====================================================================
 * G. WAFER MAP — die grid coloured by risk
 * "Do the flags cluster anywhere on the wafer?"
 *
 * Honest caveat, carried from src/wafer.py: the generator draws (x, y)
 * uniformly at random and independently of class, so there is NO spatial
 * structure in this dataset to find. The view is here because it is how an
 * inspector actually looks at a lot, and it is ready for real wafer data.
 * ===================================================================== */
export function WaferMap({
  dies, selected, onSelect, size = 300,
}: {
  dies: { x: number; y: number; r: number; v: string; s: string }[];
  selected?: string;
  onSelect?: (serial: string) => void;
  size?: number;
}) {
  const grid = 60;
  const cell = size / grid;
  const tone = (v: string) => (v === "REJECT" ? RED : v === "WATCH" ? AMBER : GREEN);
  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="w-full" role="img" aria-label="Wafer map">
      <rect x="0" y="0" width={size} height={size} fill="#FCFCFB" />
      <circle cx={size / 2} cy={size / 2} r={size / 2 - 2} fill="none"
        stroke={RULE} strokeWidth="1" strokeDasharray="3 3" />
      {dies.map((d) => (
        <rect
          key={d.s}
          x={d.x * cell} y={d.y * cell}
          width={Math.max(2.6, cell * 0.92)} height={Math.max(2.6, cell * 0.92)}
          fill={tone(d.v)}
          fillOpacity={d.v === "ACCEPT" ? 0.24 : 0.9}
          stroke={d.s === selected ? INK : "none"}
          strokeWidth={d.s === selected ? 1.4 : 0}
          onClick={onSelect ? () => onSelect(d.s) : undefined}
          style={onSelect ? { cursor: "pointer" } : undefined}
        >
          <title>{`${d.s} · risk ${d.r.toFixed(1)} · ${d.v}`}</title>
        </rect>
      ))}
    </svg>
  );
}
