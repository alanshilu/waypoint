/** Where the map's HTML overlays sit, so the map can keep its content clear of them. */

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

/** The rectangles the overlays cover on a map of this size. */
export function coveredRects(width: number, height: number, hasRoutes: boolean, leftPanelWidth: number): Rect[] {
  const covered: Rect[] = [[0, 0, HEADER_WIDTH, HEADER_HEIGHT]];
  if (hasRoutes) covered.push([width - CARDS_WIDTH, 0, width, CARDS_HEIGHT]);
  if (leftPanelWidth) covered.push([0, 0, leftPanelWidth, height]);
  return covered;
}

export type FitMode = "usa" | "route" | "stops";
