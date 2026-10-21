import { useMemo } from "react";
import { geoAlbers, geoGraticule, geoPath } from "d3-geo";
import type { GeoPermissibleObjects, GeoProjection } from "d3-geo";
import { feature } from "topojson-client";
import type { FeatureCollection, Geometry, LineString } from "geojson";
import type { GeometryCollection, Topology } from "topojson-specification";
import usAtlas from "us-atlas/states-10m.json";
import { CALLOUT_POINTS, LABEL_POINTS, STATE_CODE_BY_FIPS } from "../../data/states";
import { CARDS_HEIGHT, CARDS_WIDTH, HEADER_HEIGHT } from "./layout";
import type { FitMode } from "./layout";

// Lower 48 + DC: drop Alaska (02), Hawaii (15), Puerto Rico (72) and the
// other territories us-atlas ships (FIPS above 56).
const topology = usAtlas as unknown as Topology<{ states: GeometryCollection }>;
const lower48: FeatureCollection<Geometry> = {
  type: "FeatureCollection",
  features: (feature(topology, topology.objects.states) as FeatureCollection<Geometry>).features.filter((f) => {
    const fips = String(f.id);
    return fips !== "02" && fips !== "15" && Number(fips) <= 56;
  }),
};

const graticule = geoGraticule()
  .extent([
    [-140, 15],
    [-50, 60],
  ])
  .step([5, 5])();

// The backend searches a 2 km box, so keep at least this much around the stops (degrees).
const STOPS_PADDING = 0.01;

interface FitInput {
  width: number;
  height: number;
  view: FitMode;
  /** The routes to fit in the route view */
  routeLines: LineString[];
  /** The points to fit in the stops view */
  stopPoints: { lat: number; lon: number }[];
  hasRoutes: boolean;
  /** Width of the list on the left, 0 when none is showing */
  leftPanelWidth: number;
}

/** The projection that fits the view (the lower 48, the routes or the stops) into the map, clear of the overlays. */
export function useFittedProjection({ width, height, view, routeLines, stopPoints, hasRoutes, leftPanelWidth }: FitInput): GeoProjection | null {
  return useMemo(() => {
    if (width === 0 || height === 0) return null;
    const zoomed = view !== "usa";
    const side = zoomed ? 70 : 24;
    const left = leftPanelWidth || side;
    const bottom = zoomed ? 50 : 24;
    let target: GeoPermissibleObjects = lower48;
    if (view === "route") {
      target = { type: "GeometryCollection", geometries: routeLines };
    } else if (view === "stops" && stopPoints.length > 0) {
      const lons = stopPoints.map((p) => p.lon);
      const lats = stopPoints.map((p) => p.lat);
      target = {
        type: "MultiPoint",
        coordinates: [
          ...stopPoints.map((p) => [p.lon, p.lat]),
          [Math.min(...lons) - STOPS_PADDING, Math.min(...lats) - STOPS_PADDING],
          [Math.max(...lons) + STOPS_PADDING, Math.max(...lats) + STOPS_PADDING],
        ],
      };
    }
    const fit = (top: number, right: number) =>
      geoAlbers().fitExtent(
        [
          [left, top],
          [Math.max(left + 1, width - right), Math.max(top + 1, height - bottom)],
        ],
        target,
      );
    if (!hasRoutes) return fit(24, side);
    // The comparison cards overlay the top right corner. Keep the map clear of
    // them either by fitting below or beside them, whichever draws it larger.
    const below = fit(CARDS_HEIGHT, side);
    const beside = fit(HEADER_HEIGHT, CARDS_WIDTH);
    return below.scale() >= beside.scale() ? below : beside;
  }, [width, height, view, routeLines, stopPoints, hasRoutes, leftPanelWidth]);
}

export interface StateShape {
  /** FIPS code, e.g. "06" */
  id: string;
  d: string;
  /** Postal code, e.g. "CA" */
  code: string;
  name: string;
  /** Where the state's label and city picker anchor */
  x: number;
  y: number;
  label: { x: number; y: number };
  /** Labelled out in the Atlantic with a leader line */
  callout: boolean;
  small: boolean;
}

/** The lower 48 and the graticule, projected. */
export function useStateShapes(projection: GeoProjection | null): { graticule: string; states: StateShape[] } | null {
  return useMemo(() => {
    if (!projection) return null;
    const path = geoPath(projection);
    return {
      graticule: path(graticule) ?? "",
      states: lower48.features.map((f) => {
        const id = String(f.id);
        const code = STATE_CODE_BY_FIPS[id] ?? "";
        const area = path.area(f);
        const [x, y] = (LABEL_POINTS[code] && projection(LABEL_POINTS[code])) || path.centroid(f);
        // Tiny eastern states: label out in the Atlantic with a leader line, until zoomed in enough
        const callout = CALLOUT_POINTS[code] && area < 2500 ? projection(CALLOUT_POINTS[code]) : null;
        return {
          id,
          d: path(f) ?? "",
          code,
          name: String(f.properties?.name ?? ""),
          x,
          y,
          label: callout ? { x: callout[0], y: callout[1] } : { x, y },
          callout: callout !== null,
          // small states get a smaller label so neighbours don't collide
          small: area < 900,
        };
      }),
    };
  }, [projection]);
}
