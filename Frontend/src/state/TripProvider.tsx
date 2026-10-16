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
  selectedRouteId: number | null;
  hoverMile: number | null;
  /** Latest POI search, drawn on the map. Cleared when a new trip loads. */
  pois: PoiResult | null;
  messages: ChatMessage[];
  lastTurn: LastTurn | null;
  busy: boolean;
  error: string | null;
}

type Action =
  | { type: "ROUTE_SELECTED"; routeId: number | null }
  | { type: "HOVER"; mile: number | null }
  | { type: "TURN_STARTED"; user: ChatMessage; assistant: ChatMessage; contextRouteId: number | null }
  | { type: "STEPS_UPDATED"; messageId: number; steps: StepView[] }
  | { type: "TURN_FINISHED"; messageId: number; result: AgentTurnResult }
  | { type: "ERROR"; message: string | null };

const initialState: State = {
  trip: null,
  selectedRouteId: null,
  hoverMile: null,
  pois: null,
  messages: [],
  lastTurn: null,
  busy: false,
  error: null,
};

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
    case "TURN_STARTED":
      return {
        ...state,
        busy: true,
        messages: [...state.messages, action.user, action.assistant],
        lastTurn: {
          steps: [],
          source: api.USE_MOCK ? "mock" : "scripted",
          contextRouteId: action.contextRouteId,
          running: true,
        },
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
          m.id === action.messageId ? { ...m, text: result.reply, chips: result.chips, pending: false } : m,
        ),
        lastTurn: state.lastTurn && { ...state.lastTurn, source: result.source, running: false },
      };
    }
    case "ERROR":
      return { ...state, error: action.message };
  }
}

interface TripContextValue extends State {
  selectRoute: (routeId: number) => void;
  setHoverMile: (mile: number | null) => void;
  sendMessage: (text: string) => void;
}

const TripContext = createContext<TripContextValue | null>(null);

export function TripProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);
  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
  }, [state]);
  const nextId = useRef(1);

  const selectRoute = useCallback((routeId: number) => {
    const previous = stateRef.current.selectedRouteId;
    if (routeId === previous) return;
    dispatch({ type: "ROUTE_SELECTED", routeId });
    api.selectRoute(routeId).catch((error: unknown) => {
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
    dispatch({ type: "TURN_STARTED", user, assistant, contextRouteId: selectedRouteId });

    runAgentTurn(trimmed, { trip, selectedRouteId }, (steps) =>
      dispatch({ type: "STEPS_UPDATED", messageId: assistant.id, steps }),
    )
      .catch(
        (error: unknown): AgentTurnResult => ({
          reply: error instanceof Error ? error.message : String(error),
          steps: [],
          state_changed: [],
          source: api.USE_MOCK ? "mock" : "scripted",
          chips: [],
        }),
      )
      .then((result) => dispatch({ type: "TURN_FINISHED", messageId: assistant.id, result }));
  }, []);

  const value = useMemo(
    () => ({ ...state, selectRoute, setHoverMile, sendMessage }),
    [state, selectRoute, setHoverMile, sendMessage],
  );
  return <TripContext.Provider value={value}>{children}</TripContext.Provider>;
}

export function useTrip(): TripContextValue {
  const value = useContext(TripContext);
  if (!value) throw new Error("useTrip must be used inside TripProvider");
  return value;
}
