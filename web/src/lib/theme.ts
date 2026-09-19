/* The palette, defined once. tailwind.config.ts imports it for class names
 * (text-ink, bg-paper, ...) and the SVG charts import it for fills, so a
 * colour change is one edit here.
 *
 * Drafting-film paper, Prussian ink, and three stamp inks. Colour carries
 * STATUS and the lot population, nothing else. */

export const C = {
  paper: "#EEF2F0",    // page - cool vellum
  sheet: "#FFFFFF",    // surfaces
  well: "#F5F7F6",     // recessed areas, table heads, hover
  rule: "#D2D9D6",     // borders
  hair: "#E3E8E6",     // row dividers
  ink: "#14213A",      // text, primary action
  graphite: "#566174", // secondary text
  mute: "#7B8596",     // tertiary text, axis labels
  cobalt: "#2B55C9",   // the lot population, links, focus
  pass: "#1B7549",
  watch: "#A6670A",
  reject: "#C22A1D",
} as const;

export const VERDICT_COLOR = {
  ACCEPT: C.pass,
  WATCH: C.watch,
  REJECT: C.reject,
} as const;
