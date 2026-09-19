"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ConsoleState } from "@/components/console/shell";
import { LotDistribution, RecallOverkill, ScoreBands, Trajectory } from "@/components/charts/charts";
import {
  Card, CardHead, Figure, Notice, PageHead, Provenance, SectionTitle, Stamp, Stat, Steps,
  num, pct, sigma, unit,
} from "@/components/ui/kit";
import {
  histogram, lotBands, lotEnvelope, measurement, partsInLot, policySweep, quantile,
  recallOverkillCurve, useConsole,
} from "@/lib/console";
import { cn } from "@/lib/utils";

/* METHOD AND POLICY - the method demonstrated on a real screened component,
 * plus the decision-policy control.
 *
 * Module A answers "is this component behaving like its siblings?".
 * Module B answers "where is it heading, and can we know early?".
 * The policy answers "how much good silicon are we willing to scrap?". */

const RATIOS = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000];

export default function AnalysisPage() {
  const { data, error } = useConsole();
  const [ratioIdx, setRatioIdx] = useState(6); // 100:1, the stated default

  // The demonstration part: the most lot-deviant latent defect that still
  // passes every datasheet limit. Chosen from the data, never hardcoded.
  const subject = useMemo(() => {
    if (!data) return null;
    return data.parts.filter((p) => p.st === 0 && p.y1 === 1).sort((a, b) => b.l2 - a.l2)[0] ?? null;
  }, [data]);
  const policy = useMemo(
    () => (data ? policySweep(data.parts, RATIOS[ratioIdx], data.meta.pdaLimit) : null),
    [data, ratioIdx]
  );
  const curve = useMemo(() => (data ? recallOverkillCurve(data.parts) : []), [data]);
  const scoreBins = useMemo(() => (data ? histogram(data.parts.map((p) => p.r), 0, 100, 50) : []), [data]);

  if (!data || !subject || !policy) return <ConsoleState error={error} />;
  const { meta, summary } = data;

  const pi = 0; // Iddq_uA - the most sensitive CMOS defect indicator
  const pm = meta.params[pi];
  const lotRows = partsInLot(data.parts, subject.l);
  const at168 = lotRows.map((p) => measurement(p, pi, 3)).filter((v): v is number => v !== null);
  const v168 = subject.m[pi][3] ?? 0;
  const hi = Math.max(quantile(at168, 0.995), v168) * 1.08;
  const lo = quantile(at168, 0.002) * 0.9;
  const ref = lotBands(at168, pm.isCurrent);
  const u = unit(pm.unit);
  const slopeFires = subject.wr !== null && subject.wr > 1;

  return (
    <>
      <PageHead
        title="Method and policy"
        lede={<>Both modules demonstrated on {subject.s}, the most lot-deviant latent defect that still passes every datasheet limit, then the policy control that sets how much good silicon the line will scrap.</>}
      />

      {/* ================================================== MODULE A === */}
      <SectionTitle title="Module A: detection against the lot" note="Is this component behaving like its siblings?" />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-5">
          <h3 className="text-sm font-bold">The datasheet screen</h3>
          <Steps
            className="mt-4"
            steps={[
              { k: "Measure", v: `${pm.name} at 168 h = ${num(v168, 1)} ${u}` },
              { k: "Compare with the fixed limit", v: `${num(v168, 1)} < ${pm.usl} ${u}` },
              { k: "Decide", v: "Pass, the component ships", tone: "text-pass" },
            ]}
          />
          <p className="mt-4 text-sm text-graphite">
            One number, one limit. It catches gross failures and nothing else: static limits flag{" "}
            {summary.staticFlagged} parts at 168 h and not one of the {summary.latent} latent defects.
          </p>
        </Card>
        <Card className="p-5">
          <h3 className="text-sm font-bold">The SENTINEL screen</h3>
          <Steps
            className="mt-4"
            steps={[
              { k: "Measure", v: `${pm.name} through burn-in, 0 to 168 h` },
              { k: "Take the lot as reference", v: `Lot ${subject.l} median ${num(ref.median, 1)} ${u}` },
              { k: "Robust deviation (L2)", v: `${sigma(subject.l2)} from the lot` },
              { k: "Pooled evidence (L3)", v: `${num(subject.l3, 1)} across four drift axes` },
              { k: "Decide", v: `${subject.v === "REJECT" ? "Reject" : subject.v === "WATCH" ? "Watch" : "Accept"}, risk ${num(subject.r, 1)} of 100`, tone: "text-reject" },
            ]}
          />
        </Card>
      </div>

      <Card className="mt-4 grid divide-hair md:grid-cols-3 md:divide-x max-md:divide-y">
        {[
          {
            t: "L1 datasheet limit", v: <Stamp v={subject.st ? "BREACH" : "PASS"} />,
            d: "The upper limit at any read point. Kept in the pipeline permanently so the gap stays visible.",
          },
          {
            t: "L2 dynamic part average", v: <span className="text-xl font-bold text-reject">{sigma(subject.l2)}</span>,
            d: "Worst robust z across every parameter and view, per lot. Median and 1.4826·MAD, never mean and σ: a mean-based limit is inflated by the outlier it hunts.",
          },
          {
            t: "L3 pooled evidence", v: <span className="text-xl font-bold text-reject">{num(subject.l3, 1)}</span>,
            d: `One-sided sum of squared robust z over four drift axes, against a χ²(0.999) threshold of ${num(meta.thresholds["R-401"], 1)}.`,
          },
        ].map((l) => (
          <div key={l.t} className="p-5">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-sm font-bold">{l.t}</h3>
              {l.v}
            </div>
            <p className="mt-2 text-sm text-graphite">{l.d}</p>
          </div>
        ))}
      </Card>

      <Figure
        className="mt-4"
        title={<>The same component against its lot</>}
        meta={`${pm.name} at 168 h, lot ${subject.l}, ${at168.length} parts`}
        right={<Link href={`/console/components?id=${subject.s}`} className="link text-sm">Open {subject.s}</Link>}
        note={<>The datasheet limit did not change; the reference did. Against the {pm.usl} {u} limit this component is unremarkable. Against its own lot it is {sigma(subject.l2)} out.</>}
      >
        <LotDistribution
          bins={histogram(at168, lo, hi, 56)}
          defectBins={histogram(lotRows.filter((p) => p.y1 === 1).map((p) => measurement(p, pi, 3)).filter((v): v is number => v !== null), lo, hi, 56)}
          lo={lo} hi={hi} param={pm.name} unitName={pm.unit} usl={pm.usl}
          med={ref.median} bands={ref.bands}
          marker={v168} markerLabel={`${subject.s}: ${num(v168, 1)} ${u}`}
          w={960} h={280}
        />
      </Figure>

      {/* ================================================== MODULE B === */}
      <SectionTitle title="Module B: the forecast from hour 24" note="Triage early; the full 168 h screen still runs." />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <Figure
          title={`${subject.s} forecast from its first 24 hours`}
          note="Module B fits V(t) = V₀·(1 + A·(t/168)ⁿ) with one exponent per parameter and solves the amplitude per component from the one delta available at hour 24. The 96 h and 168 h points are drawn only so the forecast can be checked."
        >
          <Trajectory hours={meta.readPoints} values={subject.m[pi]} envelope={lotEnvelope(data.parts, subject.l, pi)}
            usl={pm.usl} forecast={subject.fc?.[pi] ?? null} unitName={pm.unit} />
        </Figure>

        <div className="space-y-4">
          <Card>
            <CardHead title="Forecast record" />
            <div className="grid grid-cols-2 gap-x-4 gap-y-3 px-4 py-4">
              {[
                { k: "Value at 0 h", v: `${num(subject.m[pi][0], 2)} ${u}` },
                { k: "Value at 24 h", v: `${num(subject.m[pi][1], 2)} ${u}` },
                { k: "Forecast for 168 h", v: `${num(subject.fc?.[pi], 2)} ${u}`, tone: "text-watch" },
                { k: "Measured at 168 h", v: `${num(subject.m[pi][3], 2)} ${u}` },
                { k: "Safety-slope ratio", v: subject.wr === null ? "—" : `${num(subject.wr, 2)}×`, tone: slopeFires ? "text-reject" : undefined },
                { k: "Limiting parameter", v: subject.wp ?? "—" },
              ].map((f) => (
                <div key={f.k}>
                  <div className="text-xs text-graphite">{f.k}</div>
                  <div className={cn("text-lg font-bold", f.tone)}>{f.v}</div>
                </div>
              ))}
            </div>
            <p className="border-t border-hair px-4 py-3 text-sm text-graphite">
              Decision rule: forecast the 168 h value, bound it at the 0.90 quantile, and pull the
              part only if even that optimistic case exceeds the safety slope.{" "}
              <strong className={slopeFires ? "text-reject" : "text-pass"}>
                {slopeFires ? "R-301 fires for this part." : "This part is within the slope."}
              </strong>
            </p>
          </Card>
          <Notice tone="warn" title="What Module B does and does not claim">
            It is a triage layer, not an earlier equivalent of the full screen. The forecast adds
            little to detection, since it is a near-monotone function of the early delta. What it
            buys is time: <strong>144 oven-hours</strong> freed for every component pulled at hour
            24, on the resource that limits the whole screening line.
          </Notice>
        </div>
      </div>

      {/* ============================================ DECISION POLICY === */}
      <SectionTitle title="Decision policy" note="How much good silicon are we willing to scrap?" />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <Card className="p-5">
          <label htmlFor="ratio" className="text-sm font-bold">Cost of a missed defect, relative to a scrapped good part</label>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="wide text-4xl font-black">{RATIOS[ratioIdx]}</span>
            <span className="text-base text-graphite">to 1</span>
          </div>
          <input
            id="ratio" type="range" min={0} max={RATIOS.length - 1} step={1} value={ratioIdx}
            onChange={(e) => setRatioIdx(Number(e.target.value))}
            aria-valuetext={`${RATIOS[ratioIdx]} to 1`}
            className="mt-3 w-full accent-ink"
          />
          <div className="mt-1 flex justify-between text-xs text-mute">
            {RATIOS.map((r, i) => (
              <span key={r} className={cn(i === ratioIdx && "font-bold text-ink")}>{r}</span>
            ))}
          </div>
          <p className="mt-4 text-sm text-graphite">
            The threshold below minimises <code>C_FN·FN + C_FP·FP</code> at this ratio. It is a
            policy an engineer sets, never a number baked into a model.
          </p>

          <div className="mt-4 grid grid-cols-2 divide-x divide-y divide-hair rounded-card border border-hair">
            <Stat k="Threshold" v={num(policy.threshold, 1)} sub="on the 0 to 100 risk score" />
            <Stat k="Flagged" v={policy.flagged.toLocaleString()} sub={`${pct(policy.flaggedFraction, 1)} of parts`} />
            <Stat k="Recall" v={pct(policy.recall, 1)} tone="text-cobalt" sub="latent defects caught" />
            <Stat k="Overkill" v={pct(policy.overkill, 1)} tone={policy.overkill > 0.1 ? "text-reject" : "text-watch"} sub="healthy parts scrapped" />
            <Stat k="Precision" v={pct(policy.precision, 1)} />
            <Stat k="Lots over the gate" v={`${policy.lotsBreaching} of ${data.lots.length}`}
              tone={policy.lotsBreaching ? "text-reject" : "text-pass"} sub={`gate at ${pct(meta.pdaLimit, 0)}`} />
          </div>

          {policy.lotsBreaching >= data.lots.length && (
            <Notice tone="danger" title="Not implementable at this ratio" className="mt-4">
              Every lot breaches its PDA gate, so the line would scrap whole lots rather than save
              them. This is why the shipped verdict has three bands: watch absorbs the recall
              pressure without consuming PDA budget.
            </Notice>
          )}
        </Card>

        <div className="space-y-4">
          <Figure
            title="Recall against the overkill budget"
            meta="red marks the operating point"
            note="Overkill counts healthy parts only. Flagging a gross failure is correct behaviour, and mixing the two flatters the screen."
          >
            <RecallOverkill points={curve} mark={{ overkill: policy.overkill, recall: policy.recall }} />
          </Figure>
          <Figure
            title="Where the policy cuts the population"
            note={`The dashed line is the cost-optimal cut at the ratio above. The coloured bands are what the screen shipped, sized to the ${pct(meta.pdaLimit, 0)} PDA budget instead of the raw cost optimum.`}
          >
            <ScoreBands bins={scoreBins} watch={meta.bands.watch} reject={meta.bands.reject} threshold={policy.threshold} />
          </Figure>
        </div>
      </div>

      <Provenance modelVersion={meta.modelVersion} source={meta.generatedFrom} />
    </>
  );
}
