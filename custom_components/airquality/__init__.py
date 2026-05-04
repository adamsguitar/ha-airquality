"""Air Quality integration for Home Assistant.

Reads /config/airquality.yaml, validates it, and exposes aggregated sensor
entities for each slot defined in each configured space.
"""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError

from .const import (
    COORDINATOR_KEY,
    DOMAIN,
    SERVICE_RECOMPUTE,
    SERVICE_RELOAD,
    SERVICE_SET_THRESHOLD_PROFILE,
    SERVICE_SYNC_DASHBOARD,
)
from .coordinator import AirQualityCoordinator
from .discovery import async_discover, render_yaml
from .ui_state import async_collect_ui_state

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "binary_sensor"]

SERVICE_DISCOVER = "discover"
SERVICE_GET_UI_STATE = "get_ui_state"


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
        try:
            await coordinator.async_reload_config()
        except Exception:
            _LOGGER.exception("Air Quality reload service failed.")
            raise

    async def handle_recompute(call: ServiceCall) -> None:
        """Force immediate recomputation of all slot values."""
        await coordinator.async_request_refresh()

    async def handle_set_threshold_profile(call: ServiceCall) -> None:
        """Temporarily override a space's threshold profile (not persisted)."""
        area = call.data["area"]
        profile = call.data["profile"]
        await coordinator.async_set_threshold_profile_override(area, profile)
        _LOGGER.info(
            "Threshold profile for area %r overridden to %r (transient).", area, profile
        )
        await coordinator.async_request_refresh()

    async def handle_discover(call: ServiceCall) -> dict:
        """Run discovery and return the proposed YAML configuration."""
        stale_threshold_days = call.data.get("stale_threshold_days", 30)
        include_stale = call.data.get("include_stale", False)
        write_to_file = call.data.get("write_to_file", False)

        result = await async_discover(
            hass,
            stale_threshold_days=stale_threshold_days,
            include_stale=include_stale,
        )
        yaml_text = render_yaml(result)

        if write_to_file:
            proposed_path = Path(hass.config.config_dir) / "airquality.yaml.proposed"

            def _write() -> None:
                proposed_path.write_text(yaml_text, encoding="utf-8")

            await hass.async_add_executor_job(_write)
            _LOGGER.info("Wrote discovery proposal to %s", proposed_path)

        return {
            "yaml": yaml_text,
            "summary": {
                "spaces": len(result.spaces),
                "slots": sum(len(s.slots) for s in result.spaces),
                "skipped_count": len(result.skipped),
                "skipped": [
                    {"entity_id": s.entity_id, "reason": s.reason}
                    for s in result.skipped
                ],
            },
        }

    async def handle_get_ui_state(call: ServiceCall) -> dict:
        """Return current configuration plus area / candidate metadata for the UI."""
        return await async_collect_ui_state(hass)

    async def handle_sync_dashboard(call: ServiceCall) -> None:
        await coordinator.async_sync_dashboard_now()

    hass.services.async_register(DOMAIN, SERVICE_RELOAD, handle_reload)
    hass.services.async_register(DOMAIN, SERVICE_RECOMPUTE, handle_recompute)
    hass.services.async_register(
        DOMAIN, SERVICE_SET_THRESHOLD_PROFILE, handle_set_threshold_profile
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DISCOVER,
        handle_discover,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_UI_STATE,
        handle_get_ui_state,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(DOMAIN, SERVICE_SYNC_DASHBOARD, handle_sync_dashboard)


def _unregister_services(hass: HomeAssistant) -> None:
    """Remove services when the last config entry is removed."""
    for service in (
        SERVICE_RELOAD,
        SERVICE_RECOMPUTE,
        SERVICE_SET_THRESHOLD_PROFILE,
        SERVICE_SYNC_DASHBOARD,
        SERVICE_DISCOVER,
        SERVICE_GET_UI_STATE,
    ):
        hass.services.async_remove(DOMAIN, service)
