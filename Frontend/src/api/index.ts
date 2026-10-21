/**
 * The composition root for backend access: the one place that chooses between the real backend and the
 * fixtures. Everything else depends on the interfaces in contract.ts.
 */
import type { AgentApi, BackendApi } from "./contract";
import { createHttpBackend } from "./http";
import { createMockBackend } from "./mock";

export type { AgentApi, AgentMessageBody, BackendApi, LocationApi, PlacePoint, PlacesApi, PoiApi, TripApi, WeatherApi } from "./contract";
export { ApiError, callMeta } from "./errors";
export { MOCK_LOCATIONS_HINT } from "./mock";

/** Mock mode is the default; set VITE_USE_MOCK=false to call the backend. */
export const USE_MOCK = import.meta.env.VITE_USE_MOCK !== "false";
export const API_BASE = (import.meta.env.VITE_API_BASE ?? "http://localhost:8000").replace(/\/+$/, "");
/** Matches the backend's PUBLIC_DEMO: route writes are agent-only, so a route picked on the map stays in the browser. */
export const PUBLIC_DEMO = import.meta.env.VITE_PUBLIC_DEMO === "true";

const http = createHttpBackend(API_BASE);

/** Trips, routes, places, stops and weather: the backend, or the fixtures in mock mode. */
export const backend: BackendApi = USE_MOCK ? createMockBackend() : http;
/** The backend's agent (real mode). */
export const agentApi: AgentApi = http;

/** What the chosen backend can do, so the UI asks about abilities rather than which mode it's in. */
export interface BackendCapabilities {
  /** A saved trip can be loaded again after a reload (the fixtures always start empty) */
  restoresTrips: boolean;
  /** A route picked on the map is saved directly; in the public demo only the agent writes routes */
  savesRoutePicks: boolean;
  /** Who answers chat turns */
  replies: "agent" | "mock";
}

export const capabilities: BackendCapabilities = {
  restoresTrips: !USE_MOCK,
  savesRoutePicks: USE_MOCK || !PUBLIC_DEMO,
  replies: USE_MOCK ? "mock" : "agent",
};

/** Starts a sleeping hosted backend booting as soon as the app loads. */
export function warmUpServer(): void {
  if (!USE_MOCK) http.warmUp();
}

// The calls one by one, for call sites that use a single function
export const { searchLocation, createTrip, getTrip, generateRoutes, selectRoute, searchPois, getSavedPois, findPlaces, getForecast } =
  backend;
