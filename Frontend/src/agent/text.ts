import { formatClimbRatio, formatDuration, formatDurationDelta, formatMiles, formatScore, routeLabel } from "../format";
import type { Place, Route, Trip } from "../types";

/** "San Francisco" from "San Francisco, California, USA" */
export const shortName = (place: Place) => place.name.split(",")[0];

export function describe(route: Route): string {
  return `${formatDuration(route.duration_seconds)}, ${formatMiles(route.distance_miles)}, scenic ${formatScore(route.scenic_score)}`;
}

/** Both routes side by side, as the scripted agent sums up a new trip. */
export function compare(trip: Trip): string {
  const fastest = trip.routes.find((r) => r.route_type === "fastest");
  const backroads = trip.routes.find((r) => r.route_type === "backroads");
  const head = `${shortName(trip.origin)} to ${shortName(trip.destination)}.`;
  if (!fastest || !backroads) {
    return `${head} ${trip.routes.map((r) => `${routeLabel(r.route_type)}: ${describe(r)}`).join(". ")}.`;
  }
  const climb = formatClimbRatio(backroads.ascent_m, fastest.ascent_m);
  const delta = formatDurationDelta(backroads.duration_seconds - fastest.duration_seconds);
  return (
    `${head} Fastest: ${describe(fastest)}. Backroads: ${describe(backroads)}. ` +
    `Backroads is ${delta}${climb ? ` with ${climb}` : ""}.`
  );
}

/** Suggested next messages after a scripted reply. */
export function followUps(trip: Trip, selectedRouteId: number | null): string[] {
  const selects = trip.routes.filter((r) => r.id !== selectedRouteId).map((r) => `Select ${r.route_type}`);
  return [...selects, "Weather at destination", "Stops near destination", "Stops along the route", "Where to stay and eat"];
}

/** Suggested next messages after a reply from the backend agent. */
export function agentChips(trip: Trip): string[] {
  const selects = trip.routes.filter((r) => r.id !== trip.selected_route_id).map((r) => `Select ${r.route_type}`);
  return [...selects, "Where should I stop overnight?", "Where can we stay and eat?", "What's the weather when I arrive?"];
}
