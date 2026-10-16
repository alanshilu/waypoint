from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from geoalchemy2.shape import to_shape # ADDED: to convert PostGIS binary to Python
from app.core.db import get_db
from app.models.trip import Trip
from app.services.routing_service import get_route_options
from app.services.scoring_service import score_route_options
from app.services.db_route_service import save_routes_to_db
from app.models.route import Route
from app.api.v1.serializers import add_duration_ratios, route_to_dict

router = APIRouter()

ROUTE_TYPES = ("fastest", "backroads")


@router.post("/generate/{trip_id}")
def generate_and_save_routes(
    trip_id: int,
    reuse_existing: bool = Query(False, description="Return the trip's existing routes instead of generating new ones"),
    db: Session = Depends(get_db),
):
    # 1. Fetch the trip directly from the database
    trip = db.query(Trip).filter(Trip.id == trip_id).first()

    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    if reuse_existing:
        # newest route of each type; reuse only when the trip has both
        latest: dict[str, Route] = {}
        for route in db.query(Route).filter(Route.trip_id == trip_id).order_by(Route.id.desc()):
            latest.setdefault(route.route_type, route)
        if all(t in latest for t in ROUTE_TYPES):
            return {
                "status": "success",
                "trip_id": trip_id,
                "reused": True,
                "routes": add_duration_ratios([route_to_dict(latest[t]) for t in ROUTE_TYPES]),
            }

    # 2. Extract Lat/Lon from the PostGIS Point binary
    origin_shape = to_shape(trip.origin_point)           # Converts to Shapely Point
    destination_shape = to_shape(trip.destination_point) # Converts to Shapely Point

    start_lon, start_lat = origin_shape.x, origin_shape.y
    end_lon, end_lat = destination_shape.x, destination_shape.y

    # 3. Pass the extracted coordinates to your services
    raw_routes = get_route_options(start_lon, start_lat, end_lon, end_lat)
    scored_routes = score_route_options(raw_routes)
    db_routes = save_routes_to_db(db, trip_id, scored_routes)

    return {
        "status": "success",
        "trip_id": trip_id,
        "reused": False,
        "routes": add_duration_ratios([route_to_dict(r) for r in db_routes])
    }
@router.post("/select/{route_id}")
def select_route(route_id: int, db: Session = Depends(get_db)):
    """
    Marks a specific route as selected and links it to the parent trip.
    """
    # 1. Find the route the user clicked
    selected_route = db.query(Route).filter(Route.id == route_id).first()

    if not selected_route:
        raise HTTPException(status_code=404, detail="Route not found")

    # 2. Find the parent trip this route belongs to
    trip = db.query(Trip).filter(Trip.id == selected_route.trip_id).first()

    # 3. Update the database state: exactly one selected route per trip
    db.query(Route).filter(Route.trip_id == trip.id, Route.id != selected_route.id).update(
        {Route.is_selected: False}, synchronize_session=False
    )
    selected_route.is_selected = True
    trip.selected_route_id = selected_route.id

    # (Optional: Delete the unselected candidate routes here to save DB space)

    db.commit()

    return {"status": "success", "message": f"Route {route_id} selected for Trip {trip.id}"}
