import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { capabilities } from "../api";
import { routeName } from "../format";

// The scripted mock answers from fixtures; only the real agent takes the user's own Anthropic key
const MOCK_REPLIES = capabilities.replies === "mock";
import { usePrefs } from "../state/prefs";
import { useTrip } from "../state/TripProvider";
import type { StepView } from "../types";
import OwnKeyPanel from "./OwnKeyPanel";
import ServerWaking from "./ServerWaking";

// The mock agent only knows San Francisco to Los Angeles; the real one takes any US drive
const STARTER_CHIPS = MOCK_REPLIES
  ? ["San Francisco to Los Angeles"]
  : ["San Francisco to Los Angeles", "Dallas to Minneapolis, leave tomorrow at 8am", "Seattle to Portland on the scenic route"];

const STATUS_LABEL: Record<StepView["status"], string> = {
  running: "running",
  done: "done",
  error: "failed",
};

/** Each tool as a checklist item reads, outside the developer view. */
const STEP_LABEL: Record<string, string> = {
  geocode_location: "Look up the place",
  create_trip: "Save the trip",
  generate_routes: "Find the routes",
  plan_stops: "Plan the stops",
  get_weather_forecast: "Check the weather",
  search_pois: "Find stops nearby",
  find_places: "Find places to stay and eat",
  select_route: "Select the route",
};

/**
 * What the agent did this turn, shown above its reply: in plain words, or in the developer view the raw tool
 * names and timings. A failure always says why.
 */
function StepChecklist({ steps }: { steps: StepView[] }) {
  const { developerView } = usePrefs();
  if (steps.length === 0) return null;
  return (
    <ol className="steps" aria-label={developerView ? "Tool calls" : "What the agent did"}>
      {steps.map((step, i) => (
        <li key={i} className={`step ${step.status}`}>
          <span className="step-mark" aria-hidden="true">
            {step.status === "done" ? "✓" : step.status === "error" ? "×" : ""}
          </span>
          <span className="step-tool">{developerView ? step.tool : (STEP_LABEL[step.tool] ?? step.tool)}</span>
          <span className="sr-only">{STATUS_LABEL[step.status]}</span>
          {developerView && <span className="step-ms">{step.ms === null ? "…" : `${step.ms} ms`}</span>}
          {step.status === "error" && step.error && <span className="step-error">{step.error}</span>}
        </li>
      ))}
    </ol>
  );
}

/** What the agent is doing right now, in words, from the tool it is running. */
const ACTIVITY: Record<string, string> = {
  geocode_location: "Looking up places",
  create_trip: "Saving the trip",
  generate_routes: "Searching routes",
  plan_stops: "Planning overnight stops",
  get_weather_forecast: "Checking the weather",
  search_pois: "Finding places to stop",
  find_places: "Finding places to stay and eat",
  select_route: "Selecting the route",
};

// Shown once a tool has run this long (s), so a slow step reads as working, not stuck. The place search
// waits for OpenStreetMap's free servers however long they take.
const SLOW_NOTES: Record<string, { after: number; text: string }> = {
  find_places: {
    after: 15,
    text: "OpenStreetMap's free servers can be slow. Still searching; this can take a few minutes.",
  },
};
// The running time shows from this many seconds in
const SHOW_ELAPSED_AFTER_S = 3;

/** Re-renders every second while mounted. */
function useEverySecond(): number {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  return now;
}

/** What the agent is doing now, how long the current tool has been at it, and a word when that's slow. */
function PendingStatus({ steps }: { steps: StepView[] }) {
  const now = useEverySecond();
  const running = [...steps].reverse().find((s) => s.status === "running");
  // between tool calls the model is deciding what to do next, or writing the answer
  if (!running) return <p className="msg-pending" role="status">Thinking…</p>;
  const elapsed = running.startedAt ? Math.floor((now - running.startedAt) / 1000) : 0;
  const slow = SLOW_NOTES[running.tool];
  return (
    <p className="msg-pending" role="status">
      {ACTIVITY[running.tool] ?? `Running ${running.tool}`}…
      {elapsed >= SHOW_ELAPSED_AFTER_S && (
        // not announced: a screen reader would read it every second
        <span className="msg-elapsed data" aria-hidden="true">
          {" "}
          {elapsed} s
        </span>
      )}
      {slow && elapsed >= slow.after && <span className="msg-slow">{slow.text}</span>}
    </p>
  );
}

interface Props {
  /** Folded into a narrow rail; the chat stays mounted, so a half-typed message survives */
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onOpenGuide: () => void;
}

export default function ChatPanel({ collapsed, onToggleCollapsed, onOpenGuide }: Props) {
  const { messages, busy, sendMessage, retryLast, trip, selectedRouteId } = useTrip();
  const [draft, setDraft] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!draft.trim() || busy) return;
    sendMessage(draft);
    setDraft("");
  };

  const last = messages[messages.length - 1];
  // The route can change on the map after a reply was written, so drop the
  // chip that would re-select what is already selected.
  const selectedType = trip?.routes.find((r) => r.id === selectedRouteId)?.route_type;
  const chips = (messages.length === 0 ? STARTER_CHIPS : last && !last.pending ? last.chips : []).filter(
    (chip) => !selectedType || chip !== `Select ${routeName(selectedType)}`,
  );

  return (
    <aside className={collapsed ? "chat collapsed" : "chat"} aria-label="Trip agent chat">
      {collapsed && (
        <div className="chat-rail">
          <button type="button" className="rail-button" aria-label="Open the chat" title="Open the chat" onClick={onToggleCollapsed}>
            &raquo;
          </button>
          <button type="button" className="rail-button" aria-label="How to use Waypoint" title="How to use Waypoint" onClick={onOpenGuide}>
            ?
          </button>
          <span className="rail-label" aria-hidden="true">
            Chat
          </span>
          {/* the agent is still working: worth opening the chat for */}
          {busy && <span className="rail-busy" role="status" aria-label="The agent is working" />}
        </div>
      )}
      <div className="chat-body" hidden={collapsed}>
      <header className="chat-head">
        <span className="brand">Waypoint</span>
        <span className="chat-head-side">
          {!MOCK_REPLIES && <OwnKeyPanel />}
          <span className={MOCK_REPLIES ? "mode-badge mock" : "mode-badge"}>{MOCK_REPLIES ? "Mock data" : "Live API"}</span>
          <button type="button" className="head-button" aria-label="How to use Waypoint" title="How to use Waypoint" onClick={onOpenGuide}>
            ?
          </button>
          <button type="button" className="head-button" aria-label="Fold the chat away" title="Fold the chat away" onClick={onToggleCollapsed}>
            &laquo;
          </button>
        </span>
      </header>
      <ServerWaking />

      <div className="chat-list" ref={listRef} aria-live="polite">
        {messages.length === 0 && (
          <p className="chat-empty">
            Tell the agent where you are driving from and to. Each step it takes is listed as it runs; the ? button
            explains the rest.
          </p>
        )}
        {messages.map((message) =>
          message.role === "user" ? (
            <div key={message.id} className="msg user">
              {message.text}
            </div>
          ) : (
            <div key={message.id} className="msg assistant">
              <StepChecklist steps={message.steps} />
              {message.pending ? (
                <PendingStatus steps={message.steps} />
              ) : message.failed ? (
                <div className="msg-error" role="alert">
                  <p>{message.text}</p>
                  {message.id === messages[messages.length - 1]?.id && (
                    <button type="button" className="chip" disabled={busy} onClick={retryLast}>
                      Try again
                    </button>
                  )}
                </div>
              ) : (
                <p className="msg-text">{message.text}</p>
              )}
            </div>
          ),
        )}
        {chips.length > 0 && (
          <div className="chips">
            {chips.map((chip) => (
              <button key={chip} type="button" className="chip" disabled={busy} onClick={() => sendMessage(chip)}>
                {chip}
              </button>
            ))}
          </div>
        )}
      </div>

      <form className="chat-form" onSubmit={submit}>
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="San Francisco to Los Angeles"
          aria-label="Message the agent"
        />
        <button type="submit" disabled={busy || !draft.trim()}>
          Send
        </button>
      </form>
      </div>
    </aside>
  );
}
