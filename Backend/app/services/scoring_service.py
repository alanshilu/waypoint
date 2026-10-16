"""
Scenic score: how much terrain a route crosses, on a 0-100 scale.

    density = (ascent_m + descent_m) / distance_miles      metres of climbing and descending per mile
    score   = 100 * density / (density + HALF_SCORE_DENSITY_M_PER_MILE)

HALF_SCORE_DENSITY_M_PER_MILE is the density that scores exactly 50. At 40 m/mi
the scale reads roughly like this (measured on routes this backend generated):

    ~10 m/mi   flat interstate                    score ~20
    ~25 m/mi   SF to LA on I-5 (Tejon Pass)       score ~38
    ~45 m/mi   SF to LA coastal backroads         score ~53
    100+ m/mi  sustained mountain driving         score 70+

The curve rises steeply for flat-to-rolling routes, where differences matter
most, and flattens for mountain routes, so the score stays inside 0-100
without clipping and never reaches 100. It is a relative, unitless value for
comparing routes; it is not a rating and should not be quoted "out of 100".

Speed is deliberately not part of the score. How much slower a route is gets
reported separately as duration_vs_fastest (see duration_ratios).
"""

HALF_SCORE_DENSITY_M_PER_MILE = 40.0


def terrain_density(distance_miles: float, ascent_m: float | None, descent_m: float | None) -> float:
    """Metres of ascent plus descent per mile. Missing elevation counts as zero."""
    distance = distance_miles if distance_miles and distance_miles > 0 else 1.0
    return ((ascent_m or 0) + (descent_m or 0)) / distance


def calculate_scenic_index(distance_miles: float, ascent_m: float | None, descent_m: float | None) -> float:
    """Terrain-only score in [0, 100); higher means hillier."""
    density = terrain_density(distance_miles, ascent_m, descent_m)
    return round(100 * density / (density + HALF_SCORE_DENSITY_M_PER_MILE), 1)


def duration_ratios(routes: dict) -> dict:
    """{route_type: duration / fastest duration}, 2 dp. Empty if there is no usable fastest route."""
    fastest = (routes.get("fastest") or {}).get("duration_seconds")
    if not fastest:
        return {}
    return {name: round(data["duration_seconds"] / fastest, 2) for name, data in routes.items()}


def score_route_options(routes_data: dict) -> dict:
    """
    Injects the terrain-only 'scenic_score' into each route dictionary.
    """
    for data in routes_data.values():
        data["scenic_score"] = calculate_scenic_index(
            distance_miles=data["distance_miles"],
            ascent_m=data.get("ascent_m"),
            descent_m=data.get("descent_m"),
        )

    return routes_data
