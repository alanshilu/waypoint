import type { AgentApi, TripApi } from "../api/contract";
import { ApiError } from "../api/errors";
import type { AgentApiResponse, AgentStreamEvent, PlannedStop, PoiResult, StepView, Trip } from "../types";
import type { AgentRunner } from "./runner";
import { agentChips } from "./text";

const SESSION_KEY = "waypoint.agent_session";

/** Where the conversation id is kept between page loads. */
export interface SessionStore {
  get(): string | null;
  set(id: string | null): void;
}

/** localStorage, or nothing when it's unavailable (a private window): the session then just won't survive a reload. */
export const browserSessionStore: SessionStore = {
  get() {
    try {
      return localStorage.getItem(SESSION_KEY);
    } catch {
      return null;
    }
  },
  set(id) {
    try {
      if (id) localStorage.setItem(SESSION_KEY, id);
      else localStorage.removeItem(SESSION_KEY);
    } catch {
      // storage unavailable
    }
  },
};

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

/**
 * The backend's Claude agent (POST /agent/message/stream): shows each tool call as it happens, then reloads
 * the trip with GET /trips/{id} so the map, cards and chart match what the agent did.
 */
export function createRemoteAgent(agent: AgentApi, trips: Pick<TripApi, "getTrip">, sessions: SessionStore = browserSessionStore): AgentRunner {
  return {
    async run(message, context, onSteps) {
      const steps: StepView[] = [];
      const emit = () => onSteps(steps.map((s) => ({ ...s })));
      const onEvent = (event: AgentStreamEvent) => {
        if (event.type === "tool_start") {
          steps.push({ tool: event.tool, status: "running", ms: null, cache: null, tokens: null, startedAt: Date.now() });
        } else if (event.type === "tool_end") {
          const view = [...steps].reverse().find((s) => s.tool === event.tool && s.status === "running");
          if (view) {
            view.status = event.error ? "error" : "done";
            view.error = event.error;
            view.ms = event.ms;
            view.cache = event.cached ? "hit" : null;
            view.tokens = event.tokens;
          }
        }
        emit();
      };

      const ask = (sessionId: string) =>
        agent.streamAgentMessage({ session_id: sessionId, message, selected_route_id: context.userSelectedRouteId }, onEvent);

      let sessionId = sessions.get() ?? (await agent.createAgentSession());
      sessions.set(sessionId);
      let response: AgentApiResponse;
      try {
        response = await ask(sessionId);
      } catch (error) {
        // Sessions expire after a while without use (AGENT_SESSION_TTL_S), and restart with the backend: start a new one once
        if (!(error instanceof ApiError && error.code === "unknown_session")) throw error;
        sessionId = await agent.createAgentSession();
        sessions.set(sessionId);
        response = await ask(sessionId);
      }

      // The steps as the server recorded them (the live list can miss events if the stream hiccuped)
      onSteps(
        response.tool_calls.map((c) => ({
          tool: c.tool,
          status: c.error ? "error" : "done",
          error: c.error,
          ms: c.ms,
          cache: c.cached ? "hit" : null,
          tokens: c.tokens,
        })),
      );

      let trip: Trip | undefined;
      const warnings: string[] = [];
      if (response.trip_id != null) {
        try {
          trip = await trips.getTrip(response.trip_id);
          trip.weather = arrivalWeather(trip, response.planned_stops);
        } catch (error) {
          warnings.push(`Could not load trip ${response.trip_id}: ${error instanceof Error ? error.message : error}`);
        }
      }

      const pois = stopsFrom(response);
      const places = response.places && response.places.length > 0 ? response.places : undefined;
      return {
        reply: [response.reply, ...warnings].filter(Boolean).join("\n\n"),
        steps: response.tool_calls.map((c) => ({ tool: c.tool, ms: c.ms, cache: c.cached ? "hit" : null, tokens: c.tokens })),
        state_changed: [...(trip ? ["trip"] : []), ...(pois ? ["pois"] : []), ...(places ? ["places"] : [])],
        source: "agent",
        trip,
        selectedRouteId: trip?.selected_route_id ?? undefined,
        pois,
        places,
        chips: trip ? agentChips(trip) : [],
      };
    },
  };
}
