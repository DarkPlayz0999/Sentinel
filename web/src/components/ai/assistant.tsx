"use client";

import { usePathname } from "next/navigation";
import { FormEvent, useEffect, useRef, useState } from "react";
import { AiStatus, AiSubject, AiText, aiApi } from "@/lib/ai-api";
import { ApiError } from "@/lib/screen-api";
import { SourceBadge } from "@/components/ai/ai-summary";
import { cn } from "@/lib/utils";

/* ASK SENTINEL AI - on every console page.
 *
 * The assistant knows which page you are on and answers from that page's
 * facts only (the same fact sheet the summary cards use). It cannot see
 * anything the page cannot, it never decides a verdict, and an answer that
 * quotes a number not in the data is thrown away before you see it. */

function subjectFor(path: string, search: URLSearchParams): { s: AiSubject; label: string } {
  if (path.startsWith("/console/lab") && search.get("sim"))
    return { s: { context: "simulation", id: search.get("sim") }, label: "this simulation" };
  if (path.startsWith("/console/realdata")) {
    const set = search.get("set") === "mosfet" ? "mosfet" : "capacitors";
    return { s: { context: "realdata", id: set }, label: `the real NASA ${set === "mosfet" ? "MOSFET" : "capacitor"} data` };
  }
  if (path.startsWith("/console/benchmark"))
    return { s: { context: "experiment", id: search.get("exp") }, label: "the latest benchmark" };
  if (path.startsWith("/console/agents"))
    return { s: { context: "workflow", id: search.get("wf") }, label: "the latest agent workflow" };
  if (path.startsWith("/console/reports") && search.get("id"))
    return { s: { context: "part", serial: search.get("id") }, label: `part ${search.get("id")}` };
  if (path.startsWith("/console/lots") && search.get("lot"))
    return { s: { context: "lot", lot: search.get("lot") }, label: `batch ${search.get("lot")}` };
  return { s: { context: "overview" }, label: "the screening results" };
}

const SUGGEST: Record<string, string[]> = {
  overview: ["Which chips should I look at first?", "Why do chips that pass the datasheet get rejected?", "Which batch is worst?"],
  simulation: ["Which part is faulty and why?", "Explain the evidence score", "Did the replacement fix it?"],
  experiment: ["How good is Sentinel here?", "Where does it miss faults?", "Why is accuracy not shown?"],
  workflow: ["What did each agent do?", "Is anything critical?"],
  part: ["Why was this part flagged?", "Is it inside the datasheet limits?"],
  lot: ["Is this batch OK to ship?", "Which parts drive the rejects?"],
  realdata: ["Which parts reached end of life?", "Can Sentinel warn early on this data?", "Why is the first month special?"],
};

interface Msg { role: "user" | "ai"; text: string; t?: AiText; err?: boolean }

export function Assistant() {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState<URLSearchParams>(new URLSearchParams());
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setSearch(new URLSearchParams(window.location.search));
  }, [path, open]);
  useEffect(() => {
    if (open && !status) aiApi.status().then(setStatus).catch(() => undefined);
  }, [open, status]);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

  const { s, label } = subjectFor(path, search);

  const send = async (text: string) => {
    const question = text.trim();
    if (!question || busy) return;
    setMsgs((m) => [...m, { role: "user", text: question }]);
    setQ("");
    setBusy(true);
    try {
      const t = await aiApi.ask(s, question);
      setMsgs((m) => [...m, { role: "ai", text: t.text, t }]);
    } catch (e) {
      setMsgs((m) => [...m, { role: "ai", text: e instanceof ApiError ? e.message : String(e), err: true }]);
    } finally {
      setBusy(false);
    }
  };

  const submit = (e: FormEvent) => { e.preventDefault(); send(q); };

  return (
    <div className="no-print fixed bottom-4 right-4 z-50 flex flex-col items-end">
      {open && (
        <div className="mb-3 flex h-[min(560px,75vh)] w-[min(400px,calc(100vw-2rem))] flex-col overflow-hidden rounded-card border border-[#6D4AB8]/40 bg-sheet shadow-xl">
          <div className="flex items-center gap-2 border-b border-hair bg-[#3E2A74] px-3 py-2.5 text-white">
            <span className="text-sm font-bold">✦ Ask SENTINEL AI</span>
            <span className="text-xs opacity-80">about {label}</span>
            <button type="button" onClick={() => setOpen(false)} className="ml-auto text-sm opacity-80 hover:opacity-100" aria-label="Close the assistant">✕</button>
          </div>
          <div className="flex-1 space-y-3 overflow-y-auto px-3 py-3 text-sm">
            {msgs.length === 0 && (
              <div className="space-y-2 text-graphite">
                <p>Ask anything about {label}. Answers use only the data on this page; any answer quoting a number that is not in the data is discarded.</p>
                {status && !status.enabled && (
                  <p className="rounded-ctl bg-well px-2 py-1.5 text-xs">AI is off on the service ({status.how_to_enable}). You will get the built-in summary instead of a free answer.</p>
                )}
                {status?.enabled && (
                  <p className="rounded-ctl bg-well px-2 py-1.5 text-xs">Using {status.model}. This page&apos;s facts are sent to the AI service.</p>
                )}
                <div className="flex flex-wrap gap-1.5 pt-1">
                  {(SUGGEST[s.context] ?? []).map((x) => (
                    <button key={x} type="button" onClick={() => send(x)}
                      className="rounded-full border border-[#6D4AB8]/40 px-2.5 py-1 text-xs text-[#3E2A74] hover:bg-[#F6F3FC]">
                      {x}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={cn("max-w-[92%] rounded-card px-3 py-2",
                m.role === "user" ? "ml-auto bg-ink text-sheet" : m.err ? "bg-reject/10 text-ink" : "bg-[#F6F3FC] text-ink")}>
                <p className="whitespace-pre-line">{m.text}</p>
                {m.t && (
                  <div className="mt-1.5 space-y-1">
                    <SourceBadge t={m.t} />
                    {m.t.note && <p className="text-[11px] text-graphite">{m.t.note}</p>}
                  </div>
                )}
              </div>
            ))}
            {busy && <p className="text-xs text-graphite">Thinking…</p>}
            <div ref={end} />
          </div>
          <form onSubmit={submit} className="flex gap-2 border-t border-hair p-2">
            <input value={q} onChange={(e) => setQ(e.target.value)} maxLength={500}
              placeholder="Ask in plain words…" className="min-w-0 flex-1 rounded-ctl border border-rule px-2.5 py-2 text-sm" />
            <button type="submit" disabled={busy || !q.trim()}
              className="rounded-ctl bg-[#3E2A74] px-3 py-2 text-sm font-bold text-white disabled:opacity-40">Ask</button>
          </form>
        </div>
      )}
      <button type="button" onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 rounded-full bg-[#3E2A74] px-4 py-3 text-sm font-bold text-white shadow-lg hover:opacity-95"
        aria-expanded={open}>
        <span aria-hidden>✦</span> {open ? "Close" : "Ask SENTINEL AI"}
      </button>
    </div>
  );
}
