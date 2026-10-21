import type { GeoPath, GeoProjection } from "d3-geo";
import { ARRIVE } from "../../directions";
import type { Direction } from "../../directions";
import { ManeuverIcon } from "../DirectionsPanel";

interface Props {
  directions: Direction[];
  /** The step shown on the map (picked, or Next / Previous) */
  active: number | null;
  /** The step under the pointer in the list */
  hovered: number | null;
  path: GeoPath;
  projection: GeoProjection;
}

/** The directions steps in view: each one's stretch over the route, and a disc with its maneuver. */
export default function StepMarkers({ directions, active, hovered, path, projection }: Props) {
  const shown = [hovered, active].filter((i, n, all): i is number => i !== null && all.indexOf(i) === n);
  return (
    <>
      {shown.map((i) => {
        const d = directions[i];
        const at = d.step.type === ARRIVE ? d.step.end : d.step.start;
        const xy = projection([at[0], at[1]]);
        const current = i === active;
        return (
          <g key={`step-${i}`} className={current ? "map-step active" : "map-step"} aria-hidden="true">
            <path className="map-step-line" d={path({ type: "LineString", coordinates: d.stretch }) ?? ""} />
            {xy && (
              <g transform={`translate(${xy[0]} ${xy[1]})`}>
                <circle r={current ? 13 : 10} />
                <g transform={`translate(${current ? -9 : -7} ${current ? -9 : -7})`}>
                  <ManeuverIcon type={d.step.type} size={current ? 18 : 14} />
                </g>
              </g>
            )}
          </g>
        );
      })}
    </>
  );
}
