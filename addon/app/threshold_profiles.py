"""Resolve threshold profile inheritance and validate threshold ordering."""

from __future__ import annotations

from typing import Any


def resolve_profile_inheritance(profiles: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Flatten profiles the same way as integration yaml_loader (single extends, shallow merge)."""

    resolved: dict[str, dict[str, Any]] = {}

    def resolve(name: str, seen: set[str]) -> dict[str, Any]:
        if name in resolved:
            return resolved[name]
        if name in seen:
            raise ValueError(f"Circular threshold_profile inheritance involving {name!r}.")
        raw = profiles.get(name, {})
        parent_name = raw.get("extends")
        if parent_name:
            parent = resolve(str(parent_name), seen | {name})
            merged = {k: v for k, v in parent.items()}
            merged.update({k: v for k, v in raw.items() if k != "extends"})
        else:
            merged = {k: v for k, v in raw.items() if k != "extends"}
        resolved[name] = merged
        return merged

    for name in profiles:
        resolve(name, set())
    return resolved


def validate_simple_monotonic(values: dict[str, float]) -> list[str]:
    keys = ["good", "fair", "poor", "unhealthy"]
    nums = [values.get(k) for k in keys]
    if any(n is None for n in nums):
        return [f"Missing simple threshold key(s); expected {keys}."]
    g, f, p, u = nums
    errs: list[str] = []
    if g > f:
        errs.append("good must be ≤ fair.")
    if f > p:
        errs.append("fair must be ≤ poor.")
    if p > u:
        errs.append("poor must be ≤ unhealthy.")
    return errs


def validate_range_ordering(values: dict[str, float]) -> list[str]:
    keys = ["good_min", "good_max", "fair_min", "fair_max"]
    nums = {k: values.get(k) for k in keys}
    if any(v is None for v in nums.values()):
        return [f"Missing range threshold key(s); expected {keys}."]
    gm, gx, fm, fx = nums["good_min"], nums["good_max"], nums["fair_min"], nums["fair_max"]
    errs: list[str] = []
    if gm > gx:
        errs.append("good_min must be ≤ good_max.")
    if fm > fx:
        errs.append("fair_min must be ≤ fair_max.")
    if gm < fm or gx > fx:
        errs.append("good range must lie inside fair range (good_min ≥ fair_min and good_max ≤ fair_max).")
    return errs


def parse_profile_form(form: Any) -> dict[str, dict[str, float]]:
    """Build measurement dicts from POST form keys like pm25_good, humidity_good_min."""
    simple_types = ("pm25", "pm10", "co2", "voc", "no2", "o3", "radon")
    simple_fields = ("good", "fair", "poor", "unhealthy")
    range_types = ("temperature", "temperature_f", "temperature_c", "humidity")
    range_fields = ("good_min", "good_max", "fair_min", "fair_max")

    out: dict[str, dict[str, float]] = {}

    for m in simple_types:
        block: dict[str, float] = {}
        for f in simple_fields:
            key = f"{m}_{f}"
            if key not in form:
                continue
            raw = form.get(key)
            if raw is None or raw == "":
                continue
            block[f] = float(raw)
        if block:
            out[m] = block

    for m in range_types:
        block = {}
        for f in range_fields:
            key = f"{m}_{f}"
            if key not in form:
                continue
            raw = form.get(key)
            if raw is None or raw == "":
                continue
            block[f] = float(raw)
        if block:
            out[m] = block

    return out


def validate_full_profile(measurements: dict[str, dict[str, float]]) -> list[str]:
    errors: list[str] = []
    simple_types = {"pm25", "pm10", "co2", "voc", "no2", "o3", "radon"}
    range_types = {"temperature", "temperature_f", "temperature_c", "humidity"}

    for m, block in measurements.items():
        if m in simple_types:
            errors.extend(f"{m}: {e}" for e in validate_simple_monotonic(block))
        elif m in range_types:
            errors.extend(f"{m}: {e}" for e in validate_range_ordering(block))
    return errors


def materialize_profile_for_save(
    measurements: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """Return a YAML-serializable profile dict (no extends)."""
    return dict(measurements)
