import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { USE_MOCK } from "../api";
import { useTrip } from "../state/TripProvider";
import type { StepView } from "../types";
import OwnKeyPanel from "./OwnKeyPanel";

const STARTER_CHIPS = ["San Francisco to Los Angeles"];

const STATUS_LABEL: Record<StepView["status"], string> = {
  running: "running",
  done: "done",
  error: "failed",
};

/** Tool calls for one assistant turn, shown above its reply. */
function StepChecklist({ steps }: { steps: StepView[] }) {
  if (steps.length === 0) return null;
  return (
    <ol className="steps" aria-label="Tool calls">
      {steps.map((step, i) => (
        <li key={i} className={`step ${step.status}`}>
          <span className="step-mark" aria-hidden="true">
            {step.status === "done" ? "✓" : step.status === "error" ? "×" : ""}
          </span>
          <span className="step-tool">{step.tool}</span>
          <span className="sr-only">{STATUS_LABEL[step.status]}</span>
          <span className="step-ms">{step.ms === null ? "…" : `${step.ms} ms`}</span>
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
  select_route: "Selecting the route",
};

function pendingLabel(steps: StepView[]): string {
  const running = [...steps].reverse().find((s) => s.status === "running");
  // between tool calls the model is deciding what to do next, or writing the answer
  return running ? `${ACTIVITY[running.tool] ?? `Running ${running.tool}`}…` : "Thinking…";
}

export default function ChatPanel() {
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
    (chip) => chip !== `Select ${selectedType}`,
  );

  return (
    <aside className="chat" aria-label="Trip agent chat">
      <header className="chat-head">
        <span className="brand">Waypoint</span>
        <span className="chat-head-side">
          {!USE_MOCK && <OwnKeyPanel />}
          <span className={USE_MOCK ? "mode-badge mock" : "mode-badge"}>{USE_MOCK ? "Mock data" : "Live API"}</span>
        </span>
      </header>

      <div className="chat-list" ref={listRef} aria-live="polite">
        {messages.length === 0 && (
          <p className="chat-empty">
            Tell the agent where you are driving from and to. Each tool call it makes is listed as it runs.
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
                <p className="msg-pending" role="status">
                  {pendingLabel(message.steps)}
                </p>
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
    </aside>
  );
}
