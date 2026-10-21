"""What the model sees of a tool result, and what the trace keeps."""

from __future__ import annotations

from typing import Any

# Size limit for a step's result in the trace. The full result stays on the step in memory (full_result)
# so eval checks can read all of it.
TRACE_RESULT_LIMIT = 4000


def truncate(text: str, limit: int = TRACE_RESULT_LIMIT) -> str:
    return text if len(text) <= limit else text[:limit] + f"... [truncated, {len(text)} chars]"


def model_view(result: Any) -> Any:
    """
    The tool result as the model sees it. Route geometry, elevation samples and turn-by-turn directions are
    replaced by short summaries: the model never needs hundreds of coordinates (plan_stops gives it the
    points it may use), and they would be re-sent on every loop iteration. The trace keeps the full result.
    """
    if isinstance(result, dict):
        out = {}
        for key, value in result.items():
            if key == "geometry" and isinstance(value, dict) and "coordinates" in value:
                out[key] = {"type": value.get("type"), "points": len(value["coordinates"])}
            elif key == "elevation_profile" and isinstance(value, list) and value:
                metres = [p.get("m") for p in value if isinstance(p, dict) and p.get("m") is not None]
                out[key] = {"samples": len(value), "min_m": min(metres, default=None), "max_m": max(metres, default=None)}
            elif key == "directions" and isinstance(value, list):
                # the app shows the turn-by-turn list; the model only needs to know it exists
                out[key] = {"steps": len(value)}
            else:
                out[key] = model_view(value)
        return out
    if isinstance(result, list):
        return [model_view(v) for v in result]
    return result
