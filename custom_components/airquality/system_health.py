"""System Health card for the Air Quality integration.

Surfaces a summary on the Settings → System → Repairs → System Information page.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components import system_health
from homeassistant.core import HomeAssistant, callback

from .const import COORDINATOR_KEY, DOMAIN
from .coordinator import AirQualityCoordinator


@callback
def async_register(
    hass: HomeAssistant, register: system_health.SystemHealthRegistration
) -> None:
    """Register the system health callback."""
    register.async_register_info(system_health_info)


async def system_health_info(hass: HomeAssistant) -> dict[str, Any]:
    """Return a summary of the integration's runtime state."""
    info: dict[str, Any] = {}

    if DOMAIN not in hass.data or not hass.data[DOMAIN]:
        info["status"] = "not loaded"
        return info

    entry_data = next(iter(hass.data[DOMAIN].values()))
    coordinator: AirQualityCoordinator | None = entry_data.get(COORDINATOR_KEY)
    if coordinator is None:
        info["status"] = "no coordinator"
        return info

    cfg = coordinator.config
    info["yaml_loaded"] = cfg is not None
    if cfg is not None:
        info["spaces_configured"] = len(cfg.spaces)
        info["slots_configured"] = sum(len(s.slots) for s in cfg.spaces)
        info["threshold_profiles"] = len(cfg.threshold_profiles)

    data = coordinator.data
    if data is not None:
        slot_states = [sd.state.value for sd in data.slots.values()]
        info["slots_ok"] = sum(1 for s in slot_states if s == "ok")
        info["slots_stale"] = sum(1 for s in slot_states if s == "stale")
        info["slots_unavailable"] = sum(1 for s in slot_states if s == "unavailable")
        info["floors_tracked"] = len(data.floors)
        if data.home is not None:
            info["home_health"] = data.home.health

    return info
