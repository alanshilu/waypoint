import { useEffect, useMemo, useState } from "react";
import { geoAlbers, geoGraticule, geoPath } from "d3-geo";
import type { GeoPermissibleObjects } from "d3-geo";
import { feature } from "topojson-client";
import type { FeatureCollection, Geometry } from "geojson";
import type { GeometryCollection, Topology } from "topojson-specification";
import usAtlas from "us-atlas/states-10m.json";
import { buildMileIndex, pointAtMile, simplifyLine } from "../geo";
import { routeLabel } from "../format";
import { useTrip } from "../state/TripProvider";
import { useSize } from "../useSize";
import type { Place } from "../types";

const MAX_ROUTE_POINTS = 500;
// Footprint of the RouteComparison overlay, including its margins.
const CARDS_HEIGHT = 285;
const CARDS_WIDTH = 520;
// Footprint of the title, weather line and zoom toggle in the top left.
const HEADER_HEIGHT = 180;

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

type FitMode = "usa" | "route" | "stops";

// Width reserved on the left for the stops list while it is showing.
const STOPS_LIST_WIDTH = 290;
// The backend searches a 2 km box, so keep at least this much around the stops (degrees).
const STOPS_PADDING = 0.01;

const shortName = (place: Place) => place.name.split(",")[0];

export default function RouteMap() {
  const { trip, selectedRouteId, hoverMile, pois, selectRoute, error } = useTrip();
  const [hoveredPoi, setHoveredPoi] = useState<number | null>(null);
  const [ref, { width, height }] = useSize<HTMLDivElement>();
  const [mode, setMode] = useState<FitMode>("usa");

  // Zoom to a new trip when it arrives; the toggle takes over from there.
  const tripId = trip?.id ?? null;
  useEffect(() => {
    setMode(tripId === null ? "usa" : "route");
  }, [tripId]);

  // A new POI search zooms to its results so the numbered markers are readable.
  const stops = pois && pois.items.length > 0 ? pois : null;
  useEffect(() => {
    if (stops) setMode("stops");
  }, [stops]);

  const routes = useMemo(
    () =>
      (trip?.routes ?? []).map((route) => ({
        route,
        line: simplifyLine(route.geometry, MAX_ROUTE_POINTS),
        index: buildMileIndex(route.geometry, route.distance_miles),
      })),
    [trip?.routes],
  );

  const hasRoutes = routes.length > 0;
  const view: FitMode = mode === "stops" && stops ? "stops" : mode !== "usa" && hasRoutes ? "route" : "usa";
  const zoomed = view !== "usa";

  const projection = useMemo(() => {
    if (width === 0 || height === 0) return null;
    const side = zoomed ? 70 : 24;
    const left = stops ? STOPS_LIST_WIDTH : side;
    const bottom = zoomed ? 50 : 24;
    let target: GeoPermissibleObjects = lower48;
    if (view === "route") {
      target = { type: "GeometryCollection", geometries: routes.map((r) => r.line) };
    } else if (view === "stops" && stops) {
      const lons = stops.items.map((p) => p.lon);
      const lats = stops.items.map((p) => p.lat);
      target = {
        type: "MultiPoint",
        coordinates: [
          ...stops.items.map((p) => [p.lon, p.lat]),
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
  }, [width, height, view, hasRoutes, routes, stops]);

  const base = useMemo(() => {
    if (!projection) return null;
    const path = geoPath(projection);
    return {
      graticule: path(graticule) ?? "",
      states: lower48.features.map((f) => ({ id: String(f.id), d: path(f) ?? "" })),
    };
  }, [projection]);

  const path = projection ? geoPath(projection) : null;
  // Draw the selected route last so it sits on top.
  const ordered = [...routes].sort(
    (a, b) => Number(a.route.id === selectedRouteId) - Number(b.route.id === selectedRouteId),
  );

  return (
    <div className="route-map" ref={ref}>
      {projection && path && base && (
        <svg width={width} height={height} role="img" aria-label="Map of the lower 48 states with trip routes">
          <path className="map-graticule" d={base.graticule} />
          <g>
            {base.states.map((s) => (
              <path key={s.id} className="map-state" d={s.d} />
            ))}
          </g>

          {ordered.map(({ route, line }) => {
            const selected = route.id === selectedRouteId;
            const d = path(line) ?? "";
            return (
              <g key={route.id} className="map-route" onClick={() => selectRoute(route.id)}>
                <title>{`${routeLabel(route.route_type)} route: click to select`}</title>
                <path className={selected ? "route-line selected" : "route-line"} d={d} />
                <path className="route-hit" d={d} />
              </g>
            );
          })}

          {ordered.map(({ route, index }) => {
            const mid = pointAtMile(index, index.totalMiles / 2);
            const xy = mid && projection(mid as [number, number]);
            if (!xy) return null;
            const selected = route.id === selectedRouteId;
            // Fastest label sits right of its line, backroads left, so they do not collide.
            const right = route.route_type === "fastest";
            return (
              <text
                key={route.id}
                className={selected ? "route-tag selected" : "route-tag"}
                x={xy[0] + (right ? 10 : -10)}
                y={xy[1]}
                textAnchor={right ? "start" : "end"}
                dominantBaseline="middle"
              >
                {routeLabel(route.route_type)}
              </text>
            );
          })}

          {trip &&
            [trip.origin, trip.destination].map((place, i) => {
              const xy = projection([place.lon, place.lat]);
              if (!xy) return null;
              return (
                <g key={i} className="map-endpoint">
                  <circle cx={xy[0]} cy={xy[1]} r={5} />
                  <text x={xy[0] + 9} y={xy[1] - 9}>
                    {shortName(place)}
                  </text>
                </g>
              );
            })}

          {hoverMile !== null &&
            ordered.map(({ route, index }) => {
              const point = pointAtMile(index, hoverMile);
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

          {stops &&
            (view === "stops" ? (
              stops.items.map((poi, i) => {
                const xy = projection([poi.lon, poi.lat]);
                if (!xy) return null;
                return (
                  <g
                    key={poi.id}
                    className={hoveredPoi === poi.id ? "poi-marker active" : "poi-marker"}
                    onMouseEnter={() => setHoveredPoi(poi.id)}
                    onMouseLeave={() => setHoveredPoi(null)}
                  >
                    <title>{`${poi.name} (${poi.category.replace(/_/g, " ")})`}</title>
                    <circle cx={xy[0]} cy={xy[1]} r={10} />
                    <text x={xy[0]} y={xy[1]} textAnchor="middle" dominantBaseline="central">
                      {i + 1}
                    </text>
                  </g>
                );
              })
            ) : (
              // Zoomed out, the stops sit on top of each other: draw one marker with a count.
              (() => {
                const xy = projection([stops.center.lon, stops.center.lat]);
                if (!xy) return null;
                return (
                  <g className="poi-cluster" onClick={() => setMode("stops")}>
                    <title>Click to zoom to these stops</title>
                    <rect x={xy[0] - 6} y={xy[1] - 6} width={12} height={12} transform={`rotate(45 ${xy[0]} ${xy[1]})`} />
                    <text x={xy[0] + 13} y={xy[1] + 16}>
                      {stops.items.length} stops
                    </text>
                  </g>
                );
              })()
            ))}
        </svg>
      )}

      <div className="map-header">
        {trip ? (
          <>
            <h1>
              {shortName(trip.origin)} <span aria-hidden="true">&rarr;</span>
              <span className="sr-only"> to </span> {shortName(trip.destination)}
            </h1>
            {trip.weather.map((point) => {
              const today = point.forecast[0];
              if (!today) return null;
              return (
                <p key={point.name} className="map-weather">
                  {shortName(point)}: {today.condition.toLowerCase()},{" "}
                  <span className="data">
                    {Math.round(today.temp_max)}&deg;/{Math.round(today.temp_min)}&deg;F
                  </span>
                  {today.precip_probability >= 40 && (
                    <span className="warn"> {today.precip_probability}% rain</span>
                  )}
                </p>
              );
            })}
          </>
        ) : (
          <>
            <h1>No trip yet</h1>
            <p className="map-weather">Ask the agent for a route to see it drawn here.</p>
          </>
        )}
        <div className="segmented" role="group" aria-label="Map zoom">
          <button type="button" aria-pressed={view === "usa"} onClick={() => setMode("usa")}>
            Full USA
          </button>
          <button type="button" aria-pressed={view === "route"} disabled={!hasRoutes} onClick={() => setMode("route")}>
            Fit route
          </button>
          {stops && (
            <button type="button" aria-pressed={view === "stops"} onClick={() => setMode("stops")}>
              Stops
            </button>
          )}
        </div>
      </div>

      {stops && (
        <section className="poi-list" aria-label="Stops">
          <h2>
            Stops near {stops.label} <span className="data">({stops.items.length})</span>
          </h2>
          <ol>
            {stops.items.map((poi) => (
              <li
                key={poi.id}
                className={hoveredPoi === poi.id ? "active" : undefined}
                onMouseEnter={() => setHoveredPoi(poi.id)}
                onMouseLeave={() => setHoveredPoi(null)}
              >
                <span className="poi-name">{poi.name}</span>
                <span className="poi-category">{poi.category.replace(/_/g, " ")}</span>
              </li>
            ))}
          </ol>
        </section>
      )}

      {error && (
        <p className="map-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
