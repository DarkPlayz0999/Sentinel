import { LAB } from "@/lib/lab-data";

/* Everything needed to reproduce the run, stated once. */
export function Footer() {
  const plate: [string, string][] = [
    ["Dataset", `${LAB.headline.parts.toLocaleString()} parts in ${LAB.headline.lots} lots, seed 42, simulated`],
    ["Burn-in", `125 °C, read at ${LAB.headline.readPoints.join(", ")} h`],
    ["Validation", "GroupKFold, grouped by lot"],
    ["Cost model", "A missed defect costs 100 scrapped parts, capped by a 5% PDA gate"],
    ["Features", "Defined once, in src/features.py"],
    ["Figures on this page", "web/scripts/export_lab_data.py"],
  ];

  return (
    <footer className="border-t border-rule bg-sheet">
      <div className="mx-auto grid max-w-[1200px] gap-10 px-4 py-12 sm:px-8 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <div>
          <p className="wide text-lg font-black tracking-[0.04em]">SENTINEL</p>
          <p className="mt-3 max-w-[46ch] text-sm text-graphite">
            Latent-defect screening for high-reliability component burn-in. Built for ISRO
            problem statement SIH26170. Every figure on this page is computed from the committed
            dataset by the shipped pipeline.
          </p>
          <p className="mt-4 text-sm font-semibold">
            An escape is a defective part that ships. It is the failure that matters.
          </p>
        </div>
        <dl className="grid gap-x-8 gap-y-3 sm:grid-cols-2">
          {plate.map(([k, v]) => (
            <div key={k}>
              <dt className="text-xs text-mute">{k}</dt>
              <dd className="text-sm">{v}</dd>
            </div>
          ))}
        </dl>
      </div>
    </footer>
  );
}
