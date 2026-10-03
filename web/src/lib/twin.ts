/**
 * Burn-in tray geometry and live lot-relative state.
 *
 * This module turns the screened rows in /data/console.json into the numbers
 * the 3D oven needs at an arbitrary point in the 168 h soak. It computes NO
 * verdicts and NO risk. The verdict a part carries (`Part.v`) and its risk
 * (`Part.r`) come from src/pipeline.py via the export script and are passed
 * through untouched - see the note in lib/console.ts.
 *
 * What IS computed here is the same class of quantity console.ts already
 * derives in the browser: lot percentiles and a robust z, as a pure function
 * of the committed measurements. Both follow the repo's rules - currents are
 * lognormal so the statistics are taken in log space, and spread is
 * 1.4826 * MAD, never a standard deviation.
 *
 * Between read points a value is interpolated, log-linearly for currents.
 * Interpolation is a DRAWING convenience for the time scrubber, not a
 * measurement: only 0, 24, 96 and 168 h were ever measured.
 */

import { Meta, Part, median, quantile, robustSigma } from "@/lib/console";

export const TRAY_COLS = 25;

/** Deviation bands, in robust sigma. Visual states, not release limits. */
export const BAND_ELEVATED = 3;
export const BAND_FAR = 6;

export type DeviationState = "nominal" | "elevated" | "far";

export interface Socket {
  part: Part;
  col: number;
  row: number;
  /** Tray-local position in world units, y is up and set per frame. */
  px: number;
  pz: number;
}

/**
 * Seat a lot in the tray.
 *
 * Socket order follows wafer, then die row and column, so the layout is a
 * deterministic function of the data rather than an arranged picture. Which
 * socket a part occupies is arbitrary in a real burn-in board too; what
 * matters is that every part in the tray is the same device type from the
 * same lot, which is the population the screening statistics are defined over.
 *
 * The serial is the final tiebreaker and it is what makes the order total. A
 * lot spans several wafers, so die coordinates repeat within it - 18 of the
 * 350 parts in L04 share an (x, y) with another part. Sorting on coordinates
 * alone leaves those ties to be broken by the order the rows arrived in,
 * which would silently reshuffle the tray if the export ever changed.
 */
export function seatLot(parts: Part[], pitch = 1): Socket[] {
  const ordered = [...parts].sort(
    (a, b) =>
      (a.w < b.w ? -1 : a.w > b.w ? 1 : 0) ||
      a.y - b.y ||
      a.x - b.x ||
      (a.s < b.s ? -1 : a.s > b.s ? 1 : 0),
  );
  const rows = Math.ceil(ordered.length / TRAY_COLS);
  const w = (TRAY_COLS - 1) * pitch;
  const d = (rows - 1) * pitch;
  return ordered.map((part, i) => {
    const col = i % TRAY_COLS;
    const row = Math.floor(i / TRAY_COLS);
    return { part, col, row, px: col * pitch - w / 2, pz: row * pitch - d / 2 };
  });
}

export const trayRows = (n: number) => Math.ceil(n / TRAY_COLS);

/**
 * The value of one parameter at soak hour `t`.
 *
 * Log-linear between read points for currents, linear otherwise. Returns null
 * when the part has no usable reading (a dropped 96 h handler read).
 */
export function valueAt(
  p: Part, pi: number, t: number, hours: number[], isCurrent: boolean,
): number | null {
  const pts: [number, number][] = [];
  for (let i = 0; i < hours.length; i++) {
    const v = p.m[pi]?.[i];
    if (v != null && Number.isFinite(v) && (!isCurrent || v > 0)) pts.push([hours[i], v]);
  }
  if (!pts.length) return null;
  if (t <= pts[0][0]) return pts[0][1];
  for (let i = 1; i < pts.length; i++) {
    const [h0, v0] = pts[i - 1];
    const [h1, v1] = pts[i];
    if (t <= h1) {
      const f = (t - h0) / (h1 - h0);
      return isCurrent
        ? Math.exp(Math.log(v0) + f * (Math.log(v1) - Math.log(v0)))
        : v0 + f * (v1 - v0);
    }
  }
  return pts[pts.length - 1][1];
}

export interface LotState {
  /** Live value per socket, index-aligned with the socket array. */
  values: (number | null)[];
  /** Live robust |z| against the lot, one-sided: higher is worse everywhere. */
  z: number[];
  state: DeviationState[];
  median: number;
  p05: number;
  p95: number;
  /** Robust sigma, in the space the statistics were taken in. */
  sigma: number;
}

/**
 * The lot's own reference at hour `t`, and every part's deviation from it.
 *
 * This is the lot-relative comparison the whole project rests on: a part is
 * judged against the 350 siblings soaking beside it, not against a datasheet
 * number fixed years earlier. Currents are transformed to log space first,
 * the centre is a median and the spread is 1.4826 * MAD.
 */
export function lotStateAt(
  sockets: Socket[], pi: number, t: number, hours: number[], isCurrent: boolean,
): LotState {
  const values = sockets.map((s) => valueAt(s.part, pi, t, hours, isCurrent));
  const ok = values.filter((v): v is number => v != null);
  const space = isCurrent ? ok.map(Math.log) : ok;
  const med = median(space);
  const sigma = robustSigma(space);
  const back = (y: number) => (isCurrent ? Math.exp(y) : y);

  const z = values.map((v) => {
    if (v == null || sigma <= 0) return 0;
    // One-sided: higher is worse for every parameter in this dataset, so a
    // part below the lot centre is not an anomaly and scores zero.
    return Math.max(0, ((isCurrent ? Math.log(v) : v) - med) / sigma);
  });

  return {
    values,
    z,
    state: z.map(bandOf),
    median: back(med),
    p05: back(quantile(space, 0.05)),
    p95: back(quantile(space, 0.95)),
    sigma,
  };
}

export const bandOf = (z: number): DeviationState =>
  z >= BAND_FAR ? "far" : z >= BAND_ELEVATED ? "elevated" : "nominal";

/** Shape marker per state, so status never depends on colour alone. */
export const STATE_MARK: Record<DeviationState, string> = {
  nominal: "circle",
  elevated: "triangle",
  far: "square",
};

export const STATE_LABEL: Record<DeviationState, string> = {
  nominal: "inside the batch",
  elevated: "leaving the batch",
  far: "far outside the batch",
};

export const paramMeta = (meta: Meta, pi: number) => meta.params[pi];
