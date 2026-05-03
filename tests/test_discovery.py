"""Tests for discovery: entity classification, area resolution, stale filtering, YAML render."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
import yaml as yaml_module
from homeassistant.util import dt as dt_util

from custom_components.airquality.discovery import (
    DiscoveredSlot,
    DiscoveredSpace,
    DiscoveryResult,
    SkippedEntity,
    _classify_entity,
    _resolve_area_id,
    async_discover,
    render_yaml,
)


# --- Helpers ---------------------------------------------------------------

def _state(device_class: str | None, unit: str | None, *, age_days: float = 0.0):
    """Build a fake HA state with the given attributes and last_changed age."""
    s = MagicMock()
    s.attributes = {}
    if device_class is not None:
        s.attributes["device_class"] = device_class
    if unit is not None:
        s.attributes["unit_of_measurement"] = unit
    s.last_changed = dt_util.utcnow() - timedelta(days=age_days)
    return s


def _entity_entry(
    entity_id: str,
    *,
    domain: str = "sensor",
    platform: str = "fake_integration",
    area_id: str | None = None,
    device_id: str | None = None,
    disabled_by=None,
    hidden_by=None,
):
    e = MagicMock()
    e.entity_id = entity_id
    e.domain = domain
    e.platform = platform
    e.area_id = area_id
    e.device_id = device_id
    e.disabled_by = disabled_by
    e.hidden_by = hidden_by
    return e


def _area(area_id: str, name: str, floor_id: str | None = None):
    a = MagicMock()
    a.area_id = area_id
    a.name = name
    a.floor_id = floor_id
    return a


def _build_hass(*, entities, states, areas, devices=None):
    """Build a hass mock with stubbed registries."""
    hass = MagicMock()
    hass.states.get = lambda eid: states.get(eid)

    entity_reg = MagicMock()
    entity_reg.entities = {e.entity_id: e for e in entities}

    device_reg = MagicMock()
    devices = devices or {}
    device_reg.async_get = lambda did: devices.get(did)

    area_reg = MagicMock()
    area_reg.async_get_area = lambda aid: areas.get(aid)

    return hass, entity_reg, device_reg, area_reg


def _patch_registries(entity_reg, device_reg, area_reg):
    return patch.multiple(
        "custom_components.airquality.discovery",
        er=MagicMock(async_get=lambda _h: entity_reg),
        dr=MagicMock(async_get=lambda _h: device_reg),
        ar=MagicMock(async_get=lambda _h: area_reg),
    )


# --- _classify_entity ------------------------------------------------------

def test_classify_humidity():
    measurement, reason = _classify_entity(_state("humidity", "%"), MagicMock())
    assert measurement == "humidity"
    assert reason is None


def test_classify_co2():
    measurement, _ = _classify_entity(_state("carbon_dioxide", "ppm"), MagicMock())
    assert measurement == "co2"


def test_classify_pm25():
    measurement, _ = _classify_entity(_state("pm25", "µg/m³"), MagicMock())
    assert measurement == "pm25"


def test_classify_temperature_fahrenheit():
    measurement, _ = _classify_entity(_state("temperature", "°F"), MagicMock())
    assert measurement == "temperature_f"


def test_classify_temperature_celsius():
    measurement, _ = _classify_entity(_state("temperature", "°C"), MagicMock())
    assert measurement == "temperature_c"


def test_classify_temperature_unknown_unit_skipped():
    measurement, reason = _classify_entity(_state("temperature", "K"), MagicMock())
    assert measurement is None
    assert "unsupported unit" in reason


def test_classify_voc_parts_accepted():
    measurement, _ = _classify_entity(
        _state("volatile_organic_compounds_parts", "ppb"), MagicMock()
    )
    assert measurement == "voc"


def test_classify_voc_mass_skipped_with_reason():
    measurement, reason = _classify_entity(
        _state("volatile_organic_compounds", "µg/m³"), MagicMock()
    )
    assert measurement is None
    assert "ppb" in reason


def test_classify_unrelated_device_class_silently_skipped():
    measurement, reason = _classify_entity(_state("battery", "%"), MagicMock())
    assert measurement is None
    assert reason is None  # not air-quality-related — silent skip


def test_classify_no_state_returns_skip_reason():
    measurement, reason = _classify_entity(None, MagicMock())
    assert measurement is None
    assert reason == "no current state"


# --- _resolve_area_id ------------------------------------------------------

def test_resolve_area_explicit():
    entry = _entity_entry("sensor.x", area_id="living_room")
    device_reg = MagicMock()
    assert _resolve_area_id(entry, device_reg) == "living_room"


def test_resolve_area_via_device():
    entry = _entity_entry("sensor.x", device_id="dev-1")
    device = MagicMock()
    device.area_id = "kitchen"
    device_reg = MagicMock()
    device_reg.async_get = lambda did: device if did == "dev-1" else None
    assert _resolve_area_id(entry, device_reg) == "kitchen"


def test_resolve_area_none_when_unset():
    entry = _entity_entry("sensor.x")
    device_reg = MagicMock()
    device_reg.async_get = lambda _: None
    assert _resolve_area_id(entry, device_reg) is None


def test_resolve_area_explicit_overrides_device():
    """If entity has area_id, use it even if device has a different one."""
    entry = _entity_entry("sensor.x", area_id="bedroom", device_id="dev-1")
    device = MagicMock()
    device.area_id = "kitchen"
    device_reg = MagicMock()
    device_reg.async_get = lambda did: device
    assert _resolve_area_id(entry, device_reg) == "bedroom"


# --- async_discover --------------------------------------------------------

@pytest.mark.asyncio
async def test_discover_groups_by_area_and_measurement():
    entities = [
        _entity_entry("sensor.lr_co2", area_id="living_room"),
        _entity_entry("sensor.lr_pm25_a", area_id="living_room"),
        _entity_entry("sensor.lr_pm25_b", area_id="living_room"),
        _entity_entry("sensor.kr_co2", area_id="kids_room"),
    ]
    states = {
        "sensor.lr_co2": _state("carbon_dioxide", "ppm"),
        "sensor.lr_pm25_a": _state("pm25", "µg/m³"),
        "sensor.lr_pm25_b": _state("pm25", "µg/m³"),
        "sensor.kr_co2": _state("carbon_dioxide", "ppm"),
    }
    areas = {
        "living_room": _area("living_room", "Living Room"),
        "kids_room": _area("kids_room", "Kids Room", floor_id="floor_1"),
    }
    hass, entity_reg, device_reg, area_reg = _build_hass(
        entities=entities, states=states, areas=areas
    )

    with _patch_registries(entity_reg, device_reg, area_reg):
        result = await async_discover(hass)

    assert len(result.spaces) == 2
    by_area = {s.area_id: s for s in result.spaces}

    lr = by_area["living_room"]
    assert lr.area_name == "Living Room"
    assert lr.floor_id is None
    measurements = {slot.measurement: slot for slot in lr.slots}
    assert "co2" in measurements
    assert "pm25" in measurements
    assert measurements["co2"].aggregation == "single"
    assert measurements["pm25"].aggregation == "average"
    assert measurements["pm25"].entities == [
        "sensor.lr_pm25_a",
        "sensor.lr_pm25_b",
    ]

    kr = by_area["kids_room"]
    assert kr.floor_id == "floor_1"


@pytest.mark.asyncio
async def test_discover_skips_unassigned_entities():
    entities = [_entity_entry("sensor.orphan")]
    states = {"sensor.orphan": _state("carbon_dioxide", "ppm")}
    hass, entity_reg, device_reg, area_reg = _build_hass(
        entities=entities, states=states, areas={}
    )

    with _patch_registries(entity_reg, device_reg, area_reg):
        result = await async_discover(hass)

    assert result.spaces == []
    assert any(
        s.entity_id == "sensor.orphan" and "no area" in s.reason
        for s in result.skipped
    )


@pytest.mark.asyncio
async def test_discover_silently_skips_disabled_and_hidden():
    entities = [
        _entity_entry("sensor.disabled", area_id="living_room", disabled_by="user"),
        _entity_entry("sensor.hidden", area_id="living_room", hidden_by="user"),
    ]
    states = {
        "sensor.disabled": _state("carbon_dioxide", "ppm"),
        "sensor.hidden": _state("carbon_dioxide", "ppm"),
    }
    areas = {"living_room": _area("living_room", "Living Room")}
    hass, entity_reg, device_reg, area_reg = _build_hass(
        entities=entities, states=states, areas=areas
    )

    with _patch_registries(entity_reg, device_reg, area_reg):
        result = await async_discover(hass)

    assert result.spaces == []
    assert result.skipped == []  # silent skip


@pytest.mark.asyncio
async def test_discover_filters_stale_entities():
    entities = [
        _entity_entry("sensor.fresh", area_id="living_room"),
        _entity_entry("sensor.stale", area_id="living_room"),
    ]
    states = {
        "sensor.fresh": _state("carbon_dioxide", "ppm", age_days=1),
        "sensor.stale": _state("carbon_dioxide", "ppm", age_days=60),
    }
    areas = {"living_room": _area("living_room", "Living Room")}
    hass, entity_reg, device_reg, area_reg = _build_hass(
        entities=entities, states=states, areas=areas
    )

    with _patch_registries(entity_reg, device_reg, area_reg):
        result = await async_discover(hass, stale_threshold_days=30)

    assert len(result.spaces) == 1
    assert result.spaces[0].slots[0].entities == ["sensor.fresh"]
    assert any("stale" in s.reason for s in result.skipped)


@pytest.mark.asyncio
async def test_discover_include_stale_disables_filter():
    entities = [_entity_entry("sensor.stale", area_id="living_room")]
    states = {"sensor.stale": _state("carbon_dioxide", "ppm", age_days=60)}
    areas = {"living_room": _area("living_room", "Living Room")}
    hass, entity_reg, device_reg, area_reg = _build_hass(
        entities=entities, states=states, areas=areas
    )

    with _patch_registries(entity_reg, device_reg, area_reg):
        result = await async_discover(hass, include_stale=True)

    assert len(result.spaces) == 1


@pytest.mark.asyncio
async def test_discover_skips_own_platform():
    """Don't try to discover entities owned by airquality itself."""
    entities = [_entity_entry("sensor.x", area_id="lr", platform="airquality")]
    states = {"sensor.x": _state("carbon_dioxide", "ppm")}
    areas = {"lr": _area("lr", "LR")}
    hass, entity_reg, device_reg, area_reg = _build_hass(
        entities=entities, states=states, areas=areas
    )

    with _patch_registries(entity_reg, device_reg, area_reg):
        result = await async_discover(hass)

    assert result.spaces == []


# --- render_yaml ----------------------------------------------------------

def test_render_yaml_produces_loadable_output():
    result = DiscoveryResult(
        spaces=[
            DiscoveredSpace(
                area_id="living_room",
                area_name="Living Room",
                floor_id=None,
                slots=[
                    DiscoveredSlot("co2", "single", ["sensor.lr_co2"]),
                    DiscoveredSlot("pm25", "average", ["sensor.a", "sensor.b"]),
                ],
            )
        ],
        skipped=[],
    )

    rendered = render_yaml(result)
    parsed = yaml_module.safe_load(rendered)

    assert "airquality" in parsed
    assert parsed["airquality"]["spaces"][0]["area"] == "living_room"
    slots = parsed["airquality"]["spaces"][0]["slots"]
    assert {s["measurement"] for s in slots} == {"co2", "pm25"}
    assert "default" in parsed["airquality"]["threshold_profiles"]


def test_render_yaml_has_helpful_header():
    result = DiscoveryResult(spaces=[], skipped=[])
    rendered = render_yaml(result)
    assert rendered.startswith("# Air Quality configuration")
    assert "airquality.reload" in rendered


def test_render_yaml_empty_discovery_still_valid():
    """Empty discovery should produce valid YAML (no spaces)."""
    rendered = render_yaml(DiscoveryResult(spaces=[], skipped=[]))
    parsed = yaml_module.safe_load(rendered)
    assert parsed["airquality"]["spaces"] == []
