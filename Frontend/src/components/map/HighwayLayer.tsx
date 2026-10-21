import { useMemo } from "react";
import type { Dispatch, SetStateAction } from "react";
import { geoPath } from "d3-geo";
import type { GeoProjection } from "d3-geo";
import { ROUTE_66, ROUTE_66_TITLE } from "../../data/route66";
import type { Highway } from "../../highways";

export const ROUTE_66_ID = "route-66";

interface Props {
  projection: GeoProjection;
  highways: Highway[];
  /** The selected route's highways, drawn stronger */
  onRouteIds: Set<string>;
  hovered: string | null;
  setHovered: Dispatch<SetStateAction<string | null>>;
  /** Hover targets on: off before a trip, when a click on a state opens the city picker */
  interactive: boolean;
}

/** Hover handlers for one highway: leaving clears the hover only if it is still this highway's. */
export const hoverHandlers = (id: string, setHovered: Dispatch<SetStateAction<string | null>>) => ({
  onMouseEnter: () => setHovered(id),
  onMouseLeave: () => setHovered((h) => (h === id ? null : h)),
});

/** The Interstate and US-route network, faded, and historic Route 66; a hovered highway is drawn strongest. */
export default function HighwayLayer({ projection, highways, onRouteIds, hovered, setHovered, interactive }: Props) {
  const network = useMemo(() => {
    const draw = geoPath(projection);
    return {
      // US routes first, so Interstates draw over them
      highways: [...highways]
        .sort((a, b) => Number(a.kind === "interstate") - Number(b.kind === "interstate"))
        .map((highway) => ({ highway, d: draw(highway.geometry) ?? "" })),
      route66: draw(ROUTE_66) ?? "",
    };
  }, [projection, highways]);

  return (
    <g className="highways" aria-hidden="true">
      {network.highways.map(({ highway, d }) => {
        const classes = ["highway", highway.kind];
        if (onRouteIds.has(highway.id)) classes.push("on-route");
        if (hovered === highway.id) classes.push("active");
        return <path key={highway.id} className={classes.join(" ")} d={d} />;
      })}
      <path className={hovered === ROUTE_66_ID ? "route66 active" : "route66"} d={network.route66} />
      {interactive && (
        <g className="highway-hits">
          {network.highways.map(({ highway, d }) => (
            <path key={highway.id} className="highway-hit" d={d} {...hoverHandlers(highway.id, setHovered)}>
              <title>{highway.name}</title>
            </path>
          ))}
          <path className="highway-hit" d={network.route66} {...hoverHandlers(ROUTE_66_ID, setHovered)}>
            <title>{ROUTE_66_TITLE}</title>
          </path>
        </g>
      )}
    </g>
  );
}
