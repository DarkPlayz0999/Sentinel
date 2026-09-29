"use client";

import { useMemo, useState } from "react";
import { Term } from "@/components/ui/term";
import { ConsoleData, useConsole } from "@/lib/console";
import { C } from "@/lib/theme";
import { cn } from "@/lib/utils";

/* "How careful should the screen be?" - the whole recall/overkill trade-off
 * as one copper handle. Counts are computed live from the risk score of every
 * screened chip (console.json); the ground truth used to COUNT catches is the
 * simulated label, which never feeds a verdict. */

export function Carefulness({ data }: { data: ConsoleData }) {
  const { parts, meta } = data;
  const [t, setT] = useState(Math.round(meta.bands.watch));

  const latent = useMemo(() => parts.filter((p) => p.tc === "latent").sort((a, b) => b.r - a.r), [parts]);
  const healthy = useMemo(() => parts.filter((p) => p.tc === "healthy"), [parts]);
  const caught = latent.filter((p) => p.r >= t).length;
  const pulled = healthy.filter((p) => p.r >= t).length;
  const missed = latent.length - caught;

  const presets = [
    { label: "Very careful", v: 20 },
    { label: "SENTINEL's setting", v: Math.round(meta.bands.watch) },
    { label: "Only the obvious", v: Math.round(meta.bands.reject) },
  ];

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <div>
        <label htmlFor="careful" className="block text-lg font-bold">
          Flag every chip with a <Term t="risk score">risk score</Term> of at least{" "}
          <span className="wide text-3xl text-copper">{t}</span>
        </label>
        <input id="careful" type="range" min={0} max={100} value={t} onChange={(e) => setT(Number(e.target.value))}
          className="range mt-2" aria-valuetext={`risk score ${t}`}
          style={{ ["--track" as string]: `linear-gradient(to right, #D3D9DF ${t}%, ${C.copper} ${t}%)` }} />
        <div className="flex justify-between text-xs text-mute" aria-hidden>
          <span>0: flag everything</span><span>100: flag nothing</span>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {presets.map((p) => (
            <button key={p.label} type="button" aria-pressed={t === p.v} onClick={() => setT(p.v)} className="chip">
              {p.label}
            </button>
          ))}
        </div>

        <p className="mt-6 text-lg leading-relaxed">
          At this setting the screen catches{" "}
          <strong style={{ color: C.pass }}>{caught} of {latent.length}</strong> hidden defects and sends{" "}
          <strong style={{ color: C.watch }}>{pulled.toLocaleString()}</strong> good chips (
          {((pulled / healthy.length) * 100).toFixed(1)}%) for a second look.
          {missed > 0 ? (
            <> The <strong style={{ color: C.reject }}>{missed}</strong> it misses would fly.</>
          ) : (
            <> Nothing hidden gets through.</>
          )}
        </p>
        <p className="mt-2 text-sm text-graphite">
          A missed defect can end a mission; a good chip checked twice costs minutes. That is why SENTINEL
          leans careful. The trade-off between <Term t="recall">catching</Term> and{" "}
          <Term t="overkill">over-flagging</Term> is yours to set.
        </p>
      </div>

      <div className="card p-5">
        <p className="text-sm font-bold">The {latent.length} hidden defects in this data</p>
        <p className="text-sm text-graphite">One square each, riskiest first. Filled = caught, outline = would ship.</p>
        <div className="mt-4 grid grid-cols-[repeat(auto-fill,minmax(14px,1fr))] gap-[5px]" role="img"
          aria-label={`${caught} of ${latent.length} hidden defects caught`}>
          {latent.map((p) => (
            <span key={p.s} title={`${p.s}: risk ${p.r.toFixed(1)}`}
              className={cn("aspect-square rounded-[3px] border-2 transition-colors duration-200",
                p.r >= t ? "border-pass bg-pass" : "border-reject bg-transparent")} />
          ))}
        </div>
        <div className="mt-6">
          <div className="flex items-baseline justify-between text-sm">
            <span className="font-bold">Good chips sent for a second look</span>
            <span>{pulled.toLocaleString()} of {healthy.length.toLocaleString()}</span>
          </div>
          <div className="mt-2 h-3 overflow-hidden rounded-full bg-hair">
            <div className="h-full rounded-full bg-watch transition-[width] duration-200"
              style={{ width: `${(pulled / healthy.length) * 100}%` }} />
          </div>
        </div>
      </div>
    </div>
  );
}

/** Landing-page wrapper: loads the screened data itself. */
export function CarefulnessSection() {
  const { data } = useConsole();
  return (
    <section id="careful" className="border-y border-rule bg-sheet">
      <div className="mx-auto max-w-[1200px] scroll-mt-4 px-4 py-16 sm:px-8 sm:py-20">
        <h2 className="wide max-w-[22ch] text-3xl font-extrabold sm:text-4xl">How careful should the screen be? You decide.</h2>
        <p className="mt-4 max-w-prose text-lg text-graphite">
          Drag the handle. Every number below is recounted from all {data?.summary.parts.toLocaleString() ?? "2,100"} screened chips.
        </p>
        <div className="mt-10">
          {data ? <Carefulness data={data} /> : <p className="text-graphite">Loading the screened chips…</p>}
        </div>
      </div>
    </section>
  );
}
