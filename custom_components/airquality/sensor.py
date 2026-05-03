"""Sensor platform for the Air Quality integration.

Entity types:
- AirQualitySlotSensor: numeric value for one slot in one space, with the
  per-measurement health band exposed as a state attribute
- AirQualitySpaceSensor: composite worst-state for a space, with all slot
  values, slot health, and a list of unhealthy_reasons in attributes
- AirQualityFloorSensor: composite worst-state for a floor (rollup of spaces)
- AirQualityHomeSensor: composite worst-state for the whole home
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    CONCENTRATION_PARTS_PER_BILLION,
    CONCENTRATION_PARTS_PER_MILLION,
    PERCENTAGE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    COORDINATOR_KEY,
    DOMAIN,
    HEALTH_STATES,
    HEALTH_UNAVAILABLE,
)
from .coordinator import AirQualityCoordinator
from .health import is_problem
from .models import SlotConfig, SlotState, SpaceConfig

_LOGGER = logging.getLogger(__name__)

_MEASUREMENT_META: dict[str, tuple[SensorDeviceClass | None, str | None]] = {
    "temperature":   (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.FAHRENHEIT),
    "temperature_f": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.FAHRENHEIT),
    "temperature_c": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
    "humidity":      (SensorDeviceClass.HUMIDITY, PERCENTAGE),
    "pm25":          (SensorDeviceClass.PM25, CONCENTRATION_MICROGRAMS_PER_CUBIC_METER),
    "pm10":          (SensorDeviceClass.PM10, CONCENTRATION_MICROGRAMS_PER_CUBIC_METER),
    "co2":           (SensorDeviceClass.CO2, CONCENTRATION_PARTS_PER_MILLION),
    "voc":           (SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS, CONCENTRATION_PARTS_PER_BILLION),
    "no2":           (SensorDeviceClass.NITROGEN_DIOXIDE, CONCENTRATION_MICROGRAMS_PER_CUBIC_METER),
    "o3":            (SensorDeviceClass.OZONE, CONCENTRATION_MICROGRAMS_PER_CUBIC_METER),
    "radon":         (None, "Bq/m³"),
}

_MEASUREMENT_FRIENDLY: dict[str, str] = {
    "temperature":   "Temperature",
    "temperature_f": "Temperature",
    "temperature_c": "Temperature",
    "humidity":      "Humidity",
    "pm25":          "PM2.5",
    "pm10":          "PM10",
    "co2":           "CO₂",
    "voc":           "VOC",
    "no2":           "NO₂",
    "o3":            "O₃",
    "radon":         "Radon",
}

_MEASUREMENT_ICONS: dict[str, str] = {
    "temperature":   "mdi:thermometer",
    "temperature_f": "mdi:thermometer",
    "temperature_c": "mdi:thermometer",
    "humidity":      "mdi:water-percent",
    "pm25":          "mdi:air-filter",
    "pm10":          "mdi:air-filter",
    "co2":           "mdi:molecule-co2",
    "voc":           "mdi:chemical-weapon",
    "no2":           "mdi:cloud",
    "o3":            "mdi:cloud",
    "radon":         "mdi:radioactive",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Air Quality sensor entities from a config entry."""
    coordinator: AirQualityCoordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR_KEY]

    if coordinator.config is None:
        return

    entities: list[SensorEntity] = []

    for space in coordinator.config.spaces:
        for slot in space.slots:
            entities.append(
                AirQualitySlotSensor(coordinator, space, slot, entry.entry_id)
            )

        entities.append(AirQualitySpaceSensor(coordinator, space, entry.entry_id))

    if coordinator.data is not None:
        for floor_id in coordinator.data.floors:
            entities.append(AirQualityFloorSensor(coordinator, floor_id, entry.entry_id))

        if coordinator.data.home is not None:
            entities.append(AirQualityHomeSensor(coordinator, entry.entry_id))

    async_add_entities(entities)

    _enforce_device_areas(hass, entry.entry_id, coordinator)


def _area_display_name(hass: HomeAssistant, area_id: str) -> str:
    from homeassistant.helpers import area_registry as ar  # noqa: PLC0415
    registry = ar.async_get(hass)
    area = registry.async_get_area(area_id)
    return area.name if area else area_id.replace("_", " ").title()


def _space_device_info(hass: HomeAssistant, entry_id: str, area_id: str) -> DeviceInfo:
    name = _area_display_name(hass, area_id)
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry_id}::{area_id}")},
        name=f"{name} Air Quality",
        manufacturer="Air Quality",
        model="Room",
        suggested_area=name,
    )


def _floor_device_info(entry_id: str, floor_id: str, name: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry_id}::floor::{floor_id}")},
        name=f"{name} Floor Air Quality",
        manufacturer="Air Quality",
        model="Floor Rollup",
    )


def _home_device_info(entry_id: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry_id}::home")},
        name="Home Air Quality",
        manufacturer="Air Quality",
        model="Home Rollup",
    )


def _enforce_device_areas(
    hass: HomeAssistant,
    entry_id: str,
    coordinator: AirQualityCoordinator,
) -> None:
    """Bind each room device to its HA area_id explicitly.

    DeviceInfo.suggested_area only takes effect on first creation; this also
    repairs devices that may have lost their area binding from a prior version.
    """
    if coordinator.config is None:
        return
    device_reg = dr.async_get(hass)
    for space in coordinator.config.spaces:
        identifier = (DOMAIN, f"{entry_id}::{space.area}")
        device = device_reg.async_get_device(identifiers={identifier})
        if device is None:
            continue
        if device.area_id != space.area:
            device_reg.async_update_device(device.id, area_id=space.area)


class AirQualitySlotSensor(CoordinatorEntity[AirQualityCoordinator], SensorEntity):
    """Numeric value for one measurement slot in one space.

    The per-measurement health band is exposed as the `health` state attribute.
    """

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_should_poll = False

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

        device_class, unit = _MEASUREMENT_META.get(slot.measurement, (None, None))
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_unique_id = f"{entry_id}::{space.area}::{slot.measurement}"
        self._attr_name = _MEASUREMENT_FRIENDLY.get(slot.measurement, slot.measurement)
        self._attr_icon = _MEASUREMENT_ICONS.get(slot.measurement)

    @property
    def device_info(self) -> DeviceInfo:
        return _space_device_info(self.coordinator.hass, self._entry_id, self._space.area)

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        slot_data = self.coordinator.data.slots.get((self._space.area, self._slot.measurement))
        if slot_data is None or slot_data.state != SlotState.OK:
            return None
        return slot_data.value

    @property
    def available(self) -> bool:
        if not super().available or self.coordinator.data is None:
            return False
        slot_data = self.coordinator.data.slots.get((self._space.area, self._slot.measurement))
        if slot_data is None:
            return False
        return slot_data.state != SlotState.UNAVAILABLE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        slot_data = self.coordinator.data.slots.get((self._space.area, self._slot.measurement))
        if slot_data is None:
            return {}
        return {
            "health": slot_data.health,
            "slot_state": slot_data.state.value,
            "aggregation": self._slot.aggregation,
            "contributing_entities": slot_data.contributing_entities,
            "source_entities": self._slot.entities,
        }


class AirQualitySpaceSensor(CoordinatorEntity[AirQualityCoordinator], SensorEntity):
    """Composite worst-state sensor for a space.

    Exposes per-measurement values and health in attributes, plus an
    `unhealthy_reasons` list naming the measurements that drove the rollup
    to a problem state (poor or worse).
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = HEALTH_STATES
    _attr_icon = "mdi:home-thermometer"
    _attr_name = "Overall"

    def __init__(
        self,
        coordinator: AirQualityCoordinator,
        space: SpaceConfig,
        entry_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._space = space
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}::{space.area}::overall"

    @property
    def device_info(self) -> DeviceInfo:
        return _space_device_info(self.coordinator.hass, self._entry_id, self._space.area)

    @property
    def native_value(self) -> str:
        if self.coordinator.data is None:
            return HEALTH_UNAVAILABLE
        space_data = self.coordinator.data.spaces.get(self._space.area)
        if space_data is None:
            return HEALTH_UNAVAILABLE
        return space_data.health

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        space_data = self.coordinator.data.spaces.get(self._space.area)
        if space_data is None:
            return {}
        measurements = {
            measurement: {
                "value": space_data.slot_values.get(measurement),
                "health": space_data.slot_healths.get(measurement),
            }
            for measurement in space_data.slot_healths
        }
        unhealthy_reasons = [
            {
                "measurement": measurement,
                "health": health,
                "value": space_data.slot_values.get(measurement),
            }
            for measurement, health in space_data.slot_healths.items()
            if is_problem(health)
        ]
        return {
            "area_id": space_data.area_id,
            "floor_id": space_data.floor_id,
            "measurements": measurements,
            "unhealthy_reasons": unhealthy_reasons,
        }


class AirQualityFloorSensor(CoordinatorEntity[AirQualityCoordinator], SensorEntity):
    """Composite worst-state sensor for a floor (rollup of spaces on that floor)."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = HEALTH_STATES
    _attr_icon = "mdi:layers"
    _attr_name = "Overall"

    def __init__(
        self,
        coordinator: AirQualityCoordinator,
        floor_id: str,
        entry_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._floor_id = floor_id
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}::floor::{floor_id}::overall"

    @property
    def device_info(self) -> DeviceInfo:
        if self.coordinator.data is None:
            name = self._floor_id
        else:
            floor = self.coordinator.data.floors.get(self._floor_id)
            name = floor.name if floor else self._floor_id
        return _floor_device_info(self._entry_id, self._floor_id, name)

    @property
    def native_value(self) -> str:
        if self.coordinator.data is None:
            return HEALTH_UNAVAILABLE
        floor = self.coordinator.data.floors.get(self._floor_id)
        return floor.health if floor else HEALTH_UNAVAILABLE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        floor = self.coordinator.data.floors.get(self._floor_id)
        if floor is None:
            return {}
        unhealthy_spaces = [
            {"area_id": area_id, "health": health}
            for area_id, health in floor.space_healths.items()
            if is_problem(health)
        ]
        return {
            "floor_id": floor.floor_id,
            "spaces": floor.space_healths,
            "unhealthy_reasons": unhealthy_spaces,
        }


class AirQualityHomeSensor(CoordinatorEntity[AirQualityCoordinator], SensorEntity):
    """Composite worst-state sensor for the whole home."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = HEALTH_STATES
    _attr_icon = "mdi:home-heart"
    _attr_name = "Overall"

    def __init__(
        self,
        coordinator: AirQualityCoordinator,
        entry_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}::home::overall"

    @property
    def device_info(self) -> DeviceInfo:
        return _home_device_info(self._entry_id)

    @property
    def native_value(self) -> str:
        if self.coordinator.data is None or self.coordinator.data.home is None:
            return HEALTH_UNAVAILABLE
        return self.coordinator.data.home.health

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None or self.coordinator.data.home is None:
            return {}
        home = self.coordinator.data.home
        unhealthy_floors = [
            {"floor_id": fid, "health": h}
            for fid, h in home.floor_healths.items()
            if is_problem(h)
        ]
        unhealthy_orphans = [
            {"area_id": aid, "health": h}
            for aid, h in home.orphan_space_healths.items()
            if is_problem(h)
        ]
        return {
            "floors": home.floor_healths,
            "orphan_spaces": home.orphan_space_healths,
            "unhealthy_reasons": unhealthy_floors + unhealthy_orphans,
        }
