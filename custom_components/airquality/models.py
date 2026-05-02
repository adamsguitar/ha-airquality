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
    """Result of computing one slot's aggregated value."""
    value: float | None
    state: SlotState
    contributing_entities: list[str] = field(default_factory=list)


@dataclass
class SlotConfig:
    """Parsed configuration for a single measurement slot."""
    measurement: str
    aggregation: str
    entities: list[str]
    weights: dict[str, float] = field(default_factory=dict)
    expose_problem_binary: bool = False


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
