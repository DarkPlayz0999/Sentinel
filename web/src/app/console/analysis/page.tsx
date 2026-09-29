"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ConsoleState } from "@/components/console/shell";
import {
  LotDistribution, RecallOverkill, ScoreBands, Trajectory,
} from "@/components/charts/charts";
import {
  ChartNote, FlowTape, Meter, Panel, PanelHead, ProvenanceNote, SectionHead,
  Stat, VerdictChip, num, pct, sigma, unit,
} from "@/components/ui/kit";
import {
  histogram, lotEnvelope, measurement, partsInLot, policySweep, quantile,
  recallOverkillCurve, useConsole,
} from "@/lib/console";
import { cn } from "@/lib/utils";

/* ANALYSIS — the method, demonstrated on a real screened component, plus the
 * decision policy control.
 *
 * Module A answers "is this component behaving like its siblings?".
 * Module B answers "where is it heading, and can we know early?".
 * Decision policy answers "how much good silicon are we willing to scrap?". */

const RATIOS = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000];

function Inner() {
  const { data, error } = useConsole();
  const [ratioIdx, setRatioIdx] = useState(6); // 100:1, the stated default

  // The demonstration part: the highest-risk component that still passes every
  // static datasheet limit. Chosen from the data, never hardcoded - if the
  // dataset is regenerated this follows it.
  const subject = useMemo(() => {
    if (!data) return null;
    const escapes = data.parts.filter((p) => p.st === 0 && p.y1 === 1);
    return escapes.sort((a, b) => b.l2 - a.l2)[0] ?? null;
  }, [data]);

  const policy = useMemo(
    () => (data ? policySweep(data.parts, RATIOS[ratioIdx], data.meta.pdaLimit) : null),
    [data, ratioIdx]
  );
  const curve = useMemo(() => (data ? recallOverkillCurve(data.parts) : []), [data]);
  const scoreBins = useMemo(
    () => (data ? histogram(data.parts.map((p) => p.r), 0, 100, 50) : []),
    [data]
  );

  if (!data || !subject || !policy) return <ConsoleState error={error} />;
  const { meta, summary } = data;

  const pi = 0; // Iddq_uA - the most sensitive CMOS defect indicator
  const pm = meta.params[pi];
  const lot = data.lots.find((l) => l.lot === subject.l)!;
  const lotRows = partsInLot(data.parts, subject.l);
  const at168 = lotRows.map((p) => measurement(p, pi, 3)).filter((v): v is number => v !== null);
  const hi = Math.max(quantile(at168, 0.995), subject.m[pi][3] ?? 0) * 1.08;
  const lo = quantile(at168, 0.002) * 0.9;
  const med = lot.ref[pm.name].median[3];
  const v168 = subject.m[pi][3] ?? 0;

  return (
    <div className="space-y-8">
      {/* ================================================== MODULE A === */}
      <section>
        <SectionHead
          index="MODULE A"
          title="Dynamic lot-relative detection"
          note="is this component behaving like its siblings?"
        />

        <div className="grid gap-px bg-lab-rule lg:grid-cols-2">
          <Panel className="border-0 p-4">
            <div className="label mb-2">Traditional screen</div>
            <FlowTape
              steps={[
                { k: "Input", v: `${pm.name} = ${num(v168, 1)} ${unit(pm.unit)}` },
                { k: "Test", v: `${num(v168, 1)} < ${pm.usl} ${unit(pm.unit)}` },
                { k: "Verdict", v: "PASS — component ships", tone: "text-sig-green" },
              ]}
            />
            <p className="mt-3 font-mono text-[10px] leading-relaxed text-lab-dim">
              One number, one limit. It catches gross failures and nothing else: in this dataset
              static limits flag {summary.staticFlagged} components at 168 h and{" "}
              <span className="font-bold text-sig-red">not one</span> of the {summary.latent}{" "}
              latent defects.
            </p>
          </Panel>

          <Panel className="border-0 p-4">
            <div className="label mb-2">SENTINEL screen</div>
            <FlowTape
              steps={[
                { k: "Input", v: `${pm.name} trace, 0 → 168 h` },
                { k: "Reference", v: `lot ${subject.l} median ${num(med, 1)} ${unit(pm.unit)}` },
                { k: "Robust deviation", v: `${sigma(subject.l2)} — L2 dynamic PAT` },
                { k: "Pooled evidence", v: `${num(subject.l3, 1)} — L3, four drift axes` },
                { k: "Verdict", v: `${subject.v} — risk ${num(subject.r, 1)}/100`, tone: "text-sig-red" },
              ]}
            />
          </Panel>
        </div>

        {/* the three layers */}
        <div className="mt-px grid gap-px bg-lab-rule sm:grid-cols-3">
          {[
            {
              tag: "L1 · STATIC",
              v: subject.st ? "BREACH" : "PASS",
              tone: subject.st ? "text-sig-red" : "text-sig-green",
              what: "Datasheet upper limit at any read point. The layer we exist to beat, kept in the pipeline permanently so the gap stays visible.",
            },
            {
              tag: "L2 · DPAT",
              v: sigma(subject.l2),
              tone: "text-sig-red",
              what: "Worst-case robust z across every parameter and view, computed per lot. Median and 1.4826·MAD, never mean and σ — a mean-based limit is inflated by the outlier it is hunting.",
            },
            {
              tag: "L3 · POOLED",
              v: num(subject.l3, 1),
              tone: "text-sig-red",
              what: `One-sided sum of squared robust z over the four drift axes, against a χ²(0.999) threshold of ${num(meta.thresholds["R-401"], 1)}. Catches components moderately elevated on several axes at once.`,
            },
          ].map((l) => (
            <div key={l.tag} className="bg-lab-card px-3.5 py-3">
              <div className="flex items-baseline justify-between">
                <span className="font-mono text-[9.5px] font-bold uppercase tracking-label text-lab-ink">
                  {l.tag}
                </span>
                <span className={cn("readout text-[15px] font-bold", l.tone)}>{l.v}</span>
              </div>
              <p className="mt-2 font-mono text-[9px] leading-relaxed text-lab-faint">{l.what}</p>
            </div>
          ))}
        </div>

        <div className="mt-px bg-lab-card px-4 py-3">
          <div className="flex flex-wrap items-center gap-3">
            <span className="label">Result</span>
            <VerdictChip v={subject.v} size="lg" />
            <Link
              href={`/console/components?id=${subject.s}`}
              className="readout text-[11px] font-semibold text-sig-blue hover:underline"
            >
              {subject.s}
            </Link>
            <span className="font-mono text-[10px] text-lab-dim">
              flagged on lot-relative evidence while inside every datasheet limit
            </span>
          </div>
        </div>

        <div className="mt-4">
          <Panel className="p-4">
            <PanelHead
              title={`The same component against its lot — ${pm.name} at 168 h`}
              meta={`lot ${subject.l} · n=${lotRows.length}`}
              className="-mx-4 -mt-4 mb-3 px-4"
            />
            <LotDistribution
              bins={histogram(at168, lo, hi, 50)}
              defectBins={histogram(
                lotRows.filter((p) => p.y1 === 1).map((p) => measurement(p, pi, 3)).filter((v): v is number => v !== null),
                lo, hi, 50
              )}
              lo={lo}
              hi={hi}
              unitName={pm.name}
              usl={pm.usl}
              med={med}
              sig={lot.ref[pm.name].sigma168}
              marker={v168}
              markerLabel={`${subject.s} — ${num(v168, 1)} ${unit(pm.unit)}`}
              w={900}
              h={260}
            />
            <ChartNote>
              The datasheet limit did not change. The <em>reference</em> did. Against a
              50 {unit(pm.unit)} static limit this component is unremarkable; against its own
              lot&rsquo;s median of {num(med, 1)} {unit(pm.unit)} it is {sigma(subject.l2)} out.
            </ChartNote>
          </Panel>
        </div>
      </section>

      {/* ================================================== MODULE B === */}
      <section>
        <SectionHead
          index="MODULE B"
          title="Early drift forecast"
          note="triage at hour 24, not a replacement for the full screen"
        />

        <div className="grid gap-px bg-lab-rule xl:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
          <Panel className="border-0 p-4">
            <PanelHead
              title={`Forecast from the first 24 hours — ${subject.s}`}
              meta="measured solid · forecast dashed"
              className="-mx-4 -mt-4 mb-3 px-4"
            />
            <Trajectory
              hours={meta.readPoints}
              values={subject.m[pi]}
              envelope={lotEnvelope(data.parts, subject.l, pi)}
              usl={pm.usl}
              forecast={subject.fc?.[pi] ?? null}
              unitName={pm.name}
              serial={subject.s}
              w={620}
              h={268}
            />
            <ChartNote>
              Module B fits V(t) = V₀·(1 + A·(t/168)ⁿ) with one global exponent per parameter and
              solves the amplitude per component from the single delta available at hour 24. It
              sees the 0 h and 24 h reads and nothing else — the 96 h and 168 h points are drawn
              here only so the forecast can be checked against what actually happened.
            </ChartNote>
          </Panel>

          <Panel className="border-0 p-4">
            <PanelHead title="Forecast record" className="-mx-4 -mt-4 mb-3 px-4" />
            <div className="grid grid-cols-2 gap-px bg-lab-hair">
              {[
                { k: `Value @ 0 h`, v: `${num(subject.m[pi][0], 2)} ${unit(pm.unit)}` },
                { k: `Value @ 24 h`, v: `${num(subject.m[pi][1], 2)} ${unit(pm.unit)}` },
                {
                  k: `Predicted @ 168 h`,
                  v: `${num(subject.fc?.[pi], 2)} ${unit(pm.unit)}`,
                  tone: "text-sig-amber",
                },
                {
                  k: `Measured @ 168 h`,
                  v: `${num(subject.m[pi][3], 2)} ${unit(pm.unit)}`,
                },
                {
                  k: "Safety-slope ratio",
                  v: subject.wr === null ? "—" : `${num(subject.wr, 2)}×`,
                  tone: subject.wr !== null && subject.wr > 1 ? "text-sig-red" : undefined,
                },
                { k: "Limiting parameter", v: subject.wp ?? "—" },
              ].map((f) => (
                <div key={f.k} className="bg-lab-card px-3 py-2">
                  <div className="label">{f.k}</div>
                  <div className={cn("readout mt-1 text-[13px] font-semibold", f.tone ?? "text-lab-ink")}>
                    {f.v}
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-3 border-l-[3px] border-l-sig-amber bg-lab-panel px-3 py-2.5">
              <div className="font-mono text-[9px] font-bold uppercase tracking-label text-lab-ink">
                What Module B does and does not claim
              </div>
              <p className="mt-1.5 font-mono text-[9.5px] leading-relaxed text-lab-dim">
                It is a <strong>triage layer</strong>, not an earlier equivalent screen. The
                forecast adds little to <em>detection</em> — a forecast is a near-monotone
                function of the early delta, and the level carries no defect information. What it
                buys is time: components pulled at hour 24 free{" "}
                <span className="readout font-semibold text-lab-ink">144 oven-hours</span> each on
                the capacity-limiting resource of the whole screening line.
              </p>
            </div>

            <div className="mt-3">
              <div className="label mb-1.5">Decision rule</div>
              <FlowTape
                steps={[
                  { k: "Predict", v: "168 h value from 0 h + 24 h" },
                  { k: "Bound", v: "0.90 quantile — reject only if even the optimistic case breaches" },
                  { k: "Compare", v: "predicted slope vs safety slope" },
                  {
                    k: "Gate",
                    v: subject.wr !== null && subject.wr > 1 ? "R-301 fires" : "within slope",
                    tone: subject.wr !== null && subject.wr > 1 ? "text-sig-red" : "text-sig-green",
                  },
                ]}
              />
            </div>
          </Panel>
        </div>
      </section>

      {/* ============================================ DECISION POLICY === */}
      <section>
        <SectionHead
          index="13"
          title="Decision policy"
          note="how much good silicon are we willing to scrap?"
        />

        <div className="grid gap-px bg-lab-rule xl:grid-cols-[minmax(0,440px)_minmax(0,1fr)]">
          <Panel className="border-0 p-4">
            <PanelHead title="False-negative cost" className="-mx-4 -mt-4 mb-4 px-4" />

            <div className="mb-2 flex items-baseline justify-between">
              <span className="label">C_FN / C_FP</span>
              <span className="readout text-[22px] font-bold leading-none text-lab-ink">
                {RATIOS[ratioIdx]} : 1
              </span>
            </div>
            <input
              type="range"
              min={0}
              max={RATIOS.length - 1}
              step={1}
              value={ratioIdx}
              onChange={(e) => setRatioIdx(Number(e.target.value))}
              aria-label="False-negative to false-positive cost ratio"
              className="h-1 w-full cursor-pointer appearance-none bg-lab-sunk accent-sig-blue"
            />
            <div className="mt-1.5 flex justify-between font-mono text-[8.5px] text-lab-faint">
              {RATIOS.map((r, i) => (
                <span key={r} className={cn(i === ratioIdx && "font-bold text-lab-ink")}>
                  {r}
                </span>
              ))}
            </div>

            <p className="mt-3 font-mono text-[9.5px] leading-relaxed text-lab-dim">
              Higher values prioritise catching latent defects over minimising overkill. The
              threshold below is the one that minimises{" "}
              <span className="readout text-lab-ink">C_FN·FN + C_FP·FP</span> at the stated
              ratio — a policy an engineer sets, never a magic number baked into a model.
            </p>

            <div className="mt-4 grid grid-cols-2 gap-px bg-lab-hair">
              <Stat k="Reject threshold" v={num(policy.threshold, 1)} sub="on the 0–100 risk score" />
              <Stat k="Flagged" v={policy.flagged.toLocaleString()} sub={pct(policy.flaggedFraction, 1) + " of population"} />
              <Stat k="Recall" v={pct(policy.recall, 1)} tone="text-sig-blue" sub="latent defects caught" />
              <Stat
                k="Overkill"
                v={pct(policy.overkill, 1)}
                tone={policy.overkill > 0.1 ? "text-sig-red" : "text-sig-amber"}
                sub="healthy components scrapped"
              />
              <Stat k="Precision" v={pct(policy.precision, 1)} />
              <Stat
                k="Lots over PDA"
                v={`${policy.lotsBreaching} / ${data.lots.length}`}
                tone={policy.lotsBreaching ? "text-sig-red" : "text-sig-green"}
                sub={`gate ${pct(meta.pdaLimit, 0)}`}
              />
            </div>

            {policy.lotsBreaching >= data.lots.length && (
              <div className="mt-3 border-l-[3px] border-l-sig-red bg-sig-red/[0.05] px-3 py-2.5">
                <p className="font-mono text-[9.5px] leading-relaxed text-lab-ink">
                  <span className="font-bold text-sig-red">Not implementable.</span> At this ratio
                  every lot breaches its PDA gate — the line would scrap whole lots rather than
                  save them. This is exactly why the shipped verdict uses three bands: WATCH
                  absorbs the recall pressure without consuming PDA budget.
                </p>
              </div>
            )}
          </Panel>

          <div className="grid gap-px bg-lab-rule">
            <Panel className="border-0 p-4">
              <PanelHead
                title="Recall against the over-rejection budget"
                meta="operating point marked"
                className="-mx-4 -mt-4 mb-3 px-4"
              />
              <RecallOverkill
                points={curve}
                mark={{ overkill: policy.overkill, recall: policy.recall }}
              />
              <ChartNote>
                Overkill counts false positives among <strong>healthy components only</strong>.
                Flagging a gross failure is correct behaviour, not over-rejection, and mixing the
                two flatters the screen.
              </ChartNote>
            </Panel>

            <Panel className="border-0 p-4">
              <PanelHead
                title="Where the policy cuts the population"
                meta={`shipped bands: WATCH ≥ ${num(meta.bands.watch, 1)} · REJECT ≥ ${num(meta.bands.reject, 1)}`}
                className="-mx-4 -mt-4 mb-3 px-4"
              />
              <ScoreBands
                bins={scoreBins}
                watch={meta.bands.watch}
                reject={meta.bands.reject}
                threshold={policy.threshold}
              />
              <ChartNote>
                The dashed black rule is the cost-optimal threshold at the ratio selected above.
                The coloured bands are what the screen actually shipped, sized to the{" "}
                {pct(meta.pdaLimit, 0)} PDA budget rather than to the raw cost optimum.
              </ChartNote>
            </Panel>
          </div>
        </div>
      </section>

      <ProvenanceNote modelVersion={meta.modelVersion} source={meta.generatedFrom} />
    </div>
  );
}

export default function AnalysisPage() {
  return <Inner />;
}
