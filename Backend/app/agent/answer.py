"""The agent's structured final answer: its schema, the reply text a user reads, and the answers for a refusal or a cut-off."""

from __future__ import annotations

import json

# output_config.format guarantees that every response that ends the turn is JSON matching this schema.
FINAL_ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "recommended_route_type": {"type": "string", "enum": ["fastest", "backroads", "none"]},
        "departure_window": {
            "type": "object",
            "properties": {
                "start": {"type": "string", "description": "ISO 8601 date-time, or empty"},
                "end": {"type": "string", "description": "ISO 8601 date-time, or empty"},
                "reason": {"type": "string"},
            },
            "required": ["start", "end", "reason"],
            "additionalProperties": False,
        },
        "stops": {"type": "array", "items": {"type": "string"}, "description": "plan_stops stop ids"},
        "places": {
            "type": "array",
            "description": "recommended find_places places",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["id", "reason"],
                "additionalProperties": False,
            },
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "recommended_route_type", "departure_window", "stops", "places", "warnings"],
    "additionalProperties": False,
}


def _empty_answer(summary: str, warning: str) -> dict:
    return {"summary": summary, "recommended_route_type": "none", "departure_window": {"start": "", "end": "", "reason": ""},
            "stops": [], "places": [], "warnings": [warning]}


def refusal_answer(category: str | None) -> dict:
    return _empty_answer("I can't help with that request.", f"The model declined this request ({category or 'no category'}).")


def parse_final_answer(text: str, stop_reason: str) -> dict:
    """The answer from the turn's last response; text that isn't JSON is only reachable on max_tokens, cut off."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return _empty_answer(text, f"The answer was cut off (stop_reason={stop_reason}).")


def render_reply(answer: dict) -> str:
    """The text a user reads. Departure times live in the structured field; the app shows them."""
    parts = [answer.get("summary", "").strip()]
    window = answer.get("departure_window") or {}
    if window.get("reason"):
        parts.append(f"Departure: {window['reason'].strip()}")
    for warning in answer.get("warnings") or []:
        parts.append(f"Note: {warning.strip()}")
    return "\n\n".join(p for p in parts if p)
