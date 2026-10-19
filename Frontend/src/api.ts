import tripFixtureJson from "./fixtures/trip.sf-la.json";
import poisFixtureJson from "./fixtures/pois.json";
import placesFixtureJson from "./fixtures/places.json";
import { haversineMiles } from "./geo";
import { getOwnKey } from "./ownKey";
import { markAwake, markGaveUp, markWaking, mayBeAsleep } from "./serverStatus";
import type {
  AgentApiResponse,
  AgentStreamEvent,
  CacheStatus,
  ForecastDay,
  Place,
  PlaceGroup,
  PlaceKind,
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
/** Matches the backend's PUBLIC_DEMO: route writes are agent-only, so a route picked on the map stays in the browser. */
export const PUBLIC_DEMO = import.meta.env.VITE_PUBLIC_DEMO === "true";

const tripFixture = tripFixtureJson as unknown as Trip;
const poisFixture = poisFixtureJson as unknown as {
  sets: { center: { lat: number; lon: number }; pois: Poi[] }[];
};
type PlaceTemplate = { name: string; category: string; dlat: number; dlon: number; facts: string[] };
const placesFixture = placesFixtureJson as unknown as Record<PlaceKind, PlaceTemplate[]>;

/**
 * Cache status of the most recent call. The backend does not report cache
 * hits, so this is always null in real mode; mock mode simulates it.
 */
export const callMeta: { cache: CacheStatus } = { cache: null };

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number | null,
    /** Machine-readable code from the agent endpoints' {"error": {"code", "message"}} */
    readonly code: string | null = null,
  ) {
    super(message);
  }
}

// ---- Real transport --------------------------------------------------------

// A backend that can sleep (anything but localhost): a slow or failed first call means "waking up", not an error
const CAN_SLEEP = !/^(https?:\/\/)?(localhost|127\.0\.0\.1)(:|\/|$)/.test(API_BASE);
// Show the waking message once a call to a possibly sleeping server takes this long
const SLOW_MS = 3000;
// Give a booting server this long before reporting it unreachable
const WAKE_TIMEOUT_MS = 120_000;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * The platform's answer while the backend boots: a network failure, or a 502/503 from its proxy.
 * The backend's own 502/503 errors are JSON ({"error": ...}, {"detail": ...}) and pass through as errors.
 */
function isBooting(response: Response | null): boolean {
  if (response === null) return true;
  if (response.status !== 502 && response.status !== 503) return false;
  return !(response.headers.get("content-type") ?? "").includes("application/json");
}

/** fetch, waiting out a sleeping backend's cold start instead of failing (see serverStatus.ts). */
async function fetchWaking(path: string, init?: RequestInit): Promise<Response | null> {
  const wake = CAN_SLEEP && mayBeAsleep();
  const slow = wake ? setTimeout(markWaking, SLOW_MS) : undefined;
  const deadline = Date.now() + WAKE_TIMEOUT_MS;
  try {
    for (let attempt = 0; ; attempt++) {
      let response: Response | null;
      try {
        response = await fetch(`${API_BASE}${path}`, init);
      } catch {
        response = null;
      }
      if (!isBooting(response)) {
        markAwake();
        return response;
      }
      if (!wake || Date.now() + 2000 > deadline) {
        if (wake) markGaveUp();
        return response;
      }
      markWaking();
      await sleep(Math.min(2000 * 2 ** attempt, 8000));
    }
  } finally {
    clearTimeout(slow);
  }
}

/** Starts a sleeping backend booting as soon as the app loads, so it is likely awake by the first message. */
export function warmUpServer(): void {
  if (!USE_MOCK && CAN_SLEEP) void fetchWaking("/health").catch(() => undefined);
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  const response = await fetchWaking(path, init);
  if (response === null) {
    throw new ApiError(`Backend unreachable at ${API_BASE}`, null, "unreachable");
  }
  if (!response.ok) {
    let detail = response.statusText;
    let code: string | null = null;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
      if (typeof body?.error?.message === "string") {
        detail = body.error.message;
        code = body.error.code ?? null;
      }
    } catch {
      // non-JSON error body; keep the status text
    }
    throw new ApiError(detail, response.status, code);
  }
  return response;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  callMeta.cache = null;
  return (await (await send(path, init)).json()) as T;
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
    duration_vs_fastest: raw.duration_vs_fastest ?? null,
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

export interface PlacePoint {
  near: string;
  /** Shown in the list, e.g. "Night 1 · Paso Robles"; the backend's response carries its own */
  label: string;
  lat: number;
  lon: number;
  kinds: PlaceKind[];
}

/** Mock mode: the fixture's invented places, at fixed offsets around each point. */
function mockPlaceGroups(points: PlacePoint[]): PlaceGroup[] {
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

/** POST /places/search: campsites and places to eat near each point, ranked best first. */
export async function findPlaces(points: PlacePoint[]): Promise<PlaceGroup[]> {
  if (USE_MOCK) return mock(mockPlaceGroups(points), 900);
  const body = { points: points.map(({ near, lat, lon, kinds }) => ({ near, lat, lon, kinds })) };
  const data = await request<{ groups: Omit<PlaceGroup, "label">[] }>("/places/search", postJson(body));
  const labels = new Map(points.map((p) => [p.near, p.label]));
  return data.groups.map((g) => ({ ...g, label: labels.get(g.near) ?? g.near }));
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

// ---- Agent (real mode only; mock mode runs the scripted agent in agent.ts) --

/** POST /agent/sessions -> a new conversation id. */
export async function createAgentSession(): Promise<string> {
  const data = await request<{ session_id: string }>("/agent/sessions", { method: "POST" });
  return data.session_id;
}

export interface AgentMessageBody {
  session_id: string;
  message: string;
  selected_route_id: number | null;
}

/** An agent message, with the user's own Anthropic key when they set one (ownKey.ts). */
function agentPost(body: AgentMessageBody): RequestInit {
  const init = postJson(body);
  const key = getOwnKey();
  if (key) init.headers = { ...init.headers, "X-Anthropic-Key": key };
  return init;
}

/** POST /agent/message: one turn, answered when it finishes. */
export function sendAgentMessage(body: AgentMessageBody): Promise<AgentApiResponse> {
  return request<AgentApiResponse>("/agent/message", agentPost(body));
}

/**
 * POST /agent/message/stream: the same turn as server-sent events. onEvent
 * receives tool_start / tool_end as the agent works; the promise resolves with
 * the final answer. Session and rate-limit errors arrive as an HTTP error
 * before the stream starts; failures during the turn as an "error" event.
 * Falls back to the non-streaming endpoint if the browser can't read the body as a stream.
 */
export async function streamAgentMessage(
  body: AgentMessageBody,
  onEvent: (event: AgentStreamEvent) => void,
): Promise<AgentApiResponse> {
  const response = await send("/agent/message/stream", agentPost(body));
  if (!response.body) return sendAgentMessage(body);

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value.replace(/\r\n/g, "\n");
    let boundary: number;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const lines = frame.split("\n").filter((line) => line && !line.startsWith(":"));
      const event = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
      const data = lines.filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
      if (!event || !data) continue;
      const payload = JSON.parse(data);
      if (event === "final") return payload as AgentApiResponse;
      if (event === "error") {
        throw new ApiError(payload.error?.message ?? "The agent failed", null, payload.error?.code ?? "agent_error");
      }
      onEvent({ ...payload, type: event } as AgentStreamEvent);
    }
  }
  throw new ApiError("The agent stream ended without an answer", null, "stream_ended");
}
