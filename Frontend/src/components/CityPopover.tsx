import { useEffect, useRef } from "react";
import type { KeyboardEvent } from "react";
import type { City } from "../data/cities";

interface Props {
  stateName: string;
  cities: City[];
  /** Which end the next pick sets */
  picking: "origin" | "destination";
  /** Already chosen as the origin; can't also be the destination */
  origin: City | null;
  /**
   * Pinned (the state was clicked, tapped or opened with Enter): the cities can be picked.
   * Otherwise it is a hover preview that ignores the pointer, so it never covers the next state.
   */
  pinned: boolean;
  /** Anchor point in map pixels, and the map's size for keeping the popover inside it */
  x: number;
  y: number;
  mapWidth: number;
  mapHeight: number;
  /** Move focus to the first city when it opens (opened from the keyboard) */
  focusOnOpen: boolean;
  onPick: (city: City) => void;
  onClose: () => void;
}

const WIDTH = 210;
const HEIGHT_ESTIMATE = 220;
const MARGIN = 8;

/** The cities of one state, to pick a trip's origin or destination from. */
export default function CityPopover(props: Props) {
  const { stateName, cities, picking, origin, pinned, x, y, mapWidth, mapHeight, focusOnOpen } = props;
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (pinned && focusOnOpen) ref.current?.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus();
  }, [pinned, focusOnOpen, stateName]);

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      props.onClose();
    }
  };

  // Beside the state's label, kept inside the map
  const left = Math.min(Math.max(MARGIN, x + 14), mapWidth - WIDTH - MARGIN);
  const top = Math.min(Math.max(MARGIN, y - 24), mapHeight - HEIGHT_ESTIMATE - MARGIN);
  const isOrigin = (city: City) => origin?.name === city.name && origin.state === city.state;
  const verb = picking === "origin" ? "Start from" : "Drive to";

  return (
    <div
      ref={ref}
      className={pinned ? "city-popover" : "city-popover preview"}
      style={{ left, top, width: WIDTH }}
      role={pinned ? "dialog" : undefined}
      aria-label={pinned ? `Cities in ${stateName}` : undefined}
      aria-hidden={pinned ? undefined : true}
      onKeyDown={onKeyDown}
      onClick={(event) => event.stopPropagation()}
    >
      <h2>{stateName}</h2>
      <p className="city-popover-hint">{pinned ? verb : `${verb}: click the state to choose`}</p>
      <ul>
        {cities.map((city) => (
          <li key={city.name}>
            <button
              type="button"
              tabIndex={pinned ? undefined : -1}
              disabled={isOrigin(city)}
              onClick={() => props.onPick(city)}
            >
              {city.name}
              {isOrigin(city) && <span className="city-popover-tag"> start</span>}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
