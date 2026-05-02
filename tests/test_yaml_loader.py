"""Tests for yaml_loader: schema validation, area binding, profile inheritance."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from homeassistant.exceptions import ConfigEntryError

from custom_components.airquality.yaml_loader import async_load_config

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _make_hass_with_areas(area_ids: list[str]) -> MagicMock:
    """Build a minimal hass mock with a stubbed area registry."""
    hass = MagicMock()
    hass.config.config_dir = "/config"

    area_map = {aid: MagicMock(area_id=aid, name=aid.replace("_", " ").title()) for aid in area_ids}

    registry = MagicMock()
    registry.async_get_area = lambda area_id: area_map.get(area_id)

    with patch(
        "custom_components.airquality.yaml_loader.ar.async_get",
        return_value=registry,
    ):
        return hass


@pytest.fixture
def valid_yaml_path(tmp_path: Path) -> Path:
    """Write the fixture YAML to a temp file and return its path."""
    content = (FIXTURE_DIR / "example.yaml").read_text()
    p = tmp_path / "airquality.yaml"
    p.write_text(content)
    return p


@pytest.mark.asyncio
async def test_valid_fixture_loads(valid_yaml_path: Path) -> None:
    """The fixture YAML should parse without errors into a valid config."""
    hass = MagicMock()
    hass.config.config_dir = str(valid_yaml_path.parent)

    area_ids = ["living_room", "kids_bedroom"]
    area_map = {aid: MagicMock(area_id=aid, name=aid.title()) for aid in area_ids}
    registry = MagicMock()
    registry.async_get_area = lambda aid: area_map.get(aid)

    with patch(
        "custom_components.airquality.yaml_loader.ar.async_get",
        return_value=registry,
    ):
        config = await async_load_config(hass, valid_yaml_path)

    assert len(config.spaces) == 2
    assert config.spaces[0].area == "living_room"
    assert len(config.spaces[0].slots) == 2
    assert config.spaces[1].area == "kids_bedroom"
    assert config.defaults.staleness_minutes == 15
    assert config.defaults.debounce_seconds == 30


@pytest.mark.asyncio
async def test_profile_inheritance_resolved(valid_yaml_path: Path) -> None:
    """Kids_room profile should have pm25 overridden and co2 inherited from default."""
    hass = MagicMock()
    area_ids = ["living_room", "kids_bedroom"]
    area_map = {aid: MagicMock(area_id=aid, name=aid.title()) for aid in area_ids}
    registry = MagicMock()
    registry.async_get_area = lambda aid: area_map.get(aid)

    with patch(
        "custom_components.airquality.yaml_loader.ar.async_get",
        return_value=registry,
    ):
        config = await async_load_config(hass, valid_yaml_path)

    kids = config.threshold_profiles.get("kids_room", {})
    assert kids.get("pm25") == {"good": 9, "fair": 25, "poor": 45, "unhealthy": 100}
    # co2 thresholds inherited from default
    assert "co2" in kids
    assert kids["co2"]["good"] == 800


@pytest.mark.asyncio
async def test_unknown_area_raises(valid_yaml_path: Path) -> None:
    """A space referencing a non-existent area_id should raise ConfigEntryError."""
    hass = MagicMock()
    registry = MagicMock()
    registry.async_get_area = lambda _: None  # all areas unknown

    with patch(
        "custom_components.airquality.yaml_loader.ar.async_get",
        return_value=registry,
    ):
        with pytest.raises(ConfigEntryError, match="area_id values are not found"):
            await async_load_config(hass, valid_yaml_path)


@pytest.mark.asyncio
async def test_invalid_schema_raises(tmp_path: Path) -> None:
    """A YAML file that fails JSON Schema validation should raise ConfigEntryError."""
    bad_yaml = tmp_path / "airquality.yaml"
    bad_yaml.write_text("airquality:\n  spaces:\n    - area: 123\n      slots: []\n")

    hass = MagicMock()
    registry = MagicMock()
    registry.async_get_area = lambda _: None

    with patch(
        "custom_components.airquality.yaml_loader.ar.async_get",
        return_value=registry,
    ):
        with pytest.raises(ConfigEntryError, match="Schema validation failed"):
            await async_load_config(hass, bad_yaml)


@pytest.mark.asyncio
async def test_missing_file_creates_example(tmp_path: Path) -> None:
    """If airquality.yaml is absent, an example should be created and loaded."""
    yaml_path = tmp_path / "airquality.yaml"
    assert not yaml_path.exists()

    hass = MagicMock()
    registry = MagicMock()
    # The example has spaces: [], so area validation is a no-op.
    registry.async_get_area = lambda aid: MagicMock(area_id=aid, name=aid.title())

    with patch(
        "custom_components.airquality.yaml_loader.ar.async_get",
        return_value=registry,
    ):
        config = await async_load_config(hass, yaml_path)

    assert yaml_path.exists(), "Example file should have been created"
    assert config.spaces == [], "Example config has an empty spaces list"


@pytest.mark.asyncio
async def test_circular_profile_inheritance_raises(tmp_path: Path) -> None:
    """A circular extends chain should raise ConfigEntryError."""
    circular = {
        "airquality": {
            "threshold_profiles": {
                "a": {"extends": "b", "pm25": {"good": 1, "fair": 2, "poor": 3, "unhealthy": 4}},
                "b": {"extends": "a", "pm25": {"good": 1, "fair": 2, "poor": 3, "unhealthy": 4}},
            },
            "spaces": [],
        }
    }
    yaml_path = tmp_path / "airquality.yaml"
    yaml_path.write_text(yaml.dump(circular))

    hass = MagicMock()
    registry = MagicMock()
    registry.async_get_area = lambda aid: MagicMock(area_id=aid)

    with patch(
        "custom_components.airquality.yaml_loader.ar.async_get",
        return_value=registry,
    ):
        with pytest.raises(ConfigEntryError, match="Circular"):
            await async_load_config(hass, yaml_path)
