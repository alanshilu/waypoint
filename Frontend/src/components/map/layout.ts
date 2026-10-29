/** Where the map's HTML overlays sit, so the map can keep its content clear of them. */
import { useEffect, useState } from "react";

/** Footprint of the RouteComparison overlay in the top right, including its margins and "via I-5" line */
export const CARDS_HEIGHT = 305;
export const CARDS_WIDTH = 520;
/** Footprint of the title, weather line and view buttons in the top left */
export const HEADER_HEIGHT = 180;
export const HEADER_WIDTH = 300;
/** Width kept clear on the left for the stops list */
export const STOPS_LIST_WIDTH = 290;
/** Width kept clear on the left for the places or directions list (300 px wide, plus its margin) */
export const PLACES_LIST_WIDTH = 330;

/** [x0, y0, x1, y1] in map pixels */
export type Rect = [number, number, number, number];

/**
 * Narrower than a desktop (the same widths as app.css): the panels stack in one column, the route cards and the
 * lists sit under the map instead of over it, and the map's header spans its top. Below MOBILE_QUERY, phones
 * also get the Chat / Map tabs.
 */
export const STACKED_QUERY = "(max-width: 899px)";
export const MOBILE_QUERY = "(max-width: 767px)";
/** Narrower than this, the map thins out its labels and highway badges so they stay readable */
export const NARROW_MAP_PX = 560;

/** Where the overlays sit in the stacked layout: the header's measured height. */
export interface Stacked {
  headerHeight: number;
}

/** Whether a media query matches, following the window as it resizes. */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => typeof window !== "undefined" && window.matchMedia(query).matches);
  useEffect(() => {
    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [query]);
  return matches;
}

/** Whether the app is in its stacked (phone and tablet) layout. */
export const useStackedLayout = () => useMediaQuery(STACKED_QUERY);
/** Whether the app is in its phone layout, with the Chat / Map tabs. */
export const useMobileLayout = () => useMediaQuery(MOBILE_QUERY);

/** The rectangles the overlays cover on a map of this size. */
export function coveredRects(width: number, height: number, hasRoutes: boolean, leftPanelWidth: number, stacked?: Stacked | null): Rect[] {
  if (stacked) return [[0, 0, width, stacked.headerHeight]];
  const covered: Rect[] = [[0, 0, HEADER_WIDTH, HEADER_HEIGHT]];
  if (hasRoutes) covered.push([width - CARDS_WIDTH, 0, width, CARDS_HEIGHT]);
  if (leftPanelWidth) covered.push([0, 0, leftPanelWidth, height]);
  return covered;
}

export type FitMode = "usa" | "route" | "stops";
