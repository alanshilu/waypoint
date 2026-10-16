import requests
import requests

BASE_URL = "http://localhost:8000"

def test_agent_workflow():
    print("--- STARTING E2E WORKFLOW TEST ---")

    # 1. Geocode Locations
    print("\n1. Geocoding Origin and Destination...")
    origin_res = requests.get(f"{BASE_URL}/location/search", params={"q": "San Francisco, CA"})
    dest_res = requests.get(f"{BASE_URL}/location/search", params={"q": "Yosemite Valley, CA"})
    origin_res.raise_for_status()
    dest_res.raise_for_status()
    
    # Assuming the first result is the most accurate
    origin = origin_res.json()["results"][0]
    dest = dest_res.json()["results"][0]
    print(f"Found Origin: {origin['label']} ({origin['lat']}, {origin['lon']})")
    print(f"Found Destination: {dest['label']} ({dest['lat']}, {dest['lon']})")

    print("\n2. Creating Trip in Database...")
    trip_payload = {
        "name": "Backend Test Trip",
        "origin_name": origin["label"],
        "origin_lon": origin["lon"],
        "origin_lat": origin["lat"],
        "destination_name": dest["label"],
        "destination_lon": dest["lon"],
        "destination_lat": dest["lat"]
    }
    trip_res = requests.post(f"{BASE_URL}/trips/", json=trip_payload)
    trip_res.raise_for_status()
    trip_id = trip_res.json()["trip_id"]
    print(f"Success! Created Trip ID: {trip_id}")

    # 3. Generate Routes
    print("\n3. Generating Routes via ORS...")
    gen_res = requests.post(f"{BASE_URL}/routes/generate/{trip_id}")
    gen_res.raise_for_status()
    routes = gen_res.json()["routes"]
    print(f"Generated {len(routes)} route candidates.")

    # 4. Select a Route
    if routes:
        selected_route_id = routes[0]["id"]
        print(f"\n4. Selecting Route ID {selected_route_id}...")
        select_res = requests.post(f"{BASE_URL}/routes/select/{selected_route_id}")
        select_res.raise_for_status()
        print(select_res.json()["message"])

    
    # 5. Fetch POIs (campsites, fuel, hotels, and other road-trip stops)
    print("\n5. Searching for POIs...")
    # Creating a small bounding box around Yosemite
    poi_params = {
        "lon": dest["lon"],
        "lat": dest["lat"]
    }
    poi_res = requests.get(f"{BASE_URL}/pois/search", params=poi_params)
    poi_res.raise_for_status()
    print(f"Found {poi_res.json().get('count', 0)} POIs in the area.")

    # 3. Check Weather
    print("\n3. Fetching Weather Forecast...")
    weather_res = requests.get(f"{BASE_URL}/weather/forecast?lat={dest['lat']}&lon={dest['lon']}")
    weather_res.raise_for_status()
    forecast = weather_res.json()["forecast"]
    tomorrow = forecast[1] if len(forecast) > 1 else forecast[0]
    print(f"Weather: {tomorrow['condition']}, High of {tomorrow['temp_max']}F")

    print("\n--- TEST COMPLETE ---")

if __name__ == "__main__":
    test_agent_workflow()