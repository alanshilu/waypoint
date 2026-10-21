import { useEffect, useRef } from "react";
import { formatDuration, formatMiles, routeLabel } from "../format";
import { ARRIVE, isEndpoint, isRoundabout, turnAngle } from "../directions";
import type { Direction } from "../directions";
import type { RouteType } from "../types";

interface Props {
  routeType: RouteType;
  /** Null when the route was saved before the backend kept directions */
  directions: Direction[] | null;
  distanceMiles: number;
  durationSeconds: number;
  active: number | null;
  onSelect: (index: number) => void;
  onHover: (index: number | null) => void;
  onClose: () => void;
}

const stepMiles = (miles: number) => (miles < 0.1 ? `${Math.round(miles * 5280)} ft` : `${miles < 10 ? miles.toFixed(1) : Math.round(miles)} mi`);

/** The maneuver as a small arrow: a turn bends the shaft by its angle; depart, arrive and roundabouts get a mark. */
export function ManeuverIcon({ type, size = 18 }: { type: number; size?: number }) {
  const angle = turnAngle(type);
  return (
    <svg className="maneuver-icon" width={size} height={size} viewBox="-10 -10 20 20" aria-hidden="true">
      {isEndpoint(type) ? (
        type === ARRIVE ? (
          <path d="M-3 7V-7L6 -3.5L-3 0" />
        ) : (
          <circle r="4" />
        )
      ) : isRoundabout(type) ? (
        <>
          <circle r="4.5" className="open" />
          <path d="M4.5 0L8 -3M4.5 0L1 -3" />
        </>
      ) : (
        // up from the bottom, then off at the turn's angle with an arrowhead
        <g>
          <path d="M0 9V1" />
          <g transform={`rotate(${angle ?? 0})`}>
            <path d="M0 1V-7M-3.5 -3.5L0 -7L3.5 -3.5" />
          </g>
        </g>
      )}
    </svg>
  );
}

/** Turn-by-turn directions for one route, beside the map: pick a step to see it on the map. */
export default function DirectionsPanel({ routeType, directions, distanceMiles, durationSeconds, active, onSelect, onHover, onClose }: Props) {
  const list = useRef<HTMLOListElement>(null);

  // keep the active step in view as Next and Previous move through the list
  useEffect(() => {
    if (active === null) return;
    list.current?.querySelector<HTMLElement>(`[data-step="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const count = directions?.length ?? 0;
  const step = (delta: number) => onSelect(Math.min(count - 1, Math.max(0, (active ?? -1) + delta)));

  return (
    <section className="directions-panel" aria-label={`Directions for the ${routeLabel(routeType).toLowerCase()} route`}>
      <header>
        <h2>
          Directions <span className="directions-route">{routeLabel(routeType)}</span>
        </h2>
        <button type="button" className="directions-close" aria-label="Close directions" onClick={onClose}>
          &times;
        </button>
      </header>

      {!directions ? (
        <p className="directions-empty">
          This route was saved before directions were kept. Ask the agent to plan the trip again to get them.
        </p>
      ) : (
        <>
          <p className="directions-summary data">
            {formatMiles(distanceMiles)} &middot; {formatDuration(durationSeconds)} &middot; {count} steps
          </p>
          <div className="directions-nav">
            <button type="button" disabled={active === 0} onClick={() => step(-1)}>
              &lsaquo; Previous
            </button>
            <span className="data" aria-live="polite">
              {active === null ? "Pick a step" : `Step ${active + 1} of ${count}`}
            </span>
            <button type="button" disabled={active === count - 1} onClick={() => step(1)}>
              {active === null ? "Start" : "Next"} &rsaquo;
            </button>
          </div>
          <ol className="directions-list" ref={list}>
            {directions.map((d, i) => (
              <li key={i} data-step={i} className={active === i ? "active" : undefined}>
                <button
                  type="button"
                  aria-current={active === i ? "step" : undefined}
                  onClick={() => onSelect(i)}
                  onMouseEnter={() => onHover(i)}
                  onMouseLeave={() => onHover(null)}
                  onFocus={() => onHover(i)}
                  onBlur={() => onHover(null)}
                >
                  <ManeuverIcon type={d.step.type} />
                  <span className="direction-text">
                    {d.text}
                    <span className="direction-at data">mile {d.atMile.toFixed(d.atMile < 10 ? 1 : 0)}</span>
                  </span>
                  {d.step.distance_miles > 0 && <span className="direction-distance data">{stepMiles(d.step.distance_miles)}</span>}
                </button>
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}
