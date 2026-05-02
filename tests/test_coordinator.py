"""Tests for AirQualityCoordinator subscription lifecycle."""
from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.airquality.coordinator import AirQualityCoordinator
from custom_components.airquality.models import (
    AirQualityConfig,
    Defaults,
    SlotConfig,
    SpaceConfig,
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
