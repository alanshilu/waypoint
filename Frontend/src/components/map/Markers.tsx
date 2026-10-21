import type { GeoProjection } from "d3-geo";
import type { Place, PlaceOption, PoiResult } from "../../types";

export const shortName = (place: Place) => place.name.split(",")[0];

/** The trip's start and end, named. */
export function EndpointMarkers({ places, projection }: { places: Place[]; projection: GeoProjection }) {
  return (
    <>
      {places.map((place, i) => {
        const xy = projection([place.lon, place.lat]);
        if (!xy) return null;
        return (
          <g key={i} className="map-endpoint">
            <circle cx={xy[0]} cy={xy[1]} r={5} />
            <text x={xy[0] + 9} y={xy[1] - 9}>
              {shortName(place)}
            </text>
          </g>
        );
      })}
    </>
  );
}

interface PlaceProps {
  /** Picks last, so they draw on top */
  places: PlaceOption[];
  projection: GeoProjection;
  hovered: string | null;
  onHover: (id: string | null) => void;
}

/** Campsites (tents) and places to eat (dots); the agent's picks larger and named. */
export function PlaceMarkers({ places, projection, hovered, onHover }: PlaceProps) {
  return (
    <>
      {places.map((place) => {
        const xy = projection([place.lon, place.lat]);
        if (!xy) return null;
        const [x, y] = xy;
        const size = place.recommended ? 8 : 5;
        const classes = ["place-marker", place.kind];
        if (place.recommended) classes.push("picked");
        if (hovered === place.id) classes.push("active");
        return (
          <g key={place.id} className={classes.join(" ")} onMouseEnter={() => onHover(place.id)} onMouseLeave={() => onHover(null)}>
            <title>{[place.name, ...(place.reason ? [place.reason] : place.facts.slice(0, 3))].join(" · ")}</title>
            {place.kind === "camping" ? (
              // a tent
              <path d={`M${x} ${y - size}L${x + size} ${y + size * 0.8}L${x - size} ${y + size * 0.8}Z`} />
            ) : (
              <circle cx={x} cy={y} r={size * 0.8} />
            )}
            {/* a night's campsite and dinner picks sit close together: name tents on the right, food on the left */}
            {(place.recommended || hovered === place.id) && (
              <text
                x={place.kind === "camping" ? x + size + 4 : x - size - 4}
                y={y}
                textAnchor={place.kind === "camping" ? "start" : "end"}
                dominantBaseline="middle"
              >
                {place.name}
              </text>
            )}
          </g>
        );
      })}
    </>
  );
}

interface StopProps {
  stops: PoiResult;
  projection: GeoProjection;
  /** Zoomed to the stops: numbered markers; otherwise one marker with a count */
  expanded: boolean;
  hovered: number | null;
  onHover: (id: number | null) => void;
  onZoomToStops: () => void;
}

/** Stops from a search or the agent's plan, numbered to match the list. */
export function StopMarkers({ stops, projection, expanded, hovered, onHover, onZoomToStops }: StopProps) {
  if (!expanded) {
    // Zoomed out, the stops sit on top of each other: draw one marker with a count.
    const xy = projection([stops.center.lon, stops.center.lat]);
    if (!xy) return null;
    return (
      <g className="poi-cluster" onClick={onZoomToStops}>
        <title>Click to zoom to these stops</title>
        <rect x={xy[0] - 6} y={xy[1] - 6} width={12} height={12} transform={`rotate(45 ${xy[0]} ${xy[1]})`} />
        <text x={xy[0] + 13} y={xy[1] + 16}>
          {stops.items.length} stops
        </text>
      </g>
    );
  }
  return (
    <>
      {stops.items.map((poi, i) => {
        const xy = projection([poi.lon, poi.lat]);
        if (!xy) return null;
        return (
          <g
            key={poi.id}
            className={hovered === poi.id ? "poi-marker active" : "poi-marker"}
            onMouseEnter={() => onHover(poi.id)}
            onMouseLeave={() => onHover(null)}
          >
            <title>{`${poi.name} (${poi.category.replace(/_/g, " ")})`}</title>
            <circle cx={xy[0]} cy={xy[1]} r={10} />
            <text x={xy[0]} y={xy[1]} textAnchor="middle" dominantBaseline="central">
              {i + 1}
            </text>
          </g>
        );
      })}
    </>
  );
}
