"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Term } from "@/components/ui/term";
import { Part, median, robustSigma, useConsole } from "@/lib/console";
import { cn } from "@/lib/utils";

/* THE OVEN WINDOW - the one bold element on the site.
 *
 * Every dot is a real chip from batch L04 of the screened (simulated) dataset,
 * measured at 0, 24, 96 and 168 h. Between readings the position is
 * interpolated on a log scale, because these currents are lognormal. Drag the
 * copper handle through the week and watch L04-0348: it never crosses the
 * datasheet limit, but it leaves its batch behind. */

const LOT = "L04";
const HERO = "L04-0348";
const PI = 0;               // Iddq_uA
const USL = 50;
const HOURS = [0, 24, 96, 168];
const YMAX = 62;
const PLAY_MS = 7000;

// On the dark oven panel the verdict inks are lifted for contrast.
const DOT = "#8EBBDD", DEFECT = "#FF7A6B", HERO_C = "#F2A365", LIMIT = "#FF6B5E";

/** Reading at hour t, log-linear between the reads that exist. */
function at(m: (number | null)[], t: number): number | null {
  const pts = HOURS.map((h, i) => [h, m[i]] as const).filter(([, v]) => v != null && v > 0) as [number, number][];
  if (!pts.length) return null;
  if (t <= pts[0][0]) return pts[0][1];
  for (let i = 1; i < pts.length; i++) {
    const [h0, v0] = pts[i - 1], [h1, v1] = pts[i];
    if (t <= h1) return Math.exp(Math.log(v0) + ((t - h0) / (h1 - h0)) * (Math.log(v1) - Math.log(v0)));
  }
  return pts[pts.length - 1][1];
}

const reduced = () =>
  typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function Window({ parts }: { parts: Part[] }) {
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [band, setBand] = useState(false);
  const [reveal, setReveal] = useState(false);
  const raf = useRef<number>();

  // Phones get a taller, narrower chart so its labels stay readable.
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 640px)");
    const on = () => setNarrow(mq.matches);
    on();
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  const W = narrow ? 520 : 960, H = narrow ? 520 : 430, L = 46, R = narrow ? 118 : 190, T = 22, B = 44;
  const X = (i: number) => L + ((i * 0.6180339) % 1) * (W - L - R);
  const Y = (v: number) => H - B - (Math.min(v, YMAX) / YMAX) * (H - T - B);

  const now = useMemo(() => parts.map((p) => at(p.m[PI], t)), [parts, t]);
  const vals = now.filter((v): v is number => v != null);
  // SENTINEL's own yardstick: median +/- 3 robust sigma on log values. A
  // percentile band would be dragged up by the very failures it should expose.
  const logs = vals.map(Math.log);
  const lm = median(logs), ls = robustSigma(logs), mid = Math.exp(lm);
  const lo = Math.exp(lm - 3 * ls), hi = Math.exp(lm + 3 * ls);
  const hi_ = parts.findIndex((p) => p.s === HERO);
  const hv = now[hi_] ?? 0;
  const outOfFamily = hv > hi;

  const play = useCallback(() => {
    if (reduced()) { setT(168); return; }
    const start = performance.now() - (t >= 168 ? 0 : (t / 168) * PLAY_MS);
    setPlaying(true);
    const step = (ts: number) => {
      const f = Math.min(1, (ts - start) / PLAY_MS);
      setT(Math.round(f * 168 * 10) / 10);
      if (f < 1) raf.current = requestAnimationFrame(step);
      else setPlaying(false);
    };
    raf.current = requestAnimationFrame(step);
  }, [t]);
  const pause = () => { if (raf.current) cancelAnimationFrame(raf.current); setPlaying(false); };
  useEffect(() => () => { if (raf.current) cancelAnimationFrame(raf.current); }, []);

  const day = Math.min(7, Math.floor(t / 24) + 1);

  return (
    <div className="overflow-hidden rounded-[10px] bg-oven text-[#E7EFEC]">
      <div className="grid gap-6 p-5 sm:p-7 lg:grid-cols-[1fr_260px]">
        <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full" role="img"
          aria-label={`Batch ${LOT}, ${parts.length} chips, at hour ${Math.round(t)} of burn-in. Chip ${HERO} reads ${hv.toFixed(1)} microamps, below the ${USL} microamp limit${outOfFamily ? ", but outside the normal range for its batch" : ""}.`}>
          {/* y grid */}
          {[0, 10, 20, 30, 40, 50, 60].map((v) => (
            <g key={v}>
              <line x1={L} x2={W - R} y1={Y(v)} y2={Y(v)} stroke="#1E4A45" strokeWidth={1} />
              <text x={L - 10} y={Y(v) + 5} textAnchor="end" fontSize={14} fill="#9FB5B0">{v}</text>
            </g>
          ))}
          <text x={L - 10} y={T - 6} textAnchor="end" fontSize={14} fill="#9FB5B0">µA</text>

          {/* batch normal range */}
          <rect x={L} width={W - L - R} y={Y(hi)} height={Math.max(0, Y(lo) - Y(hi))}
            fill={DOT} fillOpacity={band ? 0.16 : 0} style={{ transition: "fill-opacity 300ms" }} />
          {band && (
            <text x={L + 10} y={Y(hi) - 8} fontSize={14} fill={DOT}>
              Normal for this batch right now: up to {hi.toFixed(1)} µA
            </text>
          )}

          {/* datasheet limit */}
          <line x1={L} x2={W - R} y1={Y(USL)} y2={Y(USL)} stroke={LIMIT} strokeWidth={2.5} />
          <text x={W - R + 12} y={Y(USL) - 4} fontSize={15} fontWeight={700} fill={LIMIT}>
            <tspan x={W - R + 12}>{narrow ? "Limit" : "Datasheet limit"}</tspan>
            <tspan x={W - R + 12} dy={18} fontWeight={400}>{narrow ? `${USL} µA` : `${USL} µA: below = PASS`}</tspan>
          </text>

          {/* the batch */}
          {parts.map((p, i) => {
            const v = now[i];
            if (v == null || i === hi_) return null;
            const bad = reveal && p.tc === "latent";
            const gross = reveal && p.tc === "gross";
            return (
              <circle key={p.s} cx={X(i)} cy={Y(v)} r={bad ? 5 : 4}
                fill={gross ? "none" : bad ? DEFECT : DOT} fillOpacity={bad ? 0.95 : 0.55}
                stroke={gross ? "#E7EFEC" : "none"} strokeWidth={1.5} />
            );
          })}

          {/* the chip to watch */}
          {hi_ >= 0 && (
            <g>
              <circle cx={X(hi_)} cy={Y(hv)} r={15} fill="none" stroke={HERO_C} strokeWidth={2.5} />
              <circle cx={X(hi_)} cy={Y(hv)} r={6.5} fill={HERO_C} />
              <line x1={X(hi_) + 16} x2={W - R - 4} y1={Y(hv)} y2={Y(hv)} stroke={HERO_C} strokeWidth={1.5} strokeDasharray="4 4" />
              <text x={W - R + 12} y={Math.min(Math.max(Y(hv) + 5, Y(USL) + 48), H - B)} fontSize={15} fontWeight={700} fill={HERO_C}>
                <tspan x={W - R + 12}>{HERO}</tspan>
                <tspan x={W - R + 12} dy={18}>{hv.toFixed(1)} µA</tspan>
              </text>
            </g>
          )}

          {/* x caption */}
          <text x={L} y={H - 12} fontSize={14} fill="#9FB5B0">
            {narrow ? `One dot = one chip (${parts.length} in batch ${LOT})` : `Each dot is one chip from batch ${LOT} (${parts.length} chips), spread sideways so you can see them all.`}
          </text>
        </svg>

        {/* readout */}
        <div className="flex flex-col gap-4">
          <div>
            <p className="text-sm text-[#9FB5B0]">Inside the oven at 125 °C</p>
            <p className="wide text-5xl font-extrabold text-[#F2A365]" aria-live="polite">
              Hour {Math.round(t)}
            </p>
            <p className="text-sm text-[#9FB5B0]">day {day} of 7</p>
          </div>
          <dl className="space-y-3 border-t border-[#1E4A45] pt-4 text-sm">
            <div>
              <dt className="text-[#9FB5B0]">Datasheet test says</dt>
              <dd className="mt-0.5 text-lg font-bold">
                {hv < USL ? "✓ PASS" : "✕ FAIL"} <span className="font-normal text-[#9FB5B0]">({hv.toFixed(1)} is under {USL})</span>
              </dd>
            </div>
            <div>
              <dt className="text-[#9FB5B0]">Compared with its batch</dt>
              <dd className="mt-0.5 text-lg font-bold" style={{ color: outOfFamily ? DEFECT : "#E7EFEC" }}>
                {outOfFamily ? "▲ Unusual" : "● Normal"}{" "}
                <span className="font-normal text-[#9FB5B0]">({(hv / mid).toFixed(1)}× the batch middle)</span>
              </dd>
            </div>
          </dl>
          {t >= 168 && (
            <p className="rounded-card border border-[#F2A365]/50 p-3 text-sm">
              The old test ships this chip. SENTINEL rejects it and writes down why.
            </p>
          )}
        </div>
      </div>

      {/* controls */}
      <div className="border-t border-[#1E4A45] px-5 pb-5 pt-3 sm:px-7">
        <div className="flex items-center gap-4">
          <button
            type="button"
            onClick={playing ? pause : play}
            className="inline-flex min-h-[44px] min-w-[104px] items-center justify-center gap-2 rounded-full bg-[#F2A365] px-4 font-bold text-oven hover:bg-[#F7BB88]"
          >
            {playing ? "❚❚ Pause" : t >= 168 ? "↺ Replay" : "▶ Play week"}
          </button>
          <div className="relative flex-1">
            <label htmlFor="oven-hour" className="sr-only">Burn-in hour</label>
            <input
              id="oven-hour" type="range" min={0} max={168} step={1} value={Math.round(t)}
              onChange={(e) => { pause(); setT(Number(e.target.value)); }}
              className="range" aria-valuetext={`hour ${Math.round(t)}`}
              style={{ ["--track" as string]: `linear-gradient(to right, #F2A365 ${(t / 168) * 100}%, #1E4A45 ${(t / 168) * 100}%)` }}
            />
            <div className="relative h-5 text-xs text-[#9FB5B0]" aria-hidden>
              {HOURS.map((h) => (
                <span key={h} className={cn("absolute whitespace-nowrap", h === 0 ? "" : h === 168 ? "-translate-x-full" : "-translate-x-1/2")} style={{ left: `${(h / 168) * 100}%` }}>
                  {h === 168 ? "168 h" : h}
                </span>
              ))}
            </div>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" aria-pressed={band} onClick={() => setBand((b) => !b)}
            className="chip border-[#2B5C56] bg-transparent text-[#E7EFEC] aria-pressed:border-[#8EBBDD] aria-pressed:bg-[#8EBBDD] aria-pressed:text-oven">
            {band ? "✓ " : ""}Show what&rsquo;s normal for this batch
          </button>
          <button type="button" aria-pressed={reveal} onClick={() => setReveal((r) => !r)}
            className="chip border-[#2B5C56] bg-transparent text-[#E7EFEC] aria-pressed:border-[#FF7A6B] aria-pressed:bg-[#FF7A6B] aria-pressed:text-oven">
            {reveal ? "✓ " : ""}Reveal the hidden defects
          </button>
        </div>
        {reveal && (
          <p className="mt-3 text-sm text-[#9FB5B0]">
            <span style={{ color: DEFECT }}>●</span> hidden defect (known only because this data is simulated) ·{" "}
            <span className="inline-block h-2.5 w-2.5 rounded-full border border-[#E7EFEC] align-middle" /> gross failure the old test already catches.
            Most red dots never touch the limit line.
          </p>
        )}
      </div>
    </div>
  );
}

export function OvenSection() {
  const { data, error } = useConsole();
  const parts = useMemo(() => data?.parts.filter((p) => p.l === LOT) ?? [], [data]);

  return (
    <section id="oven" className="mx-auto max-w-[1200px] scroll-mt-4 px-4 py-16 sm:px-8 sm:py-20">
      <h2 className="wide max-w-[22ch] text-3xl font-extrabold sm:text-4xl">Now watch a whole batch go through the week.</h2>
      <p className="mt-4 max-w-prose text-lg text-graphite">
        Press play. Each dot is one of {parts.length || 350} chips. Chip {HERO} never crosses the{" "}
        <Term t="datasheet limit">limit line</Term>, yet it leaves its <Term t="lot">batch</Term> behind.
      </p>
      <div className="mt-10">
        {parts.length ? (
          <Window parts={parts} />
        ) : (
          <div className="grid min-h-[420px] place-items-center rounded-[10px] bg-oven p-8 text-center text-[#9FB5B0]">
            {error ? `Could not load the batch: ${error}` : `Loading batch ${LOT}…`}
          </div>
        )}
      </div>
    </section>
  );
}
