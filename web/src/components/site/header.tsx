import Link from "next/link";
import { Wordmark } from "@/components/console/shell";

const SECTIONS = [
  { id: "gap", label: "Is it legal?" },
  { id: "detection", label: "Is it normal?" },
  { id: "forecast", label: "Where is it heading?" },
  { id: "careful", label: "Try it" },
];

export function SiteHeader() {
  return (
    <header className="border-b border-rule bg-paper/95">
      <div className="mx-auto flex h-16 max-w-[1200px] items-center gap-6 px-4 sm:px-8">
        <Wordmark />
        <nav className="hidden gap-1 md:flex" aria-label="Sections">
          {SECTIONS.map((s) => (
            <a key={s.id} href={`#${s.id}`}
              className="rounded-ctl px-3 py-2 text-sm text-graphite transition-colors hover:bg-sheet hover:text-ink">
              {s.label}
            </a>
          ))}
        </nav>
        <Link href="/console" className="btn-primary ml-auto">Open the console</Link>
      </div>
    </header>
  );
}
