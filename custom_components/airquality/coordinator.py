"""DataUpdateCoordinator for the Air Quality integration.

Push-based: no polling interval. Subscribes to state-change events for all
source entities defined in the YAML config. Incoming events are debounced
before triggering recomputation. Recomputation produces aggregated values,
slot health, and rollups for spaces, floors, and the home.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .aggregation import compute_aggregation
from .const import (
    DOMAIN,
    HEALTH_STALE,
    HEALTH_UNAVAILABLE,
    YAML_FILENAME,
)
from .health import evaluate_slot_health, rollup_health
from .models import (
    AirQualityConfig,
    CoordinatorState,
    FloorHealth,
    HomeHealth,
    SlotConfig,
    SlotData,
    SlotState,
    SpaceConfig,
    SpaceHealth,
)
from .yaml_loader import async_load_config

_LOGGER = logging.getLogger(__name__)


class AirQualityCoordinator(DataUpdateCoordinator[CoordinatorState]):
    """Coordinator that tracks air quality slot values, health, and rollups."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
        )
        self._config: AirQualityConfig | None = None
        self._yaml_path = Path(hass.config.config_dir) / YAML_FILENAME
        self._active_issue_ids: set[str] = set()

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

        self.config_entry.async_on_unload(unsub)
        self.config_entry.async_on_unload(debouncer.async_shutdown)

    async def async_reload_config(self) -> None:
        """Reload YAML, resubscribe to entities, and push fresh data to listeners."""
        self._config = await async_load_config(self.hass, self._yaml_path)
        self._subscribe_to_source_entities()
        await self.async_refresh()

    async def _async_update_data(self) -> CoordinatorState:
        """Compute slot values, slot health, and per-space/floor/home rollups."""
        if self._config is None:
            raise UpdateFailed("Configuration not loaded yet.")

        state = CoordinatorState()
        area_reg = ar.async_get(self.hass)

        # 1. Compute slot values + health for every slot.
        for space in self._config.spaces:
            profile = self._resolve_profile(space)
            for slot in space.slots:
                slot_data = self._compute_slot(space, slot, profile)
                state.slots[(space.area, slot.measurement)] = slot_data

        # 2. Roll up per-space health.
        spaces_by_floor: dict[str, list[str]] = {}
        orphan_spaces: list[str] = []

        for space in self._config.spaces:
            slot_healths: dict[str, str] = {}
            slot_values: dict[str, float | None] = {}
            for slot in space.slots:
                sd = state.slots.get((space.area, slot.measurement))
                if sd is None:
                    continue
                slot_healths[slot.measurement] = sd.health
                slot_values[slot.measurement] = sd.value

            space_health_value = rollup_health(list(slot_healths.values())) if slot_healths else HEALTH_UNAVAILABLE

            ha_area = area_reg.async_get_area(space.area)
            floor_id = ha_area.floor_id if ha_area else None
            display_name = space.name or (ha_area.name if ha_area else space.area)

            state.spaces[space.area] = SpaceHealth(
                area_id=space.area,
                name=display_name,
                floor_id=floor_id,
                health=space_health_value,
                slot_healths=slot_healths,
                slot_values=slot_values,
            )

            if floor_id:
                spaces_by_floor.setdefault(floor_id, []).append(space.area)
            else:
                orphan_spaces.append(space.area)

        # 3. Roll up per-floor health.
        floor_reg = self._floor_registry()
        for floor_id, area_ids in spaces_by_floor.items():
            space_healths_map = {aid: state.spaces[aid].health for aid in area_ids}
            floor_health_value = rollup_health(list(space_healths_map.values()))
            floor = floor_reg.async_get_floor(floor_id) if floor_reg else None
            floor_name = floor.name if floor else floor_id
            state.floors[floor_id] = FloorHealth(
                floor_id=floor_id,
                name=floor_name,
                health=floor_health_value,
                space_healths=space_healths_map,
            )

        # 4. Roll up home health: floor healths + orphan space healths.
        floor_health_values = [f.health for f in state.floors.values()]
        orphan_health_values = [state.spaces[aid].health for aid in orphan_spaces]
        all_home_inputs = floor_health_values + orphan_health_values

        state.home = HomeHealth(
            health=rollup_health(all_home_inputs) if all_home_inputs else HEALTH_UNAVAILABLE,
            floor_healths={fid: f.health for fid, f in state.floors.items()},
            orphan_space_healths={aid: state.spaces[aid].health for aid in orphan_spaces},
        )

        self._sync_repair_issues(state)

        return state

    def _sync_repair_issues(self, state: CoordinatorState) -> None:
        """Sync the issue registry with the current set of detected problems.

        Creates issues for new problems, deletes issues that have resolved.
        Idempotent — safe to call on every coordinator update.
        """
        if self._config is None:
            return

        desired: dict[str, tuple[str, dict[str, str]]] = {}

        for space in self._config.spaces:
            for slot in space.slots:
                slot_data = state.slots.get((space.area, slot.measurement))
                if slot_data is None:
                    continue
                if slot_data.state == SlotState.UNAVAILABLE:
                    issue_id = f"slot_unavailable::{space.area}::{slot.measurement}"
                    desired[issue_id] = (
                        "slot_unavailable",
                        {"area": space.area, "measurement": slot.measurement},
                    )
                elif slot_data.state == SlotState.STALE:
                    issue_id = f"slot_stale::{space.area}::{slot.measurement}"
                    desired[issue_id] = (
                        "slot_stale",
                        {"area": space.area, "measurement": slot.measurement},
                    )

            profile_name = space.threshold_profile or self._config.defaults.threshold_profile
            if (
                self._config.threshold_profiles
                and profile_name not in self._config.threshold_profiles
            ):
                issue_id = f"missing_profile::{space.area}::{profile_name}"
                desired[issue_id] = (
                    "missing_profile",
                    {"area": space.area, "profile": profile_name},
                )

        for issue_id, (translation_key, placeholders) in desired.items():
            if issue_id in self._active_issue_ids:
                continue
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=translation_key,
                translation_placeholders=placeholders,
            )

        for stale_id in self._active_issue_ids - desired.keys():
            ir.async_delete_issue(self.hass, DOMAIN, stale_id)

        self._active_issue_ids = set(desired)

    def _floor_registry(self):
        """Get the floor registry. Returns None if HA version doesn't expose it."""
        try:
            from homeassistant.helpers import floor_registry as fr  # noqa: PLC0415
            return fr.async_get(self.hass)
        except ImportError:
            return None

    def _resolve_profile(self, space: SpaceConfig) -> dict:
        """Return the resolved threshold profile dict for a space."""
        assert self._config is not None
        profile_name = space.threshold_profile or self._config.defaults.threshold_profile
        return self._config.threshold_profiles.get(profile_name, {})

    def _compute_slot(
        self,
        space: SpaceConfig,
        slot: SlotConfig,
        profile: dict,
    ) -> SlotData:
        """Compute aggregated value and health classification for one slot."""
        staleness_cutoff = None
        if self._config and self._config.defaults.staleness_minutes > 0:
            staleness_cutoff = dt_util.utcnow() - timedelta(
                minutes=self._config.defaults.staleness_minutes
            )

        valid_values: list[float] = []
        valid_entity_ids: list[str] = []
        any_stale = False

        for entity_id in slot.entities:
            ha_state = self.hass.states.get(entity_id)

            if ha_state is None or ha_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                continue

            if staleness_cutoff and ha_state.last_changed < staleness_cutoff:
                any_stale = True
                continue

            try:
                valid_values.append(float(ha_state.state))
                valid_entity_ids.append(entity_id)
            except (ValueError, TypeError):
                _LOGGER.debug(
                    "Entity %s has non-numeric state %r — skipping.",
                    entity_id,
                    ha_state.state,
                )

        if not valid_values:
            slot_state = SlotState.STALE if any_stale else SlotState.UNAVAILABLE
            health = HEALTH_STALE if any_stale else HEALTH_UNAVAILABLE
            return SlotData(value=None, state=slot_state, health=health, contributing_entities=[])

        weights = [slot.weights.get(eid, 1.0) for eid in valid_entity_ids]
        value = compute_aggregation(slot.aggregation, valid_values, weights)

        health = (
            evaluate_slot_health(slot.measurement, value, profile)
            if value is not None
            else HEALTH_UNAVAILABLE
        )

        return SlotData(
            value=value,
            state=SlotState.OK,
            health=health,
            contributing_entities=valid_entity_ids,
        )
