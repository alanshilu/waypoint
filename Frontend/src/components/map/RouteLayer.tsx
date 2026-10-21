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
}

/** The routes, clickable to select; the selected one drawn heavier. */
export function RouteLines({ routes, selectedRouteId, path, fullDetail, onSelect }: LinesProps) {
  return (
    <>
      {routes.map(({ route, line }) => {
        const d = path(fullDetail ? route.geometry : line) ?? "";
        return (
          <g key={route.id} className="map-route" onClick={() => onSelect(route.id)}>
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

/** A dot on each route at the mile the elevation chart is hovering. */
export function RouteHoverDots({ routes, selectedRouteId, projection, mile }: MarkProps & { mile: number }) {
  return (
    <>
      {routes.map(({ route, index }) => {
        const point = pointAtMile(index, mile);
        const xy = point && projection(point as [number, number]);
        if (!xy) return null;
        return (
          <circle
            key={route.id}
            className={route.id === selectedRouteId ? "hover-dot selected" : "hover-dot"}
            cx={xy[0]}
            cy={xy[1]}
            r={6}
          />
        );
      })}
    </>
  );
}
