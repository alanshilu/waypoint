import ChatPanel from "./components/ChatPanel";
import ElevationProfile from "./components/ElevationProfile";
import RouteComparison from "./components/RouteComparison";
import RouteMap from "./components/RouteMap";
import TraceDrawer from "./components/TraceDrawer";

export default function App() {
  return (
    <div className="app">
      <ChatPanel />
      <main className="center">
        <div className="map-area">
          <RouteMap />
          <RouteComparison />
        </div>
        <ElevationProfile />
      </main>
      <TraceDrawer />
    </div>
  );
}
