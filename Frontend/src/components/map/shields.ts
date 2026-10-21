import type { GeoProjection } from "d3-geo";
import { linesOf } from "../../highways";
import type { Highway, HighwayOnRoute } from "../../highways";
import type { Rect } from "./layout";

// At most this many shields, at least this far apart (px), and clear of the map's edge
const MAX_SHIELDS = 36;
const SPACING = { usa: 110, closeUp: 75 };
const MARGIN = 18;
// Shields keep this far (px) from the trip's endpoint labels
const ENDPOINT_CLEARANCE = 40;
// Where the Route 66 label goes: the first of these towns that is on screen
const ROUTE_66_LABEL_AT: [number, number][] = [
  [-101.8313, 35.222], // Amarillo
  [-111.6513, 35.1983], // Flagstaff
  [-94.5133, 37.0842], // Joplin
  [-117.0173, 34.8958], // Barstow
];

export interface Shield {
  highway: Highway;
  x: number;
  y: number;
  onRoute: boolean;
}

/** Points along a highway to try for its shield, from the middle of its longest line outwards. */
function candidates(highway: Highway): [number, number][] {
  const line = linesOf(highway.geometry).reduce((a, b) => (b.length > a.length ? b : a));
  const mid = line.length >> 1;
  const step = Math.max(1, Math.floor(line.length / 8));
  const out: [number, number][] = [];
  for (let k = 0; k <= line.length; k += step) {
    for (const i of k === 0 ? [mid] : [mid + k, mid - k]) {
      if (i >= 0 && i < line.length) out.push(line[i] as [number, number]);
    }
  }
  return out;
}

interface PlaceInput {
  projection: GeoProjection;
  highways: Highway[];
  /** The selected route's highways, shielded first, on the route itself */
  onRoute: HighwayOnRoute[];
  /** Zoomed in from the national view: tighter spacing, and US routes get shields too */
  closeUp: boolean;
  width: number;
  height: number;
  /** Screen points to keep clear (the trip's endpoints) */
  blocked: [number, number][];
  /** Screen areas under the overlays */
  covered: Rect[];
}

/** Where the shields go: the selected route's highways first, then the rest of the network, spaced out greedily. */
export function placeShields({ projection, highways, onRoute, closeUp, width, height, blocked, covered }: PlaceInput): Shield[] {
  const spacing = closeUp ? SPACING.closeUp : SPACING.usa;
  const placed: Shield[] = [];
  const onRouteIds = new Set(onRoute.map((h) => h.highway.id));
  const onScreen = (x: number, y: number) =>
    x > MARGIN &&
    y > MARGIN &&
    x < width - MARGIN &&
    y < height - MARGIN &&
    covered.every(([x0, y0, x1, y1]) => x < x0 - MARGIN || x > x1 + MARGIN || y < y0 || y > y1 + MARGIN);
  const clear = (x: number, y: number, gap: number) =>
    placed.every((s) => Math.hypot(s.x - x, s.y - y) >= gap) &&
    blocked.every(([bx, by]) => Math.hypot(bx - x, by - y) >= ENDPOINT_CLEARANCE);

  for (const { highway, at } of onRoute) {
    const xy = projection(at as [number, number]);
    // a route's own shields may sit closer together: they're the ones that matter
    if (xy && onScreen(xy[0], xy[1]) && clear(xy[0], xy[1], spacing * 0.6)) {
      placed.push({ highway, x: xy[0], y: xy[1], onRoute: true });
    }
  }
  const rest = highways
    .filter((h) => !onRouteIds.has(h.id) && (closeUp || h.kind === "interstate"))
    // Interstates, then shorter (more important) numbers: I-5 and I-80 before I-805
    .sort(
      (a, b) =>
        Number(a.kind !== "interstate") - Number(b.kind !== "interstate") ||
        a.number.length - b.number.length ||
        parseInt(a.number, 10) - parseInt(b.number, 10),
    );
  for (const highway of rest) {
    if (placed.length >= MAX_SHIELDS) break;
    for (const point of candidates(highway)) {
      const xy = projection(point);
      if (xy && onScreen(xy[0], xy[1]) && clear(xy[0], xy[1], spacing)) {
        placed.push({ highway, x: xy[0], y: xy[1], onRoute: false });
        break;
      }
    }
  }
  return placed;
}

/** Where the "Route 66" label goes, or null when none of its towns is on screen. */
export function route66LabelAt(projection: GeoProjection, width: number, height: number): [number, number] | null {
  for (const town of ROUTE_66_LABEL_AT) {
    const xy = projection(town);
    if (xy && xy[0] > 60 && xy[1] > 30 && xy[0] < width - 60 && xy[1] < height - 30) return xy;
  }
  return null;
}
