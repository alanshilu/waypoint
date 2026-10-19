import { useState } from "react";
import type { FormEvent } from "react";
import { getOwnKey, isPlausibleKey, maskKey, setOwnKey } from "../ownKey";

/**
 * "Use your own key": the user's Anthropic key pays for their agent turns and skips the demo's
 * daily limit. The toggle sits in the chat header; the form opens under it.
 */
export default function OwnKeyPanel() {
  const [key, setKey] = useState<string | null>(getOwnKey);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  const save = (event: FormEvent) => {
    event.preventDefault();
    if (!isPlausibleKey(draft)) {
      setProblem("That doesn't look like an Anthropic API key (it starts with sk-ant-).");
      return;
    }
    setOwnKey(draft);
    setKey(draft.trim());
    setDraft("");
    setProblem(null);
    setOpen(false);
  };

  const remove = () => {
    setOwnKey(null);
    setKey(null);
  };

  return (
    <>
      <button
        type="button"
        className={key ? "own-key-toggle active" : "own-key-toggle"}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {key ? "Your key" : "Use your key"}
      </button>
      {open && (
        <div className="own-key-panel">
          {key ? (
            <>
              <p>
                Your messages run on <span className="own-key-mask">{maskKey(key)}</span> and are billed to your
                Anthropic account, with no daily demo limit.
              </p>
              <button type="button" className="chip" onClick={remove}>
                Remove key
              </button>
            </>
          ) : (
            <form onSubmit={save}>
              <p>
                Over the demo's daily limit, or planning a lot? Use your own{" "}
                <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noreferrer">
                  Anthropic API key
                </a>
                . Your messages are billed to you and skip the daily limit.
              </p>
              <input
                type="password"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="sk-ant-…"
                autoComplete="off"
                spellCheck={false}
                aria-label="Anthropic API key"
              />
              {problem && <p className="own-key-problem">{problem}</p>}
              <button type="submit" disabled={!draft.trim()}>
                Use this key
              </button>
            </form>
          )}
          <p className="own-key-note">
            The key stays in this browser tab and is gone when you close it. It is sent only with your messages,
            used for that one reply, and never stored or logged by Waypoint.
          </p>
        </div>
      )}
    </>
  );
}
