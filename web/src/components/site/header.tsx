"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Led } from "@/components/ui/kit";

const SECTIONS = [
  { id: "problem", label: "The gap" },
  { id: "module-a", label: "Detection" },
  { id: "module-b", label: "Prediction" },
  { id: "explain", label: "Explainability" },
];

/** The plate riveted to the front of the rack: identity, jump links, status. */
export function SiteHeader() {
  const [utc, setUtc] = useState("--:--:--");
  useEffect(() => {
    const tick = () => setUtc(new Date().toISOString().slice(11, 19));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <header className="sticky top-0 z-50 border-b border-lab-rule bg-lab-panel/96 backdrop-blur-sm">
      <div className="mx-auto flex h-[52px] max-w-[1400px] items-center gap-5 px-4 sm:px-6">
        <Link href="/" className="flex shrink-0 items-center gap-2.5">
          <span className="grid h-8 w-8 place-items-center border border-lab-ink bg-lab-ink">
            <span className="font-mono text-[13px] font-bold text-lab-panel">S</span>
          </span>
          <span className="leading-none">
            <span className="block font-mono text-[13px] font-bold tracking-[0.18em] text-lab-ink">
              SENTINEL
            </span>
            <span className="mt-1 block font-mono text-[8.5px] uppercase tracking-label text-lab-faint">
              Component Reliability Intelligence
            </span>
          </span>
        </Link>

        <nav className="ml-4 hidden min-w-0 gap-1 md:flex" aria-label="Sections">
          {SECTIONS.map((s) => (
            <a
              key={s.id}
              href={`#${s.id}`}
              className="whitespace-nowrap px-2.5 py-2 font-mono text-[10px] uppercase tracking-label text-lab-dim transition-colors hover:text-lab-ink"
            >
              {s.label}
            </a>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-4">
          <span className="hidden items-baseline gap-1.5 lg:flex">
            <span className="label">UTC</span>
            <span className="readout text-[11px] text-lab-ink">{utc}</span>
          </span>
          <span className="hidden items-center gap-1.5 sm:flex">
            <Led tone="green" />
            <span className="font-mono text-[9px] uppercase tracking-label text-lab-dim">
              Screening active
            </span>
          </span>
          <Link
            href="/console"
            className="border border-lab-ink bg-lab-ink px-3 py-1.5 font-mono text-[10px] uppercase tracking-label text-lab-panel transition-opacity hover:opacity-85"
          >
            Open console
          </Link>
        </div>
      </div>
    </header>
  );
}
