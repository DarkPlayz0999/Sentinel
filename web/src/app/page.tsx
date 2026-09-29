import { Footer } from "@/components/site/footer";
import { SiteHeader } from "@/components/site/header";
import { Hero } from "@/components/site/hero";
import { OvenSection } from "@/components/site/oven";
import { CarefulnessSection } from "@/components/site/careful";
import {
  ConsoleCta, DetectionSection, ForecastSection, GapSection, ReasonsSection,
} from "@/components/site/sections";

/* The landing page is one argument in five moves:
 *
 *   the hero       three chips, two tests: only the hidden defect splits them
 *   the gap        a real component that passes every limit and should not have
 *   Module A       the reference is the lot, not the datasheet
 *   Module B       and it can be triaged at hour 24
 *   the oven       drag a whole batch through the week
 *   carefulness    you set the catch / over-flag trade-off yourself
 *   reasons        with a sentence an engineer can check and overrule
 *   the console    now go look at all of them
 *
 * Every figure is generated from the screened dataset by
 * web/scripts/export_lab_data.py. There is no marketing number here. */

export default function Home() {
  return (
    <>
      <SiteHeader />
      <main>
        <Hero />
        <GapSection />
        <DetectionSection />
        <ForecastSection />
        <OvenSection />
        <CarefulnessSection />
        <ReasonsSection />
        <ConsoleCta />
      </main>
      <Footer />
    </>
  );
}
