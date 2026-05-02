"""Air Quality integration for Home Assistant.

Reads /config/airquality.yaml, validates it, and exposes aggregated sensor
entities for each slot defined in each configured space.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

from .const import (
    COORDINATOR_KEY,
    DOMAIN,
    SERVICE_RECOMPUTE,
    SERVICE_RELOAD,
    SERVICE_SET_THRESHOLD_PROFILE,
)
from .coordinator import AirQualityCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Air Quality from a config entry."""
    coordinator = AirQualityCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        COORDINATOR_KEY: coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _register_services(hass, entry, coordinator)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
            _unregister_services(hass)
    return unloaded


def _register_services(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: AirQualityCoordinator,
) -> None:
    """Register integration services. Guards against double-registration."""
    if hass.services.has_service(DOMAIN, SERVICE_RELOAD):
        return

    async def handle_reload(call: ServiceCall) -> None:
        """Reload YAML config and push updated data to all entities."""
        _LOGGER.info("Reloading Air Quality configuration.")
        await coordinator.async_reload_config()

    async def handle_recompute(call: ServiceCall) -> None:
        """Force immediate recomputation of all slot values."""
        await coordinator.async_request_refresh()

    async def handle_set_threshold_profile(call: ServiceCall) -> None:
        """Temporarily override a space's threshold profile (not persisted)."""
        area = call.data.get("area")
        profile = call.data.get("profile")
        _LOGGER.info(
            "Setting threshold profile for area %r to %r (transient).", area, profile
        )
        # Phase 2: store override in coordinator and trigger recomputation.
        await coordinator.async_request_refresh()

    hass.services.async_register(DOMAIN, SERVICE_RELOAD, handle_reload)
    hass.services.async_register(DOMAIN, SERVICE_RECOMPUTE, handle_recompute)
    hass.services.async_register(
        DOMAIN, SERVICE_SET_THRESHOLD_PROFILE, handle_set_threshold_profile
    )


def _unregister_services(hass: HomeAssistant) -> None:
    """Remove services when the last config entry is removed."""
    for service in (SERVICE_RELOAD, SERVICE_RECOMPUTE, SERVICE_SET_THRESHOLD_PROFILE):
        hass.services.async_remove(DOMAIN, service)
