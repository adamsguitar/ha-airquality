"""Tests for the add-on's high-level YAML mutation helpers."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ADDON_APP = Path(__file__).resolve().parent.parent / "addon" / "app"
sys.path.insert(0, str(ADDON_APP))

import config_ops  # noqa: E402
import yaml_io  # noqa: E402


@pytest.fixture
def empty_config():
    return None


@pytest.fixture
def sample_config():
    text = """
airquality:
  defaults:
    staleness_minutes: 15
    debounce_seconds: 30
    threshold_profile: default
  threshold_profiles:
    default:
      pm25: { good: 12, fair: 35, poor: 55, unhealthy: 150 }
  spaces:
    - area: living_room
      slots:
        - measurement: co2
          aggregation: single
          entities:
            - sensor.living_co2
"""
    return yaml_io.parse_text(text)


def test_add_slot_creates_space_when_missing(empty_config):
    data = config_ops.add_slot(empty_config, "kitchen", "co2")
    spaces = data["airquality"]["spaces"]
    assert len(spaces) == 1
    assert spaces[0]["area"] == "kitchen"
    assert spaces[0]["slots"][0]["measurement"] == "co2"
    assert spaces[0]["slots"][0]["aggregation"] == "single"
    assert list(spaces[0]["slots"][0]["entities"]) == []


def test_add_slot_idempotent(sample_config):
    data = config_ops.add_slot(sample_config, "living_room", "co2")
    slots = data["airquality"]["spaces"][0]["slots"]
    measurements = [s["measurement"] for s in slots]
    assert measurements.count("co2") == 1


def test_add_entity_appends_and_promotes_aggregation(sample_config):
    data = config_ops.add_entity(
        sample_config, "living_room", "co2", "sensor.living_co2_b"
    )
    slot = data["airquality"]["spaces"][0]["slots"][0]
    assert list(slot["entities"]) == ["sensor.living_co2", "sensor.living_co2_b"]
    assert slot["aggregation"] == "average"


def test_add_entity_creates_slot_and_space_if_missing(empty_config):
    data = config_ops.add_entity(empty_config, "office", "pm25", "sensor.office_pm25")
    space = data["airquality"]["spaces"][0]
    assert space["area"] == "office"
    assert space["slots"][0]["measurement"] == "pm25"
    assert list(space["slots"][0]["entities"]) == ["sensor.office_pm25"]


def test_remove_entity_removes_slot_when_last(sample_config):
    data = config_ops.remove_entity(
        sample_config, "living_room", "co2", "sensor.living_co2"
    )
    spaces = data["airquality"]["spaces"]
    assert spaces == []  # space cleaned up too because slot list is empty


def test_remove_entity_demotes_aggregation_to_single(sample_config):
    config_ops.add_entity(sample_config, "living_room", "co2", "sensor.b")
    config_ops.add_entity(sample_config, "living_room", "co2", "sensor.c")
    slot = sample_config["airquality"]["spaces"][0]["slots"][0]
    assert slot["aggregation"] == "average"
    config_ops.remove_entity(sample_config, "living_room", "co2", "sensor.b")
    config_ops.remove_entity(sample_config, "living_room", "co2", "sensor.c")
    slot = sample_config["airquality"]["spaces"][0]["slots"][0]
    assert slot["aggregation"] == "single"
    assert list(slot["entities"]) == ["sensor.living_co2"]


def test_set_aggregation_validates(sample_config):
    with pytest.raises(ValueError):
        config_ops.set_aggregation(sample_config, "living_room", "co2", "bogus")
    config_ops.set_aggregation(sample_config, "living_room", "co2", "median")
    assert sample_config["airquality"]["spaces"][0]["slots"][0]["aggregation"] == "median"


def test_set_space_threshold_profile_clears_when_empty(sample_config):
    config_ops.set_space_threshold_profile(sample_config, "living_room", "kids_room")
    assert sample_config["airquality"]["spaces"][0]["threshold_profile"] == "kids_room"
    config_ops.set_space_threshold_profile(sample_config, "living_room", None)
    assert "threshold_profile" not in sample_config["airquality"]["spaces"][0]


def test_remove_space(sample_config):
    config_ops.remove_space(sample_config, "living_room")
    assert sample_config["airquality"]["spaces"] == []


def test_merge_discovery_proposal_appends_only(sample_config):
    proposal = {
        "airquality": {
            "spaces": [
                {
                    "area": "living_room",
                    "slots": [
                        {
                            "measurement": "co2",
                            "aggregation": "average",
                            "entities": ["sensor.living_co2", "sensor.new_co2"],
                        }
                    ],
                },
                {
                    "area": "bedroom",
                    "slots": [
                        {
                            "measurement": "humidity",
                            "aggregation": "single",
                            "entities": ["sensor.bedroom_humidity"],
                        }
                    ],
                },
            ]
        }
    }
    data = config_ops.merge_discovery_proposal(sample_config, proposal)
    spaces = {s["area"]: s for s in data["airquality"]["spaces"]}
    assert "bedroom" in spaces
    co2_slot = spaces["living_room"]["slots"][0]
    assert list(co2_slot["entities"]) == ["sensor.living_co2", "sensor.new_co2"]


def test_merge_discovery_proposal_overwrite(sample_config):
    proposal = {
        "airquality": {
            "spaces": [
                {
                    "area": "living_room",
                    "slots": [
                        {
                            "measurement": "co2",
                            "aggregation": "max",
                            "entities": ["sensor.replacement_co2"],
                        }
                    ],
                }
            ]
        }
    }
    data = config_ops.merge_discovery_proposal(
        sample_config, proposal, overwrite_slots=True
    )
    slot = data["airquality"]["spaces"][0]["slots"][0]
    assert list(slot["entities"]) == ["sensor.replacement_co2"]
    assert slot["aggregation"] == "max"
