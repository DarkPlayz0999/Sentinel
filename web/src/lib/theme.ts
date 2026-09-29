/* The palette, defined once. tailwind.config.ts imports it for class names
 * (text-ink, bg-paper, ...) and the SVG charts import it for fills, so a
 * colour change is one edit here.
 *
 * "The oven window": aluminium chamber walls, circuit-board green for text,
 * copper for time and anything you can drag, steel blue for the batch, and
 * three verdict inks that always travel with a shape. */

export const C = {
  paper: "#EEF1F4",    // page - brushed aluminium
  sheet: "#FFFFFF",    // surfaces
  well: "#F4F6F8",     // recessed areas, table heads, hover
  rule: "#D3D9DF",     // borders
  hair: "#E4E8EC",     // row dividers
  ink: "#0E3B36",      // text, primary action - solder-mask green
  graphite: "#4B5A5F", // secondary text
  mute: "#6F7C80",     // tertiary text, axis labels
  cobalt: "#3B78A6",   // the batch (lot population), links, focus
  copper: "#9C4F1F",   // time and interactive handles only
  oven: "#0B2D2A",     // the one dark panel: the oven window
  pass: "#1D7A55",
  watch: "#9A6A00",
  reject: "#C8322A",
} as const;

export const VERDICT_COLOR = {
  ACCEPT: C.pass,
  WATCH: C.watch,
  REJECT: C.reject,
} as const;
