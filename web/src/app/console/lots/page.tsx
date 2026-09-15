"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { ConsoleState } from "@/components/console/shell";
import { LotDistribution, PdaBars, WaferMap } from "@/components/charts/charts";
import {
  ChartNote, Meter, Panel, PanelHead, ProvenanceNote, SectionHead, Stat,
  VerdictChip, num, pct, unit,
} from "@/components/ui/kit";
import { histogram, measurement, partsInLot, quantile, useConsole } from "@/lib/console";
import { cn } from "@/lib/utils";

/* LOTS — "Is this lot behaving, and if not, which components are driving it?"
 *
 * The lot is the unit a PDA gate is applied to and the unit every statistic in
 * this system is computed within, so it gets its own screen rather than being
 * a filter on the component table. */

function Inner() {
  const { data, error } = useConsole();
  const params = useSearchParams();
  const router = useRouter();
  const [pi, setPi] = useState(0);
  const [wafer, setWafer] = useState<string>("ALL");

  const selected = params.get("lot") ?? data?.lots[0]?.lot ?? "";
  const lot = data?.lots.find((l) => l.lot === selected) ?? data?.lots[0];

  const rows = useMemo(
    () => (data && lot ? partsInLot(data.parts, lot.lot) : []),
    [data, lot]
  );
  const ranked = useMemo(() => [...rows].sort((a, b) => b.r - a.r), [rows]);

  if (!data || !lot) return <ConsoleState error={error} />;
  const { meta } = data;
  const pm = meta.params[pi];

  const at168 = rows
    .map((p) => measurement(p, pi, 3))
    .filter((v): v is number => v !== null);
  const defects168 = rows
    .filter((p) => p.y1 === 1)
    .map((p) => measurement(p, pi, 3))
    .filter((v): v is number => v !== null);
  const hi = quantile(at168, 0.995) * 1.08;
  const lo = quantile(at168, 0.002) * 0.92;

  const wafers = Array.from(new Set(rows.map((p) => p.w))).sort();
  const dies = rows
    .filter((p) => wafer === "ALL" || p.w === wafer)
    .map((p) => ({ x: p.x, y: p.y, r: p.r, v: p.v, s: p.s }));

  const breach = lot.pdaStatus !== "OK";

  return (
    <div className="space-y-6">
      <SectionHead
        index="12"
        title="Lot health"
        note="every statistic in this system is computed within a lot"
      />

      {/* --------------------------------------------------- lot selector */}
      <div className="grid gap-px bg-lab-rule sm:grid-cols-3 lg:grid-cols-6">
        {data.lots.map((l) => {
          const on = l.lot === lot.lot;
          const bad = l.pdaStatus !== "OK";
          return (
            <button
              key={l.lot}
              onClick={() => router.push(`/console/lots?lot=${l.lot}`)}
              className={cn(
                "bg-lab-card px-3 py-2.5 text-left transition-colors hover:bg-lab-panel",
                on && "bg-lab-panel ring-1 ring-inset ring-sig-blue"
              )}
            >
              <div className="flex items-center justify-between">
                <span className="readout text-[13px] font-bold text-lab-ink">{l.lot}</span>
                <span
                  className={cn(
                    "font-mono text-[8.5px] font-bold uppercase tracking-label",
                    bad ? "text-sig-red" : "text-sig-green"
                  )}
                >
                  {bad ? "REVIEW" : "OK"}
                </span>
              </div>
              <div className="mt-1.5 font-mono text-[9px] text-lab-faint">
                {l.parts} parts · {pct(l.rejectFrac, 1)} reject
              </div>
              <div className="mt-1.5">
                <Meter
                  value={l.rejectFrac}
                  max={Math.max(meta.pdaLimit * 2, 0.1)}
                  height={4}
                  color={bad ? "#A81E12" : "#12508C"}
                />
              </div>
            </button>
          );
        })}
      </div>

      {/* ------------------------------------------------------ lot header */}
      <div className="panel">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-lab-hair px-4 py-3">
          <div>
            <div className="label">Lot</div>
            <div className="readout text-[22px] font-bold leading-none text-lab-ink">{lot.lot}</div>
          </div>
          <div className="font-mono text-[10px] text-lab-dim">
            {lot.parts} components · {wafers.length} wafer(s)
          </div>
          <span
            className={cn(
              "ml-auto border px-2.5 py-1 font-mono text-[10px] font-bold uppercase tracking-label",
              breach
                ? "border-sig-red/35 bg-sig-red/[0.08] text-sig-red"
                : "border-sig-green/35 bg-sig-green/[0.08] text-sig-green"
            )}
          >
            PDA {breach ? "REVIEW REQUIRED" : "WITHIN GATE"}
          </span>
        </div>

        <div className="grid grid-cols-2 gap-px bg-lab-hair sm:grid-cols-4 lg:grid-cols-7">
          <Stat k="Components" v={lot.parts} />
          <Stat k="Healthy" v={lot.healthy} tone="text-sig-green" sub="simulated ground truth" />
          <Stat k="Latent" v={lot.latent} tone="text-sig-amber" sub={`${pct(lot.latentRate, 1)} latent rate`} />
          <Stat k="Gross" v={lot.gross} tone="text-sig-red" sub="breaches a limit by 168 h" />
          <Stat k="Accept" v={lot.accept} tone="text-sig-green" />
          <Stat k="Watch" v={lot.watch} tone="text-sig-amber" />
          <Stat
            k="Reject"
            v={lot.reject}
            tone="text-sig-red"
            sub={`${pct(lot.rejectFrac, 1)} vs ${pct(meta.pdaLimit, 0)} gate`}
          />
        </div>
      </div>

      {breach && (
        <div className="panel border-l-[3px] border-l-sig-red px-4 py-3">
          <div className="font-mono text-[10px] font-bold uppercase tracking-label text-sig-red">
            R-601 · lot exceeds PDA
          </div>
          <p className="mt-1.5 text-[12px] leading-relaxed text-lab-ink">
            Lot {lot.lot} has {pct(lot.rejectFrac, 1)} rejected components ({lot.reject}/
            {lot.parts}), exceeding the {pct(meta.pdaLimit, 0)} Percent Defective Allowable
            threshold — recommend lot-level review.
          </p>
          <p className="mt-2 font-mono text-[9px] text-lab-faint">
            Only REJECT consumes PDA budget. WATCH components ship with the serial flagged and do
            not count against the gate.
          </p>
        </div>
      )}

      {/* ------------------------------------------------------- charts */}
      <div className="grid gap-px bg-lab-rule xl:grid-cols-2">
        <Panel className="border-0 p-4">
          <PanelHead
            title="Lot distribution at 168 h"
            meta={`n=${rows.length}`}
            right={
              <select
                value={pi}
                onChange={(e) => setPi(Number(e.target.value))}
                className="readout border border-lab-rule bg-lab-card px-1.5 py-0.5 text-[10px] text-lab-ink outline-none focus:border-sig-blue"
              >
                {meta.params.map((p, i) => (
                  <option key={p.name} value={i}>{p.name}</option>
                ))}
              </select>
            }
            className="-mx-4 -mt-4 mb-3 px-4"
          />
          <LotDistribution
            bins={histogram(at168, lo, hi, 48)}
            defectBins={histogram(defects168, lo, hi, 48)}
            lo={lo}
            hi={hi}
            unitName={pm.name}
            usl={pm.usl}
            med={lot.ref[pm.name].median[3]}
            sig={lot.ref[pm.name].sigma168}
          />
          <ChartNote>
            Lot median {num(lot.ref[pm.name].median[3], 2)} {unit(pm.unit)}, robust σ{" "}
            {num(lot.ref[pm.name].sigma168, 3)}. The +3σ and +6σ rules are this lot&rsquo;s own
            dynamic limits — computed from the population in front of you, not from the
            datasheet. USL {pm.usl} {unit(pm.unit)} sits far to the right of where the lot
            actually lives, which is the whole argument for a dynamic reference.
          </ChartNote>
        </Panel>

        <Panel className="border-0 p-4">
          <PanelHead
            title="Wafer map"
            meta="die grid coloured by screening risk"
            right={
              <select
                value={wafer}
                onChange={(e) => setWafer(e.target.value)}
                className="readout border border-lab-rule bg-lab-card px-1.5 py-0.5 text-[10px] text-lab-ink outline-none focus:border-sig-blue"
              >
                <option value="ALL">ALL WAFERS</option>
                {wafers.map((w) => (
                  <option key={w} value={w}>{w}</option>
                ))}
              </select>
            }
            className="-mx-4 -mt-4 mb-3 px-4"
          />
          <div className="mx-auto max-w-[320px]">
            <WaferMap
              dies={dies}
              onSelect={(s) => router.push(`/console/components?id=${s}`)}
            />
          </div>
          <ChartNote>
            <span className="font-bold text-lab-dim">Honest caveat.</span> This dataset&rsquo;s
            generator draws die coordinates uniformly at random and independently of a
            component&rsquo;s class, so there is <em>no</em> spatial structure here to find —{" "}
            <code>src/wafer.py</code> runs a permutation test and correctly reports none. The
            view is here because it is how an inspector looks at a lot, and it is ready for real
            wafer data where clustering is genuine.
          </ChartNote>
        </Panel>
      </div>

      {/* ------------------------------------------ ranking + comparison */}
      <div className="grid gap-px bg-lab-rule lg:grid-cols-[minmax(0,1fr)_minmax(0,420px)]">
        <Panel className="overflow-x-auto border-0">
          <PanelHead
            title={`Component risk ranking — ${lot.lot}`}
            meta="highest risk first · click a serial for the full record"
          />
          <table className="w-full min-w-[560px] border-collapse">
            <thead>
              <tr className="border-b border-lab-rule bg-lab-panel">
                {["#", "Component", `${pm.name} @168h`, "Dynamic σ", "Risk", "Decision"].map((h) => (
                  <th key={h} className="px-2.5 py-2 text-left font-mono text-[9px] uppercase tracking-label text-lab-faint">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ranked.slice(0, 25).map((p, i) => (
                <tr key={p.s} className="border-b border-lab-hair hover:bg-lab-panel">
                  <td className="readout px-2.5 py-[5px] text-[10px] text-lab-faint">{i + 1}</td>
                  <td className="px-2.5 py-[5px]">
                    <Link
                      href={`/console/components?id=${p.s}`}
                      className="readout text-[11px] font-semibold text-sig-blue hover:underline"
                    >
                      {p.s}
                    </Link>
                  </td>
                  <td className="readout px-2.5 py-[5px] text-[10px]">{num(p.m[pi][3], 2)}</td>
                  <td className="readout px-2.5 py-[5px] text-[10px]">{num(p.l2, 2)}σ</td>
                  <td className="px-2.5 py-[5px]">
                    <div className="flex items-center gap-2">
                      <span className="readout w-8 text-[10px] font-semibold">{num(p.r, 1)}</span>
                      <span className="w-16">
                        <Meter value={p.r} max={100} height={4}
                          color={p.v === "REJECT" ? "#A81E12" : p.v === "WATCH" ? "#9A5B06" : "#186B45"} />
                      </span>
                    </div>
                  </td>
                  <td className="px-2.5 py-[5px]"><VerdictChip v={p.v} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel className="border-0 p-4">
          <PanelHead title="Lot comparison" meta="reject fraction vs the PDA gate" className="-mx-4 -mt-4 mb-3 px-4" />
          <PdaBars
            lots={data.lots.map((l) => ({
              lot: l.lot, rejectFrac: l.rejectFrac, breach: l.pdaStatus !== "OK",
            }))}
            limit={meta.pdaLimit}
          />
          <ChartNote>
            The informative comparison is a clearly bad lot against a clearly good one. Lots
            landing either side of the gate by a fraction of a percent are what a{" "}
            <em>global</em> band tuned to that gate produces, and should not be read as a
            meaningful difference.
          </ChartNote>
        </Panel>
      </div>

      <ProvenanceNote modelVersion={meta.modelVersion} source={meta.generatedFrom} />
    </div>
  );
}

export default function LotsPage() {
  return (
    <Suspense fallback={<ConsoleState />}>
      <Inner />
    </Suspense>
  );
}
