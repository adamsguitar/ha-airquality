"""Discovery: classify HA sensor entities and propose an air quality config.

Reads the entity, device, area, and floor registries to find sensors with known
device classes (temperature, humidity, CO2, PM, VOC, etc.) and groups them by
HA area into proposed slots. The result is rendered as YAML for user review.

Discovery does not write the integration's active config. It produces a proposal
that the user (or the add-on UI in Phase 4) reviews before saving.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import yaml
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

# Map HA SensorDeviceClass strings → our measurement keys.
# Stored as plain strings to avoid importing HA constants here.
_DEVICE_CLASS_TO_MEASUREMENT: dict[str, str] = {
    "humidity": "humidity",
    "carbon_dioxide": "co2",
    "pm25": "pm25",
    "pm10": "pm10",
    "volatile_organic_compounds_parts": "voc",
    "nitrogen_dioxide": "no2",
    "ozone": "o3",
}

# Temperature uses unit-of-measurement to disambiguate F vs C.
_TEMPERATURE_UNITS: dict[str, str] = {
    "°F": "temperature_f",
    "°C": "temperature_c",
}

# device_class values we recognise but don't currently support — record the reason
# so the user knows why the entity was skipped.
_UNSUPPORTED_DEVICE_CLASSES = {
    "volatile_organic_compounds": "VOC in µg/m³ is not yet supported (use ppb sensors)",
}


@dataclass
class DiscoveredSlot:
    """One proposed slot: measurement type, aggregation strategy, candidate entities."""
    measurement: str
    aggregation: str
    entities: list[str]


@dataclass
class DiscoveredSpace:
    """One proposed space: area binding plus its discovered slots."""
    area_id: str
    area_name: str
    floor_id: str | None
    slots: list[DiscoveredSlot] = field(default_factory=list)


@dataclass
class SkippedEntity:
    """An entity that was considered but not included, plus the reason."""
    entity_id: str
    reason: str


@dataclass
class DiscoveryResult:
    """The full output of a discovery pass."""
    spaces: list[DiscoveredSpace]
    skipped: list[SkippedEntity]


def _classify_entity(state, registry_entry) -> tuple[str | None, str | None]:
    """Determine the measurement type for one entity.

    Returns (measurement_key, skip_reason). At most one is non-None.
    """
    if state is None:
        return None, "no current state"

    device_class = state.attributes.get("device_class")
    unit = state.attributes.get("unit_of_measurement")

    if device_class == "temperature":
        measurement = _TEMPERATURE_UNITS.get(unit)
        if measurement is None:
            return None, f"temperature with unsupported unit {unit!r}"
        return measurement, None

    if device_class in _UNSUPPORTED_DEVICE_CLASSES:
        return None, _UNSUPPORTED_DEVICE_CLASSES[device_class]

    measurement = _DEVICE_CLASS_TO_MEASUREMENT.get(device_class)
    if measurement is None:
        return None, None  # not air-quality-related; silently skip

    return measurement, None


def _resolve_area_id(entity_entry, device_reg) -> str | None:
    """Resolve an entity's effective area: explicit → device → None."""
    if entity_entry.area_id:
        return entity_entry.area_id
    if entity_entry.device_id:
        device = device_reg.async_get(entity_entry.device_id)
        if device and device.area_id:
            return device.area_id
    return None


def _is_disabled_or_hidden(entity_entry) -> bool:
    return entity_entry.disabled_by is not None or entity_entry.hidden_by is not None


async def async_discover(
    hass: HomeAssistant,
    *,
    stale_threshold_days: int = 30,
    include_stale: bool = False,
) -> DiscoveryResult:
    """Scan registries and return a proposed configuration.

    Args:
        stale_threshold_days: An entity whose last_changed is older than this
            is filtered out unless include_stale is True. Default 30.
        include_stale: If True, ignore staleness filtering.
    """
    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)
    area_reg = ar.async_get(hass)

    cutoff: datetime | None = None
    if not include_stale and stale_threshold_days > 0:
        cutoff = dt_util.utcnow() - timedelta(days=stale_threshold_days)

    grouped: dict[tuple[str, str], list[str]] = {}
    skipped: list[SkippedEntity] = []

    for entry in entity_reg.entities.values():
        if entry.domain != "sensor":
            continue
        if entry.platform == "airquality":
            continue  # don't try to discover our own entities
        if _is_disabled_or_hidden(entry):
            continue

        state = hass.states.get(entry.entity_id)
        measurement, skip_reason = _classify_entity(state, entry)

        if measurement is None:
            if skip_reason:
                skipped.append(SkippedEntity(entry.entity_id, skip_reason))
            continue

        area_id = _resolve_area_id(entry, device_reg)
        if area_id is None:
            skipped.append(SkippedEntity(entry.entity_id, "no area assignment"))
            continue

        if cutoff and state and state.last_changed < cutoff:
            skipped.append(
                SkippedEntity(
                    entry.entity_id,
                    f"stale (last_changed older than {stale_threshold_days} days)",
                )
            )
            continue

        grouped.setdefault((area_id, measurement), []).append(entry.entity_id)

    spaces_by_area: dict[str, DiscoveredSpace] = {}
    for (area_id, measurement), entity_ids in grouped.items():
        if area_id not in spaces_by_area:
            area = area_reg.async_get_area(area_id)
            spaces_by_area[area_id] = DiscoveredSpace(
                area_id=area_id,
                area_name=area.name if area else area_id,
                floor_id=area.floor_id if area else None,
            )
        aggregation = "single" if len(entity_ids) == 1 else "average"
        spaces_by_area[area_id].slots.append(
            DiscoveredSlot(
                measurement=measurement,
                aggregation=aggregation,
                entities=sorted(entity_ids),
            )
        )

    spaces = sorted(spaces_by_area.values(), key=lambda s: s.area_name.lower())
    for sp in spaces:
        sp.slots.sort(key=lambda sl: sl.measurement)

    return DiscoveryResult(spaces=spaces, skipped=skipped)


def render_yaml(result: DiscoveryResult) -> str:
    """Render a DiscoveryResult as an airquality.yaml configuration string.

    Includes a default threshold_profile based on EPA AQI / ASHRAE 62.1 / standard
    comfort ranges so the proposal is immediately usable without further edits.
    """
    spaces_out: list[dict[str, Any]] = []
    for space in result.spaces:
        space_dict: dict[str, Any] = {
            "area": space.area_id,
            "slots": [
                {
                    "measurement": slot.measurement,
                    "aggregation": slot.aggregation,
                    "entities": list(slot.entities),
                }
                for slot in space.slots
            ],
        }
        spaces_out.append(space_dict)

    config = {
        "airquality": {
            "defaults": {
                "staleness_minutes": 15,
                "debounce_seconds": 30,
                "threshold_profile": "default",
            },
            "threshold_profiles": {
                "default": {
                    "pm25": {"good": 12, "fair": 35, "poor": 55, "unhealthy": 150},
                    "pm10": {"good": 54, "fair": 154, "poor": 254, "unhealthy": 354},
                    "co2": {"good": 800, "fair": 1000, "poor": 1500, "unhealthy": 2500},
                    "voc": {"good": 250, "fair": 500, "poor": 1000, "unhealthy": 2000},
                    "humidity": {"good_min": 30, "good_max": 60, "fair_min": 25, "fair_max": 65},
                    "temperature_f": {"good_min": 68, "good_max": 76, "fair_min": 65, "fair_max": 80},
                    "temperature_c": {"good_min": 20, "good_max": 24, "fair_min": 18, "fair_max": 27},
                },
            },
            "spaces": spaces_out,
        }
    }

    header = (
        "# Air Quality configuration — generated by airquality.discover\n"
        "# Review and edit this file, then save it as /config/airquality.yaml\n"
        "# and call the airquality.reload service.\n"
        "\n"
    )
    return header + yaml.safe_dump(config, sort_keys=False, default_flow_style=False)
