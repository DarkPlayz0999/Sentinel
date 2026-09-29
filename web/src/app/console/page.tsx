"use client";

import Link from "next/link";
import { useMemo } from "react";
import { ConsoleState } from "@/components/console/shell";
import { PdaBars, ScoreBands } from "@/components/charts/charts";
import {
  ChartNote, Field, Meter, Panel, PanelHead, ProvenanceNote, SectionHead,
  Stat, VerdictChip, num, pct,
} from "@/components/ui/kit";
import { histogram, useConsole } from "@/lib/console";

/* OVERVIEW — "Which components should the reliability engineer investigate,
 * and is any lot misbehaving?" Nothing on this screen is decorative: every
 * tile is a count or a rate the screen produced. */

export default function Overview() {
  const { data, error } = useConsole();

  const scoreBins = useMemo(
    () => (data ? histogram(data.parts.map((p) => p.r), 0, 100, 50) : []),
    [data]
  );
  const worst = useMemo(
    () =>
      data
        ? [...data.parts].sort((a, b) => b.r - a.r).slice(0, 12)
        : [],
    [data]
  );

  if (!data) return <ConsoleState error={error} />;
  const { summary: s, meta, lots } = data;

  return (
    <div className="space-y-7">
      {/* ---------------------------------------------------- disposition */}
      <section>
        <SectionHead
          index="01"
          title="Screening disposition"
          note={`${s.parts.toLocaleString()} components · ${s.lots} lots · one signed record per part`}
        />

        <div className="grid grid-cols-2 gap-px bg-lab-rule sm:grid-cols-3 lg:grid-cols-6">
          <Stat k="Components" v={s.parts.toLocaleString()} sub="screened this run" />
          <Stat
            k="Accept"
            v={s.accept.toLocaleString()}
            tone="text-sig-green"
            sub={`${pct(s.accept / s.parts)} of population`}
          />
          <Stat
            k="Watch"
            v={s.watch.toLocaleString()}
            tone="text-sig-amber"
            sub="ship with the serial flagged"
          />
          <Stat
            k="Reject"
            v={s.reject.toLocaleString()}
            tone="text-sig-red"
            sub={`${pct(s.reject / s.parts)} — sized to the PDA budget`}
          />
          <Stat
            k="Lot health"
            v={`${s.lots - s.lotsBreachingPda}/${s.lots}`}
            tone={s.lotsBreachingPda ? "text-sig-amber" : "text-sig-green"}
            sub={`${s.lotsBreachingPda} lot(s) over the ${pct(meta.pdaLimit, 0)} PDA gate`}
          />
          <Stat
            k="Latent risk"
            v={s.latent.toLocaleString()}
            sub={`known latent defects in this simulated lot set`}
          />
        </div>
      </section>

      {/* ------------------------------------------------------ the gap */}
      <section>
        <SectionHead
          index="02"
          title="What the datasheet limits missed"
          note="the reason this console exists"
        />
        <div className="grid gap-px bg-lab-rule lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <Panel className="border-0 p-4">
            <div className="grid grid-cols-2 gap-px bg-lab-rule">
              <div className="bg-lab-card px-3 py-3">
                <div className="label">Static datasheet screen</div>
                <div className="readout mt-1.5 text-[24px] font-semibold leading-none text-lab-ink">
                  {pct(s.staticRecall, 1)}
                </div>
                <div className="mt-1.5 font-mono text-[9px] leading-tight text-lab-faint">
                  latent-defect recall. {s.staticFlagged} parts breach a limit at 168 h; not one
                  of them is a latent defect.
                </div>
              </div>
              <div className="bg-lab-card px-3 py-3">
                <div className="label">SENTINEL screen</div>
                <div className="readout mt-1.5 text-[24px] font-semibold leading-none text-sig-blue">
                  {pct(s.flaggedRecall, 1)}
                </div>
                <div className="mt-1.5 font-mono text-[9px] leading-tight text-lab-faint">
                  latent-defect recall at {pct(s.flaggedOverkill, 1)} overkill, measured against
                  healthy parts only.
                </div>
              </div>
            </div>

            <div className="mt-4 space-y-2.5">
              {[
                { k: "Latent defects passing every static limit at 168 h", v: `${s.latent} / ${s.latent}`, tone: "text-sig-red" },
                { k: "Recall at a 5% overkill budget", v: pct(s.recallAt5, 1) },
                { k: "Recall at a 10% overkill budget", v: pct(s.recallAt10, 1) },
                { k: "Fused score PR-AUC", v: num(s.fusedPrAuc, 4) },
              ].map((r) => (
                <div key={r.k} className="flex items-baseline justify-between gap-3 border-b border-lab-hair pb-1.5">
                  <span className="font-mono text-[10px] text-lab-dim">{r.k}</span>
                  <span className={`readout text-[12px] font-semibold ${r.tone ?? "text-lab-ink"}`}>
                    {r.v}
                  </span>
                </div>
              ))}
            </div>
            <ChartNote>
              Accuracy is deliberately not reported. At {pct(s.latent / s.parts, 1)} prevalence a
              screen that says &ldquo;all good&rdquo; scores {pct(1 - s.latent / s.parts, 1)} and
              catches nothing — <code>src/evaluate.py</code> raises rather than compute it.
            </ChartNote>
          </Panel>

          <Panel className="border-0 p-4">
            <PanelHead
              title="Risk score distribution"
              meta={`bands sized to the ${pct(meta.pdaLimit, 0)} PDA budget`}
              className="-mx-4 -mt-4 mb-3 px-4"
            />
            <ScoreBands bins={scoreBins} watch={meta.bands.watch} reject={meta.bands.reject} />
            <ChartNote>
              WATCH ≥ {num(meta.bands.watch, 1)} · REJECT ≥ {num(meta.bands.reject, 1)}. Only
              REJECT consumes PDA budget; WATCH parts ship with the serial flagged, which is what
              lets the screen buy recall without scrapping a lot.
            </ChartNote>
          </Panel>
        </div>
      </section>

      {/* --------------------------------------------------------- lots */}
      <section>
        <SectionHead index="03" title="Lot disposition" note="PDA gate, per lot" />
        <div className="grid gap-px bg-lab-rule lg:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
          <Panel className="border-0 p-4">
            <PdaBars
              lots={lots.map((l) => ({
                lot: l.lot,
                rejectFrac: l.rejectFrac,
                breach: l.pdaStatus !== "OK",
              }))}
              limit={meta.pdaLimit}
            />
            <ChartNote>
              A lot over the gate goes to engineering review rather than shipping. L04 is the
              deliberately degraded lot in this dataset and the screen finds it without being
              told it exists.
            </ChartNote>
          </Panel>

          <Panel className="overflow-x-auto border-0">
            <PanelHead title="Lot register" meta="click a lot for its distribution and ranking" />
            <table className="w-full min-w-[620px] border-collapse">
              <thead>
                <tr className="border-b border-lab-rule bg-lab-panel">
                  {["Lot", "Parts", "Accept", "Watch", "Reject", "Reject %", "Mean risk", "PDA"].map(
                    (h) => (
                      <th
                        key={h}
                        className="px-3 py-2 text-left font-mono text-[9px] uppercase tracking-label text-lab-faint"
                      >
                        {h}
                      </th>
                    )
                  )}
                </tr>
              </thead>
              <tbody>
                {lots.map((l) => (
                  <tr key={l.lot} className="border-b border-lab-hair hover:bg-lab-panel">
                    <td className="px-3 py-1.5">
                      <Link
                        href={`/console/lots?lot=${l.lot}`}
                        className="readout text-[11px] font-semibold text-sig-blue hover:underline"
                      >
                        {l.lot}
                      </Link>
                    </td>
                    <td className="readout px-3 py-1.5 text-[11px]">{l.parts}</td>
                    <td className="readout px-3 py-1.5 text-[11px] text-sig-green">{l.accept}</td>
                    <td className="readout px-3 py-1.5 text-[11px] text-sig-amber">{l.watch}</td>
                    <td className="readout px-3 py-1.5 text-[11px] text-sig-red">{l.reject}</td>
                    <td className="readout px-3 py-1.5 text-[11px]">{pct(l.rejectFrac, 1)}</td>
                    <td className="px-3 py-1.5">
                      <div className="flex items-center gap-2">
                        <span className="readout w-8 text-[11px]">{num(l.meanRisk, 1)}</span>
                        <span className="w-20">
                          <Meter value={l.meanRisk} max={100} height={5} />
                        </span>
                      </div>
                    </td>
                    <td className="px-3 py-1.5">
                      <span
                        className={`font-mono text-[9px] font-bold uppercase tracking-label ${
                          l.pdaStatus === "OK" ? "text-sig-green" : "text-sig-red"
                        }`}
                      >
                        {l.pdaStatus}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </div>
      </section>

      {/* ----------------------------------------------------- worst parts */}
      <section>
        <SectionHead
          index="04"
          title="Investigation queue"
          note="highest screening risk first"
        />
        <Panel className="overflow-x-auto">
          <table className="w-full min-w-[760px] border-collapse">
            <thead>
              <tr className="border-b border-lab-rule bg-lab-panel">
                {["Component", "Lot", "Risk", "Dynamic σ", "Pooled", "Slope ratio", "Static", "Decision"].map(
                  (h) => (
                    <th
                      key={h}
                      className="px-3 py-2 text-left font-mono text-[9px] uppercase tracking-label text-lab-faint"
                    >
                      {h}
                    </th>
                  )
                )}
              </tr>
            </thead>
            <tbody>
              {worst.map((p) => (
                <tr key={p.s} className="border-b border-lab-hair hover:bg-lab-panel">
                  <td className="px-3 py-1.5">
                    <Link
                      href={`/console/components?id=${p.s}`}
                      className="readout text-[11px] font-semibold text-sig-blue hover:underline"
                    >
                      {p.s}
                    </Link>
                  </td>
                  <td className="readout px-3 py-1.5 text-[11px] text-lab-dim">{p.l}</td>
                  <td className="px-3 py-1.5">
                    <div className="flex items-center gap-2">
                      <span className="readout w-9 text-[11px] font-semibold">{num(p.r, 1)}</span>
                      <span className="w-16">
                        <Meter
                          value={p.r}
                          max={100}
                          height={5}
                          color={p.v === "REJECT" ? "#A81E12" : p.v === "WATCH" ? "#9A5B06" : "#186B45"}
                        />
                      </span>
                    </div>
                  </td>
                  <td className="readout px-3 py-1.5 text-[11px]">{num(p.l2, 2)}σ</td>
                  <td className="readout px-3 py-1.5 text-[11px]">{num(p.l3, 1)}</td>
                  <td className="readout px-3 py-1.5 text-[11px]">
                    {p.wr === null ? "—" : `${num(p.wr, 2)}×`}
                  </td>
                  <td className="px-3 py-1.5 font-mono text-[9px] font-bold uppercase tracking-label">
                    <span className={p.st ? "text-sig-red" : "text-sig-green"}>
                      {p.st ? "BREACH" : "PASS"}
                    </span>
                  </td>
                  <td className="px-3 py-1.5">
                    <VerdictChip v={p.v} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
        <p className="mt-2 font-mono text-[9px] text-lab-faint">
          <span className="font-bold text-lab-dim">Static</span> is the traditional datasheet
          verdict at 168 h. A row reading <span className="text-sig-green">PASS</span> against a
          SENTINEL <span className="text-sig-red">REJECT</span> is exactly the escape this system
          exists to stop.
        </p>
      </section>

      <ProvenanceNote modelVersion={meta.modelVersion} source={meta.generatedFrom} />
    </div>
  );
}
