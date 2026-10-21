import type { Trip } from "../../types";
import type { FitMode } from "./layout";
import { shortName } from "./Markers";
import { cityLabel } from "./useCityPicker";
import type { CityPicker } from "./useCityPicker";

interface Props {
  trip: Trip | null;
  /** No trip yet: show the picks made on the map */
  picking: boolean;
  picker: Pick<CityPicker, "origin" | "destination" | "resetPicks">;
  busy: boolean;
  view: FitMode;
  /** Zoomed or panned away from the fit: no view button is pressed */
  zoomed: boolean;
  hasRoutes: boolean;
  hasStops: boolean;
  onView: (view: FitMode) => void;
  directionsOpen: boolean;
  onToggleDirections: () => void;
}

/** Top left: the trip and its weather (or the city picks so far), the view buttons and the Directions toggle. */
export default function MapHeader({ trip, picking, picker, busy, view, zoomed, hasRoutes, hasStops, onView, directionsOpen, onToggleDirections }: Props) {
  const { origin, destination, resetPicks } = picker;
  return (
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
                {today.precip_probability >= 40 && <span className="warn"> {today.precip_probability}% rain</span>}
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
          <button type="button" aria-pressed={view === "usa" && !zoomed} onClick={() => onView("usa")}>
            Full USA
          </button>
          <button type="button" aria-pressed={view === "route" && !zoomed} disabled={!hasRoutes} onClick={() => onView("route")}>
            Fit route
          </button>
          {hasStops && (
            <button type="button" aria-pressed={view === "stops" && !zoomed} onClick={() => onView("stops")}>
              Stops
            </button>
          )}
        </div>
        {hasRoutes && (
          <button type="button" className="directions-toggle" aria-pressed={directionsOpen} onClick={onToggleDirections}>
            Directions
          </button>
        )}
      </div>
    </div>
  );
}
