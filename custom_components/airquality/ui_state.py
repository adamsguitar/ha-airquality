"""UI state assembly for the add-on's area-driven editor.

Collects HA areas, the current YAML config, and air-quality candidate sensors
grouped by area. Returned as plain JSON so the add-on can render without
holding HA registry references itself.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)

from .const import MEASUREMENT_TYPES, YAML_FILENAME
from .discovery import (
    _DEVICE_CLASS_TO_MEASUREMENT,
    _TEMPERATURE_UNITS,
    _is_disabled_or_hidden,
    _resolve_area_id,
)

_LOGGER = logging.getLogger(__name__)


def _classify_for_ui(state) -> tuple[str | None, str | None, str | None]:
    """Return (measurement, device_class, unit) or (None, dc, unit) if not AQ-relevant."""
    if state is None:
        return None, None, None

    device_class = state.attributes.get("device_class")
    unit = state.attributes.get("unit_of_measurement")

    if device_class == "temperature":
        return _TEMPERATURE_UNITS.get(unit), device_class, unit

    measurement = _DEVICE_CLASS_TO_MEASUREMENT.get(device_class)
    return measurement, device_class, unit


async def async_collect_ui_state(hass: HomeAssistant) -> dict[str, Any]:
    """Build the full UI state payload."""
    area_reg = ar.async_get(hass)
    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)

    areas = []
    for area in area_reg.async_list_areas():
        areas.append(
            {
                "area_id": area.id,
                "name": area.name,
                "floor_id": area.floor_id,
                "icon": area.icon,
            }
        )
    areas.sort(key=lambda a: a["name"].lower())

    candidates_by_area: dict[str, list[dict[str, Any]]] = {}

    for entry in entity_reg.entities.values():
        if entry.domain != "sensor":
            continue
        if entry.platform == "airquality":
            continue
        if _is_disabled_or_hidden(entry):
            continue

        state = hass.states.get(entry.entity_id)
        measurement, device_class, unit = _classify_for_ui(state)
        if measurement is None:
            continue

        area_id = _resolve_area_id(entry, device_reg)
        if area_id is None:
            continue

        friendly = (
            (state.attributes.get("friendly_name") if state else None)
            or entry.name
            or entry.original_name
            or entry.entity_id
        )

        candidates_by_area.setdefault(area_id, []).append(
            {
                "entity_id": entry.entity_id,
                "name": friendly,
                "measurement": measurement,
                "device_class": device_class,
                "unit_of_measurement": unit,
                "state": state.state if state else None,
            }
        )

    for items in candidates_by_area.values():
        items.sort(key=lambda c: (c["measurement"], c["name"].lower()))

    yaml_path = Path(hass.config.config_dir) / YAML_FILENAME
    raw_config: dict[str, Any] = {}
    if yaml_path.exists():
        try:
            raw_config = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as err:
            _LOGGER.warning("Could not parse %s for UI state: %s", yaml_path, err)
            raw_config = {}

    return {
        "areas": areas,
        "candidates_by_area": candidates_by_area,
        "config": raw_config,
        "available_measurements": sorted(MEASUREMENT_TYPES),
        "yaml_path": str(yaml_path),
    }
