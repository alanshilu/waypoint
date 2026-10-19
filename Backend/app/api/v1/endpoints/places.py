"""POST /places/search: campsites and places to eat near a trip's stops (see app/services/places_service.py)."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.places_service import find_places

router = APIRouter()


class PlacePoint(BaseModel):
    near: str = Field(min_length=1, max_length=64, description="What the point is, e.g. a plan_stops stop id")
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    kinds: list[Literal["camping", "food"]] = Field(min_length=1, max_length=2)


class PlaceSearch(BaseModel):
    points: list[PlacePoint] = Field(min_length=1, max_length=10)


@router.post("/search")
def search_places(body: PlaceSearch):
    """
    Campsites (within about 15 miles) and places to eat (about 3 miles) near each point, from
    OpenStreetMap, ranked by distance and by how much is known about each. One group per point and kind.
    """
    groups = find_places([p.model_dump() for p in body.points])
    return {
        "groups": groups,
        "attribution": "Place data © OpenStreetMap contributors (ODbL)",
    }
