from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.services.ors_http import OrsError
from app.services.poi_service import fetch_pois_from_ors, get_saved_pois, save_pois_to_db
from app.utils.bbox import boundingBox
from app.api.v1.serializers import poi_to_dict

router = APIRouter()

@router.get("/")
def list_saved_pois(
    lon: float = Query(..., ge=-180, le=180),
    lat: float = Query(..., ge=-90, le=90),
    radius_km: float = Query(2, gt=0, le=50),
    db: Session = Depends(get_db)
):
    """
    Returns POIs already saved in the database around a point. Does not call the external API.
    """
    min_lon, min_lat, max_lon, max_lat = boundingBox(lat, lon, radius_km)
    pois = [poi_to_dict(poi) for poi in get_saved_pois(db, min_lon, min_lat, max_lon, max_lat)]

    return {
        "status": "success",
        "count": len(pois),
        "pois": pois
    }

@router.get("/search")
def search_and_save_pois(
    lon: float = Query(..., ge=-180, le=180),
    lat: float = Query(..., ge=-90, le=90),
    db: Session = Depends(get_db)
):
    """
    Finds road-trip-relevant POIs in a bounding box, saves them, and returns them.
    """
    try:
        # 1. Fetch filtered data from external API
        min_lon, min_lat, max_lon, max_lat = boundingBox(lat, lon, 2)  # Adjust the buffer distance as needed
        raw_pois = fetch_pois_from_ors(min_lon, min_lat, max_lon, max_lat)

        if not raw_pois:
            return {"status": "success", "pois": [], "message": "No relevant POIs found"}

        # 2. Save them to the database
        db_pois = save_pois_to_db(db, raw_pois)

        # 3. Format the response
        response_pois = [poi_to_dict(poi) for poi in db_pois]

        return {
            "status": "success",
            "count": len(response_pois),
            "pois": response_pois
        }

    except OrsError as e:
        raise HTTPException(status_code=504 if e.timed_out else 502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
