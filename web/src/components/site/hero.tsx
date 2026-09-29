"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { LAB } from "@/lib/lab-data";
import { Led, num, unit } from "@/components/ui/kit";
import { cn } from "@/lib/utils";

/* HERO.
 *
 * The visual is a test fixture and a measurement trace, not an abstraction of
 * intelligence. The trace being drawn is the REAL 0/24/96/168 h Iddq record of
 * the component the rest of the page is about (LAB.hero.trace, exported from
 * the screened dataset) - the playhead interpolates between measured points
 * with the same power law Module B fits, and every readout is a real figure at
 * that elapsed hour. Nothing on this page is a decorative number. */

const H = LAB.hero;
const HOURS = 168;

/** Interpolate the real read points. Between reads, the power law the physics
 *  model uses; at a read point, exactly the measured value. */
function traceAt(t: number): number {
  const hs = H.hours as readonly number[];
  const vs = H.trace as readonly number[];
  if (t <= hs[0]) return vs[0];
  for (let i = 1; i < hs.length; i++) {
    if (t <= hs[i]) {
      const f = (t - hs[i - 1]) / (hs[i] - hs[i - 1]);
      // ease toward the next measured point - degradation accelerates, so a
      // straight line between reads understates the late-window movement
      return vs[i - 1] + (vs[i] - vs[i - 1]) * Math.pow(f, 0.82);
    }
  }
  return vs[vs.length - 1];
}

const tempAt = (t: number) => (t < 2 ? 25 + (125 - 25) * (t / 2) : 125 + Math.sin(t * 1.7) * 0.3);

function useBurnInClock() {
  const [t, setT] = useState(HOURS);
  const [running, setRunning] = useState(true);
  const hold = useRef(0);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setT(HOURS);
      return;
    }
    if (!running) return;
    let raf = 0;
    let last = performance.now();
    setT((p) => (p >= HOURS ? 0 : p));
    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      setT((prev) => {
        if (prev >= HOURS) {
          if (!hold.current) hold.current = now + 3800;
          if (now < hold.current) return HOURS;
          hold.current = 0;
          return 0;
        }
        return Math.min(HOURS, prev + dt * 30);
      });
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [running]);

  return { t, running, setRunning, seek: setT };
}

/* ------------------------------------------------- the fixture drawing */
function Fixture({ t, value }: { t: number; value: number }) {
  const hot = t > 1;
  const risk = Math.min(1, Math.max(0, (value - H.lotMedian168) / (H.usl - H.lotMedian168)));
  const tone = risk > 0.62 ? "#A81E12" : risk > 0.28 ? "#9A5B06" : "#186B45";

  return (
    <svg viewBox="0 0 260 176" className="w-full" role="img"
      aria-label="Component in a burn-in test socket at 125 °C">
      <title>Component under burn-in in a test socket</title>
      <defs>
        <pattern id="gp-fx" width="10" height="10" patternUnits="userSpaceOnUse">
          <path d="M10 0H0V10" fill="none" stroke="#0F1317" strokeOpacity="0.055" strokeWidth="1" />
        </pattern>
      </defs>
      {/* burn-in board */}
      <rect x="10" y="26" width="240" height="128" fill="#F0EFEA" stroke="#C6C9CF" />
      <rect x="10" y="26" width="240" height="128" fill="url(#gp-fx)" opacity="0.5" />
      {/* board traces */}
      {[44, 58, 72, 118, 132, 146].map((y) => (
        <path key={y} d={`M14,${y} H96 L108,${y > 100 ? y + 10 : y - 10} H246`}
          fill="none" stroke="#B9BDC4" strokeWidth="1" />
      ))}

      {/* socket */}
      <rect x="84" y="58" width="92" height="62" fill="#DEDFE2" stroke="#9CA2AB" />
      {/* pins */}
      {Array.from({ length: 8 }, (_, i) => (
        <g key={i}>
          <rect x={92 + i * 10.5} y="50" width="4" height="10" fill="#8E939B" />
          <rect x={92 + i * 10.5} y="118" width="4" height="10" fill="#8E939B" />
        </g>
      ))}

      {/* the component package */}
      <rect x="94" y="66" width="72" height="46" fill="#1B1F24" stroke="#0F1317" />
      <circle cx="103" cy="75" r="3" fill="#3A4048" />
      <text x="130" y="86" textAnchor="middle" className="font-mono"
        style={{ fontSize: 8, fill: "#C9CDD3", letterSpacing: "0.1em" }}>
        {H.serial}
      </text>
      <text x="130" y="98" textAnchor="middle" className="font-mono"
        style={{ fontSize: 6.5, fill: "#7C838D", letterSpacing: "0.14em" }}>
        LOT {H.lot} · {H.wafer}
      </text>

      {/* status LED on the board */}
      <circle cx="232" cy="40" r="4" fill={tone} opacity={hot ? 1 : 0.35}>
        {hot && <animate attributeName="opacity" values="1;0.4;1" dur="2.4s" repeatCount="indefinite" />}
      </circle>

      {/* chamber heat: hatch rising from the board when at soak */}
      {hot && (
        <g opacity="0.5">
          {[40, 130, 210].map((x, i) => (
            <path key={x} d={`M${x},24 q4,-8 0,-16 q-4,-8 0,-14`} fill="none"
              stroke="#A81E12" strokeWidth="1" strokeOpacity="0.5"
              className="animate-shimmer" style={{ animationDelay: `${i * 0.4}s` }} />
          ))}
        </g>
      )}

      {/* chamber label */}
      <text x="14" y="20" className="font-mono"
        style={{ fontSize: 7.5, fill: "#8C939E", letterSpacing: "0.14em" }}>
        BURN-IN CHAMBER · SLOT 042
      </text>
      <text x="246" y="20" textAnchor="end" className="font-mono"
        style={{ fontSize: 8, fill: hot ? "#A81E12" : "#8C939E", fontWeight: 700 }}>
        {tempAt(t).toFixed(1)} °C
      </text>
      <rect x="10" y="160" width="240" height="8" fill="#DEDFE2" stroke="#C6C9CF" />
      <rect x="10" y="160" width={240 * (t / HOURS)} height="8" fill="#12508C" fillOpacity="0.55" />
    </svg>
  );
}

/* ------------------------------------------------- the live trace plot */
function LiveTrace({ t }: { t: number }) {
  const w = 420, h = 188;
  const pl = 40, pr = 52, pt = 14, pb = 30;
  const x0 = pl, x1 = w - pr, y0 = pt, y1 = h - pb;
  const lo = 0;
  const hi = Math.max(H.usl * 1.06, ...(H.p95 as readonly number[]));
  const X = (v: number) => x0 + (v / HOURS) * (x1 - x0);
  const Y = (v: number) => y1 - ((v - lo) / (hi - lo)) * (y1 - y0);

  const hs = H.hours as readonly number[];
  const band = (arr: readonly number[]) => hs.map((hv, i) => `${X(hv)},${Y(arr[i])}`).join(" L");

  // the drawn portion of the real trace, up to the playhead
  const step = 2;
  const pts: string[] = [];
  for (let x = 0; x <= t; x += step) pts.push(`${X(x).toFixed(1)},${Y(traceAt(x)).toFixed(1)}`);
  pts.push(`${X(t).toFixed(1)},${Y(traceAt(t)).toFixed(1)}`);

  const now = traceAt(t);

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full" role="img"
      aria-label={`Live ${H.param} trace for ${H.serial}`}>
      <title>{`${H.param} against the lot envelope`}</title>
      <defs>
        <pattern id="gp-tr" width="10" height="10" patternUnits="userSpaceOnUse">
          <path d="M10 0H0V10" fill="none" stroke="#0F1317" strokeOpacity="0.055" strokeWidth="1" />
        </pattern>
      </defs>
      <rect x={x0} y={y0} width={x1 - x0} height={y1 - y0} fill="#FCFCFB" />
      <rect x={x0} y={y0} width={x1 - x0} height={y1 - y0} fill="url(#gp-tr)" />

      {/* lot 5th-95th envelope */}
      <path
        d={`M${band(H.p95 as readonly number[])} L${hs.slice().reverse()
          .map((hv, i) => `${X(hv)},${Y((H.p05 as readonly number[])[hs.length - 1 - i])}`)
          .join(" L")} Z`}
        fill="#12508C" fillOpacity="0.13"
      />
      <path d={`M${band(H.p50 as readonly number[])}`} fill="none" stroke="#12508C"
        strokeWidth="1" strokeDasharray="4 3" strokeOpacity="0.8" />

      {/* datasheet limit */}
      <line x1={x0} x2={x1} y1={Y(H.usl)} y2={Y(H.usl)} stroke="#A81E12" strokeWidth="1.25" />
      <text x={x1 + 4} y={Y(H.usl) + 3} className="font-mono"
        style={{ fontSize: 7.5, fill: "#A81E12", fontWeight: 700 }}>
        USL {H.usl}
      </text>

      {/* read-point rules */}
      {hs.map((hv) => (
        <line key={hv} x1={X(hv)} x2={X(hv)} y1={y0} y2={y1} stroke="#9CA2AB"
          strokeOpacity="0.35" strokeWidth="0.75" strokeDasharray="1 3" />
      ))}

      {/* the trace, drawn to the playhead */}
      <polyline points={pts.join(" ")} fill="none" stroke="#A81E12" strokeWidth="1.9" />
      {hs.map((hv, i) =>
        t >= hv ? (
          <circle key={hv} cx={X(hv)} cy={Y((H.trace as readonly number[])[i])} r="2.8"
            fill="#FFFFFF" stroke="#A81E12" strokeWidth="1.5" />
        ) : null
      )}
      {/* playhead */}
      <circle cx={X(t)} cy={Y(now)} r="4" fill="#A81E12" />
      <line x1={X(t)} x2={X(t)} y1={y0} y2={y1} stroke="#A81E12" strokeOpacity="0.28" strokeWidth="1" />

      {/* axes */}
      {[0, 24, 96, 168].map((hv) => (
        <text key={hv} x={X(hv)} y={y1 + 12} textAnchor="middle" className="font-mono"
          style={{ fontSize: 8, fill: "#8C939E" }}>
          {hv}h
        </text>
      ))}
      {[0, H.lotMedian168, H.usl].map((v, i) => (
        <text key={i} x={x0 - 5} y={Y(v) + 3} textAnchor="end" className="font-mono"
          style={{ fontSize: 7.5, fill: "#8C939E" }}>
          {v.toFixed(0)}
        </text>
      ))}
      <text x={(x0 + x1) / 2} y={h - 3} textAnchor="middle" className="font-mono"
        style={{ fontSize: 7.5, fill: "#8C939E", letterSpacing: "0.1em" }}>
        {H.param} ({unit(H.unit)}) · BURN-IN HOURS AT 125 °C
      </text>
      <rect x={x0} y={y0} width={x1 - x0} height={y1 - y0} fill="none" stroke="#9CA2AB" />
    </svg>
  );
}

/* --------------------------------------------------------------- hero */
export function Hero() {
  const { t, running, setRunning, seek } = useBurnInClock();
  const v = traceAt(t);
  const stage =
    t < 24 ? "SETTLING" : t < 96 ? "DRIFT DETECTED" : t < 168 ? "TRACKING" : "SCREEN COMPLETE";

  return (
    <section className="border-b border-lab-rule bg-lab-card">
      <div className="mx-auto grid max-w-[1400px] gap-px bg-lab-rule px-0 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.02fr)]">
        {/* ------------------------------------------------------- copy */}
        <div className="bg-lab-card px-4 py-10 sm:px-8 lg:py-14">
          <div className="flex flex-wrap items-center gap-2.5">
            <span className="border border-lab-rule bg-lab-panel px-2 py-1 font-mono text-[9px] uppercase tracking-label text-lab-dim">
              ISRO · SIH26170 · Burn-in reliability
            </span>
            <span className="flex items-center gap-1.5">
              <Led tone="green" />
              <span className="font-mono text-[9px] uppercase tracking-label text-lab-dim">
                {LAB.headline.parts.toLocaleString()} components screened
              </span>
            </span>
          </div>

          <h1 className="mt-5 text-[34px] font-semibold leading-[1.08] tracking-[-0.02em] text-lab-ink sm:text-[44px]">
            Beyond Pass/Fail.
            <br />
            <span className="text-sig-blue">Detect What the Limits Miss.</span>
          </h1>

          <p className="mt-4 max-w-[52ch] text-[14px] leading-relaxed text-lab-dim">
            Identify statistically abnormal components, forecast emerging drift, and provide an
            auditable engineering reason for every screening decision.
          </p>

          <p className="mt-3 max-w-[56ch] font-mono text-[10.5px] leading-relaxed text-lab-faint">
            SENTINEL analyses burn-in behaviour relative to a component&rsquo;s manufacturing lot
            and forecasts emerging drift before conventional screening limits are exceeded.
          </p>

          <div className="mt-6 flex flex-wrap gap-2.5">
            <Link
              href="/console"
              className="border border-lab-ink bg-lab-ink px-4 py-2.5 font-mono text-[11px] uppercase tracking-label text-lab-panel transition-opacity hover:opacity-85"
            >
              Open Screening Console
            </Link>
            <a
              href="#module-a"
              className="border border-lab-rule bg-lab-card px-4 py-2.5 font-mono text-[11px] uppercase tracking-label text-lab-ink transition-colors hover:bg-lab-panel"
            >
              View Detection Method
            </a>
          </div>

          {/* the process tape */}
          <ol className="mt-8 grid gap-px bg-lab-rule sm:grid-cols-5">
            {[
              { k: "01", v: "Component", s: "high-reliability part" },
              { k: "02", v: "Burn-in 125 °C", s: "powered under stress" },
              { k: "03", v: "0 · 24 · 96 · 168 h", s: "four parametric reads" },
              { k: "04", v: "SENTINEL analysis", s: "lot-relative + forecast" },
              { k: "05", v: "Pass / Watch / Reject", s: "with a signed reason" },
            ].map((s) => (
              <li key={s.k} className="bg-lab-card px-2.5 py-2.5">
                <div className="font-mono text-[8.5px] font-bold tracking-label text-sig-blue">
                  {s.k}
                </div>
                <div className="readout mt-1 text-[10.5px] font-semibold leading-tight text-lab-ink">
                  {s.v}
                </div>
                <div className="mt-1 font-mono text-[8.5px] leading-tight text-lab-faint">{s.s}</div>
              </li>
            ))}
          </ol>
        </div>

        {/* ----------------------------------------------------- fixture */}
        <div className="bg-lab-panel px-4 py-8 sm:px-6">
          <div className="flex items-baseline justify-between border-b border-lab-hair pb-2">
            <span className="font-mono text-[10px] font-bold uppercase tracking-label text-lab-ink">
              Live test cell
            </span>
            <span className="font-mono text-[9px] uppercase tracking-label text-lab-faint">
              replay of a screened record
            </span>
          </div>

          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div className="panel p-2">
              <Fixture t={t} value={v} />
            </div>
            <div className="panel p-2">
              <LiveTrace t={t} />
            </div>
          </div>

          {/* readouts */}
          <div className="mt-3 grid grid-cols-2 gap-px bg-lab-rule sm:grid-cols-4">
            {[
              { k: "Elapsed", v: `${Math.floor(t)}h`, tone: "text-lab-ink" },
              { k: H.param, v: `${num(v, 1)} ${unit(H.unit)}`, tone: "text-sig-red" },
              { k: "Lot median", v: `${num(H.lotMedian168, 1)} ${unit(H.unit)}`, tone: "text-lab-dim" },
              {
                k: "Stage",
                v: stage,
                tone: t >= 24 ? "text-sig-amber" : "text-sig-green",
              },
            ].map((r) => (
              <div key={r.k} className="bg-lab-card px-2.5 py-2">
                <div className="label">{r.k}</div>
                <div className={cn("readout mt-1 text-[12px] font-semibold leading-none", r.tone)}>
                  {r.v}
                </div>
              </div>
            ))}
          </div>

          {/* transport */}
          <div className="panel mt-3 flex items-center gap-3 px-3 py-2">
            <button
              onClick={() => setRunning(!running)}
              aria-label={running ? "Hold the replay" : "Resume the replay"}
              className="border border-lab-ink bg-lab-ink px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-label text-lab-panel hover:opacity-85"
            >
              {running ? "❚❚ Hold" : "▶ Run"}
            </button>
            <input
              type="range"
              min={0}
              max={HOURS}
              step={1}
              value={Math.round(t)}
              aria-label="Burn-in elapsed hours"
              onChange={(e) => { setRunning(false); seek(Number(e.target.value)); }}
              className="h-1 flex-1 cursor-pointer appearance-none bg-lab-sunk accent-sig-blue"
            />
            <span className="readout w-14 text-right text-[10px] text-lab-dim">
              {Math.floor(t)}h / 168h
            </span>
          </div>

          <p className="mt-2.5 font-mono text-[8.5px] leading-relaxed text-lab-faint">
            <span className="font-bold text-lab-dim">Replay, not live acquisition.</span> The
            trace is the actual 0/24/96/168 h record of {H.serial} from the screened dataset
            (seed 42); the playhead interpolates between measured reads. Live inference runs in
            the console.
          </p>
        </div>
      </div>
    </section>
  );
}
