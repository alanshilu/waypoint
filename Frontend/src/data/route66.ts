import type { LineString } from "geojson";

/**
 * Historic Route 66, Chicago to Santa Monica, as a line through the towns it ran through (the post-1937
 * alignment, via Santa Rosa rather than Santa Fe). US 66 was decommissioned in 1985 and isn't in current
 * road data, so this is approximate: right town to town, not the exact road between them.
 */
const TOWNS: [name: string, lon: number, lat: number][] = [
  ["Chicago, IL", -87.6298, 41.8781],
  ["Joliet, IL", -88.0817, 41.525],
  ["Pontiac, IL", -88.6298, 40.8809],
  ["Bloomington, IL", -88.9937, 40.4842],
  ["Springfield, IL", -89.6501, 39.7817],
  ["St. Louis, MO", -90.1994, 38.627],
  ["Rolla, MO", -91.7713, 37.9514],
  ["Springfield, MO", -93.2923, 37.209],
  ["Joplin, MO", -94.5133, 37.0842],
  ["Miami, OK", -94.8775, 36.8745],
  ["Tulsa, OK", -95.9928, 36.154],
  ["Oklahoma City, OK", -97.5164, 35.4676],
  ["Clinton, OK", -98.9673, 35.5159],
  ["Amarillo, TX", -101.8313, 35.222],
  ["Tucumcari, NM", -103.725, 35.1717],
  ["Santa Rosa, NM", -104.6825, 34.9387],
  ["Albuquerque, NM", -106.6504, 35.0844],
  ["Gallup, NM", -108.7426, 35.5281],
  ["Holbrook, AZ", -110.1582, 34.9022],
  ["Winslow, AZ", -110.6974, 35.0242],
  ["Flagstaff, AZ", -111.6513, 35.1983],
  ["Williams, AZ", -112.191, 35.2495],
  ["Seligman, AZ", -112.8749, 35.3256],
  ["Kingman, AZ", -114.053, 35.1894],
  ["Needles, CA", -114.6141, 34.8481],
  ["Barstow, CA", -117.0173, 34.8958],
  ["San Bernardino, CA", -117.2898, 34.1083],
  ["Pasadena, CA", -118.1445, 34.1478],
  ["Santa Monica, CA", -118.4912, 34.0195],
];

export const ROUTE_66: LineString = { type: "LineString", coordinates: TOWNS.map(([, lon, lat]) => [lon, lat]) };

export const ROUTE_66_TITLE = "Historic Route 66, Chicago to Santa Monica (approximate; decommissioned in 1985)";
