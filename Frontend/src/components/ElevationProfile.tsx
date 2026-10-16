import { useMemo } from "react";
import type { MouseEvent } from "react";
import { routeLabel } from "../format";
import { useTrip } from "../state/TripProvider";
import { useSize } from "../useSize";
import type { ElevationPoint, Route } from "../types";

const MARGIN = { top: 14, right: 16, bottom: 26, left: 68 };

/** Rounds a span up to a tidy tick step (1, 2 or 5 times a power of ten). */
function niceStep(span: number, targetTicks: number): number {
  const raw = span / targetTicks;
  const power = 10 ** Math.floor(Math.log10(raw));
  const unit = raw / power;
  return (unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 5 ? 5 : 10) * power;
}

function ticks(max: number, targetTicks: number): number[] {
  const step = niceStep(max, targetTicks);
  const out: number[] = [];
  for (let v = 0; v <= max + 1e-9; v += step) out.push(v);
  return out;
}

/** Elevation at a mile marker, interpolated; null beyond the end of the route. */
function elevationAt(profile: ElevationPoint[], mile: number): number | null {
  if (profile.length === 0 || mile < profile[0].mile || mile > profile[profile.length - 1].mile) return null;
  let lo = 0;
  let hi = profile.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (profile[mid].mile <= mile) lo = mid;
    else hi = mid;
  }
  const span = profile[hi].mile - profile[lo].mile;
  const t = span > 0 ? (mile - profile[lo].mile) / span : 0;
  return profile[lo].m + (profile[hi].m - profile[lo].m) * t;
}

type Profiled = Route & { elevation_profile: ElevationPoint[] };

export default function ElevationProfile() {
  const { trip, selectedRouteId, hoverMile, setHoverMile } = useTrip();
  const [ref, { width, height }] = useSize<HTMLDivElement>();

  const profiled = useMemo(
    () =>
      (trip?.routes ?? []).filter(
        (r): r is Profiled => Array.isArray(r.elevation_profile) && r.elevation_profile.length > 1,
      ),
    [trip?.routes],
  );

  const scales = useMemo(() => {
    if (profiled.length === 0 || width === 0 || height === 0) return null;
    const maxMile = Math.max(...profiled.map((r) => r.elevation_profile[r.elevation_profile.length - 1].mile));
    const maxM = Math.max(...profiled.flatMap((r) => r.elevation_profile.map((p) => p.m)), 1);
    const yTicks = ticks(maxM, 3);
    const yMax = Math.max(maxM, yTicks[yTicks.length - 1]);
    const plotWidth = Math.max(1, width - MARGIN.left - MARGIN.right);
    const plotHeight = Math.max(1, height - MARGIN.top - MARGIN.bottom);
    const x = (mile: number) => MARGIN.left + (mile / maxMile) * plotWidth;
    const y = (m: number) => MARGIN.top + plotHeight - (m / yMax) * plotHeight;
    return {
      maxMile,
      plotWidth,
      plotHeight,
      x,
      y,
      xTicks: ticks(maxMile, 6),
      yTicks,
      paths: profiled.map((r) => ({
        id: r.id,
        d: r.elevation_profile
          .map((p, i) => `${i ? "L" : "M"}${x(p.mile).toFixed(1)},${y(p.m).toFixed(1)}`)
          .join(""),
      })),
    };
  }, [profiled, width, height]);

  // Without elevation data (routes saved before the backend kept it) the panel
  // is not rendered at all and the map takes the full height.
  if (profiled.length === 0) return null;

  const onMove = (event: MouseEvent<SVGRectElement>) => {
    if (!scales) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const t = Math.min(1, Math.max(0, (event.clientX - bounds.left) / bounds.width));
    setHoverMile(Math.round(t * scales.maxMile * 10) / 10);
  };

  // Selected route drawn last so it sits on top.
  const ordered = [...profiled].sort(
    (a, b) => Number(a.id === selectedRouteId) - Number(b.id === selectedRouteId),
  );

  return (
    <section className="elevation" aria-label="Elevation profile">
      <header className="elevation-head">
        <h2>Elevation</h2>
        <ul className="legend">
          {profiled.map((r) => {
            const m = hoverMile === null ? null : elevationAt(r.elevation_profile, hoverMile);
            return (
              <li key={r.id}>
                <span className={r.id === selectedRouteId ? "legend-key selected" : "legend-key"} aria-hidden="true" />
                {routeLabel(r.route_type)}
                {hoverMile !== null && (
                  <span className="data">{m === null ? "ended" : `${Math.round(m).toLocaleString("en-US")} m`}</span>
                )}
              </li>
            );
          })}
          <li className="legend-mile data">{hoverMile === null ? "hover for detail" : `mile ${hoverMile.toFixed(0)}`}</li>
        </ul>
      </header>

      <div className="elevation-plot" ref={ref}>
        {scales && (
          <svg width={width} height={height} role="img" aria-label="Elevation in metres by mile for each route">
            {scales.yTicks.map((v) => (
              <g key={v}>
                <line className="chart-grid" x1={MARGIN.left} x2={MARGIN.left + scales.plotWidth} y1={scales.y(v)} y2={scales.y(v)} />
                <text className="chart-tick" x={MARGIN.left - 8} y={scales.y(v)} textAnchor="end" dominantBaseline="middle">
                  {v.toLocaleString("en-US")} m
                </text>
              </g>
            ))}
            {scales.xTicks.map((v) => (
              <text key={v} className="chart-tick" x={scales.x(v)} y={height - 8} textAnchor="middle">
                {v} mi
              </text>
            ))}

            {ordered.map((r) => {
              const path = scales.paths.find((p) => p.id === r.id);
              return (
                <path
                  key={r.id}
                  className={r.id === selectedRouteId ? "chart-line selected" : "chart-line"}
                  d={path?.d}
                />
              );
            })}

            {hoverMile !== null && (
              <g pointerEvents="none">
                <line
                  className="chart-crosshair"
                  x1={scales.x(hoverMile)}
                  x2={scales.x(hoverMile)}
                  y1={MARGIN.top}
                  y2={MARGIN.top + scales.plotHeight}
                />
                {ordered.map((r) => {
                  const m = elevationAt(r.elevation_profile, hoverMile);
                  if (m === null) return null;
                  return (
                    <circle
                      key={r.id}
                      className={r.id === selectedRouteId ? "hover-dot selected" : "hover-dot"}
                      cx={scales.x(hoverMile)}
                      cy={scales.y(m)}
                      r={4.5}
                    />
                  );
                })}
              </g>
            )}

            <rect
              className="chart-hit"
              x={MARGIN.left}
              y={MARGIN.top}
              width={scales.plotWidth}
              height={scales.plotHeight}
              onMouseMove={onMove}
              onMouseLeave={() => setHoverMile(null)}
            />
          </svg>
        )}
      </div>
    </section>
  );
}
