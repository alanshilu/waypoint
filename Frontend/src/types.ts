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

/**
 * One turn-by-turn step from OpenRouteService. type: 0 left, 1 right, 2 sharp left, 3 sharp right,
 * 4 slight left, 5 slight right, 6 straight, 7 enter roundabout, 8 exit roundabout, 9 U-turn,
 * 10 arrive, 11 depart, 12 keep left, 13 keep right.
 */
export interface DirectionStep {
  instruction: string;
  /** Null when ORS has no name for the road, common on motorways */
  name: string | null;
  type: number;
  distance_miles: number;
  duration_seconds: number;
  /** [lon, lat] where the step starts and ends, from the full-resolution route */
  start: [number, number];
  end: [number, number];
}

export interface Route {
  id: number;
  route_type: RouteType;
  distance_miles: number;
  duration_seconds: number;
  ascent_m: number;
  descent_m: number;
  /** Terrain only, 0-100 (higher is hillier). Unitless: compare routes, don't quote it "out of 100". */
  scenic_score: number;
  /** Duration divided by the fastest route's duration; slowness is kept out of the scenic score. */
  duration_vs_fastest?: number | null;
  /** [lon, lat] pairs */
  geometry: LineString;
  /** Absent for routes saved before the backend kept elevation. */
  elevation_profile?: ElevationPoint[];
  /** Turn-by-turn steps; null for routes saved before the backend kept them. */
  directions?: DirectionStep[] | null;
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

/** stay: anywhere to spend the night, from campgrounds to hotels */
export type PlaceKind = "stay" | "food";

/** A place to stay or eat from find_places (OpenStreetMap). */
export interface PlaceOption {
  id: string;
  kind: PlaceKind;
  /**
   * stay: camp_site, caravan_site, hotel, motel, guest_house, hostel, chalet, apartment;
   * food: restaurant, fast_food, cafe, food_court
   */
  category: string;
  name: string;
  lat: number;
  lon: number;
  /** From the stop or lunch point the search was around */
  distance_mi: number;
  /** Straight from the place's OpenStreetMap tags: "toilets", "tents allowed", "hours: ..." */
  facts: string[];
  website?: string;
  /** The agent picked it */
  recommended?: boolean;
  /** Why the agent picked it */
  reason?: string | null;
}

/** The places of one kind found near one point of the trip (an overnight stop or a lunch stop). */
export interface PlaceGroup {
  /** The plan_stops id the search was for */
  near: string;
  /** e.g. "Night 1 · San Benito County" or "Lunch, day 1 · near Gilroy" */
  label: string;
  kind: PlaceKind;
  lat: number;
  lon: number;
  radius_mi: number;
  /** openstreetmap, openrouteservice (fallback), none, or mock */
  source: string;
  /** Why a search came back empty or smaller than usual */
  note?: string;
  places: PlaceOption[];
}

export type CacheStatus = "hit" | "miss" | null;

/** Tokens of the model call that requested a tool (shared by tool calls from the same call). */
export interface StepTokens {
  input: number;
  output: number;
  cache_read: number;
  cache_write: number;
}

export interface AgentStep {
  tool: string;
  ms: number;
  cache: CacheStatus;
  tokens?: StepTokens | null;
}

export interface AgentReply {
  reply: string;
  steps: AgentStep[];
  state_changed: string[];
}

// ---- POST /agent/message(/stream) ------------------------------------------

export interface AgentFinalAnswer {
  summary: string;
  recommended_route_type: "fastest" | "backroads" | "none";
  departure_window: { start: string; end: string; reason: string };
  stops: string[];
  warnings: string[];
}

export interface AgentToolCall {
  tool: string;
  ms: number;
  cached: boolean;
  error: string | null;
  tokens: StepTokens | null;
  model_call: number;
}

/** A stop from plan_stops that the agent's answer recommends. */
export interface PlannedStop {
  id: string;
  day: number;
  kind: "overnight" | "destination";
  name: string;
  lat: number;
  lon: number;
  cumulative_miles?: number;
  cumulative_drive_hours?: number;
  arrival_date: string;
  arrival_time?: string;
  forecast?: ForecastDay | null;
}

export interface AgentApiResponse {
  session_id: string;
  trip_id: number | null;
  reply: string;
  answer: AgentFinalAnswer;
  planned_stops: PlannedStop[];
  /** Campsites and places to eat found this turn, picks marked; absent from older backends */
  places?: PlaceGroup[];
  pois: { center: { lat: number; lon: number }; items: Poi[] } | null;
  tool_calls: AgentToolCall[];
  usage: { input_tokens: number; output_tokens: number; requests: number };
}

/** Server-sent events from POST /agent/message/stream. */
export type AgentStreamEvent =
  | { type: "start"; session_id: string }
  | { type: "tool_start"; tool: string; args: Record<string, unknown> }
  | { type: "tool_end"; tool: string; ms: number; error: string | null; cached: boolean; tokens: StepTokens | null };

// ---- UI-side types ---------------------------------------------------------

/** A tool call as shown in the chat checklist; ms is null while it runs. */
export interface StepView {
  tool: string;
  status: "running" | "done" | "error";
  ms: number | null;
  cache: CacheStatus;
  tokens?: StepTokens | null;
  /** Why the tool failed, as the backend reported it */
  error?: string | null;
  /** When it started (Date.now()), for the elapsed time while it runs */
  startedAt?: number;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  text: string;
  steps: StepView[];
  pending: boolean;
  chips: string[];
  /** The turn failed; the text is the error and the UI offers a retry. */
  failed?: boolean;
}

/** Where a turn's tool calls came from, shown in the trace drawer. */
export type TurnSource = "mock" | "agent";

export interface AgentContext {
  trip: Trip | null;
  selectedRouteId: number | null;
  /** A route the user picked on the map since the last message; sent so the agent knows. */
  userSelectedRouteId: number | null;
}

/** What an agent turn hands back to the UI on top of the wire reply. */
export interface AgentTurnResult extends AgentReply {
  source: TurnSource;
  trip?: Trip;
  selectedRouteId?: number;
  pois?: PoiResult;
  places?: PlaceGroup[];
  chips: string[];
  failed?: boolean;
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
  /** Added with the terrain-only score; absent from older backends. */
  duration_vs_fastest?: number | null;
  distance_miles: number;
  duration_seconds: number;
  ascent_m: number | null;
  descent_m: number | null;
  is_selected: boolean;
  /** Simplified server-side; [lon, lat] pairs */
  geometry: LineString;
  /** Null for routes saved before the backend kept elevation. */
  elevation_profile: ElevationPoint[] | null;
  /** Null for routes saved before the backend kept directions; absent from older backends. */
  directions?: DirectionStep[] | null;
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
