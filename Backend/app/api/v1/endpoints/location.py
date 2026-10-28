from fastapi import APIRouter, HTTPException, Query

from app.services.geocoding_service import search_address
from app.services.ors_http import OrsError

router = APIRouter()


@router.get("/search")
def geocode_location(
    q: str = Query(..., min_length=2, description="The address or city name to search")
):
    """
    Returns a list of matching locations and their lat/lon coordinates.
    """
    try:
        results = search_address(q)
    except OrsError as e:
        # The geocoder failing is an upstream problem: 504 when it timed out, else 502, with its reason
        raise HTTPException(status_code=504 if e.timed_out else 502, detail=str(e))
    return {"status": "success", "results": results}
