// Generates src/fixtures/trip.sf-la.json (MOCK DATA, not from OpenRouteService).
// Waypoints are hand-placed [lon, lat, elevation_m] along the real corridors,
// then densified. Run with: npm run fixture
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const FASTEST = {
  id: 101,
  route_type: "fastest",
  distance_miles: 382.4,
  duration_seconds: 21000, // 5h 50m
  wiggle: 0.003,
  roughness: 18,
  terrain: 1.3,
  waypoints: [
    [-122.4194, 37.7749, 16], // San Francisco
    [-122.36, 37.815, 5], // Bay Bridge
    [-122.27, 37.805, 13], // Oakland
    [-122.156, 37.725, 17],
    [-122.08, 37.695, 50], // Castro Valley
    [-121.93, 37.7, 110], // Dublin
    [-121.77, 37.7, 150], // Livermore
    [-121.65, 37.74, 225], // Altamont Pass
    [-121.33, 37.6, 40], // I-580 / I-5
    [-121.2, 37.55, 30],
    [-121.13, 37.47, 30], // Patterson
    [-121.02, 37.1, 50], // Santa Nella
    [-120.95, 36.98, 60],
    [-120.63, 36.63, 70],
    [-120.24, 36.25, 130], // Coalinga
    [-119.96, 36.01, 80], // Kettleman City
    [-119.69, 35.62, 90], // Lost Hills
    [-119.47, 35.4, 85], // Buttonwillow
    [-119.2, 35.17, 110],
    [-118.95, 34.99, 290], // Wheeler Ridge
    [-118.92, 34.94, 460], // Grapevine
    [-118.85, 34.8, 1260], // Tejon Pass
    [-118.76, 34.66, 870], // Pyramid Lake
    [-118.62, 34.49, 360], // Castaic
    [-118.56, 34.39, 370], // Santa Clarita
    [-118.49, 34.32, 420], // Newhall Pass
    [-118.44, 34.28, 320],
    [-118.31, 34.18, 180], // Burbank
    [-118.26, 34.14, 150],
    [-118.2437, 34.0522, 90], // Los Angeles
  ],
};

const BACKROADS = {
  id: 102,
  route_type: "backroads",
  distance_miles: 478.1,
  duration_seconds: 36300, // 10h 05m
  wiggle: 0.006,
  roughness: 68,
  terrain: 0.45,
  waypoints: [
    [-122.4194, 37.7749, 16], // San Francisco
    [-122.47, 37.69, 100], // Daly City
    [-122.49, 37.61, 25], // Pacifica
    [-122.51, 37.54, 60], // Devil's Slide
    [-122.43, 37.46, 25], // Half Moon Bay
    [-122.4, 37.32, 30], // San Gregorio
    [-122.39, 37.18, 20], // Pigeon Point
    [-122.31, 37.11, 40],
    [-122.19, 37.01, 30], // Davenport
    [-122.03, 36.97, 10], // Santa Cruz
    [-121.9, 36.98, 30],
    [-121.76, 36.91, 10], // Watsonville
    [-121.79, 36.8, 5], // Moss Landing
    [-121.8, 36.68, 15],
    [-121.89, 36.6, 10], // Monterey
    [-121.92, 36.55, 60], // Carmel
    [-121.93, 36.5, 50],
    [-121.9, 36.37, 85], // Bixby Bridge
    [-121.88, 36.31, 40], // Point Sur
    [-121.81, 36.27, 50], // Big Sur
    [-121.78, 36.23, 250],
    [-121.67, 36.16, 80],
    [-121.55, 36.02, 110], // Lucia
    [-121.47, 35.87, 90], // Gorda
    [-121.33, 35.78, 100], // Ragged Point
    [-121.19, 35.64, 10], // San Simeon
    [-121.08, 35.56, 20], // Cambria
    [-120.89, 35.44, 10],
    [-120.85, 35.37, 15], // Morro Bay
    [-120.66, 35.28, 70], // San Luis Obispo
    [-120.64, 35.14, 15], // Pismo Beach
    [-120.48, 35.04, 100],
    [-120.44, 34.95, 65], // Santa Maria
    [-120.28, 34.74, 170], // Los Alamos
    [-120.19, 34.61, 110], // Buellton
    [-120.23, 34.51, 280], // Gaviota Pass
    [-120.21, 34.47, 20],
    [-120.07, 34.46, 10],
    [-119.83, 34.44, 10], // Goleta
    [-119.7, 34.42, 15], // Santa Barbara
    [-119.52, 34.4, 5],
    [-119.29, 34.28, 10], // Ventura
    [-119.18, 34.2, 15],
    [-119.06, 34.09, 5], // Point Mugu
    [-118.93, 34.045, 10],
    [-118.78, 34.03, 20], // Malibu
    [-118.58, 34.04, 10],
    [-118.5, 34.02, 30], // Santa Monica
    [-118.39, 34.03, 35],
    [-118.2437, 34.0522, 90], // Los Angeles
  ],
};

const round = (n, places) => Number(n.toFixed(places));

function haversineMiles(a, b) {
  const rad = (d) => (d * Math.PI) / 180;
  const dLat = rad(b[1] - a[1]);
  const dLon = rad(b[0] - a[0]);
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(rad(a[1])) * Math.cos(rad(b[1])) * Math.sin(dLon / 2) ** 2;
  return 2 * 3958.8 * Math.asin(Math.sqrt(h));
}

// Deterministic noise so the fixture is reproducible.
const noise = (x, seed) =>
  Math.sin(x * 1.7 + seed) * 0.5 + Math.sin(x * 4.3 + seed * 2.1) * 0.3 + Math.sin(x * 9.1 + seed * 0.7) * 0.2;

function buildRoute(spec) {
  const pts = spec.waypoints;
  const cumulative = [0];
  for (let i = 1; i < pts.length; i++) cumulative.push(cumulative[i - 1] + haversineMiles(pts[i - 1], pts[i]));
  const measured = cumulative[cumulative.length - 1];
  const scale = spec.distance_miles / measured;

  // Geometry: a vertex roughly every half mile, bent slightly off the chord.
  const coordinates = [];
  for (let i = 1; i < pts.length; i++) {
    const [ax, ay] = pts[i - 1];
    const [bx, by] = pts[i];
    const segment = cumulative[i] - cumulative[i - 1];
    const n = Math.max(1, Math.round(segment / 0.5));
    const length = Math.hypot(bx - ax, by - ay) || 1;
    const nx = -(by - ay) / length;
    const ny = (bx - ax) / length;
    for (let k = 0; k < n; k++) {
      const t = k / n;
      // Offset fades to zero at the waypoints so segments join cleanly.
      const offset = Math.sin(t * Math.PI) * noise(cumulative[i - 1] + t * segment, spec.id) * spec.wiggle;
      coordinates.push([round(ax + (bx - ax) * t + nx * offset, 4), round(ay + (by - ay) * t + ny * offset, 4)]);
    }
  }
  const last = pts[pts.length - 1];
  coordinates.push([last[0], last[1]]);

  // Elevation: interpolate waypoint heights, add terrain roughness.
  const elevationAt = (mile) => {
    const raw = mile / scale;
    let i = 1;
    while (i < cumulative.length - 1 && cumulative[i] < raw) i++;
    const span = cumulative[i] - cumulative[i - 1] || 1;
    const t = Math.min(1, Math.max(0, (raw - cumulative[i - 1]) / span));
    const base = pts[i - 1][2] + (pts[i][2] - pts[i - 1][2]) * t;
    return Math.max(0, base + (noise(mile * spec.terrain, spec.id + 5) + 0.6) * spec.roughness);
  };
  const elevation_profile = [];
  for (let mile = 0; mile < spec.distance_miles; mile += 1) {
    elevation_profile.push({ mile, m: Math.round(elevationAt(mile)) });
  }
  elevation_profile.push({ mile: spec.distance_miles, m: Math.round(last[2]) });

  let ascent = 0;
  let descent = 0;
  for (let i = 1; i < elevation_profile.length; i++) {
    const delta = elevation_profile[i].m - elevation_profile[i - 1].m;
    if (delta > 0) ascent += delta;
    else descent -= delta;
  }

  // Same terrain-only formula as Backend/app/services/scoring_service.py
  const HALF_SCORE_DENSITY_M_PER_MILE = 40;
  const density = (ascent + descent) / spec.distance_miles;
  const scenic_score = round((100 * density) / (density + HALF_SCORE_DENSITY_M_PER_MILE), 1);

  return {
    id: spec.id,
    route_type: spec.route_type,
    distance_miles: spec.distance_miles,
    duration_seconds: spec.duration_seconds,
    ascent_m: ascent,
    descent_m: descent,
    scenic_score,
    geometry: { type: "LineString", coordinates },
    elevation_profile,
  };
}

// Same as the backend's duration_vs_fastest: duration / fastest duration, 2 dp
function withDurationRatios(routes) {
  const fastest = routes.find((r) => r.route_type === "fastest").duration_seconds;
  return routes.map((r) => ({ ...r, duration_vs_fastest: round(r.duration_seconds / fastest, 2) }));
}

const forecast = (rows) =>
  rows.map(([date, temp_max, temp_min, precip_probability, condition]) => ({
    date,
    temp_max,
    temp_min,
    precip_probability,
    condition,
  }));

const trip = {
  _comment:
    "MOCK DATA. Generated by scripts/make-fixture.mjs from hand-placed waypoints. Geometry, elevation and weather are plausible but invented; nothing here came from OpenRouteService or Open-Meteo.",
  id: 1,
  origin: { name: "San Francisco, California, USA", lat: 37.7749, lon: -122.4194 },
  destination: { name: "Los Angeles, California, USA", lat: 34.0522, lon: -118.2437 },
  selected_route_id: null,
  routes: withDurationRatios([buildRoute(FASTEST), buildRoute(BACKROADS)]),
  weather: [
    {
      name: "San Francisco, California, USA",
      lat: 37.7749,
      lon: -122.4194,
      forecast: forecast([
        ["2026-10-12", 68.4, 55.1, 5, "Partly cloudy"],
        ["2026-10-13", 66.9, 54.3, 10, "Fog"],
        ["2026-10-14", 70.2, 55.8, 0, "Clear sky"],
        ["2026-10-15", 71.5, 56.4, 0, "Mainly clear"],
        ["2026-10-16", 67.3, 54.9, 20, "Overcast"],
        ["2026-10-17", 64.8, 53.6, 45, "Slight rain"],
        ["2026-10-18", 66.1, 53.9, 15, "Partly cloudy"],
      ]),
    },
    {
      name: "Los Angeles, California, USA",
      lat: 34.0522,
      lon: -118.2437,
      forecast: forecast([
        ["2026-10-12", 82.6, 62.3, 0, "Clear sky"],
        ["2026-10-13", 84.1, 63.0, 0, "Clear sky"],
        ["2026-10-14", 85.7, 64.2, 0, "Mainly clear"],
        ["2026-10-15", 83.9, 63.5, 0, "Clear sky"],
        ["2026-10-16", 80.4, 61.8, 5, "Partly cloudy"],
        ["2026-10-17", 77.2, 60.9, 10, "Partly cloudy"],
        ["2026-10-18", 79.5, 61.2, 0, "Mainly clear"],
      ]),
    },
  ],
};

const out = fileURLToPath(new URL("../src/fixtures/trip.sf-la.json", import.meta.url));
writeFileSync(out, JSON.stringify(trip) + "\n");

for (const r of trip.routes) {
  console.log(
    `${r.route_type}: ${r.geometry.coordinates.length} pts, ${r.distance_miles} mi, ` +
      `ascent ${r.ascent_m} m, descent ${r.descent_m} m, scenic ${r.scenic_score}`,
  );
}
