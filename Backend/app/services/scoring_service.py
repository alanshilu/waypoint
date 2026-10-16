def calculate_scenic_index(distance_miles: float, duration_seconds: int, ascent_m: float, descent_m: float) -> float:
    """
    Calculates a single score where lower means faster/flatter 
    and higher means scenic/curvy/mountainous.
    """
    # Prevent division by zero on microscopic routes
    distance = distance_miles if distance_miles > 0 else 1.0
    
    # 1. How hilly is it? (Meters of elevation change per mile)
    total_elevation = (ascent_m or 0) + (descent_m or 0)
    elevation_density = total_elevation / distance
    
    # 2. How slow is the drive? (Seconds per mile)
    pace = duration_seconds / distance
    
    # Combine the metrics. 
    # We multiply pace by 0.5 just to keep the final score numbers 
    # readable (usually landing between 30 and 150).
    raw_score = elevation_density + (pace * 0.5)
    
    return round(raw_score, 1)

def score_route_options(routes_data: dict) -> dict:
    """
    Injects the 'scenic_score' into each route dictionary.
    """
    for route_name, data in routes_data.items():
        data["scenic_score"] = calculate_scenic_index(
            distance_miles=data["distance_miles"],
            duration_seconds=data["duration_seconds"],
            ascent_m=data.get("ascent_m", 0),
            descent_m=data.get("descent_m", 0)
        )
        
    return routes_data