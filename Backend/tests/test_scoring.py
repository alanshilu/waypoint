import pytest

from app.services.scoring_service import (
    HALF_SCORE_DENSITY_M_PER_MILE,
    calculate_scenic_index,
    duration_ratios,
    score_route_options,
)


def test_zero_distance_does_not_divide_by_zero():
    assert calculate_scenic_index(0, 100, 100) == calculate_scenic_index(1, 100, 100)
    assert calculate_scenic_index(-5, 0, 0) == 0


def test_null_elevation_scores_zero():
    assert calculate_scenic_index(250, None, None) == 0
    assert calculate_scenic_index(250, None, 500) == calculate_scenic_index(250, 0, 500)


@pytest.mark.parametrize("ascent", [0, 1, 50, 1_000, 10_000, 100_000, 10_000_000])
@pytest.mark.parametrize("miles", [0.1, 1, 30, 400, 3_000])
def test_score_stays_in_bounds(ascent, miles):
    score = calculate_scenic_index(miles, ascent, ascent)
    assert 0 <= score <= 100


def test_half_score_constant():
    # a route at exactly the reference density scores 50
    miles = 100
    total = HALF_SCORE_DENSITY_M_PER_MILE * miles
    assert calculate_scenic_index(miles, total / 2, total / 2) == 50


def test_hillier_scores_higher_and_flatter_lower():
    flat = calculate_scenic_index(383, 2_000, 2_000)      # ~10 m/mi
    rolling = calculate_scenic_index(383, 4_786, 4_786)   # ~25 m/mi
    mountain = calculate_scenic_index(383, 20_000, 20_000)
    assert flat < rolling < mountain


def test_duration_no_longer_moves_the_score():
    a = {"fastest": {"distance_miles": 383, "duration_seconds": 23_000, "ascent_m": 4_786, "descent_m": 4_786}}
    b = {"fastest": {"distance_miles": 383, "duration_seconds": 90_000, "ascent_m": 4_786, "descent_m": 4_786}}
    assert score_route_options(a)["fastest"]["scenic_score"] == score_route_options(b)["fastest"]["scenic_score"]


def test_slowness_is_reported_separately():
    routes = {
        "fastest": {"distance_miles": 383, "duration_seconds": 23_400, "ascent_m": 4_786, "descent_m": 4_700},
        "backroads": {"distance_miles": 421, "duration_seconds": 50_460, "ascent_m": 9_360, "descent_m": 9_300},
    }
    assert duration_ratios(routes) == {"fastest": 1.0, "backroads": 2.16}
    assert duration_ratios({"backroads": {"duration_seconds": 10}}) == {}
    assert "duration_vs_fastest" not in score_route_options(routes)["backroads"]
