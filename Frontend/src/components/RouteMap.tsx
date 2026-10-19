import { useCallback, useEffect, useMemo, useState } from "react";
import type { KeyboardEvent } from "react";
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
import { citiesIn } from "../data/cities";
import type { City } from "../data/cities";
import { CALLOUT_POINTS, LABEL_POINTS, STATE_CODE_BY_FIPS } from "../data/states";
import CityPopover from "./CityPopover";

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

const cityLabel = (city: City) => `${city.name}, ${city.state}`;

export default function RouteMap() {
  const { trip, tripLoading, selectedRouteId, hoverMile, pois, selectRoute, error, busy, sendMessage } = useTrip();
  const [hoveredPoi, setHoveredPoi] = useState<number | null>(null);
  const [ref, { width, height }] = useSize<HTMLDivElement>();
  const [mode, setMode] = useState<FitMode>("usa");

  // State labels and, before a trip exists, the city picker
  const [hoveredState, setHoveredState] = useState<string | null>(null);
  const [pinnedState, setPinnedState] = useState<string | null>(null);
  const [openedByKeyboard, setOpenedByKeyboard] = useState(false);
  const [origin, setOrigin] = useState<City | null>(null);
  const [destination, setDestination] = useState<City | null>(null);
  const picking = !trip && !tripLoading;

  // Zoom to a new trip when it arrives; the toggle takes over from there.
  const tripId = trip?.id ?? null;
  useEffect(() => {
    setMode(tripId === null ? "usa" : "route");
    // A trip replaces the picker; start it fresh if the trip goes away
    setPinnedState(null);
    setOrigin(null);
    setDestination(null);
  }, [tripId]);

  // A pinned popover closes on a click or tap anywhere but itself or a state (which re-pins)
  useEffect(() => {
    if (!pinnedState) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Element | null;
      if (target?.closest(".city-popover, .map-state")) return;
      setPinnedState(null);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [pinnedState]);

  const closePopover = useCallback(() => {
    const fips = pinnedState;
    setPinnedState(null);
    setHoveredState(null);
    // back to the state it was opened from, for keyboard users
    if (fips) document.querySelector<SVGPathElement>(`.map-state[data-fips="${fips}"]`)?.focus();
  }, [pinnedState]);

  const pickCity = (city: City) => {
    if (busy) return;
    if (!origin) {
      setOrigin(city);
    } else if (!destination) {
      setDestination(city);
      sendMessage(`Plan a trip from ${cityLabel(origin)} to ${cityLabel(city)}`);
    }
    setPinnedState(null);
    setHoveredState(null);
  };

  const resetPicks = () => {
    setOrigin(null);
    setDestination(null);
  };

  const onStateKeyDown = (fips: string) => (event: KeyboardEvent) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      setOpenedByKeyboard(true);
      setPinnedState(fips);
    } else if (event.key === "Escape") {
      setPinnedState(null);
    }
  };

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

  const path = projection ? geoPath(projection) : null;
  // Draw the selected route last so it sits on top.
  const ordered = [...routes].sort(
    (a, b) => Number(a.route.id === selectedRouteId) - Number(b.route.id === selectedRouteId),
  );

  return (
    <div className="route-map" ref={ref}>
      {projection && path && base && (
        <svg
          width={width}
          height={height}
          role={picking ? undefined : "img"}
          aria-label={picking ? undefined : "Map of the lower 48 states with trip routes"}
        >
          <path className="map-graticule" d={base.graticule} />
          <g role={picking ? "group" : undefined} aria-label={picking ? "States: open one to pick a city" : undefined}>
            {base.states.map((s) => {
              const classes = ["map-state"];
              if (picking) classes.push("pickable");
              if (picking && (s.id === pinnedState || (!pinnedState && s.id === hoveredState))) classes.push("active");
              return (
                <path
                  key={s.id}
                  className={classes.join(" ")}
                  d={s.d}
                  data-fips={s.id}
                  onMouseEnter={() => setHoveredState(s.id)}
                  onMouseLeave={() => setHoveredState((current) => (current === s.id ? null : current))}
                  {...(picking && {
                    tabIndex: 0,
                    role: "button",
                    "aria-label": `${s.name}: pick a city`,
                    "aria-expanded": pinnedState === s.id,
                    onClick: (event) => {
                      event.stopPropagation();
                      setOpenedByKeyboard(false);
                      setPinnedState((current) => (current === s.id ? null : s.id));
                    },
                    onKeyDown: onStateKeyDown(s.id),
                  })}
                />
              );
            })}
          </g>

          {/* Below the routes and markers, and never in the way of the pointer */}
          <g className="state-labels" aria-hidden="true">
            {base.states.map((s) => {
              const full = s.id === hoveredState || (picking && s.id === pinnedState);
              const classes = ["state-label"];
              if (s.small || s.callout) classes.push("small");
              if (s.callout) classes.push("callout");
              if (full) classes.push("full");
              return (
                <g key={s.id}>
                  {s.callout && <line className="state-leader" x1={s.x} y1={s.y} x2={s.label.x - 8} y2={s.label.y} />}
                  <text className={classes.join(" ")} x={s.label.x} y={s.label.y}>
                    {full ? s.name : s.code}
                  </text>
                </g>
              );
            })}
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
            <p className="map-weather">Ask the agent for a route, or pick a start and an end city on the map.</p>
            {picking && (origin || destination) && (
              <div className="trip-picks" role="group" aria-label="Trip from the map">
                <span className="trip-pick">
                  <span className="trip-pick-label">From</span> {origin ? cityLabel(origin) : "…"}
                </span>
                <span className="trip-pick">
                  <span className="trip-pick-label">To</span>{" "}
                  {destination ? cityLabel(destination) : <span className="trip-pick-empty">pick a city</span>}
                </span>
                <button type="button" className="trip-picks-clear" disabled={busy} onClick={resetPicks}>
                  Clear
                </button>
              </div>
            )}
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

      {picking &&
        !destination &&
        base &&
        (() => {
          const fips = pinnedState ?? hoveredState;
          const state = fips ? base.states.find((s) => s.id === fips) : null;
          if (!state) return null;
          return (
            <CityPopover
              stateName={state.name}
              cities={citiesIn(state.code)}
              picking={origin ? "destination" : "origin"}
              origin={origin}
              x={state.x}
              y={state.y}
              mapWidth={width}
              mapHeight={height}
              pinned={pinnedState === state.id}
              focusOnOpen={openedByKeyboard}
              onPick={pickCity}
              onClose={closePopover}
            />
          );
        })()}

      {tripLoading && (
        <p className="map-loading" role="status">
          Loading your trip&hellip;
        </p>
      )}

      {error && (
        <p className="map-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
