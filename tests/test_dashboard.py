"""Tests for managed Lovelace dashboard config builder."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.airquality.const import DASHBOARD_URL_PATH, HEALTH_GOOD, HEALTH_POOR
from custom_components.airquality.dashboard import (
    _space_not_normal,
    async_sync_dashboard,
    build_lovelace_config,
)
from custom_components.airquality.models import (
    AirQualityConfig,
    CoordinatorState,
    Defaults,
    SlotConfig,
    SpaceConfig,
    SpaceHealth,
)


def test_space_not_normal():
    assert _space_not_normal(HEALTH_GOOD) is False
    assert _space_not_normal(HEALTH_POOR) is True


def test_build_lovelace_config_room_order_and_section_background():
    hass = MagicMock()
    area_reg = MagicMock()

    def _area(aid: str):
        m = MagicMock()
        m.name = {"a": "Bedroom", "b": "Kitchen"}.get(aid, aid)
        return m

    area_reg.async_get_area.side_effect = _area

    slots_a = [
        SlotConfig(measurement="pm25", aggregation="single", entities=["sensor.x"]),
    ]
    slots_b = [
        SlotConfig(measurement="co2", aggregation="single", entities=["sensor.y"]),
    ]
    config = AirQualityConfig(
        defaults=Defaults(),
        threshold_profiles={},
        spaces=[
            SpaceConfig(area="a", slots=slots_a),
            SpaceConfig(area="b", slots=slots_b),
        ],
    )

    area_health = {"a": HEALTH_GOOD, "b": HEALTH_POOR}

    with patch("homeassistant.helpers.area_registry.async_get", return_value=area_reg):
        ll = build_lovelace_config(
            config=config,
            hass=hass,
            area_health=area_health,
            slot_entity_ids={
                ("a", "pm25"): "sensor.airquality_a_pm25",
                ("b", "co2"): "sensor.airquality_b_co2",
            },
            overall_entity_ids={"a": "sensor.a_overall", "b": "sensor.b_overall"},
            problem_entity_ids={
                "a": "binary_sensor.a_problem",
                "b": "binary_sensor.b_problem",
            },
            home_overall_entity_id="sensor.home_overall",
            home_problem_entity_id="binary_sensor.home_problem",
        )

    view = ll["views"][0]
    sections = view["sections"]
    assert len(sections) == 2

    assert view["header"]["layout"] == "responsive"
    hdr = view["header"]["card"]
    assert hdr["type"] == "markdown"
    assert "## Household" in hdr["content"]
    assert "states('sensor.home_overall')" in hdr["content"]
    assert "sensor.a_overall" in hdr["content"] and "sensor.b_overall" in hdr["content"]
    assert view["badges"][0]["entity"] == "sensor.home_overall"
    assert view["badges"][1]["entity"] == "binary_sensor.home_problem"

    first_heading = sections[0]["cards"][0]["heading"]
    assert first_heading == "Kitchen"
    meas = sections[0]["cards"][2]
    assert meas["type"] == "grid"
    assert meas["columns"] == 2
    assert meas["cards"][0]["type"] == "tile"
    assert meas["cards"][0]["entity"] == "sensor.airquality_b_co2"
    assert meas["cards"][0]["state_content"] == ["state", "health"]
    assert "background" in sections[0]
    assert "background" not in sections[1]


@pytest.mark.asyncio
async def test_async_sync_dashboard_skipped_when_lovelace_not_bootstrapped(
    hass,
    mock_config_entry,
) -> None:
    mock_config_entry.add_to_hass(hass)
    hass.data.pop("lovelace", None)

    from custom_components.airquality.coordinator import AirQualityCoordinator

    coordinator = AirQualityCoordinator(hass, mock_config_entry)
    coordinator._config = AirQualityConfig(
        defaults=Defaults(debounce_seconds=5),
        threshold_profiles={},
        spaces=[
            SpaceConfig(
                area="a",
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
    coordinator.data = CoordinatorState()
    coordinator.data.spaces["a"] = SpaceHealth(
        area_id="a",
        name="A",
        floor_id=None,
        health=HEALTH_GOOD,
    )

    with (
        patch(
            "custom_components.airquality.dashboard.async_hass_config_yaml",
            AsyncMock(return_value={}),
        ),
        patch(
            "custom_components.airquality.dashboard.async_setup_component",
            AsyncMock(return_value=False),
        ),
    ):
        result = await async_sync_dashboard(hass, coordinator)

    assert result.status == "skipped"
    assert result.skip_reason == "lovelace_unavailable"
    assert result.detail and "dashboards integration" in result.detail


@pytest.mark.asyncio
async def test_async_sync_dashboard_bootstraps_lovelace_when_missing(
    hass,
    mock_config_entry,
) -> None:
    mock_config_entry.add_to_hass(hass)
    hass.data.pop("lovelace", None)

    from custom_components.airquality.coordinator import AirQualityCoordinator

    coordinator = AirQualityCoordinator(hass, mock_config_entry)
    coordinator._config = AirQualityConfig(
        defaults=Defaults(debounce_seconds=5),
        threshold_profiles={},
        spaces=[
            SpaceConfig(
                area="a",
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
    coordinator.data = CoordinatorState()
    coordinator.data.spaces["a"] = SpaceHealth(
        area_id="a",
        name="A",
        floor_id=None,
        health=HEALTH_GOOD,
    )

    store = MagicMock()
    store.async_save = AsyncMock()

    async def _fake_setup_lovelace(
        _hass: object, domain: str, _config: dict
    ) -> bool:
        if domain == "lovelace":
            hass.data["lovelace"] = {"dashboards": {DASHBOARD_URL_PATH: store}}
            return True
        return True

    er = MagicMock()

    def _get_eid(_domain: str, _platform: str, unique_id: str) -> str | None:
        mapping = {
            f"{mock_config_entry.entry_id}::a::co2": "sensor.slot_a_co2",
            f"{mock_config_entry.entry_id}::a::overall": "sensor.overall_a",
            f"{mock_config_entry.entry_id}::a::problem": "binary_sensor.prob_a",
            f"{mock_config_entry.entry_id}::home::overall": "sensor.home_overall",
            f"{mock_config_entry.entry_id}::home::problem": "binary_sensor.home_problem",
        }
        return mapping.get(unique_id)

    er.async_get_entity_id.side_effect = _get_eid

    area_reg = MagicMock()
    a = MagicMock()
    a.name = "Room A"
    area_reg.async_get_area.return_value = a

    with (
        patch(
            "custom_components.airquality.dashboard.async_hass_config_yaml",
            AsyncMock(return_value={}),
        ),
        patch(
            "custom_components.airquality.dashboard.async_setup_component",
            side_effect=_fake_setup_lovelace,
        ),
        patch("homeassistant.helpers.area_registry.async_get", return_value=area_reg),
        patch("homeassistant.helpers.entity_registry.async_get", return_value=er),
    ):
        result = await async_sync_dashboard(hass, coordinator)

    assert result.status == "ok"
    store.async_save.assert_awaited_once()
    saved = store.async_save.call_args[0][0]
    assert saved["views"][0]["header"]["card"]["type"] == "markdown"
    assert "## Household" in saved["views"][0]["header"]["card"]["content"]


@pytest.mark.asyncio
async def test_async_sync_dashboard_saves_when_storage_exists(
    hass,
    mock_config_entry,
) -> None:
    mock_config_entry.add_to_hass(hass)
    store = MagicMock()
    store.async_save = AsyncMock()
    hass.data["lovelace"] = {"dashboards": {DASHBOARD_URL_PATH: store}}

    from custom_components.airquality.coordinator import AirQualityCoordinator

    coordinator = AirQualityCoordinator(hass, mock_config_entry)
    coordinator._config = AirQualityConfig(
        defaults=Defaults(debounce_seconds=5),
        threshold_profiles={},
        spaces=[
            SpaceConfig(
                area="a",
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
    coordinator.data = CoordinatorState()
    coordinator.data.spaces["a"] = SpaceHealth(
        area_id="a",
        name="A",
        floor_id=None,
        health=HEALTH_GOOD,
    )

    er = MagicMock()

    def _get_eid(_domain: str, _platform: str, unique_id: str) -> str | None:
        mapping = {
            f"{mock_config_entry.entry_id}::a::co2": "sensor.slot_a_co2",
            f"{mock_config_entry.entry_id}::a::overall": "sensor.overall_a",
            f"{mock_config_entry.entry_id}::a::problem": "binary_sensor.prob_a",
            f"{mock_config_entry.entry_id}::home::overall": "sensor.home_overall",
            f"{mock_config_entry.entry_id}::home::problem": "binary_sensor.home_problem",
        }
        return mapping.get(unique_id)

    er.async_get_entity_id.side_effect = _get_eid

    area_reg = MagicMock()
    a = MagicMock()
    a.name = "Room A"
    area_reg.async_get_area.return_value = a

    with (
        patch("homeassistant.helpers.area_registry.async_get", return_value=area_reg),
        patch("homeassistant.helpers.entity_registry.async_get", return_value=er),
    ):
        result = await async_sync_dashboard(hass, coordinator)

    assert result.status == "ok"
    store.async_save.assert_awaited_once()
    saved = store.async_save.call_args[0][0]
    assert saved["views"][0]["header"]["card"]["type"] == "markdown"
    assert "## Household" in saved["views"][0]["header"]["card"]["content"]


@pytest.mark.asyncio
async def test_async_sync_dashboard_saves_with_lovelace_dataclass_shape(
    hass,
    mock_config_entry,
) -> None:
    """Newer HA may store hass.data['lovelace'] as an object with .dashboards, not dict."""
    mock_config_entry.add_to_hass(hass)
    store = MagicMock()
    store.async_save = AsyncMock()
    dashboards: dict = {DASHBOARD_URL_PATH: store}
    ll_state = SimpleNamespace(dashboards=dashboards, dashboards_collection=None)
    hass.data["lovelace"] = ll_state

    from custom_components.airquality.coordinator import AirQualityCoordinator

    coordinator = AirQualityCoordinator(hass, mock_config_entry)
    coordinator._config = AirQualityConfig(
        defaults=Defaults(debounce_seconds=5),
        threshold_profiles={},
        spaces=[
            SpaceConfig(
                area="a",
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
    coordinator.data = CoordinatorState()
    coordinator.data.spaces["a"] = SpaceHealth(
        area_id="a",
        name="A",
        floor_id=None,
        health=HEALTH_GOOD,
    )

    er = MagicMock()

    def _get_eid(_domain: str, _platform: str, unique_id: str) -> str | None:
        mapping = {
            f"{mock_config_entry.entry_id}::a::co2": "sensor.slot_a_co2",
            f"{mock_config_entry.entry_id}::a::overall": "sensor.overall_a",
            f"{mock_config_entry.entry_id}::a::problem": "binary_sensor.prob_a",
            f"{mock_config_entry.entry_id}::home::overall": "sensor.home_overall",
            f"{mock_config_entry.entry_id}::home::problem": "binary_sensor.home_problem",
        }
        return mapping.get(unique_id)

    er.async_get_entity_id.side_effect = _get_eid

    area_reg = MagicMock()
    a = MagicMock()
    a.name = "Room A"
    area_reg.async_get_area.return_value = a

    with (
        patch("homeassistant.helpers.area_registry.async_get", return_value=area_reg),
        patch("homeassistant.helpers.entity_registry.async_get", return_value=er),
    ):
        result = await async_sync_dashboard(hass, coordinator)

    assert result.status == "ok"
    store.async_save.assert_awaited_once()
    saved = store.async_save.call_args[0][0]
    assert saved["views"][0]["header"]["card"]["type"] == "markdown"
    assert "## Household" in saved["views"][0]["header"]["card"]["content"]
