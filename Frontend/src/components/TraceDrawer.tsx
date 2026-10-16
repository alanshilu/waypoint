import { useState } from "react";
import { useTrip } from "../state/TripProvider";
import type { TurnSource } from "../types";

const SOURCE_LABEL: Record<TurnSource, string> = {
  mock: "mock fixtures, simulated latency",
  agent: "LLM agent via POST /agent/message",
  scripted: "scripted in the browser, no LLM (backend has no /agent/message)",
};

export default function TraceDrawer() {
  const { lastTurn } = useTrip();
  const [open, setOpen] = useState(false);

  const steps = lastTurn?.steps ?? [];
  const totalMs = steps.reduce((sum, s) => sum + (s.ms ?? 0), 0);
  const hits = steps.filter((s) => s.cache === "hit").length;
  const cacheable = steps.filter((s) => s.cache !== null).length;
  const failed = steps.filter((s) => s.status === "error").length;

  const summary = !lastTurn
    ? "No agent turn yet"
    : `${steps.length} tool call${steps.length === 1 ? "" : "s"} · ${totalMs.toLocaleString("en-US")} ms` +
      (cacheable ? ` · ${hits}/${cacheable} cache hits` : " · cache not reported") +
      (failed ? ` · ${failed} failed` : "") +
      (lastTurn.running ? " · running" : "");

  return (
    <footer className={open ? "trace open" : "trace"}>
      <button type="button" className="trace-bar" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span className="trace-caret" aria-hidden="true">
          {open ? "▾" : "▸"}
        </span>
        <span className="trace-title">Trace</span>
        <span className="trace-summary">{summary}</span>
      </button>

      {open && (
        <div className="trace-body">
          {!lastTurn || steps.length === 0 ? (
            <p className="trace-empty">
              {lastTurn ? "The last turn made no tool calls." : "Tool calls from the last agent turn appear here."}
            </p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th scope="col">#</th>
                  <th scope="col">Tool</th>
                  <th scope="col">Status</th>
                  <th scope="col" className="numeric">
                    Latency
                  </th>
                  <th scope="col">Cache</th>
                </tr>
              </thead>
              <tbody>
                {steps.map((step, i) => (
                  <tr key={i}>
                    <td>{i + 1}</td>
                    <td>{step.tool}</td>
                    <td className={step.status === "error" ? "warn" : undefined}>{step.status}</td>
                    <td className="numeric">{step.ms === null ? "…" : `${step.ms} ms`}</td>
                    <td className={step.cache === "hit" ? "good" : undefined}>{step.cache ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {lastTurn && (
            <p className="trace-meta">
              Source: {SOURCE_LABEL[lastTurn.source]}. Context sent with the message:{" "}
              {lastTurn.contextRouteId === null ? "no route selected" : `selected route ${lastTurn.contextRouteId}`}.
            </p>
          )}
        </div>
      )}
    </footer>
  );
}
