"""POST /places/search: campsites and places to eat near a trip's stops (see app/services/places/)."""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.services.places import PlacesFinder, get_places_finder

router = APIRouter()


class PlacePoint(BaseModel):
    near: str = Field(min_length=1, max_length=64, description="What the point is, e.g. a plan_stops stop id")
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    # stay: campgrounds, RV parks, hotels, motels, guest houses, hostels, cabins, vacation rentals
    kinds: list[Literal["stay", "food"]] = Field(min_length=1, max_length=2)


class PlaceSearch(BaseModel):
    points: list[PlacePoint] = Field(min_length=1, max_length=10)


@router.post("/search")
def search_places(body: PlaceSearch, finder: PlacesFinder = Depends(get_places_finder)):
    """
    Places to stay (campgrounds to hotels, within about 15 miles) and to eat (about 3 miles) near each point,
    from OpenStreetMap, ranked by distance and by how much is known about each. One group per point and kind.
    """
    groups = finder.find([p.model_dump() for p in body.points])
    return {
        "groups": groups,
        "attribution": "Place data © OpenStreetMap contributors (ODbL)",
    }
