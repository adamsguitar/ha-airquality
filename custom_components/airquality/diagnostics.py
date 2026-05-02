"""Diagnostics support for the Air Quality integration.

Returns a JSON-serializable snapshot of the loaded config, current coordinator
state, and source entity states. Surfaced via the integration's "Download
Diagnostics" button on the Devices & Services page.
"""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import COORDINATOR_KEY, DOMAIN
from .coordinator import AirQualityCoordinator


def _serialize_config(coordinator: AirQualityCoordinator) -> dict[str, Any] | None:
    cfg = coordinator.config
    if cfg is None:
        return None
    return {
        "defaults": {
            "staleness_minutes": cfg.defaults.staleness_minutes,
            "debounce_seconds": cfg.defaults.debounce_seconds,
            "threshold_profile": cfg.defaults.threshold_profile,
        },
        "threshold_profiles": cfg.threshold_profiles,
        "spaces": [
            {
                "area": s.area,
                "name": s.name,
                "threshold_profile": s.threshold_profile,
                "slots": [
                    {
                        "measurement": slot.measurement,
                        "aggregation": slot.aggregation,
                        "entities": list(slot.entities),
                        "weights": dict(slot.weights),
                        "expose_problem_binary": slot.expose_problem_binary,
                    }
                    for slot in s.slots
                ],
            }
            for s in cfg.spaces
        ],
    }


def _serialize_state(coordinator: AirQualityCoordinator) -> dict[str, Any] | None:
    data = coordinator.data
    if data is None:
        return None
    return {
        "slots": {
            f"{area}::{measurement}": {
                "value": sd.value,
                "state": sd.state.value,
                "health": sd.health,
                "contributing_entities": list(sd.contributing_entities),
            }
            for (area, measurement), sd in data.slots.items()
        },
        "spaces": {
            aid: {
                "name": sh.name,
                "floor_id": sh.floor_id,
                "health": sh.health,
                "slot_healths": dict(sh.slot_healths),
                "slot_values": dict(sh.slot_values),
            }
            for aid, sh in data.spaces.items()
        },
        "floors": {
            fid: {
                "name": fh.name,
                "health": fh.health,
                "space_healths": dict(fh.space_healths),
            }
            for fid, fh in data.floors.items()
        },
        "home": (
            {
                "health": data.home.health,
                "floor_healths": dict(data.home.floor_healths),
                "orphan_space_healths": dict(data.home.orphan_space_healths),
            }
            if data.home
            else None
        ),
    }


def _serialize_source_states(
    hass: HomeAssistant, coordinator: AirQualityCoordinator
) -> dict[str, Any]:
    """Snapshot the current state of every entity referenced by the config."""
    if coordinator.config is None:
        return {}

    entity_ids: set[str] = {
        eid
        for space in coordinator.config.spaces
        for slot in space.slots
        for eid in slot.entities
    }

    snapshot: dict[str, Any] = {}
    for eid in sorted(entity_ids):
        state = hass.states.get(eid)
        if state is None:
            snapshot[eid] = None
            continue
        snapshot[eid] = {
            "state": state.state,
            "device_class": state.attributes.get("device_class"),
            "unit_of_measurement": state.attributes.get("unit_of_measurement"),
            "last_changed": state.last_changed.isoformat() if state.last_changed else None,
            "last_updated": state.last_updated.isoformat() if state.last_updated else None,
        }
    return snapshot


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostic data for a config entry."""
    coordinator: AirQualityCoordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR_KEY]

    return {
        "entry": {
            "entry_id": entry.entry_id,
            "version": entry.version,
            "minor_version": getattr(entry, "minor_version", None),
            "title": entry.title,
            "data": dict(entry.data),
        },
        "config": _serialize_config(coordinator),
        "state": _serialize_state(coordinator),
        "source_entities": _serialize_source_states(hass, coordinator),
        "ha": {
            "version": hass.config.as_dict().get("version") if hasattr(hass.config, "as_dict") else None,
        },
    }
