"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { C } from "@/lib/theme";
import { Card, num } from "@/components/ui/kit";
import { useConsole } from "@/lib/console";

/* The console chrome: a rail with the six screens and the run's tag - the
 * facts that hang on a lot as it moves through the line. Screen sits second
 * because it is step one of the workflow: a lot arrives, you screen it, then
 * you read the result in the screens that follow. */

const NAV = [
  { href: "/console", label: "Overview" },
  { href: "/console/screen", label: "Screen a data log" },
  { href: "/console/lots", label: "Lots" },
  { href: "/console/components", label: "Components" },
  { href: "/console/analysis", label: "Method and policy" },
  { href: "/console/reports", label: "Reports" },
];

export function Wordmark({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="wide text-lg font-black tracking-[0.04em] text-ink" aria-label="SENTINEL home">
      SENTINEL
    </Link>
  );
}

/** Accept / watch / reject as one proportional bar - the run at a glance. */
function Disposition({ accept, watch, reject }: { accept: number; watch: number; reject: number }) {
  const total = accept + watch + reject || 1;
  const rows = [
    { k: "Accept", n: accept, c: C.pass },
    { k: "Watch", n: watch, c: C.watch },
    { k: "Reject", n: reject, c: C.reject },
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
            <dt className="flex items-center gap-2 text-graphite">
              <span className="h-2 w-2 rounded-full" style={{ background: r.c }} />
              {r.k}
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
      <aside className="no-print border-b border-rule bg-sheet lg:sticky lg:top-0 lg:h-screen lg:overflow-y-auto lg:border-b-0 lg:border-r">
        <div className="flex items-center justify-between px-4 py-4 lg:px-6 lg:pt-6">
          <Wordmark />
          <Link href="/" className="text-sm text-graphite hover:text-ink lg:hidden">
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
                "whitespace-nowrap rounded-ctl px-3 py-2 text-sm transition-colors",
                isOn(n.href)
                  ? "bg-ink font-semibold text-sheet"
                  : "text-graphite hover:bg-well hover:text-ink"
              )}
            >
              {n.label}
            </Link>
          ))}
        </nav>

        {s && m && (
          <div className="hidden px-6 pb-6 pt-8 lg:block">
            <h2 className="text-xs font-semibold text-graphite">This screening run</h2>
            <p className="wide mt-1 text-2xl font-extrabold">{s.parts.toLocaleString()}</p>
            <p className="text-sm text-graphite">components in {s.lots} lots</p>
            <div className="mt-4">
              <Disposition accept={s.accept} watch={s.watch} reject={s.reject} />
            </div>
            {s.lotsBreachingPda > 0 && (
              <Link href="/console/lots" className="mt-4 block rounded-ctl border border-reject/30 bg-reject/[0.06] px-3 py-2 text-sm text-reject hover:bg-reject/10">
                {s.lotsBreachingPda} lot{s.lotsBreachingPda > 1 ? "s" : ""} over the PDA gate
              </Link>
            )}
            <dl className="mt-6 space-y-1.5 border-t border-hair pt-4 text-xs">
              {[
                ["Bands", `Watch ${num(m.bands.watch, 1)}, reject ${num(m.bands.reject, 1)}`],
                ["Burn-in", `${m.stressTempC} °C, reads at ${m.readPoints.join(", ")} h`],
                ["Model", m.modelVersion],
                ["Data", "Simulated, seed 42"],
              ].map(([k, v]) => (
                <div key={k} className="grid grid-cols-[60px_1fr] gap-2">
                  <dt className="text-mute">{k}</dt>
                  <dd className="text-graphite">{v}</dd>
                </div>
              ))}
            </dl>
            <Link href="/" className="mt-6 inline-block text-sm text-graphite hover:text-ink">
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
