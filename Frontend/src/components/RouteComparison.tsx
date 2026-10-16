import {
  formatClimbRatio,
  formatDuration,
  formatDurationDelta,
  formatMetres,
  formatMiles,
  formatMilesDelta,
  formatScore,
  routeLabel,
  scenicBreakdown,
  HALF_SCORE_DENSITY_M_PER_MILE,
} from "../format";
import { useTrip } from "../state/TripProvider";
import type { Route } from "../types";

const num = (n: number, digits = 0) =>
  n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });

/** Shows how the backend arrives at the score, using this route's numbers. */
function ScenicTooltip({ route }: { route: Route }) {
  const { elevationDensity, score } = scenicBreakdown(route);
  return (
    <div className="tooltip" role="tooltip">
      <p className="tooltip-title">Scenic score</p>
      <p>Terrain only: climb density d = (ascent + descent) / distance, score = 100 &times; d / (d + {HALF_SCORE_DENSITY_M_PER_MILE})</p>
      <dl>
        <dt>Climb density</dt>
        <dd>
          ({num(route.ascent_m)} + {num(route.descent_m)}) / {num(route.distance_miles, 1)} ={" "}
          {num(elevationDensity, 1)} m/mi
        </dd>
        <dt>Score</dt>
        <dd>
          100 &times; {num(elevationDensity, 1)} / ({num(elevationDensity, 1)} + {HALF_SCORE_DENSITY_M_PER_MILE}) ={" "}
          {num(score, 1)}
        </dd>
      </dl>
      <p className="tooltip-note">
        Higher means hillier. {HALF_SCORE_DENSITY_M_PER_MILE} m/mi scores 50. Drive time is not part of the score; it
        is compared separately on the card.
      </p>
    </div>
  );
}

function RouteCard({ route, baseline }: { route: Route; baseline: Route | null }) {
  const { selectedRouteId, selectRoute } = useTrip();
  const selected = route.id === selectedRouteId;

  // Deltas are against the fastest route. Backroads can come out shorter in
  // miles (the backend asks ORS for "shortest, avoid highways"), so every
  // delta is signed.
  const dTime = baseline ? route.duration_seconds - baseline.duration_seconds : 0;
  const dMiles = baseline ? route.distance_miles - baseline.distance_miles : 0;
  const dScore = baseline ? route.scenic_score - baseline.scenic_score : 0;
  const climb = baseline ? formatClimbRatio(route.ascent_m, baseline.ascent_m) : null;

  return (
    <article className={selected ? "route-card selected" : "route-card"}>
      <button
        type="button"
        className="route-card-head"
        aria-pressed={selected}
        onClick={() => selectRoute(route.id)}
      >
        <span className="route-card-swatch" aria-hidden="true" />
        <span className="route-card-name">{routeLabel(route.route_type)}</span>
        <span className="route-card-state">{selected ? "Selected" : "Select"}</span>
      </button>

      <dl className="route-stats">
        <div>
          <dt>Drive time</dt>
          <dd>
            {formatDuration(route.duration_seconds)}
            {baseline && dTime !== 0 && (
              <span className={dTime > 0 ? "delta warn" : "delta good"}>{formatDurationDelta(dTime)}</span>
            )}
          </dd>
        </div>
        <div>
          <dt>Distance</dt>
          <dd>
            {formatMiles(route.distance_miles)}
            {baseline && Math.round(dMiles) !== 0 && <span className="delta">{formatMilesDelta(dMiles)}</span>}
          </dd>
        </div>
        <div>
          <dt>Total ascent</dt>
          <dd>
            {formatMetres(route.ascent_m)}
            {climb && <span className="delta">{climb}</span>}
          </dd>
        </div>
        <div className="has-tooltip" tabIndex={0}>
          <dt>
            Scenic score <span className="hint">how?</span>
          </dt>
          <dd>
            {formatScore(route.scenic_score)}
            {baseline && dScore !== 0 && (
              <span className={dScore > 0 ? "delta good" : "delta"}>
                {dScore > 0 ? "+" : "−"}
                {formatScore(Math.abs(dScore))}
              </span>
            )}
          </dd>
          <ScenicTooltip route={route} />
        </div>
      </dl>
    </article>
  );
}

export default function RouteComparison() {
  const { trip } = useTrip();
  if (!trip || trip.routes.length === 0) return null;

  const fastest = trip.routes.find((r) => r.route_type === "fastest") ?? null;
  // Fastest first so the baseline is always the left-hand card.
  const ordered = [...trip.routes].sort(
    (a, b) => Number(b.route_type === "fastest") - Number(a.route_type === "fastest"),
  );

  return (
    <section className="route-comparison" aria-label="Route comparison">
      {ordered.map((route) => (
        <RouteCard key={route.id} route={route} baseline={route === fastest ? null : fastest} />
      ))}
    </section>
  );
}
