"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ConsoleState } from "@/components/console/shell";
import { PdaBars, ScoreBands } from "@/components/charts/charts";
import {
  Card, CardHead, Figure, PageHead, Provenance, Risk, SectionTitle, Stamp,
  num, pct,
} from "@/components/ui/kit";
import { ConsoleData, histogram, useConsole } from "@/lib/console";
import { Carefulness } from "@/components/site/careful";
import { Term } from "@/components/ui/term";

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
        title="Results at a glance"
        lede={<>{s.parts.toLocaleString()} chips from {s.lots} <Term t="lot">batches</Term> went through a week of{" "}
          <Term t="burn-in">burn-in</Term>. Here is what the old test caught, what SENTINEL caught, and which chips to look at first.</>}
      />

      {/* ------------------------------------------------ start here */}
      <ol className="mb-6 flex flex-wrap items-center gap-x-2 gap-y-2 text-sm" aria-label="How to read this page">
        {[
          { h: "See the gap", href: "#gap" },
          { h: "Set how careful to be", href: "#careful" },
          { h: "Open a chip", href: "#queue" },
        ].map((x, i) => (
          <li key={x.h} className="flex items-center gap-2">
            {i > 0 && <span aria-hidden className="hidden text-mute sm:inline">→</span>}
            <a href={x.href} className="inline-flex min-h-[40px] items-center gap-2 rounded-full border border-rule bg-sheet py-1 pl-1 pr-4 font-bold transition-colors hover:border-ink">
              <span className="grid h-8 w-8 place-items-center rounded-full bg-ink text-sheet">{i + 1}</span>
              {x.h}
            </a>
          </li>
        ))}
      </ol>

      {/* ------------------------------------------------ the gap, stated */}
      <Scoreboard data={data} />

      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <Figure
          title="Every chip's risk score"
          meta="0 = nothing unusual, 100 = alarming"
          note="Left of the first line: accept. Between the lines: ship, but flag for a second look. Right of the second line: reject. The lines are placed so no more than 5% of chips are rejected."
        >
          <ScoreBands bins={scoreBins} watch={meta.bands.watch} reject={meta.bands.reject} />
        </Figure>
        <Card className="flex flex-col p-5">
          <h2 className="text-sm font-bold">What happens to the {s.parts.toLocaleString()} chips</h2>
          <div className="mt-4 flex h-10 overflow-hidden rounded-[8px]" role="img"
            aria-label={`${s.accept} accept, ${s.watch} watch, ${s.reject} reject`}>
            {[
              { n: s.accept, c: "bg-pass" }, { n: s.watch, c: "bg-watch" }, { n: s.reject, c: "bg-reject" },
            ].map((x, i) => (
              <span key={i} className={`${x.c} grow-in`} style={{ width: `${(x.n / s.parts) * 100}%`, animationDelay: `${i * 120}ms` }} />
            ))}
          </div>
          <dl className="mt-5 space-y-3">
            {[
              { k: "● Accept", t: "ships as normal", n: s.accept, c: "text-pass" },
              { k: "▲ Watch", t: "ships, serial flagged for a second look", n: s.watch, c: "text-watch" },
              { k: "■ Reject", t: "pulled, with a written reason", n: s.reject, c: "text-reject" },
            ].map((x) => (
              <div key={x.k} className="flex items-baseline justify-between gap-4 border-b border-hair pb-2">
                <dt><span className={`font-bold ${x.c}`}>{x.k}</span> <span className="text-sm text-graphite">{x.t}</span></dt>
                <dd className={`wide text-2xl font-extrabold ${x.c}`}>{x.n.toLocaleString()}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-auto pt-4 text-sm text-graphite">
            {s.lots - s.lotsBreachingPda} of {s.lots} batches stay within the{" "}
            <Term t="pda">5% reject limit</Term>; {s.lotsBreachingPda} go to engineering review.
          </p>
        </Card>
      </div>

      {/* ----------------------------------------------------- the queue */}
      <section id="careful" className="mt-10 scroll-mt-6">
        <SectionTitle title="How careful should the screen be?" note="Drag the handle. Counts are recomputed from every chip in this run." />
        <Card className="p-5 sm:p-6"><Carefulness data={data} /></Card>
      </section>

      <div id="queue" className="scroll-mt-6" />
      <SectionTitle title="Chips to look at first" note="They pass every datasheet limit, yet SENTINEL flagged them. Riskiest first; click a serial to open it." />
      <Card className="overflow-x-auto">
        <table className="tbl min-w-[760px]">
          <thead>
            <tr>
              <th>Component</th><th>Lot</th><th>Risk</th>
              <th className="n">Distance from batch</th><th className="n">Small signs combined</th>
              <th className="n">Rise vs safe rate</th><th>Old test</th><th>SENTINEL</th>
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
      <SectionTitle title="Batches" note="If more than 5% of a batch is rejected, the whole batch goes to engineering review." />
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

/** Counts up to `to` once on mount. Reduced motion shows the final value. */
function useCountUp(to: number, ms = 1200) {
  const [v, setV] = useState(0);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) { setV(to); return; }
    let raf = 0;
    const t0 = performance.now();
    const tick = (t: number) => {
      const f = Math.min(1, (t - t0) / ms);
      setV(Math.round(to * (1 - Math.pow(1 - f, 3))));
      if (f < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [to, ms]);
  return v;
}

/* The page's one bold element: the same hidden defects, judged by both tests.
 * Each square is a real latent defect from this run, riskiest first. */
function Scoreboard({ data }: { data: ConsoleData }) {
  const { summary: s } = data;
  const latent = useMemo(() => data.parts.filter((p) => p.tc === "latent").sort((a, b) => b.r - a.r), [data]);
  const caught = latent.filter((p) => p.v !== "ACCEPT").length;
  const oldCaught = latent.filter((p) => p.st === 1).length;
  const nOld = useCountUp(oldCaught), nNew = useCountUp(caught);

  const side = (title: string, sub: string, n: number, isNew: boolean) => (
    <div className="min-w-0 p-5 sm:p-7">
      <p className="text-sm text-[#9FB5B0]">{title}</p>
      <p className="mt-1 font-bold text-[#E7EFEC]">{sub}</p>
      <p className="wide mt-4 text-6xl font-extrabold leading-none sm:text-7xl" style={{ color: isNew ? "#7FD6A8" : "#FF7A6B" }}>
        {n}<span className="text-2xl text-[#9FB5B0] sm:text-3xl"> of {latent.length}</span>
      </p>
      <p className="mt-2 text-sm text-[#9FB5B0]">hidden defects caught ({Math.round((n / latent.length) * 100)}%)</p>
      <div className="mt-5 grid grid-cols-[repeat(auto-fill,minmax(11px,1fr))] gap-[4px]" aria-hidden>
        {latent.map((p, i) => {
          const hit = isNew ? p.v !== "ACCEPT" : p.st === 1;
          return (
            <span key={p.s} className={hit ? "tray-fill aspect-square rounded-[2px] bg-[#7FD6A8]" : "aspect-square rounded-[2px] border border-[#FF7A6B]/60"}
              style={hit ? { animationDelay: `${300 + i * 6}ms` } : undefined} />
          );
        })}
      </div>
    </div>
  );

  return (
    <section id="gap" className="scroll-mt-6 overflow-hidden rounded-[14px] bg-oven text-[#E7EFEC]">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-[#1E4A45] px-5 py-4 sm:px-7">
        <h2 className="wide text-xl font-bold sm:text-2xl">
          {latent.length} chips in this run carry a <Term t="latent defect">hidden defect</Term>. Who catches them?
        </h2>
        <span className="text-sm text-[#9FB5B0]">one square = one chip · filled = caught · outline = would fly</span>
      </div>
      <div className="grid md:grid-cols-2 md:divide-x md:divide-[#1E4A45]">
        {side("The old test", "Is every reading under the datasheet limit?", nOld, false)}
        {side("SENTINEL", "Is the chip behaving like its batch?", nNew, true)}
      </div>
      <dl className="grid grid-cols-2 gap-px border-t border-[#1E4A45] bg-[#1E4A45] text-sm sm:grid-cols-4">
        {[
          ["Good chips checked twice", pct(s.flaggedOverkill, 1)],
          ["Caught if 5% of good chips are flagged", pct(s.recallAt5, 1)],
          ["Caught if 10% are flagged", pct(s.recallAt10, 1)],
          ["Chips the old test rejects", `${s.staticFlagged}, all obvious failures`],
        ].map(([k, v]) => (
          <div key={k} className="bg-oven px-5 py-3 sm:px-7">
            <dt className="text-[#9FB5B0]">{k}</dt>
            <dd className="mt-0.5 text-lg font-bold">{v}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
