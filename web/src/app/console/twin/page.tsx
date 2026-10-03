"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ConsoleState } from "@/components/console/shell";
import {
  Card, CardHead, Notice, PageHead, Provenance, ReasonCode, Risk, Row, Stamp,
  num, unit,
} from "@/components/ui/kit";
import { paramIndex, partsInLot, useConsole } from "@/lib/console";
import { STATE_LABEL, lotStateAt, seatLot } from "@/lib/twin";
import { C } from "@/lib/theme";
import { cn } from "@/lib/utils";

/* THE OVEN IN THREE DIMENSIONS - the screen that explains the problem without
 * a sentence of statistics.
 *
 * A tray of 350 parts from one lot soaks at 125 C. Each column is a live
 * measurement, scaled so the red ceiling is the datasheet limit. The blue slab
 * is the batch itself. Scrub the week and one part climbs out of its batch
 * while never once touching the ceiling. It passes every test it will ever be
 * given, and it is already the odd one out.
 *
 * Every number on this screen comes from the committed screening record. The
 * risk score and verdict are src/pipeline.py output, passed through untouched.
 * The live deviation shown during the scrub is a lot percentile and a robust
 * z recomputed in the browser from the same measurements - the construction is
 * documented in lib/twin.ts and it decides nothing. */

// WebGL cannot be server-rendered, and the console is a static export.
const TrayScene = dynamic(() => import("@/components/twin/scene").then((m) => m.TrayScene), {
  ssr: false,
  loading: () => (
    <div className="grid h-full place-items-center bg-[#0B2D2A] text-sm text-[#8FA8A2]">
      Loading the oven…
    </div>
  ),
});

const SWEEP_MS = 11000; // one pass through the soak
const READ_POINTS = [0, 24, 96, 168];

export default function TwinPage() {
  const { data, error } = useConsole();
  const [lotId, setLotId] = useState("L04");
  const [pi, setPi] = useState(0);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const [showCeiling, setShowCeiling] = useState(true);
  const [showBatch, setShowBatch] = useState(true);
  const raf = useRef<number>();

  const parts = useMemo(
    () => (data ? partsInLot(data.parts, lotId) : []),
    [data, lotId],
  );
  const sockets = useMemo(() => seatLot(parts), [parts]);

  const isCurrent = data?.meta.params[pi]?.isCurrent ?? true;
  const hours = data?.meta.readPoints ?? READ_POINTS;

  const lot = useMemo(
    () => lotStateAt(sockets, pi, t, hours, isCurrent),
    [sockets, pi, t, hours, isCurrent],
  );

  // Playback. One sweep of the soak, then stop at 168 h.
  useEffect(() => {
    if (!playing) return;
    const from = t >= 168 ? 0 : t;
    const t0 = performance.now();
    const tick = (now: number) => {
      const p = from + ((now - t0) / SWEEP_MS) * 168;
      if (p >= 168) {
        setT(168);
        setPlaying(false);
        return;
      }
      setT(p);
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      if (raf.current) cancelAnimationFrame(raf.current);
    };
    // `t` is the starting point captured once; re-running on every frame would
    // restart the sweep.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing]);

  const pick = useCallback((i: number) => setSelected(i < 0 ? null : i), []);

  /**
   * Jump to the chip that matters: the highest pipeline risk among chips that
   * NEVER breach the datasheet.
   *
   * Filtering on the datasheet result rather than on risk alone is the point.
   * The riskiest chip in a lot is usually a gross failure that any static test
   * already catches, which demonstrates nothing. The target class is the one
   * that passes every limit and is still wrong, and whether a chip passed is
   * an observable, not ground truth - `Part.tc` is never consulted here.
   *
   * The view also switches to the measurement that carried the flag, so the
   * tray is showing the parameter the reason codes are talking about.
   */
  const findSuspect = useCallback(() => {
    let best = -1;
    let bestRisk = -1;
    sockets.forEach((s, i) => {
      if (s.part.st === 0 && s.part.r > bestRisk) {
        bestRisk = s.part.r;
        best = i;
      }
    });
    if (best < 0) return;
    const carrier = sockets[best].part.wp;
    if (carrier && data) {
      const ci = paramIndex(data.meta, carrier);
      if (ci >= 0) setPi(ci);
    }
    setSelected(best);
    setPlaying(false);
    setT(168);
  }, [sockets, data]);

  if (!data) return <ConsoleState error={error} />;

  const { meta } = data;
  const pm = meta.params[pi];
  const sel = selected != null && selected >= 0 ? sockets[selected] : null;
  const selValue = selected != null && selected >= 0 ? lot.values[selected] : null;
  const selZ = selected != null && selected >= 0 ? lot.z[selected] : 0;
  const selState = selected != null && selected >= 0 ? lot.state[selected] : "nominal";
  const reasons = sel ? data.reasons[sel.part.s] ?? [] : [];
  const breached = selValue != null && selValue >= pm.usl;

  return (
    <>
      <PageHead
        title="The oven, in three dimensions"
        lede={
          <>
            One tray, {parts.length} chips, one batch, {meta.stressTempC} °C. Each column is a
            measured value. The red sheet is the datasheet limit and the blue slab is the batch
            itself. Press play and watch one chip leave its batch without ever touching the limit.
          </>
        }
        right={
          <button
            type="button"
            onClick={findSuspect}
            className="rounded-ctl bg-ink px-4 py-2.5 text-sm font-bold text-sheet hover:opacity-90"
          >
            Show me the hidden one
          </button>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_355px]">
        <div className="min-w-0">
          {/* ------------------------------------------------ the oven */}
          <div className="overflow-hidden rounded-card border border-rule bg-[#0B2D2A]">
            <div className="h-[clamp(360px,58vh,620px)] w-full">
              <TrayScene
                sockets={sockets}
                lot={lot}
                usl={pm.usl}
                selected={selected}
                onPick={pick}
                showCeiling={showCeiling}
                showBatch={showBatch}
                // Timing limits are sub-10 and must not round: the propagation
                // delay limit is 4.6 ns, and "5 ns" on screen is simply wrong.
                uslLabel={`${num(pm.usl, pm.usl < 10 ? 1 : 0)} ${unit(pm.unit)}`}
              />
            </div>

            {/* --------------------------------------------- scrubber */}
            <div className="border-t border-white/10 px-4 py-3.5">
              <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
                <button
                  type="button"
                  onClick={() => setPlaying((p) => !p)}
                  className="rounded-ctl bg-[#9C4F1F] px-4 py-2 text-sm font-bold text-white hover:opacity-90"
                  aria-label={playing ? "Pause the soak" : "Play the soak"}
                >
                  {playing ? "Pause" : t >= 168 ? "Replay" : "Play the week"}
                </button>

                <div className="min-w-[210px] flex-1">
                  <input
                    type="range"
                    min={0}
                    max={168}
                    step={0.5}
                    value={t}
                    onChange={(e) => {
                      setPlaying(false);
                      setT(Number(e.target.value));
                    }}
                    className="w-full accent-[#F2A365]"
                    aria-label="Hours into the burn-in soak"
                  />
                  <div className="mt-1 flex justify-between text-[11px] text-[#8FA8A2]">
                    {hours.map((h) => (
                      <button
                        key={h}
                        type="button"
                        onClick={() => {
                          setPlaying(false);
                          setT(h);
                        }}
                        className="hover:text-[#F7C49A]"
                      >
                        {h} h
                      </button>
                    ))}
                  </div>
                </div>

                <div className="wide tabular-nums text-lg font-black text-[#F2A365]">
                  {t.toFixed(0)} h
                </div>
              </div>

              {/* legend: colour is repeated as words, never used alone */}
              <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-[11px] text-[#B9CFCA]">
                <Key color="#8EBBDD" label="inside the batch" />
                <Key color="#F2A365" label="leaving the batch (3σ)" />
                <Key color="#FF7A6B" label="far outside (6σ)" />
                <Key color={C.reject} label="red sheet: datasheet limit" />
                <Key color={C.cobalt} label="blue slab: batch 5th–95th" />
                <label className="ml-auto flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={showCeiling}
                    onChange={(e) => setShowCeiling(e.target.checked)}
                  />
                  limit
                </label>
                <label className="flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={showBatch}
                    onChange={(e) => setShowBatch(e.target.checked)}
                  />
                  batch
                </label>
              </div>
            </div>
          </div>

          {/* ------------------------------------------- what to look at */}
          <div className="mt-4 grid gap-4 sm:grid-cols-3">
            <Readout k={`Batch middle at ${t.toFixed(0)} h`} v={`${num(lot.median, 2)} ${unit(pm.unit)}`} />
            <Readout k="Datasheet limit" v={`${num(pm.usl, 1)} ${unit(pm.unit)}`} tone="text-reject" />
            <Readout
              k="Chips above the limit"
              v={`${lot.values.filter((v) => v != null && v >= pm.usl).length} of ${parts.length}`}
            />
          </div>
        </div>

        {/* ------------------------------------------------ inspector */}
        <aside className="min-w-0">
          <div className="mb-3 flex flex-wrap gap-2">
            <Select
              label="Batch"
              value={lotId}
              onChange={(v) => {
                setLotId(v);
                setSelected(null);
              }}
              options={data.lots.map((l) => ({ v: l.lot, t: l.lot }))}
            />
            <Select
              label="Measurement"
              value={String(pi)}
              onChange={(v) => setPi(Number(v))}
              options={meta.params.map((p, i) => ({ v: String(i), t: p.label }))}
            />
          </div>

          {!sel ? (
            <Card className="p-5">
              <p className="text-sm text-graphite">
                Click any chip in the tray to inspect it, or press{" "}
                <strong className="text-ink">Show me the hidden one</strong> to jump to the chip this
                batch should worry about.
              </p>
            </Card>
          ) : (
            <Card className="overflow-hidden">
              <CardHead title={sel.part.s} right={<Stamp v={sel.part.v} />} />
              <div className="px-5 pb-5">
                <Risk r={sel.part.r} v={sel.part.v} />

                <div className="mt-4 border-t border-hair pt-3">
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-mute">
                    At {t.toFixed(0)} h, against its own batch
                  </p>
                  <Row k={pm.label} v={selValue == null ? "no reading" : `${num(selValue, 2)} ${unit(pm.unit)}`} />
                  <Row k="Batch middle" v={`${num(lot.median, 2)} ${unit(pm.unit)}`} />
                  <Row
                    k="Distance from batch"
                    v={`${num(selZ, 1)} σ`}
                    tone={selZ >= 6 ? "text-reject" : selZ >= 3 ? "text-watch" : undefined}
                  />
                  <Row
                    k="Standing"
                    v={STATE_LABEL[selState]}
                    tone={selZ >= 6 ? "text-reject" : selZ >= 3 ? "text-watch" : undefined}
                  />
                  <Row
                    k="Datasheet"
                    v={breached ? "BREACH" : "PASS"}
                    tone={breached ? "text-reject" : "text-pass"}
                  />
                </div>

                {sel.part.st === 0 && sel.part.y1 === 1 && (
                  <Notice tone="warn" className="mt-4">
                    This chip passes the datasheet at every read point and is a real defect. A
                    fixed limit would have shipped it.
                  </Notice>
                )}

                {reasons.length > 0 && (
                  <div className="mt-4 border-t border-hair pt-1">
                    <p className="mb-1 mt-2 text-xs font-semibold uppercase tracking-wide text-mute">
                      Why SENTINEL flagged it
                    </p>
                    <ul className="divide-y divide-hair">
                      {reasons.map((r) => (
                        <ReasonCode key={r.code} r={r} />
                      ))}
                    </ul>
                  </div>
                )}

                <Link
                  href={`/console/reports?serial=${sel.part.s}`}
                  className="mt-4 inline-block text-sm font-semibold text-cobalt underline underline-offset-4"
                >
                  Open the inspector report
                </Link>
              </div>
            </Card>
          )}

          <Notice className="mt-4">
            The risk score, verdict and reason codes come from{" "}
            <code>src/pipeline.py</code> and are shown as computed. The σ distance shown while
            scrubbing is a batch percentile recomputed in the browser from the same measurements,
            for drawing only. It decides nothing.
          </Notice>
        </aside>
      </div>

      <Provenance modelVersion={meta.modelVersion} source={meta.generatedFrom} />
    </>
  );
}

// ------------------------------------------------------------- small parts
function Key({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span aria-hidden className="h-2.5 w-2.5 rounded-sm" style={{ background: color }} />
      {label}
    </span>
  );
}

function Readout({ k, v, tone }: { k: string; v: string; tone?: string }) {
  return (
    <div className="rounded-card border border-rule bg-sheet px-4 py-3">
      <div className="text-xs text-graphite">{k}</div>
      <div className={cn("wide mt-0.5 text-lg font-bold tabular-nums", tone)}>{v}</div>
    </div>
  );
}

function Select({
  label, value, onChange, options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { v: string; t: string }[];
}) {
  return (
    <label className="flex-1 text-xs text-graphite">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-ctl border border-rule bg-sheet px-2.5 py-2 text-sm font-semibold text-ink"
      >
        {options.map((o) => (
          <option key={o.v} value={o.v}>
            {o.t}
          </option>
        ))}
      </select>
    </label>
  );
}
