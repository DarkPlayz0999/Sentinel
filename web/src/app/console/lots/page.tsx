"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { ConsoleState } from "@/components/console/shell";
import { LotDistribution, PdaBars, WaferMap } from "@/components/charts/charts";
import {
  Card, CardHead, Figure, Meter, Notice, PageHead, Provenance, Risk, Stamp, Stat, StatRow,
  num, pct, unit,
} from "@/components/ui/kit";
import { histogram, lotBands, measurement, partsInLot, quantile, useConsole } from "@/lib/console";
import { C } from "@/lib/theme";
import { cn } from "@/lib/utils";

/* LOTS - "Is this lot behaving, and if not, which components are driving it?"
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

  const rows = useMemo(() => (data && lot ? partsInLot(data.parts, lot.lot) : []), [data, lot]);
  const ranked = useMemo(() => [...rows].sort((a, b) => b.r - a.r), [rows]);

  if (!data || !lot) return <ConsoleState error={error} />;
  const { meta } = data;
  const pm = meta.params[pi];

  const at168 = rows.map((p) => measurement(p, pi, 3)).filter((v): v is number => v !== null);
  const defects168 = rows.filter((p) => p.y1 === 1)
    .map((p) => measurement(p, pi, 3)).filter((v): v is number => v !== null);
  const hi = quantile(at168, 0.995) * 1.08;
  const lo = quantile(at168, 0.002) * 0.92;
  const ref = lotBands(at168, pm.isCurrent);

  const wafers = Array.from(new Set(rows.map((p) => p.w))).sort();
  const dies = rows.filter((p) => wafer === "ALL" || p.w === wafer)
    .map((p) => ({ x: p.x, y: p.y, r: p.r, v: p.v, s: p.s }));
  const breach = lot.pdaStatus !== "OK";

  return (
    <>
      <PageHead
        title={`Lot ${lot.lot}`}
        lede="Every statistic in this system is computed within a lot. This is where a lot's health is read against the PDA gate."
      />

      {/* --------------------------------------------------- lot selector */}
      <nav aria-label="Lots" className="mb-6 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {data.lots.map((l) => {
          const on = l.lot === lot.lot;
          const bad = l.pdaStatus !== "OK";
          return (
            <button
              key={l.lot}
              onClick={() => router.push(`/console/lots?lot=${l.lot}`)}
              aria-current={on ? "page" : undefined}
              className={cn(
                "rounded-card border bg-sheet px-3 py-2.5 text-left transition-colors hover:border-graphite",
                on ? "border-ink ring-1 ring-ink" : "border-rule"
              )}
            >
              <span className="flex items-center justify-between">
                <span className="wide text-lg font-extrabold">{l.lot}</span>
                <span className={cn("text-xs font-semibold", bad ? "text-reject" : "text-pass")}>
                  {bad ? "Review" : "Within gate"}
                </span>
              </span>
              <span className="mt-1 block text-xs text-graphite">{pct(l.rejectFrac, 1)} rejected</span>
              <span className="mt-2 block">
                <Meter value={l.rejectFrac} max={Math.max(meta.pdaLimit * 2, 0.1)} height={4}
                  color={bad ? C.reject : C.cobalt} />
              </span>
            </button>
          );
        })}
      </nav>

      {breach && (
        <Notice tone="danger" title="R-601: lot exceeds the PDA gate" className="mb-4">
          Lot {lot.lot} has {pct(lot.rejectFrac, 1)} of its components rejected ({lot.reject} of{" "}
          {lot.parts}), above the {pct(meta.pdaLimit, 0)} Percent Defective Allowable. Recommend a
          lot-level engineering review. Only rejects count against the gate; watch parts ship with
          the serial flagged.
        </Notice>
      )}

      <StatRow className="grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
        <Stat k="Components" v={lot.parts} sub={`${wafers.length} wafer${wafers.length === 1 ? "" : "s"}`} />
        <Stat k="Accept" v={lot.accept} tone="text-pass" />
        <Stat k="Watch" v={lot.watch} tone="text-watch" />
        <Stat k="Reject" v={lot.reject} tone="text-reject" sub={`${pct(lot.rejectFrac, 1)} against a ${pct(meta.pdaLimit, 0)} gate`} />
        <Stat k="Latent defects" v={lot.latent} sub={`${pct(lot.latentRate, 1)}, simulated ground truth`} />
        <Stat k="Gross failures" v={lot.gross} sub="breach a limit by 168 h" />
      </StatRow>

      {/* ------------------------------------------------------- charts */}
      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <Figure
          title="Lot distribution at 168 h"
          meta={`${at168.length} parts`}
          right={
            <select value={pi} onChange={(e) => setPi(Number(e.target.value))} className="input py-1" aria-label="Parameter">
              {meta.params.map((p, i) => <option key={p.name} value={i}>{p.name}</option>)}
            </select>
          }
          note={<>Lot median {num(ref.median, 2)} {unit(pm.unit)}. The +3σ and +6σ lines are this lot&rsquo;s own robust limits{pm.isCurrent ? ", computed on log values because currents are lognormal" : ""}. The datasheet limit of {pm.usl} {unit(pm.unit)} sits far to the right of where the lot lives, which is the case for a lot-relative reference.</>}
        >
          <LotDistribution
            bins={histogram(at168, lo, hi, 48)} defectBins={histogram(defects168, lo, hi, 48)}
            lo={lo} hi={hi} param={pm.name} unitName={pm.unit} usl={pm.usl}
            med={ref.median} bands={ref.bands}
          />
        </Figure>

        <Figure
          title="Wafer map"
          meta="die coloured by decision"
          right={
            <select value={wafer} onChange={(e) => setWafer(e.target.value)} className="input py-1" aria-label="Wafer">
              <option value="ALL">All wafers</option>
              {wafers.map((w) => <option key={w} value={w}>{w}</option>)}
            </select>
          }
          note={<>There is no spatial structure to find here: the generator places dies at random, independent of class, and <code>src/wafer.py</code>&rsquo;s permutation test correctly reports none. The view is ready for real wafer data. Select a die to open it.</>}
        >
          <div className="mx-auto max-w-[320px]">
            <WaferMap dies={dies} onSelect={(s) => router.push(`/console/components?id=${s}`)} />
          </div>
        </Figure>
      </div>

      {/* ------------------------------------------ ranking + comparison */}
      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <Card className="overflow-x-auto">
          <CardHead title={`Highest-risk components in ${lot.lot}`} meta="Top 15." />
          <table className="tbl min-w-[560px]">
            <thead>
              <tr>
                <th className="n">Rank</th><th>Component</th><th className="n">{pm.name} 168 h</th>
                <th className="n">Lot deviation</th><th>Risk</th><th>Decision</th>
              </tr>
            </thead>
            <tbody>
              {ranked.slice(0, 15).map((p, i) => (
                <tr key={p.s}>
                  <td className="n text-mute">{i + 1}</td>
                  <td><Link href={`/console/components?id=${p.s}`} className="link">{p.s}</Link></td>
                  <td className="n">{num(p.m[pi][3], 2)}</td>
                  <td className="n">{num(p.l2, 2)}σ</td>
                  <td><Risk r={p.r} v={p.v} /></td>
                  <td><Stamp v={p.v} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        <Figure
          title="All lots against the gate"
          note="Read a clearly bad lot against a clearly good one. Lots either side of the gate by a fraction of a percent are what a global band tuned to that gate produces, not a meaningful difference."
        >
          <PdaBars
            lots={data.lots.map((l) => ({ lot: l.lot, rejectFrac: l.rejectFrac, breach: l.pdaStatus !== "OK" }))}
            limit={meta.pdaLimit}
          />
        </Figure>
      </div>

      <Provenance modelVersion={meta.modelVersion} source={meta.generatedFrom} />
    </>
  );
}

export default function LotsPage() {
  return (
    <Suspense fallback={<ConsoleState />}>
      <Inner />
    </Suspense>
  );
}
