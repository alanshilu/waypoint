"""Trips: create, list, read, and plan a route's days. HTTP over app/services/trip_service.py and trip_planning.py."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import internal_only, not_in_public_demo
from app.api.v1.serializers import DEFAULT_SIMPLIFY_TOLERANCE, trip_to_dict
from app.core.db import get_db
from app.models.route import Route
from app.models.trip import Trip
from app.schemas.trip import TripCreate
from app.services import trip_service
from app.services.trip_planning import TripPlanner, get_trip_planner

router = APIRouter()


@router.post("/", dependencies=[Depends(internal_only)])
def create_trip(
    payload: TripCreate,
    reuse_recent: bool = Query(False, description="Return an existing trip with the same ends from the last 24 h"),
    db: Session = Depends(get_db),
):
    result = trip_service.create_trip(db, payload, reuse_recent)
    return {
        "status": "success",
        "message": ("Reused a trip with the same origin and destination from the last 24 hours" if result.reused
                    else "Trip created successfully"),
        "trip_id": result.trip_id,
        "reused": result.reused,
    }


@router.get("/trips", dependencies=[Depends(not_in_public_demo)])
def list_trips(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    # Fetches a limited number of trips, ordered by newest first
    trips = db.query(Trip).order_by(Trip.created_at.desc()).offset(skip).limit(limit).all()
    return {
        "status": "success",
        "trips": [
            {"id": t.id, "origin_name": t.origin_name, "destination_name": t.destination_name, "created_at": t.created_at}
            for t in trips
        ],
    }


@router.get("/{trip_id}")
def get_trip(
    trip_id: int,
    tolerance: float = Query(DEFAULT_SIMPLIFY_TOLERANCE, ge=0, description="Route simplification in degrees. 0 returns every point."),
    db: Session = Depends(get_db),
):
    """Returns a saved trip with its origin, destination and routes."""
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    return trip_to_dict(trip, trip_service.routes_to_show(db, trip), tolerance)


@router.post("/{trip_id}/plan")
def plan_trip_stops(
    trip_id: int,
    route_id: int = Query(..., description="One of this trip's routes"),
    max_hours: float = Query(8, gt=0, le=16, description="Maximum driving hours per day"),
    start: datetime | None = Query(None, description="Departure, ISO 8601. Default: tomorrow 08:00 at the origin."),
    db: Session = Depends(get_db),
    planner: TripPlanner = Depends(get_trip_planner),
):
    """
    Splits a route into days of at most max_hours of driving and returns each
    overnight stop and the destination with its arrival date and the forecast
    for that date. Stop positions are computed, never guessed; see notes.
    """
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    route = db.query(Route).filter(Route.id == route_id, Route.trip_id == trip_id).first()
    if not route:
        raise HTTPException(status_code=404, detail="Route not found for this trip")
    return planner.plan(trip, route, max_hours, start)
