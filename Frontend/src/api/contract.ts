import type {
  AgentApiResponse,
  AgentStreamEvent,
  ForecastDay,
  Place,
  PlaceGroup,
  PlaceKind,
  Poi,
  Route,
  SharedTrip,
  Trip,
} from "../types";

/**
 * What the app asks of the backend, split by concern so each consumer depends only on what it uses.
 * The HTTP client (http.ts) and the mock (mock.ts) both implement BackendApi, and either can stand in
 * for the other: same arguments, same results, same errors (ApiError).
 */

export interface LocationApi {
  /** GET /location/search */
  searchLocation(q: string): Promise<Place[]>;
}

export interface TripApi {
  /** POST /trips/ -> the new trip id */
  createTrip(origin: Place, destination: Place, name?: string): Promise<number>;
  /** GET /trips/{id}: a saved trip with its routes; weather starts empty */
  getTrip(tripId: number): Promise<Trip>;
  /** POST /routes/generate/{trip_id}. Not idempotent: each call adds two rows. */
  generateRoutes(tripId: number): Promise<Route[]>;
  /** POST /routes/select/{route_id} */
  selectRoute(routeId: number): Promise<void>;
  /** GET /shared/{public_id}: a trip from its share link, read-only. Its route ids are local, not the backend's. */
  getSharedTrip(publicId: string): Promise<SharedTrip>;
}

export interface PoiApi {
  /** GET /pois/search */
  searchPois(lat: number, lon: number): Promise<Poi[]>;
  /** GET /pois/: stops already saved; no external lookup */
  getSavedPois(lat: number, lon: number, radiusKm?: number): Promise<Poi[]>;
}

export interface PlacePoint {
  near: string;
  /** Shown in the list, e.g. "Night 1 · Paso Robles"; the backend's response carries its own */
  label: string;
  lat: number;
  lon: number;
  kinds: PlaceKind[];
}

export interface PlacesApi {
  /** POST /places/search: campsites and places to eat near each point, ranked best first */
  findPlaces(points: PlacePoint[]): Promise<PlaceGroup[]>;
}

export interface WeatherApi {
  /** GET /weather/forecast: the 7-day list */
  getForecast(lat: number, lon: number): Promise<ForecastDay[]>;
}

/** Everything the app reads and writes, apart from the agent. */
export type BackendApi = LocationApi & TripApi & PoiApi & PlacesApi & WeatherApi;

export interface AgentMessageBody {
  session_id: string;
  message: string;
  selected_route_id: number | null;
}

/** The backend's Claude agent. Real mode only: mock mode runs the scripted agent instead. */
export interface AgentApi {
  /** POST /agent/sessions -> a new conversation id */
  createAgentSession(): Promise<string>;
  /** POST /agent/message: one turn, answered when it finishes */
  sendAgentMessage(body: AgentMessageBody): Promise<AgentApiResponse>;
  /** POST /agent/message/stream: the same turn as server-sent events, resolving with the final answer */
  streamAgentMessage(body: AgentMessageBody, onEvent: (event: AgentStreamEvent) => void): Promise<AgentApiResponse>;
}
