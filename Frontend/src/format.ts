import type { Route } from "./types";

export function formatDuration(seconds: number): string {
  const totalMinutes = Math.round(Math.abs(seconds) / 60);
  const h = Math.floor(totalMinutes / 60);
  const m = totalMinutes % 60;
  if (h === 0) return `${m}m`;
  return `${h}h ${String(m).padStart(2, "0")}m`;
}

const sign = (n: number) => (n < 0 ? "−" : "+");

export const formatMiles = (miles: number) => `${Math.round(miles).toLocaleString("en-US")} mi`;
export const formatMetres = (m: number) => `${Math.round(m).toLocaleString("en-US")} m`;
export const formatScore = (score: number) => score.toFixed(1);

export const formatDurationDelta = (seconds: number) => `${sign(seconds)}${formatDuration(seconds)}`;
export const formatMilesDelta = (miles: number) =>
  `${sign(miles)}${Math.abs(Math.round(miles)).toLocaleString("en-US")} mi`;

/** "2.3x climbing", or null when the baseline has no recorded ascent. */
export function formatClimbRatio(ascent: number, baselineAscent: number): string | null {
  if (!(baselineAscent > 0)) return null;
  return `${(ascent / baselineAscent).toFixed(1)}x climbing`;
}

/** Climb density that scores 50; must match Backend/app/services/scoring_service.py. */
export const HALF_SCORE_DENSITY_M_PER_MILE = 40;

/** Same terrain-only formula as Backend/app/services/scoring_service.py. */
export function scenicBreakdown(route: Route) {
  const distance = route.distance_miles > 0 ? route.distance_miles : 1;
  const elevationDensity = (route.ascent_m + route.descent_m) / distance;
  const score = (100 * elevationDensity) / (elevationDensity + HALF_SCORE_DENSITY_M_PER_MILE);
  return { elevationDensity, score };
}

export const routeLabel = (type: string) => (type === "backroads" ? "Backroads" : "Fastest");
