"""Tests for AirQualityCoordinator subscription lifecycle and slot computation."""
from __future__ import annotations

import logging
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from custom_components.airquality.const import (
    HEALTH_GOOD,
    HEALTH_POOR,
    HEALTH_STALE,
    HEALTH_UNAVAILABLE,
)
from custom_components.airquality.coordinator import AirQualityCoordinator
from custom_components.airquality.models import (
    AirQualityConfig,
    Defaults,
    SlotConfig,
    SpaceConfig,
    SlotState,
)


def _config(*entity_ids: str, debounce_seconds: int = 30) -> AirQualityConfig:
    """Build a minimal coordinator config for subscription tests."""
    return AirQualityConfig(
        defaults=Defaults(debounce_seconds=debounce_seconds),
        threshold_profiles={},
        spaces=[
            SpaceConfig(
                area="living_room",
                slots=[
                    SlotConfig(
                        measurement="co2",
                        aggregation="single",
                        entities=list(entity_ids),
                    )
                ],
            )
        ],
    )


@pytest.mark.asyncio
async def test_reload_replaces_existing_source_subscription(
    hass, mock_config_entry
) -> None:
    """Reload should remove the old listener/debouncer before subscribing again."""
    mock_config_entry.add_to_hass(hass)
    coordinator = AirQualityCoordinator(hass, mock_config_entry)
    coordinator._config = _config("sensor.old_co2", debounce_seconds=5)
    coordinator.async_refresh = AsyncMock()

    subscriptions: list[tuple[list[str], Mock]] = []
    debouncers: list[Mock] = []

    def _track_state_change(_hass, entity_ids, _handler):  # noqa: ANN001
        unsub = Mock()
        subscriptions.append((entity_ids, unsub))
        return unsub

    def _make_debouncer(*_args, **_kwargs) -> Mock:
        debouncer = Mock()
        debouncer.async_call = AsyncMock()
        debouncer.async_shutdown = AsyncMock()
        debouncers.append(debouncer)
        return debouncer

    with (
        patch(
            "custom_components.airquality.coordinator.async_track_state_change_event",
            side_effect=_track_state_change,
        ),
        patch(
            "custom_components.airquality.coordinator.Debouncer",
            side_effect=_make_debouncer,
        ),
        patch(
            "custom_components.airquality.coordinator.async_load_config",
            AsyncMock(return_value=_config("sensor.new_co2", debounce_seconds=7)),
        ),
    ):
        coordinator._subscribe_to_source_entities()
        await coordinator.async_reload_config()

    assert subscriptions == [
        (["sensor.old_co2"], subscriptions[0][1]),
        (["sensor.new_co2"], subscriptions[1][1]),
    ]
    subscriptions[0][1].assert_called_once_with()
    subscriptions[1][1].assert_not_called()
    debouncers[0].async_shutdown.assert_awaited_once_with()
    debouncers[1].async_shutdown.assert_not_awaited()
    coordinator.async_refresh.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_compute_slot_staleness_uses_last_updated_not_last_changed(
    hass, mock_config_entry
) -> None:
    """Steady sensor values update last_updated but not last_changed; do not flag as stale."""
    mock_config_entry.add_to_hass(hass)
    coordinator = AirQualityCoordinator(hass, mock_config_entry)
    now = dt_util.utcnow()
    hass.states.async_set("sensor.temp", "72")
    # Simulate HA behavior: value unchanged for a long time but device still reports.
    state = hass.states.get("sensor.temp")
    object.__setattr__(state, "last_changed", now - timedelta(hours=6))
    object.__setattr__(state, "last_updated", now - timedelta(minutes=1))

    coordinator._config = AirQualityConfig(
        defaults=Defaults(staleness_minutes=15, debounce_seconds=5),
        threshold_profiles={"default": {}},
        spaces=[
            SpaceConfig(
                area="living_room",
                slots=[
                    SlotConfig(
                        measurement="temperature",
                        aggregation="single",
                        entities=["sensor.temp"],
                    )
                ],
            )
        ],
    )

    slot = coordinator._config.spaces[0].slots[0]
    space = coordinator._config.spaces[0]
    profile = coordinator._resolve_profile(space)

    slot_data = coordinator._compute_slot(space, slot, profile)

    assert slot_data.state == SlotState.OK
    assert slot_data.value == 72.0
    assert "sensor.temp" in slot_data.contributing_entities


@pytest.mark.asyncio
async def test_compute_slot_stale_when_last_updated_exceeds_window(
    hass, mock_config_entry
) -> None:
    """When last_updated is older than staleness_minutes, the slot is stale."""
    mock_config_entry.add_to_hass(hass)
    coordinator = AirQualityCoordinator(hass, mock_config_entry)
    now = dt_util.utcnow()
    hass.states.async_set("sensor.temp", "72")
    state = hass.states.get("sensor.temp")
    object.__setattr__(state, "last_changed", now - timedelta(minutes=20))
    object.__setattr__(state, "last_updated", now - timedelta(minutes=20))

    coordinator._config = AirQualityConfig(
        defaults=Defaults(staleness_minutes=15, debounce_seconds=5),
        threshold_profiles={"default": {}},
        spaces=[
            SpaceConfig(
                area="living_room",
                slots=[
                    SlotConfig(
                        measurement="temperature",
                        aggregation="single",
                        entities=["sensor.temp"],
                    )
                ],
            )
        ],
    )

    slot = coordinator._config.spaces[0].slots[0]
    space = coordinator._config.spaces[0]
    profile = coordinator._resolve_profile(space)

    slot_data = coordinator._compute_slot(space, slot, profile)

    assert slot_data.state == SlotState.STALE
    assert slot_data.value is None
    assert slot_data.health == HEALTH_STALE


def test_compute_slot_staleness_with_mock_state_no_hass_mutation() -> None:
    """Regression: last_changed may be ancient while last_updated is fresh (mocked hass)."""
    hass = Mock()
    hass.config.config_dir = "/tmp"
    now = dt_util.utcnow()
    hass.states.get.return_value = SimpleNamespace(
        state="72",
        last_changed=now - timedelta(days=1),
        last_updated=now - timedelta(seconds=30),
    )
    entry = Mock()
    coordinator = AirQualityCoordinator(hass, entry)
    coordinator._config = AirQualityConfig(
        defaults=Defaults(staleness_minutes=15, debounce_seconds=5),
        threshold_profiles={"default": {}},
        spaces=[
            SpaceConfig(
                area="living_room",
                slots=[
                    SlotConfig(
                        measurement="temperature",
                        aggregation="single",
                        entities=["sensor.temp"],
                    )
                ],
            )
        ],
    )
    space = coordinator._config.spaces[0]
    slot = space.slots[0]
    slot_data = coordinator._compute_slot(space, slot, coordinator._resolve_profile(space))
    assert slot_data.state == SlotState.OK
    assert slot_data.value == 72.0

    hass.states.get.return_value = SimpleNamespace(
        state="72",
        last_changed=now - timedelta(minutes=1),
        last_updated=now - timedelta(minutes=20),
    )
    slot_data = coordinator._compute_slot(space, slot, coordinator._resolve_profile(space))
    assert slot_data.state == SlotState.STALE
    assert slot_data.health == HEALTH_STALE

    hass.states.get.return_value = None
    slot_data = coordinator._compute_slot(space, slot, coordinator._resolve_profile(space))
    assert slot_data.state == SlotState.UNAVAILABLE
    assert slot_data.health == HEALTH_UNAVAILABLE


@pytest.mark.asyncio
async def test_threshold_profile_override_changes_slot_health(
    hass, mock_config_entry
) -> None:
    """Runtime override must use the named profile from YAML for health evaluation."""
    mock_config_entry.add_to_hass(hass)
    coordinator = AirQualityCoordinator(hass, mock_config_entry)
    hass.states.async_set("sensor.co2", "801")

    coordinator._config = AirQualityConfig(
        defaults=Defaults(threshold_profile="strict", debounce_seconds=5),
        threshold_profiles={
            "strict": {"co2": {"good": 600, "fair": 800, "poor": 1000, "unhealthy": 1500}},
            "lenient": {"co2": {"good": 1000, "fair": 1200, "poor": 1400, "unhealthy": 2000}},
        },
        spaces=[
            SpaceConfig(
                area="living_room",
                slots=[
                    SlotConfig(
                        measurement="co2",
                        aggregation="single",
                        entities=["sensor.co2"],
                    )
                ],
            )
        ],
    )

    space = coordinator._config.spaces[0]
    slot = space.slots[0]

    assert coordinator._resolve_profile(space)["co2"]["good"] == 600
    slot_data = coordinator._compute_slot(space, slot, coordinator._resolve_profile(space))
    assert slot_data.health == HEALTH_POOR  # above strict "fair" (800), at or below "poor"

    await coordinator.async_set_threshold_profile_override("living_room", "lenient")
    slot_data = coordinator._compute_slot(space, slot, coordinator._resolve_profile(space))
    assert slot_data.health == HEALTH_GOOD


@pytest.mark.asyncio
async def test_threshold_profile_override_cleared_on_reload(
    hass, mock_config_entry
) -> None:
    """YAML reload clears transient overrides."""
    mock_config_entry.add_to_hass(hass)
    coordinator = AirQualityCoordinator(hass, mock_config_entry)
    coordinator._config = AirQualityConfig(
        defaults=Defaults(debounce_seconds=5),
        threshold_profiles={
            "a": {"co2": {"good": 1, "fair": 2, "poor": 3, "unhealthy": 4}},
            "b": {"co2": {"good": 10, "fair": 20, "poor": 30, "unhealthy": 40}},
        },
        spaces=[
            SpaceConfig(
                area="living_room",
                slots=[
                    SlotConfig(
                        measurement="co2",
                        aggregation="single",
                        entities=["sensor.x"],
                    )
                ],
            )
        ],
    )
    await coordinator.async_set_threshold_profile_override("living_room", "b")
    assert coordinator.threshold_profile_overrides == {"living_room": "b"}

    coordinator.async_refresh = AsyncMock()

    with patch(
        "custom_components.airquality.coordinator.async_load_config",
        AsyncMock(return_value=coordinator._config),
    ):
        await coordinator.async_reload_config()

    assert coordinator.threshold_profile_overrides == {}
    coordinator.async_refresh.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_reload_logs_and_aborts_when_refresh_raises(
    hass, mock_config_entry, caplog
) -> None:
    """Reload must not propagate refresh failures — add-on callers must not receive HTTP 500."""
    mock_config_entry.add_to_hass(hass)
    coordinator = AirQualityCoordinator(hass, mock_config_entry)
    coordinator._config = _config("sensor.old_co2", debounce_seconds=5)
    coordinator.async_refresh = AsyncMock(side_effect=RuntimeError("simulated refresh failure"))

    with (
        patch(
            "custom_components.airquality.coordinator.async_track_state_change_event",
            return_value=Mock(),
        ),
        patch(
            "custom_components.airquality.coordinator.Debouncer",
            return_value=Mock(async_call=AsyncMock(), async_shutdown=AsyncMock()),
        ),
        patch(
            "custom_components.airquality.coordinator.async_load_config",
            AsyncMock(return_value=_config("sensor.new_co2", debounce_seconds=5)),
        ),
        caplog.at_level(logging.ERROR),
    ):
        await coordinator.async_reload_config()

    coordinator.async_refresh.assert_awaited_once_with()
    assert "Air Quality refresh failed after configuration reload" in caplog.text


@pytest.mark.asyncio
async def test_reload_keeps_previous_config_when_load_fails(
    hass, mock_config_entry
) -> None:
    """If async_load_config raises, the coordinator keeps its current config and does not crash."""
    mock_config_entry.add_to_hass(hass)
    coordinator = AirQualityCoordinator(hass, mock_config_entry)
    original_config = _config("sensor.co2")
    coordinator._config = original_config
    coordinator.async_refresh = AsyncMock()

    with patch(
        "custom_components.airquality.coordinator.async_load_config",
        AsyncMock(side_effect=HomeAssistantError("area 'missing_room' not found")),
    ):
        await coordinator.async_reload_config()

    assert coordinator._config is original_config
    coordinator.async_refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_threshold_profile_override_validates_area_and_profile(
    hass, mock_config_entry
) -> None:
    """Invalid area_id or profile name must raise."""
    mock_config_entry.add_to_hass(hass)
    coordinator = AirQualityCoordinator(hass, mock_config_entry)
    coordinator._config = AirQualityConfig(
        defaults=Defaults(debounce_seconds=5),
        threshold_profiles={"only": {}},
        spaces=[SpaceConfig(area="living_room", slots=[])],
    )

    with pytest.raises(HomeAssistantError, match="Unknown area_id"):
        await coordinator.async_set_threshold_profile_override("bedroom", "only")

    with pytest.raises(HomeAssistantError, match="Unknown threshold profile"):
        await coordinator.async_set_threshold_profile_override("living_room", "missing")
