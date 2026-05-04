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
from .dashboard_sync import DashboardSkipReason, DashboardSyncResult
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


def _jinja_double_quoted_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\r", " ").replace("\n", " ")


def _household_summary_markdown(
    *,
    home_overall_id: str | None,
    room_rows: list[tuple[str, str]],
) -> str:
    """Jinja markdown: bullet list of {room} {measurement} is {health} from attention_reasons."""
    blocks: list[str] = []
    for room_title, overall_id in room_rows:
        room_lit = _jinja_double_quoted_literal(room_title)
        blocks.append(
            "{% set room_title = \"" + room_lit + "\" %}"
            "{% set r = state_attr('" + overall_id + "', 'attention_reasons') %}"
            "{% if r %}{% for item in r %}- **{{ room_title }}** {{ item.label }} is **{{ item.health }}**\n"
            "{% endfor %}{% endif %}"
        )
    body = "\n".join(blocks) if blocks else ""
    if not home_overall_id:
        return body or "*Add spaces to see household air quality here.*"

    head = (
        "{% if states('" + home_overall_id + "') in ['good', 'fair'] %}"
        "*Household rollup is good — no problem-level readings driving the home score.*\n\n"
        "{% else %}"
        "*Household rollup needs attention — details by room below.*\n\n"
        "{% endif %}"
    )
    if body:
        return head + body
    return (
        head
        + "{% if states('" + home_overall_id + "') in ['good', 'fair'] %}"
        "*No measurements flagged for attention right now.*\n"
        "{% else %}"
        "*Open each room section below for measurement values.*\n"
        "{% endif %}"
    )


def build_lovelace_config(
    *,
    config: AirQualityConfig,
    hass: HomeAssistant,
    area_health: dict[str, str],
    slot_entity_ids: dict[tuple[str, str], str],
    overall_entity_ids: dict[str, str],
    problem_entity_ids: dict[str, str],
    home_overall_entity_id: str | None,
    home_problem_entity_id: str | None,
) -> dict[str, Any]:
    """Build Lovelace dashboard JSON (single sections view)."""

    from homeassistant.helpers import area_registry as ar  # noqa: PLC0415

    area_reg = ar.async_get(hass)

    def room_sort_key(space: SpaceConfig) -> tuple[int, str]:
        health_val = area_health.get(space.area, "")
        attention = 0 if _space_not_normal(health_val) else 1

        ha_area = area_reg.async_get_area(space.area)
        name = space.name or (ha_area.name if ha_area else space.area)
        return (attention, name.lower())

    spaces_sorted = sorted(config.spaces, key=room_sort_key)
    sections: list[dict[str, Any]] = []

    room_summary_rows: list[tuple[str, str]] = []
    for space in config.spaces:
        oid = overall_entity_ids.get(space.area)
        if not oid:
            continue
        ha_area = area_reg.async_get_area(space.area)
        title = space.name or (ha_area.name if ha_area else space.area)
        room_summary_rows.append((title, oid))
    room_summary_rows.sort(key=lambda row: row[0].lower())

    summary_md = _household_summary_markdown(
        home_overall_id=home_overall_entity_id,
        room_rows=room_summary_rows,
    )
    header_markdown = "## Household\n\n" + summary_md

    view_badges: list[dict[str, Any]] = []
    if home_overall_entity_id:
        view_badges.append(
            {
                "type": "entity",
                "entity": home_overall_entity_id,
                "show_state": True,
                "state_content": "state",
                "color": "state",
            }
        )
    if home_problem_entity_id:
        view_badges.append(
            {
                "type": "entity",
                "entity": home_problem_entity_id,
                "show_state": True,
                "state_content": "state",
                "color": "state",
            }
        )

    view_header: dict[str, Any] = {
        "layout": "responsive",
        "badges_position": "bottom",
        "card": {
            "type": "markdown",
            "content": header_markdown,
            "text_only": True,
        },
    }

    for space in spaces_sorted:
        health_val = area_health.get(space.area, "")
        show_bg = _space_not_normal(health_val)

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

        tile_cards: list[dict[str, Any]] = []
        for slot in sorted(space.slots, key=lambda s: measurement_label(s.measurement).lower()):
            eid = slot_entity_ids.get((space.area, slot.measurement))
            if not eid:
                continue
            label = measurement_label(slot.measurement)
            tile_cards.append(
                {
                    "type": "tile",
                    "entity": eid,
                    "name": label,
                    "state_content": ["state", "health"],
                    "color": "state",
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

        if tile_cards:
            cards.append(
                {
                    "type": "grid",
                    "columns": 2,
                    "square": False,
                    "cards": tile_cards,
                }
            )

        section: dict[str, Any] = {"type": "grid", "cards": cards}
        if show_bg:
            section["background"] = {
                "color": PROBLEM_SECTION_BG_COLOR,
                "opacity": PROBLEM_SECTION_BG_OPACITY,
            }
        sections.append(section)

    view: dict[str, Any] = {
        "title": DASHBOARD_TITLE,
        "path": "airquality",
        "type": "sections",
        "header": view_header,
        "sections": sections,
    }
    if view_badges:
        view["badges"] = view_badges

    return {"views": [view]}


def _resolve_entity_ids(
    hass: HomeAssistant,
    entry_id: str,
    config: AirQualityConfig,
) -> tuple[
    dict[tuple[str, str], str],
    dict[str, str],
    dict[str, str],
    str | None,
    str | None,
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

    home_overall = ent_reg.async_get_entity_id("sensor", DOMAIN, f"{entry_id}::home::overall")
    home_problem = ent_reg.async_get_entity_id(
        "binary_sensor",
        DOMAIN,
        f"{entry_id}::home::problem",
    )

    return slot_ids, overall_ids, problem_ids, home_overall, home_problem


def _panel_path_taken(hass: HomeAssistant, url_path: str) -> bool:
    """Return True if another integration already registered this sidebar path."""
    return url_path in hass.data.get(frontend.DATA_PANELS, {})


def _lovelace_dashboard_map(hass: HomeAssistant) -> dict[str | None, Any] | None:
    """Resolve Lovelace's url_path→config map (dict or LovelaceData.dashboards)."""
    raw = hass.data.get("lovelace")
    if raw is None:
        return None
    dashboards = getattr(raw, "dashboards", None)
    if isinstance(dashboards, dict):
        return dashboards
    if isinstance(raw, dict):
        dm = raw.get("dashboards")
        return dm if isinstance(dm, dict) else None
    return None


def _lovelace_dashboards_collection(hass: HomeAssistant) -> Any | None:
    raw = hass.data.get("lovelace")
    if raw is None:
        return None
    if hasattr(raw, "dashboards_collection"):
        return getattr(raw, "dashboards_collection", None)
    if isinstance(raw, dict):
        return raw.get("dashboards_collection")
    return None


def _assign_lovelace_dashboards_collection(hass: HomeAssistant, collection: Any) -> None:
    raw = hass.data.get("lovelace")
    if raw is None:
        return
    if hasattr(raw, "dashboards_collection"):
        setattr(raw, "dashboards_collection", collection)
    elif isinstance(raw, dict):
        raw["dashboards_collection"] = collection


def lovelace_storage_ready(hass: HomeAssistant) -> bool:
    """True when Hass has a usable Lovelace dashboard map (dict or dataclass-backed)."""
    return _lovelace_dashboard_map(hass) is not None


def _dashboard_storage_preview(hass: HomeAssistant) -> str:
    """Short, log-safe description of hass.data['lovelace'] for diagnostics."""
    raw = hass.data.get("lovelace")
    if raw is None:
        return "missing (None)"
    if isinstance(raw, dict):
        keys = sorted(raw)
        parts = [repr(k) for k in keys[:12]]
        tail = f", … (+{len(keys) - 12} more keys)" if len(keys) > 12 else ""
        return f"dict with keys [{', '.join(parts)}]{tail}"
    return f"{type(raw).__name__!s}: {raw!r}"[:240]


def _lovelace_unavailable_message(
    hass: HomeAssistant,
    *,
    reason: str,
    yaml_error: str | None = None,
) -> str:
    try:
        import homeassistant

        ha_version = getattr(homeassistant, "__version__", "?")
    except ImportError:
        ha_version = "?"

    comps = getattr(hass.config, "components", set()) or set()
    recovery = getattr(hass.config, "recovery_mode", False)
    lines = [
        f"Home Assistant {ha_version}; recovery_mode={recovery}",
        f"Components loaded: frontend={'frontend' in comps}, lovelace={'lovelace' in comps}",
        f"hass.data['lovelace']: {_dashboard_storage_preview(hass)}",
    ]
    if reason == "yaml":
        lines.append(
            "Reading configuration.yaml failed — open **Settings → System → Logs** and search for configuration errors.",
        )
        if yaml_error:
            lines.append(f"Error from loader: {yaml_error}")
    elif reason == "setup_false":
        lines.append(
            "async_setup_component('lovelace') returned False — the dashboards integration did not finish setup. "
            "Search the full log for **Setup failed for** or **lovelace** at startup.",
        )
    elif reason == "data_invalid_after_setup":
        lines.append(
            "After setup, no Lovelace dashboard map was found (expected a dict or "
            "LovelaceData with a .dashboards attribute). If you are on a recent Home Assistant "
            "release, update Air Quality to the latest version.",
        )
    else:
        lines.append(f"Internal reason tag: {reason}")

    lines.append(
        "If dashboards work in the UI, copy this block into a GitHub issue on the Air Quality integration.",
    )
    return "\n".join(lines)


async def _ensure_lovelace_data(
    hass: HomeAssistant,
) -> tuple[bool, str, str | None]:
    """Return (success, failure_reason_tag, yaml_error_detail)."""
    if lovelace_storage_ready(hass):
        return True, "", None

    try:
        full_config = await async_hass_config_yaml(hass)
    except HomeAssistantError as err:
        _LOGGER.warning("Cannot load Home Assistant YAML to set up dashboards: %s", err)
        return False, "yaml", str(err)

    if not await async_setup_component(hass, "lovelace", full_config):
        _LOGGER.warning(
            "The Lovelace (dashboards) integration could not be set up. "
            "Check Settings → Repairs and your configuration for dashboard-related errors.",
        )
        return False, "setup_false", None

    if not lovelace_storage_ready(hass):
        return False, "data_invalid_after_setup", None

    return True, "", None


async def async_sync_dashboard(
    hass: HomeAssistant, coordinator: AirQualityCoordinator
) -> DashboardSyncResult:
    """Ensure the Air Quality dashboard exists and matches current entities.

    Returns a result record for diagnostics, repairs, and notifications.
    """
    if not lovelace_storage_ready(hass):
        _LOGGER.info(
            "Lovelace data not loaded yet — loading the dashboards integration before sync.",
        )
        ok_ll, ll_fail_reason, yaml_err_detail = await _ensure_lovelace_data(hass)

        if not lovelace_storage_ready(hass):
            diagnostics = _lovelace_unavailable_message(
                hass,
                reason=ll_fail_reason or "unknown",
                yaml_error=yaml_err_detail,
            )
            _LOGGER.warning(
                "Cannot create or update the Air Quality dashboard — Lovelace storage not available.\n%s",
                diagnostics,
            )
            return DashboardSyncResult(
                "skipped",
                diagnostics,
                skip_reason="lovelace_unavailable",
            )

    dashboards = _lovelace_dashboard_map(hass)
    if dashboards is None:
        diagnostics = _lovelace_unavailable_message(hass, reason="data_invalid_after_setup")
        return DashboardSyncResult(
            "skipped",
            diagnostics,
            skip_reason="lovelace_unavailable",
        )

    entry = coordinator.config_entry
    if entry is None or coordinator.config is None or coordinator.data is None:
        _LOGGER.warning("Air Quality dashboard sync skipped — coordinator state not ready.")
        return DashboardSyncResult(
            "skipped",
            "Coordinator has no config entry, YAML config, or computed state yet. "
            "Wait for the integration to finish starting, then call airquality.sync_dashboard.",
            skip_reason="coordinator_not_ready",
        )

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

    slot_map, overall_map, problem_map, home_overall, home_problem = _resolve_entity_ids(
        hass, entry_id, yaml_config
    )

    ll_config = build_lovelace_config(
        config=yaml_config,
        hass=hass,
        area_health=area_health,
        slot_entity_ids=slot_map,
        overall_entity_ids=overall_map,
        problem_entity_ids=problem_map,
        home_overall_entity_id=home_overall,
        home_problem_entity_id=home_problem,
    )

    store = dashboards.get(DASHBOARD_URL_PATH)

    try:
        if store is None:
            if _panel_path_taken(hass, DASHBOARD_URL_PATH):
                msg = (
                    f"Sidebar path '{DASHBOARD_URL_PATH}' is already used by another panel. "
                    "Rename or remove that panel, or change DASHBOARD_URL_PATH in code."
                )
                _LOGGER.warning("Cannot create Air Quality dashboard — %s", msg)
                return DashboardSyncResult(
                    "skipped",
                    msg,
                    skip_reason="sidebar_path_blocked",
                )

            dashboards_coll = _lovelace_dashboards_collection(hass)
            if dashboards_coll is None:
                dashboards_coll = ll_dashboard.DashboardsCollection(hass)
                await dashboards_coll.async_load()
                _assign_lovelace_dashboards_collection(hass, dashboards_coll)

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
