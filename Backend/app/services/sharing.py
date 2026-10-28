"""
Share links: the latest plan the agent made for a trip (kept on trips.shared_plan), and the read-only view of a
trip that GET /shared/{public_id} serves.

The view holds the routes, which one is selected, the planned stops and the places, and nothing else: no trip,
route or row ids (integers that could be counted through to find other trips), no session or conversation
data, no timestamps of who did what. Stop ids, which embed the route id ("17-1"), are renumbered.
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.api.v1.serializers import DEFAULT_SIMPLIFY_TOLERANCE, add_duration_ratios, point_to_place, route_to_dict
from app.models.route import Route
from app.models.trip import Trip

# The route fields a shared trip shows
ROUTE_FIELDS = ("route_type", "distance_miles", "duration_seconds", "ascent_m", "descent_m", "scenic_score",
                "duration_vs_fastest", "geometry", "elevation_profile", "directions")
# The place fields a shared trip shows (each from OpenStreetMap or the agent's reason for picking it)
PLACE_FIELDS = ("id", "kind", "name", "category", "lat", "lon", "distance_mi", "facts", "website", "recommended",
                "reason")


def plan_snapshot(response: dict) -> dict | None:
    """What a turn's response says the plan is, to keep for the share link; None when it planned nothing."""
    stops = response.get("planned_stops") or []
    places = response.get("places") or []
    if not stops and not places:
        return None
    return {"planned_stops": copy.deepcopy(stops), "places": copy.deepcopy(places),
            "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def save_plan(db: Session, trip_id: int, snapshot: dict) -> None:
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if trip is None:
        return
    trip.shared_plan = snapshot
    db.commit()


def find_by_public_id(db: Session, public_id: uuid.UUID) -> Trip | None:
    return db.query(Trip).filter(Trip.public_id == public_id).first()


def shared_view(trip: Trip, routes: list[Route], tolerance: float = DEFAULT_SIMPLIFY_TOLERANCE) -> dict:
    """The read-only trip for a share link. routes: the routes the trip shows (trip_service.routes_to_show)."""
    route_dicts = add_duration_ratios([route_to_dict(r, tolerance) for r in routes])
    shown_routes = [{**{k: r.get(k) for k in ROUTE_FIELDS}, "selected": r["id"] == trip.selected_route_id}
                    for r in route_dicts]

    plan = trip.shared_plan or {}
    renamed: dict[str, str] = {}

    def new_id(old) -> str:
        key = str(old)
        if key not in renamed:
            renamed[key] = f"stop-{len(renamed) + 1}"
        return renamed[key]

    stops = []
    for stop in plan.get("planned_stops") or []:
        stops.append({k: v for k, v in stop.items() if k not in ("route_id", "trip_id")} | {"id": new_id(stop.get("id"))})

    places = []
    for group in plan.get("places") or []:
        places.append({
            "near": new_id(group.get("near")),
            "label": group.get("label"),
            "kind": group.get("kind"),
            "lat": group.get("lat"),
            "lon": group.get("lon"),
            "radius_mi": group.get("radius_mi"),
            "source": group.get("source"),
            **({"note": group["note"]} if group.get("note") else {}),
            "places": [{k: p[k] for k in PLACE_FIELDS if k in p} for p in group.get("places") or []],
        })

    return {
        "public_id": str(trip.public_id),
        "name": trip.name,
        "origin": point_to_place(trip.origin_name, trip.origin_point),
        "destination": point_to_place(trip.destination_name, trip.destination_point),
        "routes": shown_routes,
        "planned_stops": stops,
        "places": places,
        "plan_saved_at": plan.get("saved_at"),
    }
