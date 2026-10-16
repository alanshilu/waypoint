from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from app.services.weather_service import get_current_weather, get_forecast, get_forecast_for_date

router = APIRouter()

@router.get("/current")
def current_weather(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180)
):
    """Gets the live, current conditions for a specific coordinate."""
    try:
        return get_current_weather(lat, lon)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/forecast")
def weather_forecast(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    target_date: Optional[str] = Query(None, description="Format: YYYY-MM-DD. Optional.")
):
    """
    Gets the 7-day forecast. If a target_date is provided, 
    it returns only the weather for that specific day.
    """
    try:
        if target_date:
            forecast = get_forecast_for_date(lat, lon, target_date)
            if not forecast:
                raise HTTPException(status_code=400, detail="Date is in the past or too far in the future (max 16 days).")
            return forecast
            
        # Default behavior: return the standard 7-day list
        return {"forecast": get_forecast(lat, lon, days=7)}
        
    except HTTPException:
        raise  # the 400 above, not a server error
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
