import json
from urllib import request
from sqlalchemy import func
from sqlalchemy.orm import Session
from shapely.geometry import Point
from geoalchemy2.shape import from_shape

from app.core.config import settings
from app.models.poi import POI
from app.services import ors_http

URL = "https://api.openrouteservice.org/pois"
# Seconds for one attempt, and for all attempts of one search together
POI_TIMEOUT_S = 30
POI_RETRY_BUDGET_S = 75
SOURCE = "openrouteservice"
UNNAMED = "Unknown Location"  # placeholder older rows were saved with
HEADERS = {
    'Accept': 'application/json, application/geo+json; charset=utf-8',
    'Authorization': settings.ors_api_key, 
    'Content-Type': 'application/json; charset=utf-8'
}

ROAD_TRIP_CATEGORIES = {
    "restaurant", "cafe", "fast_food", "pub", "bar",
    "fuel", "hotel", "attraction", "artwork", "museum", 
    "viewpoint", "camp_site", "park", "beach", "picnic_site",
    "supermarket", "convenience",
}

def has_road_trip_category(feature: dict) -> bool:
    """Filters POIs based on the predefined road trip categories."""
    properties = feature.get("properties", {})
    category_names = set()

    category_ids = properties.get("category_ids", {})
    if isinstance(category_ids, dict):
        for category in category_ids.values():
            if isinstance(category, dict):
                category_name = category.get("category_name")
                if category_name:
                    category_names.add(str(category_name).lower())

    for key in ("categories", "category", "category_name", "type"):
        value = properties.get(key)
        if isinstance(value, str):
            category_names.add(value.lower())
        elif isinstance(value, list):
            category_names.update(str(item).lower() for item in value)

    return bool(category_names & ROAD_TRIP_CATEGORIES)

def fetch_pois_from_ors(min_lon: float, min_lat: float, max_lon: float, max_lat: float,
                        category_ids: list[int] | None = None) -> list[dict]:
    """Fetches POIs within a bounding box from ORS, optionally only these ORS category ids."""
    body = {
        "request": "pois",
        "geometry": {
            "bbox": [[min_lon, min_lat], [max_lon, max_lat]]
        },
        "limit": 500
    }
    if category_ids:
        body["filters"] = {"category_ids": category_ids}

    req = request.Request(URL, data=json.dumps(body).encode("utf-8"), headers=HEADERS, method="POST")

    # timeouts, 429 and 5xx are retried; raises ors_http.OrsError
    data = ors_http.open_json(req, timeout=POI_TIMEOUT_S, budget_s=POI_RETRY_BUDGET_S, what="the POI search",
                              opener=request.urlopen)
    features = data.get("features", [])
    return [f for f in features if has_road_trip_category(f)]

def get_saved_pois(db: Session, min_lon: float, min_lat: float, max_lon: float, max_lat: float, limit: int = 500) -> list[POI]:
    """Reads already-saved POIs inside a bounding box. No external API call."""
    envelope = func.ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326)
    return (
        db.query(POI)
        .filter(func.ST_Intersects(POI.location, envelope), POI.name != UNNAMED)
        .order_by(POI.id)
        .limit(limit)
        .all()
    )

def save_pois_to_db(db: Session, geojson_features: list[dict]) -> list[POI]:
    """Converts GeoJSON features to PostGIS Points and saves them safely."""
    saved_pois = []
    seen_ids = set()  # one response can list the same OSM id twice

    for feature in geojson_features:
        properties = feature.get("properties", {})
        geometry = feature.get("geometry", {})
        
        # A stop with no name is no use to the traveller, so it is not stored
        name = (properties.get("osm_tags") or {}).get("name")
        if not name:
            continue

        # Extract unique ID to prevent duplicates
        osm_id = properties.get("osm_id")
        osm_id = str(osm_id) if osm_id is not None else None

        if osm_id is not None:
            if osm_id in seen_ids:
                continue
            seen_ids.add(osm_id)

            existing_poi = db.query(POI).filter(POI.source == SOURCE, POI.external_id == osm_id).first()
            if existing_poi:
                saved_pois.append(existing_poi)
                continue

        # Convert to PostGIS Geometry
        coords = geometry.get("coordinates", [0, 0])
        poi_point = from_shape(Point(coords[0], coords[1]), srid=4326)

        # Grab the first available category name for the database
        category = "generic"
        if properties.get("category_ids"):
            first_cat = list(properties["category_ids"].values())[0]
            if isinstance(first_cat, dict) and first_cat.get("category_name"):
                category = first_cat.get("category_name")
                
        new_poi = POI(
            name=name,
            category=category.lower(),
            location=poi_point,
            source=SOURCE,
            external_id=osm_id
        )
        
        db.add(new_poi)
        saved_pois.append(new_poi)
        
    db.commit()
    for poi in saved_pois:
        db.refresh(poi)
        
    return saved_pois