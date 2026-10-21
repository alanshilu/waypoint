"""What an agent turn returns to the app: the reply, the trip it worked on, the stops and places it chose."""

from __future__ import annotations

from typing import Any

from app.agent.orchestrator import AgentTurn
from app.agent.sessions import Session


def user_text(message: str, selected_route_id: int | None) -> str:
    """The message as the model sees it, with the route the user picked on the map since the last one."""
    if selected_route_id is None:
        return message
    return f"[App context: the user has selected route {selected_route_id} on the map.]\n{message}"


def _last_result(steps, tool: str):
    for step in reversed(steps):
        if step.tool == tool and step.error is None and isinstance(step.full_result, dict):
            yield step


def _stop_label(stop: dict) -> str:
    # "San Benito County, California, United States" -> "San Benito County"
    name = (stop.get("name") or "").split(",")[0]
    if stop.get("kind") == "lunch":
        return f"Lunch, day {stop.get('day')} · near {name}"
    if stop.get("kind") == "destination":
        return name
    return f"Night {stop.get('day')} · {name}"


def place_groups(steps, answer: dict) -> list[dict]:
    """
    This turn's find_places groups for the map and list, each labelled with the stop it belongs to,
    and each recommended place marked with the agent's reason. Ids the answer names that no group
    returned are dropped, so the app only highlights places the search actually found.
    """
    labels: dict[str, str] = {}
    for step in steps:
        if step.tool == "plan_stops" and step.error is None and isinstance(step.full_result, dict):
            for stop in (step.full_result.get("stops") or []) + (step.full_result.get("lunch_stops") or []):
                labels[str(stop.get("id"))] = _stop_label(stop)
    reasons = {str(p.get("id")): str(p.get("reason") or "") for p in answer.get("places") or [] if isinstance(p, dict)}

    groups = []
    for step in steps:
        if step.tool != "find_places" or step.error is not None or not isinstance(step.full_result, dict):
            continue
        for group in step.full_result.get("groups") or []:
            places = [{**place, "recommended": place["id"] in reasons, "reason": reasons.get(place["id"]) or None}
                      for place in group.get("places") or []]
            groups.append({**group, "label": labels.get(str(group.get("near")), str(group.get("near"))),
                           "places": places})
    return groups


def build_response(session: Session, turn: AgentTurn) -> dict[str, Any]:
    answer = turn.final_answer or {}

    trip_id = session.trip_id
    for tool in ("plan_stops", "generate_routes", "create_trip"):
        step = next(_last_result(turn.steps, tool), None)
        if step and step.full_result.get("trip_id") is not None:
            trip_id = step.full_result["trip_id"]
            break

    # The stops the answer names, resolved from this turn's plan_stops results
    known: dict[str, dict] = {}
    for step in turn.steps:
        if step.tool == "plan_stops" and step.error is None and isinstance(step.full_result, dict):
            for stop in step.full_result.get("stops") or []:
                known[str(stop.get("id"))] = stop
    planned_stops = [known[s] for s in answer.get("stops") or [] if s in known]

    poi_step = next(_last_result(turn.steps, "search_pois"), None)
    pois = None
    if poi_step:
        pois = {"center": {"lat": poi_step.args.get("lat"), "lon": poi_step.args.get("lon")},
                "items": poi_step.full_result.get("pois") or []}

    return {
        "session_id": session.id,
        "trip_id": trip_id,
        "reply": turn.reply,
        "answer": answer,
        "planned_stops": planned_stops,
        "places": place_groups(turn.steps, answer),
        "pois": pois,
        "tool_calls": [
            {"tool": s.tool, "ms": s.ms, "cached": s.cached, "error": s.error, "tokens": s.tokens,
             "model_call": s.model_call}
            for s in turn.steps
        ],
        "usage": turn.usage.to_dict(),
    }
