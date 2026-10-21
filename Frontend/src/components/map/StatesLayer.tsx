import type { StateShape } from "./fit";
import type { CityPicker } from "./useCityPicker";

interface StatesProps {
  graticule: string;
  states: StateShape[];
  /** No trip yet: states open the city picker */
  picking: boolean;
  picker: Pick<CityPicker, "hoveredState" | "pinnedState" | "setHoveredState" | "toggleState" | "onStateKeyDown">;
}

/** The graticule and the lower 48; before a trip exists, each state opens the city picker. */
export function StatesLayer({ graticule, states, picking, picker }: StatesProps) {
  const { hoveredState, pinnedState, setHoveredState, toggleState, onStateKeyDown } = picker;
  return (
    <>
      <path className="map-graticule" d={graticule} />
      <g role={picking ? "group" : undefined} aria-label={picking ? "States: open one to pick a city" : undefined}>
        {states.map((s) => {
          const classes = ["map-state"];
          if (picking) classes.push("pickable");
          if (picking && (s.id === pinnedState || (!pinnedState && s.id === hoveredState))) classes.push("active");
          return (
            <path
              key={s.id}
              className={classes.join(" ")}
              d={s.d}
              data-fips={s.id}
              onMouseEnter={() => setHoveredState(s.id)}
              onMouseLeave={() => setHoveredState((current) => (current === s.id ? null : current))}
              {...(picking && {
                tabIndex: 0,
                role: "button",
                "aria-label": `${s.name}: pick a city`,
                "aria-expanded": pinnedState === s.id,
                onClick: (event) => {
                  event.stopPropagation();
                  toggleState(s.id);
                },
                onKeyDown: onStateKeyDown(s.id),
              })}
            />
          );
        })}
      </g>
    </>
  );
}

interface LabelsProps {
  states: StateShape[];
  picking: boolean;
  hoveredState: string | null;
  pinnedState: string | null;
}

/** State codes (full names when hovered or opened), below the routes and markers and never in the pointer's way. */
export function StateLabels({ states, picking, hoveredState, pinnedState }: LabelsProps) {
  return (
    <g className="state-labels" aria-hidden="true">
      {states.map((s) => {
        const full = s.id === hoveredState || (picking && s.id === pinnedState);
        const classes = ["state-label"];
        if (s.small || s.callout) classes.push("small");
        if (s.callout) classes.push("callout");
        if (full) classes.push("full");
        return (
          <g key={s.id}>
            {s.callout && <line className="state-leader" x1={s.x} y1={s.y} x2={s.label.x - 8} y2={s.label.y} />}
            <text className={classes.join(" ")} x={s.label.x} y={s.label.y}>
              {full ? s.name : s.code}
            </text>
          </g>
        );
      })}
    </g>
  );
}
