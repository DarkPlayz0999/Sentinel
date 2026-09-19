"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { ConsoleState } from "@/components/console/shell";
import { ACTION } from "@/components/console/detail";
import { Trajectory } from "@/components/charts/charts";
import { Card, PageHead, ReasonCode, Stamp, num, pct, sigma, unit, verdictText } from "@/components/ui/kit";
import { ConsoleData, Part, lotEnvelope, useConsole } from "@/lib/console";
import { cn } from "@/lib/utils";

/* REPORTS - the record a QA engineer attaches to a test traveller.
 *
 * Laid out to survive a print to A4 (see @media print in globals.css): in a
 * real hi-rel flow this is a signed paper artefact, not a web page. Its
 * sections are numbered because it is a document that gets cited ("see 4").
 * Mirrors src/screening_report.py, which renders the same record as a PDF. */

function Cell({ k, v, tone }: { k: string; v: React.ReactNode; tone?: string }) {
  return (
    <div className="border-b border-r border-hair px-3 py-2">
      <div className="text-xs text-graphite">{k}</div>
      <div className={cn("mt-0.5 text-sm font-semibold", tone)}>{v}</div>
    </div>
  );
}

function Cells({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("grid border-l border-t border-hair", className)}>{children}</div>;
}

function Block({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <section className="break-inside-avoid">
      <h2 className="mb-3 flex items-baseline gap-3 border-b-2 border-ink pb-1.5">
        <span className="text-sm font-bold text-graphite">{n}</span>
        <span className="wide text-base font-extrabold">{title}</span>
      </h2>
      {children}
    </section>
  );
}

const Small = ({ children }: { children: React.ReactNode }) => (
  <p className="mt-2 max-w-prose text-xs text-graphite">{children}</p>
);

function Report({ part, data }: { part: Part; data: ConsoleData }) {
  const { meta } = data;
  const lot = data.lots.find((l) => l.lot === part.l)!;
  const codes = data.reasons[part.s] ?? [];
  const [stamp, setStamp] = useState("");
  useEffect(() => setStamp(new Date().toISOString().replace("T", " ").slice(0, 16) + " UTC"), []);

  return (
    <article className="print-sheet card mx-auto max-w-[980px] p-6 sm:p-10">
      {/* ------------------------------------------------------- masthead */}
      <header className="flex flex-wrap items-start justify-between gap-6 border-b-[3px] border-ink pb-4">
        <div>
          <p className="wide text-sm font-black tracking-[0.04em]">SENTINEL</p>
          <h1 className="wide mt-1 text-2xl font-extrabold">Screening report</h1>
          <p className="mt-1 text-sm text-graphite">Burn-in latent-defect screen, component {part.s}</p>
        </div>
        <div className="text-right">
          <Stamp v={part.v} size="lg" />
          <p className={cn("wide mt-2 text-3xl font-black", verdictText[part.v])}>
            {num(part.r, 1)}<span className="text-base font-semibold text-mute"> / 100 risk</span>
          </p>
        </div>
      </header>

      <Cells className="mt-5 grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
        <Cell k="Component" v={part.s} />
        <Cell k="Lot" v={part.l} />
        <Cell k="Wafer" v={part.w} />
        <Cell k="Die position" v={`X${part.x} Y${part.y}`} />
        <Cell k="Datasheet verdict" v={part.st ? "Breach" : "Pass"} tone={part.st ? "text-reject" : "text-pass"} />
        <Cell k="Reason codes" v={codes.length} />
      </Cells>

      <div className="mt-8 space-y-8">
        <Block n={1} title="Measurements">
          <div className="overflow-x-auto">
            <table className="tbl min-w-[640px]">
              <thead>
                <tr>
                  <th>Parameter</th><th className="n">0 h</th><th className="n">24 h</th><th className="n">96 h</th>
                  <th className="n">168 h</th><th className="n">Lot median 168 h</th><th className="n">Limit</th><th className="n">Margin used</th>
                </tr>
              </thead>
              <tbody>
                {meta.params.map((p, i) => {
                  const v0 = part.m[i][0];
                  const v168 = part.m[i][3];
                  const used = v0 !== null && v168 !== null && p.usl - v0 > 0 ? (v168 - v0) / (p.usl - v0) : NaN;
                  return (
                    <tr key={p.name}>
                      <td className="font-semibold">{p.name} <span className="font-normal text-mute">{unit(p.unit)}</span></td>
                      {[0, 1, 2, 3].map((ri) => (
                        <td key={ri} className={cn("n", ri === 3 && v168 !== null && v168 > p.usl && "font-bold text-reject")}>
                          {num(part.m[i][ri], 3)}
                        </td>
                      ))}
                      <td className="n text-graphite">{num(lot.ref[p.name].median[3], 3)}</td>
                      <td className="n text-graphite">{num(p.usl, 2)}</td>
                      <td className="n">{Number.isFinite(used) ? pct(used, 1) : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <Small>
            Margin used is (V₁₆₈ − V₀) / (limit − V₀): the share of its own headroom the component
            consumed during burn-in. Read at {meta.readPoints.join(", ")} h at {meta.stressTempC} °C.
          </Small>
        </Block>

        <Block n={2} title="Detection evidence">
          <Cells className="grid-cols-2 sm:grid-cols-5">
            {meta.subScores.map((name, i) => (
              <Cell key={name} k={name.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())}
                v={`${num(part.ss[i], 1)} (×${pct(meta.weights[name] ?? 0, 0)})`} />
            ))}
          </Cells>
          <Cells className="mt-3 grid-cols-2 sm:grid-cols-4">
            <Cell k="L1 datasheet limit" v={part.st ? "Breach" : "Pass"} tone={part.st ? "text-reject" : "text-pass"} />
            <Cell k="L2 worst lot deviation" v={sigma(part.l2)} />
            <Cell k="L3 pooled evidence" v={`${num(part.l3, 1)} against ${num(meta.thresholds["R-401"], 1)}`}
              tone={part.l3 > meta.thresholds["R-401"] ? "text-reject" : undefined} />
            <Cell k="Weighted risk score" v={num(part.r, 1)} />
          </Cells>
          <div className="mt-3 overflow-x-auto">
            <table className="tbl min-w-[520px]">
              <thead>
                <tr><th>Parameter</th><th className="n">Drift vs lot</th><th className="n">Curvature</th><th>Reading</th></tr>
              </thead>
              <tbody>
                {meta.params.map((p, i) => (
                  <tr key={p.name}>
                    <td>{p.name}</td>
                    <td className={cn("n font-semibold",
                      (part.dz[i] ?? 0) >= 6 ? "text-reject" : (part.dz[i] ?? 0) >= 3 ? "text-watch" : "text-graphite")}>
                      {sigma(part.dz[i])}
                    </td>
                    <td className="n text-graphite">{part.cz[i] === null ? "—" : `${num(part.cz[i], 2)}×`}</td>
                    <td className="text-graphite">
                      {(part.cz[i] ?? 0) > meta.thresholds["R-501"] ? "Accelerating, not settling" : "Normal settling"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Block>

        <Block n={3} title="Forecast (Module B)">
          <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,300px)]">
            <Trajectory hours={meta.readPoints} values={part.m[0]} envelope={lotEnvelope(data.parts, part.l, 0)}
              usl={meta.params[0].usl} forecast={part.fc?.[0] ?? null} unitName={meta.params[0].unit} h={240} />
            <Cells className="grid-cols-2 self-start">
              {meta.params.map((p, i) => (
                <Cell key={p.name} k={`${p.name} forecast`} v={`${num(part.fc?.[i], 2)} ${unit(p.unit)}`} />
              ))}
              <Cell k="Safety-slope ratio" v={part.wr === null ? "—" : `${num(part.wr, 2)}×`}
                tone={part.wr !== null && part.wr > 1 ? "text-reject" : undefined} />
              <Cell k="Limiting parameter" v={part.wp ?? "—"} />
            </Cells>
          </div>
          <Small>
            The 168 h value is forecast from the 0 h and 24 h reads only and bounded at the 0.90
            quantile; the reject gate applies to the bound, so a part is pulled only when even its
            optimistic case breaches. The chart shows {meta.params[0].name}.
          </Small>
        </Block>

        <Block n={4} title="Reason codes">
          {codes.length === 0 ? (
            <p className="text-sm text-graphite">No reason code fired for this component.</p>
          ) : (
            <ul className="divide-y divide-hair">
              {codes.map((c, i) => (
                <ReasonCode key={`${c.code}-${i}`} r={{ ...c, gate: meta.thresholds[c.code] }} />
              ))}
            </ul>
          )}
        </Block>

        <Block n={5} title="Reference population">
          <Cells className="grid-cols-2 sm:grid-cols-4 lg:grid-cols-7">
            <Cell k="Lot" v={lot.lot} />
            <Cell k="Components" v={lot.parts} />
            <Cell k="Accept" v={lot.accept} tone="text-pass" />
            <Cell k="Watch" v={lot.watch} tone="text-watch" />
            <Cell k="Reject" v={lot.reject} tone="text-reject" />
            <Cell k="Reject share" v={pct(lot.rejectFrac, 2)} />
            <Cell k="PDA gate" v={lot.pdaStatus === "OK" ? "Within" : "Review"} tone={lot.pdaStatus === "OK" ? "text-pass" : "text-reject"} />
          </Cells>
          <div className="mt-3 overflow-x-auto">
            <table className="tbl min-w-[520px]">
              <thead>
                <tr><th>Parameter</th><th className="n">Lot median 0 h</th><th className="n">Lot median 168 h</th><th className="n">Robust σ 168 h, raw units</th><th className="n">Limit</th></tr>
              </thead>
              <tbody>
                {meta.params.map((p) => (
                  <tr key={p.name}>
                    <td>{p.name}</td>
                    <td className="n">{num(lot.ref[p.name].median[0], 3)}</td>
                    <td className="n">{num(lot.ref[p.name].median[3], 3)}</td>
                    <td className="n">{num(lot.ref[p.name].sigma168, 4)}</td>
                    <td className="n text-graphite">{num(p.usl, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Small>
            Location is the median and spread is 1.4826·MAD, within this lot. The spread column is in
            raw units for reference; the screen itself computes current statistics on log(x),
            because leakage currents are lognormal and a raw σ is inflated by the tail that hides
            the outliers.
          </Small>
        </Block>

        <Block n={6} title="Decision policy in force">
          <Cells className="grid-cols-2 sm:grid-cols-4">
            <Cell k="Cost ratio, missed defect to scrapped part" v={`${meta.costRatioDefault} to 1`} />
            <Cell k="PDA gate" v={pct(meta.pdaLimit, 0)} />
            <Cell k="Watch band" v={`from ${num(meta.bands.watch, 1)}`} />
            <Cell k="Reject band" v={`from ${num(meta.bands.reject, 1)}`} />
          </Cells>
          <Small>
            The verdict is a weighted sum of named sub-scores (weights in 2), never a raw model
            output. Band edges are sized to the PDA budget, because a cost-optimal binary threshold
            at 100 to 1 would flag most of every lot and cannot run on a real line.
          </Small>
        </Block>

        <Block n={7} title="Disposition and sign-off">
          <p className="text-base font-medium">{ACTION[part.v]}</p>
          <Small>
            SENTINEL recommends; a reliability engineer dispositions. This record is not valid until
            countersigned. The screen may add rejections to the datasheet verdict, never remove them.
          </Small>

          {/* Title block, as on an engineering drawing: who, when, signed. */}
          <div className="mt-5 grid grid-cols-2 border-2 border-ink sm:grid-cols-[1.4fr_1fr_1fr_1.4fr]">
            {[
              ["Reliability engineer", ""],
              ["Date", ""],
              ["Model", meta.modelVersion],
              ["Generated", stamp || "—"],
            ].map(([k, v], i) => (
              <div key={k} className={cn("min-h-[64px] px-3 py-2", i > 0 && "sm:border-l-2 sm:border-ink", i % 2 && "max-sm:border-l-2 max-sm:border-ink", i > 1 && "max-sm:border-t-2 max-sm:border-ink")}>
                <div className="text-xs text-graphite">{k}</div>
                <div className="mt-1 text-sm font-semibold">{v}</div>
              </div>
            ))}
            <div className="col-span-2 min-h-[72px] border-t-2 border-ink px-3 py-2 sm:col-span-4">
              <div className="text-xs text-graphite">Signature</div>
            </div>
          </div>
        </Block>
      </div>

      <footer className="mt-8 border-t border-rule pt-3 text-xs text-mute">
        <strong className="font-semibold text-graphite">Simulated data.</strong> Generated by
        src/generate_burnin_dataset.py at seed 42 and screened by src/pipeline.py ({meta.modelVersion})
        from {meta.generatedFrom}. Ground truth is used only to measure recall and is never an input
        to a verdict.
      </footer>
    </article>
  );
}

function Inner() {
  const { data, error } = useConsole();
  const params = useSearchParams();
  const router = useRouter();
  const id = params.get("id");

  // The 60 highest-risk parts, plus the open one if it is not among them -
  // otherwise the picker would claim nothing is selected.
  const candidates = useMemo(() => {
    if (!data) return [];
    const top = [...data.parts].sort((a, b) => b.r - a.r).slice(0, 60);
    const cur = id ? data.parts.find((p) => p.s === id) : undefined;
    return cur && !top.includes(cur) ? [cur, ...top] : top;
  }, [data, id]);

  if (!data) return <ConsoleState error={error} />;
  const part = id ? data.parts.find((p) => p.s === id) : undefined;

  return (
    <>
      <div className="no-print">
        <PageHead
          title="Screening report"
          lede="The record a QA engineer signs and attaches to the test traveller. Print it or save it as a PDF."
        />
        <Card className="mb-6 flex flex-wrap items-end gap-3 px-4 py-3">
          <label className="min-w-[240px] flex-1">
            <span className="mb-1 block text-xs text-graphite">Component (60 highest-risk)</span>
            <select value={id ?? ""} onChange={(e) => router.push(`/console/reports?id=${e.target.value}`)} className="input w-full">
              <option value="">Choose a component</option>
              {candidates.map((p) => (
                <option key={p.s} value={p.s}>
                  {p.s}: {p.v.toLowerCase()}, risk {num(p.r, 1)}
                </option>
              ))}
            </select>
          </label>
          {part && <button onClick={() => window.print()} className="btn-primary">Print or save PDF</button>}
        </Card>
      </div>

      {part ? (
        <Report part={part} data={data} />
      ) : id ? (
        <Card className="p-8 text-center">
          <p>No component with serial <strong>{id}</strong> in this screening run.</p>
          <Link href="/console/components" className="link mt-2 inline-block">Find it in Components</Link>
        </Card>
      ) : (
        <Card className="p-10 text-center">
          <p className="text-base font-semibold">Choose a component to render its screening record.</p>
          <p className="mt-2 text-sm text-graphite">
            Or open any component from <Link href="/console/components" className="link">Components</Link>.
            The same one-page PDF is produced offline by <code>python -m src.screening_report</code>.
          </p>
        </Card>
      )}
    </>
  );
}

export default function ReportsPage() {
  return (
    <Suspense fallback={<ConsoleState />}>
      <Inner />
    </Suspense>
  );
}
