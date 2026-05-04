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
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
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
from .dashboard import _space_not_normal, async_sync_dashboard
from .dashboard_sync import DashboardSyncResult
from .health import evaluate_slot_health, is_problem, rollup_health
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
        self._threshold_profile_overrides: dict[str, str] = {}
        self._active_issue_ids: set[str] = set()
        self._source_entities_unsub: CALLBACK_TYPE | None = None
        self._source_entities_debouncer: Debouncer | None = None
        self._dashboard_render_key: tuple[Any, ...] | None = None
        self._dashboard_failure_reported_render_key: tuple[Any, ...] | None = None
        entry.async_on_unload(self._async_unsubscribe_from_source_entities)

    @property
    def config(self) -> AirQualityConfig | None:
        """The parsed YAML configuration, or None before first load."""
        return self._config

    @property
    def threshold_profile_overrides(self) -> dict[str, str]:
        """Runtime-only threshold profile overrides by area_id (copy)."""
        return dict(self._threshold_profile_overrides)

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

        self._source_entities_unsub = unsub
        self._source_entities_debouncer = debouncer

    async def _async_unsubscribe_from_source_entities(self) -> None:
        """Remove the active source listener and shut down its debouncer."""
        if self._source_entities_unsub is not None:
            self._source_entities_unsub()
            self._source_entities_unsub = None

        if self._source_entities_debouncer is not None:
            await self._source_entities_debouncer.async_shutdown()
            self._source_entities_debouncer = None

    async def async_reload_config(self) -> None:
        """Reload YAML, resubscribe to entities, and push fresh data to listeners."""
        try:
            config = await async_load_config(self.hass, self._yaml_path)
        except HomeAssistantError as err:
            _LOGGER.error(
                "Air Quality config reload failed — keeping previous config active: %s",
                err,
            )
            return
        await self._async_unsubscribe_from_source_entities()
        self._config = config
        self._threshold_profile_overrides.clear()
        self._dashboard_render_key = None
        self._dashboard_failure_reported_render_key = None
        self._subscribe_to_source_entities()
        try:
            await self.async_refresh()
        except Exception:
            _LOGGER.exception(
                "Air Quality refresh failed after configuration reload "
                "(entities may be stale until the next update). Check Home Assistant logs.",
            )

    async def async_set_threshold_profile_override(
        self, area_id: str, profile_name: str
    ) -> None:
        """Apply a transient threshold profile for one space (not persisted to YAML)."""
        if self._config is None:
            raise HomeAssistantError("Air Quality configuration is not loaded yet.")
        if not any(s.area == area_id for s in self._config.spaces):
            raise HomeAssistantError(
                f"Unknown area_id {area_id!r}; it is not configured in airquality.yaml."
            )
        if profile_name not in self._config.threshold_profiles:
            known = ", ".join(sorted(self._config.threshold_profiles)) or "(none)"
            raise HomeAssistantError(
                f"Unknown threshold profile {profile_name!r}. "
                f"Defined profiles in YAML: {known}."
            )
        self._threshold_profile_overrides[area_id] = profile_name

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

        await self._maybe_sync_dashboard(state)

        return state

    def _dashboard_structure_fingerprint(self) -> tuple[Any, ...]:
        assert self._config is not None
        rows: list[tuple[Any, ...]] = []
        for space in sorted(self._config.spaces, key=lambda s: s.area):
            slot_parts = []
            for slot in sorted(space.slots, key=lambda sl: sl.measurement):
                slot_parts.append(
                    (slot.measurement, slot.aggregation, tuple(slot.entities))
                )
            rows.append((space.area, tuple(slot_parts)))
        return tuple(rows)

    async def _maybe_sync_dashboard(self, state: CoordinatorState) -> None:
        if self._config is None:
            return
        structure = self._dashboard_structure_fingerprint()
        health_layout = tuple(
            (
                space.area,
                _space_not_normal(state.spaces[space.area].health),
            )
            for space in sorted(self._config.spaces, key=lambda s: s.area)
            if space.area in state.spaces
        )
        render_key = (structure, health_layout)
        if render_key == self._dashboard_render_key:
            return
        self._dashboard_render_key = render_key
        result = await async_sync_dashboard(self.hass, self)
        self._handle_dashboard_sync_outcome(render_key, result)

    def _dashboard_issue_ids_to_clear_on_success(self) -> tuple[str, ...]:
        return (
            "dashboard_sync_failure",
            "dashboard_lovelace_unavailable",
            "dashboard_sidebar_path_blocked",
        )

    def _handle_dashboard_sync_outcome(
        self,
        render_key: tuple[Any, ...],
        result: DashboardSyncResult,
    ) -> None:
        if result.status == "ok":
            for iid in self._dashboard_issue_ids_to_clear_on_success():
                ir.async_delete_issue(self.hass, DOMAIN, iid)
            self._dashboard_failure_reported_render_key = None
            return

        actionable = (
            result.status == "failed" or (
                result.status == "skipped" and result.detail
            )
        )
        if not actionable:
            return

        issue_id = "dashboard_sync_failure"
        translation_key = "dashboard_sync_failed"
        placeholders: dict[str, str]

        if result.status == "failed":
            placeholders = {"message": result.detail or "Unknown error."}
        elif result.detail:
            lowered = result.detail.lower()
            lovelace_unready = "lovelace" in lowered and "initialized" in lowered
            if lovelace_unready:
                issue_id = "dashboard_lovelace_unavailable"
                translation_key = "dashboard_lovelace_not_ready"
                placeholders = {}
            elif "already used" in lowered or "sidebar path" in lowered:
                issue_id = "dashboard_sidebar_path_blocked"
                translation_key = "dashboard_sidebar_path_blocked"
                placeholders = {}
            else:
                placeholders = {"message": result.detail}
        else:
            return

        for oid, should_drop in (
            ("dashboard_sync_failure", issue_id != "dashboard_sync_failure"),
            ("dashboard_lovelace_unavailable", issue_id != "dashboard_lovelace_unavailable"),
            ("dashboard_sidebar_path_blocked", issue_id != "dashboard_sidebar_path_blocked"),
        ):
            if should_drop:
                ir.async_delete_issue(self.hass, DOMAIN, oid)

        if render_key != self._dashboard_failure_reported_render_key:
            self._dashboard_failure_reported_render_key = render_key
            summary = (
                placeholders["message"]
                if "message" in placeholders
                else "Open Settings → Repairs (Air Quality) for details."
            )
            persistent_notification.async_create(
                self.hass,
                summary,
                title="Air Quality: dashboard sync failed",
                notification_id=f"{DOMAIN}_dashboard_sync_problem",
            )

        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=translation_key,
            translation_placeholders=placeholders,
        )

    async def async_sync_dashboard_now(self) -> None:
        """Force dashboard regeneration (e.g. after new entity IDs are registered)."""
        if self._config is None or self.data is None:
            return
        self._dashboard_render_key = None
        structure = self._dashboard_structure_fingerprint()
        health_layout = tuple(
            (
                space.area,
                _space_not_normal(self.data.spaces[space.area].health),
            )
            for space in sorted(self._config.spaces, key=lambda s: s.area)
            if space.area in self.data.spaces
        )
        forced_key = (structure, health_layout)
        result = await async_sync_dashboard(self.hass, self)
        self._handle_dashboard_sync_outcome(forced_key, result)

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

            profile_name = self._effective_profile_name(space)
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

    def _effective_profile_name(self, space: SpaceConfig) -> str:
        """Return the active threshold profile name (YAML or runtime override)."""
        assert self._config is not None
        if space.area in self._threshold_profile_overrides:
            return self._threshold_profile_overrides[space.area]
        return space.threshold_profile or self._config.defaults.threshold_profile

    def _resolve_profile(self, space: SpaceConfig) -> dict:
        """Return the resolved threshold profile dict for a space."""
        assert self._config is not None
        profile_name = self._effective_profile_name(space)
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

            if staleness_cutoff and ha_state.last_updated < staleness_cutoff:
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
