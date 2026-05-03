"""YAML configuration loader: file I/O, schema validation, area binding."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import area_registry as ar
from jsonschema import ValidationError, validate

from .models import AirQualityConfig, Defaults, SlotConfig, SpaceConfig

_LOGGER = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent / "schema" / "airquality.schema.json"

EXAMPLE_CONFIG = """\
# Air Quality integration configuration.
# Documentation: https://github.com/adamsguitar/ha-airquality
#
# Set 'area' to a valid Home Assistant area_id (visible in Settings > Areas).
# Add one slot per measurement type you want to track in each space.
#
# Uncomment and edit the blocks below to match your setup.

airquality:
  defaults:
    staleness_minutes: 15
    debounce_seconds: 30
    threshold_profile: default

  threshold_profiles:
    default:
      pm25:        { good: 12,  fair: 35,   poor: 55,   unhealthy: 150 }
      co2:         { good: 800, fair: 1000,  poor: 1500, unhealthy: 2500 }
      humidity:    { good_min: 30, good_max: 60, fair_min: 25, fair_max: 65 }
      temperature_f: { good_min: 68, good_max: 76, fair_min: 65, fair_max: 80 }

  spaces: []
  # spaces:
  #   - area: living_room
  #     slots:
  #       - measurement: co2
  #         aggregation: single
  #         entities:
  #           - sensor.living_room_co2
  #       - measurement: pm25
  #         aggregation: single
  #         entities:
  #           - sensor.living_room_pm25
"""


def _load_schema() -> dict:
    with _SCHEMA_PATH.open() as f:
        return json.load(f)


def _parse_config(raw: dict) -> AirQualityConfig:
    """Convert validated raw YAML dict into typed dataclasses."""
    aq = raw["airquality"]

    raw_defaults = aq.get("defaults", {})
    defaults = Defaults(
        staleness_minutes=raw_defaults.get("staleness_minutes", 15),
        debounce_seconds=raw_defaults.get("debounce_seconds", 30),
        threshold_profile=raw_defaults.get("threshold_profile", "default"),
    )

    spaces: list[SpaceConfig] = []
    for raw_space in aq.get("spaces", []):
        slots: list[SlotConfig] = []
        for raw_slot in raw_space.get("slots", []):
            slots.append(
                SlotConfig(
                    measurement=raw_slot["measurement"],
                    aggregation=raw_slot.get("aggregation", "single"),
                    entities=raw_slot["entities"],
                    weights=raw_slot.get("weights", {}),
                )
            )
        spaces.append(
            SpaceConfig(
                area=raw_space["area"],
                slots=slots,
                name=raw_space.get("name"),
                threshold_profile=raw_space.get("threshold_profile"),
            )
        )

    return AirQualityConfig(
        defaults=defaults,
        threshold_profiles=aq.get("threshold_profiles", {}),
        spaces=spaces,
    )


def _validate_threshold_profile_references(config: AirQualityConfig) -> None:
    """Ensure all profile references exist and extends chains are acyclic."""
    profiles = config.threshold_profiles
    default_profile = config.defaults.threshold_profile

    if default_profile not in profiles and profiles:
        _LOGGER.warning(
            "Default threshold_profile %r is not defined in threshold_profiles. "
            "Health computation will fall back to built-in defaults.",
            default_profile,
        )

    for name, profile in profiles.items():
        parent = profile.get("extends")
        if parent and parent not in profiles:
            raise ConfigEntryError(
                f"Threshold profile {name!r} extends {parent!r}, "
                f"but {parent!r} is not defined."
            )

    for space in config.spaces:
        profile_name = space.threshold_profile or default_profile
        if profile_name not in profiles and profiles:
            _LOGGER.warning(
                "Space %r references threshold_profile %r which is not defined.",
                space.area,
                profile_name,
            )


def _resolve_profile_inheritance(profiles: dict[str, dict]) -> dict[str, dict]:
    """Flatten profile inheritance chains into resolved profiles.

    Single inheritance only: each profile may specify 'extends' pointing to one
    parent. Resolution is eager — the returned dict contains only flat profiles
    with no 'extends' key.
    """
    resolved: dict[str, dict] = {}

    def resolve(name: str, seen: set[str]) -> dict:
        if name in resolved:
            return resolved[name]
        if name in seen:
            raise ConfigEntryError(
                f"Circular threshold_profile inheritance detected involving {name!r}."
            )
        raw = profiles.get(name, {})
        parent_name = raw.get("extends")
        if parent_name:
            parent = resolve(parent_name, seen | {name})
            merged = {k: v for k, v in parent.items()}
            merged.update({k: v for k, v in raw.items() if k != "extends"})
        else:
            merged = {k: v for k, v in raw.items() if k != "extends"}
        resolved[name] = merged
        return merged

    for name in profiles:
        resolve(name, set())

    return resolved


async def async_load_config(hass: HomeAssistant, yaml_path: Path) -> AirQualityConfig:
    """Load, validate, and return the typed integration config.

    Raises ConfigEntryError on any structural or semantic error so the config
    entry fails with a clear UI message rather than a traceback.
    """
    if not yaml_path.exists():
        _LOGGER.info(
            "No configuration found at %s — creating example configuration.", yaml_path
        )
        try:
            yaml_path.write_text(EXAMPLE_CONFIG, encoding="utf-8")
        except OSError as err:
            raise ConfigEntryError(
                f"Could not create example config at {yaml_path}: {err}"
            ) from err

    try:
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as err:
        raise ConfigEntryError(
            f"Could not parse {yaml_path}: {err}"
        ) from err

    if raw is None:
        raise ConfigEntryError(f"{yaml_path} is empty.")

    try:
        schema = _load_schema()
        validate(instance=raw, schema=schema)
    except ValidationError as err:
        raise ConfigEntryError(
            f"Schema validation failed: {err.message} (path: {list(err.absolute_path)})"
        ) from err

    config = _parse_config(raw)

    # Validate area references against the HA registry.
    registry = ar.async_get(hass)
    unknown_areas = [
        space.area
        for space in config.spaces
        if registry.async_get_area(space.area) is None
    ]
    if unknown_areas:
        raise ConfigEntryError(
            f"The following area_id values are not found in Home Assistant's area "
            f"registry: {unknown_areas}. Check Settings > Areas for valid IDs."
        )

    _validate_threshold_profile_references(config)

    config.threshold_profiles = _resolve_profile_inheritance(config.threshold_profiles)

    _LOGGER.debug(
        "Loaded air quality config: %d space(s), %d profile(s).",
        len(config.spaces),
        len(config.threshold_profiles),
    )
    return config
