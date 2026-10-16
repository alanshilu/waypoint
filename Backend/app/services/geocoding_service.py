import json
from urllib import error, parse, request

from app.core.config import settings


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


def near_label(lat: float, lon: float) -> str:
    """The name used when a point cannot be reverse geocoded. Never a guessed place name."""
    return f"near {lat:.3f},{lon:.3f}"


def reverse_geocode(lat: float, lon: float) -> str:
    """
    Names the town or area at a point via OpenRouteService, e.g.
    "Fort Stockton, Texas, United States". Returns near_label(lat, lon) on any
    failure or empty result, so a name always comes from the geocoder or is
    plainly a coordinate.
    """
    query = parse.urlencode({
        "api_key": settings.ors_api_key,
        "point.lat": lat,
        "point.lon": lon,
        "size": 1,
        "layers": "locality,localadmin,county",
    })
    req = request.Request(
        f"https://api.openrouteservice.org/geocode/reverse?{query}",
        headers={"Accept": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        props = data["features"][0]["properties"]
    except Exception:  # noqa: BLE001 - any failure falls back to coordinates
        return near_label(lat, lon)

    parts = [props.get("locality") or props.get("localadmin") or props.get("name"), props.get("region"),
             props.get("country")]
    label = ", ".join(dict.fromkeys(p for p in parts if p))
    return label or near_label(lat, lon)
