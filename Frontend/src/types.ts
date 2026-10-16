import type { LineString } from "geojson";

// ---- Contract the UI is built against -------------------------------------

export type RouteType = "fastest" | "backroads";

export interface Place {
  name: string;
  lat: number;
  lon: number;
}

export interface ElevationPoint {
  mile: number;
  m: number;
}

export interface Route {
  id: number;
  route_type: RouteType;
  distance_miles: number;
  duration_seconds: number;
  ascent_m: number;
  descent_m: number;
  scenic_score: number;
  /** [lon, lat] pairs */
  geometry: LineString;
  /** Absent for routes saved before the backend kept elevation. */
  elevation_profile?: ElevationPoint[];
}

export interface ForecastDay {
  date: string;
  temp_max: number;
  temp_min: number;
  precip_probability: number;
  condition: string;
}

export interface WeatherPoint extends Place {
  forecast: ForecastDay[];
}

export interface Trip {
  id: number;
  origin: Place;
  destination: Place;
  selected_route_id: number | null;
  routes: Route[];
  weather: WeatherPoint[];
}

export interface Poi {
  id: number;
  name: string;
  category: string;
  lat: number;
  lon: number;
}

/** Result of one POI search, kept in state so the map can draw it. */
export interface PoiResult {
  /** Where the search was centred, e.g. "Los Angeles". */
  label: string;
  center: { lat: number; lon: number };
  items: Poi[];
}

export type CacheStatus ="hit" | "miss" | null;

export interface AgentStep {
  tool: string;
  ms: number;
  cache: CacheStatus;
}

export interface AgentReply {
  reply: string;
  steps: AgentStep[];
  state_changed: string[];
}

// ---- UI-side types ---------------------------------------------------------

/** A tool call as shown in the chat checklist; ms is null while it runs. */
export interface StepView {
  tool: string;
  status: "running" | "done" | "error";
  ms: number | null;
  cache: CacheStatus;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  text: string;
  steps: StepView[];
  pending: boolean;
  chips: string[];
}

/** Where a turn's tool calls came from, shown in the trace drawer. */
export type TurnSource = "mock" | "agent" | "scripted";

export interface AgentContext {
  trip: Trip | null;
  selectedRouteId: number | null;
}

/** What an agent turn hands back to the UI on top of the wire reply. */
export interface AgentTurnResult extends AgentReply {
  source: TurnSource;
  trip?: Trip;
  selectedRouteId?: number;
  pois?: PoiResult;
  chips: string[];
}

// ---- Raw shapes the FastAPI backend returns today ---------------------------

export interface RawLocationResult {
  label: string;
  lon: number;
  lat: number;
  confidence: number;
}

export interface RawLocationSearch {
  status: string;
  results: RawLocationResult[];
}

export interface RawTripCreated {
  status: string;
  message: string;
  trip_id: number;
}

export interface RawRoute {
  id: number;
  trip_id: number;
  route_type: string;
  scenic_score: number | null;
  distance_miles: number;
  duration_seconds: number;
  ascent_m: number | null;
  descent_m: number | null;
  is_selected: boolean;
  /** Simplified server-side; [lon, lat] pairs */
  geometry: LineString;
  /** Null for routes saved before the backend kept elevation. */
  elevation_profile: ElevationPoint[] | null;
  /** ISO 8601 with a UTC offset */
  created_at: string;
}

export interface RawRoutesGenerated {
  status: string;
  trip_id: number;
  routes: RawRoute[];
}

/** GET /trips/{id} */
export interface RawTrip {
  id: number;
  name: string | null;
  origin: Place;
  destination: Place;
  selected_route_id: number | null;
  routes: RawRoute[];
  created_at: string;
  updated_at: string;
}

export interface RawPoiSearch {
  status: string;
  count?: number;
  pois: Poi[];
  message?: string;
}

export interface RawForecast {
  forecast: ForecastDay[];
}
