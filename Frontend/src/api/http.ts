import { getOwnKey } from "../ownKey";
import { markAwake, markGaveUp, markWaking, mayBeAsleep } from "../serverStatus";
import type {
  AgentApiResponse,
  AgentStreamEvent,
  PlaceGroup,
  RawForecast,
  RawLocationSearch,
  RawPoiSearch,
  RawRoute,
  RawRoutesGenerated,
  RawTrip,
  RawTripCreated,
  Route,
  RouteType,
} from "../types";
import type { AgentApi, AgentMessageBody, BackendApi } from "./contract";
import { ApiError, callMeta } from "./errors";

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
    directions: raw.directions ?? null,
  };
}

/** An agent message, with the user's own Anthropic key when they set one (ownKey.ts). */
function agentPost(body: AgentMessageBody): RequestInit {
  const init = postJson(body);
  const key = getOwnKey();
  if (key) init.headers = { ...init.headers, "X-Anthropic-Key": key };
  return init;
}

export interface HttpBackend extends BackendApi, AgentApi {
  /** Starts a sleeping backend booting as soon as the app loads, so it is likely awake by the first message. */
  warmUp(): void;
}

/** The FastAPI backend at base (no trailing slash). */
export function createHttpBackend(base: string): HttpBackend {
  // A backend that can sleep (anything but localhost): a slow or failed first call means "waking up", not an error
  const canSleep = !/^(https?:\/\/)?(localhost|127\.0\.0\.1)(:|\/|$)/.test(base);

  /** fetch, waiting out a sleeping backend's cold start instead of failing (see serverStatus.ts). */
  async function fetchWaking(path: string, init?: RequestInit): Promise<Response | null> {
    const wake = canSleep && mayBeAsleep();
    const slow = wake ? setTimeout(markWaking, SLOW_MS) : undefined;
    const deadline = Date.now() + WAKE_TIMEOUT_MS;
    try {
      for (let attempt = 0; ; attempt++) {
        let response: Response | null;
        try {
          response = await fetch(`${base}${path}`, init);
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

  async function send(path: string, init?: RequestInit): Promise<Response> {
    const response = await fetchWaking(path, init);
    if (response === null) {
      throw new ApiError(`Backend unreachable at ${base}`, null, "unreachable");
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

  const sendAgentMessage = (body: AgentMessageBody) => request<AgentApiResponse>("/agent/message", agentPost(body));

  return {
    warmUp() {
      if (canSleep) void fetchWaking("/health").catch(() => undefined);
    },

    async searchLocation(q) {
      const data = await request<RawLocationSearch>(`/location/search?${query({ q })}`);
      return (data.results ?? []).map((r) => ({ name: r.label, lat: r.lat, lon: r.lon }));
    },

    async createTrip(origin, destination, name) {
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
    },

    async getTrip(tripId) {
      const data = await request<RawTrip>(`/trips/${tripId}`);
      return {
        id: data.id,
        origin: data.origin,
        destination: data.destination,
        selected_route_id: data.selected_route_id,
        routes: data.routes.map(adaptRoute),
        weather: [],
      };
    },

    async generateRoutes(tripId) {
      const data = await request<RawRoutesGenerated>(`/routes/generate/${tripId}`, { method: "POST" });
      return data.routes.map(adaptRoute);
    },

    async selectRoute(routeId) {
      await request<{ status: string; message: string }>(`/routes/select/${routeId}`, { method: "POST" });
    },

    async searchPois(lat, lon) {
      const data = await request<RawPoiSearch>(`/pois/search?${query({ lat, lon })}`);
      return data.pois ?? [];
    },

    async getSavedPois(lat, lon, radiusKm = 2) {
      const data = await request<RawPoiSearch>(`/pois/?${query({ lat, lon, radius_km: radiusKm })}`);
      return data.pois ?? [];
    },

    async findPlaces(points) {
      const body = { points: points.map(({ near, lat, lon, kinds }) => ({ near, lat, lon, kinds })) };
      const data = await request<{ groups: Omit<PlaceGroup, "label">[] }>("/places/search", postJson(body));
      const labels = new Map(points.map((p) => [p.near, p.label]));
      return data.groups.map((g) => ({ ...g, label: labels.get(g.near) ?? g.near }));
    },

    async getForecast(lat, lon) {
      const data = await request<RawForecast>(`/weather/forecast?${query({ lat, lon })}`);
      return data.forecast ?? [];
    },

    async createAgentSession() {
      const data = await request<{ session_id: string }>("/agent/sessions", { method: "POST" });
      return data.session_id;
    },

    sendAgentMessage,

    /**
     * onEvent receives tool_start / tool_end as the agent works. Session and rate-limit errors arrive as an
     * HTTP error before the stream starts; failures during the turn as an "error" event. Falls back to the
     * non-streaming endpoint if the browser can't read the body as a stream.
     */
    async streamAgentMessage(body: AgentMessageBody, onEvent: (event: AgentStreamEvent) => void) {
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
    },
  };
}
