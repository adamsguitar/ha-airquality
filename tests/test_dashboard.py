"""Tests for managed Lovelace dashboard config builder."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from custom_components.airquality.const import HEALTH_GOOD, HEALTH_POOR
from custom_components.airquality.dashboard import _space_not_normal, build_lovelace_config
from custom_components.airquality.models import (
    AirQualityConfig,
    Defaults,
    SlotConfig,
    SpaceConfig,
)


def test_space_not_normal():
    assert _space_not_normal(HEALTH_GOOD) is False
    assert _space_not_normal(HEALTH_POOR) is True


def test_build_lovelace_config_room_order_and_section_background():
    hass = MagicMock()
    area_reg = MagicMock()

    def _area(aid: str):
        m = MagicMock()
        m.name = {"a": "Bedroom", "b": "Kitchen"}.get(aid, aid)
        return m

    area_reg.async_get_area.side_effect = _area

    slots_a = [
        SlotConfig(measurement="pm25", aggregation="single", entities=["sensor.x"]),
    ]
    slots_b = [
        SlotConfig(measurement="co2", aggregation="single", entities=["sensor.y"]),
    ]
    config = AirQualityConfig(
        defaults=Defaults(),
        threshold_profiles={},
        spaces=[
            SpaceConfig(area="a", slots=slots_a),
            SpaceConfig(area="b", slots=slots_b),
        ],
    )

    area_health = {"a": HEALTH_GOOD, "b": HEALTH_POOR}

    with patch("homeassistant.helpers.area_registry.async_get", return_value=area_reg):
        ll = build_lovelace_config(
            config=config,
            hass=hass,
            area_health=area_health,
            slot_entity_ids={
                ("a", "pm25"): "sensor.airquality_a_pm25",
                ("b", "co2"): "sensor.airquality_b_co2",
            },
            overall_entity_ids={"a": "sensor.a_overall", "b": "sensor.b_overall"},
            problem_entity_ids={
                "a": "binary_sensor.a_problem",
                "b": "binary_sensor.b_problem",
            },
        )

    view = ll["views"][0]
    sections = view["sections"]
    assert len(sections) == 2
    first_heading = sections[0]["cards"][0]["heading"]
    assert first_heading == "Kitchen"
    assert "background" in sections[0]
    assert "background" not in sections[1]
