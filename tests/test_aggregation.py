"""Tests for the aggregation module."""
from __future__ import annotations

import pytest

from custom_components.airquality.aggregation import compute_aggregation


def test_single():
    assert compute_aggregation("single", [42.0]) == 42.0
    assert compute_aggregation("single", [1.0, 2.0, 3.0]) == 1.0


def test_average():
    assert compute_aggregation("average", [10.0, 20.0, 30.0]) == 20.0


def test_median():
    assert compute_aggregation("median", [1.0, 3.0, 2.0]) == 2.0


def test_min():
    assert compute_aggregation("min", [5.0, 1.0, 3.0]) == 1.0


def test_max():
    assert compute_aggregation("max", [5.0, 1.0, 3.0]) == 5.0


def test_weighted_average():
    result = compute_aggregation("weighted_average", [10.0, 20.0], [1.0, 3.0])
    assert result == pytest.approx(17.5)


def test_primary_with_fallback():
    assert compute_aggregation("primary_with_fallback", [99.0, 1.0]) == 99.0


def test_empty_values_returns_none():
    for strategy in ("single", "average", "median", "min", "max", "primary_with_fallback"):
        assert compute_aggregation(strategy, []) is None


def test_unknown_strategy_raises():
    with pytest.raises(ValueError, match="Unknown aggregation strategy"):
        compute_aggregation("magic", [1.0])
