"""High-level mutation helpers for the airquality.yaml config.

Operates on the ruamel.yaml round-trip data structure produced by yaml_io
so that the user's comments and formatting are preserved across edits.
"""
from __future__ import annotations

from typing import Any

from ruamel.yaml.comments import CommentedMap, CommentedSeq

VALID_AGGREGATIONS = (
    "single",
    "average",
    "median",
    "min",
    "max",
    "weighted_average",
    "primary_with_fallback",
)


def _root(data: Any) -> CommentedMap:
    if data is None:
        data = CommentedMap()
    if "airquality" not in data:
        data["airquality"] = CommentedMap()
    aq = data["airquality"]
    if "spaces" not in aq:
        aq["spaces"] = CommentedSeq()
    if "threshold_profiles" not in aq:
        aq["threshold_profiles"] = CommentedMap()
    if "defaults" not in aq:
        aq["defaults"] = CommentedMap(
            {
                "staleness_minutes": 15,
                "debounce_seconds": 30,
                "threshold_profile": "default",
            }
        )
    return data


def _find_space(data: Any, area_id: str) -> CommentedMap | None:
    aq = data.get("airquality", {})
    for space in aq.get("spaces") or []:
        if space.get("area") == area_id:
            return space
    return None


def _find_or_create_space(data: Any, area_id: str) -> CommentedMap:
    space = _find_space(data, area_id)
    if space is not None:
        return space
    space = CommentedMap()
    space["area"] = area_id
    space["slots"] = CommentedSeq()
    data["airquality"]["spaces"].append(space)
    return space


def _find_slot(space: CommentedMap, measurement: str) -> CommentedMap | None:
    for slot in space.get("slots") or []:
        if slot.get("measurement") == measurement:
            return slot
    return None


def add_slot(data: Any, area_id: str, measurement: str) -> Any:
    """Add an empty slot for measurement to space."""
    data = _root(data)
    space = _find_or_create_space(data, area_id)
    if _find_slot(space, measurement) is not None:
        return data
    slot = CommentedMap()
    slot["measurement"] = measurement
    slot["aggregation"] = "single"
    slot["entities"] = CommentedSeq()
    space["slots"].append(slot)
    return data


def remove_slot(data: Any, area_id: str, measurement: str) -> Any:
    """Remove a slot from a space. Removes the space too if it becomes empty."""
    data = _root(data)
    space = _find_space(data, area_id)
    if space is None:
        return data
    slots = space.get("slots") or []
    for i, slot in enumerate(slots):
        if slot.get("measurement") == measurement:
            del slots[i]
            break
    if not slots:
        spaces = data["airquality"]["spaces"]
        for i, sp in enumerate(spaces):
            if sp.get("area") == area_id:
                del spaces[i]
                break
    return data


def add_entity(
    data: Any, area_id: str, measurement: str, entity_id: str
) -> Any:
    """Append an entity to a slot, creating slot/space as needed."""
    data = _root(data)
    space = _find_or_create_space(data, area_id)
    slot = _find_slot(space, measurement)
    if slot is None:
        slot = CommentedMap()
        slot["measurement"] = measurement
        slot["aggregation"] = "single"
        slot["entities"] = CommentedSeq()
        space["slots"].append(slot)
    entities = slot.get("entities") or CommentedSeq()
    if entity_id not in entities:
        entities.append(entity_id)
        slot["entities"] = entities
    if len(entities) > 1 and slot.get("aggregation") == "single":
        slot["aggregation"] = "average"
    return data


def remove_entity(
    data: Any, area_id: str, measurement: str, entity_id: str
) -> Any:
    """Remove an entity from a slot. Removes the slot if its last entity goes."""
    data = _root(data)
    space = _find_space(data, area_id)
    if space is None:
        return data
    slot = _find_slot(space, measurement)
    if slot is None:
        return data
    entities = slot.get("entities") or []
    for i, eid in enumerate(entities):
        if eid == entity_id:
            del entities[i]
            break
    if not entities:
        return remove_slot(data, area_id, measurement)
    if len(entities) == 1 and slot.get("aggregation") in {"average", "median", "min", "max", "weighted_average"}:
        slot["aggregation"] = "single"
    return data


def set_aggregation(
    data: Any, area_id: str, measurement: str, aggregation: str
) -> Any:
    """Change a slot's aggregation strategy."""
    if aggregation not in VALID_AGGREGATIONS:
        raise ValueError(f"Unknown aggregation {aggregation!r}")
    data = _root(data)
    space = _find_space(data, area_id)
    if space is None:
        return data
    slot = _find_slot(space, measurement)
    if slot is None:
        return data
    slot["aggregation"] = aggregation
    return data


def set_space_threshold_profile(
    data: Any, area_id: str, profile_name: str | None
) -> Any:
    """Set or clear the threshold_profile for a space. Empty string clears it."""
    data = _root(data)
    space = _find_or_create_space(data, area_id)
    if profile_name:
        space["threshold_profile"] = profile_name
    elif "threshold_profile" in space:
        del space["threshold_profile"]
    return data


def set_space_name(data: Any, area_id: str, name: str | None) -> Any:
    data = _root(data)
    space = _find_or_create_space(data, area_id)
    if name:
        space["name"] = name
    elif "name" in space:
        del space["name"]
    return data


def remove_space(data: Any, area_id: str) -> Any:
    data = _root(data)
    spaces = data["airquality"].get("spaces") or []
    for i, sp in enumerate(spaces):
        if sp.get("area") == area_id:
            del spaces[i]
            break
    return data


def upsert_threshold_profile(
    data: Any, name: str, profile: dict[str, Any]
) -> Any:
    """Add or replace a named threshold profile."""
    data = _root(data)
    profiles = data["airquality"].setdefault("threshold_profiles", CommentedMap())
    profiles[name] = profile
    return data


def delete_threshold_profile(data: Any, name: str) -> Any:
    data = _root(data)
    profiles = data["airquality"].get("threshold_profiles") or {}
    if name in profiles:
        del profiles[name]
    return data


def merge_discovery_proposal(
    data: Any, proposal: dict[str, Any], *, overwrite_slots: bool = False
) -> Any:
    """Merge a discovery proposal into the active config.

    For each proposed space:
      - Create the space if it doesn't exist.
      - For each proposed slot, append entities not already present.
      - If overwrite_slots, replace the slot's entity list with the proposed one.
    """
    data = _root(data)
    proposed_spaces = (proposal.get("airquality") or {}).get("spaces") or []
    for proposed_space in proposed_spaces:
        area_id = proposed_space.get("area")
        if not area_id:
            continue
        space = _find_or_create_space(data, area_id)
        for proposed_slot in proposed_space.get("slots") or []:
            measurement = proposed_slot.get("measurement")
            if not measurement:
                continue
            existing = _find_slot(space, measurement)
            proposed_entities = list(proposed_slot.get("entities") or [])
            if existing is None:
                slot = CommentedMap()
                slot["measurement"] = measurement
                slot["aggregation"] = proposed_slot.get("aggregation", "single")
                slot["entities"] = CommentedSeq(proposed_entities)
                space["slots"].append(slot)
            elif overwrite_slots:
                existing["entities"] = CommentedSeq(proposed_entities)
                existing["aggregation"] = proposed_slot.get("aggregation", "single")
            else:
                entities = existing.get("entities") or CommentedSeq()
                for eid in proposed_entities:
                    if eid not in entities:
                        entities.append(eid)
                existing["entities"] = entities
    return data
