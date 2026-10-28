/**
 * Taking a trip elsewhere: a Google Maps directions link, and a GPX file of the selected route.
 * Pure functions with no imports at run time, so `npm test` runs them under Node as they are.
 */
import type { LineString } from "geojson";
import type { Place, PlannedStop } from "./types";

/**
 * Google Maps URLs take at most 9 waypoints; on a phone's browser only the first 3 are used. Beyond that the
 * link would be cut or rejected, so later stops are left out and the app says how many.
 */
export const GOOGLE_MAPS_MAX_WAYPOINTS = 9;
export const GOOGLE_MAPS_MOBILE_WAYPOINTS = 3;

export interface MapsLink {
  url: string;
  /** Overnight stops in the link, in driving order */
  waypoints: number;
  /** Overnight stops left out for the limit */
  dropped: number;
}

const latLon = (p: { lat: number; lon: number }) => `${p.lat.toFixed(5)},${p.lon.toFixed(5)}`;

/**
 * A Google Maps directions link from the origin to the destination through the overnight stops, by coordinates
 * (a stop's name, "Kern County", would be ambiguous). Google picks its own roads between the points, so it may
 * not follow the scenic route exactly.
 */
export function googleMapsDirectionsUrl(origin: Place, destination: Place, stops: PlannedStop[]): MapsLink {
  const overnight = [...stops].filter((s) => s.kind === "overnight").sort((a, b) => a.day - b.day);
  const kept = overnight.slice(0, GOOGLE_MAPS_MAX_WAYPOINTS);
  const params = new URLSearchParams({
    api: "1",
    origin: latLon(origin),
    destination: latLon(destination),
    travelmode: "driving",
  });
  if (kept.length > 0) params.set("waypoints", kept.map(latLon).join("|"));
  return {
    url: `https://www.google.com/maps/dir/?${params.toString()}`,
    waypoints: kept.length,
    dropped: overnight.length - kept.length,
  };
}

const escapeXml = (text: string) =>
  text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&apos;");

const coord = (value: number) => value.toFixed(6);

export interface GpxInput {
  /** e.g. "San Francisco to Los Angeles (scenic)" */
  name: string;
  origin: Place;
  destination: Place;
  /** The route's line, [lon, lat] pairs as the API serves them */
  geometry: LineString;
  /** Overnight stops become waypoints too */
  stops?: PlannedStop[];
  /** Written to the metadata when given; left out by default so the same route gives the same file */
  time?: Date;
}

/** A GPX 1.1 file: the route as a track, and the start, overnight stops and destination as waypoints. */
export function routeGpx({ name, origin, destination, geometry, stops = [], time }: GpxInput): string {
  const waypoint = (p: { lat: number; lon: number }, label: string, type: string) =>
    `  <wpt lat="${coord(p.lat)}" lon="${coord(p.lon)}"><name>${escapeXml(label)}</name><type>${type}</type></wpt>`;
  const overnight = stops.filter((s) => s.kind === "overnight").sort((a, b) => a.day - b.day);
  const points = geometry.coordinates
    .filter((c) => Number.isFinite(c[0]) && Number.isFinite(c[1]))
    .map(([lon, lat]) => `      <trkpt lat="${coord(lat)}" lon="${coord(lon)}"/>`);
  return [
    `<?xml version="1.0" encoding="UTF-8"?>`,
    `<gpx version="1.1" creator="Waypoint" xmlns="http://www.topografix.com/GPX/1/1">`,
    `  <metadata><name>${escapeXml(name)}</name>${time ? `<time>${time.toISOString()}</time>` : ""}</metadata>`,
    waypoint(origin, origin.name, "start"),
    ...overnight.map((s) => waypoint(s, `Night ${s.day}: ${s.name}`, "overnight")),
    waypoint(destination, destination.name, "destination"),
    `  <trk>`,
    `    <name>${escapeXml(name)}</name>`,
    `    <trkseg>`,
    ...points,
    `    </trkseg>`,
    `  </trk>`,
    `</gpx>`,
    "",
  ].join("\n");
}

/** "san-francisco-to-los-angeles-scenic.gpx" */
export function gpxFileName(name: string): string {
  const slug = name
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^\w\s-]/g, "")
    .trim()
    .replace(/[\s_-]+/g, "-")
    .slice(0, 80);
  return `${slug || "route"}.gpx`;
}
