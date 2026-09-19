"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { ConsoleState } from "@/components/console/shell";
import { PartDetail } from "@/components/console/detail";
import { Card, PageHead, Provenance, Risk, Stamp, num, unit } from "@/components/ui/kit";
import { Part, Verdict, useConsole } from "@/lib/console";
import { cn } from "@/lib/utils";

/* COMPONENTS - the dense engineering register.
 *
 * One row per part, not one card per part: an engineer scans a hundred rows
 * for the two that matter, and cards would put eight on a screen. The table
 * scrolls sideways on narrow viewports rather than reflowing into cards. */

type SortKey = "r" | "l2" | "wr" | "s" | "v168";

function Th({
  label, sortKey, sort, onSort, numeric,
}: {
  label: string; sortKey?: SortKey; sort: { k: SortKey; dir: 1 | -1 };
  onSort: (k: SortKey) => void; numeric?: boolean;
}) {
  const active = sortKey !== undefined && sort.k === sortKey;
  return (
    <th
      className={cn("sticky top-0 z-10", numeric && "n")}
      aria-sort={active ? (sort.dir === -1 ? "descending" : "ascending") : undefined}
    >
      {sortKey ? (
        <button onClick={() => onSort(sortKey)} className={cn("hover:text-ink", active && "text-ink")}>
          {label}
          <span aria-hidden className="ml-1">{active ? (sort.dir === -1 ? "↓" : "↑") : ""}</span>
        </button>
      ) : (
        label
      )}
    </th>
  );
}

function Inner() {
  const { data, error } = useConsole();
  const params = useSearchParams();
  const selected = params.get("id");

  const [q, setQ] = useState("");
  const [lot, setLot] = useState("ALL");
  const [verdict, setVerdict] = useState<"ALL" | Verdict>("ALL");
  const [escapesOnly, setEscapesOnly] = useState(false);
  const [pi, setPi] = useState(0);
  const [sort, setSort] = useState<{ k: SortKey; dir: 1 | -1 }>({ k: "r", dir: -1 });
  const [limit, setLimit] = useState(150);

  const rows = useMemo(() => {
    if (!data) return [];
    const needle = q.trim().toUpperCase();
    const out = data.parts.filter((p) => {
      if (needle && !p.s.toUpperCase().includes(needle)) return false;
      if (lot !== "ALL" && p.l !== lot) return false;
      if (verdict !== "ALL" && p.v !== verdict) return false;
      // An escape passes every static limit but the screen flags it - the
      // population this project exists to catch.
      if (escapesOnly && !(p.st === 0 && p.v !== "ACCEPT")) return false;
      return true;
    });
    const val = (p: Part) =>
      sort.k === "s" ? p.s : sort.k === "v168" ? (p.m[pi][3] ?? -Infinity) : (p[sort.k] ?? -Infinity);
    return out.sort((a, b) => {
      const x = val(a), y = val(b);
      if (typeof x === "string" || typeof y === "string") return String(x).localeCompare(String(y)) * sort.dir;
      return ((x as number) - (y as number)) * sort.dir;
    });
  }, [data, q, lot, verdict, escapesOnly, sort, pi]);

  if (!data) return <ConsoleState error={error} />;

  const part = selected ? data.parts.find((p) => p.s === selected) : undefined;
  if (selected && !part) {
    return (
      <Card className="p-6">
        <p className="text-base">
          No component with serial <strong>{selected}</strong> in this screening run.
        </p>
        <Link href="/console/components" className="link mt-2 inline-block">Back to all components</Link>
      </Card>
    );
  }
  if (part) return <PartDetail part={part} data={data} />;

  const { meta } = data;
  const pm = meta.params[pi];
  const onSort = (k: SortKey) =>
    setSort((s) => (s.k === k ? { k, dir: s.dir === -1 ? 1 : -1 } : { k, dir: -1 }));
  const escapes = data.parts.filter((p) => p.st === 0 && p.v !== "ACCEPT").length;
  const filtered = q || lot !== "ALL" || verdict !== "ALL" || escapesOnly;

  return (
    <>
      <PageHead
        title="Components"
        lede={`Every screened part, highest risk first. ${rows.length.toLocaleString()} of ${data.parts.length.toLocaleString()} shown.`}
      />

      {/* ---------------------------------------------------- filter bar */}
      <Card className="mb-4 flex flex-wrap items-end gap-x-4 gap-y-3 px-4 py-3">
        <label className="min-w-[160px] flex-1">
          <span className="mb-1 block text-xs text-graphite">Search serial</span>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="L04-0348" className="input w-full" />
        </label>
        <label>
          <span className="mb-1 block text-xs text-graphite">Lot</span>
          <select value={lot} onChange={(e) => setLot(e.target.value)} className="input">
            <option value="ALL">All lots</option>
            {data.lots.map((l) => <option key={l.lot} value={l.lot}>{l.lot}</option>)}
          </select>
        </label>
        <label>
          <span className="mb-1 block text-xs text-graphite">Decision</span>
          <select value={verdict} onChange={(e) => setVerdict(e.target.value as Verdict | "ALL")} className="input">
            <option value="ALL">All decisions</option>
            <option value="REJECT">Reject</option>
            <option value="WATCH">Watch</option>
            <option value="ACCEPT">Accept</option>
          </select>
        </label>
        <label>
          <span className="mb-1 block text-xs text-graphite">Readings shown</span>
          <select value={pi} onChange={(e) => setPi(Number(e.target.value))} className="input">
            {meta.params.map((p, i) => <option key={p.name} value={i}>{p.name}</option>)}
          </select>
        </label>
        <label className="flex cursor-pointer items-center gap-2 pb-2 text-sm">
          <input type="checkbox" checked={escapesOnly} onChange={(e) => setEscapesOnly(e.target.checked)}
            className="h-4 w-4 accent-reject" />
          Escapes only <span className="text-graphite">({escapes})</span>
        </label>
        {filtered && (
          <button
            onClick={() => { setQ(""); setLot("ALL"); setVerdict("ALL"); setEscapesOnly(false); }}
            className="btn-quiet ml-auto"
          >
            Clear filters
          </button>
        )}
      </Card>

      {/* -------------------------------------------------------- table */}
      <Card className="overflow-x-auto">
        <table className="tbl min-w-[1000px]">
          <thead>
            <tr>
              <Th label="Component" sortKey="s" sort={sort} onSort={onSort} />
              <Th label="Lot" sort={sort} onSort={onSort} />
              <Th label={`${pm.name} 0 h`} sort={sort} onSort={onSort} numeric />
              <Th label="24 h" sort={sort} onSort={onSort} numeric />
              <Th label="96 h" sort={sort} onSort={onSort} numeric />
              <Th label="168 h" sortKey="v168" sort={sort} onSort={onSort} numeric />
              <Th label="Lot deviation" sortKey="l2" sort={sort} onSort={onSort} numeric />
              <Th label="Slope ratio" sortKey="wr" sort={sort} onSort={onSort} numeric />
              <Th label="Datasheet" sort={sort} onSort={onSort} />
              <Th label="Risk" sortKey="r" sort={sort} onSort={onSort} />
              <Th label="Decision" sort={sort} onSort={onSort} />
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, limit).map((p) => {
              const v168 = p.m[pi][3];
              const breach = v168 !== null && v168 > pm.usl;
              const escape = p.st === 0 && p.v !== "ACCEPT";
              return (
                <tr key={p.s} className={cn(escape && "bg-reject/[0.03]")}>
                  <td><Link href={`/console/components?id=${p.s}`} className="link">{p.s}</Link></td>
                  <td className="text-graphite">{p.l}</td>
                  {[0, 1, 2].map((ri) => (
                    <td key={ri} className="n text-graphite">{num(p.m[pi][ri], 2)}</td>
                  ))}
                  <td className={cn("n font-semibold", breach && "text-reject")}>{num(v168, 2)}</td>
                  <td className={cn("n font-semibold",
                    p.l2 >= 6 ? "text-reject" : p.l2 >= 4.5 ? "text-watch" : "text-graphite")}>
                    {num(p.l2, 2)}σ
                  </td>
                  <td className={cn("n", p.wr !== null && p.wr > 1 ? "text-reject" : "text-graphite")}>
                    {p.wr === null ? "—" : `${num(p.wr, 2)}×`}
                  </td>
                  <td><Stamp v={p.st ? "BREACH" : "PASS"} /></td>
                  <td><Risk r={p.r} v={p.v} /></td>
                  <td><Stamp v={p.v} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>

        {rows.length === 0 && (
          <div className="px-4 py-8 text-center text-sm text-graphite">
            No component matches these filters.{" "}
            <button onClick={() => { setQ(""); setLot("ALL"); setVerdict("ALL"); setEscapesOnly(false); }} className="link">
              Clear filters
            </button>
          </div>
        )}
        {rows.length > limit && (
          <div className="border-t border-hair px-4 py-3 text-center">
            <button onClick={() => setLimit((l) => l + 300)} className="btn-quiet">
              Show 300 more ({(rows.length - limit).toLocaleString()} left)
            </button>
          </div>
        )}
      </Card>

      <p className="mt-3 max-w-prose text-sm text-graphite">
        Readings are in {unit(pm.unit)}; the datasheet limit is {pm.usl} {unit(pm.unit)}. Tinted
        rows are escapes: parts that pass every datasheet limit at 168 h and would ship under
        traditional screening, but which SENTINEL flags against their own lot.
      </p>

      <Provenance modelVersion={meta.modelVersion} source={meta.generatedFrom} />
    </>
  );
}

export default function ComponentsPage() {
  return (
    <Suspense fallback={<ConsoleState />}>
      <Inner />
    </Suspense>
  );
}
