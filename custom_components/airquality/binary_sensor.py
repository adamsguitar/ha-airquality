"""Binary sensor platform for the Air Quality integration.

One problem binary_sensor per device:
- AirQualitySpaceProblemBinarySensor (one per space/room device)
- AirQualityFloorProblemBinarySensor (one per floor device)
- AirQualityHomeProblemBinarySensor (one per home device)

A 'problem' is defined as health = poor, unhealthy, or hazardous.
Stale and unavailable do not trigger problem state — that's a sensor health
concern, not air quality.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import COORDINATOR_KEY, DOMAIN
from .coordinator import AirQualityCoordinator
from .health import is_problem
from .models import SpaceConfig
from .sensor import (
    _floor_device_info,
    _home_device_info,
    _space_device_info,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Air Quality binary sensors."""
    coordinator: AirQualityCoordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR_KEY]

    if coordinator.config is None:
        return

    entities: list[BinarySensorEntity] = []

    for space in coordinator.config.spaces:
        entities.append(
            AirQualitySpaceProblemBinarySensor(coordinator, space, entry.entry_id)
        )

    if coordinator.data is not None:
        for floor_id in coordinator.data.floors:
            entities.append(
                AirQualityFloorProblemBinarySensor(coordinator, floor_id, entry.entry_id)
            )
        if coordinator.data.home is not None:
            entities.append(AirQualityHomeProblemBinarySensor(coordinator, entry.entry_id))

    async_add_entities(entities)

    await hass.async_block_till_done()
    await coordinator.async_sync_dashboard_now()


class _ProblemBase(CoordinatorEntity[AirQualityCoordinator], BinarySensorEntity):
    """Base class for all problem binary sensors."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_name = "Problem"


class AirQualitySpaceProblemBinarySensor(_ProblemBase):
    """Problem state for an entire space (rollup)."""

    def __init__(
        self,
        coordinator: AirQualityCoordinator,
        space: SpaceConfig,
        entry_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._space = space
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}::{space.area}::problem"

    @property
    def device_info(self) -> DeviceInfo:
        return _space_device_info(self.coordinator.hass, self._entry_id, self._space.area)

    @property
    def is_on(self) -> bool:
        if self.coordinator.data is None:
            return False
        space = self.coordinator.data.spaces.get(self._space.area)
        return space is not None and is_problem(space.health)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        space = self.coordinator.data.spaces.get(self._space.area)
        if space is None:
            return {}
        return {
            "unhealthy_reasons": [
                {
                    "measurement": measurement,
                    "health": health,
                    "value": space.slot_values.get(measurement),
                }
                for measurement, health in space.slot_healths.items()
                if is_problem(health)
            ],
        }


class AirQualityFloorProblemBinarySensor(_ProblemBase):
    """Problem state for an entire floor."""

    def __init__(
        self,
        coordinator: AirQualityCoordinator,
        floor_id: str,
        entry_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._floor_id = floor_id
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}::floor::{floor_id}::problem"

    @property
    def device_info(self) -> DeviceInfo:
        if self.coordinator.data is None:
            name = self._floor_id
        else:
            floor = self.coordinator.data.floors.get(self._floor_id)
            name = floor.name if floor else self._floor_id
        return _floor_device_info(self._entry_id, self._floor_id, name)

    @property
    def is_on(self) -> bool:
        if self.coordinator.data is None:
            return False
        floor = self.coordinator.data.floors.get(self._floor_id)
        return floor is not None and is_problem(floor.health)


class AirQualityHomeProblemBinarySensor(_ProblemBase):
    """Problem state for the whole home."""

    def __init__(
        self,
        coordinator: AirQualityCoordinator,
        entry_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}::home::problem"

    @property
    def device_info(self) -> DeviceInfo:
        return _home_device_info(self._entry_id)

    @property
    def is_on(self) -> bool:
        if self.coordinator.data is None or self.coordinator.data.home is None:
            return False
        return is_problem(self.coordinator.data.home.health)
