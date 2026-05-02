"""Health evaluation: threshold comparison and worst-state rollup.

Phase 1 stubs — function signatures are final; logic lands in Phase 2.
Phase 1 sensors return health state 'unavailable' (i.e. no health sensor yet).
"""
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


def evaluate_simple_threshold(measurement: str, value: float, profile: dict) -> str:
    """Return the health band for a pollutant using simple (monotonic) thresholds.

    Phase 2 implementation.
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

    Phase 2 implementation.
    """
    thresholds = profile.get(measurement)
    if thresholds is None:
        return HEALTH_UNAVAILABLE

    if thresholds["good_min"] <= value <= thresholds["good_max"]:
        return HEALTH_GOOD
    if thresholds["fair_min"] <= value <= thresholds["fair_max"]:
        return HEALTH_FAIR
    return HEALTH_POOR


_RANGE_MEASUREMENTS = {
    "temperature",
    "temperature_f",
    "temperature_c",
    "humidity",
}


def evaluate_slot_health(measurement: str, value: float, profile: dict) -> str:
    """Return health state string for a slot value against a resolved threshold profile.

    Phase 1: always returns HEALTH_UNAVAILABLE (health sensors are Phase 2).
    Phase 2 will route to evaluate_simple_threshold or evaluate_range_threshold.
    """
    # Phase 2: remove the early return and route properly.
    return HEALTH_UNAVAILABLE


def rollup_health(health_states: list[str]) -> str:
    """Compute worst-state rollup across a list of health states.

    Policy (per design): stale/unavailable are excluded from the rollup unless
    *all* inputs are stale/unavailable, in which case the dominant excluded state
    is returned. This prevents a dead sensor from cascading to home health.
    """
    if not health_states:
        return HEALTH_UNAVAILABLE

    active = [s for s in health_states if s not in _EXCLUDED_FROM_ROLLUP]
    if active:
        return max(active, key=lambda s: _SEVERITY_INDEX.get(s, 0))

    # All states are stale or unavailable — return the dominant excluded state.
    return max(health_states, key=lambda s: _SEVERITY_INDEX.get(s, 0))
