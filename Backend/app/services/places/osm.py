"""
What a campsite or place to eat is in OpenStreetMap, and how they're ranked. Pure functions over
OSM-shaped elements ({"type", "id", "lat"/"lon" or "center", "tags"}), whichever source found them.
Everything a place says about itself (facts) comes from its tags; nothing is inferred.
"""

from __future__ import annotations

import math

CAMPING_RADIUS_KM = 25.0  # about 15 miles: a short drive off the route at the end of the day
FOOD_RADIUS_KM = 5.0
# Overnight and lunch points on backroads are often far from a town: food searches that find nothing
# within FOOD_RADIUS_KM are repeated once out to this radius (about 12 miles)
FOOD_WIDE_RADIUS_KM = 20.0
PLACES_PER_GROUP = 6

KINDS = ("camping", "food")
CAMPING_TAGS = ("camp_site", "caravan_site")  # tourism=*
FOOD_TAGS = ("restaurant", "fast_food", "cafe", "food_court")  # amenity=*

KM_PER_MILE = 1.609344

# (kind, lat, lon): one search
Search = tuple[str, float, float]


def radius_km(kind: str) -> float:
    return CAMPING_RADIUS_KM if kind == "camping" else FOOD_RADIUS_KM


def km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def kind_of(tags: dict) -> str | None:
    if tags.get("tourism") in CAMPING_TAGS:
        return "camping"
    if tags.get("amenity") in FOOD_TAGS:
        return "food"
    return None


def usable(tags: dict) -> bool:
    """A place a traveller can actually go to: named, not private, not hike-in only."""
    if not tags.get("name"):
        return False
    if tags.get("access") in ("private", "no"):
        return False
    if tags.get("backcountry") == "yes":
        return False
    return tags.get("disused") != "yes"


def _yes(tags: dict, key: str) -> bool:
    return tags.get(key) in ("yes", "designated")


def facts_of(kind: str, tags: dict) -> list[str]:
    """Short facts, each straight from an OSM tag, that help a traveller choose."""
    facts: list[str] = []
    if kind == "camping":
        if tags.get("tourism") == "caravan_site":
            facts.append("RV park")
        if _yes(tags, "tents"):
            facts.append("tents allowed")
        elif tags.get("tents") == "no":
            facts.append("no tents")
        if _yes(tags, "caravans") and tags.get("tourism") != "caravan_site":
            facts.append("RVs allowed")
        if _yes(tags, "toilets"):
            facts.append("toilets")
        if _yes(tags, "shower") or _yes(tags, "showers"):
            facts.append("showers")
        if _yes(tags, "drinking_water"):
            facts.append("drinking water")
        if tags.get("power_supply") == "yes":
            facts.append("power hookups")
        if tags.get("fee") == "no":
            facts.append("free")
        elif tags.get("fee") == "yes":
            facts.append("fee")
        if tags.get("reservation") in ("required", "recommended", "yes", "no"):
            facts.append(f"reservations: {tags['reservation']}")
        if tags.get("operator"):
            facts.append(f"run by {tags['operator']}")
    else:
        facts.append(tags.get("amenity", "").replace("_", " "))
        if tags.get("cuisine"):
            facts.append(tags["cuisine"].replace("_", " ").replace(";", ", "))
        if tags.get("opening_hours"):
            facts.append(f"hours: {tags['opening_hours']}")
        if tags.get("diet:vegetarian") in ("yes", "only"):
            facts.append("vegetarian options")
        if tags.get("diet:vegan") in ("yes", "only"):
            facts.append("vegan options")
        if _yes(tags, "takeaway"):
            facts.append("takeaway")
        if _yes(tags, "outdoor_seating"):
            facts.append("outdoor seating")
    return [f for f in facts if f]


def _score(kind: str, distance_mi: float, tags: dict) -> float:
    """Lower is better: distance, less a little for each fact that makes the choice easier to trust."""
    known = 0
    if kind == "camping":
        known += sum(_yes(tags, k) for k in ("toilets", "drinking_water", "shower"))
        known += 1 if tags.get("website") or tags.get("reservation") else 0
        return distance_mi - 0.75 * known
    known += 1 if tags.get("opening_hours") else 0
    known += 1 if tags.get("cuisine") else 0
    return distance_mi - 0.3 * known


def to_place(element: dict, kind: str, lat: float, lon: float) -> dict:
    tags = element.get("tags") or {}
    plat = element.get("lat", (element.get("center") or {}).get("lat"))
    plon = element.get("lon", (element.get("center") or {}).get("lon"))
    distance_mi = km(lat, lon, plat, plon) / KM_PER_MILE
    place = {
        "id": f"osm:{element['type']}/{element['id']}",
        "kind": kind,
        "category": tags.get("tourism") if kind == "camping" else tags.get("amenity"),
        "name": tags["name"],
        "lat": round(plat, 5),
        "lon": round(plon, 5),
        "distance_mi": round(distance_mi, 1),
        "facts": facts_of(kind, tags),
    }
    if tags.get("website"):
        place["website"] = tags["website"]
    place["_score"] = _score(kind, distance_mi, tags)
    return place


def candidates(elements: list[dict]) -> list[tuple[str, dict]]:
    """(kind, element) for each usable place, once each."""
    seen = set()
    out = []
    for element in elements:
        key = (element.get("type"), element.get("id"))
        tags = element.get("tags") or {}
        kind = kind_of(tags)
        if key in seen or kind is None or not usable(tags):
            continue
        if "lat" not in element and "center" not in element:
            continue
        seen.add(key)
        out.append((kind, element))
    return out


def ranked(found: list[tuple[str, dict]], kind: str, lat: float, lon: float, within_km: float) -> list[dict]:
    """The best PLACES_PER_GROUP places of this kind within within_km of the point."""
    places = [to_place(e, k, lat, lon) for k, e in found if k == kind]
    places = [p for p in places if p["distance_mi"] * KM_PER_MILE <= within_km + 0.05]
    places.sort(key=lambda p: p["_score"])
    return places[:PLACES_PER_GROUP]
