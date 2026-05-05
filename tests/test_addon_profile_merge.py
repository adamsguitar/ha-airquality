"""Tests for add-on threshold profile helpers."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

_ADDON_APP = Path(__file__).resolve().parents[1] / "addon" / "app"
sys.path.insert(0, str(_ADDON_APP))

import threshold_profiles as addon_threshold_profiles  # noqa: E402

from custom_components.airquality import yaml_loader


FIXTURE_YAML = Path(__file__).parent / "fixtures" / "example.yaml"


def test_resolve_profile_matches_integration() -> None:
    raw_full = yaml.safe_load(FIXTURE_YAML.read_text())
    raw_profiles = raw_full["airquality"]["threshold_profiles"]

    addon_res = addon_threshold_profiles.resolve_profile_inheritance(raw_profiles)

    # yaml_loader mutates in place; shallow copy top-level profile dicts
    copy_profiles = {k: dict(v) for k, v in raw_profiles.items()}
    int_res = yaml_loader._resolve_profile_inheritance(copy_profiles)

    kids = addon_res["kids_room"]
    assert kids["pm25"] == {"good": 9, "fair": 25, "poor": 45, "unhealthy": 100}
    assert kids["co2"]["good"] == 800

    assert int_res == addon_res


def test_simple_monotonic_validation() -> None:
    assert addon_threshold_profiles.validate_simple_monotonic(
        {"good": 1, "fair": 2, "poor": 3, "unhealthy": 4}
    ) == []
    errs = addon_threshold_profiles.validate_simple_monotonic(
        {"good": 10, "fair": 5, "poor": 3, "unhealthy": 2}
    )
    assert len(errs) == 3


def test_range_validation() -> None:
    assert addon_threshold_profiles.validate_range_ordering(
        {"good_min": 20, "good_max": 24, "fair_min": 18, "fair_max": 27}
    ) == []
    bad = addon_threshold_profiles.validate_range_ordering(
        {"good_min": 10, "good_max": 30, "fair_min": 15, "fair_max": 25}
    )
    assert bad
