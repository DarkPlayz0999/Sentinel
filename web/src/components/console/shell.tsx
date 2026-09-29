"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactNode, useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { Led } from "@/components/ui/kit";
import { useConsole } from "@/lib/console";

/* The console chrome: identity plate, route rail, and the facility status
 * strip. Modelled on the front panel of a rack instrument - a name plate, a
 * row of legends, and a line of live readouts. Six routes, no mega-menu. */

const NAV = [
  { href: "/console", label: "Overview" },
  // Screen sits second because it is step one of the workflow: a lot arrives,
  // you screen it, then you read the result in the screens that follow.
  { href: "/console/screen", label: "Screen" },
  { href: "/console/lots", label: "Lots" },
  { href: "/console/components", label: "Components" },
  { href: "/console/analysis", label: "Analysis" },
  { href: "/console/reports", label: "Reports" },
];

function Readout({ k, v, tone, led }: { k: string; v: string; tone?: string; led?: ReactNode }) {
  return (
    <span className="flex items-baseline gap-1.5 whitespace-nowrap">
      <span className="label">{k}</span>
      {led}
      <span className={cn("readout text-[11px] font-semibold", tone ?? "text-lab-ink")}>{v}</span>
    </span>
  );
}

export function ConsoleShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const { data } = useConsole();
  const [utc, setUtc] = useState("--:--:--");

  useEffect(() => {
    const tick = () => setUtc(new Date().toISOString().slice(11, 19));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  const s = data?.summary;

  return (
    <div className="min-h-screen bg-lab-floor">
      <header className="sticky top-0 z-50 border-b border-lab-rule bg-lab-panel/96 backdrop-blur-sm">
        {/* identity + route rail */}
        <div className="flex h-[52px] items-center gap-5 border-b border-lab-hair px-4 sm:px-6">
          <Link href="/" className="flex shrink-0 items-center gap-2.5" aria-label="SENTINEL home">
            <span className="grid h-8 w-8 place-items-center border border-lab-ink bg-lab-ink">
              <span className="font-mono text-[13px] font-bold text-lab-panel">S</span>
            </span>
            <span className="leading-none">
              <span className="block font-mono text-[13px] font-bold tracking-[0.18em] text-lab-ink">
                SENTINEL
              </span>
              <span className="mt-1 block font-mono text-[8.5px] uppercase tracking-label text-lab-faint">
                Reliability Intelligence
              </span>
            </span>
          </Link>

          <nav className="-mb-px ml-2 flex min-w-0 overflow-x-auto" aria-label="Console sections">
            {NAV.map((n) => {
              const on = n.href === "/console" ? path === n.href : path.startsWith(n.href);
              return (
                <Link
                  key={n.href}
                  href={n.href}
                  aria-current={on ? "page" : undefined}
                  className={cn(
                    "whitespace-nowrap border-b-2 px-3.5 py-4 font-mono text-[10px] uppercase tracking-label transition-colors",
                    on
                      ? "border-sig-blue text-lab-ink"
                      : "border-transparent text-lab-dim hover:text-lab-ink"
                  )}
                >
                  {n.label}
                </Link>
              );
            })}
          </nav>

          <div className="ml-auto hidden items-center gap-4 lg:flex">
            <Readout k="Chamber" v="125 °C" />
            <Readout k="Cycle" v="168 h" />
            <Readout
              k="System"
              v={data ? "HEALTHY" : "LOADING"}
              tone={data ? "text-sig-green" : "text-lab-faint"}
              led={<Led tone={data ? "green" : "amber"} />}
            />
          </div>
        </div>

        {/* facility status strip */}
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1 px-4 py-1.5 sm:px-6">
          <Readout k="Burn-in" v="125 °C soak" />
          <Readout k="Read points" v="0 / 24 / 96 / 168 h" />
          <Readout k="Screening" v="ACTIVE" tone="text-sig-green" />
          {s && (
            <>
              <Readout k="Components" v={s.parts.toLocaleString()} />
              <Readout k="Flagged" v={(s.reject + s.watch).toLocaleString()} tone="text-sig-amber" />
              <Readout k="Reject" v={s.reject.toLocaleString()} tone="text-sig-red" />
              <Readout
                k="PDA"
                v={s.lotsBreachingPda ? `${s.lotsBreachingPda} LOT REVIEW` : "ALL OK"}
                tone={s.lotsBreachingPda ? "text-sig-red" : "text-sig-green"}
              />
            </>
          )}
          <Readout k="Model" v={data?.meta.modelVersion ?? "—"} />
          <span className="ml-auto hidden sm:block">
            <Readout k="UTC" v={utc} />
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-[1500px] px-4 py-6 sm:px-6">{children}</main>

      <footer className="border-t border-lab-rule bg-lab-panel">
        <div className="mx-auto flex max-w-[1500px] flex-wrap items-center gap-x-5 gap-y-1 px-4 py-3 sm:px-6">
          <span className="label">SENTINEL · SIH26170 · ISRO</span>
          <span className="font-mono text-[9px] text-lab-faint">
            All screening output on simulated data (seed 42) via src/pipeline.py
          </span>
          <Link
            href="/"
            className="ml-auto font-mono text-[9px] uppercase tracking-label text-sig-blue hover:underline"
          >
            ← Detection method
          </Link>
        </div>
      </footer>
    </div>
  );
}

/** Full-bleed loading / error state, so no screen renders half a dataset. */
export function ConsoleState({ error }: { error?: string | null }) {
  return (
    <div className="panel grid min-h-[320px] place-items-center p-8 text-center">
      {error ? (
        <div className="max-w-lg">
          <div className="font-mono text-[10px] font-bold uppercase tracking-label text-sig-red">
            Dataset unavailable
          </div>
          <p className="mt-2 font-mono text-[11px] leading-relaxed text-lab-dim">{error}</p>
          <p className="mt-3 font-mono text-[10px] text-lab-faint">
            Generate it with:{" "}
            <code className="text-lab-ink">python web/scripts/export_lab_data.py</code>
          </p>
        </div>
      ) : (
        <div className="flex items-center gap-2.5">
          <Led tone="amber" />
          <span className="font-mono text-[10px] uppercase tracking-label text-lab-dim">
            Loading screening record…
          </span>
        </div>
      )}
    </div>
  );
}
