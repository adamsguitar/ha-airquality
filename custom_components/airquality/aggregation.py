"""Named aggregation strategies for combining multiple sensor readings into one value.

Phase 1 implements 'single'. All others raise NotImplementedError as placeholders
for Phase 2. The function signatures are final — only the bodies will be filled in.
"""
from __future__ import annotations

import logging
import statistics

_LOGGER = logging.getLogger(__name__)


def compute_single(values: list[float]) -> float | None:
    """Return the first value. Caller must ensure the list is non-empty."""
    return values[0] if values else None


def compute_average(values: list[float]) -> float | None:
    """Return the arithmetic mean."""
    return statistics.mean(values) if values else None


def compute_median(values: list[float]) -> float | None:
    """Return the median."""
    return statistics.median(values) if values else None


def compute_min(values: list[float]) -> float | None:
    """Return the minimum value."""
    return min(values) if values else None


def compute_max(values: list[float]) -> float | None:
    """Return the maximum value."""
    return max(values) if values else None


def compute_weighted_average(
    values: list[float], weights: list[float]
) -> float | None:
    """Return the weighted arithmetic mean."""
    if not values:
        return None
    if len(values) != len(weights):
        raise ValueError("values and weights must have the same length")
    total_weight = sum(weights)
    if total_weight == 0:
        return compute_average(values)
    return sum(v * w for v, w in zip(values, weights)) / total_weight


def compute_primary_with_fallback(values: list[float]) -> float | None:
    """Return the first value (priority order = list order in YAML)."""
    return values[0] if values else None


_STRATEGY_MAP = {
    "single": lambda values, _weights: compute_single(values),
    "average": lambda values, _weights: compute_average(values),
    "median": lambda values, _weights: compute_median(values),
    "min": lambda values, _weights: compute_min(values),
    "max": lambda values, _weights: compute_max(values),
    "weighted_average": lambda values, weights: compute_weighted_average(values, weights),
    "primary_with_fallback": lambda values, _weights: compute_primary_with_fallback(values),
}


def compute_aggregation(
    strategy: str,
    values: list[float],
    weights: list[float] | None = None,
) -> float | None:
    """Dispatch to the named aggregation strategy.

    Args:
        strategy: One of the AGGREGATION_* constants.
        values: Non-empty list of numeric sensor readings. Caller filters
                stale/unavailable values before calling this function.
        weights: Required for 'weighted_average'; ignored otherwise.

    Returns:
        The aggregated float value, or None if values is empty.
    """
    if not values:
        return None

    fn = _STRATEGY_MAP.get(strategy)
    if fn is None:
        raise ValueError(f"Unknown aggregation strategy: {strategy!r}")

    return fn(values, weights or [])
