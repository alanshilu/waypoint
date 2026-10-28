import { useTrip } from "../state/TripProvider";

/** In place of the chat on a trip opened from its share link: says what it is, and offers a trip of your own. */
export default function SharedPanel() {
  const { trip, tripLoading, plannedStops, places } = useTrip();
  const nights = (plannedStops ?? []).filter((s) => s.kind === "overnight").length;
  return (
    <aside className="chat shared-panel" aria-label="Shared trip">
      <div className="chat-body">
        <header className="chat-head">
          <span className="brand">Waypoint</span>
          <span className="mode-badge">Shared trip</span>
        </header>
        <div className="shared-body">
          <h2>Shared trip</h2>
          {tripLoading ? (
            <p role="status">Opening the trip…</p>
          ) : trip ? (
            <p>
              A read-only copy of a trip planned with Waypoint: both routes
              {trip.selected_route_id !== null ? ", the one that was picked" : ""}
              {nights > 0 ? `, ${nights} overnight stop${nights === 1 ? "" : "s"}` : ""}
              {(places?.length ?? 0) > 0 ? " and the places found along the way" : ""}. Opening it runs no agent and changes
              nothing. Picking a route here only changes this page.
            </p>
          ) : (
            <p>This trip couldn't be opened. The link may be wrong, or the trip was removed.</p>
          )}
          <a className="shared-own" href="/">
            Plan your own trip
          </a>
        </div>
      </div>
    </aside>
  );
}
