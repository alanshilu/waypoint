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
import type { AgentContext, AgentTurnResult, Place, Route, StepView, Trip } from "./types";

type StepListener = (steps: StepView[]) => void;

const shortName = (place: Place) => place.name.split(",")[0];

/**
 * Runs one agent turn.
 *
 * Real mode first tries POST /agent/message. The backend does not expose that
 * yet, so the fallback is a scripted runner: it reads the intent from the
 * message and calls the same endpoints the LLM agent's tools call, in the
 * order the agent's system prompt prescribes. Mock mode uses the same runner
 * over fixtures, so both modes exercise one code path.
 */
export async function runAgentTurn(
  message: string,
  context: AgentContext,
  onSteps: StepListener,
): Promise<AgentTurnResult> {
  const remote = await api.postAgentMessage(message, {
    trip_id: context.trip?.id ?? null,
    selected_route_id: context.selectedRouteId,
  });
  if (remote) {
    onSteps(remote.steps.map((s) => ({ ...s, status: "done" as const })));
    return {
      ...remote,
      source: "agent",
      trip: remote.trip,
      selectedRouteId: remote.trip?.selected_route_id ?? undefined,
      chips: [],
    };
  }
  return runScripted(message, context, onSteps);
}

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
    source: api.USE_MOCK ? "mock" : "scripted",
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
