"""Sensor platform for the Air Quality integration.

Creates one AirQualitySlotSensor per slot defined in each space. Each sensor
reads its aggregated value from the coordinator and reports the correct
device_class, unit_of_measurement, and state_class.
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
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import COORDINATOR_KEY, DOMAIN
from .coordinator import AirQualityCoordinator
from .models import SlotConfig, SlotState, SpaceConfig

_LOGGER = logging.getLogger(__name__)

# (device_class, native_unit) keyed by measurement type.
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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Air Quality sensor entities from a config entry."""
    coordinator: AirQualityCoordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR_KEY]

    if coordinator.config is None:
        return

    entities: list[AirQualitySlotSensor] = []
    for space in coordinator.config.spaces:
        for slot in space.slots:
            entities.append(
                AirQualitySlotSensor(coordinator, space, slot, entry.entry_id)
            )

    async_add_entities(entities)


def _area_display_name(hass: HomeAssistant, area_id: str) -> str:
    """Return the HA area's display name, falling back to area_id if not found."""
    from homeassistant.helpers import area_registry as ar  # noqa: PLC0415
    registry = ar.async_get(hass)
    area = registry.async_get_area(area_id)
    return area.name if area else area_id.replace("_", " ").title()


class AirQualitySlotSensor(CoordinatorEntity[AirQualityCoordinator], SensorEntity):
    """A sensor reporting the aggregated value for one measurement slot in one space."""

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
        self._attr_icon = self._pick_icon(slot.measurement)

    @staticmethod
    def _pick_icon(measurement: str) -> str | None:
        icons = {
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
        return icons.get(measurement)

    @property
    def device_info(self) -> DeviceInfo:
        """Group all sensors for a space under a virtual device."""
        area_name = _area_display_name(self.coordinator.hass, self._space.area)
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}::{self._space.area}")},
            name=f"{area_name} Air Quality",
            manufacturer="Air Quality",
            model="Computed",
            area_id=self._space.area,
        )

    @property
    def native_value(self) -> float | None:
        """Return the aggregated sensor value, or None if unavailable/stale."""
        if self.coordinator.data is None:
            return None
        slot_data = self.coordinator.data.get((self._space.area, self._slot.measurement))
        if slot_data is None or slot_data.state != SlotState.OK:
            return None
        return slot_data.value

    @property
    def available(self) -> bool:
        """Mark unavailable when coordinator has no data or slot value cannot be computed."""
        if not super().available or self.coordinator.data is None:
            return False
        slot_data = self.coordinator.data.get((self._space.area, self._slot.measurement))
        if slot_data is None:
            return False
        return slot_data.state != SlotState.UNAVAILABLE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose contributing entities and slot state for diagnostics."""
        if self.coordinator.data is None:
            return {}
        slot_data = self.coordinator.data.get((self._space.area, self._slot.measurement))
        if slot_data is None:
            return {}
        return {
            "aggregation": self._slot.aggregation,
            "slot_state": slot_data.state.value,
            "contributing_entities": slot_data.contributing_entities,
            "source_entities": self._slot.entities,
        }
