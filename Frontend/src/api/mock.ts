import tripFixtureJson from "../fixtures/trip.sf-la.json";
import poisFixtureJson from "../fixtures/pois.json";
import placesFixtureJson from "../fixtures/places.json";
import directionsFixtureJson from "../fixtures/directions.sf-la.json";
import { haversineMiles } from "../geo";
import type { DirectionStep, Place, PlaceGroup, PlaceKind, Poi, RouteType, Trip } from "../types";
import type { BackendApi, PlacePoint } from "./contract";
import { callMeta } from "./errors";

// The mock routes are hand-drawn; their directions are real ORS steps for the same trip
const mockDirections = directionsFixtureJson as unknown as Record<RouteType, DirectionStep[]>;
const tripFixture: Trip = {
  ...(tripFixtureJson as unknown as Trip),
  routes: (tripFixtureJson as unknown as Trip).routes.map((r) => ({ ...r, directions: mockDirections[r.route_type] })),
};
const poisFixture = poisFixtureJson as unknown as {
  sets: { center: { lat: number; lon: number }; pois: Poi[] }[];
};
type PlaceTemplate = { name: string; category: string; dlat: number; dlon: number; facts: string[] };
const placesFixture = placesFixtureJson as unknown as Record<PlaceKind, PlaceTemplate[]>;

/** What mock mode can find: the fixture trip's two ends. */
export const MOCK_LOCATIONS_HINT = "Mock mode only knows San Francisco and Los Angeles.";

/** The fixtures in src/fixtures behind the same contract as the HTTP client, with simulated delays and cache hits. */
export function createMockBackend(): BackendApi {
  const seen = new Set<string>();

  /** Serves a fixture after a simulated delay; repeat cacheable calls are fast "hits". */
  function mock<T>(value: T, ms: number, cacheKey?: string): Promise<T> {
    let delay = ms * (0.8 + Math.random() * 0.4);
    if (cacheKey) {
      callMeta.cache = seen.has(cacheKey) ? "hit" : "miss";
      if (callMeta.cache === "hit") delay = 12 + Math.random() * 18;
      seen.add(cacheKey);
    } else {
      callMeta.cache = null;
    }
    return new Promise((resolve) => setTimeout(() => resolve(structuredClone(value)), delay));
  }

  function locations(q: string): Place[] {
    const text = q.toLowerCase();
    if (/san fran|\bsf\b/.test(text)) return [tripFixture.origin];
    if (/los angeles|\bla\b/.test(text)) return [tripFixture.destination];
    return [];
  }

  function nearestPois(lat: number, lon: number): Promise<Poi[]> {
    const distance = (set: { center: { lat: number; lon: number } }) => Math.hypot(set.center.lat - lat, set.center.lon - lon);
    const nearest = [...poisFixture.sets].sort((a, b) => distance(a) - distance(b))[0];
    return mock(nearest?.pois ?? [], 520, `poi:${lat.toFixed(2)},${lon.toFixed(2)}`);
  }

  /** The fixture's invented places, at fixed offsets around each point. */
  function placeGroups(points: PlacePoint[]): PlaceGroup[] {
    return points.flatMap((point) =>
      point.kinds.map((kind) => ({
        near: point.near,
        label: point.label,
        kind,
        lat: point.lat,
        lon: point.lon,
        radius_mi: kind === "camping" ? 15.5 : 3.1,
        source: "mock",
        places: placesFixture[kind]
          .map((t, i) => {
            const lat = point.lat + t.dlat;
            const lon = point.lon + t.dlon;
            return {
              id: `mock:${point.near}:${kind}:${i}`,
              kind,
              category: t.category,
              name: t.name,
              lat,
              lon,
              distance_mi: Math.round(haversineMiles([point.lon, point.lat], [lon, lat]) * 10) / 10,
              facts: t.facts,
            };
          })
          .sort((a, b) => a.distance_mi - b.distance_mi),
      })),
    );
  }

  return {
    searchLocation: (q) => mock(locations(q), 380, `geo:${q.toLowerCase()}`),
    createTrip: () => mock(tripFixture.id, 240),
    getTrip: () => mock(tripFixture, 260),
    generateRoutes: () => mock(tripFixture.routes, 1150),
    selectRoute: async () => {
      await mock(null, 180);
    },
    searchPois: nearestPois,
    getSavedPois: (lat, lon) => nearestPois(lat, lon),
    findPlaces: (points) => mock(placeGroups(points), 900),
    getForecast: (lat, lon) => {
      const point =
        tripFixture.weather.find((w) => Math.abs(w.lat - lat) < 0.5 && Math.abs(w.lon - lon) < 0.5) ?? tripFixture.weather[0];
      return mock(point?.forecast ?? [], 420, `wx:${lat},${lon}`);
    },
  };
}
