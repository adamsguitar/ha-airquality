"""Authoritative reference thresholds aligned with integration discovery defaults.

Discovery embeds the same numbers in `render_yaml` (EPA AQI breakpoints for PM,
comfort-oriented CO₂ and VOC ppb, indoor humidity and temperature bands).
"""

from __future__ import annotations

from typing import Any

_SIMPLE_KEYS = ("good", "fair", "poor", "unhealthy")
_RANGE_KEYS = ("good_min", "good_max", "fair_min", "fair_max")

_REFERENCE_SIMPLE: dict[str, dict[str, Any]] = {
    "pm25": {
        "caption": (
            "EPA Air Quality Index breakpoints for PM2.5 (24h average, µg/m³) — "
            "same bands as the discovery wizard default profile."
        ),
        "values": {"good": 12, "fair": 35, "poor": 55, "unhealthy": 150},
        "unit": "µg/m³",
    },
    "pm10": {
        "caption": (
            "EPA Air Quality Index breakpoints for PM10 (24h average, µg/m³) — "
            "discovery default profile."
        ),
        "values": {"good": 54, "fair": 154, "poor": 254, "unhealthy": 354},
        "unit": "µg/m³",
    },
    "co2": {
        "caption": (
            "CO₂ ppm bands oriented on typical indoor targets (discovery default: "
            "~ASHRAE / high-ventilation comfort framing)."
        ),
        "values": {"good": 800, "fair": 1000, "poor": 1500, "unhealthy": 2500},
        "unit": "ppm",
    },
    "voc": {
        "caption": (
            "VOC in ppb — discovery uses rounded indoor targets; your sensor must "
            "report volatile_organic_compounds_parts."
        ),
        "values": {"good": 250, "fair": 500, "poor": 1000, "unhealthy": 2000},
        "unit": "ppb",
    },
    "no2": {
        "caption": (
            "NO₂ breakpoints (µg/m³, illustrative indoor targets — adjust to your guideline)."
        ),
        "values": {"good": 20, "fair": 40, "poor": 100, "unhealthy": 200},
        "unit": "µg/m³",
    },
    "o3": {
        "caption": (
            "O₃ breakpoints (µg/m³, illustrative indoor targets — adjust to your guideline)."
        ),
        "values": {"good": 50, "fair": 100, "poor": 160, "unhealthy": 240},
        "unit": "µg/m³",
    },
    "radon": {
        "caption": (
            "Radon breakpoints (Bq/m³, illustrative — many regions use separate action levels)."
        ),
        "values": {"good": 50, "fair": 100, "poor": 200, "unhealthy": 300},
        "unit": "Bq/m³",
    },
}

_REFERENCE_RANGE: dict[str, dict[str, Any]] = {
    "humidity": {
        "caption": (
            "Relative humidity % — good band inside fair band (discovery default comfort range)."
        ),
        "values": {"good_min": 30, "good_max": 60, "fair_min": 25, "fair_max": 65},
        "unit": "%",
    },
    "temperature_f": {
        "caption": "Indoor comfort range °F — discovery default.",
        "values": {"good_min": 68, "good_max": 76, "fair_min": 65, "fair_max": 80},
        "unit": "°F",
    },
    "temperature_c": {
        "caption": "Indoor comfort range °C — discovery default.",
        "values": {"good_min": 20, "good_max": 24, "fair_min": 18, "fair_max": 27},
        "unit": "°C",
    },
}


def measurement_reference(measurement: str) -> dict[str, Any] | None:
    """Return caption, unit, and values dict for sliders, or None if not defined."""
    if measurement in _REFERENCE_SIMPLE:
        return _REFERENCE_SIMPLE[measurement]
    if measurement in _REFERENCE_RANGE:
        return _REFERENCE_RANGE[measurement]
    if measurement == "temperature":
        return {
            "caption": (
                "Generic temperature key — prefer temperature_f or temperature_c in YAML. "
                "Reference shown is the °C discovery band for comparison."
            ),
            "values": dict(_REFERENCE_RANGE["temperature_c"]["values"]),
            "unit": _REFERENCE_RANGE["temperature_c"]["unit"],
        }
    return None


def default_profile_dict() -> dict[str, dict[str, float]]:
    """Default profile: discovery pollutants + ranges + illustrative no2/o3/radon."""
    out: dict[str, dict[str, float]] = {}
    for m, spec in _REFERENCE_SIMPLE.items():
        out[m] = dict(spec["values"])
    for m, spec in _REFERENCE_RANGE.items():
        out[m] = dict(spec["values"])
    return out


def all_schema_measurements() -> tuple[list[str], list[str]]:
    """Simple (monotonic) keys and range keys per JSON schema."""
    simple = ["pm25", "pm10", "co2", "voc", "no2", "o3", "radon"]
    range_m = ["temperature", "temperature_f", "temperature_c", "humidity"]
    return simple, range_m


def slider_min_max_simple(user: dict[str, float], ref: dict[str, float]) -> tuple[float, float]:
    values = [*user.values(), *ref.values()]
    lo, hi = min(values), max(values)
    span = hi - lo
    pad = max(span * 0.2, 1e-6)
    lo_n = lo - pad
    hi_n = hi + pad
    return lo_n, hi_n


def slider_min_max_range(user: dict[str, float], ref: dict[str, float]) -> tuple[float, float]:
    values = [*user.values(), *ref.values()]
    lo, hi = min(values), max(values)
    span = hi - lo
    pad = max(span * 0.15, 0.5)
    return lo - pad, hi + pad


def pct_on_span(value: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 50.0
    return max(0.0, min(100.0, 100.0 * (value - lo) / (hi - lo)))
