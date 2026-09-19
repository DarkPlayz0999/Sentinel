"use client";

import Link from "next/link";
import { useState } from "react";
import { LotDistribution, RiskComposition, Trajectory } from "@/components/charts/charts";
import {
  Card, CardHead, Field, Figure, Notice, ReasonCode, Row, Stamp, num, sigma, unit, verdictText,
} from "@/components/ui/kit";
import {
  ConsoleData, Part, histogram, lotBands, lotEnvelope, measurement, partsInLot, quantile,
} from "@/lib/console";
import { cn } from "@/lib/utils";

/* COMPONENT DETAIL - "why is this component abnormal, and where is it
 * heading?" Ordered the way a reliability engineer reads a record: what it
 * is, what it measured, how it moved against its lot, what evidence the
 * screen found, what the codes say, what to do. */

export const ACTION = {
  REJECT: "Hold the component for engineering review and remove it from the lot before final electrical test.",
  WATCH: "Ship with the serial flagged. Record the disposition and re-inspect at the next screen.",
  ACCEPT: "No action. The component is within its lot's normal behaviour.",
} as const;

export function PartDetail({ part, data }: { part: Part; data: ConsoleData }) {
  const { meta, reasons } = data;
  const [pi, setPi] = useState(0);
  const pm = meta.params[pi];
  const lot = data.lots.find((l) => l.lot === part.l);
  const codes = reasons[part.s] ?? [];
  const env = lotEnvelope(data.parts, part.l, pi);

  // The lot at 168 h for the selected parameter: the population the verdict
  // is made against, drawn as the population it came from.
  const lotRows = partsInLot(data.parts, part.l);
  const at168 = lotRows.map((p) => measurement(p, pi, 3)).filter((v): v is number => v !== null);
  const defects168 = lotRows.filter((p) => p.y1 === 1)
    .map((p) => measurement(p, pi, 3)).filter((v): v is number => v !== null);
  const ref = lotBands(at168, pm.isCurrent);

  const value168 = part.m[pi][3];
  const hi = Math.max(quantile(at168, 0.995), value168 ?? 0) * 1.08;
  const lo = Math.min(quantile(at168, 0.002), value168 ?? Infinity) * 0.9;
  const staticPass = !(value168 !== null && value168 > pm.usl);
  const escape = part.st === 0 && part.v === "REJECT";

  return (
    <div className="space-y-4">
      <Link href="/console/components" className="text-sm text-graphite hover:text-ink">
        Back to all components
      </Link>

      {/* ------------------------------------------------------- header */}
      <Card>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3 px-5 py-4">
          <div>
            <h1 className="wide text-3xl font-extrabold">{part.s}</h1>
            <p className="mt-1 text-sm text-graphite">
              Lot {part.l}, wafer {part.w}, die X{part.x} Y{part.y}
            </p>
          </div>
          <Stamp v={part.v} size="lg" />
          <div className="ml-auto text-right">
            <div className="text-sm text-graphite">Screening risk</div>
            <div className={cn("wide text-4xl font-black leading-none", verdictText[part.v])}>
              {num(part.r, 1)}
              <span className="ml-1 text-base font-semibold text-mute">/ 100</span>
            </div>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4 border-t border-hair px-5 py-3 sm:grid-cols-4">
          <Field k="Datasheet verdict at 168 h" v={part.st ? "Breach" : "Pass"} tone={part.st ? "text-reject" : "text-pass"} />
          <Field k="Worst lot deviation (L2)" v={sigma(part.l2)} />
          <Field k="Pooled drift evidence (L3)" v={num(part.l3, 1)} />
          <Field k="Lot PDA gate" v={lot?.pdaStatus === "OK" ? "Within" : "Review"} tone={lot?.pdaStatus === "OK" ? "text-pass" : "text-reject"} />
        </div>
      </Card>

      {escape && (
        <Notice tone="danger" title="An escape, prevented">
          This component passes every datasheet limit at 168 h and would have shipped under
          traditional screening. It is rejected because it is abnormal <em>relative to its own
          lot</em>.
        </Notice>
      )}

      {/* -------------------------------------------------- measurements */}
      <Card className="overflow-x-auto">
        <CardHead title="Burn-in measurements" meta="Select a parameter to re-plot the charts." />
        <table className="tbl min-w-[760px]">
          <thead>
            <tr>
              <th>Parameter</th>
              <th className="n">0 h</th><th className="n">24 h</th><th className="n">96 h</th><th className="n">168 h</th>
              <th className="n">Lot median 168 h</th><th className="n">Limit</th>
              <th className="n">Drift vs lot</th><th className="n">Curvature</th>
            </tr>
          </thead>
          <tbody>
            {meta.params.map((p, i) => {
              const v168 = part.m[i][3];
              const breach = v168 !== null && v168 > p.usl;
              const dz = part.dz[i];
              return (
                <tr
                  key={p.name}
                  onClick={() => setPi(i)}
                  className={cn("cursor-pointer", i === pi && "!bg-cobalt/[0.07]")}
                >
                  <td>
                    <button onClick={() => setPi(i)} aria-pressed={i === pi} className="text-left">
                      <span className="font-semibold">{p.name}</span>
                      <span className="ml-2 text-xs text-graphite">{p.label}</span>
                    </button>
                  </td>
                  {[0, 1, 2, 3].map((ri) => (
                    <td key={ri} className={cn("n", ri === 3 && breach && "font-bold text-reject")}>
                      {num(part.m[i][ri], 2)}
                    </td>
                  ))}
                  <td className="n text-graphite">{num(lot?.ref[p.name]?.median[3], 2)}</td>
                  <td className="n text-graphite">{num(p.usl, 2)} {unit(p.unit)}</td>
                  <td className={cn("n font-semibold",
                    dz !== null && dz >= 6 ? "text-reject" : dz !== null && dz >= 3 ? "text-watch" : "text-graphite")}>
                    {sigma(dz)}
                  </td>
                  <td className="n text-graphite">{part.cz[i] === null ? "—" : `${num(part.cz[i], 2)}×`}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="border-t border-hair px-4 py-3 text-sm text-graphite">
          Drift vs lot is the total 0 to 168 h movement in robust standard deviations of this lot.
          A dash is a dropped handler read. Curvature above 1.0 means the late window drifts faster
          than the early one: accelerating, not settling.
        </p>
      </Card>

      {/* ----------------------------------------------------- the charts */}
      <div className="grid gap-4 xl:grid-cols-2">
        <Figure
          title={`${pm.name} through burn-in`}
          meta="against the lot's 5th to 95th percentile"
          note={<>The amber dashed line is Module B&rsquo;s forecast of the 168 h value from the 0 h and 24 h reads alone. It never sees the 96 h or 168 h measurement.</>}
        >
          <Trajectory hours={meta.readPoints} values={part.m[pi]} envelope={env}
            usl={pm.usl} forecast={part.fc?.[pi] ?? null} unitName={pm.unit} />
        </Figure>

        <Figure
          title={`Lot ${part.l} at 168 h`}
          meta={`${pm.name}, ${at168.length} parts`}
          note={<>Red bars are parts this simulated dataset labels as latent defects, shown so the separation can be checked against a known answer. {pm.isCurrent ? "Bands are computed on log values, because currents are lognormal." : ""}</>}
        >
          <LotDistribution
            bins={histogram(at168, lo, hi, 46)} defectBins={histogram(defects168, lo, hi, 46)}
            lo={lo} hi={hi} param={pm.name} unitName={pm.unit} usl={pm.usl}
            med={ref.median} bands={ref.bands}
            marker={value168 ?? undefined} markerLabel={`This part: ${num(value168, 1)} ${unit(pm.unit)}`}
          />
        </Figure>
      </div>

      {/* ------------------------------------------------- risk evidence */}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <Figure
          title="What produced the risk score"
          note="The verdict is a weighted sum of named sub-scores, never a raw model output. Each weight is fixed policy, so an engineer can decompose the number instead of trusting it."
        >
          <RiskComposition subScores={meta.subScores} values={part.ss} weights={meta.weights} total={part.r} />
        </Figure>

        <Card>
          <CardHead title="Evidence register" />
          <div className="px-4 py-1">
            <Row k="L1 datasheet limit" v={staticPass ? "Pass" : "Breach"} tone={staticPass ? "text-pass" : "text-reject"} />
            <Row k="L2 worst lot deviation" v={sigma(part.l2)} />
            <Row k="L3 pooled drift evidence"
              v={`${num(part.l3, 1)} against ${num(meta.thresholds["R-401"], 1)}`}
              tone={part.l3 > meta.thresholds["R-401"] ? "text-reject" : undefined} />
            <Row k="Module B safety-slope ratio"
              v={part.wr === null ? "—" : `${num(part.wr, 2)}×`}
              tone={part.wr !== null && part.wr > 1 ? "text-reject" : undefined} />
            <Row k="Module B limiting parameter" v={part.wp ?? "—"} />
            <Row k={`Forecast 168 h, ${pm.name}`} v={part.fc ? `${num(part.fc[pi], 2)} ${unit(pm.unit)}` : "—"} tone="text-watch" />
            <Row k={`Measured 168 h, ${pm.name}`} v={`${num(value168, 2)} ${unit(pm.unit)}`} />
          </div>
          <p className="border-t border-hair px-4 py-3 text-xs text-graphite">
            The measured value sits next to the forecast so the forecast can be checked. In
            production at hour 24, only the forecast exists.
          </p>
        </Card>
      </div>

      {/* ------------------------------------------------- reason codes */}
      <Card>
        <CardHead
          title={part.v === "ACCEPT" ? "Reason codes" : `Why this component is ${part.v === "REJECT" ? "rejected" : "on watch"}`}
          meta={`${codes.length} code${codes.length === 1 ? "" : "s"} fired`}
        />
        {codes.length === 0 ? (
          <p className="px-4 py-4 text-sm text-graphite">
            No reason code fired. Every rule threshold in <code>src/explain.py</code> is above this
            component&rsquo;s values.
          </p>
        ) : (
          <ul className="divide-y divide-hair px-4">
            {codes.map((c, i) => (
              <ReasonCode key={`${c.code}-${i}`}
                r={{ ...c, gate: meta.thresholds[c.code] }} />
            ))}
          </ul>
        )}
      </Card>

      {/* ----------------------------------------------- recommended action */}
      <Notice tone={part.v === "REJECT" ? "danger" : part.v === "WATCH" ? "warn" : "pass"} title="Recommended action">
        <p className="text-base font-medium">{ACTION[part.v]}</p>
        <p className="mt-2 text-sm text-graphite">
          SENTINEL recommends; a reliability engineer dispositions. Every reject and every lot over
          the PDA gate needs human approval before the part leaves the line. The screen may add
          rejections to the datasheet verdict, never remove them.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <Link href={`/console/reports?id=${part.s}`} className="btn-primary">Open screening report</Link>
          <Link href={`/console/lots?lot=${part.l}`} className="btn-quiet">View lot {part.l}</Link>
        </div>
      </Notice>
    </div>
  );
}
