import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import type { Place, PlaceOption } from "../types";
import { citiesIn } from "../data/cities";
import type { City } from "../data/cities";
import { CALLOUT_POINTS, LABEL_POINTS, STATE_CODE_BY_FIPS } from "../data/states";
import { ROUTE_66, ROUTE_66_TITLE } from "../data/route66";
import { highwaysAlong, linesOf, useHighways } from "../highways";
import type { Highway } from "../highways";
import CityPopover from "./CityPopover";
import PlacesPanel from "./PlacesPanel";
import DirectionsPanel, { ManeuverIcon } from "./DirectionsPanel";
import { ARRIVE, buildDirections } from "../directions";
import { useMapZoom, ZOOM_BUTTON_FACTOR } from "../useMapZoom";

const MAX_ROUTE_POINTS = 500;
// Footprint of the RouteComparison overlay, including its margins (and its "via I-5" line).
const CARDS_HEIGHT = 305;
const CARDS_WIDTH = 520;
// Footprint of the title, weather line and zoom toggle in the top left.
const HEADER_HEIGHT = 180;
const HEADER_WIDTH = 300;

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
// Width reserved on the left for the campsites-and-food list (300 px wide, plus its margin)
const PLACES_LIST_WIDTH = 330;
// The backend searches a 2 km box, so keep at least this much around the stops (degrees).
const STOPS_PADDING = 0.01;

// Highway shields: at most this many, at least this far apart (px), and clear of the map's edge
const MAX_SHIELDS = 36;
const SHIELD_SPACING = { usa: 110, zoomed: 75 };
const SHIELD_MARGIN = 18;
// Where the Route 66 label goes: the first of these towns that is on screen
const ROUTE_66_LABEL_AT: [number, number][] = [
  [-101.8313, 35.222], // Amarillo
  [-111.6513, 35.1983], // Flagstaff
  [-94.5133, 37.0842], // Joplin
  [-117.0173, 34.8958], // Barstow
];
const ROUTE_66_ID = "route-66";
// Zooming to a directions step shows about this many miles each side of the maneuver
const STEP_VIEW_MILES = 0.8;
// From this far in, routes are drawn from their full served line rather than the 500-point version
const FULL_DETAIL_K = 3;

interface Shield {
  highway: Highway;
  x: number;
  y: number;
  onRoute: boolean;
}

/** Points along a highway to try for its shield, from the middle of its longest line outwards. */
function shieldCandidates(highway: Highway): [number, number][] {
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

const shieldWidth = (text: string) => 9 + text.length * 6.6;

const shortName = (place: Place) => place.name.split(",")[0];

const cityLabel = (city: City) => `${city.name}, ${city.state}`;

export default function RouteMap() {
  const { trip, tripLoading, selectedRouteId, hoverMile, pois, places, selectRoute, error, busy, sendMessage } =
    useTrip();
  const [hoveredPoi, setHoveredPoi] = useState<number | null>(null);
  const [hoveredPlace, setHoveredPlace] = useState<string | null>(null);
  // The Interstates and US routes, drawn faded; null until loaded (or if they can't be)
  const highways = useHighways();
  const [hoveredHighway, setHoveredHighway] = useState<string | null>(null);

  // Campsites and places to eat, once each (a place can be found from two stops); a pick wins
  const placeMarkers = useMemo(() => {
    const byId = new Map<string, PlaceOption>();
    for (const group of places ?? []) {
      for (const place of group.places) {
        const seen = byId.get(place.id);
        if (!seen || (place.recommended && !seen.recommended)) byId.set(place.id, place);
      }
    }
    // picks last, so they draw on top
    return [...byId.values()].sort((a, b) => Number(!!a.recommended) - Number(!!b.recommended));
  }, [places]);
  const picks = useMemo(() => placeMarkers.filter((p) => p.recommended), [placeMarkers]);
  const hasPlaces = placeMarkers.length > 0 || (places?.length ?? 0) > 0;
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

  // Directions: for the selected route, or the fastest until one is picked
  const [directionsOpen, setDirectionsOpen] = useState(false);
  const [activeStep, setActiveStep] = useState<number | null>(null);
  const [hoveredStep, setHoveredStep] = useState<number | null>(null);
  const directionsRoute =
    routes.find((r) => r.route.id === selectedRouteId)?.route ??
    routes.find((r) => r.route.route_type === "fastest")?.route ??
    null;
  const directions = useMemo(
    () => (directionsRoute ? buildDirections(directionsRoute, highways) : null),
    [directionsRoute, highways],
  );
  const showDirections = directionsOpen && directionsRoute !== null;
  // a new route (another trip, or the other route selected) starts the list from the top
  useEffect(() => {
    setActiveStep(null);
    setHoveredStep(null);
  }, [directionsRoute]);
  // the left-hand list in view: directions while open, else the places list, else the stops list
  const leftPanelWidth = showDirections || hasPlaces ? PLACES_LIST_WIDTH : stops ? STOPS_LIST_WIDTH : 0;

  const fitted = useMemo(() => {
    if (width === 0 || height === 0) return null;
    const side = zoomed ? 70 : 24;
    const left = leftPanelWidth || side;
    const bottom = zoomed ? 50 : 24;
    let target: GeoPermissibleObjects = lower48;
    if (view === "route") {
      target = { type: "GeometryCollection", geometries: routes.map((r) => r.line) };
    } else if (view === "stops" && stops) {
      // the stops, and the campsites and places to eat picked near them
      const points = [...stops.items, ...picks];
      const lons = points.map((p) => p.lon);
      const lats = points.map((p) => p.lat);
      target = {
        type: "MultiPoint",
        coordinates: [
          ...points.map((p) => [p.lon, p.lat]),
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
  }, [width, height, view, hasRoutes, routes, stops, picks, leftPanelWidth, zoomed]);

  // Zoom and pan on top of the fitted view
  const svgRef = useRef<SVGSVGElement>(null);
  const zoom = useMapZoom(svgRef, fitted, { width, height });
  const projection = zoom.projection;
  // Zoomed in from the fit: draw routes at full detail and give US routes shields too
  const closeUp = zoomed || zoom.k > 1.5;

  const setView = (next: FitMode) => {
    setMode(next);
    zoom.reset();
  };

  /** Zooms to a step's maneuver (its start; the arrival's end), about a mile around it. */
  const showStep = (index: number) => {
    const d = directions?.[index];
    if (!d) return;
    setActiveStep(index);
    const [lon, lat] = d.step.type === ARRIVE ? d.step.end : d.step.start;
    const dLat = STEP_VIEW_MILES / 69.17;
    const dLon = dLat / Math.cos((lat * Math.PI) / 180);
    zoom.zoomTo(
      [
        [lon - dLon, lat - dLat],
        [lon + dLon, lat + dLat],
      ],
      // below the route cards, right of the directions list
      { x0: leftPanelWidth + 30, y0: CARDS_HEIGHT, x1: width - 30, y1: height - 30 },
    );
  };

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

  // The highways the selected route drives on: drawn stronger than the rest of the network
  const selectedGeometry = routes.find((r) => r.route.id === selectedRouteId)?.route.geometry ?? null;
  const onRoute = useMemo(
    () => (highways && selectedGeometry ? highwaysAlong(selectedGeometry, highways) : []),
    [highways, selectedGeometry],
  );
  const onRouteIds = useMemo(() => new Set(onRoute.map((h) => h.highway.id)), [onRoute]);

  const network = useMemo(() => {
    if (!projection || !highways) return null;
    const draw = geoPath(projection);
    return {
      // US routes first, so Interstates draw over them
      highways: [...highways]
        .sort((a, b) => Number(a.kind === "interstate") - Number(b.kind === "interstate"))
        .map((highway) => ({ highway, d: draw(highway.geometry) ?? "" })),
      route66: draw(ROUTE_66) ?? "",
    };
  }, [projection, highways]);

  // Shields: the selected route's highways first, on the route itself, then the rest of the network,
  // spaced out greedily. Zoomed out, only Interstates get one.
  const shields = useMemo(() => {
    if (!projection || !highways) return [];
    const spacing = closeUp ? SHIELD_SPACING.zoomed : SHIELD_SPACING.usa;
    const placed: Shield[] = [];
    // trip endpoints keep their labels clear
    const blocked = (trip ? [trip.origin, trip.destination] : [])
      .map((p) => projection([p.lon, p.lat]))
      .filter((xy): xy is [number, number] => xy !== null);
    // nor under the overlays: the title and zoom toggle, the route cards, the places or stops list
    const covered: [number, number, number, number][] = [[0, 0, HEADER_WIDTH, HEADER_HEIGHT]];
    if (hasRoutes) covered.push([width - CARDS_WIDTH, 0, width, CARDS_HEIGHT]);
    if (leftPanelWidth) covered.push([0, 0, leftPanelWidth, height]);
    const onScreen = (x: number, y: number) =>
      x > SHIELD_MARGIN &&
      y > SHIELD_MARGIN &&
      x < width - SHIELD_MARGIN &&
      y < height - SHIELD_MARGIN &&
      covered.every(([x0, y0, x1, y1]) => x < x0 - SHIELD_MARGIN || x > x1 + SHIELD_MARGIN || y < y0 || y > y1 + SHIELD_MARGIN);
    const clear = (x: number, y: number, gap: number) =>
      placed.every((s) => Math.hypot(s.x - x, s.y - y) >= gap) &&
      blocked.every(([bx, by]) => Math.hypot(bx - x, by - y) >= 40);
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
      for (const point of shieldCandidates(highway)) {
        const xy = projection(point);
        if (xy && onScreen(xy[0], xy[1]) && clear(xy[0], xy[1], spacing)) {
          placed.push({ highway, x: xy[0], y: xy[1], onRoute: false });
          break;
        }
      }
    }
    return placed;
  }, [projection, highways, onRoute, onRouteIds, closeUp, width, height, trip, hasRoutes, leftPanelWidth]);

  const route66Label = useMemo(() => {
    if (!projection) return null;
    for (const town of ROUTE_66_LABEL_AT) {
      const xy = projection(town);
      if (xy && xy[0] > 60 && xy[1] > 30 && xy[0] < width - 60 && xy[1] < height - 30) return xy;
    }
    return null;
  }, [projection, width, height]);

  return (
    <div className="route-map" ref={ref}>
      {projection && path && base && (
        <svg
          ref={svgRef}
          className={zoom.dragging ? "map-svg dragging" : "map-svg"}
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

          {/* The highway network, faded; the selected route's highways stronger, a hovered one strongest */}
          {network && (
            <g className="highways" aria-hidden="true">
              {network.highways.map(({ highway, d }) => {
                const classes = ["highway", highway.kind];
                if (onRouteIds.has(highway.id)) classes.push("on-route");
                if (hoveredHighway === highway.id) classes.push("active");
                return <path key={highway.id} className={classes.join(" ")} d={d} />;
              })}
              <path className={hoveredHighway === ROUTE_66_ID ? "route66 active" : "route66"} d={network.route66} />
              {/* hover targets, once there's a trip: before that a click on a state opens the city picker */}
              {!picking && (
                <g className="highway-hits">
                  {network.highways.map(({ highway, d }) => (
                    <path
                      key={highway.id}
                      className="highway-hit"
                      d={d}
                      onMouseEnter={() => setHoveredHighway(highway.id)}
                      onMouseLeave={() => setHoveredHighway((h) => (h === highway.id ? null : h))}
                    >
                      <title>{highway.name}</title>
                    </path>
                  ))}
                  <path
                    className="highway-hit"
                    d={network.route66}
                    onMouseEnter={() => setHoveredHighway(ROUTE_66_ID)}
                    onMouseLeave={() => setHoveredHighway((h) => (h === ROUTE_66_ID ? null : h))}
                  >
                    <title>{ROUTE_66_TITLE}</title>
                  </path>
                </g>
              )}
            </g>
          )}

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
            const d = path(zoom.k >= FULL_DETAIL_K ? route.geometry : line) ?? "";
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

          {/* The directions step in view (or under the pointer in the list): its stretch, and the maneuver */}
          {showDirections &&
            directions &&
            [hoveredStep, activeStep]
              .filter((i, n, all): i is number => i !== null && all.indexOf(i) === n)
              .map((i) => {
                const d = directions[i];
                const at = d.step.type === ARRIVE ? d.step.end : d.step.start;
                const xy = projection([at[0], at[1]]);
                const current = i === activeStep;
                return (
                  <g key={`step-${i}`} className={current ? "map-step active" : "map-step"} aria-hidden="true">
                    <path className="map-step-line" d={path({ type: "LineString", coordinates: d.stretch }) ?? ""} />
                    {xy && (
                      <g transform={`translate(${xy[0]} ${xy[1]})`}>
                        <circle r={current ? 13 : 10} />
                        <g transform={`translate(${current ? -9 : -7} ${current ? -9 : -7})`}>
                          <ManeuverIcon type={d.step.type} size={current ? 18 : 14} />
                        </g>
                      </g>
                    )}
                  </g>
                );
              })}

          {/* Highway shields over the routes, so the selected route's own shields read on top of it */}
          {network && (
            <g className={picking ? "shields passive" : "shields"} aria-hidden="true">
              {route66Label && (
                <text
                  className={hoveredHighway === ROUTE_66_ID ? "route66-label active" : "route66-label"}
                  x={route66Label[0]}
                  y={route66Label[1] - 9}
                  textAnchor="middle"
                >
                  Route 66
                </text>
              )}
              {shields.map(({ highway, x, y, onRoute: on }) => {
                const text = highway.kind === "interstate" ? `I-${highway.number}` : highway.number;
                const w = shieldWidth(text);
                const classes = ["shield", highway.kind];
                if (on) classes.push("on-route");
                if (hoveredHighway === highway.id) classes.push("active");
                return (
                  <g
                    key={highway.id}
                    className={classes.join(" ")}
                    transform={`translate(${x} ${y})`}
                    onMouseEnter={() => setHoveredHighway(highway.id)}
                    onMouseLeave={() => setHoveredHighway((h) => (h === highway.id ? null : h))}
                  >
                    <title>{highway.name}</title>
                    <rect x={-w / 2} y={-7.5} width={w} height={15} rx={highway.kind === "interstate" ? 3.5 : 1} />
                    <text textAnchor="middle" dominantBaseline="central">
                      {text}
                    </text>
                  </g>
                );
              })}
            </g>
          )}

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

          {placeMarkers.map((place) => {
            const xy = projection([place.lon, place.lat]);
            if (!xy) return null;
            const [x, y] = xy;
            const size = place.recommended ? 8 : 5;
            const classes = ["place-marker", place.kind];
            if (place.recommended) classes.push("picked");
            if (hoveredPlace === place.id) classes.push("active");
            return (
              <g
                key={place.id}
                className={classes.join(" ")}
                onMouseEnter={() => setHoveredPlace(place.id)}
                onMouseLeave={() => setHoveredPlace(null)}
              >
                <title>
                  {[place.name, ...(place.reason ? [place.reason] : place.facts.slice(0, 3))].join(" · ")}
                </title>
                {place.kind === "camping" ? (
                  // a tent
                  <path d={`M${x} ${y - size}L${x + size} ${y + size * 0.8}L${x - size} ${y + size * 0.8}Z`} />
                ) : (
                  <circle cx={x} cy={y} r={size * 0.8} />
                )}
                {/* a night's campsite and dinner picks sit close together: name tents on the right, food on the left */}
                {(place.recommended || hoveredPlace === place.id) && (
                  <text
                    x={place.kind === "camping" ? x + size + 4 : x - size - 4}
                    y={y}
                    textAnchor={place.kind === "camping" ? "start" : "end"}
                    dominantBaseline="middle"
                  >
                    {place.name}
                  </text>
                )}
              </g>
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
                  <g className="poi-cluster" onClick={() => setView("stops")}>
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
        <div className="map-header-controls">
          <div className="segmented" role="group" aria-label="Map view">
            {/* pressed only while showing that fit, not after zooming or panning away from it */}
            <button type="button" aria-pressed={view === "usa" && !zoom.zoomed} onClick={() => setView("usa")}>
              Full USA
            </button>
            <button
              type="button"
              aria-pressed={view === "route" && !zoom.zoomed}
              disabled={!hasRoutes}
              onClick={() => setView("route")}
            >
              Fit route
            </button>
            {stops && (
              <button type="button" aria-pressed={view === "stops" && !zoom.zoomed} onClick={() => setView("stops")}>
                Stops
              </button>
            )}
          </div>
          {hasRoutes && (
            <button
              type="button"
              className="directions-toggle"
              aria-pressed={directionsOpen}
              onClick={() => setDirectionsOpen((open) => !open)}
            >
              Directions
            </button>
          )}
        </div>
      </div>

      <div className="zoom-controls" role="group" aria-label="Zoom">
        <button type="button" aria-label="Zoom in" onClick={() => zoom.zoomBy(ZOOM_BUTTON_FACTOR)}>
          +
        </button>
        <button type="button" aria-label="Zoom out" onClick={() => zoom.zoomBy(1 / ZOOM_BUTTON_FACTOR)}>
          &minus;
        </button>
        <button type="button" aria-label="Reset zoom" disabled={!zoom.zoomed} onClick={zoom.reset}>
          &#x2922;
        </button>
      </div>

      {showDirections && directionsRoute ? (
        <DirectionsPanel
          routeType={directionsRoute.route_type}
          directions={directions}
          distanceMiles={directionsRoute.distance_miles}
          durationSeconds={directionsRoute.duration_seconds}
          active={activeStep}
          onSelect={showStep}
          onHover={setHoveredStep}
          onClose={() => setDirectionsOpen(false)}
        />
      ) : places && places.length > 0 ? (
        <PlacesPanel groups={places} hovered={hoveredPlace} onHover={setHoveredPlace} />
      ) : stops && (
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
