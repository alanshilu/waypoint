import { useState } from "react";
import { GOOGLE_MAPS_MOBILE_WAYPOINTS, googleMapsDirectionsUrl, gpxFileName, routeGpx } from "../export";
import { routeName } from "../format";
import { shareUrl } from "../share";
import { useTrip } from "../state/TripProvider";

/** Copies text, or says it couldn't (an insecure page or a refused permission). */
async function copy(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function download(fileName: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Share the trip, open it in Google Maps, or download the selected route as GPX. */
export default function TripActions() {
  const { trip, selectedRouteId, plannedStops, shared } = useTrip();
  const [status, setStatus] = useState<{ text: string; link?: string } | null>(null);
  if (!trip || trip.routes.length === 0) return null;

  const route = trip.routes.find((r) => r.id === selectedRouteId) ?? trip.routes.find((r) => r.route_type === "fastest") ?? trip.routes[0];
  const stops = plannedStops ?? [];
  const maps = googleMapsDirectionsUrl(trip.origin, trip.destination, stops);
  const title = `${trip.origin.name.split(",")[0]} to ${trip.destination.name.split(",")[0]} (${routeName(route.route_type)})`;
  const canShare = Boolean(trip.public_id) && !shared;

  const share = async () => {
    const link = shareUrl(window.location.origin, trip.public_id!);
    setStatus((await copy(link)) ? { text: "Link copied" } : { text: "Copy this link:", link });
  };

  const mapsNote =
    `Opens directions from ${trip.origin.name.split(",")[0]} to ${trip.destination.name.split(",")[0]}` +
    (maps.waypoints ? ` through ${maps.waypoints} overnight stop${maps.waypoints === 1 ? "" : "s"}` : "") +
    `. Google picks its own roads between them. Phones use only the first ${GOOGLE_MAPS_MOBILE_WAYPOINTS} stops` +
    (maps.dropped ? `; ${maps.dropped} later stop${maps.dropped === 1 ? " is" : "s are"} past Google's limit and left out.` : ".");

  return (
    <div className="trip-actions" role="group" aria-label="Share and export">
      {canShare && (
        <button type="button" className="trip-action" onClick={share}>
          Share
        </button>
      )}
      <a className="trip-action" href={maps.url} target="_blank" rel="noreferrer" title={mapsNote}>
        Google Maps<span className="sr-only"> (opens in a new tab). {mapsNote}</span>
      </a>
      <button
        type="button"
        className="trip-action"
        title={`The ${routeName(route.route_type)} route as a GPX track, with the overnight stops`}
        onClick={() => download(gpxFileName(title), routeGpx({ name: title, origin: trip.origin, destination: trip.destination, geometry: route.geometry, stops }), "application/gpx+xml")}
      >
        GPX
      </button>
      {maps.dropped > 0 && (
        <span className="trip-action-note">Google Maps link: first {maps.waypoints} of {maps.waypoints + maps.dropped} stops</span>
      )}
      <span className="trip-action-status" role="status">
        {status?.text}
        {status?.link && (
          <input className="trip-action-link" readOnly value={status.link} aria-label="Share link" onFocus={(e) => e.currentTarget.select()} />
        )}
      </span>
    </div>
  );
}
