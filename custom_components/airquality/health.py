"""Health evaluation: threshold comparison and worst-state rollup."""
from __future__ import annotations

import logging

from .const import (
    HEALTH_FAIR,
    HEALTH_GOOD,
    HEALTH_HAZARDOUS,
    HEALTH_POOR,
    HEALTH_STALE,
    HEALTH_UNAVAILABLE,
    HEALTH_UNHEALTHY,
)

_LOGGER = logging.getLogger(__name__)

# Severity order for rollup. Higher index = worse.
_SEVERITY = [
    HEALTH_GOOD,
    HEALTH_FAIR,
    HEALTH_POOR,
    HEALTH_UNHEALTHY,
    HEALTH_HAZARDOUS,
    HEALTH_STALE,
    HEALTH_UNAVAILABLE,
]
_SEVERITY_INDEX = {state: i for i, state in enumerate(_SEVERITY)}

# States excluded from worst-state rollup unless ALL inputs share them.
_EXCLUDED_FROM_ROLLUP = {HEALTH_STALE, HEALTH_UNAVAILABLE}

# Measurement types evaluated as a comfort range (good_min/good_max/...).
# All other measurements use simple monotonic thresholds (good < fair < poor < unhealthy).
_RANGE_MEASUREMENTS = {
    "temperature",
    "temperature_f",
    "temperature_c",
    "humidity",
}


def evaluate_simple_threshold(measurement: str, value: float, profile: dict) -> str:
    """Return the health band for a pollutant using simple (monotonic) thresholds.

    Bands above 'unhealthy' map to 'hazardous'.
    """
    thresholds = profile.get(measurement)
    if thresholds is None:
        return HEALTH_UNAVAILABLE

    if value <= thresholds["good"]:
        return HEALTH_GOOD
    if value <= thresholds["fair"]:
        return HEALTH_FAIR
    if value <= thresholds["poor"]:
        return HEALTH_POOR
    if value <= thresholds["unhealthy"]:
        return HEALTH_UNHEALTHY
    return HEALTH_HAZARDOUS


def evaluate_range_threshold(measurement: str, value: float, profile: dict) -> str:
    """Return the health band for a comfort parameter using range thresholds.

    Inside good_min..good_max: GOOD.
    Inside fair_min..fair_max (but outside good): FAIR.
    Outside fair range: POOR.
    """
    thresholds = profile.get(measurement)
    if thresholds is None:
        return HEALTH_UNAVAILABLE

    if thresholds["good_min"] <= value <= thresholds["good_max"]:
        return HEALTH_GOOD
    if thresholds["fair_min"] <= value <= thresholds["fair_max"]:
        return HEALTH_FAIR
    return HEALTH_POOR


def evaluate_slot_health(measurement: str, value: float, profile: dict) -> str:
    """Return health state string for a slot value against a resolved threshold profile.

    Routes to range or simple evaluator based on measurement type.
    """
    if measurement in _RANGE_MEASUREMENTS:
        return evaluate_range_threshold(measurement, value, profile)
    return evaluate_simple_threshold(measurement, value, profile)


def rollup_health(health_states: list[str]) -> str:
    """Compute worst-state rollup across a list of health states.

    Policy: stale/unavailable are excluded from the rollup unless *all* inputs are
    stale/unavailable, in which case the dominant excluded state is returned.
    This prevents a dead sensor from cascading to home health.
    """
    if not health_states:
        return HEALTH_UNAVAILABLE

    active = [s for s in health_states if s not in _EXCLUDED_FROM_ROLLUP]
    if active:
        return max(active, key=lambda s: _SEVERITY_INDEX.get(s, 0))

    # All states are stale or unavailable — return the dominant excluded state.
    return max(health_states, key=lambda s: _SEVERITY_INDEX.get(s, 0))


def is_problem(health: str) -> bool:
    """Return True if a health state should trigger a 'problem' binary sensor.

    Threshold for 'problem' is poor or worse. Stale/unavailable are not problems
    in themselves — that's a sensor health concern, not air quality.
    """
    if health in _EXCLUDED_FROM_ROLLUP:
        return False
    return _SEVERITY_INDEX.get(health, 0) >= _SEVERITY_INDEX[HEALTH_POOR]


def slot_draws_dashboard_attention(health: str) -> bool:
    """True when a slot should be called out on the managed Lovelace dashboard."""
    return health not in (HEALTH_GOOD, HEALTH_FAIR)
