import { useEffect, useMemo, useRef, useState } from "react";
import { geoPath } from "d3-geo";
import { buildMileIndex, nearestMile, simplifyLine } from "../geo";
import { useTrip } from "../state/TripProvider";
import { useSize } from "../useSize";
import type { PlaceOption } from "../types";
import { citiesIn } from "../data/cities";
import { highwaysAlong, useHighways } from "../highways";
import { ARRIVE, buildDirections } from "../directions";
import { useMapZoom } from "../useMapZoom";
import CityPopover from "./CityPopover";
import PlacesPanel from "./PlacesPanel";
import DirectionsPanel from "./DirectionsPanel";
import { useFittedProjection, useStateShapes } from "./map/fit";
import { CARDS_HEIGHT, coveredRects, PLACES_LIST_WIDTH, STOPS_LIST_WIDTH } from "./map/layout";
import type { FitMode } from "./map/layout";
import { useCityPicker } from "./map/useCityPicker";
import { StateLabels, StatesLayer } from "./map/StatesLayer";
import HighwayLayer from "./map/HighwayLayer";
import ShieldLayer from "./map/ShieldLayer";
import { placeShields, route66LabelAt } from "./map/shields";
import { RouteHoverCar, RouteLines, RouteTags } from "./map/RouteLayer";
import type { MapRoute } from "./map/RouteLayer";
import StepMarkers from "./map/StepMarkers";
import { EndpointMarkers, PlaceMarkers, StopMarkers } from "./map/Markers";
import MapHeader from "./map/MapHeader";
import ZoomControls from "./map/ZoomControls";
import StopsList from "./map/StopsList";

const MAX_ROUTE_POINTS = 500;
// Zooming to a directions step shows about this many miles each side of the maneuver
const STEP_VIEW_MILES = 0.8;
// From this far in, routes are drawn from their full served line rather than the 500-point version
const FULL_DETAIL_K = 3;
// Zoomed in this far from the national fit, US routes get shields too
const CLOSE_UP_K = 1.5;

/**
 * The trip map: composes the layers in ./map (states, highways, routes, markers, overlays) and owns the state
 * they share: the view, the zoom, what's hovered and the directions step in view.
 */
export default function RouteMap() {
  const { trip, tripLoading, selectedRouteId, hoverMile, setHoverMile, pois, places, selectRoute, error, busy, sendMessage } =
    useTrip();
  // The route the pointer is driving along on the map; null when the hover comes from the elevation chart
  const [hoveredRouteId, setHoveredRouteId] = useState<number | null>(null);
  const hoverFrame = useRef<number | null>(null);
  const [hoveredPoi, setHoveredPoi] = useState<number | null>(null);
  const [hoveredPlace, setHoveredPlace] = useState<string | null>(null);
  // The Interstates and US routes, drawn faded; null until loaded (or if they can't be)
  const highways = useHighways();
  const [hoveredHighway, setHoveredHighway] = useState<string | null>(null);
  const [ref, { width, height }] = useSize<HTMLDivElement>();
  const [mode, setMode] = useState<FitMode>("usa");

  const picking = !trip && !tripLoading;
  const tripId = trip?.id ?? null;
  const picker = useCityPicker({ tripId, busy, onTrip: sendMessage });

  // Zoom to a new trip when it arrives; the view buttons take over from there.
  useEffect(() => setMode(tripId === null ? "usa" : "route"), [tripId]);

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

  // A new POI search zooms to its results so the numbered markers are readable.
  const stops = pois && pois.items.length > 0 ? pois : null;
  useEffect(() => {
    if (stops) setMode("stops");
  }, [stops]);

  const routes: MapRoute[] = useMemo(
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

  // Directions: for the selected route, or the fastest until one is picked
  const [directionsOpen, setDirectionsOpen] = useState(false);
  const [activeStep, setActiveStep] = useState<number | null>(null);
  const [hoveredStep, setHoveredStep] = useState<number | null>(null);
  const directionsRoute =
    routes.find((r) => r.route.id === selectedRouteId)?.route ?? routes.find((r) => r.route.route_type === "fastest")?.route ?? null;
  const directions = useMemo(() => (directionsRoute ? buildDirections(directionsRoute, highways) : null), [directionsRoute, highways]);
  const showDirections = directionsOpen && directionsRoute !== null;
  // a new route (another trip, or the other route selected) starts the list from the top
  useEffect(() => {
    setActiveStep(null);
    setHoveredStep(null);
  }, [directionsRoute]);
  // the list on the left: directions while open, else the places list, else the stops list
  const leftPanelWidth = showDirections || hasPlaces ? PLACES_LIST_WIDTH : stops ? STOPS_LIST_WIDTH : 0;

  // The fitted view, then zoom and pan on top of it
  const routeLines = useMemo(() => routes.map((r) => r.line), [routes]);
  // the stops, and the campsites and places to eat picked near them
  const stopPoints = useMemo(() => (stops ? [...stops.items, ...picks] : []), [stops, picks]);
  const fitted = useFittedProjection({ width, height, view, routeLines, stopPoints, hasRoutes, leftPanelWidth });
  const svgRef = useRef<SVGSVGElement>(null);
  const zoom = useMapZoom(svgRef, fitted, { width, height });
  const projection = zoom.projection;
  const closeUp = view !== "usa" || zoom.k > CLOSE_UP_K;
  const shapes = useStateShapes(projection);

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

  // Draw the selected route last so it sits on top.
  const ordered = [...routes].sort((a, b) => Number(a.route.id === selectedRouteId) - Number(b.route.id === selectedRouteId));

  // The highways the selected route drives on: drawn stronger than the rest of the network, shielded first
  const selectedGeometry = routes.find((r) => r.route.id === selectedRouteId)?.route.geometry ?? null;
  const onRoute = useMemo(
    () => (highways && selectedGeometry ? highwaysAlong(selectedGeometry, highways) : []),
    [highways, selectedGeometry],
  );
  const onRouteIds = useMemo(() => new Set(onRoute.map((h) => h.highway.id)), [onRoute]);

  const shields = useMemo(() => {
    if (!projection || !highways) return [];
    const blocked = (trip ? [trip.origin, trip.destination] : [])
      .map((p) => projection([p.lon, p.lat]))
      .filter((xy): xy is [number, number] => xy !== null);
    const covered = coveredRects(width, height, hasRoutes, leftPanelWidth);
    return placeShields({ projection, highways, onRoute, closeUp, width, height, blocked, covered });
  }, [projection, highways, onRoute, closeUp, width, height, trip, hasRoutes, leftPanelWidth]);
  const route66At = useMemo(() => (projection ? route66LabelAt(projection, width, height) : null), [projection, width, height]);

  const path = projection ? geoPath(projection) : null;

  /** The pointer along a route on the map: the mile it's at drives the car, and the elevation chart follows. */
  const onHoverAlong = (routeId: number | null, clientX?: number, clientY?: number) => {
    if (hoverFrame.current !== null) cancelAnimationFrame(hoverFrame.current);
    if (routeId === null) {
      hoverFrame.current = null;
      setHoveredRouteId(null);
      setHoverMile(null);
      return;
    }
    // at most once a frame: a mousemove can fire far more often than the map can redraw
    hoverFrame.current = requestAnimationFrame(() => {
      hoverFrame.current = null;
      const rect = svgRef.current?.getBoundingClientRect();
      const mapRoute = routes.find((r) => r.route.id === routeId);
      const lonLat = rect && projection?.invert?.([clientX! - rect.left, clientY! - rect.top]);
      if (!mapRoute || !lonLat) return;
      setHoveredRouteId(routeId);
      setHoverMile(Math.round(nearestMile(mapRoute.index, lonLat) * 10) / 10);
    });
  };
  // the car drives the hovered route, else the selected one, else the fastest
  const carRouteId =
    hoveredRouteId ?? selectedRouteId ?? routes.find((r) => r.route.route_type === "fastest")?.route.id ?? null;
  const popoverState = picking && !picker.destination && shapes ? shapes.states.find((s) => s.id === (picker.pinnedState ?? picker.hoveredState)) : undefined;

  return (
    <div className="route-map" ref={ref}>
      {projection && path && shapes && (
        <svg
          ref={svgRef}
          className={zoom.dragging ? "map-svg dragging" : "map-svg"}
          width={width}
          height={height}
          role={picking ? undefined : "img"}
          aria-label={picking ? undefined : "Map of the lower 48 states with trip routes"}
        >
          <StatesLayer graticule={shapes.graticule} states={shapes.states} picking={picking} picker={picker} />
          {highways && (
            <HighwayLayer
              projection={projection}
              highways={highways}
              onRouteIds={onRouteIds}
              hovered={hoveredHighway}
              setHovered={setHoveredHighway}
              interactive={!picking}
            />
          )}
          <StateLabels states={shapes.states} picking={picking} hoveredState={picker.hoveredState} pinnedState={picker.pinnedState} />
          <RouteLines
            routes={ordered}
            selectedRouteId={selectedRouteId}
            path={path}
            fullDetail={zoom.k >= FULL_DETAIL_K}
            onSelect={selectRoute}
            onHoverAlong={onHoverAlong}
          />
          <RouteTags routes={ordered} selectedRouteId={selectedRouteId} projection={projection} />
          {showDirections && directions && (
            <StepMarkers directions={directions} active={activeStep} hovered={hoveredStep} path={path} projection={projection} />
          )}
          {highways && (
            <ShieldLayer shields={shields} route66At={route66At} hovered={hoveredHighway} setHovered={setHoveredHighway} interactive={!picking} />
          )}
          {trip && <EndpointMarkers places={[trip.origin, trip.destination]} projection={projection} />}
          {hoverMile !== null && <RouteHoverCar routes={ordered} carRouteId={carRouteId} projection={projection} mile={hoverMile} />}
          <PlaceMarkers places={placeMarkers} projection={projection} hovered={hoveredPlace} onHover={setHoveredPlace} />
          {stops && (
            <StopMarkers
              stops={stops}
              projection={projection}
              expanded={view === "stops"}
              hovered={hoveredPoi}
              onHover={setHoveredPoi}
              onZoomToStops={() => setView("stops")}
            />
          )}
        </svg>
      )}

      <MapHeader
        trip={trip}
        picking={picking}
        picker={picker}
        busy={busy}
        view={view}
        zoomed={zoom.zoomed}
        hasRoutes={hasRoutes}
        hasStops={stops !== null}
        onView={setView}
        directionsOpen={directionsOpen}
        onToggleDirections={() => setDirectionsOpen((open) => !open)}
      />

      <ZoomControls zoom={zoom} />

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
      ) : (
        stops && <StopsList stops={stops} hovered={hoveredPoi} onHover={setHoveredPoi} />
      )}

      {popoverState && (
        <CityPopover
          stateName={popoverState.name}
          cities={citiesIn(popoverState.code)}
          picking={picker.origin ? "destination" : "origin"}
          origin={picker.origin}
          x={popoverState.x}
          y={popoverState.y}
          mapWidth={width}
          mapHeight={height}
          pinned={picker.pinnedState === popoverState.id}
          focusOnOpen={picker.openedByKeyboard}
          onPick={picker.pickCity}
          onClose={picker.closePopover}
        />
      )}

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
