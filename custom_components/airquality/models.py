"""Typed dataclasses representing the loaded configuration and runtime state."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SlotState(str, Enum):
    """Runtime state of a single slot computation."""
    OK = "ok"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


@dataclass
class SlotData:
    """Result of computing one slot's aggregated value and its health classification."""
    value: float | None
    state: SlotState
    health: str  # one of HEALTH_* constants
    contributing_entities: list[str] = field(default_factory=list)


@dataclass
class SpaceHealth:
    """Rolled-up health for a single space, plus per-slot details for diagnostics."""
    area_id: str
    name: str
    floor_id: str | None
    health: str
    slot_healths: dict[str, str] = field(default_factory=dict)
    slot_values: dict[str, float | None] = field(default_factory=dict)


@dataclass
class FloorHealth:
    """Rolled-up health for a floor, computed from the spaces assigned to it."""
    floor_id: str
    name: str
    health: str
    space_healths: dict[str, str] = field(default_factory=dict)


@dataclass
class HomeHealth:
    """Whole-home rollup. Includes floor healths and any orphan spaces (no floor)."""
    health: str
    floor_healths: dict[str, str] = field(default_factory=dict)
    orphan_space_healths: dict[str, str] = field(default_factory=dict)


@dataclass
class CoordinatorState:
    """The complete computed state the coordinator publishes to entities."""
    slots: dict[tuple[str, str], SlotData] = field(default_factory=dict)
    spaces: dict[str, SpaceHealth] = field(default_factory=dict)
    floors: dict[str, FloorHealth] = field(default_factory=dict)
    home: HomeHealth | None = None


@dataclass
class SlotConfig:
    """Parsed configuration for a single measurement slot."""
    measurement: str
    aggregation: str
    entities: list[str]
    weights: dict[str, float] = field(default_factory=dict)


@dataclass
class SpaceConfig:
    """Parsed configuration for a single monitored space."""
    area: str
    slots: list[SlotConfig]
    name: str | None = None
    threshold_profile: str | None = None


@dataclass
class Defaults:
    """Integration-wide defaults parsed from the 'defaults' block."""
    staleness_minutes: int = 15
    debounce_seconds: int = 30
    threshold_profile: str = "default"


@dataclass
class AirQualityConfig:
    """Top-level parsed configuration."""
    defaults: Defaults
    threshold_profiles: dict[str, dict]
    spaces: list[SpaceConfig]
