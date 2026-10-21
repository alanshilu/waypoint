import { useEffect, useState } from "react";
import type { FeatureCollection, LineString, MultiLineString, Position } from "geojson";
import { feature } from "topojson-client";
import type { GeometryCollection, Topology } from "topojson-specification";

/**
 * The lower 48's Interstates and US routes (public/data/highways.json, built by `npm run highways` from
 * Natural Earth), and which of them a route drives on.
 */

export interface Highway {
  /** "I-5", "US-101" */
  id: string;
  kind: "interstate" | "us";
  /** The number on the shield: "5", "101", "35W" */
  number: string;
  /** "Interstate 5", "US Route 101" */
  name: string;
  geometry: LineString | MultiLineString;
}

export interface HighwayOnRoute {
  highway: Highway;
  /** Miles of the route that follow this highway */
  miles: number;
  /** A point on the route about halfway along the stretch that follows it, for a shield */
  at: Position;
}

let loading: Promise<Highway[] | null> | null = null;

/** Loads the network once. Null if it can't be fetched: the map then draws without it. */
export function loadHighways(): Promise<Highway[] | null> {
  loading ??= fetch(`${import.meta.env.BASE_URL}data/highways.json`)
    .then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json() as Promise<Topology<{ highways: GeometryCollection<{ id: string }> }>>;
    })
    .then((topology) => {
      const collection = feature(topology, topology.objects.highways) as FeatureCollection<
        LineString | MultiLineString,
        { id: string }
      >;
      return collection.features.map((f) => {
        const id = f.properties.id;
        const interstate = id.startsWith("I-");
        const number = id.slice(interstate ? 2 : 3);
        return {
          id,
          kind: interstate ? "interstate" : "us",
          number,
          name: interstate ? `Interstate ${number}` : `US Route ${number}`,
          geometry: f.geometry,
        } satisfies Highway;
      });
    })
    .catch((error: unknown) => {
      console.warn("Highway network unavailable; the map draws without it", error);
      return null;
    });
  return loading;
}

/** The network once it has loaded; null until then, or if it couldn't be loaded. */
export function useHighways(): Highway[] | null {
  const [highways, setHighways] = useState<Highway[] | null>(null);
  useEffect(() => {
    let live = true;
    void loadHighways().then((h) => live && setHighways(h));
    return () => {
      live = false;
    };
  }, []);
  return highways;
}

export const linesOf = (geometry: LineString | MultiLineString): Position[][] =>
  geometry.type === "LineString" ? [geometry.coordinates] : geometry.coordinates;

// ---- Which highways a route drives on ----

const MILES_PER_DEGREE = 69.17;
// The network is generalised (Natural Earth at 1:10m, then simplified to 1.2 km): a real SF to LA route
// on I-5 sat 0.09 mi from the drawn line at the median and 0.53 mi at worst. Much wider and roads running
// alongside a highway (frontage roads, old alignments) start to count as driving on it.
const TOLERANCE_MILES = 0.75;
const SAMPLE_MILES = 1;
// Shorter stretches are usually a junction or a city crossing, not a highway the trip follows
const MIN_MILES = 10;
const CELL_DEGREES = 0.25;

interface Segment {
  highway: number;
  a: Position;
  b: Position;
}

type SegmentIndex = Map<string, Segment[]>;

const cellKey = (x: number, y: number) => `${x}:${y}`;

const indexes = new WeakMap<Highway[], SegmentIndex>();

function segmentIndex(highways: Highway[]): SegmentIndex {
  const cached = indexes.get(highways);
  if (cached) return cached;
  const index: SegmentIndex = new Map();
  highways.forEach((highway, h) => {
    for (const line of linesOf(highway.geometry)) {
      for (let i = 1; i < line.length; i++) {
        const a = line[i - 1];
        const b = line[i];
        const segment = { highway: h, a, b };
        for (let x = Math.floor(Math.min(a[0], b[0]) / CELL_DEGREES); x <= Math.floor(Math.max(a[0], b[0]) / CELL_DEGREES); x++) {
          for (let y = Math.floor(Math.min(a[1], b[1]) / CELL_DEGREES); y <= Math.floor(Math.max(a[1], b[1]) / CELL_DEGREES); y++) {
            const key = cellKey(x, y);
            const cell = index.get(key);
            if (cell) cell.push(segment);
            else index.set(key, [segment]);
          }
        }
      }
    }
  });
  indexes.set(highways, index);
  return index;
}

/** Miles from p to segment ab, on a local flat projection (fine at these distances). */
function milesToSegment(p: Position, a: Position, b: Position): number {
  const kx = Math.cos((p[1] * Math.PI) / 180) * MILES_PER_DEGREE;
  const ky = MILES_PER_DEGREE;
  const ax = (a[0] - p[0]) * kx;
  const ay = (a[1] - p[1]) * ky;
  const dx = (b[0] - a[0]) * kx;
  const dy = (b[1] - a[1]) * ky;
  const lengthSq = dx * dx + dy * dy;
  const t = lengthSq === 0 ? 0 : Math.max(0, Math.min(1, -(ax * dx + ay * dy) / lengthSq));
  return Math.hypot(ax + t * dx, ay + t * dy);
}

/** A point every SAMPLE_MILES along the line (straight-line miles between its vertices). */
function samples(line: LineString): Position[] {
  const out: Position[] = [];
  const coords = line.coordinates;
  if (coords.length === 0) return out;
  out.push(coords[0]);
  let carried = 0;
  for (let i = 1; i < coords.length; i++) {
    const a = coords[i - 1];
    const b = coords[i];
    const kx = Math.cos((a[1] * Math.PI) / 180) * MILES_PER_DEGREE;
    const length = Math.hypot((b[0] - a[0]) * kx, (b[1] - a[1]) * MILES_PER_DEGREE);
    let next = SAMPLE_MILES - carried;
    while (next <= length) {
      const t = next / length;
      out.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]);
      next += SAMPLE_MILES;
    }
    carried = length - (next - SAMPLE_MILES);
  }
  return out;
}

const along = new WeakMap<LineString, WeakMap<Highway[], HighwayOnRoute[]>>();

/**
 * The highways a route drives on, in driving order: each sample point along the route counts towards the
 * nearest highway within TOLERANCE_MILES, and highways it follows for at least MIN_MILES are kept.
 */
export function highwaysAlong(route: LineString, highways: Highway[], minMiles = MIN_MILES): HighwayOnRoute[] {
  // whole routes are cached; a one-off stretch (a directions step, with its own minimum) is not
  const cacheable = minMiles === MIN_MILES;
  const cached = cacheable ? along.get(route)?.get(highways) : undefined;
  if (cached) return cached;

  const index = segmentIndex(highways);
  // highway -> sample positions credited to it
  const credited = new Map<number, Position[]>();
  const firstSeen = new Map<number, number>();
  samples(route).forEach((p, i) => {
    const cx = Math.floor(p[0] / CELL_DEGREES);
    const cy = Math.floor(p[1] / CELL_DEGREES);
    let best = -1;
    let bestMiles = TOLERANCE_MILES;
    for (let x = cx - 1; x <= cx + 1; x++) {
      for (let y = cy - 1; y <= cy + 1; y++) {
        for (const s of index.get(cellKey(x, y)) ?? []) {
          const miles = milesToSegment(p, s.a, s.b);
          if (miles < bestMiles) {
            bestMiles = miles;
            best = s.highway;
          }
        }
      }
    }
    if (best < 0) return;
    const points = credited.get(best);
    if (points) points.push(p);
    else credited.set(best, [p]);
    if (!firstSeen.has(best)) firstSeen.set(best, i);
  });

  const result = [...credited.entries()]
    .map(([h, points]) => ({ h, highway: highways[h], miles: points.length * SAMPLE_MILES, at: points[points.length >> 1] }))
    .filter((r) => r.miles >= minMiles)
    .sort((a, b) => firstSeen.get(a.h)! - firstSeen.get(b.h)!)
    .map(({ highway, miles, at }) => ({ highway, miles, at }));

  if (cacheable) {
    if (!along.has(route)) along.set(route, new WeakMap());
    along.get(route)!.set(highways, result);
  }
  return result;
}

/** "I-5", "US 101": how a highway is written in running text. */
export const highwayLabel = (h: Highway) => (h.kind === "interstate" ? `I-${h.number}` : `US ${h.number}`);
