from fastapi import APIRouter, Query, HTTPException
from app.services.geocoding_service import search_address

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
        if not results:
            return {"status": "success", "results": []}
            
        return {
            "status": "success",
            "results": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))