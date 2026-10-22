import { useState } from "react";
import ChatPanel from "./components/ChatPanel";
import ElevationProfile from "./components/ElevationProfile";
import Guide from "./components/Guide";
import RouteComparison from "./components/RouteComparison";
import RouteMap from "./components/RouteMap";
import TraceDrawer from "./components/TraceDrawer";
import { setPrefs, usePrefs } from "./state/prefs";

export default function App() {
  const { chatCollapsed, developerView, guideSeen } = usePrefs();
  // the guide opens by itself on a first visit, then only from the ? button
  const [guideOpen, setGuideOpen] = useState(!guideSeen);

  const closeGuide = () => {
    setGuideOpen(false);
    setPrefs({ guideSeen: true });
  };

  return (
    <div className={chatCollapsed ? "app chat-collapsed" : "app"}>
      <ChatPanel
        collapsed={chatCollapsed}
        onToggleCollapsed={() => setPrefs({ chatCollapsed: !chatCollapsed })}
        onOpenGuide={() => setGuideOpen(true)}
      />
      <main className="center">
        <div className="map-area">
          <RouteMap />
          <RouteComparison />
        </div>
        <ElevationProfile />
      </main>
      {/* the agent's tool trace is for developers; the guide turns it on */}
      {developerView && <TraceDrawer />}
      <Guide open={guideOpen} onClose={closeGuide} />
    </div>
  );
}
