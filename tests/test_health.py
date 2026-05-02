"""Tests for health rollup logic."""
from __future__ import annotations

from custom_components.airquality.health import rollup_health
from custom_components.airquality.const import (
    HEALTH_GOOD,
    HEALTH_FAIR,
    HEALTH_POOR,
    HEALTH_UNHEALTHY,
    HEALTH_STALE,
    HEALTH_UNAVAILABLE,
)


def test_rollup_returns_worst_active():
    assert rollup_health([HEALTH_GOOD, HEALTH_FAIR, HEALTH_POOR]) == HEALTH_POOR


def test_rollup_ignores_stale_when_active_states_present():
    assert rollup_health([HEALTH_GOOD, HEALTH_STALE]) == HEALTH_GOOD


def test_rollup_ignores_unavailable_when_active_states_present():
    assert rollup_health([HEALTH_GOOD, HEALTH_UNAVAILABLE]) == HEALTH_GOOD


def test_rollup_all_stale_returns_stale():
    assert rollup_health([HEALTH_STALE, HEALTH_STALE]) == HEALTH_STALE


def test_rollup_all_unavailable_returns_unavailable():
    assert rollup_health([HEALTH_UNAVAILABLE, HEALTH_UNAVAILABLE]) == HEALTH_UNAVAILABLE


def test_rollup_stale_worse_than_unavailable():
    # Per severity index, unavailable > stale — both excluded from rollup,
    # so the dominant one is returned.
    result = rollup_health([HEALTH_STALE, HEALTH_UNAVAILABLE])
    assert result == HEALTH_UNAVAILABLE


def test_rollup_empty_returns_unavailable():
    assert rollup_health([]) == HEALTH_UNAVAILABLE
