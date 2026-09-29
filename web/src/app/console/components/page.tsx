"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { ConsoleState } from "@/components/console/shell";
import { PartDetail } from "@/components/console/detail";
import {
  Meter, Panel, PanelHead, ProvenanceNote, SectionHead, VerdictChip, num, pct, unit,
} from "@/components/ui/kit";
import { Part, Verdict, useConsole } from "@/lib/console";
import { cn } from "@/lib/utils";

/* COMPONENTS — the dense engineering table.
 *
 * One row per part, not one card per part. A reliability engineer scans a
 * hundred rows looking for the two that matter; cards would put eight on a
 * screen. Row height is 26 px, numbers are tabular, and the table scrolls
 * horizontally on narrow viewports rather than reflowing into unusable cards. */

type SortKey = "r" | "l2" | "wr" | "s" | "v168";

function Th({
  label, sortKey, active, dir, onSort, align = "left", width,
}: {
  label: string; sortKey?: SortKey; active?: boolean; dir?: 1 | -1;
  onSort?: (k: SortKey) => void; align?: "left" | "right"; width?: string;
}) {
  return (
    <th
      style={width ? { width } : undefined}
      className={cn(
        "sticky top-0 z-10 whitespace-nowrap border-b border-lab-rule bg-lab-panel px-2.5 py-2 font-mono text-[9px] uppercase tracking-label text-lab-faint",
        align === "right" ? "text-right" : "text-left",
        sortKey && "cursor-pointer select-none hover:text-lab-ink"
      )}
      onClick={sortKey && onSort ? () => onSort(sortKey) : undefined}
      aria-sort={active ? (dir === -1 ? "descending" : "ascending") : undefined}
    >
      {label}
      {active && <span className="ml-1 text-lab-ink">{dir === -1 ? "▾" : "▴"}</span>}
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
      // "escape" = passes every static limit but the screen flags it. The
      // population this project exists to catch.
      if (escapesOnly && !(p.st === 0 && p.v !== "ACCEPT")) return false;
      return true;
    });
    const val = (p: Part) =>
      sort.k === "s" ? p.s : sort.k === "v168" ? (p.m[pi][3] ?? -Infinity) : (p[sort.k] ?? -Infinity);
    return out.sort((a, b) => {
      const x = val(a), y = val(b);
      if (typeof x === "string" || typeof y === "string") {
        return String(x).localeCompare(String(y)) * sort.dir;
      }
      return ((x as number) - (y as number)) * sort.dir;
    });
  }, [data, q, lot, verdict, escapesOnly, sort, pi]);

  if (!data) return <ConsoleState error={error} />;

  const part = selected ? data.parts.find((p) => p.s === selected) : undefined;
  if (selected && !part) {
    return (
      <Panel className="p-6">
        <p className="font-mono text-[11px] text-lab-dim">
          No component with serial <span className="readout text-lab-ink">{selected}</span> in this
          screening run.{" "}
          <Link href="/console/components" className="text-sig-blue hover:underline">
            Back to the register
          </Link>
          .
        </p>
      </Panel>
    );
  }
  if (part) return <PartDetail part={part} data={data} />;

  const { meta } = data;
  const pm = meta.params[pi];
  const setSortKey = (k: SortKey) =>
    setSort((s) => (s.k === k ? { k, dir: s.dir === -1 ? 1 : -1 } : { k, dir: -1 }));

  const escapes = data.parts.filter((p) => p.st === 0 && p.v !== "ACCEPT").length;

  return (
    <div className="space-y-5">
      <SectionHead
        index="10"
        title="Component register"
        note={`${rows.length.toLocaleString()} of ${data.parts.length.toLocaleString()} components shown`}
      />

      {/* ---------------------------------------------------- filter bar */}
      <Panel className="flex flex-wrap items-end gap-x-4 gap-y-3 px-3 py-2.5">
        <label className="min-w-[150px] flex-1">
          <span className="label mb-1 block">Search serial</span>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="L04-0348"
            className="readout w-full border border-lab-rule bg-lab-card px-2 py-1.5 text-[11px] text-lab-ink outline-none placeholder:text-lab-faint focus:border-sig-blue"
          />
        </label>

        <label>
          <span className="label mb-1 block">Lot</span>
          <select
            value={lot}
            onChange={(e) => setLot(e.target.value)}
            className="readout border border-lab-rule bg-lab-card px-2 py-1.5 text-[11px] text-lab-ink outline-none focus:border-sig-blue"
          >
            <option value="ALL">ALL</option>
            {data.lots.map((l) => (
              <option key={l.lot} value={l.lot}>{l.lot}</option>
            ))}
          </select>
        </label>

        <label>
          <span className="label mb-1 block">Decision</span>
          <select
            value={verdict}
            onChange={(e) => setVerdict(e.target.value as Verdict | "ALL")}
            className="readout border border-lab-rule bg-lab-card px-2 py-1.5 text-[11px] text-lab-ink outline-none focus:border-sig-blue"
          >
            {["ALL", "REJECT", "WATCH", "ACCEPT"].map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
        </label>

        <label>
          <span className="label mb-1 block">Parameter shown</span>
          <select
            value={pi}
            onChange={(e) => setPi(Number(e.target.value))}
            className="readout border border-lab-rule bg-lab-card px-2 py-1.5 text-[11px] text-lab-ink outline-none focus:border-sig-blue"
          >
            {meta.params.map((p, i) => (
              <option key={p.name} value={i}>{p.name}</option>
            ))}
          </select>
        </label>

        <label className="flex cursor-pointer items-center gap-2 pb-1.5">
          <input
            type="checkbox"
            checked={escapesOnly}
            onChange={(e) => setEscapesOnly(e.target.checked)}
            className="h-3.5 w-3.5 accent-sig-red"
          />
          <span className="font-mono text-[10px] text-lab-ink">
            Escapes only
            <span className="ml-1.5 text-lab-faint">
              (static PASS, SENTINEL flags — {escapes})
            </span>
          </span>
        </label>

        {(q || lot !== "ALL" || verdict !== "ALL" || escapesOnly) && (
          <button
            onClick={() => { setQ(""); setLot("ALL"); setVerdict("ALL"); setEscapesOnly(false); }}
            className="ml-auto border border-lab-rule bg-lab-card px-2.5 py-1.5 font-mono text-[9px] uppercase tracking-label text-lab-dim hover:bg-lab-panel"
          >
            Clear filters
          </button>
        )}
      </Panel>

      {/* -------------------------------------------------------- table */}
      <Panel className="overflow-x-auto">
        <PanelHead
          title={`Screened components — ${pm.name}`}
          meta={`readings in ${unit(pm.unit)} · USL ${pm.usl} ${unit(pm.unit)} · sorted by ${sort.k}`}
        />
        <table className="w-full min-w-[980px] border-collapse">
          <thead>
            <tr>
              <Th label="Component" sortKey="s" active={sort.k === "s"} dir={sort.dir} onSort={setSortKey} width="118px" />
              <Th label="Lot" width="54px" />
              <Th label="0 h" align="right" />
              <Th label="24 h" align="right" />
              <Th label="96 h" align="right" />
              <Th label="168 h" sortKey="v168" active={sort.k === "v168"} dir={sort.dir} onSort={setSortKey} align="right" />
              <Th label="Dynamic σ" sortKey="l2" active={sort.k === "l2"} dir={sort.dir} onSort={setSortKey} align="right" />
              <Th label="Predicted drift" sortKey="wr" active={sort.k === "wr"} dir={sort.dir} onSort={setSortKey} align="right" />
              <Th label="Static" width="64px" />
              <Th label="Risk" sortKey="r" active={sort.k === "r"} dir={sort.dir} onSort={setSortKey} width="130px" />
              <Th label="Decision" width="104px" />
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, limit).map((p) => {
              const v168 = p.m[pi][3];
              const breach = v168 !== null && v168 > pm.usl;
              const escape = p.st === 0 && p.v !== "ACCEPT";
              return (
                <tr
                  key={p.s}
                  className={cn(
                    "border-b border-lab-hair hover:bg-lab-panel",
                    escape && "bg-sig-red/[0.025]"
                  )}
                >
                  <td className="px-2.5 py-[5px]">
                    <Link
                      href={`/console/components?id=${p.s}`}
                      className="readout text-[11px] font-semibold text-sig-blue hover:underline"
                    >
                      {p.s}
                    </Link>
                  </td>
                  <td className="readout px-2.5 py-[5px] text-[10px] text-lab-dim">{p.l}</td>
                  {[0, 1, 2].map((ri) => (
                    <td key={ri} className="readout px-2.5 py-[5px] text-right text-[10px] text-lab-dim">
                      {num(p.m[pi][ri], 2)}
                    </td>
                  ))}
                  <td
                    className={cn(
                      "readout px-2.5 py-[5px] text-right text-[10px] font-semibold",
                      breach ? "text-sig-red" : "text-lab-ink"
                    )}
                  >
                    {num(v168, 2)}
                  </td>
                  <td
                    className={cn(
                      "readout px-2.5 py-[5px] text-right text-[10px] font-semibold",
                      p.l2 >= 6 ? "text-sig-red" : p.l2 >= 4.5 ? "text-sig-amber" : "text-lab-dim"
                    )}
                  >
                    {num(p.l2, 2)}σ
                  </td>
                  <td
                    className={cn(
                      "readout px-2.5 py-[5px] text-right text-[10px]",
                      p.wr !== null && p.wr > 1 ? "text-sig-red" : "text-lab-dim"
                    )}
                  >
                    {p.wr === null ? "—" : `${num(p.wr, 2)}×`}
                  </td>
                  <td className="px-2.5 py-[5px]">
                    <span
                      className={cn(
                        "font-mono text-[9px] font-bold uppercase tracking-label",
                        p.st ? "text-sig-red" : "text-sig-green"
                      )}
                    >
                      {p.st ? "BREACH" : "PASS"}
                    </span>
                  </td>
                  <td className="px-2.5 py-[5px]">
                    <div className="flex items-center gap-2">
                      <span className="readout w-8 text-[10px] font-semibold">{num(p.r, 1)}</span>
                      <span className="w-[72px]">
                        <Meter
                          value={p.r}
                          max={100}
                          height={4}
                          color={p.v === "REJECT" ? "#A81E12" : p.v === "WATCH" ? "#9A5B06" : "#186B45"}
                        />
                      </span>
                    </div>
                  </td>
                  <td className="px-2.5 py-[5px]">
                    <VerdictChip v={p.v} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        {rows.length === 0 && (
          <p className="px-4 py-6 text-center font-mono text-[10px] text-lab-faint">
            No component matches these filters.
          </p>
        )}
        {rows.length > limit && (
          <div className="border-t border-lab-hair px-3 py-2.5 text-center">
            <button
              onClick={() => setLimit((l) => l + 300)}
              className="border border-lab-rule bg-lab-card px-3 py-1.5 font-mono text-[10px] uppercase tracking-label text-lab-ink hover:bg-lab-panel"
            >
              Show 300 more — {(rows.length - limit).toLocaleString()} remaining
            </button>
          </div>
        )}
      </Panel>

      <p className="font-mono text-[9px] leading-relaxed text-lab-faint">
        Rows tinted red are <span className="font-bold text-lab-dim">escapes</span>: components
        that pass every static datasheet limit at 168 h and would ship under traditional
        screening, but which SENTINEL flags as abnormal relative to their own lot.
      </p>

      <ProvenanceNote modelVersion={meta.modelVersion} source={meta.generatedFrom} />
    </div>
  );
}

export default function ComponentsPage() {
  return (
    <Suspense fallback={<ConsoleState />}>
      <Inner />
    </Suspense>
  );
}
