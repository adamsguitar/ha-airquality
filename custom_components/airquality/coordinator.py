"""DataUpdateCoordinator for the Air Quality integration.

Push-based: no polling interval. Subscribes to state-change events for all
source entities defined in the YAML config. Incoming events are debounced
before triggering recomputation.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .aggregation import compute_aggregation
from .const import DOMAIN, YAML_FILENAME
from .models import AirQualityConfig, SlotConfig, SlotData, SlotState, SpaceConfig
from .yaml_loader import async_load_config

_LOGGER = logging.getLogger(__name__)

# Type alias for coordinator data: (area_id, measurement) → SlotData
CoordinatorData = dict[tuple[str, str], SlotData]


class AirQualityCoordinator(DataUpdateCoordinator[CoordinatorData]):
    """Coordinator that tracks air quality slot values across all configured spaces."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
        )
        self._config: AirQualityConfig | None = None
        self._yaml_path = Path(hass.config.config_dir) / YAML_FILENAME

    @property
    def config(self) -> AirQualityConfig | None:
        """The parsed YAML configuration, or None before first load."""
        return self._config

    async def _async_setup(self) -> None:
        """Load config and subscribe to source entity state changes.

        Called automatically by async_config_entry_first_refresh().
        """
        self._config = await async_load_config(self.hass, self._yaml_path)
        self._subscribe_to_source_entities()

    def _collect_entity_ids(self) -> set[str]:
        """Return the union of all source entity IDs across all slots."""
        if self._config is None:
            return set()
        return {
            entity_id
            for space in self._config.spaces
            for slot in space.slots
            for entity_id in slot.entities
        }

    def _subscribe_to_source_entities(self) -> None:
        """Register a debounced state-change listener for all source entities."""
        entity_ids = self._collect_entity_ids()
        if not entity_ids:
            return

        assert self.config_entry is not None
        debounce_seconds = self._config.defaults.debounce_seconds if self._config else 30

        debouncer = Debouncer(
            self.hass,
            _LOGGER,
            cooldown=debounce_seconds,
            immediate=False,
            function=self.async_request_refresh,
        )

        @callback
        def _handle_state_change(event) -> None:  # noqa: ANN001
            self.hass.async_create_task(debouncer.async_call())

        unsub = async_track_state_change_event(
            self.hass, list(entity_ids), _handle_state_change
        )

        # Cleanup on config entry unload.
        self.config_entry.async_on_unload(unsub)
        self.config_entry.async_on_unload(debouncer.async_shutdown)

    async def async_reload_config(self) -> None:
        """Reload YAML, resubscribe to entities, and push fresh data to listeners.

        Called by the airquality.reload service. Replaces the config in-place so
        existing entity objects survive; only coordinator.data changes.
        """
        self._config = await async_load_config(self.hass, self._yaml_path)
        self._subscribe_to_source_entities()
        await self.async_refresh()

    async def _async_update_data(self) -> CoordinatorData:
        """Compute aggregated values for every slot in every space."""
        if self._config is None:
            raise UpdateFailed("Configuration not loaded yet.")

        data: CoordinatorData = {}
        for space in self._config.spaces:
            for slot in space.slots:
                key = (space.area, slot.measurement)
                data[key] = self._compute_slot(space, slot)
        return data

    def _compute_slot(self, space: SpaceConfig, slot: SlotConfig) -> SlotData:
        """Compute the aggregated value for one slot from current HA states."""
        staleness_cutoff = None
        if self._config and self._config.defaults.staleness_minutes > 0:
            staleness_cutoff = dt_util.utcnow() - timedelta(
                minutes=self._config.defaults.staleness_minutes
            )

        valid_values: list[float] = []
        valid_entity_ids: list[str] = []
        any_stale = False

        for entity_id in slot.entities:
            state = self.hass.states.get(entity_id)

            if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                continue

            if staleness_cutoff and state.last_changed < staleness_cutoff:
                any_stale = True
                _LOGGER.debug(
                    "Entity %s in space %s/%s is stale (last_changed=%s).",
                    entity_id,
                    space.area,
                    slot.measurement,
                    state.last_changed,
                )
                continue

            try:
                valid_values.append(float(state.state))
                valid_entity_ids.append(entity_id)
            except (ValueError, TypeError):
                _LOGGER.debug(
                    "Entity %s has non-numeric state %r — skipping.",
                    entity_id,
                    state.state,
                )

        if not valid_values:
            slot_state = SlotState.STALE if any_stale else SlotState.UNAVAILABLE
            return SlotData(value=None, state=slot_state, contributing_entities=[])

        # Build weights list aligned to valid_entity_ids for weighted_average.
        weights = [slot.weights.get(eid, 1.0) for eid in valid_entity_ids]

        value = compute_aggregation(slot.aggregation, valid_values, weights)
        return SlotData(
            value=value,
            state=SlotState.OK,
            contributing_entities=valid_entity_ids,
        )
