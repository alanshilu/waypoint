// Run with `npm test` (Node's own test runner; Node strips the TypeScript types).
import assert from "node:assert/strict";
import { test } from "node:test";
import { GOOGLE_MAPS_MAX_WAYPOINTS, googleMapsDirectionsUrl, gpxFileName, routeGpx } from "../src/export.ts";
import { sharedIdFromPath, shareUrl } from "../src/share.ts";
import type { PlannedStop } from "../src/types.ts";

const SF = { name: "San Francisco, California, USA", lat: 37.7749, lon: -122.4194 };
const LA = { name: "Los Angeles, California, USA", lat: 34.0522, lon: -118.2437 };

const stop = (day: number, kind: PlannedStop["kind"] = "overnight", name = `Town ${day}`): PlannedStop => ({
  id: `stop-${day}`,
  day,
  kind,
  name,
  lat: 36 - day * 0.1,
  lon: -120 + day * 0.1,
  arrival_date: "2026-10-29",
});

test("maps link: origin, destination and overnight stops in driving order", () => {
  const link = googleMapsDirectionsUrl(SF, LA, [stop(2), stop(1), stop(3, "destination", "Los Angeles")]);
  const url = new URL(link.url);
  assert.equal(url.origin + url.pathname, "https://www.google.com/maps/dir/");
  assert.equal(url.searchParams.get("api"), "1");
  assert.equal(url.searchParams.get("origin"), "37.77490,-122.41940");
  assert.equal(url.searchParams.get("destination"), "34.05220,-118.24370");
  assert.equal(url.searchParams.get("travelmode"), "driving");
  // the destination stop is not a waypoint; the rest go by day
  assert.equal(url.searchParams.get("waypoints"), "35.90000,-119.90000|35.80000,-119.80000");
  assert.deepEqual([link.waypoints, link.dropped], [2, 0]);
});

test("maps link: no stops, no waypoints parameter", () => {
  const link = googleMapsDirectionsUrl(SF, LA, []);
  assert.equal(new URL(link.url).searchParams.has("waypoints"), false);
  assert.deepEqual([link.waypoints, link.dropped], [0, 0]);
});

test("maps link: stops past Google's waypoint limit are left out and counted", () => {
  const stops = Array.from({ length: 12 }, (_, i) => stop(i + 1));
  const link = googleMapsDirectionsUrl(SF, LA, stops);
  const waypoints = new URL(link.url).searchParams.get("waypoints")!.split("|");
  assert.equal(waypoints.length, GOOGLE_MAPS_MAX_WAYPOINTS);
  assert.equal(waypoints[0], "35.90000,-119.90000"); // the first nights are kept
  assert.deepEqual([link.waypoints, link.dropped], [9, 3]);
});

const LINE = { type: "LineString" as const, coordinates: [[-122.4194, 37.7749], [-120.5, 36.1], [-118.2437, 34.0522]] as [number, number][] };

test("gpx: a GPX 1.1 track of the route, with start, overnight and destination waypoints", () => {
  const gpx = routeGpx({ name: "SF to LA (scenic)", origin: SF, destination: LA, geometry: LINE, stops: [stop(1), stop(2, "destination")] });
  assert.match(gpx, /^<\?xml version="1\.0" encoding="UTF-8"\?>\n<gpx version="1\.1" creator="Waypoint" xmlns="http:\/\/www\.topografix\.com\/GPX\/1\/1">/);
  const trkpts = [...gpx.matchAll(/<trkpt lat="([-\d.]+)" lon="([-\d.]+)"\/>/g)].map((m) => [Number(m[2]), Number(m[1])]);
  assert.deepEqual(trkpts, LINE.coordinates); // lat and lon the right way round
  const wpts = [...gpx.matchAll(/<wpt [^>]*><name>([^<]*)<\/name><type>(\w+)<\/type><\/wpt>/g)].map((m) => [m[1], m[2]]);
  assert.deepEqual(wpts, [
    ["San Francisco, California, USA", "start"],
    ["Night 1: Town 1", "overnight"],
    ["Los Angeles, California, USA", "destination"],
  ]);
  assert.equal((gpx.match(/<trkseg>/g) ?? []).length, 1);
  assert.ok(gpx.endsWith("</gpx>\n"));
  assert.ok(!gpx.includes("<time>"), "no time unless asked, so the file is the same for the same route");
});

test("gpx: names are escaped, a time is written when given, bad points are skipped", () => {
  const gpx = routeGpx({
    name: `Tom & Jerry's <"road"> trip`,
    origin: { ...SF, name: "A & B" },
    destination: LA,
    geometry: { type: "LineString", coordinates: [[-122, 37], [Number.NaN, 36], [-118, 34]] },
    time: new Date("2026-10-28T12:00:00Z"),
  });
  assert.ok(gpx.includes("<name>Tom &amp; Jerry&apos;s &lt;&quot;road&quot;&gt; trip</name>"));
  assert.ok(gpx.includes("<name>A &amp; B</name>"));
  assert.ok(gpx.includes("<time>2026-10-28T12:00:00.000Z</time>"));
  assert.equal((gpx.match(/<trkpt /g) ?? []).length, 2);
});

test("gpx file name", () => {
  assert.equal(gpxFileName("San Francisco to Los Angeles (scenic)"), "san-francisco-to-los-angeles-scenic.gpx");
  assert.equal(gpxFileName("???"), "route.gpx");
});

test("share links", () => {
  const id = "6f1c2b8e-3a41-4e0b-9a51-2d6b8f0c7e11";
  assert.equal(shareUrl("https://waypoint.example.com/", id), `https://waypoint.example.com/t/${id}`);
  assert.equal(sharedIdFromPath(`/t/${id}`), id);
  assert.equal(sharedIdFromPath(`/t/${id.toUpperCase()}/`), id);
  assert.equal(sharedIdFromPath("/t/41"), null); // never an integer id
  assert.equal(sharedIdFromPath("/"), null);
  assert.equal(sharedIdFromPath(`/x/${id}`), null);
});
