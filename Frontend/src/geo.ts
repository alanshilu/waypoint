import type { LineString, Position } from "geojson";

const EARTH_RADIUS_MILES = 3958.8;
const toRad = (deg: number) => (deg * Math.PI) / 180;

export function haversineMiles(a: Position, b: Position): number {
  const dLat = toRad(b[1] - a[1]);
  const dLon = toRad(b[0] - a[0]);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a[1])) * Math.cos(toRad(b[1])) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_MILES * Math.asin(Math.sqrt(h));
}

function perpendicularDistance(p: Position, a: Position, b: Position): number {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const lengthSq = dx * dx + dy * dy;
  if (lengthSq === 0) return Math.hypot(p[0] - a[0], p[1] - a[1]);
  const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / lengthSq));
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
}

function douglasPeucker(points: Position[], tolerance: number): Position[] {
  const keep = new Uint8Array(points.length);
  keep[0] = 1;
  keep[points.length - 1] = 1;
  const stack: [number, number][] = [[0, points.length - 1]];
  while (stack.length) {
    const [first, last] = stack.pop()!;
    let maxDistance = 0;
    let index = -1;
    for (let i = first + 1; i < last; i++) {
      const d = perpendicularDistance(points[i], points[first], points[last]);
      if (d > maxDistance) {
        maxDistance = d;
        index = i;
      }
    }
    if (index > 0 && maxDistance > tolerance) {
      keep[index] = 1;
      stack.push([first, index], [index, last]);
    }
  }
  return points.filter((_, i) => keep[i]);
}

/**
 * Reduces a route to at most maxPoints by raising the Douglas-Peucker
 * tolerance (in degrees) until it fits. Routes already under the limit are
 * returned untouched.
 */
export function simplifyLine(line: LineString, maxPoints = 500): LineString {
  const points = line.coordinates;
  if (points.length <= maxPoints) return line;
  let tolerance = 0.0005;
  let simplified = points;
  for (let i = 0; i < 20 && simplified.length > maxPoints; i++) {
    simplified = douglasPeucker(points, tolerance);
    tolerance *= 2;
  }
  return { type: "LineString", coordinates: simplified };
}

export interface MileIndex {
  coordinates: Position[];
  /** Cumulative mile marker for each coordinate, scaled to end at totalMiles. */
  miles: number[];
  totalMiles: number;
}

/**
 * Builds a mile marker per vertex. Straight-line distance between vertices
 * under-reads a real road, so markers are scaled to the route's reported
 * distance_miles to keep the map marker in step with the elevation chart.
 */
export function buildMileIndex(line: LineString, totalMiles: number): MileIndex {
  const coordinates = line.coordinates;
  const raw = [0];
  for (let i = 1; i < coordinates.length; i++) {
    raw.push(raw[i - 1] + haversineMiles(coordinates[i - 1], coordinates[i]));
  }
  const measured = raw[raw.length - 1] || 1;
  const scale = totalMiles > 0 ? totalMiles / measured : 1;
  return { coordinates, miles: raw.map((m) => m * scale), totalMiles: measured * scale };
}

/** Interpolated [lon, lat] at a mile marker, or null if it is off the route. */
export function pointAtMile(index: MileIndex, mile: number): Position | null {
  const { coordinates, miles } = index;
  if (coordinates.length === 0 || mile < 0 || mile > index.totalMiles) return null;
  let lo = 0;
  let hi = miles.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (miles[mid] <= mile) lo = mid;
    else hi = mid;
  }
  const span = miles[hi] - miles[lo];
  const t = span > 0 ? (mile - miles[lo]) / span : 0;
  const a = coordinates[lo];
  const b = coordinates[hi];
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
}

/** The mile marker of the route point nearest p ([lon, lat]): where along the route the pointer is. */
export function nearestMile(index: MileIndex, p: Position): number {
  const { coordinates, miles } = index;
  const kx = Math.cos(toRad(p[1]));
  let best = 0;
  let bestD = Infinity;
  for (let i = 0; i < coordinates.length; i++) {
    const dx = (coordinates[i][0] - p[0]) * kx;
    const dy = coordinates[i][1] - p[1];
    const d = dx * dx + dy * dy;
    if (d < bestD) {
      bestD = d;
      best = i;
    }
  }
  return miles[best] ?? 0;
}
