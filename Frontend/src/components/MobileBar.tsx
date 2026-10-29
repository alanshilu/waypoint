import { useEffect, useRef, useState } from "react";
import { capabilities } from "../api";
import { setPrefs, usePrefs } from "../state/prefs";
import OwnKeyPanel from "./OwnKeyPanel";
import ServerWaking from "./ServerWaking";
import TraceDrawer from "./TraceDrawer";

const MOCK = capabilities.replies === "mock";

/**
 * The phone layout's top bar: the name, the Live API / Mock badge (always visible), the guide, and one menu with
 * what the desktop header and footer spread out: "Use your key", the developer view and its tool trace.
 */
export default function MobileBar({ onOpenGuide, shared }: { onOpenGuide: () => void; shared: boolean }) {
  const { developerView } = usePrefs();
  const [open, setOpen] = useState(false);
  const menu = useRef<HTMLDivElement>(null);

  // Escape or a tap outside closes the menu
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    const onDown = (event: PointerEvent) => {
      if (menu.current && !menu.current.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("pointerdown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("pointerdown", onDown);
    };
  }, [open]);

  return (
    <header className="mobile-bar" ref={menu}>
      <div className="mobile-bar-row">
        <span className="brand">Waypoint</span>
        <span className={MOCK ? "mode-badge mock" : "mode-badge"}>{shared ? "Shared trip" : MOCK ? "Mock data" : "Live API"}</span>
        <button type="button" className="head-button" aria-label="How to use Waypoint" title="How to use Waypoint" onClick={onOpenGuide}>
          ?
        </button>
        {!shared && (
          <button type="button" className="head-button mobile-menu-button" aria-label="Menu" aria-expanded={open} aria-controls="mobile-menu" onClick={() => setOpen((v) => !v)}>
            <span aria-hidden="true">&#9776;</span>
          </button>
        )}
      </div>
      <ServerWaking />
      {open && (
        <div className="mobile-menu" id="mobile-menu">
          {!MOCK && (
            <div className="mobile-menu-item mobile-menu-key">
              <OwnKeyPanel />
            </div>
          )}
          <label className="mobile-menu-item">
            <input type="checkbox" checked={developerView} onChange={(event) => setPrefs({ developerView: event.target.checked })} />
            Developer view: tool names, timings and the trace
          </label>
          {developerView && <TraceDrawer />}
        </div>
      )}
    </header>
  );
}
