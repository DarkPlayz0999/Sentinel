"use client";

import Link from "next/link";
import { useState } from "react";
import { LotDistribution, RiskComposition, Trajectory } from "@/components/charts/charts";
import {
  ChartNote, Field, Panel, PanelHead, SeverityTag, VerdictChip,
  num, pct, sigma, unit,
} from "@/components/ui/kit";
import {
  ConsoleData, Part, histogram, lotEnvelope, measurement, partsInLot,
  quantile, robustSigma,
} from "@/lib/console";
import { cn } from "@/lib/utils";

/* COMPONENT DETAIL — the screen that answers "why is this component
 * abnormal, and where is it heading?"
 *
 * Order is the order a reliability engineer reads a record in: what is it,
 * what did it measure, how did it move against its lot, what evidence the
 * screen found, what the codes say, what to do. */

function Row({ k, v, tone }: { k: string; v: React.ReactNode; tone?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-lab-hair py-1.5">
      <span className="font-mono text-[10px] text-lab-dim">{k}</span>
      <span className={cn("readout text-[11px] font-semibold", tone ?? "text-lab-ink")}>{v}</span>
    </div>
  );
}

export function PartDetail({ part, data }: { part: Part; data: ConsoleData }) {
  const { meta, reasons } = data;
  const [pi, setPi] = useState(0);
  const pm = meta.params[pi];
  const lot = data.lots.find((l) => l.lot === part.l);
  const codes = reasons[part.s] ?? [];
  const env = lotEnvelope(data.parts, part.l, pi);

  // Lot population at 168 h for the selected parameter - the reference the
  // verdict is actually made against, drawn as the population it came from.
  const lotRows = partsInLot(data.parts, part.l);
  const at168 = lotRows
    .map((p) => measurement(p, pi, 3))
    .filter((v): v is number => v !== null);
  const defects168 = lotRows
    .filter((p) => p.y1 === 1)
    .map((p) => measurement(p, pi, 3))
    .filter((v): v is number => v !== null);

  const med = lot?.ref[pm.name]?.median[3] ?? 0;
  const sig = lot?.ref[pm.name]?.sigma168 ?? robustSigma(at168);
  const hi = Math.max(quantile(at168, 0.995), part.m[pi][3] ?? 0) * 1.08;
  const lo = Math.min(quantile(at168, 0.002), part.m[pi][3] ?? 0) * 0.9;

  const value168 = part.m[pi][3];
  const staticVerdict = value168 !== null && value168 > pm.usl ? "BREACH" : "PASS";
  const disagrees = staticVerdict === "PASS" && part.v === "REJECT";

  const action =
    part.v === "REJECT"
      ? "Hold component for engineering review. Remove from the lot before final electrical test."
      : part.v === "WATCH"
        ? "Ship with the serial flagged. Record the disposition and re-inspect at next screen."
        : "No action. Component is within its lot's normal behaviour.";

  return (
    <div className="space-y-6">
      {/* ------------------------------------------------------- header */}
      <div className="panel">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-3 border-b border-lab-hair px-4 py-3">
          <Link
            href="/console/components"
            className="font-mono text-[9px] uppercase tracking-label text-sig-blue hover:underline"
          >
            ← Components
          </Link>
          <div>
            <div className="label">Component</div>
            <div className="readout text-[19px] font-bold leading-none text-lab-ink">{part.s}</div>
          </div>
          <VerdictChip v={part.v} size="lg" />
          <div className="ml-auto flex items-baseline gap-2">
            <span className="label">Screening risk</span>
            <span
              className={cn(
                "readout text-[26px] font-bold leading-none",
                part.v === "REJECT" ? "text-sig-red" : part.v === "WATCH" ? "text-sig-amber" : "text-sig-green"
              )}
            >
              {num(part.r, 1)}
            </span>
            <span className="font-mono text-[10px] text-lab-faint">/ 100</span>
          </div>
        </div>

        {disagrees && (
          <div className="border-b border-sig-red/25 bg-sig-red/[0.05] px-4 py-2.5">
            <p className="font-mono text-[10px] leading-relaxed text-lab-ink">
              <span className="font-bold text-sig-red">ESCAPE PREVENTED.</span> This component
              passes every static datasheet limit at 168 h and would have shipped under
              traditional screening. It is flagged because it is abnormal{" "}
              <em>relative to its own lot</em>, not relative to the datasheet.
            </p>
          </div>
        )}

        <div className="grid grid-cols-2 gap-px bg-lab-hair sm:grid-cols-4 lg:grid-cols-7">
          {[
            { k: "Serial", v: part.s },
            { k: "Lot", v: part.l },
            { k: "Wafer", v: part.w },
            { k: "Die position", v: `X${part.x} · Y${part.y}` },
            { k: "Static verdict", v: staticVerdict, tone: staticVerdict === "PASS" ? "text-sig-green" : "text-sig-red" },
            { k: "Dynamic σ (L2)", v: sigma(part.l2), tone: "text-lab-ink" },
            { k: "Pooled evidence (L3)", v: num(part.l3, 1) },
          ].map((f) => (
            <div key={f.k} className="bg-lab-card px-3 py-2">
              <Field k={f.k} v={f.v} tone={f.tone} />
            </div>
          ))}
        </div>
      </div>

      {/* -------------------------------------------------- measurements */}
      <Panel className="overflow-x-auto">
        <PanelHead
          title="Burn-in measurements"
          meta="four parameters · four read points at 125 °C · lot median for reference"
          right={
            <span className="font-mono text-[9px] text-lab-faint">
              — indicates a dropped handler read
            </span>
          }
        />
        <table className="w-full min-w-[720px] border-collapse">
          <thead>
            <tr className="border-b border-lab-rule bg-lab-panel">
              {["Parameter", "0 h", "24 h", "96 h", "168 h", "Lot median 168 h", "USL", "Drift σ", "Curvature"].map(
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
            {meta.params.map((p, i) => {
              const v168 = part.m[i][3];
              const breach = v168 !== null && v168 > p.usl;
              const dz = part.dz[i];
              return (
                <tr
                  key={p.name}
                  className={cn(
                    "cursor-pointer border-b border-lab-hair hover:bg-lab-panel",
                    i === pi && "bg-sig-blue/[0.05]"
                  )}
                  onClick={() => setPi(i)}
                >
                  <td className="px-3 py-1.5">
                    <span className="readout text-[11px] font-semibold text-lab-ink">{p.name}</span>
                    <span className="ml-2 font-mono text-[9px] text-lab-faint">{p.label}</span>
                  </td>
                  {[0, 1, 2, 3].map((ri) => (
                    <td
                      key={ri}
                      className={cn(
                        "readout px-3 py-1.5 text-[11px]",
                        ri === 3 && breach && "font-bold text-sig-red"
                      )}
                    >
                      {num(part.m[i][ri], 2)}
                    </td>
                  ))}
                  <td className="readout px-3 py-1.5 text-[11px] text-lab-dim">
                    {num(lot?.ref[p.name]?.median[3], 2)}
                  </td>
                  <td className="readout px-3 py-1.5 text-[11px] text-lab-faint">
                    {num(p.usl, 2)} {unit(p.unit)}
                  </td>
                  <td
                    className={cn(
                      "readout px-3 py-1.5 text-[11px] font-semibold",
                      dz !== null && dz >= 6 ? "text-sig-red" : dz !== null && dz >= 3 ? "text-sig-amber" : "text-lab-dim"
                    )}
                  >
                    {sigma(dz)}
                  </td>
                  <td className="readout px-3 py-1.5 text-[11px] text-lab-dim">
                    {part.cz[i] === null ? "—" : `${num(part.cz[i], 2)}×`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="border-t border-lab-hair px-3 py-2 font-mono text-[9px] text-lab-faint">
          Select a row to re-plot the charts below. Drift σ is the total 0→168 h movement
          expressed in robust standard deviations <em>of this lot</em>; curvature above 1.0 means
          the late window is drifting faster than the early one — accelerating, not settling.
        </p>
      </Panel>

      {/* ----------------------------------------------------- the charts */}
      <div className="grid gap-px bg-lab-rule xl:grid-cols-2">
        <Panel className="border-0 p-4">
          <PanelHead
            title={`Burn-in trajectory — ${pm.name}`}
            meta="measured solid · forecast dashed"
            className="-mx-4 -mt-4 mb-3 px-4"
          />
          <Trajectory
            hours={meta.readPoints}
            values={part.m[pi]}
            envelope={env}
            usl={pm.usl}
            forecast={part.fc?.[pi] ?? null}
            unitName={pm.name}
            serial={part.s}
          />
          <ChartNote>
            Blue band is the lot&rsquo;s 5th–95th percentile at each read point; the dashed blue
            line is the lot median. The amber dashed segment is Module B&rsquo;s forecast of the
            168 h value from the <strong>0 h and 24 h reads alone</strong> — it never sees the
            96 h or 168 h measurement.
          </ChartNote>
        </Panel>

        <Panel className="border-0 p-4">
          <PanelHead
            title={`Lot population at 168 h — ${pm.name}`}
            meta={`lot ${part.l} · n=${lotRows.length}`}
            className="-mx-4 -mt-4 mb-3 px-4"
          />
          <LotDistribution
            bins={histogram(at168, lo, hi, 46)}
            defectBins={histogram(defects168, lo, hi, 46)}
            lo={lo}
            hi={hi}
            unitName={pm.name}
            usl={pm.usl}
            med={med}
            sig={sig}
            marker={value168 ?? undefined}
            markerLabel={`${num(value168, 1)} ${unit(pm.unit)}`}
          />
          <ChartNote>
            Lot median {num(med, 2)} {unit(pm.unit)}, robust σ {num(sig, 2)}. Red bars are
            components this simulated dataset labels as latent defects — shown so the separation
            can be checked against a known answer, never used to produce a verdict.
          </ChartNote>
        </Panel>
      </div>

      {/* ------------------------------------------------- risk evidence */}
      <div className="grid gap-px bg-lab-rule lg:grid-cols-[minmax(0,1fr)_minmax(0,420px)]">
        <Panel className="border-0 p-4">
          <PanelHead
            title="Detection evidence"
            meta="what produced the risk score"
            className="-mx-4 -mt-4 mb-3 px-4"
          />
          <RiskComposition
            subScores={meta.subScores}
            values={part.ss}
            weights={meta.weights}
            total={part.r}
          />
          <ChartNote>
            The verdict is a weighted sum of named sub-scores, never a raw model output. Each
            term is inspectable and its weight is fixed policy, so an engineer can decompose the
            number rather than trust it.
          </ChartNote>
        </Panel>

        <Panel className="border-0 p-4">
          <PanelHead title="Evidence register" className="-mx-4 -mt-4 mb-2 px-4" />
          <Row
            k="L1 · static datasheet limit"
            v={staticVerdict}
            tone={staticVerdict === "PASS" ? "text-sig-green" : "text-sig-red"}
          />
          <Row k="L2 · worst-case lot deviation" v={sigma(part.l2)} />
          <Row
            k="L3 · pooled drift evidence"
            v={`${num(part.l3, 1)} / ${num(meta.thresholds["R-401"], 1)}`}
            tone={part.l3 > meta.thresholds["R-401"] ? "text-sig-red" : undefined}
          />
          <Row
            k="Module B · safety-slope ratio"
            v={part.wr === null ? "—" : `${num(part.wr, 2)}×`}
            tone={part.wr !== null && part.wr > 1 ? "text-sig-red" : undefined}
          />
          <Row k="Module B · limiting parameter" v={part.wp ?? "—"} />
          <Row
            k="Forecast 168 h · selected param"
            v={part.fc ? `${num(part.fc[pi], 2)} ${unit(pm.unit)}` : "—"}
          />
          <Row
            k="Measured 168 h · selected param"
            v={`${num(value168, 2)} ${unit(pm.unit)}`}
          />
          <Row k="Lot PDA status" v={lot?.pdaStatus ?? "—"}
            tone={lot?.pdaStatus === "OK" ? "text-sig-green" : "text-sig-red"} />
          <p className="mt-3 font-mono text-[9px] leading-relaxed text-lab-faint">
            The forecast row is shown next to the measured value so the forecast can be checked.
            In production at hour 24 only the forecast exists — that is the point of Module B.
          </p>
        </Panel>
      </div>

      {/* ------------------------------------------------- reason codes */}
      <Panel>
        <PanelHead
          title={part.v === "ACCEPT" ? "Reason codes" : `Why was this component ${part.v.toLowerCase()}ed?`}
          meta={`${codes.length} code(s) · thresholds from src/explain.py`}
        />
        {codes.length === 0 ? (
          <p className="px-4 py-4 font-mono text-[10px] leading-relaxed text-lab-dim">
            No reason code fired. Every rule threshold in <code>src/explain.py</code> is above
            this component&rsquo;s values, so the screen has nothing specific to report about it.
          </p>
        ) : (
          <ul className="divide-y divide-lab-hair">
            {codes.map((c, i) => (
              <li key={`${c.code}-${i}`} className="px-4 py-3">
                <div className="flex flex-wrap items-center gap-2.5">
                  <span className="readout border border-lab-ink bg-lab-ink px-1.5 py-[2px] text-[10px] font-bold text-lab-panel">
                    {c.code}
                  </span>
                  <SeverityTag s={c.severity} />
                  <span className="font-mono text-[9px] text-lab-faint">
                    gate: {c.feature} · trigger {num(meta.thresholds[c.code], 2)}
                  </span>
                </div>
                <p className="mt-2 text-[12px] leading-relaxed text-lab-ink">{c.message}</p>
                <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1">
                  <Field k="Observed" v={num(c.value, 3)} />
                  <Field k="Lot reference" v={num(c.ref, 3)} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      {/* ----------------------------------------------- recommended action */}
      <div
        className={cn(
          "panel border-l-[3px] px-4 py-3",
          part.v === "REJECT" ? "border-l-sig-red" : part.v === "WATCH" ? "border-l-sig-amber" : "border-l-sig-green"
        )}
      >
        <div className="label">Recommended action</div>
        <p className="mt-1.5 text-[13px] font-medium text-lab-ink">{action}</p>
        <p className="mt-2 font-mono text-[9px] leading-relaxed text-lab-faint">
          SENTINEL recommends; a reliability engineer dispositions. In a flight-lot context every
          REJECT and every lot-level PDA breach requires human approval before the part leaves
          the line — the screen may add rejections to the datasheet, never remove them.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <Link
            href={`/console/reports?id=${part.s}`}
            className="border border-lab-ink bg-lab-ink px-3 py-1.5 font-mono text-[10px] uppercase tracking-label text-lab-panel transition-opacity hover:opacity-85"
          >
            Open screening report
          </Link>
          <Link
            href={`/console/lots?lot=${part.l}`}
            className="border border-lab-rule bg-lab-card px-3 py-1.5 font-mono text-[10px] uppercase tracking-label text-lab-ink transition-colors hover:bg-lab-panel"
          >
            Lot {part.l} health
          </Link>
        </div>
      </div>
    </div>
  );
}
