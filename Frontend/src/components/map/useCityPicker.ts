import { useCallback, useEffect, useState } from "react";
import type { KeyboardEvent } from "react";
import type { City } from "../../data/cities";

export const cityLabel = (city: City) => `${city.name}, ${city.state}`;

/**
 * Before a trip exists, the map picks one: open a state (hover, click or Enter), pick a start city, then an
 * end city, and the trip is asked for. A click anywhere but a state or the popover closes a pinned popover.
 */
export function useCityPicker({ tripId, busy, onTrip }: { tripId: number | null; busy: boolean; onTrip: (message: string) => void }) {
  const [hoveredState, setHoveredState] = useState<string | null>(null);
  const [pinnedState, setPinnedState] = useState<string | null>(null);
  const [openedByKeyboard, setOpenedByKeyboard] = useState(false);
  const [origin, setOrigin] = useState<City | null>(null);
  const [destination, setDestination] = useState<City | null>(null);

  // A trip replaces the picker; start it fresh if the trip goes away
  useEffect(() => {
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
      onTrip(`Plan a trip from ${cityLabel(origin)} to ${cityLabel(city)}`);
    }
    setPinnedState(null);
    setHoveredState(null);
  };

  const resetPicks = () => {
    setOrigin(null);
    setDestination(null);
  };

  /** A click on a state toggles its popover */
  const toggleState = (fips: string) => {
    setOpenedByKeyboard(false);
    setPinnedState((current) => (current === fips ? null : fips));
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

  return {
    hoveredState,
    setHoveredState,
    pinnedState,
    openedByKeyboard,
    origin,
    destination,
    pickCity,
    resetPicks,
    closePopover,
    toggleState,
    onStateKeyDown,
  };
}

export type CityPicker = ReturnType<typeof useCityPicker>;
