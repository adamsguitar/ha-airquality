"""Create and refresh the managed Lovelace dashboard (storage mode)."""
from __future__ import annotations

import logging
import traceback
from typing import TYPE_CHECKING, Any

from homeassistant.components import frontend
from homeassistant.config import async_hass_config_yaml
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component

from .const import DASHBOARD_TITLE, DASHBOARD_URL_PATH, DOMAIN
from .dashboard_sync import DashboardSyncResult
from .health import is_problem
from .measurement_labels import measurement_label

if TYPE_CHECKING:
    from .coordinator import AirQualityCoordinator
    from .models import AirQualityConfig, SpaceConfig

from .const import HEALTH_FAIR, HEALTH_GOOD

_LOGGER = logging.getLogger(__name__)

PROBLEM_SECTION_BG_COLOR = "warning"
PROBLEM_SECTION_BG_OPACITY = 35


def _space_not_normal(health: str) -> bool:
    """True when the room should surface as needing attention on the dashboard."""
    if health in (HEALTH_GOOD, HEALTH_FAIR):
        return False
    if is_problem(health):
        return True
    return health not in (HEALTH_GOOD, HEALTH_FAIR)


def build_lovelace_config(
    *,
    config: AirQualityConfig,
    hass: HomeAssistant,
    area_health: dict[str, str],
    slot_entity_ids: dict[tuple[str, str], str],
    overall_entity_ids: dict[str, str],
    problem_entity_ids: dict[str, str],
) -> dict[str, Any]:
    """Build Lovelace dashboard JSON (single sections view)."""

    from homeassistant.helpers import area_registry as ar  # noqa: PLC0415

    def room_sort_key(space: SpaceConfig) -> tuple[int, str]:
        health_val = area_health.get(space.area, "")
        attention = 0 if _space_not_normal(health_val) else 1

        area_reg = ar.async_get(hass)
        ha_area = area_reg.async_get_area(space.area)
        name = space.name or (ha_area.name if ha_area else space.area)
        return (attention, name.lower())

    spaces_sorted = sorted(config.spaces, key=room_sort_key)
    sections: list[dict[str, Any]] = []

    for space in spaces_sorted:
        health_val = area_health.get(space.area, "")
        show_bg = _space_not_normal(health_val)

        area_reg = ar.async_get(hass)
        ha_area = area_reg.async_get_area(space.area)
        title = space.name or (ha_area.name if ha_area else space.area)

        overall_id = overall_entity_ids.get(space.area)
        problem_id = problem_entity_ids.get(space.area)
        badges: list[dict[str, Any]] = []
        if overall_id:
            badges.append(
                {
                    "type": "entity",
                    "entity": overall_id,
                    "show_state": True,
                    "state_content": "state",
                    "color": "state",
                }
            )
        if problem_id:
            badges.append(
                {
                    "type": "entity",
                    "entity": problem_id,
                    "show_state": True,
                    "state_content": "state",
                    "color": "state",
                }
            )

        heading: dict[str, Any] = {
            "type": "heading",
            "heading": title,
            "icon": "mdi:home-thermometer",
        }
        if badges:
            heading["badges"] = badges

        entity_rows: list[dict[str, Any]] = []
        for slot in sorted(space.slots, key=lambda s: measurement_label(s.measurement).lower()):
            eid = slot_entity_ids.get((space.area, slot.measurement))
            if not eid:
                continue
            label = measurement_label(slot.measurement)
            entity_rows.append(
                {
                    "entity": eid,
                    "name": label,
                    "secondary_info": "attribute",
                    "attribute": "health",
                }
            )

        cards: list[dict[str, Any]] = [heading]

        if overall_id:
            stale_template = (
                "{% if state_attr('" + overall_id + "', 'health') in ['stale', 'unavailable'] %}"
                "**Room status:** {{ state_attr('" + overall_id + "', 'health') | upper }}"
                "{% endif %}"
            )
            attention_template = (
                "{% if state_attr('" + overall_id + "', 'attention_reasons') %}"
                "**Needs attention:**\n"
                "{% for r in state_attr('" + overall_id + "', 'attention_reasons') %}"
                "- **{{ r.label }}:** {{ r.health }} ({{ r.value }})\n"
                "{% endfor %}"
                "{% endif %}"
            )
            content = stale_template + "\n\n" + attention_template
            cards.append(
                {
                    "type": "markdown",
                    "content": content,
                    "text_only": True,
                }
            )

        if entity_rows:
            cards.append(
                {
                    "type": "entities",
                    "title": "Measurements",
                    "state_color": True,
                    "entities": entity_rows,
                }
            )

        section: dict[str, Any] = {"type": "grid", "cards": cards}
        if show_bg:
            section["background"] = {
                "color": PROBLEM_SECTION_BG_COLOR,
                "opacity": PROBLEM_SECTION_BG_OPACITY,
            }
        sections.append(section)

    return {
        "views": [
            {
                "title": DASHBOARD_TITLE,
                "path": "airquality",
                "type": "sections",
                "sections": sections,
            }
        ]
    }


def _resolve_entity_ids(
    hass: HomeAssistant,
    entry_id: str,
    config: AirQualityConfig,
) -> tuple[
    dict[tuple[str, str], str],
    dict[str, str],
    dict[str, str],
]:
    from homeassistant.helpers import entity_registry as er  # noqa: PLC0415

    ent_reg = er.async_get(hass)
    slot_ids: dict[tuple[str, str], str] = {}
    overall_ids: dict[str, str] = {}
    problem_ids: dict[str, str] = {}

    for space in config.spaces:
        for slot in space.slots:
            uid = f"{entry_id}::{space.area}::{slot.measurement}"
            eid = ent_reg.async_get_entity_id("sensor", DOMAIN, uid)
            if eid:
                slot_ids[(space.area, slot.measurement)] = eid

        ouid = f"{entry_id}::{space.area}::overall"
        o_eid = ent_reg.async_get_entity_id("sensor", DOMAIN, ouid)
        if o_eid:
            overall_ids[space.area] = o_eid

        puid = f"{entry_id}::{space.area}::problem"
        p_eid = ent_reg.async_get_entity_id("binary_sensor", DOMAIN, puid)
        if p_eid:
            problem_ids[space.area] = p_eid

    return slot_ids, overall_ids, problem_ids


def _panel_path_taken(hass: HomeAssistant, url_path: str) -> bool:
    """Return True if another integration already registered this sidebar path."""
    return url_path in hass.data.get(frontend.DATA_PANELS, {})


async def _ensure_lovelace_data(hass: HomeAssistant) -> bool:
    ll_root = hass.data.get("lovelace")
    if isinstance(ll_root, dict) and "dashboards" in ll_root:
        return True

    try:
        full_config = await async_hass_config_yaml(hass)
    except HomeAssistantError as err:
        _LOGGER.warning("Cannot load Home Assistant YAML to set up dashboards: %s", err)
        return False

    if not await async_setup_component(hass, "lovelace", full_config):
        _LOGGER.warning(
            "The Lovelace (dashboards) integration could not be set up. "
            "Check Settings → Repairs and your configuration for dashboard-related errors.",
        )
        return False

    retry = hass.data.get("lovelace")
    return isinstance(retry, dict) and "dashboards" in retry


async def async_sync_dashboard(
    hass: HomeAssistant, coordinator: AirQualityCoordinator
) -> DashboardSyncResult:
    """Ensure the Air Quality dashboard exists and matches current entities.

    Returns a result record for diagnostics, repairs, and notifications.
    """
    ll_root = hass.data.get("lovelace")
    if not isinstance(ll_root, dict) or "dashboards" not in ll_root:
        _LOGGER.info(
            "Lovelace data not loaded yet — loading the dashboards integration before sync.",
        )
        if await _ensure_lovelace_data(hass):
            ll_root = hass.data.get("lovelace")
        if not isinstance(ll_root, dict) or "dashboards" not in ll_root:
            _LOGGER.warning(
                "Lovelace is still not available — cannot create or update the Air Quality dashboard.",
            )
            return DashboardSyncResult(
                "skipped",
                "Lovelace is not initialized after setup. Ensure Home Assistant dashboards are "
                "enabled in your user profile (**Always show the dashboard**). If dashboards are "
                "disabled in configuration.yaml, re-enable them, then reload the integration "
                "or call airquality.sync_dashboard.",
            )

    entry = coordinator.config_entry
    if entry is None or coordinator.config is None or coordinator.data is None:
        _LOGGER.warning("Air Quality dashboard sync skipped — coordinator state not ready.")
        return DashboardSyncResult("skipped")

    entry_id = entry.entry_id
    yaml_config = coordinator.config

    try:
        from homeassistant.components.lovelace import const as ll_const
        from homeassistant.components.lovelace import dashboard as ll_dashboard
    except ImportError as err:
        _LOGGER.warning(
            "Lovelace components are not available (%s); skipping dashboard sync.", err,
        )
        return DashboardSyncResult(
            "failed",
            f"Could not load Lovelace components: {err}",
        )

    area_health: dict[str, str] = {}
    for space in yaml_config.spaces:
        sh = coordinator.data.spaces.get(space.area)
        area_health[space.area] = sh.health if sh else ""

    slot_map, overall_map, problem_map = _resolve_entity_ids(hass, entry_id, yaml_config)

    ll_config = build_lovelace_config(
        config=yaml_config,
        hass=hass,
        area_health=area_health,
        slot_entity_ids=slot_map,
        overall_entity_ids=overall_map,
        problem_entity_ids=problem_map,
    )

    dashboards: dict[str | None, Any] = ll_root["dashboards"]
    store = dashboards.get(DASHBOARD_URL_PATH)

    try:
        if store is None:
            if _panel_path_taken(hass, DASHBOARD_URL_PATH):
                msg = (
                    f"Sidebar path '{DASHBOARD_URL_PATH}' is already used by another panel. "
                    "Rename or remove that panel, or change DASHBOARD_URL_PATH in code."
                )
                _LOGGER.warning("Cannot create Air Quality dashboard — %s", msg)
                return DashboardSyncResult("skipped", msg)

            dashboards_coll = ll_root.get("dashboards_collection")
            if dashboards_coll is None:
                dashboards_coll = ll_dashboard.DashboardsCollection(hass)
                await dashboards_coll.async_load()
                ll_root["dashboards_collection"] = dashboards_coll

            existing_item: dict[str, Any] | None = None
            for item in dashboards_coll.async_items():
                if item.get(ll_const.CONF_URL_PATH) == DASHBOARD_URL_PATH:
                    existing_item = item
                    break

            if existing_item is None:
                created = await dashboards_coll.async_create_item(
                    {
                        ll_const.CONF_TITLE: DASHBOARD_TITLE,
                        ll_const.CONF_URL_PATH: DASHBOARD_URL_PATH,
                        ll_const.CONF_ICON: "mdi:air-filter",
                        ll_const.CONF_SHOW_IN_SIDEBAR: True,
                        ll_const.CONF_REQUIRE_ADMIN: False,
                    }
                )
                dashboards[DASHBOARD_URL_PATH] = ll_dashboard.LovelaceStorage(hass, created)
                panel_cfg = {
                    ll_const.CONF_TITLE: created[ll_const.CONF_TITLE],
                    ll_const.CONF_REQUIRE_ADMIN: created[ll_const.CONF_REQUIRE_ADMIN],
                    ll_const.CONF_SHOW_IN_SIDEBAR: created[ll_const.CONF_SHOW_IN_SIDEBAR],
                    ll_const.CONF_ICON: created.get(ll_const.CONF_ICON, ll_const.DEFAULT_ICON),
                }
                frontend.async_register_built_in_panel(
                    hass,
                    ll_const.DOMAIN,
                    frontend_url_path=DASHBOARD_URL_PATH,
                    require_admin=panel_cfg[ll_const.CONF_REQUIRE_ADMIN],
                    show_in_sidebar=panel_cfg[ll_const.CONF_SHOW_IN_SIDEBAR],
                    sidebar_title=panel_cfg[ll_const.CONF_TITLE],
                    sidebar_icon=panel_cfg[ll_const.CONF_ICON],
                    config={"mode": ll_const.MODE_STORAGE},
                    update=False,
                )
            else:
                dashboards[DASHBOARD_URL_PATH] = ll_dashboard.LovelaceStorage(hass, existing_item)
            store = dashboards[DASHBOARD_URL_PATH]

        await store.async_save(ll_config)
    except Exception as err:
        tb = traceback.format_exc()
        _LOGGER.error("Air Quality Lovelace dashboard create/save failed: %s\n%s", err, tb)
        return DashboardSyncResult(
            "failed",
            f"Could not create or save the Lovelace dashboard: {err!s}",
        )
    _LOGGER.info("Updated Air Quality Lovelace dashboard (%s).", DASHBOARD_URL_PATH)
    return DashboardSyncResult("ok")
