import type { PlaceOption } from "./types";

/** How a place is drawn, on the map and in the list: a tent, a house or a dot. */
export type PlaceGlyph = "camp" | "room" | "food";

const CAMP_CATEGORIES = new Set(["camp_site", "caravan_site"]);

/** Campgrounds and RV parks get a tent, every other place to stay (hotel, motel...) a house, food a dot. */
export function placeGlyph(place: Pick<PlaceOption, "kind" | "category">): PlaceGlyph {
  if (place.kind === "food") return "food";
  return CAMP_CATEGORIES.has(place.category) ? "camp" : "room";
}
