"""Tests for AirQualityCoordinator subscription lifecycle and slot computation."""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.airquality.const import HEALTH_STALE, HEALTH_UNAVAILABLE
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
