"""Tests for health evaluation and rollup logic."""
from __future__ import annotations

import pytest

from custom_components.airquality.const import (
    HEALTH_FAIR,
    HEALTH_GOOD,
    HEALTH_HAZARDOUS,
    HEALTH_POOR,
    HEALTH_STALE,
    HEALTH_UNAVAILABLE,
    HEALTH_UNHEALTHY,
)
from custom_components.airquality.health import (
    evaluate_range_threshold,
    evaluate_simple_threshold,
    evaluate_slot_health,
    is_problem,
    rollup_health,
)


# --- evaluate_simple_threshold (pollutants) ---

@pytest.fixture
def co2_profile() -> dict:
    return {"co2": {"good": 800, "fair": 1000, "poor": 1500, "unhealthy": 2500}}


def test_simple_threshold_good(co2_profile):
    assert evaluate_simple_threshold("co2", 500, co2_profile) == HEALTH_GOOD
    assert evaluate_simple_threshold("co2", 800, co2_profile) == HEALTH_GOOD


def test_simple_threshold_fair(co2_profile):
    assert evaluate_simple_threshold("co2", 900, co2_profile) == HEALTH_FAIR


def test_simple_threshold_poor(co2_profile):
    assert evaluate_simple_threshold("co2", 1200, co2_profile) == HEALTH_POOR


def test_simple_threshold_unhealthy(co2_profile):
    assert evaluate_simple_threshold("co2", 2000, co2_profile) == HEALTH_UNHEALTHY


def test_simple_threshold_hazardous(co2_profile):
    assert evaluate_simple_threshold("co2", 5000, co2_profile) == HEALTH_HAZARDOUS


def test_simple_threshold_missing_returns_unavailable():
    assert evaluate_simple_threshold("co2", 800, {}) == HEALTH_UNAVAILABLE


# --- evaluate_range_threshold (comfort parameters) ---

@pytest.fixture
def humidity_profile() -> dict:
    return {
        "humidity": {"good_min": 30, "good_max": 60, "fair_min": 25, "fair_max": 65}
    }


def test_range_threshold_good(humidity_profile):
    assert evaluate_range_threshold("humidity", 45, humidity_profile) == HEALTH_GOOD
    assert evaluate_range_threshold("humidity", 30, humidity_profile) == HEALTH_GOOD
    assert evaluate_range_threshold("humidity", 60, humidity_profile) == HEALTH_GOOD


def test_range_threshold_fair_below_good(humidity_profile):
    assert evaluate_range_threshold("humidity", 27, humidity_profile) == HEALTH_FAIR


def test_range_threshold_fair_above_good(humidity_profile):
    assert evaluate_range_threshold("humidity", 63, humidity_profile) == HEALTH_FAIR


def test_range_threshold_poor_below(humidity_profile):
    assert evaluate_range_threshold("humidity", 10, humidity_profile) == HEALTH_POOR


def test_range_threshold_poor_above(humidity_profile):
    assert evaluate_range_threshold("humidity", 80, humidity_profile) == HEALTH_POOR


def test_range_threshold_missing_returns_unavailable():
    assert evaluate_range_threshold("humidity", 50, {}) == HEALTH_UNAVAILABLE


# --- evaluate_slot_health routing ---

def test_evaluate_slot_health_routes_humidity_to_range(humidity_profile):
    assert evaluate_slot_health("humidity", 50, humidity_profile) == HEALTH_GOOD


def test_evaluate_slot_health_routes_temperature_f_to_range():
    profile = {"temperature_f": {"good_min": 68, "good_max": 76, "fair_min": 65, "fair_max": 80}}
    assert evaluate_slot_health("temperature_f", 72, profile) == HEALTH_GOOD


def test_evaluate_slot_health_routes_co2_to_simple(co2_profile):
    assert evaluate_slot_health("co2", 1200, co2_profile) == HEALTH_POOR


def test_evaluate_slot_health_routes_pm25_to_simple():
    profile = {"pm25": {"good": 12, "fair": 35, "poor": 55, "unhealthy": 150}}
    assert evaluate_slot_health("pm25", 200, profile) == HEALTH_HAZARDOUS


# --- rollup_health ---

def test_rollup_returns_worst_active():
    assert rollup_health([HEALTH_GOOD, HEALTH_FAIR, HEALTH_POOR]) == HEALTH_POOR


def test_rollup_ignores_stale_when_active_states_present():
    assert rollup_health([HEALTH_GOOD, HEALTH_STALE]) == HEALTH_GOOD


def test_rollup_ignores_unavailable_when_active_states_present():
    assert rollup_health([HEALTH_GOOD, HEALTH_UNAVAILABLE]) == HEALTH_GOOD


def test_rollup_dead_sensor_does_not_cascade():
    """A single dead sensor in a healthy room must not propagate to home."""
    assert rollup_health([HEALTH_GOOD, HEALTH_GOOD, HEALTH_UNAVAILABLE]) == HEALTH_GOOD


def test_rollup_all_stale_returns_stale():
    assert rollup_health([HEALTH_STALE, HEALTH_STALE]) == HEALTH_STALE


def test_rollup_all_unavailable_returns_unavailable():
    assert rollup_health([HEALTH_UNAVAILABLE, HEALTH_UNAVAILABLE]) == HEALTH_UNAVAILABLE


def test_rollup_empty_returns_unavailable():
    assert rollup_health([]) == HEALTH_UNAVAILABLE


def test_rollup_hazardous_dominates():
    assert rollup_health([HEALTH_GOOD, HEALTH_FAIR, HEALTH_HAZARDOUS]) == HEALTH_HAZARDOUS


# --- is_problem ---

def test_is_problem_true_for_poor_and_worse():
    assert is_problem(HEALTH_POOR) is True
    assert is_problem(HEALTH_UNHEALTHY) is True
    assert is_problem(HEALTH_HAZARDOUS) is True


def test_is_problem_false_for_good_and_fair():
    assert is_problem(HEALTH_GOOD) is False
    assert is_problem(HEALTH_FAIR) is False


def test_is_problem_false_for_stale_and_unavailable():
    assert is_problem(HEALTH_STALE) is False
    assert is_problem(HEALTH_UNAVAILABLE) is False
