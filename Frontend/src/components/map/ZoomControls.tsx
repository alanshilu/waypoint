import type { MapZoom } from "../../useMapZoom";
import { ZOOM_BUTTON_FACTOR } from "../../useMapZoom";

/** Bottom right: zoom in, zoom out, and back to the fit. */
export default function ZoomControls({ zoom }: { zoom: Pick<MapZoom, "zoomBy" | "reset" | "zoomed"> }) {
  return (
    <div className="zoom-controls" role="group" aria-label="Zoom">
      <button type="button" aria-label="Zoom in" onClick={() => zoom.zoomBy(ZOOM_BUTTON_FACTOR)}>
        +
      </button>
      <button type="button" aria-label="Zoom out" onClick={() => zoom.zoomBy(1 / ZOOM_BUTTON_FACTOR)}>
        &minus;
      </button>
      <button type="button" aria-label="Reset zoom" disabled={!zoom.zoomed} onClick={zoom.reset}>
        &#x2922;
      </button>
    </div>
  );
}
