import type { LineString, Position } from "geojson";
import { highwayLabel, highwaysAlong } from "./highways";
import type { Highway } from "./highways";
import type { DirectionStep, Route } from "./types";

/** A step ready to show: its text with the road filled in where ORS left it unnamed, and where it runs. */
export interface Direction {
  step: DirectionStep;
  /** "Keep left onto I-5" when ORS said only "Keep left" but the stretch follows I-5 */
  text: string;
  /** Miles from the start of the trip to this step */
  atMile: number;
  /** The stretch of the route this step covers (from the served, simplified line) */
  stretch: Position[];
}

export const ARRIVE = 10;
const DEPART = 11;

/** Degrees the maneuver arrow turns from straight ahead; null for depart, arrive and roundabouts. */
export function turnAngle(type: number): number | null {
  switch (type) {
    case 0: return -90; // left
    case 1: return 90; // right
    case 2: return -135; // sharp left
    case 3: return 135; // sharp right
    case 4: return -45; // slight left
    case 5: return 45; // slight right
    case 6: return 0; // straight
    case 9: return 180; // U-turn
    case 12: return -25; // keep left
    case 13: return 25; // keep right
    default: return null;
  }
}

export const isEndpoint = (type: number) => type === ARRIVE || type === DEPART;
export const isRoundabout = (type: number) => type === 7 || type === 8;

const squaredDistance = (a: Position, b: Position) => {
  const kx = Math.cos((a[1] * Math.PI) / 180);
  return ((a[0] - b[0]) * kx) ** 2 + (a[1] - b[1]) ** 2;
};

/** Index of the vertex nearest to p, searching from `from` onwards (steps come in driving order). */
function nearestFrom(line: Position[], p: Position, from: number): number {
  let best = from;
  let bestD = Infinity;
  for (let i = from; i < line.length; i++) {
    const d = squaredDistance(line[i], p);
    if (d < bestD) {
      bestD = d;
      best = i;
    }
  }
  return best;
}

// A step needs at least this many miles before it's worth naming from the highway network
const NAME_FROM_HIGHWAYS_MIN_MILES = 2;

/**
 * The route's steps with their stretches, and unnamed long steps named after the Interstate or US route
 * they follow (most of the stretch, by the highway matcher). Null when the route has no directions.
 */
export function buildDirections(route: Route, highways: Highway[] | null): Direction[] | null {
  const steps = route.directions;
  if (!steps || steps.length === 0) return null;
  const line = route.geometry.coordinates;
  let cursor = 0;
  let mile = 0;
  return steps.map((step) => {
    const first = nearestFrom(line, step.start, cursor);
    const last = Math.max(first, nearestFrom(line, step.end, first));
    cursor = first;
    const stretch = [step.start, ...line.slice(first + 1, last), step.end];
    const atMile = mile;
    mile += step.distance_miles;

    let text = step.instruction;
    if (!step.name && highways && step.distance_miles >= NAME_FROM_HIGHWAYS_MIN_MILES && !isEndpoint(step.type)) {
      const stretchLine: LineString = { type: "LineString", coordinates: stretch };
      const [main] = highwaysAlong(stretchLine, highways, step.distance_miles * 0.5);
      if (main) text = `${step.instruction} onto ${highwayLabel(main.highway)}`;
    }
    return { step, text, atMile, stretch };
  });
}
