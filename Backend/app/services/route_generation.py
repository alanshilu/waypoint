"""A trip's two routes: generated with a router, scored and saved, or reused; and which one is selected."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

from geoalchemy2.shape import to_shape
from sqlalchemy.orm import Session

from app.models.route import Route
from app.models.trip import Trip
from app.services.db_route_service import save_routes_to_db
from app.services.errors import NotFound
from app.services.providers import OrsRouting, RoutingProvider
from app.services.scoring_service import score_route_options

ROUTE_TYPES = ("fastest", "backroads")


@dataclass
class GeneratedRoutes:
    routes: list[Route]
    reused: bool


class RouteGenerator:
    """Generates a trip's fastest and backroads routes with the given router, then scores and saves them."""

    def __init__(self, routing: RoutingProvider,
                 score: Callable[[dict], dict] = score_route_options,
                 save: Callable[[Session, int, dict], list[Route]] = save_routes_to_db):
        self.routing = routing
        self._score = score
        self._save = save

    def generate(self, db: Session, trip_id: int, reuse_existing: bool = False) -> GeneratedRoutes:
        """
        The trip's routes. With reuse_existing, the newest route of each type when the trip has both and both
        have directions (routes saved before directions were kept are generated again, once).
        Raises NotFound, or routing_service.RoutingError when the router fails.
        """
        trip = db.query(Trip).filter(Trip.id == trip_id).first()
        if not trip:
            raise NotFound("Trip not found")

        if reuse_existing:
            latest: dict[str, Route] = {}
            for route in db.query(Route).filter(Route.trip_id == trip_id).order_by(Route.id.desc()):
                latest.setdefault(route.route_type, route)
            if all(t in latest and latest[t].directions is not None for t in ROUTE_TYPES):
                return GeneratedRoutes([latest[t] for t in ROUTE_TYPES], reused=True)

        # Shapely Points are (longitude, latitude)
        origin, destination = to_shape(trip.origin_point), to_shape(trip.destination_point)
        options = self.routing.get_route_options(origin.x, origin.y, destination.x, destination.y)
        return GeneratedRoutes(self._save(db, trip_id, self._score(options)), reused=False)


def select_route(db: Session, route_id: int) -> Trip:
    """Marks the route selected, and the only selected one of its trip. Returns the trip. Raises NotFound."""
    selected = db.query(Route).filter(Route.id == route_id).first()
    if not selected:
        raise NotFound("Route not found")
    trip = db.query(Trip).filter(Trip.id == selected.trip_id).first()
    db.query(Route).filter(Route.trip_id == trip.id, Route.id != selected.id).update(
        {Route.is_selected: False}, synchronize_session=False
    )
    selected.is_selected = True
    trip.selected_route_id = selected.id
    db.commit()
    return trip


@lru_cache(maxsize=1)
def get_route_generator() -> RouteGenerator:
    """The app's generator, on OpenRouteService. The FastAPI dependency."""
    return RouteGenerator(OrsRouting())
