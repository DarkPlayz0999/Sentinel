"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Card, num } from "@/components/ui/kit";
import { useConsole } from "@/lib/console";

/* The console chrome: a rail with the six screens and the run's tag - the
 * facts that hang on a lot as it moves through the line. Screen sits second
 * because it is step one of the workflow: a lot arrives, you screen it, then
 * you read the result in the screens that follow. */

const NAV = [
  { href: "/console", label: "Results at a glance", hint: "What was caught, and what to look at first" },
  { href: "/console/screen", label: "Check a new batch", hint: "Upload a test file and screen it" },
  { href: "/console/lots", label: "Batches", hint: "Is any whole batch misbehaving?" },
  { href: "/console/components", label: "Every chip", hint: "Search, sort and open any chip" },
  { href: "/console/analysis", label: "How it decides", hint: "The checks, weights and limits" },
  { href: "/console/reports", label: "Inspector report", hint: "A printable record for one chip" },
  { href: "/console/agents", label: "AI agents, live", hint: "The automated team at work" },
];

export function Wordmark({ href = "/", className = "text-ink" }: { href?: string; className?: string }) {
  return (
    <Link href={href} className={cn("wide text-lg font-black tracking-[0.04em]", className)} aria-label="SENTINEL home">
      SENTINEL
    </Link>
  );
}

/** Accept / watch / reject as one proportional bar - the run at a glance. */
function Disposition({ accept, watch, reject }: { accept: number; watch: number; reject: number }) {
  const total = accept + watch + reject || 1;
  const rows = [
    { k: "● Accept", n: accept, c: "#7FD6A8" },
    { k: "▲ Watch", n: watch, c: "#F2C14E" },
    { k: "■ Reject", n: reject, c: "#FF7A6B" },
  ];
  return (
    <div>
      <div className="flex h-2 overflow-hidden rounded-full" role="presentation">
        {rows.map((r) => (
          <span key={r.k} style={{ width: `${(r.n / total) * 100}%`, background: r.c }} />
        ))}
      </div>
      <dl className="mt-3 space-y-1">
        {rows.map((r) => (
          <div key={r.k} className="flex items-baseline justify-between text-sm">
            <dt className="flex items-center gap-2 text-[#B9CCC7]">
              <span style={{ color: r.c }}>{r.k.slice(0, 1)}</span>
              {r.k.slice(2)}
            </dt>
            <dd className="font-semibold">{r.n.toLocaleString()}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function ConsoleShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const { data } = useConsole();
  const s = data?.summary;
  const m = data?.meta;
  const isOn = (href: string) => (href === "/console" ? path === href : path.startsWith(href));

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[248px_minmax(0,1fr)]">
      <aside className="no-print bg-oven text-[#E7EFEC] lg:sticky lg:top-0 lg:h-screen lg:overflow-y-auto">
        <div className="flex items-center justify-between px-4 py-4 lg:px-6 lg:pt-6">
          <Wordmark className="text-[#E7EFEC]" />
          <Link href="/" className="text-sm text-[#9FB5B0] hover:text-[#E7EFEC] lg:hidden">
            How it works
          </Link>
        </div>

        <nav aria-label="Console" className="flex gap-1 overflow-x-auto px-3 pb-3 lg:flex-col lg:gap-0.5 lg:px-3 lg:pb-0">
          {NAV.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              aria-current={isOn(n.href) ? "page" : undefined}
              className={cn(
                "group whitespace-nowrap rounded-ctl px-3 py-2 text-sm transition-colors lg:whitespace-normal",
                isOn(n.href)
                  ? "bg-[#F2A365]/15 font-bold text-[#F7C49A] shadow-[inset_3px_0_0_#F2A365]"
                  : "text-[#E7EFEC] hover:bg-white/5"
              )}
            >
              {n.label}
              <span className={cn("hidden text-xs font-normal lg:block", isOn(n.href) ? "text-[#F7C49A]/80" : "text-[#8FA8A2]")}>
                {n.hint}
              </span>
            </Link>
          ))}
        </nav>

        {s && m && (
          <div className="hidden px-6 pb-6 pt-8 lg:block">
            <h2 className="text-xs font-semibold text-[#9FB5B0]">What was screened</h2>
            <p className="wide mt-1 text-2xl font-extrabold">{s.parts.toLocaleString()}</p>
            <p className="text-sm text-[#9FB5B0]">chips in {s.lots} batches</p>
            <div className="mt-4">
              <Disposition accept={s.accept} watch={s.watch} reject={s.reject} />
            </div>
            {s.lotsBreachingPda > 0 && (
              <Link href="/console/lots" className="mt-4 block rounded-ctl border border-[#FF7A6B]/40 bg-[#FF7A6B]/10 px-3 py-2 text-sm text-[#FFA195] hover:bg-[#FF7A6B]/20">
                {s.lotsBreachingPda} batch{s.lotsBreachingPda > 1 ? "es" : ""} rejected too often: review
              </Link>
            )}
            <dl className="mt-6 space-y-1.5 border-t border-[#1E4A45] pt-4 text-xs">
              {[
                ["Flag at", `watch ≥ ${num(m.bands.watch, 1)}, reject ≥ ${num(m.bands.reject, 1)}`],
                ["Burn-in", `${m.stressTempC} °C, reads at ${m.readPoints.join(", ")} h`],
                ["Model", m.modelVersion],
                ["Data", "Simulated, seed 42"],
              ].map(([k, v]) => (
                <div key={k} className="grid grid-cols-[60px_1fr] gap-2">
                  <dt className="text-[#8FA8A2]">{k}</dt>
                  <dd className="text-[#C9D8D4]">{v}</dd>
                </div>
              ))}
            </dl>
            <Link href="/" className="mt-6 inline-block text-sm text-[#9FB5B0] hover:text-[#E7EFEC]">
              How SENTINEL works
            </Link>
          </div>
        )}
      </aside>

      <main className="mx-auto w-full max-w-[1280px] px-4 py-8 sm:px-8 lg:py-10">{children}</main>
    </div>
  );
}

/** Loading / error state, so no screen renders half a dataset. */
export function ConsoleState({ error }: { error?: string | null }) {
  return (
    <Card className="grid min-h-[320px] place-items-center p-8 text-center">
      {error ? (
        <div className="max-w-lg">
          <p className="font-bold text-reject">The screening record could not be loaded</p>
          <p className="mt-2 text-sm text-graphite">{error}</p>
          <p className="mt-3 text-sm text-graphite">
            Generate it from the repository root with{" "}
            <code>python web/scripts/export_lab_data.py</code>, then reload.
          </p>
        </div>
      ) : (
        <p className="text-sm text-graphite">Loading the screening record…</p>
      )}
    </Card>
  );
}
