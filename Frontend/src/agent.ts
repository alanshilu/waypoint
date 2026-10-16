import * as api from "./api";
import {
  formatClimbRatio,
  formatDuration,
  formatDurationDelta,
  formatMiles,
  formatScore,
  routeLabel,
} from "./format";
import { buildMileIndex, pointAtMile } from "./geo";
import type {
  AgentApiResponse,
  AgentContext,
  AgentStreamEvent,
  AgentTurnResult,
  Place,
  PlannedStop,
  PoiResult,
  Route,
  StepView,
  Trip,
} from "./types";

type StepListener = (steps: StepView[]) => void;

const shortName = (place: Place) => place.name.split(",")[0];

/**
 * Runs one agent turn.
 *
 * Real mode sends the message to the backend's Claude agent
 * (POST /agent/message/stream), shows each tool call as it happens, then
 * reloads the trip with GET /trips/{id} so the map, cards and chart match what
 * the agent did. Mock mode runs a scripted stand-in over the fixtures.
 */
export function runAgentTurn(message: string, context: AgentContext, onSteps: StepListener): Promise<AgentTurnResult> {
  return api.USE_MOCK ? runScripted(message, context, onSteps) : runRemote(message, context, onSteps);
}

// ---- Real mode: the backend agent ------------------------------------------

const SESSION_KEY = "waypoint.agent_session";

function storedSession(): string | null {
  try {
    return localStorage.getItem(SESSION_KEY);
  } catch {
    return null;
  }
}

function storeSession(id: string | null) {
  try {
    if (id) localStorage.setItem(SESSION_KEY, id);
    else localStorage.removeItem(SESSION_KEY);
  } catch {
    // storage unavailable (private window); the session just won't survive a reload
  }
}

async function runRemote(message: string, context: AgentContext, onSteps: StepListener): Promise<AgentTurnResult> {
  const steps: StepView[] = [];
  const emit = () => onSteps(steps.map((s) => ({ ...s })));
  const onEvent = (event: AgentStreamEvent) => {
    if (event.type === "tool_start") {
      steps.push({ tool: event.tool, status: "running", ms: null, cache: null, tokens: null });
    } else if (event.type === "tool_end") {
      const view = [...steps].reverse().find((s) => s.tool === event.tool && s.status === "running");
      if (view) {
        view.status = event.error ? "error" : "done";
        view.ms = event.ms;
        view.cache = event.cached ? "hit" : null;
        view.tokens = event.tokens;
      }
    }
    emit();
  };

  const ask = async (sessionId: string) =>
    api.streamAgentMessage(
      { session_id: sessionId, message, selected_route_id: context.userSelectedRouteId },
      onEvent,
    );

  let sessionId = storedSession() ?? (await api.createAgentSession());
  storeSession(sessionId);
  let response: AgentApiResponse;
  try {
    response = await ask(sessionId);
  } catch (error) {
    // Sessions expire after an hour without use, and restart with the backend: start a new one once
    if (!(error instanceof api.ApiError && error.code === "unknown_session")) throw error;
    sessionId = await api.createAgentSession();
    storeSession(sessionId);
    response = await ask(sessionId);
  }

  // The steps as the server recorded them (the live list can miss events if the stream hiccuped)
  const finalSteps: StepView[] = response.tool_calls.map((c) => ({
    tool: c.tool,
    status: c.error ? "error" : "done",
    ms: c.ms,
    cache: c.cached ? "hit" : null,
    tokens: c.tokens,
  }));
  onSteps(finalSteps);

  let trip: Trip | undefined;
  const warnings: string[] = [];
  if (response.trip_id != null) {
    try {
      trip = await api.getTrip(response.trip_id);
      trip.weather = arrivalWeather(trip, response.planned_stops);
    } catch (error) {
      warnings.push(`Could not load trip ${response.trip_id}: ${error instanceof Error ? error.message : error}`);
    }
  }

  const pois = stopsFrom(response);
  return {
    reply: [response.reply, ...warnings].filter(Boolean).join("\n\n"),
    steps: response.tool_calls.map((c) => ({ tool: c.tool, ms: c.ms, cache: c.cached ? "hit" : null, tokens: c.tokens })),
    state_changed: [...(trip ? ["trip"] : []), ...(pois ? ["pois"] : [])],
    source: "agent",
    trip,
    selectedRouteId: trip?.selected_route_id ?? undefined,
    pois,
    chips: trip ? agentChips(trip) : [],
  };
}

/** The forecast for the destination's arrival date, if the agent planned stops. */
function arrivalWeather(trip: Trip, stops: PlannedStop[]): Trip["weather"] {
  const destination = stops.find((s) => s.kind === "destination" && s.forecast);
  return destination?.forecast ? [{ ...trip.destination, forecast: [destination.forecast] }] : [];
}

const shortDate = (iso: string) =>
  new Date(`${iso}T12:00:00`).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });

/** What the map's stop list shows: the planned overnight stops, else the last POI search. */
function stopsFrom(response: AgentApiResponse): PoiResult | undefined {
  const planned = response.planned_stops;
  if (planned.length > 0) {
    return {
      label: "your planned stops",
      center: { lat: planned[0].lat, lon: planned[0].lon },
      items: planned.map((s, i) => ({
        id: i + 1,
        name: s.name,
        category: `day ${s.day}, ${shortDate(s.arrival_date)}`,
        lat: s.lat,
        lon: s.lon,
      })),
    };
  }
  if (response.pois && response.pois.items.length > 0) {
    return { label: "the search point", center: response.pois.center, items: response.pois.items };
  }
  return undefined;
}

function agentChips(trip: Trip): string[] {
  const selects = trip.routes.filter((r) => r.id !== trip.selected_route_id).map((r) => `Select ${r.route_type}`);
  return [...selects, "Where should I stop overnight?", "What's the weather when I arrive?"];
}

// ---- Mock mode: scripted stand-in over the fixtures ------------------------

/**
 * Reads the intent from the message and calls the same functions the agent's
 * tools call, in the order the agent's system prompt prescribes, against
 * the fixtures in src/fixtures.
 */
async function runScripted(
  message: string,
  context: AgentContext,
  onSteps: StepListener,
): Promise<AgentTurnResult> {
  const steps: StepView[] = [];
  const emit = () => onSteps(steps.map((s) => ({ ...s })));

  async function step<T>(tool: string, call: () => Promise<T>): Promise<T> {
    const view: StepView = { tool, status: "running", ms: null, cache: null };
    steps.push(view);
    emit();
    const started = performance.now();
    try {
      const value = await call();
      view.status = "done";
      view.cache = api.callMeta.cache;
      return value;
    } catch (error) {
      view.status = "error";
      throw error;
    } finally {
      view.ms = Math.round(performance.now() - started);
      emit();
    }
  }

  const finish = (
    reply: string,
    extra: Partial<Pick<AgentTurnResult, "state_changed" | "trip" | "selectedRouteId" | "pois" | "chips">> = {},
  ): AgentTurnResult => ({
    reply,
    steps: steps.map((s) => ({ tool: s.tool, ms: s.ms ?? 0, cache: s.cache })),
    state_changed: extra.state_changed ?? [],
    source: "mock",
    trip: extra.trip,
    selectedRouteId: extra.selectedRouteId,
    pois: extra.pois,
    chips: extra.chips ?? [],
  });

  const { trip, selectedRouteId } = context;
  const text = message.trim();
  const lower = text.toLowerCase();

  try {
    // 1. Route selection
    const wanted = /backroad|scenic/.test(lower) ? "backroads" : /fast|quick/.test(lower) ? "fastest" : null;
    const isSelection = wanted && (/select|choose|pick|go with|take|switch|use/.test(lower) || lower === wanted);
    if (isSelection) {
      const route = trip?.routes.find((r) => r.route_type === wanted);
      if (!trip || !route) return finish("There is no trip yet. Tell me where you are driving from and to.");
      if (route.id === selectedRouteId) {
        return finish(`${routeLabel(route.route_type)} (route ${route.id}) is already selected.`, {
          chips: followUps(trip, route.id),
        });
      }
      await step("select_route", () => api.selectRoute(route.id));
      return finish(`${routeLabel(route.route_type)} selected: ${describe(route)}.`, {
        state_changed: ["selected_route"],
        selectedRouteId: route.id,
        chips: followUps(trip, route.id),
      });
    }

    // 2. New trip: "<origin> to <destination>"
    // An explicit "from X to Y" always plans; a bare "X to Y" only does when
    // the message is not a follow-up question about the current trip.
    const explicit = text.match(/\bfrom\s+(.+?)\s+to\s+(.+?)[.?!]*$/i);
    const isFollowUp = !!trip && /weather|forecast|rain|temperature|stop|poi|food|eat|fuel|gas|coffee|near/.test(lower);
    const match = explicit ?? (isFollowUp ? null : text.match(/^(?:plan\s+)?(.+?)\s+to\s+(.+?)[.?!]*$/i));
    if (match) {
      const [origin] = await step("geocode_location", () => api.searchLocation(match[1]));
      const [destination] = await step("geocode_location", () => api.searchLocation(match[2]));
      if (!origin || !destination) {
        const missing = !origin ? match[1] : match[2];
        const hint = api.USE_MOCK ? " Mock mode only knows San Francisco and Los Angeles." : "";
        return finish(`I could not find a location for "${missing}".${hint}`);
      }
      const tripId = await step("create_trip", () =>
        api.createTrip(origin, destination, `${shortName(origin)} to ${shortName(destination)}`),
      );
      const routes = await step("generate_routes", () => api.generateRoutes(tripId));
      const newTrip: Trip = { id: tripId, origin, destination, selected_route_id: null, routes, weather: [] };

      // Weather is a nice-to-have: a failure here must not lose the routes.
      let weatherNote = "";
      try {
        const forecast = await step("get_weather_forecast", () => api.getForecast(destination.lat, destination.lon));
        newTrip.weather = [{ ...destination, forecast }];
        const today = forecast[0];
        if (today) {
          weatherNote = ` ${shortName(destination)} forecast: ${today.condition.toLowerCase()}, ${Math.round(today.temp_max)}°/${Math.round(today.temp_min)}°F.`;
        }
      } catch {
        weatherNote = " The weather lookup failed, so no forecast is shown.";
      }

      return finish(compare(newTrip) + weatherNote + " Which route do you want?", {
        state_changed: ["trip"],
        trip: newTrip,
        chips: followUps(newTrip, null),
      });
    }

    // 3. Follow-ups on the current trip
    if (/weather|forecast|rain|temperature/.test(lower)) {
      if (!trip) return finish("There is no trip yet. Tell me where you are driving from and to.");
      const forecast = await step("get_weather_forecast", () =>
        api.getForecast(trip.destination.lat, trip.destination.lon),
      );
      const days = forecast
        .slice(0, 3)
        .map((d) => `${d.date}: ${d.condition.toLowerCase()}, ${Math.round(d.temp_max)}°/${Math.round(d.temp_min)}°F, ${d.precip_probability}% rain`)
        .join("; ");
      const updated: Trip = { ...trip, weather: [{ ...trip.destination, forecast }] };
      return finish(days ? `${shortName(trip.destination)}: ${days}.` : "No forecast came back.", {
        state_changed: ["trip"],
        trip: updated,
        selectedRouteId: selectedRouteId ?? undefined,
        chips: followUps(trip, selectedRouteId),
      });
    }

    if (/stop|poi|food|eat|fuel|gas|coffee|near/.test(lower)) {
      if (!trip) return finish("There is no trip yet. Tell me where you are driving from and to.");
      // "along the route" searches around the midpoint of the selected route
      // (fastest if none is selected); anything else searches the destination.
      // The backend only searches around one point per call.
      let label = shortName(trip.destination);
      let center = { lat: trip.destination.lat, lon: trip.destination.lon };
      const route = trip.routes.find((r) => r.id === selectedRouteId) ?? trip.routes[0];
      if (route && /along|midpoint|halfway|half way|on the way|en route/.test(lower)) {
        const index = buildMileIndex(route.geometry, route.distance_miles);
        const mid = pointAtMile(index, index.totalMiles / 2);
        if (mid) {
          center = { lat: mid[1], lon: mid[0] };
          label = `the midpoint of the ${route.route_type} route`;
        }
      }
      const items = await step("search_pois", () => api.searchPois(center.lat, center.lon));
      const list = items
        .slice(0, 5)
        .map((p) => `${p.name} (${p.category.replace(/_/g, " ")})`)
        .join(", ");
      const more = items.length > 5 ? ` and ${items.length - 5} more` : "";
      return finish(
        list
          ? `${items.length} stops near ${label}: ${list}${more}. They are numbered on the map.`
          : `No stops found near ${label}.`,
        {
          state_changed: ["pois"],
          pois: { label, center, items },
          chips: followUps(trip, selectedRouteId),
        },
      );
    }

    const selected = trip?.routes.find((r) => r.id === selectedRouteId);
    const status = selected
      ? ` Route ${selected.id} (${selected.route_type}) is currently selected.`
      : trip
        ? " No route is selected yet."
        : "";
    return finish(
      `I can plan a trip ("San Francisco to Los Angeles"), select a route, check the weather or find stops.${status}`,
      { chips: trip ? followUps(trip, selectedRouteId) : ["San Francisco to Los Angeles"] },
    );
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    const failed = steps[steps.length - 1]?.tool ?? "request";
    return finish(`${failed} failed: ${reason}`, { chips: trip ? followUps(trip, selectedRouteId) : [] });
  }
}

function describe(route: Route): string {
  return `${formatDuration(route.duration_seconds)}, ${formatMiles(route.distance_miles)}, scenic ${formatScore(route.scenic_score)}`;
}

function compare(trip: Trip): string {
  const fastest = trip.routes.find((r) => r.route_type === "fastest");
  const backroads = trip.routes.find((r) => r.route_type === "backroads");
  const head = `${shortName(trip.origin)} to ${shortName(trip.destination)}.`;
  if (!fastest || !backroads) {
    return `${head} ${trip.routes.map((r) => `${routeLabel(r.route_type)}: ${describe(r)}`).join(". ")}.`;
  }
  const climb = formatClimbRatio(backroads.ascent_m, fastest.ascent_m);
  const delta = formatDurationDelta(backroads.duration_seconds - fastest.duration_seconds);
  return (
    `${head} Fastest: ${describe(fastest)}. Backroads: ${describe(backroads)}. ` +
    `Backroads is ${delta}${climb ? ` with ${climb}` : ""}.`
  );
}

function followUps(trip: Trip, selectedRouteId: number | null): string[] {
  const selects = trip.routes
    .filter((r) => r.id !== selectedRouteId)
    .map((r) => `Select ${r.route_type}`);
  return [...selects, "Weather at destination", "Stops near destination", "Stops along the route"];
}
