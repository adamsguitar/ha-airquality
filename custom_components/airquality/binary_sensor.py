"""Binary sensor platform for the Air Quality integration.

Phase 1 placeholder — binary sensors require health computation (Phase 2).
The platform is registered here so the file is in place for Phase 2 to fill in
without structural changes.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Air Quality binary sensor entities.

    Phase 2 will add:
    - Per-slot binary sensors (where expose_problem_binary=True)
    - Per-space binary sensors (always)
    - Per-floor and whole-home binary sensors
    """
