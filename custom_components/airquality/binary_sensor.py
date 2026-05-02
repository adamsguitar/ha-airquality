"""Binary sensor platform for the Air Quality integration.

Entity types:
- AirQualitySlotProblemBinarySensor (opt-in via expose_problem_binary)
- AirQualitySpaceProblemBinarySensor (one per space, always)
- AirQualityFloorProblemBinarySensor (one per floor with at least one space)
- AirQualityHomeProblemBinarySensor (one for the whole home)

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
from .models import SlotConfig, SpaceConfig
from .sensor import (
    _MEASUREMENT_FRIENDLY,
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
        for slot in space.slots:
            if slot.expose_problem_binary:
                entities.append(
                    AirQualitySlotProblemBinarySensor(
                        coordinator, space, slot, entry.entry_id
                    )
                )
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


class _ProblemBase(CoordinatorEntity[AirQualityCoordinator], BinarySensorEntity):
    """Base class for all problem binary sensors."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_name = "Problem"


class AirQualitySlotProblemBinarySensor(_ProblemBase):
    """Problem state for one slot in one space (opt-in)."""

    def __init__(
        self,
        coordinator: AirQualityCoordinator,
        space: SpaceConfig,
        slot: SlotConfig,
        entry_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._space = space
        self._slot = slot
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}::{space.area}::{slot.measurement}::problem"
        friendly = _MEASUREMENT_FRIENDLY.get(slot.measurement, slot.measurement)
        self._attr_name = f"{friendly} Problem"

    @property
    def device_info(self) -> DeviceInfo:
        return _space_device_info(self.coordinator.hass, self._entry_id, self._space.area)

    @property
    def is_on(self) -> bool:
        if self.coordinator.data is None:
            return False
        slot_data = self.coordinator.data.slots.get((self._space.area, self._slot.measurement))
        return slot_data is not None and is_problem(slot_data.health)


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
