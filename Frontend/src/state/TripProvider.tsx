import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef } from "react";
import type { ReactNode } from "react";
import * as api from "../api";
import { runAgentTurn } from "../agent";
import type { AgentTurnResult, ChatMessage, PoiResult, StepView, Trip, TurnSource } from "../types";

export interface LastTurn {
  steps: StepView[];
  source: TurnSource;
  /** Route id sent along with the user's message, if any. */
  contextRouteId: number | null;
  running: boolean;
}

interface State {
  trip: Trip | null;
  /** A saved trip is being loaded (on page load, from the URL or local storage). */
  tripLoading: boolean;
  selectedRouteId: number | null;
  hoverMile: number | null;
  /** Latest POI search or planned stops, drawn on the map. Cleared when a new trip loads. */
  pois: PoiResult | null;
  messages: ChatMessage[];
  lastTurn: LastTurn | null;
  busy: boolean;
  error: string | null;
}

type Action =
  | { type: "ROUTE_SELECTED"; routeId: number | null }
  | { type: "HOVER"; mile: number | null }
  | { type: "TRIP_LOADING" }
  | { type: "TRIP_RESTORED"; trip: Trip }
  | { type: "TRIP_RESTORE_FAILED"; message: string }
  | { type: "TURN_STARTED"; user: ChatMessage; assistant: ChatMessage; contextRouteId: number | null }
  | { type: "STEPS_UPDATED"; messageId: number; steps: StepView[] }
  | { type: "TURN_FINISHED"; messageId: number; result: AgentTurnResult }
  | { type: "ERROR"; message: string | null };

const initialState: State = {
  trip: null,
  tripLoading: false,
  selectedRouteId: null,
  hoverMile: null,
  pois: null,
  messages: [],
  lastTurn: null,
  busy: false,
  error: null,
};

const SOURCE: TurnSource = api.USE_MOCK ? "mock" : "agent";

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "ROUTE_SELECTED":
      return {
        ...state,
        selectedRouteId: action.routeId,
        trip: state.trip && { ...state.trip, selected_route_id: action.routeId },
        error: null,
      };
    case "HOVER":
      return state.hoverMile === action.mile ? state : { ...state, hoverMile: action.mile };
    case "TRIP_LOADING":
      return { ...state, tripLoading: true };
    case "TRIP_RESTORED":
      return {
        ...state,
        tripLoading: false,
        trip: action.trip,
        selectedRouteId: action.trip.selected_route_id,
        pois: null,
      };
    case "TRIP_RESTORE_FAILED":
      return { ...state, tripLoading: false, error: action.message };
    case "TURN_STARTED":
      return {
        ...state,
        busy: true,
        messages: [...state.messages, action.user, action.assistant],
        lastTurn: { steps: [], source: SOURCE, contextRouteId: action.contextRouteId, running: true },
      };
    case "STEPS_UPDATED":
      return {
        ...state,
        messages: state.messages.map((m) => (m.id === action.messageId ? { ...m, steps: action.steps } : m)),
        lastTurn: state.lastTurn && { ...state.lastTurn, steps: action.steps },
      };
    case "TURN_FINISHED": {
      const { result } = action;
      // The agent and the UI write to the same state: apply what the turn changed.
      let { trip, selectedRouteId, pois } = state;
      if (result.state_changed.includes("trip") && result.trip) {
        if (result.trip.id !== trip?.id) pois = null;
        trip = result.trip;
        selectedRouteId = result.selectedRouteId ?? result.trip.selected_route_id;
      }
      if (result.state_changed.includes("selected_route") && result.selectedRouteId != null) {
        selectedRouteId = result.selectedRouteId;
      }
      if (trip && trip.selected_route_id !== selectedRouteId) {
        trip = { ...trip, selected_route_id: selectedRouteId };
      }
      return {
        ...state,
        trip,
        selectedRouteId,
        pois: result.state_changed.includes("pois") && result.pois ? result.pois : pois,
        hoverMile: null,
        busy: false,
        messages: state.messages.map((m) =>
          m.id === action.messageId
            ? { ...m, text: result.reply, chips: result.chips, pending: false, failed: result.failed }
            : m,
        ),
        lastTurn: state.lastTurn && { ...state.lastTurn, source: result.source, running: false },
      };
    }
    case "ERROR":
      return { ...state, error: action.message };
  }
}

/** What to tell the user when a turn fails, by the backend's error code. */
function failureText(error: unknown): string {
  if (error instanceof api.ApiError) {
    switch (error.code) {
      case "rate_limited":
        return "You're sending messages faster than the agent allows. Wait a moment, then try again.";
      case "session_busy":
        return "The agent is still answering your previous message.";
      case "agent_timeout":
        return "The agent took too long to answer. Try again, or ask for less at once.";
      case "model_rate_limited":
      case "model_api_unreachable":
      case "model_api_error":
        return `The AI service is unavailable right now (${error.message}). Try again shortly.`;
      case "unreachable":
        return `Can't reach the Waypoint backend at ${api.API_BASE}. Is it running?`;
    }
    return error.message;
  }
  return error instanceof Error ? error.message : String(error);
}

const TRIP_KEY = "waypoint.trip_id";

/** The trip to restore on load: ?trip=ID in the URL wins over local storage. */
function savedTripId(): number | null {
  const fromUrl = new URLSearchParams(window.location.search).get("trip");
  let raw = fromUrl;
  if (!raw) {
    try {
      raw = localStorage.getItem(TRIP_KEY);
    } catch {
      raw = null;
    }
  }
  const id = Number(raw);
  return Number.isInteger(id) && id > 0 ? id : null;
}

function rememberTrip(id: number | null) {
  try {
    if (id) localStorage.setItem(TRIP_KEY, String(id));
    else localStorage.removeItem(TRIP_KEY);
  } catch {
    // storage unavailable; the URL still carries the trip
  }
  const url = new URL(window.location.href);
  if (id) url.searchParams.set("trip", String(id));
  else url.searchParams.delete("trip");
  window.history.replaceState(null, "", url);
}

interface TripContextValue extends State {
  selectRoute: (routeId: number) => void;
  setHoverMile: (mile: number | null) => void;
  sendMessage: (text: string) => void;
  retryLast: () => void;
}

const TripContext = createContext<TripContextValue | null>(null);

export function TripProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);
  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
  }, [state]);
  const nextId = useRef(1);
  // A route picked on the map since the last message; sent with the next one so the agent knows
  const pickedRouteId = useRef<number | null>(null);

  // Restore the last trip after a reload (real mode; mock mode always starts empty)
  const restored = useRef(false);
  useEffect(() => {
    if (restored.current || api.USE_MOCK) return;
    restored.current = true;
    const id = savedTripId();
    if (id === null) return;
    dispatch({ type: "TRIP_LOADING" });
    api
      .getTrip(id)
      .then((trip) => dispatch({ type: "TRIP_RESTORED", trip }))
      .catch((error: unknown) => {
        rememberTrip(null);
        dispatch({
          type: "TRIP_RESTORE_FAILED",
          message: `Could not restore trip ${id}: ${error instanceof Error ? error.message : String(error)}`,
        });
      });
  }, []);

  // Keep the URL and local storage pointing at the current trip
  const tripId = state.trip?.id ?? null;
  useEffect(() => {
    if (tripId !== null && !api.USE_MOCK) rememberTrip(tripId);
  }, [tripId]);

  const selectRoute = useCallback((routeId: number) => {
    const previous = stateRef.current.selectedRouteId;
    if (routeId === previous) return;
    dispatch({ type: "ROUTE_SELECTED", routeId });
    pickedRouteId.current = routeId;
    api.selectRoute(routeId).catch((error: unknown) => {
      pickedRouteId.current = null;
      dispatch({ type: "ROUTE_SELECTED", routeId: previous });
      dispatch({
        type: "ERROR",
        message: `Could not select route ${routeId}: ${error instanceof Error ? error.message : String(error)}`,
      });
    });
  }, []);

  const setHoverMile = useCallback((mile: number | null) => dispatch({ type: "HOVER", mile }), []);

  const sendMessage = useCallback((text: string) => {
    const { trip, selectedRouteId, busy } = stateRef.current;
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    const user: ChatMessage = { id: nextId.current++, role: "user", text: trimmed, steps: [], pending: false, chips: [] };
    const assistant: ChatMessage = { id: nextId.current++, role: "assistant", text: "", steps: [], pending: true, chips: [] };
    const userSelectedRouteId = pickedRouteId.current;
    pickedRouteId.current = null;
    dispatch({ type: "TURN_STARTED", user, assistant, contextRouteId: userSelectedRouteId ?? selectedRouteId });

    runAgentTurn(trimmed, { trip, selectedRouteId, userSelectedRouteId }, (steps) =>
      dispatch({ type: "STEPS_UPDATED", messageId: assistant.id, steps }),
    )
      .catch((error: unknown): AgentTurnResult => {
        // keep the map selection for the retry
        if (pickedRouteId.current === null) pickedRouteId.current = userSelectedRouteId;
        return { reply: failureText(error), steps: [], state_changed: [], source: SOURCE, chips: [], failed: true };
      })
      .then((result) => dispatch({ type: "TURN_FINISHED", messageId: assistant.id, result }));
  }, []);

  const retryLast = useCallback(() => {
    const lastUser = [...stateRef.current.messages].reverse().find((m) => m.role === "user");
    if (lastUser) sendMessage(lastUser.text);
  }, [sendMessage]);

  const value = useMemo(
    () => ({ ...state, selectRoute, setHoverMile, sendMessage, retryLast }),
    [state, selectRoute, setHoverMile, sendMessage, retryLast],
  );
  return <TripContext.Provider value={value}>{children}</TripContext.Provider>;
}

export function useTrip(): TripContextValue {
  const value = useContext(TripContext);
  if (!value) throw new Error("useTrip must be used inside TripProvider");
  return value;
}
