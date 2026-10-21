import type { Dispatch, SetStateAction } from "react";
import { hoverHandlers, ROUTE_66_ID } from "./HighwayLayer";
import type { Shield } from "./shields";

const shieldWidth = (text: string) => 9 + text.length * 6.6;

interface Props {
  shields: Shield[];
  route66At: [number, number] | null;
  hovered: string | null;
  setHovered: Dispatch<SetStateAction<string | null>>;
  /** Off before a trip, so shields don't block clicks on the states under them */
  interactive: boolean;
}

/** Route shields ("I-5", "101") and the Route 66 label, drawn over the routes. */
export default function ShieldLayer({ shields, route66At, hovered, setHovered, interactive }: Props) {
  return (
    <g className={interactive ? "shields" : "shields passive"} aria-hidden="true">
      {route66At && (
        <text className={hovered === ROUTE_66_ID ? "route66-label active" : "route66-label"} x={route66At[0]} y={route66At[1] - 9} textAnchor="middle">
          Route 66
        </text>
      )}
      {shields.map(({ highway, x, y, onRoute }) => {
        const text = highway.kind === "interstate" ? `I-${highway.number}` : highway.number;
        const w = shieldWidth(text);
        const classes = ["shield", highway.kind];
        if (onRoute) classes.push("on-route");
        if (hovered === highway.id) classes.push("active");
        return (
          <g key={highway.id} className={classes.join(" ")} transform={`translate(${x} ${y})`} {...hoverHandlers(highway.id, setHovered)}>
            <title>{highway.name}</title>
            <rect x={-w / 2} y={-7.5} width={w} height={15} rx={highway.kind === "interstate" ? 3.5 : 1} />
            <text textAnchor="middle" dominantBaseline="central">
              {text}
            </text>
          </g>
        );
      })}
    </g>
  );
}
