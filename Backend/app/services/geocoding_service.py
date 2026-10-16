import json
from urllib import error, parse, request
import json
from urllib import parse, request, error
from app.core.config import settings

def search_address(query: str) -> list[dict]:
    """Return matching OpenRouteService geocoding results."""
    encoded_query = parse.quote(query)
    url = (
        "https://api.openrouteservice.org/geocode/search"
        f"?api_key={parse.quote(settings.ors_api_key)}&text={encoded_query}"
    )
    req = request.Request(url, headers={"Accept": "application/json"})

    try:
        with request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        raise ValueError(f"Failed to geocode address: {query}") from exc

    results = []
    for feature in data.get("features", []):
        properties = feature.get("properties", {})
        coordinates = feature.get("geometry", {}).get("coordinates", [])
        if len(coordinates) < 2:
            continue

        label = properties.get("label") or properties.get("name", "Unknown Location")
        results.append({
            "label": label,
            "lon": coordinates[0],
            "lat": coordinates[1],
            "confidence": properties.get("confidence", 0),
        })

    return results

def search_address(query: str) -> list[dict]:
    """
    Converts a human-readable address into a list of possible coordinate matches.
    """
    # URL encode the query (e.g., "New York" -> "New%20York")
    encoded_query = parse.quote(query)
    url = f"https://api.openrouteservice.org/geocode/search?api_key={settings.ors_api_key}&text={encoded_query}"

    req = request.Request(url, headers={"Accept": "application/json"})

    try:
        with request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as e:
        print(f"Geocoding HTTP Error: {e.code}")
        raise ValueError(f"Failed to geocode address: {query}")

    results = []
    
    # ORS returns a GeoJSON FeatureCollection
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        coords = feature.get("geometry", {}).get("coordinates", [0, 0])
        
        # Build a clean, human-readable label (e.g., "San Francisco, California, USA")
        label_parts = [
            props.get("name"),
            props.get("region"),
            props.get("country")
        ]
        clean_label = ", ".join([p for p in label_parts if p])

        results.append({
            "label": clean_label or props.get("label", "Unknown Location"),
            "lon": coords[0],
            "lat": coords[1],
            "confidence": props.get("confidence", 0) # Helps frontend sort best matches
        })

    return results