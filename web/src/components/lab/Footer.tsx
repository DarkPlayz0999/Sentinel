import { LAB } from "@/lib/lab-data";

/** The plate on the side of the rack. Everything needed to reproduce the run. */
export function Footer() {
  const plate: [string, string][] = [
    ["Instrument", "SENTINEL screening pipeline"],
    ["Modules", "A · dynamic outlier   B · drift forecast   Fusion · verdict"],
    ["Dataset", `${LAB.headline.parts.toLocaleString()} parts · ${LAB.headline.lots} lots · seed 42`],
    ["Read points", `${LAB.headline.readPoints.join(" / ")} h at 125 °C`],
    ["Validation", "GroupKFold, grouped by lot"],
    ["Cost model", "C_FN / C_FP = 100, capped by a 5 % PDA gate"],
    ["Location", "src/features.py — the only place a feature is defined"],
    ["Figures on this page", "web/scripts/export_lab_data.py"],
  ];

  return (
    <footer className="grid-paper border-t border-lab-rule bg-lab-panel">
      <div className="mx-auto max-w-[1400px] px-4 py-10 sm:px-6">
        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
          <div>
            <div className="flex items-center gap-3">
              <div className="grid h-8 w-8 place-items-center border border-lab-ink bg-lab-ink">
                <span className="font-mono text-[12px] font-bold text-lab-panel">S</span>
              </div>
              <div>
                <div className="font-mono text-[15px] font-bold tracking-[0.2em] text-lab-ink">
                  SENTINEL
                </div>
                <div className="label mt-1">Component Reliability Lab · Bay 03</div>
              </div>
            </div>
            <p className="mt-4 max-w-[46ch] text-[12.5px] leading-relaxed text-lab-dim">
              AI-driven anomaly detection in component burn-in and screening. Parts are judged
              against their own lot, forecast from their first 24 hours, and dispositioned with a
              reason an inspector can sign.
            </p>
            <p className="mt-4 font-mono text-[10px] leading-relaxed text-lab-faint">
              Cell 03-B is a scripted walkthrough. Every population figure, histogram, limit and
              recall number on this page is computed from the committed dataset and the shipped
              scorer — regenerate with{" "}
              <span className="text-lab-dim">python web/scripts/export_lab_data.py</span>.
            </p>
          </div>

          <dl className="grid grid-cols-1 gap-px self-start border border-lab-rule bg-lab-rule sm:grid-cols-2">
            {plate.map(([k, v]) => (
              <div key={k} className="bg-lab-card px-3 py-2">
                <dt className="label">{k}</dt>
                <dd className="readout mt-1 text-[11.5px] leading-snug text-lab-ink">{v}</dd>
              </div>
            ))}
          </dl>
        </div>

        <div className="mt-8 flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-lab-hair pt-4">
          <span className="label">Calibration due 2026-12-01</span>
          <span className="label">Record retention 10 y</span>
          <span className="label">Rev 1.0</span>
          <span className="label ml-auto">
            Escape = a defective part that ships. It is the only failure that matters.
          </span>
        </div>
      </div>
    </footer>
  );
}
