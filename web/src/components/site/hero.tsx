"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Term } from "@/components/ui/term";
import { ConsoleData, Part, median, robustSigma, useConsole } from "@/lib/console";
import { C } from "@/lib/theme";
import { cn } from "@/lib/utils";

/* HERO - one chip at a time, two tests side by side.
 *
 * Three real chips from batch L04 (simulated dataset, console.json): a healthy
 * one, an obvious failure, and a hidden defect. Both tests agree on the first
 * two. Only the hidden defect splits them - which is the whole idea, learned
 * in one click. Every value, band and verdict is read from the screened data. */

const LOT = "L04";
const USL = 50;
const HOURS = [0, 24, 96, 168];
const EXAMPLES = [
  { serial: "L04-0323", tab: "Healthy" },
  { serial: "L04-0043", tab: "Obvious failure" },
  { serial: "L04-0348", tab: "Hidden defect" },
] as const;

const VERDICT = {
  ACCEPT: { mark: "●", word: "Accept", color: C.pass },
  WATCH: { mark: "▲", word: "Watch", color: C.watch },
  REJECT: { mark: "■", word: "Reject", color: C.reject },
} as const;

function Chip({ serial, color }: { serial: string; color: string }) {
  // A drawn package: board-green body, copper pins, a status light in the verdict colour.
  const pins = Array.from({ length: 7 }, (_, i) => 22 + i * 16);
  return (
    <svg viewBox="0 0 200 150" className="h-auto w-full max-w-[140px] sm:max-w-[180px]" aria-hidden>
      {pins.map((x) => (
        <g key={x} fill={C.copper}>
          <rect x={x} y={4} width={8} height={18} rx={1.5} />
          <rect x={x} y={128} width={8} height={18} rx={1.5} />
        </g>
      ))}
      <rect x={12} y={20} width={176} height={110} rx={10} fill={C.ink} />
      <circle cx={30} cy={38} r={5} fill="none" stroke="#2E6660" strokeWidth={2} />
      <text x={100} y={82} textAnchor="middle" fontSize={20} fontWeight={700} fill="#E7EFEC">{serial}</text>
      <text x={100} y={104} textAnchor="middle" fontSize={12} fill="#8FB0AA">batch {LOT}</text>
      <circle cx={168} cy={112} r={7} fill={color} />
    </svg>
  );
}

function Week({ part, env }: { part: Part; env: { p05: number[]; p50: number[]; p95: number[] } }) {
  const W = 560, H = 300, L = 44, R = 70, T = 16, B = 36;
  const X = (h: number) => L + (h / 168) * (W - L - R);
  const Y = (v: number) => H - B - (Math.min(v, 62) / 62) * (H - T - B);
  const vals = part.m[0];
  const pts = HOURS.map((h, i) => [h, vals[i]] as const).filter(([, v]) => v != null) as [number, number][];
  const line = pts.map(([h, v], i) => `${i ? "L" : "M"}${X(h)},${Y(v)}`).join(" ");
  const band =
    HOURS.map((h, i) => `${i ? "L" : "M"}${X(h)},${Y(env.p95[i])}`).join(" ") +
    [...HOURS].reverse().map((h, j) => `L${X(h)},${Y(env.p05[3 - j])}`).join(" ") + "Z";
  const last = pts[pts.length - 1];
  const over = last[1] >= USL;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full" role="img"
      aria-label={`${part.s} over the week: ${pts.map(([h, v]) => `${v.toFixed(1)} at ${h} hours`).join(", ")}. Limit ${USL}.`}>
      {[0, 20, 40, 60].map((v) => (
        <g key={v}>
          <line x1={L} x2={W - R} y1={Y(v)} y2={Y(v)} stroke={C.hair} />
          <text x={L - 8} y={Y(v) + 4} textAnchor="end" fontSize={12} fill={C.mute}>{v}</text>
        </g>
      ))}
      <text x={L - 8} y={T - 2} textAnchor="end" fontSize={12} fill={C.mute}>µA</text>
      {HOURS.map((h) => (
        <text key={h} x={X(h)} y={H - 12} textAnchor="middle" fontSize={12} fill={C.mute}>
          {h === 168 ? "168 h" : h === 0 ? "start" : `${h} h`}
        </text>
      ))}

      <path d={band} fill={C.cobalt} fillOpacity={0.14} />
      <text x={X(96)} y={Y(env.p05[2]) + 16} textAnchor="middle" fontSize={12} fill={C.cobalt}>
        normal range for this batch
      </text>

      <line x1={L} x2={W - R} y1={Y(USL)} y2={Y(USL)} stroke={C.reject} strokeWidth={2} strokeDasharray="6 4" />
      <text x={L + 6} y={Y(USL) - 7} fontSize={12} fontWeight={700} fill={C.reject}>datasheet limit {USL} µA</text>

      {/* keyed by serial so the line redraws each time you switch chip */}
      <g key={part.s}>
        <path d={line} fill="none" stroke={C.ink} strokeWidth={3.5} strokeLinecap="round" strokeLinejoin="round"
          pathLength={1} className="draw" />
        {pts.map(([h, v]) => (
          <circle key={h} cx={X(h)} cy={Y(v)} r={5} fill={C.sheet} stroke={C.ink} strokeWidth={2.5} className="pop" />
        ))}
        <text x={W - R + 6} y={Y(last[1]) + (Math.abs(Y(last[1]) - Y(USL)) < 16 ? 20 : 4)} fontSize={14}
          fontWeight={700} fill={over ? C.reject : C.ink} className="pop">
          {last[1].toFixed(1)}
        </text>
      </g>
    </svg>
  );
}

function Stage({ data }: { data: ConsoleData }) {
  const [k, setK] = useState(2);
  // The batch's normal range at each reading: median +/- 3 robust sigma on log
  // values, the same yardstick as the pipeline. Percentiles would be dragged
  // up by this batch's own failures.
  const env = useMemo(() => {
    const rows = data.parts.filter((p) => p.l === LOT);
    const at = HOURS.map((_, i) => rows.map((p) => p.m[0][i]).filter((v): v is number => v != null && v > 0).map(Math.log));
    const m = at.map(median), sd = at.map(robustSigma);
    return { p05: m.map((x, i) => Math.exp(x - 3 * sd[i])), p50: m.map(Math.exp), p95: m.map((x, i) => Math.exp(x + 3 * sd[i])) };
  }, [data]);
  const part = data.parts.find((p) => p.s === EXAMPLES[k].serial)!;
  const v168 = part.m[0][3] ?? 0, v0 = part.m[0][0] ?? 0;
  const oldPass = part.st === 0;
  const sv = VERDICT[part.v];
  const disagree = oldPass && part.v !== "ACCEPT";

  const why =
    part.v === "ACCEPT"
      ? `Went from ${v0.toFixed(1)} to ${v168.toFixed(1)} µA, moving with its batch. Nothing unusual.`
      : !oldPass
        ? `Crossed a datasheet limit. Both tests reject it; this one was never going to fly.`
        : `Rose from ${v0.toFixed(1)} to ${v168.toFixed(1)} µA while its batch stayed near ${env.p50[3].toFixed(1)}. Legal, but far outside its family.`;

  return (
    <div className="rounded-[14px] border border-rule bg-sheet shadow-[0_1px_0_#D3D9DF]">
      <div role="tablist" aria-label="Pick a chip" className="flex gap-1 overflow-x-auto border-b border-rule p-2">
        {EXAMPLES.map((e, i) => (
          <button key={e.serial} role="tab" aria-selected={k === i} onClick={() => setK(i)}
            className={cn("min-h-[44px] whitespace-nowrap rounded-[8px] px-4 text-sm font-bold transition-colors",
              k === i ? "bg-ink text-sheet" : "text-graphite hover:bg-well hover:text-ink")}>
            {e.tab}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 p-4 sm:grid-cols-[150px_minmax(0,1fr)] sm:p-5">
        <div className="flex items-center justify-center sm:items-start"><Chip serial={part.s} color={sv.color} /></div>
        <Week part={part} env={env} />
      </div>

      <div className="grid gap-px border-t border-rule bg-rule sm:grid-cols-2">
        <div className="bg-sheet p-4 sm:p-5">
          <p className="text-sm text-graphite">Old test: is it under the limit?</p>
          <p className="wide mt-1 text-3xl font-extrabold" style={{ color: oldPass ? C.pass : C.reject }}>
            {oldPass ? "✓ Pass" : "✕ Fail"}
          </p>
          <p className="mt-1 text-sm text-graphite">
            {oldPass ? `${v168.toFixed(1)} is under ${USL}, and every other reading is in range.` : "At least one reading is over its limit."}
          </p>
        </div>
        <div className={cn("bg-sheet p-4 sm:p-5", disagree && "outline outline-2 -outline-offset-2 outline-copper")}>
          <p className="text-sm text-graphite">SENTINEL: is it behaving like its batch?</p>
          <p key={part.s} className="wide pop-late mt-1 text-3xl font-extrabold" style={{ color: sv.color }}>
            {sv.mark} {sv.word}
          </p>
          <p className="mt-1 text-sm text-graphite">{why}</p>
        </div>
      </div>
      <p className={cn("border-t border-rule px-4 py-3 text-sm sm:px-5", disagree ? "bg-copper/10 font-bold text-copper" : "text-graphite")}>
        {disagree
          ? "The two tests disagree. This is the chip that would have flown."
          : "Both tests agree here. Try \u201cHidden defect\u201d to see where they don't."}
      </p>
    </div>
  );
}

export function Hero() {
  const { data, error } = useConsole();
  return (
    <section className="mx-auto grid max-w-[1200px] grid-cols-[minmax(0,1fr)] gap-10 px-4 pb-16 pt-10 sm:px-8 sm:pt-16 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:items-center">
      <div>
        <h1 className="wide text-[44px] font-extrabold leading-[1] sm:text-6xl lg:text-[68px]">
          Catch the chip that passes but shouldn&rsquo;t.
        </h1>
        <p className="mt-6 max-w-prose text-lg text-graphite">
          Before a chip goes to space it spends a week in a hot oven, called <Term t="burn-in">burn-in</Term>.
          The old test only asks if each reading stays under a <Term t="datasheet limit">limit</Term>.
          SENTINEL also asks if the chip is behaving like the rest of its <Term t="lot">batch</Term>.
        </p>
        <p className="mt-3 max-w-prose text-lg text-graphite">Pick a chip and compare the two answers.</p>
        <div className="mt-7 flex flex-wrap gap-3">
          <Link href="/console" className="btn-primary min-h-[44px] px-5 text-base">Open the screening console</Link>
          <a href="#gap" className="btn-quiet min-h-[44px] px-5 text-base">How it works</a>
        </div>
      </div>
      {data ? (
        <Stage data={data} />
      ) : (
        <div className="grid min-h-[480px] place-items-center rounded-[14px] border border-rule bg-sheet text-graphite">
          {error ? `Could not load the chips: ${error}` : "Loading chips…"}
        </div>
      )}
    </section>
  );
}
