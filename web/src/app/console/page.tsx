"use client";

import Link from "next/link";
import { useMemo } from "react";
import { ConsoleState } from "@/components/console/shell";
import { PdaBars, ScoreBands } from "@/components/charts/charts";
import {
  Card, CardHead, Figure, PageHead, Provenance, Risk, SectionTitle, Stamp, Stat, StatRow,
  num, pct,
} from "@/components/ui/kit";
import { histogram, useConsole } from "@/lib/console";

/* OVERVIEW - "Which components should the reliability engineer investigate,
 * and is any lot misbehaving?" Every figure is a count or a rate the screen
 * produced. */

export default function Overview() {
  const { data, error } = useConsole();

  const scoreBins = useMemo(
    () => (data ? histogram(data.parts.map((p) => p.r), 0, 100, 50) : []),
    [data]
  );
  // The queue leads with escapes: parts that pass every datasheet limit but
  // the screen flags. Gross breaches are already caught by the datasheet test.
  const worst = useMemo(
    () => (data ? data.parts.filter((p) => p.st === 0 && p.v !== "ACCEPT").sort((a, b) => b.r - a.r).slice(0, 12) : []),
    [data]
  );

  if (!data) return <ConsoleState error={error} />;
  const { summary: s, meta, lots } = data;

  return (
    <>
      <PageHead
        title="Overview"
        lede={`${s.parts.toLocaleString()} components from ${s.lots} lots, screened against their own lot and forecast from the first 24 hours. Start with the investigation queue.`}
      />

      {/* ------------------------------------------------ the gap, stated */}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <Card className="p-5">
          <h2 className="text-sm font-semibold text-graphite">Latent defects caught</h2>
          <div className="mt-4 grid grid-cols-2 gap-5">
            <div>
              <div className="wide text-4xl font-black text-reject">{pct(s.staticRecall, 0)}</div>
              <p className="mt-2 text-sm text-graphite">
                by the datasheet limits. {s.staticFlagged} parts breach a limit at 168 h; none of
                them is a latent defect.
              </p>
            </div>
            <div>
              <div className="wide text-4xl font-black text-cobalt">{pct(s.flaggedRecall, 0)}</div>
              <p className="mt-2 text-sm text-graphite">
                by SENTINEL (watch or reject), at {pct(s.flaggedOverkill, 1)} of healthy parts
                flagged.
              </p>
            </div>
          </div>
          <dl className="mt-5 border-t border-hair pt-3 text-sm">
            {[
              ["Latent defects passing every limit at 168 h", `${s.latent} of ${s.latent}`],
              ["Recall at a 5% overkill budget", pct(s.recallAt5, 1)],
              ["Recall at a 10% overkill budget", pct(s.recallAt10, 1)],
              ["Fused score PR-AUC", num(s.fusedPrAuc, 3)],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between gap-4 py-1">
                <dt className="text-graphite">{k}</dt>
                <dd className="font-semibold">{v}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-3 text-xs text-mute">
            Accuracy is not reported. At {pct(s.latent / s.parts, 1)} prevalence, a screen that
            passes everything scores {pct(1 - s.latent / s.parts, 1)} and catches nothing.
          </p>
        </Card>

        <Figure
          title="Risk score distribution"
          meta="bands sized to the 5% PDA budget"
          note="Only reject consumes the PDA budget. Watch parts ship with the serial flagged, which is how the screen buys recall without scrapping a lot."
        >
          <ScoreBands bins={scoreBins} watch={meta.bands.watch} reject={meta.bands.reject} />
        </Figure>
      </div>

      <StatRow className="mt-4 grid-cols-2 sm:grid-cols-4">
        <Stat k="Accept" v={s.accept.toLocaleString()} tone="text-pass" sub={`${pct(s.accept / s.parts)} of parts`} />
        <Stat k="Watch" v={s.watch.toLocaleString()} tone="text-watch" sub="ship with the serial flagged" />
        <Stat k="Reject" v={s.reject.toLocaleString()} tone="text-reject" sub={`${pct(s.reject / s.parts)} of parts`} />
        <Stat
          k="Lots within PDA gate"
          v={`${s.lots - s.lotsBreachingPda} of ${s.lots}`}
          tone={s.lotsBreachingPda ? "text-watch" : "text-pass"}
          sub={`gate at ${pct(meta.pdaLimit, 0)} rejected`}
        />
      </StatRow>

      {/* ----------------------------------------------------- the queue */}
      <SectionTitle title="Investigation queue" note="Flagged parts that pass every datasheet limit, highest risk first." />
      <Card className="overflow-x-auto">
        <table className="tbl min-w-[760px]">
          <thead>
            <tr>
              <th>Component</th><th>Lot</th><th>Risk</th>
              <th className="n">Lot deviation</th><th className="n">Pooled evidence</th>
              <th className="n">Slope ratio</th><th>Datasheet</th><th>Decision</th>
            </tr>
          </thead>
          <tbody>
            {worst.map((p) => (
              <tr key={p.s}>
                <td><Link href={`/console/components?id=${p.s}`} className="link">{p.s}</Link></td>
                <td className="text-graphite">{p.l}</td>
                <td><Risk r={p.r} v={p.v} /></td>
                <td className="n">{num(p.l2, 2)}σ</td>
                <td className="n">{num(p.l3, 1)}</td>
                <td className="n">{p.wr === null ? "—" : `${num(p.wr, 2)}×`}</td>
                <td><Stamp v={p.st ? "BREACH" : "PASS"} /></td>
                <td><Stamp v={p.v} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <p className="mt-3 max-w-prose text-sm text-graphite">
        Every row here would ship under traditional screening. These are the escapes this system
        exists to stop; <Link href="/console/components" className="link">Components</Link> lists
        all {s.parts.toLocaleString()} parts, including the gross failures the datasheet already catches.
      </p>

      {/* ---------------------------------------------------------- lots */}
      <SectionTitle title="Lot disposition" note="A lot over the PDA gate goes to engineering review." />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <Figure
          title="Reject fraction per lot"
          note="L04 is the deliberately degraded lot in this dataset. The screen finds it without being told it exists."
        >
          <PdaBars
            lots={lots.map((l) => ({ lot: l.lot, rejectFrac: l.rejectFrac, breach: l.pdaStatus !== "OK" }))}
            limit={meta.pdaLimit}
          />
        </Figure>

        <Card className="overflow-x-auto">
          <CardHead title="Lot register" meta="Select a lot for its distribution and ranking." />
          <table className="tbl min-w-[560px]">
            <thead>
              <tr>
                <th>Lot</th><th className="n">Parts</th><th className="n">Accept</th>
                <th className="n">Watch</th><th className="n">Reject</th><th className="n">Reject share</th>
                <th>PDA gate</th>
              </tr>
            </thead>
            <tbody>
              {lots.map((l) => (
                <tr key={l.lot}>
                  <td><Link href={`/console/lots?lot=${l.lot}`} className="link">{l.lot}</Link></td>
                  <td className="n">{l.parts}</td>
                  <td className="n text-pass">{l.accept}</td>
                  <td className="n text-watch">{l.watch}</td>
                  <td className="n text-reject">{l.reject}</td>
                  <td className="n">{pct(l.rejectFrac, 1)}</td>
                  <td className={l.pdaStatus === "OK" ? "text-pass" : "font-semibold text-reject"}>
                    {l.pdaStatus === "OK" ? "Within" : "Review"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>

      <Provenance modelVersion={meta.modelVersion} source={meta.generatedFrom} />
    </>
  );
}
