"use client";

import { useCallback, useEffect, useState } from "react";
import { AiSubject, AiText, aiApi } from "@/lib/ai-api";
import { ApiError } from "@/lib/screen-api";
import { cn } from "@/lib/utils";

/* THE AI SUMMARY CARD - one page, in plain language.
 *
 * The text is written by Mistral when the service has a key, otherwise by the
 * built-in explainer. Either way the badge says which, and whether the AI's
 * numbers were checked against the data. "Show the facts" lists exactly what
 * the text was allowed to use, so a reader can verify every figure. */

export function SourceBadge({ t }: { t: AiText }) {
  const ai = t.source === "mistral";
  return (
    <span
      className={cn("inline-flex items-center gap-1.5 rounded-ctl border px-2 py-0.5 text-[11px] font-bold",
        ai ? "border-[#6D4AB8] text-[#6D4AB8]" : "border-rule text-graphite")}
      title={ai ? "Written by Mistral; every number was checked against the data" : "Written by the built-in explainer"}
    >
      <span aria-hidden>{ai ? "✦" : "≡"}</span>
      {ai ? `AI · ${t.model} · numbers checked` : "Built-in summary"}
      {t.cached && <span className="font-normal opacity-70">· cached</span>}
    </span>
  );
}

export function AiSummary({
  subject, title = "In plain language", className, compact = false, watch,
}: {
  subject: AiSubject | null; title?: string; className?: string; compact?: boolean;
  /** Any value that changes when the page's data changes; the card re-asks
   *  (the service answers from its cache if the facts did not change). */
  watch?: unknown;
}) {
  const [t, setT] = useState<AiText | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [facts, setFacts] = useState(false);
  const key = subject ? JSON.stringify([subject, watch ?? null]) : "";

  const load = useCallback(async (refresh = false) => {
    if (!subject) return;
    setBusy(true);
    try {
      setT(await aiApi.summary(subject, refresh));
      setErr(null);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  useEffect(() => { load(false); }, [load]);

  if (!subject) return null;
  return (
    <div className={cn("rounded-card border border-[#6D4AB8]/35 bg-[#F6F3FC] px-4 py-3", className)}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-bold text-[#3E2A74]">✦ {title}</span>
        {t && <SourceBadge t={t} />}
        <button type="button" onClick={() => load(true)} disabled={busy}
          className="ml-auto text-xs font-semibold text-[#6D4AB8] underline-offset-2 hover:underline disabled:opacity-40">
          {busy ? "Writing…" : "Regenerate"}
        </button>
      </div>
      {err && <p className="mt-2 text-sm text-graphite">AI summary unavailable: {err}</p>}
      {!t && !err && <p className="mt-2 text-sm text-graphite">Writing the summary…</p>}
      {t && (
        <>
          <p className={cn("mt-2 text-ink", compact ? "text-sm" : "text-[15px] leading-6")}>{t.summary}</p>
          {t.next_steps.length > 0 && (
            <ul className="mt-2 list-disc space-y-0.5 pl-5 text-sm text-ink">
              {t.next_steps.map((s) => <li key={s}>{s}</li>)}
            </ul>
          )}
          {t.note && <p className="mt-2 text-xs text-graphite">{t.note}</p>}
          <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-graphite">
            <button type="button" onClick={() => setFacts((v) => !v)} className="font-semibold underline-offset-2 hover:underline">
              {facts ? "Hide the facts" : "Show the facts it used"}
            </button>
            {!t.ai.enabled && <span>AI off: set MISTRAL_API_KEY on the API to switch Mistral on.</span>}
            {t.ai.enabled && <span>Explains only; verdicts come from the screen, decisions from a person.</span>}
          </div>
          {facts && (
            <pre className="mt-2 max-h-64 overflow-auto rounded-ctl bg-sheet p-2 text-[11px] leading-4 text-graphite">
              {JSON.stringify(t.facts, null, 2)}
            </pre>
          )}
        </>
      )}
    </div>
  );
}
