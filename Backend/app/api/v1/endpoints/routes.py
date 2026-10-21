"""POST /routes/generate and /routes/select: HTTP over app/services/route_generation.py."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import internal_only
from app.api.v1.serializers import add_duration_ratios, route_to_dict
from app.core.db import get_db
from app.services.errors import NotFound
from app.services.route_generation import RouteGenerator, get_route_generator, select_route as select
from app.services.routing_service import RoutingError

router = APIRouter()


@router.post("/generate/{trip_id}", dependencies=[Depends(internal_only)])
def generate_and_save_routes(
    trip_id: int,
    reuse_existing: bool = Query(False, description="Return the trip's existing routes instead of generating new ones"),
    db: Session = Depends(get_db),
    generator: RouteGenerator = Depends(get_route_generator),
):
    try:
        result = generator.generate(db, trip_id, reuse_existing)
    except NotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RoutingError as e:
        # The route service failing is an upstream problem, not ours: 504 when it timed out, else 502
        raise HTTPException(status_code=504 if e.timed_out else 502, detail=str(e))
    return {
        "status": "success",
        "trip_id": trip_id,
        "reused": result.reused,
        "routes": add_duration_ratios([route_to_dict(r) for r in result.routes]),
    }


@router.post("/select/{route_id}", dependencies=[Depends(internal_only)])
def select_route(route_id: int, db: Session = Depends(get_db)):
    """Marks a route as selected, the only selected one of its trip."""
    try:
        trip = select(db, route_id)
    except NotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "success", "message": f"Route {route_id} selected for Trip {trip.id}"}
