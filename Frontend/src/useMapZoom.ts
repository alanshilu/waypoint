import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { RefObject } from "react";
import { geoAlbers } from "d3-geo";
import type { GeoProjection } from "d3-geo";

/**
 * Zoom and pan on top of a fitted map projection: wheel and pinch zoom about the pointer, drag to pan,
 * buttons, and zoomTo for a set of points. A zoom belongs to the fitted view it was made on, so changing
 * that view (Full USA, Fit route, a resize) starts again from the fit.
 */

interface ZoomState {
  /** The fitted projection this zoom applies to */
  base: GeoProjection;
  k: number;
  x: number;
  y: number;
}

// Relative to the fit: a little room to zoom out, and in to street level
const MIN_K = 0.5;
// Absolute Albers scale (pixels per radian of the earth): 250,000 is about 25 m per pixel
const MAX_SCALE = 250_000;
const BUTTON_FACTOR = 1.6;
// A press that moves less than this is a click, not a pan
const DRAG_THRESHOLD_PX = 4;

export interface MapZoom {
  /** The fitted projection with the zoom applied; null until there's a fit */
  projection: GeoProjection | null;
  /** How far in from the fit (1 = the fit) */
  k: number;
  /** Zoomed or panned away from the fit */
  zoomed: boolean;
  zoomBy: (factor: number) => void;
  /** Fit these [lon, lat] points into the given screen box, no closer than maxScale */
  zoomTo: (points: [number, number][], box: { x0: number; y0: number; x1: number; y1: number }, maxScale?: number) => void;
  reset: () => void;
  dragging: boolean;
}

export function useMapZoom(svg: RefObject<SVGSVGElement | null>, fitted: GeoProjection | null, size: { width: number; height: number }): MapZoom {
  const [state, setState] = useState<ZoomState | null>(null);
  const [dragging, setDragging] = useState(false);
  const fittedRef = useRef(fitted);
  fittedRef.current = fitted;
  const suppressClick = useRef(false);

  // the zoom in force: none if it was made on another fit
  const current = state && state.base === fitted ? state : null;
  const k = current?.k ?? 1;

  const projection = useMemo(() => {
    if (!fitted || !current) return fitted;
    const [tx, ty] = fitted.translate();
    return geoAlbers()
      .scale(fitted.scale() * current.k)
      .translate([tx * current.k + current.x, ty * current.k + current.y]);
  }, [fitted, current]);

  const clampK = useCallback((value: number) => {
    const base = fittedRef.current;
    const maxK = base ? MAX_SCALE / base.scale() : 1;
    return Math.min(Math.max(value, MIN_K), Math.max(maxK, 1));
  }, []);

  /** Zoom by factor keeping screen point (cx, cy) still, then pan by (dx, dy). */
  const apply = useCallback(
    (factor: number, cx: number, cy: number, dx = 0, dy = 0) => {
      const base = fittedRef.current;
      if (!base) return;
      setState((s) => {
        const cur = s && s.base === base ? s : { base, k: 1, x: 0, y: 0 };
        const nextK = clampK(cur.k * factor);
        const f = nextK / cur.k;
        return { base, k: nextK, x: cx - (cx - cur.x) * f + dx, y: cy - (cy - cur.y) * f + dy };
      });
    },
    [clampK],
  );

  const zoomBy = useCallback((factor: number) => apply(factor, size.width / 2, size.height / 2), [apply, size.width, size.height]);

  const reset = useCallback(() => setState(null), []);

  const zoomTo = useCallback<MapZoom["zoomTo"]>(
    (points, box, maxScale = MAX_SCALE) => {
      const base = fittedRef.current;
      if (!base || points.length === 0) return;
      const xy = points.map((p) => base(p)).filter((p): p is [number, number] => p !== null);
      if (xy.length === 0) return;
      const xs = xy.map((p) => p[0]);
      const ys = xy.map((p) => p[1]);
      const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
      const fit = Math.min((box.x1 - box.x0) / Math.max(x1 - x0, 1e-6), (box.y1 - box.y0) / Math.max(y1 - y0, 1e-6));
      const nextK = Math.min(Math.max(fit, MIN_K), maxScale / base.scale(), MAX_SCALE / base.scale());
      // the points' centre lands on the box's centre
      const x = (box.x0 + box.x1) / 2 - nextK * ((x0 + x1) / 2);
      const y = (box.y0 + box.y1) / 2 - nextK * ((y0 + y1) / 2);
      setState({ base, k: nextK, x, y });
    },
    [],
  );

  // Wheel and trackpad pinch (ctrlKey): a native listener, since React's wheel handler can't preventDefault
  useEffect(() => {
    const el = svg.current;
    if (!el) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const rect = el.getBoundingClientRect();
      const factor = Math.exp(-event.deltaY * (event.ctrlKey ? 0.01 : 0.0015));
      apply(factor, event.clientX - rect.left, event.clientY - rect.top);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [svg, apply, fitted]);

  // Drag to pan with one pointer, pinch to zoom with two. Window listeners rather than pointer capture,
  // so a click still reaches the state, route or marker under the pointer.
  useEffect(() => {
    const el = svg.current;
    if (!el) return;
    const pointers = new Map<number, { x: number; y: number }>();
    let moved = 0;

    const local = (event: PointerEvent) => {
      const rect = el.getBoundingClientRect();
      return { x: event.clientX - rect.left, y: event.clientY - rect.top };
    };

    const onMove = (event: PointerEvent) => {
      const prev = pointers.get(event.pointerId);
      if (!prev) return;
      const next = local(event);
      if (pointers.size >= 2) {
        const [a, b] = [...pointers.entries()].map(([id, p]) => (id === event.pointerId ? next : p));
        const [pa, pb] = [...pointers.values()];
        const before = Math.hypot(pa.x - pb.x, pa.y - pb.y) || 1;
        const after = Math.hypot(a.x - b.x, a.y - b.y) || 1;
        const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
        const prevMid = { x: (pa.x + pb.x) / 2, y: (pa.y + pb.y) / 2 };
        apply(after / before, prevMid.x, prevMid.y, mid.x - prevMid.x, mid.y - prevMid.y);
        moved = DRAG_THRESHOLD_PX;
      } else {
        moved += Math.hypot(next.x - prev.x, next.y - prev.y);
        if (moved >= DRAG_THRESHOLD_PX) {
          setDragging(true);
          apply(1, 0, 0, next.x - prev.x, next.y - prev.y);
        }
      }
      pointers.set(event.pointerId, next);
    };

    const onUp = (event: PointerEvent) => {
      pointers.delete(event.pointerId);
      if (pointers.size > 0) return;
      // a pan ends in a click on whatever is under the pointer: swallow it
      if (moved >= DRAG_THRESHOLD_PX) suppressClick.current = true;
      setDragging(false);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };

    const onDown = (event: PointerEvent) => {
      if (event.button !== 0 && event.pointerType === "mouse") return;
      if (pointers.size === 0) {
        moved = 0;
        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onUp);
        window.addEventListener("pointercancel", onUp);
      }
      pointers.set(event.pointerId, local(event));
    };

    const onClickCapture = (event: MouseEvent) => {
      if (!suppressClick.current) return;
      suppressClick.current = false;
      event.stopPropagation();
      event.preventDefault();
    };

    el.addEventListener("pointerdown", onDown);
    el.addEventListener("click", onClickCapture, true);
    return () => {
      el.removeEventListener("pointerdown", onDown);
      el.removeEventListener("click", onClickCapture, true);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
  }, [svg, apply, fitted]);

  // panned counts too: Reset and the view buttons' pressed state depend on it
  const zoomed = current !== null && (current.k !== 1 || current.x !== 0 || current.y !== 0);
  return { projection, k, zoomed, zoomBy, zoomTo, reset, dragging };
}

export const ZOOM_BUTTON_FACTOR = BUTTON_FACTOR;
