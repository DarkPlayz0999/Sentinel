import Link from "next/link";
import { LAB } from "@/lib/lab-data";
import { unit } from "@/components/ui/kit";
import { C } from "@/lib/theme";

/* HERO.
 *
 * The argument of the whole project in one picture: lot L04 at 168 h, one dot
 * per component, piled up around its median - and one component far out on
 * its own, sitting just under the datasheet limit. Every dot is a real part
 * from the screened dataset (LAB.hero.lotHist, 1.25 µA bins, exported by
 * web/scripts/export_lab_data.py). The one animation on the site is the lot
 * settling into place; reduced motion gets the final frame. */

const H = LAB.hero;
const U = unit(H.unit);
type Bin = { readonly x: number; readonly n: number };

function DotPlot({ w, h, across, fs, narrow = false }: { w: number; h: number; across: number; fs: number; narrow?: boolean }) {
  // Label rows, in multiples of fs below the top rule. On a narrow screen the
  // median and limit labels would collide, so they stack instead.
  const row = narrow
    ? { usl: 0.9, med: [2.3, 3.5], part: [4.9, 6.1] }
    : { usl: 0.9, med: [0.9, 2.2], part: [3.3, 4.6] };
  const bins = H.lotHist as readonly Bin[];
  const defects = H.lotDefectHist as readonly Bin[];
  const pl = fs * 0.5, pr = fs * 0.5, pt = fs * (row.part[1] + 1.2), pb = fs * 3;
  const x0 = pl, x1 = w - pr, y1 = h - pb;
  const X = (v: number) => x0 + ((v - H.histLo) / (H.histHi - H.histLo)) * (x1 - x0);
  const col = (x1 - x0) / bins.length;
  const pitch = col / across;
  const r = pitch * 0.4;
  const heroBin = Math.floor((H.value168 - H.histLo) / ((H.histHi - H.histLo) / bins.length));

  // Healthy dots first, labelled latent defects stacked on top, so the red
  // accumulates where the lot thins out - which is the point.
  const dots: { cx: number; cy: number; d: boolean; i: number; hero: boolean }[] = [];
  bins.forEach((b, i) => {
    const nd = defects[i]?.n ?? 0;
    for (let k = 0; k < b.n; k++) {
      const cx = x0 + i * col + pitch * ((k % across) + 0.5);
      const cy = y1 - pitch * (Math.floor(k / across) + 0.5);
      const hero = i === heroBin && k === b.n - 1;
      dots.push({ cx, cy, d: k >= b.n - nd, i, hero });
    }
  });
  const hd = dots.find((d) => d.hero)!;
  const n = bins.reduce((a, b) => a + b.n, 0);
  const xm = X(H.lotMedian168), xu = X(H.usl);
  const top = pt - fs * 1.2;

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="block h-auto w-full" role="img"
      aria-label={`Lot ${H.lot}: ${n} components at 168 h. ${H.serial} reads ${H.value168} ${U}, under the ${H.usl} ${U} datasheet limit and far from its lot's median of ${H.lotMedian168} ${U}.`}>
      {/* datasheet limit */}
      <line x1={xu} x2={xu} y1={top} y2={y1} stroke={C.reject} strokeWidth={fs * 0.14} />
      <text x={xu - fs * 0.5} y={top + fs * row.usl} textAnchor="end" fontSize={fs} fontWeight={700} fill={C.reject}>
        Datasheet limit {H.usl} {U}
      </text>

      {/* lot median */}
      <line x1={xm} x2={xm} y1={top} y2={y1} stroke={C.ink} strokeWidth={fs * 0.1} strokeDasharray={`${fs * 0.3} ${fs * 0.3}`} />
      <text x={xm + fs * 0.5} y={top + fs * row.med[0]} paintOrder="stroke" stroke={C.sheet} strokeWidth={fs * 0.35} fontSize={fs} fontWeight={700} fill={C.ink}>
        Lot median {H.lotMedian168} {U}
      </text>
      <text x={xm + fs * 0.5} y={top + fs * row.med[1]} paintOrder="stroke" stroke={C.sheet} strokeWidth={fs * 0.35} fontSize={fs} fill={C.graphite}>
        where {n} parts from lot {H.lot} ended up
      </text>

      <g className="settle">
        {dots.map((d, j) =>
          d.hero ? null : (
            <circle key={j} cx={d.cx} cy={d.cy} r={r} fill={d.d ? C.reject : C.cobalt}
              fillOpacity={d.d ? 0.9 : 0.55} style={{ animationDelay: `${d.i * 22 + (j % across) * 8}ms` }} />
          )
        )}
      </g>

      {/* the component */}
      <g className="settle-last">
        <circle cx={hd.cx} cy={hd.cy} r={r * 2.3} fill="none" stroke={C.reject} strokeWidth={fs * 0.12} />
        <circle cx={hd.cx} cy={hd.cy} r={r * 1.3} fill={C.reject} />
        <line x1={hd.cx} x2={hd.cx} y1={hd.cy - r * 2.6} y2={top + fs * (row.part[0] + 0.1)} stroke={C.reject} strokeWidth={fs * 0.08} />
        <text x={hd.cx - fs * 0.6} y={top + fs * row.part[0]} textAnchor="end" paintOrder="stroke" stroke={C.sheet} strokeWidth={fs * 0.35} fontSize={fs * 1.15} fontWeight={800} fill={C.reject}>
          {H.serial}: {H.value168} {U}
        </text>
        <text x={hd.cx - fs * 0.6} y={top + fs * row.part[1]} textAnchor="end" paintOrder="stroke" stroke={C.sheet} strokeWidth={fs * 0.35} fontSize={fs} fill={C.graphite}>
          passes by {H.marginLeft} {U}; drift {H.driftZ}σ beyond its lot
        </text>
      </g>

      {/* axis */}
      <line x1={x0} x2={x1} y1={y1} y2={y1} stroke={C.rule} strokeWidth={fs * 0.1} />
      {[0, 10, 20, 30, 40, 50].map((v) => (
        <text key={v} x={X(v)} y={y1 + fs * 1.4} textAnchor="middle" fontSize={fs} fill={C.mute}>{v}</text>
      ))}
      <text x={x1} y={h - fs * 0.3} textAnchor="end" fontSize={fs} fill={C.mute}>
        {H.param} at 168 h of burn-in, {U}
      </text>
    </svg>
  );
}

export function Hero() {
  return (
    <section className="mx-auto max-w-[1200px] px-4 pb-16 pt-12 sm:px-8 sm:pt-20">
      <h1 className="wide max-w-[17ch] text-[40px] font-black leading-[1.02] tracking-[-0.02em] sm:text-5xl lg:text-[76px]">
        It passed every limit. It was still the worst part in its lot.
      </h1>
      <div className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:items-end">
        <p className="max-w-prose text-lg text-graphite">
          SENTINEL screens burn-in components against their own production lot, not just the
          datasheet. It forecasts drift from the first 24 hours and gives every rejection a
          reason an inspector can check.
        </p>
        <div className="flex flex-wrap gap-3 lg:justify-end">
          <Link href="/console" className="btn-primary px-5 py-2.5 text-base">Open the console</Link>
          <a href="#detection" className="btn-quiet px-5 py-2.5 text-base">See how detection works</a>
        </div>
      </div>

      <figure className="card mt-10 px-4 pb-4 pt-5 sm:px-6">
        <div className="hidden sm:block"><DotPlot w={1120} h={440} across={2} fs={13} /></div>
        <div className="sm:hidden"><DotPlot w={560} h={560} across={2} fs={18} narrow /></div>
        <figcaption className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm text-graphite">
          <span>One dot per component, binned to {(H.histHi - H.histLo) / H.lotHist.length} {U}.</span>
          <span className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-full bg-reject" />
            Labelled latent defect (simulated ground truth, never a screening input)
          </span>
        </figcaption>
      </figure>
    </section>
  );
}
