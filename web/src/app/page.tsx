import { Footer } from "@/components/lab/Footer";
import { SiteHeader } from "@/components/site/header";
import { Hero } from "@/components/site/hero";
import {
  ConsoleCta, ExplainSection, ModuleASection, ModuleBSection, ProblemSection,
} from "@/components/site/sections";

/* The landing page is one argument in five moves:
 *
 *   the gap        a real component that passes every limit and should not have
 *   Module A       the reference is the lot, not the datasheet
 *   Module B       and we can see it coming at hour 24
 *   explainability with a sentence an engineer can check and overrule
 *   the console    now go look at all 2,100 of them
 *
 * Every figure on it is generated from the screened dataset by
 * web/scripts/export_lab_data.py. There is no marketing number here. */

export default function Home() {
  return (
    <div className="min-h-screen bg-lab-floor">
      <SiteHeader />
      <main>
        <Hero />
        <ProblemSection />
        <ModuleASection />
        <ModuleBSection />
        <ExplainSection />
        <ConsoleCta />
      </main>
      <Footer />
    </div>
  );
}
