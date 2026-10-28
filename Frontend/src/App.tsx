import { useState } from "react";
import ChatPanel from "./components/ChatPanel";
import ElevationProfile from "./components/ElevationProfile";
import Guide from "./components/Guide";
import RouteComparison from "./components/RouteComparison";
import RouteMap from "./components/RouteMap";
import SharedPanel from "./components/SharedPanel";
import TraceDrawer from "./components/TraceDrawer";
import { setPrefs, usePrefs } from "./state/prefs";
import { useTrip } from "./state/TripProvider";

export default function App() {
  const { chatCollapsed, developerView, guideSeen } = usePrefs();
  const { shared } = useTrip();
  // the guide opens by itself on a first visit, then only from the ? button (never over a shared trip)
  const [guideOpen, setGuideOpen] = useState(!guideSeen && !shared);

  const closeGuide = () => {
    setGuideOpen(false);
    setPrefs({ guideSeen: true });
  };

  return (
    <div className={chatCollapsed && !shared ? "app chat-collapsed" : "app"}>
      {shared ? (
        <SharedPanel />
      ) : (
        <ChatPanel
          collapsed={chatCollapsed}
          onToggleCollapsed={() => setPrefs({ chatCollapsed: !chatCollapsed })}
          onOpenGuide={() => setGuideOpen(true)}
        />
      )}
      <main className="center">
        <div className="map-area">
          <RouteMap />
          <RouteComparison />
        </div>
        <ElevationProfile />
      </main>
      {/* the agent's tool trace is for developers; the guide turns it on */}
      {developerView && !shared && <TraceDrawer />}
      <Guide open={guideOpen} onClose={closeGuide} />
    </div>
  );
}
