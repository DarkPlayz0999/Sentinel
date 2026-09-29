"use client";

import { ReactNode, useEffect, useId, useRef, useState } from "react";

/* Jargon, explained in place. A dotted underline marks a word that has a
 * plain-English definition; click, tap or Enter opens it, Escape or a click
 * elsewhere closes it. Never hover-only, so it works on a phone. */

export const GLOSSARY = {
  "burn-in": "Running a new chip hot (125 °C) for about a week before it flies. Weak chips tend to fail early, so they fail here instead of in orbit.",
  "datasheet limit": "The maximum value the manufacturer allows. Below it, a traditional test says PASS, no matter how odd the chip looks.",
  lot: "A batch of chips made together. Chips in one batch should behave alike, so the batch is the best yardstick for any one chip.",
  "latent defect": "A hidden flaw. The chip passes every test today but is quietly getting worse and will fail early in service.",
  sigma: "σ (sigma) measures how far a chip is from the middle of its batch, in units of the batch's normal spread. 1σ is ordinary; 6σ is extremely unusual.",
  drift: "How much a reading changed during burn-in. Healthy chips barely move; a defective one keeps climbing.",
  "risk score": "0 to 100. A weighted sum of five named checks, so you can always see which check pushed a chip up.",
  watch: "Ships, but its serial number is flagged for a second look. Costs nothing from the batch's reject allowance.",
  reject: "Pulled from the batch. Every reject carries a written reason an inspector can check and overrule.",
  pda: "Percent Defective Allowable. If more than 5% of a batch is rejected, the whole batch goes to engineering review.",
  forecast: "A prediction of the 168-hour reading from the first 24 hours, so the worst chips can come out of the oven six days early.",
  "safety slope": "The fastest a reading may rise and still be trusted. A chip forecast to climb faster is pulled at hour 24.",
  overkill: "A good chip wrongly pulled. Expensive, but survivable - unlike a bad chip that ships.",
  recall: "Of all the truly defective chips, the share the screen caught.",
  "reason code": "A numbered, written reason (R-101 to R-601) attached to every flag, stating the chip's value and its batch's value.",
} as const;

export type TermKey = keyof typeof GLOSSARY;

export function Term({ t, children }: { t: TermKey; children?: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  return (
    <span ref={ref} className="relative inline">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
        className="cursor-help underline decoration-copper decoration-dotted decoration-2 underline-offset-[5px] hover:text-copper"
      >
        {children ?? t}
      </button>
      {open && (
        <span
          id={id}
          role="note"
          className="fixed inset-x-4 bottom-4 z-50 block rounded-card sm:absolute sm:inset-x-auto sm:bottom-auto sm:left-0 sm:top-full sm:mt-2 sm:w-[320px] border border-ink bg-sheet p-3 text-left text-sm font-normal normal-case leading-snug tracking-normal text-ink shadow-[4px_4px_0_0_#0E3B36]"
        >
          <span className="mb-1 block font-bold capitalize">{t}</span>
          {GLOSSARY[t]}
        </span>
      )}
    </span>
  );
}
