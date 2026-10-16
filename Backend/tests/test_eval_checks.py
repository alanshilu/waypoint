"""The eval checks themselves, on synthetic sessions (no model or backend calls)."""

from types import SimpleNamespace

from evals.checks import (
    Session,
    TurnRecord,
    concise_reply,
    no_duplicate_work,
    no_invented_scale,
    numeric_grounding,
    poi_coords_grounded,
    stops_grounded,
    weather_on_arrival_dates,
)


def step(tool, args, result=None, error=None, cached=False):
    return SimpleNamespace(tool=tool, args=args, full_result=result, error=error, cached=cached)


GEO_AUSTIN = step("geocode_location", {"query": "Austin"}, {"label": "Austin, Texas, United States", "lat": 30.27, "lon": -97.74})
GEO_SF = step("geocode_location", {"query": "SF"}, {"label": "San Francisco, California, United States", "lat": 37.78, "lon": -122.43})
TRIP = step("create_trip", {"name": "x", "origin_label": "Austin", "origin_lat": 30.27, "origin_lon": -97.74,
                            "destination_label": "SF", "destination_lat": 37.78, "destination_lon": -122.43},
            {"trip_id": 11})
ROUTES = step("generate_routes", {"trip_id": 11}, {"routes": [
    {"id": 1, "route_type": "fastest", "distance_miles": 1753.8, "duration_seconds": 99180, "ascent_m": 9000.0,
     "descent_m": 9200.0, "scenic_score": 21.3,
     "geometry": {"type": "LineString", "coordinates": [[-97.74, 30.27], [-106.44, 31.76], [-122.43, 37.78]]}},
    {"id": 2, "route_type": "backroads", "distance_miles": 1739.0, "duration_seconds": 130000, "ascent_m": 14000.0,
     "descent_m": 14100.0, "scenic_score": 28.9,
     "geometry": {"type": "LineString", "coordinates": [[-97.74, 30.27], [-122.43, 37.78]]}},
]})
PLAN = step("plan_stops", {"trip_id": 11, "route_id": 1, "start": "2026-10-17T08:00:00-05:00"}, {
    "start": "2026-10-17T08:00:00-05:00",
    "stops": [
        {"id": "1:1", "day": 1, "kind": "overnight", "name": "Fort Stockton, Texas, United States", "lat": 30.89,
         "lon": -102.88, "cumulative_miles": 320.0, "cumulative_drive_hours": 8.0, "arrival_date": "2026-10-17",
         "forecast": {"date": "2026-10-17", "temp_max": 88.0, "temp_min": 60.1, "precip_probability": 0, "condition": "Clear sky"}},
        {"id": "1:dest", "day": 4, "kind": "destination", "name": "San Francisco, California, United States",
         "lat": 37.78, "lon": -122.43, "cumulative_miles": 1753.8, "cumulative_drive_hours": 27.55,
         "arrival_date": "2026-10-20", "forecast": None},
    ],
})
BASE_STEPS = [GEO_AUSTIN, GEO_SF, TRIP, ROUTES]


def session(reply, steps, prompt="Austin to SF", final_answer=None):
    return Session("t", [TurnRecord(prompt, reply, final_answer, steps)])


# a. numeric_grounding

def test_numeric_grounded_values_pass():
    reply = "The fastest route is 1,754 miles and takes about 27h 33m; backroads is 15 miles shorter."
    assert numeric_grounding(session(reply, BASE_STEPS)).passed


def test_numeric_invented_number_fails():
    r = numeric_grounding(session("Plan on about 5 hours a day and 4 nights.", BASE_STEPS))
    assert not r.passed
    assert any("5 hours" in e for e in r.evidence)
    assert any("'4'" in e for e in r.evidence)


def test_numeric_ratio_derivation_passes():
    # 14000 / 9000 = 1.56
    assert numeric_grounding(session("Backroads has 1.6x the climbing.", BASE_STEPS)).passed


def test_numeric_dates_must_come_from_results():
    ok = numeric_grounding(session("You arrive on Oct 20.", [*BASE_STEPS, PLAN]))
    bad = numeric_grounding(session("You arrive on Oct 22.", [*BASE_STEPS, PLAN]))
    assert ok.passed and not bad.passed


def test_numeric_clock_time_must_be_in_a_result():
    plan = step("plan_stops", PLAN.args, {**PLAN.full_result, "stops": [
        {**PLAN.full_result["stops"][0], "arrival_time": "2026-10-17T16:00-05:00"}]})
    assert numeric_grounding(session("Leave at 8 AM, stop around 16:00.", [*BASE_STEPS, plan])).passed
    assert not numeric_grounding(session("Leave at 6 AM.", [*BASE_STEPS, plan])).passed


def test_plain_sentence_start_is_not_a_list_lead():
    assert stops_grounded(session("Leave Sunday, October 18, on the fastest route.", BASE_STEPS)).passed


def test_numeric_ids_only_ground_when_written_as_ids():
    assert numeric_grounding(session("Trip #11 uses route 2.", BASE_STEPS)).passed
    assert not numeric_grounding(session("It is about 11 miles shorter.", BASE_STEPS)).passed


def test_numeric_road_names_ignored():
    assert numeric_grounding(session("Take I-10 then US-101.", BASE_STEPS)).passed


# b. no_invented_scale

def test_scale_patterns():
    assert not no_invented_scale(session("Scenic score: 46.5 / 100", BASE_STEPS)).passed
    assert not no_invented_scale(session("It rates 7 out of 10.", BASE_STEPS)).passed
    assert no_invented_scale(session("Backroads scores 28.9 versus 21.3.", BASE_STEPS)).passed


# c. stops_grounded

def test_invented_overnight_stop_fails():
    r = stops_grounded(session("Stop overnight in El Paso, then Phoenix.", BASE_STEPS))
    assert not r.passed and any("El Paso" in e for e in r.evidence)


def test_planned_stop_passes():
    assert stops_grounded(session("Stay overnight in Fort Stockton.", [*BASE_STEPS, PLAN])).passed


def test_final_answer_stop_ids_must_exist():
    fa = {"stops": ["1:1", "9:9"]}
    r = stops_grounded(session("Done.", [*BASE_STEPS, PLAN], final_answer=fa))
    assert not r.passed and any("9:9" in e for e in r.evidence)


def test_list_item_places_are_checked():
    pois = step("search_pois", {"lat": 37.0, "lon": -121.56}, {"pois": [{"id": 5, "name": "Sandy's Cafe", "category": "cafe"}]})
    reply = (
        "**Stops along the backroads route**\n"
        "- **Gilroy, about 80 miles in:** best place for a meal.\n"
        "  - Food: Sandy's Cafe\n"
        "- **Lebec / Grapevine area:** fuel.\n"
    )
    r = stops_grounded(session(reply, [*BASE_STEPS, pois]))
    flagged = " ".join(r.evidence)
    assert "Gilroy" in flagged and "Lebec" in flagged
    assert "'Food'" not in flagged and "'Stops" not in flagged


def test_lowercase_phrases_are_not_places():
    assert stops_grounded(session("I can search for stops at other points on the route.", BASE_STEPS)).passed


def test_bold_labels_are_not_places_but_leads_with_detail_are():
    reply = "**Tradeoff:** slower.\n- **Dinner:** tacos\n- **Hollister (about mile 100):** food\n"
    r = stops_grounded(session(reply, BASE_STEPS))
    flagged = " ".join(r.evidence)
    assert "Hollister" in flagged
    assert "Tradeoff" not in flagged and "Dinner" not in flagged


def test_list_items_are_not_joined_across_lines():
    pois = step("search_pois", {"lat": 36.19, "lon": -115.28},
                {"pois": [{"id": 1, "name": "Burger King", "category": "fast_food"},
                          {"id": 2, "name": "Tomoya Japanese Cuisine", "category": "restaurant"}]})
    reply = "- Burger King\n\nTomoya, Pierogi Village and Port of Subs sit next to each other."
    assert stops_grounded(session(reply, [*BASE_STEPS, pois])).passed


def test_impossible_slash_dates_are_not_dates():
    r = numeric_grounding(session("Slater's 50/50 is nearby.", BASE_STEPS))
    assert not any("date" in e for e in r.evidence)


def test_the_before_a_place_is_skipped():
    r = stops_grounded(session("I'd stop overnight in the Omaha, NE area.", BASE_STEPS))
    assert any("Omaha" in e for e in r.evidence)


# d. weather_on_arrival_dates

def test_undated_destination_weather_fails():
    wx = step("get_weather_forecast", {"lat": 37.78, "lon": -122.43}, {"forecast": []})
    assert not weather_on_arrival_dates(session("SF looks clear.", [*BASE_STEPS, wx])).passed


def test_dated_stop_weather_passes():
    wx = step("get_weather_forecast", {"lat": 37.78, "lon": -122.43, "target_date": "2026-10-20"}, {"date": "2026-10-20"})
    assert weather_on_arrival_dates(session("SF looks clear on arrival.", [*BASE_STEPS, PLAN, wx])).passed


def test_wrong_date_fails():
    wx = step("get_weather_forecast", {"lat": 37.78, "lon": -122.43, "target_date": "2026-10-17"}, {"date": "2026-10-17"})
    assert not weather_on_arrival_dates(session("Clear.", [*BASE_STEPS, PLAN, wx])).passed


def test_weather_talk_without_source_fails():
    assert not weather_on_arrival_dates(session("Expect rain in San Francisco.", BASE_STEPS)).passed
    assert not weather_on_arrival_dates(session("Highs near 80 degrees.", BASE_STEPS)).passed
    # an offer to check is not a weather claim
    assert weather_on_arrival_dates(session("I can also check the weather along the way.", BASE_STEPS)).passed


# e. poi_coords_grounded

def test_poi_near_route_passes_and_far_fails():
    near = step("search_pois", {"lat": 31.76, "lon": -106.40}, {"pois": []})  # on the fastest line near El Paso
    far = step("search_pois", {"lat": 34.05, "lon": -118.24}, {"pois": []})  # Los Angeles, from nowhere
    assert poi_coords_grounded(session("x", [*BASE_STEPS, near])).passed
    assert not poi_coords_grounded(session("x", [*BASE_STEPS, far])).passed


# f. no_duplicate_work

def test_duplicate_trip_fails_and_cached_repeat_passes():
    assert not no_duplicate_work(session("x", [*BASE_STEPS, TRIP])).passed
    cached = step("generate_routes", {"trip_id": 11}, ROUTES.full_result, cached=True)
    assert no_duplicate_work(session("x", [*BASE_STEPS, cached])).passed


# g. concise_reply (judge stubbed)

def test_concise_needs_judge_and_counts_to_agree():
    def yes(_):
        return {"pass": True, "reason": "ok"}

    assert concise_reply(session("Short and plain.", BASE_STEPS), yes).passed
    assert not concise_reply(session("Great trip! \U0001F697", BASE_STEPS), yes).passed
    assert not concise_reply(session("| a | b |\n| - | - |\n| 1 | 2 |", BASE_STEPS), yes).passed
    assert not concise_reply(session("word " * 200, BASE_STEPS), yes).passed
