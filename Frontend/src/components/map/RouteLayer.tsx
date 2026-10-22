import type { GeoPath, GeoProjection } from "d3-geo";
import type { LineString } from "geojson";
import { routeLabel } from "../../format";
import { pointAtMile } from "../../geo";
import type { MileIndex } from "../../geo";
import type { Route } from "../../types";

/** A trip route ready to draw: its simplified line for the fitted views, and a mile index for markers. */
export interface MapRoute {
  route: Route;
  line: LineString;
  index: MileIndex;
}

interface LinesProps {
  /** In drawing order: the selected route last, so it sits on top */
  routes: MapRoute[];
  selectedRouteId: number | null;
  path: GeoPath;
  /** Zoomed in close: draw from the full served line */
  fullDetail: boolean;
  onSelect: (routeId: number) => void;
  /** The pointer moved along a route (client coordinates), or left it (null) */
  onHoverAlong: (routeId: number | null, clientX?: number, clientY?: number) => void;
}

/** The routes, clickable to select and hoverable to drive along; the selected one drawn heavier. */
export function RouteLines({ routes, selectedRouteId, path, fullDetail, onSelect, onHoverAlong }: LinesProps) {
  return (
    <>
      {routes.map(({ route, line }) => {
        const d = path(fullDetail ? route.geometry : line) ?? "";
        return (
          <g
            key={route.id}
            className="map-route"
            onClick={() => onSelect(route.id)}
            onMouseMove={(event) => onHoverAlong(route.id, event.clientX, event.clientY)}
            onMouseLeave={() => onHoverAlong(null)}
          >
            <title>{`${routeLabel(route.route_type)} route: click to select`}</title>
            <path className={route.id === selectedRouteId ? "route-line selected" : "route-line"} d={d} />
            <path className="route-hit" d={d} />
          </g>
        );
      })}
    </>
  );
}

interface MarkProps {
  routes: MapRoute[];
  selectedRouteId: number | null;
  projection: GeoProjection;
}

/** "Fastest" and "Backroads" at each route's midpoint: fastest right of its line, backroads left, so they don't collide. */
export function RouteTags({ routes, selectedRouteId, projection }: MarkProps) {
  return (
    <>
      {routes.map(({ route, index }) => {
        const mid = pointAtMile(index, index.totalMiles / 2);
        const xy = mid && projection(mid as [number, number]);
        if (!xy) return null;
        const right = route.route_type === "fastest";
        return (
          <text
            key={route.id}
            className={route.id === selectedRouteId ? "route-tag selected" : "route-tag"}
            x={xy[0] + (right ? 10 : -10)}
            y={xy[1]}
            textAnchor={right ? "start" : "end"}
            dominantBaseline="middle"
          >
            {routeLabel(route.route_type)}
          </text>
        );
      })}
    </>
  );
}

// How far ahead (miles) to look for the car's heading
const HEADING_LOOKAHEAD_MI = 0.4;

/** The screen angle (degrees, 0 = east) a route heads in at this mile, from a point a little further on. */
function headingAt(projection: GeoProjection, index: MileIndex, mile: number): number | null {
  const ahead = Math.min(mile + HEADING_LOOKAHEAD_MI, index.totalMiles);
  // at the very end, look back instead
  const [fromMile, toMile] = ahead - mile < 0.05 ? [Math.max(0, mile - HEADING_LOOKAHEAD_MI), mile] : [mile, ahead];
  const from = pointAtMile(index, fromMile);
  const to = pointAtMile(index, toMile);
  const a = from && projection(from as [number, number]);
  const b = to && projection(to as [number, number]);
  if (!a || !b || (a[0] === b[0] && a[1] === b[1])) return null;
  return (Math.atan2(b[1] - a[1], b[0] - a[0]) * 180) / Math.PI;
}

/**
 * At the hovered mile (from the elevation chart, or the pointer along a route on the map): a small car on the
 * route being driven, pointing the way it goes, and a dot on the other route at the same mile.
 */
export function RouteHoverCar({ routes, carRouteId, projection, mile }: { routes: MapRoute[]; carRouteId: number | null; projection: GeoProjection; mile: number }) {
  return (
    <>
      {routes.map(({ route, index }) => {
        const point = pointAtMile(index, mile);
        const xy = point && projection(point as [number, number]);
        if (!xy) return null;
        if (route.id !== carRouteId) {
          return <circle key={route.id} className="hover-dot" cx={xy[0]} cy={xy[1]} r={5} />;
        }
        const angle = headingAt(projection, index, mile) ?? 0;
        // drawn heading east; flipped upright when it heads west, so it never drives upside down
        const flip = Math.abs(angle) > 90 ? " scale(1 -1)" : "";
        return (
          <g key={route.id} className="hover-car" aria-hidden="true">
            <g transform={`translate(${xy[0]} ${xy[1]}) rotate(${angle})${flip}`}>
              <rect className="car-body" x={-11} y={-6} width={22} height={12} rx={4} />
              <rect className="car-glass" x={3} y={-4.5} width={4} height={9} rx={1.5} />
              <rect className="car-glass" x={-8} y={-4.5} width={3} height={9} rx={1.5} />
              <rect className="car-roof" x={-4} y={-4} width={6} height={8} rx={1} />
            </g>
            <text className="hover-car-mile" x={xy[0]} y={xy[1] - 14} textAnchor="middle">
              mile {Math.round(mile)}
            </text>
          </g>
        );
      })}
    </>
  );
}
