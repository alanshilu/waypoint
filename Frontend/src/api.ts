import tripFixtureJson from "./fixtures/trip.sf-la.json";
import poisFixtureJson from "./fixtures/pois.json";
import type {
  AgentReply,
  CacheStatus,
  ForecastDay,
  Place,
  Poi,
  RawForecast,
  RawLocationSearch,
  RawPoiSearch,
  RawRoute,
  RawRoutesGenerated,
  RawTrip,
  RawTripCreated,
  Route,
  RouteType,
  Trip,
} from "./types";

/** Mock mode is the default; set VITE_USE_MOCK=false to call the backend. */
export const USE_MOCK = import.meta.env.VITE_USE_MOCK !== "false";
export const API_BASE = (import.meta.env.VITE_API_BASE ?? "http://localhost:8000").replace(/\/+$/, "");

const tripFixture = tripFixtureJson as unknown as Trip;
const poisFixture = poisFixtureJson as unknown as {
  sets: { center: { lat: number; lon: number }; pois: Poi[] }[];
};

/**
 * Cache status of the most recent call. The backend does not report cache
 * hits, so this is always null in real mode; mock mode simulates it.
 */
export const callMeta: { cache: CacheStatus } = { cache: null };

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number | null,
  ) {
    super(message);
  }
}

// ---- Real transport --------------------------------------------------------

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  callMeta.cache = null;
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, init);
  } catch {
    throw new ApiError(`Backend unreachable at ${API_BASE}`, null);
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // non-JSON error body; keep the status text
    }
    throw new ApiError(`${response.status} ${detail}`, response.status);
  }
  return (await response.json()) as T;
}

const postJson = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

const query = (params: Record<string, string | number>) =>
  new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString();

/** Backend route dict -> contract Route (nulls -> 0, null profile -> absent). */
function adaptRoute(raw: RawRoute): Route {
  return {
    id: raw.id,
    route_type: raw.route_type as RouteType,
    distance_miles: raw.distance_miles,
    duration_seconds: raw.duration_seconds,
    ascent_m: raw.ascent_m ?? 0,
    descent_m: raw.descent_m ?? 0,
    scenic_score: raw.scenic_score ?? 0,
    geometry: raw.geometry,
    elevation_profile: raw.elevation_profile ?? undefined,
  };
}

// ---- Mock transport --------------------------------------------------------

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

function mockLocations(q: string): Place[] {
  const text = q.toLowerCase();
  if (/san fran|\bsf\b/.test(text)) return [tripFixture.origin];
  if (/los angeles|\bla\b/.test(text)) return [tripFixture.destination];
  return [];
}

// ---- Endpoints -------------------------------------------------------------

/** GET /location/search */
export async function searchLocation(q: string): Promise<Place[]> {
  if (USE_MOCK) return mock(mockLocations(q), 380, `geo:${q.toLowerCase()}`);
  const data = await request<RawLocationSearch>(`/location/search?${query({ q })}`);
  return (data.results ?? []).map((r) => ({ name: r.label, lat: r.lat, lon: r.lon }));
}

/** POST /trips/ -> the new trip id (the backend returns nothing else). */
export async function createTrip(origin: Place, destination: Place, name?: string): Promise<number> {
  if (USE_MOCK) return mock(tripFixture.id, 240);
  const data = await request<RawTripCreated>(
    "/trips/",
    postJson({
      name: name ?? null,
      origin_name: origin.name,
      origin_lat: origin.lat,
      origin_lon: origin.lon,
      destination_name: destination.name,
      destination_lat: destination.lat,
      destination_lon: destination.lon,
    }),
  );
  return data.trip_id;
}

/** GET /trips/{id}: a saved trip with its routes. Weather is not stored, so it starts empty. */
export async function getTrip(tripId: number): Promise<Trip> {
  if (USE_MOCK) return mock(tripFixture, 260);
  const data = await request<RawTrip>(`/trips/${tripId}`);
  return {
    id: data.id,
    origin: data.origin,
    destination: data.destination,
    selected_route_id: data.selected_route_id,
    routes: data.routes.map(adaptRoute),
    weather: [],
  };
}

/** POST /routes/generate/{trip_id}. Not idempotent: each call adds two rows. */
export async function generateRoutes(tripId: number): Promise<Route[]> {
  if (USE_MOCK) return mock(tripFixture.routes, 1150);
  const data = await request<RawRoutesGenerated>(`/routes/generate/${tripId}`, { method: "POST" });
  return data.routes.map(adaptRoute);
}

/** POST /routes/select/{route_id} */
export async function selectRoute(routeId: number): Promise<void> {
  if (USE_MOCK) {
    await mock(null, 180);
    return;
  }
  await request<{ status: string; message: string }>(`/routes/select/${routeId}`, { method: "POST" });
}

/** GET /pois/search */
export async function searchPois(lat: number, lon: number): Promise<Poi[]> {
  if (USE_MOCK) {
    const distance = (set: { center: { lat: number; lon: number } }) =>
      Math.hypot(set.center.lat - lat, set.center.lon - lon);
    const nearest = [...poisFixture.sets].sort((a, b) => distance(a) - distance(b))[0];
    return mock(nearest?.pois ?? [], 520, `poi:${lat.toFixed(2)},${lon.toFixed(2)}`);
  }
  const data = await request<RawPoiSearch>(`/pois/search?${query({ lat, lon })}`);
  return data.pois ?? [];
}

/** GET /pois/: stops already saved in the database; no external lookup. */
export async function getSavedPois(lat: number, lon: number, radiusKm = 2): Promise<Poi[]> {
  if (USE_MOCK) return searchPois(lat, lon);
  const data = await request<RawPoiSearch>(`/pois/?${query({ lat, lon, radius_km: radiusKm })}`);
  return data.pois ?? [];
}

/** GET /weather/forecast (7-day list; target_date is not used by the UI). */
export async function getForecast(lat: number, lon: number): Promise<ForecastDay[]> {
  if (USE_MOCK) {
    const point =
      tripFixture.weather.find((w) => Math.abs(w.lat - lat) < 0.5 && Math.abs(w.lon - lon) < 0.5) ??
      tripFixture.weather[0];
    return mock(point?.forecast ?? [], 420, `wx:${lat},${lon}`);
  }
  const data = await request<RawForecast>(`/weather/forecast?${query({ lat, lon })}`);
  return data.forecast ?? [];
}

let agentEndpointMissing = false;

/**
 * POST /agent/message. The backend has no such endpoint yet, so this returns
 * null on 404/405 and the caller falls back to the scripted runner.
 */
export async function postAgentMessage(
  message: string,
  context: { trip_id: number | null; selected_route_id: number | null },
): Promise<(AgentReply & { trip?: Trip }) | null> {
  if (USE_MOCK || agentEndpointMissing) return null;
  try {
    return await request<AgentReply & { trip?: Trip }>("/agent/message", postJson({ message, ...context }));
  } catch (error) {
    if (error instanceof ApiError && (error.status === 404 || error.status === 405)) {
      agentEndpointMissing = true;
      return null;
    }
    throw error;
  }
}
