import { useEffect, useRef, useState } from "react";
import ChatPanel from "./components/ChatPanel";
import ElevationProfile from "./components/ElevationProfile";
import Guide from "./components/Guide";
import { useMobileLayout } from "./components/map/layout";
import MobileBar from "./components/MobileBar";
import RouteComparison from "./components/RouteComparison";
import RouteMap from "./components/RouteMap";
import SharedPanel from "./components/SharedPanel";
import TraceDrawer from "./components/TraceDrawer";
import { setPrefs, usePrefs } from "./state/prefs";
import { useTrip } from "./state/TripProvider";

type Tab = "chat" | "map";

/** The chat's message box has focus and text in it: the user is typing, so the view mustn't change under them. */
function typing(): boolean {
  const el = document.activeElement;
  return el instanceof HTMLInputElement && el.getAttribute("aria-label") === "Message the agent" && el.value.trim() !== "";
}

/**
 * Phones: the app's height follows the visual viewport, so the message box stays above the on-screen keyboard
 * (100dvh doesn't shrink for the keyboard on iOS Safari).
 */
function useVisualViewportHeight(enabled: boolean) {
  useEffect(() => {
    const viewport = window.visualViewport;
    const root = document.documentElement;
    if (!enabled || !viewport) {
      root.style.removeProperty("--app-height");
      return;
    }
    const update = () => root.style.setProperty("--app-height", `${Math.round(viewport.height)}px`);
    update();
    viewport.addEventListener("resize", update);
    return () => {
      viewport.removeEventListener("resize", update);
      root.style.removeProperty("--app-height");
    };
  }, [enabled]);
}

export default function App() {
  const { chatCollapsed, developerView, guideSeen } = usePrefs();
  const { shared, trip, places, pois } = useTrip();
  const mobile = useMobileLayout();
  // the guide opens by itself on a first visit, then only from the ? button (never over a shared trip)
  const [guideOpen, setGuideOpen] = useState(!guideSeen && !shared);
  useVisualViewportHeight(mobile);

  // Phones show one view at a time. A new or changed trip (the agent's answer, a shared or restored trip)
  // switches to the map, unless the user is typing: then it waits until they leave the message box.
  const [tab, setTab] = useState<Tab>("chat");
  const [autoSwitched, setAutoSwitched] = useState(false);
  const tabRef = useRef(tab);
  tabRef.current = tab;
  const pendingSwitch = useRef(false);
  /** The app moving to the map by itself: from the chat it offers a way back; the map shows from its top. */
  const switchToMap = () => {
    if (tabRef.current === "chat") setAutoSwitched(true);
    setTab("map");
    // once the view is showing (a hidden element keeps no scroll position)
    requestAnimationFrame(() => requestAnimationFrame(() => document.getElementById("map-view")?.scrollTo({ top: 0 })));
  };
  const seen = useRef({ trip, places, pois });
  useEffect(() => {
    const before = seen.current;
    seen.current = { trip, places, pois };
    const tripChanged = trip !== null && (trip.id !== before.trip?.id || trip.routes !== before.trip?.routes);
    const resultsChanged = (places !== before.places && places !== null) || (pois !== before.pois && pois !== null);
    if (!mobile || !(tripChanged || resultsChanged)) return;
    if (typing()) {
      pendingSwitch.current = true;
      return;
    }
    switchToMap();
  }, [mobile, trip, places, pois]);
  useEffect(() => {
    // the user stopped typing: left the box, emptied it or sent the message
    const settle = () => {
      if (!pendingSwitch.current) return;
      // once focus has moved on and the box has updated
      setTimeout(() => {
        if (!pendingSwitch.current || typing()) return;
        pendingSwitch.current = false;
        switchToMap();
      }, 0);
    };
    const events = ["focusout", "input", "submit"] as const;
    events.forEach((name) => document.addEventListener(name, settle));
    return () => events.forEach((name) => document.removeEventListener(name, settle));
  }, []);

  const show = (next: Tab) => {
    setTab(next);
    setAutoSwitched(false);
    pendingSwitch.current = false;
  };

  const closeGuide = () => {
    setGuideOpen(false);
    setPrefs({ guideSeen: true });
  };

  const classes = ["app"];
  if (mobile) classes.push("mobile", `tab-${tab}`);
  else if (chatCollapsed && !shared) classes.push("chat-collapsed");

  return (
    <div className={classes.join(" ")}>
      {mobile && <MobileBar onOpenGuide={() => setGuideOpen(true)} shared={shared} />}
      {shared ? (
        <SharedPanel />
      ) : (
        <ChatPanel
          collapsed={chatCollapsed && !mobile}
          onToggleCollapsed={() => setPrefs({ chatCollapsed: !chatCollapsed })}
          onOpenGuide={() => setGuideOpen(true)}
        />
      )}
      <main className="center" id="map-view">
        {mobile && autoSwitched && tab === "map" && (
          <button type="button" className="back-to-chat" onClick={() => show("chat")}>
            <span aria-hidden="true">&lsaquo;</span> Back to {shared ? "the trip" : "chat"}
          </button>
        )}
        <div className="map-area">
          <RouteMap />
          <RouteComparison />
        </div>
        <ElevationProfile />
      </main>
      {/* the agent's tool trace is for developers; the guide turns it on (on a phone it's in the menu) */}
      {developerView && !shared && !mobile && <TraceDrawer />}
      {mobile && (
        <nav className="tab-bar" aria-label="Views">
          <div role="tablist" aria-label="Views">
            {(["chat", "map"] as const).map((name) => (
              <button
                key={name}
                type="button"
                role="tab"
                aria-selected={tab === name}
                aria-controls={name === "map" ? "map-view" : undefined}
                className="tab"
                onClick={() => show(name)}
              >
                {name === "chat" ? (shared ? "Trip" : "Chat") : "Map"}
              </button>
            ))}
          </div>
        </nav>
      )}
      <Guide open={guideOpen} onClose={closeGuide} />
    </div>
  );
}
