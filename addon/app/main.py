"""Air Quality UI — FastAPI app served behind HA ingress.

Area-driven editor for /config/airquality.yaml. The user picks rooms (HA areas)
and adds measurement slots and source sensors; every action persists straight
to YAML and reloads the integration. There is no raw YAML editor — for that
the user can edit the file directly on disk.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import config_ops
import ha_client
import threshold_profiles as threshold_profile_utils
import threshold_references
import yaml_io
from measurement_labels import MEASUREMENT_LABELS
from schema_validator import validate
from version_info import ADDON_VERSION

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_LOGGER = logging.getLogger("airquality_ui")

APP_DIR = Path(__file__).parent

def _cache_bust_read(relative: str) -> str:
    p = APP_DIR / relative
    return p.read_text(encoding="utf-8")

_INLINE_STYLE_CSS = _cache_bust_read("static/style.css")
_INLINE_PROFILE_JS = _cache_bust_read("static/profile-editor.js")

app = FastAPI(title="Air Quality UI")
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
templates.env.filters["m_label"] = lambda m: MEASUREMENT_LABELS.get(m, m)
templates.env.globals["addon_version"] = ADDON_VERSION
templates.env.globals["inline_style_css"] = _INLINE_STYLE_CSS
templates.env.globals["inline_profile_editor_js"] = _INLINE_PROFILE_JS


AGGREGATIONS = list(config_ops.VALID_AGGREGATIONS)

_SIMPLE_MEASUREMENTS = (
    "pm25",
    "pm10",
    "co2",
    "voc",
    "no2",
    "o3",
    "radon",
)
_RANGE_MEASUREMENTS = ("temperature", "temperature_f", "temperature_c", "humidity")


def _coerce_measurement_block(raw: dict[str, Any]) -> dict[str, float]:
    """Convert YAML measurement values to floats, skipping extends."""
    out: dict[str, float] = {}
    if not isinstance(raw, dict):
        return out
    for key, val in raw.items():
        try:
            out[str(key)] = float(val)
        except (TypeError, ValueError):
            continue
    return out


def _profiles_raw_dict(parsed: Any) -> dict[str, dict[str, Any]]:
    aq = (parsed or {}).get("airquality") or {}
    raw = aq.get("threshold_profiles") or {}
    return {str(k): dict(v) if isinstance(v, dict) else {} for k, v in raw.items()}


def _build_profile_edit_model(
    *,
    name: str,
    raw: dict[str, Any],
    resolved: dict[str, Any],
    default_name: str | None,
    ref_defaults: dict[str, dict[str, float]],
) -> dict[str, Any]:
    extends = raw.get("extends")
    raw_extends = extends if extends else None

    rows: list[dict[str, Any]] = []
    for measurement in _SIMPLE_MEASUREMENTS:
        user_block = _coerce_measurement_block(
            resolved[measurement]
            if measurement in resolved and isinstance(resolved.get(measurement), dict)
            else {}
        )
        ref_spec = threshold_references.measurement_reference(measurement)
        ref_vals: dict[str, float] = dict(ref_spec["values"]) if ref_spec else {}
        if not user_block and measurement in ref_defaults:
            user_block = dict(ref_defaults[measurement])
        sliders: list[dict[str, Any]] = []
        lo, hi = threshold_references.slider_min_max_simple(user_block, ref_vals)
        for band in ("good", "fair", "poor", "unhealthy"):
            val = user_block.get(band, ref_vals.get(band, 0))
            field = f"{measurement}_{band}"
            markers = [
                {
                    "label": f"ref {rk}",
                    "pct": threshold_references.pct_on_span(rv, lo, hi),
                }
                for rk, rv in ref_vals.items()
            ]
            sliders.append(
                {
                    "band": band,
                    "field": field,
                    "label": band.replace("_", " "),
                    "num_value": val,
                    "range_min": lo,
                    "range_max": hi,
                    "markers": markers,
                }
            )
        rows.append(
            {
                "measurement": measurement,
                "kind": "simple",
                "heading": MEASUREMENT_LABELS.get(measurement, measurement),
                "reference": ref_spec,
                "sliders": sliders,
            }
        )

    for measurement in _RANGE_MEASUREMENTS:
        user_block = _coerce_measurement_block(
            resolved[measurement]
            if measurement in resolved and isinstance(resolved.get(measurement), dict)
            else {}
        )
        ref_spec = threshold_references.measurement_reference(measurement)
        ref_vals = dict(ref_spec["values"]) if ref_spec else {}
        if not user_block and measurement in ref_defaults:
            user_block = dict(ref_defaults[measurement])
        sliders = []
        lo, hi = threshold_references.slider_min_max_range(user_block, ref_vals)
        for band in ("good_min", "good_max", "fair_min", "fair_max"):
            val = user_block.get(band, ref_vals.get(band, 0))
            field = f"{measurement}_{band}"
            labels_map = {
                "good_min": "Good min",
                "good_max": "Good max",
                "fair_min": "Fair min",
                "fair_max": "Fair max",
            }
            markers = [
                {
                    "label": f"ref {rk}",
                    "pct": threshold_references.pct_on_span(rv, lo, hi),
                }
                for rk, rv in ref_vals.items()
            ]
            sliders.append(
                {
                    "band": band,
                    "field": field,
                    "label": labels_map.get(band, band),
                    "num_value": val,
                    "range_min": lo,
                    "range_max": hi,
                    "markers": markers,
                }
            )
        rows.append(
            {
                "measurement": measurement,
                "kind": "range",
                "heading": MEASUREMENT_LABELS.get(measurement, measurement),
                "reference": ref_spec,
                "sliders": sliders,
            }
        )

    return {
        "name": name,
        "extends": raw_extends,
        "default_profile_name": default_name,
        "can_delete": name != default_name if default_name else True,
        "measurements": rows,
    }


def _ingress_safe_redirect(location: str) -> str:
    """Redirect target relative to the current URL (required when behind HA ingress)."""
    if location.startswith("/#"):
        return f".{location}"
    if location == "/":
        return "."
    if location.startswith("/"):
        return location.lstrip("/")
    return location


def _flash(request: Request, message: str, level: str = "info") -> None:
    """Stash a one-shot flash message in the URL query string for a redirect."""
    # Simpler than a session: pass via query params on redirect.
    request.scope.setdefault("flash", []).append((level, message))


def _build_view_model(
    ui_state: dict[str, Any], parsed: Any
) -> dict[str, Any]:
    """Combine the live HA state with the parsed YAML into a single render model."""
    config = (parsed or {}).get("airquality") or {}
    spaces_by_area: dict[str, dict[str, Any]] = {}
    for space in config.get("spaces") or []:
        area_id = space.get("area")
        if not area_id:
            continue
        slots = []
        for slot in space.get("slots") or []:
            slots.append(
                {
                    "measurement": slot.get("measurement"),
                    "aggregation": slot.get("aggregation", "single"),
                    "entities": list(slot.get("entities") or []),
                }
            )
        spaces_by_area[area_id] = {
            "name": space.get("name"),
            "threshold_profile": space.get("threshold_profile"),
            "slots": {s["measurement"]: s for s in slots},
        }

    candidates_by_area = ui_state.get("candidates_by_area") or {}
    available_measurements = ui_state.get("available_measurements") or list(MEASUREMENT_LABELS)

    rooms = []
    for area in ui_state.get("areas") or []:
        area_id = area["area_id"]
        space = spaces_by_area.get(area_id, {"slots": {}})
        configured_entities: set[str] = set()
        for slot in space.get("slots", {}).values():
            configured_entities.update(slot["entities"])

        candidates = candidates_by_area.get(area_id, [])
        unassigned = [c for c in candidates if c["entity_id"] not in configured_entities]
        candidates_by_measurement: dict[str, list[dict[str, Any]]] = {}
        for c in unassigned:
            candidates_by_measurement.setdefault(c["measurement"], []).append(c)

        configured_measurements = set(space.get("slots", {}).keys())
        addable_measurements = [
            m for m in available_measurements if m not in configured_measurements
        ]

        rooms.append(
            {
                "area_id": area_id,
                "name": area["name"],
                "icon": area.get("icon"),
                "floor_id": area.get("floor_id"),
                "configured": area_id in spaces_by_area,
                "display_name": space.get("name"),
                "threshold_profile": space.get("threshold_profile"),
                "slots": list(space.get("slots", {}).values()),
                "candidates_by_measurement": candidates_by_measurement,
                "all_candidates_count": len(candidates),
                "unassigned_candidates_count": len(unassigned),
                "addable_measurements": addable_measurements,
            }
        )

    profile_names = sorted((config.get("threshold_profiles") or {}).keys())
    return {
        "rooms": rooms,
        "profile_names": profile_names,
        "aggregations": AGGREGATIONS,
        "measurement_labels": MEASUREMENT_LABELS,
        "yaml_path": ui_state.get("yaml_path", str(yaml_io.YAML_PATH)),
        "default_profile": (config.get("defaults") or {}).get("threshold_profile"),
    }


async def _gather_view(request: Request, **extra: Any) -> dict[str, Any]:
    """Build the template context, reading both HA UI state and the YAML on disk."""
    ui_state: dict[str, Any] = {"areas": [], "candidates_by_area": {}, "config": {}}
    integration_error: str | None = None
    try:
        ui_state = await ha_client.get_ui_state()
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("airquality.get_ui_state failed: %s", err)
        integration_error = (
            "Could not reach the Air Quality integration. "
            "Make sure it is installed and the config entry has been added in "
            f"Settings → Devices & Services. ({err})"
        )

    parsed = yaml_io.load()
    model = _build_view_model(ui_state, parsed)
    model.update(
        {
            "request": request,
            "integration_error": integration_error,
            **extra,
        }
    )
    return model


def _persist_and_reload(parsed: Any, *, validate_first: bool = True) -> list[str]:
    """Validate, save, reload. Returns a list of validation errors (empty if OK)."""
    if validate_first:
        errors = validate(parsed)
        if errors:
            return errors
    yaml_io.save(parsed)
    return []


async def _trigger_reload() -> str | None:
    try:
        await ha_client.reload()
        try:
            await ha_client.sync_dashboard()
        except Exception as sync_err:  # noqa: BLE001
            _LOGGER.warning("airquality.sync_dashboard failed: %s", sync_err)
        return None
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("airquality.reload failed: %s", err)
        return str(err)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    context = await _gather_view(request)
    return templates.TemplateResponse("index.html", context)


@app.post("/space/{area_id}/slot/add")
async def add_slot(
    area_id: str,
    measurement: str = Form(...),
) -> RedirectResponse:
    parsed = yaml_io.load()
    parsed = config_ops.add_slot(parsed, area_id, measurement)
    errors = _persist_and_reload(parsed)
    if errors:
        _LOGGER.warning("Validation failed adding slot: %s", errors)
    else:
        await _trigger_reload()
    return RedirectResponse(url=_ingress_safe_redirect(f"/#area-{area_id}"), status_code=303)


@app.post("/space/{area_id}/slot/{measurement}/delete")
async def delete_slot(area_id: str, measurement: str) -> RedirectResponse:
    parsed = yaml_io.load()
    parsed = config_ops.remove_slot(parsed, area_id, measurement)
    errors = _persist_and_reload(parsed)
    if errors:
        _LOGGER.warning("Validation failed deleting slot: %s", errors)
    else:
        await _trigger_reload()
    return RedirectResponse(url=_ingress_safe_redirect(f"/#area-{area_id}"), status_code=303)


@app.post("/space/{area_id}/slot/{measurement}/entity/add")
async def add_entity(
    area_id: str,
    measurement: str,
    entity_id: str = Form(...),
) -> RedirectResponse:
    parsed = yaml_io.load()
    parsed = config_ops.add_entity(parsed, area_id, measurement, entity_id)
    errors = _persist_and_reload(parsed)
    if errors:
        _LOGGER.warning("Validation failed adding entity: %s", errors)
    else:
        await _trigger_reload()
    return RedirectResponse(url=_ingress_safe_redirect(f"/#area-{area_id}"), status_code=303)


@app.post("/space/{area_id}/slot/{measurement}/entity/delete")
async def delete_entity(
    area_id: str,
    measurement: str,
    entity_id: str = Form(...),
) -> RedirectResponse:
    parsed = yaml_io.load()
    parsed = config_ops.remove_entity(parsed, area_id, measurement, entity_id)
    errors = _persist_and_reload(parsed)
    if errors:
        _LOGGER.warning("Validation failed deleting entity: %s", errors)
    else:
        await _trigger_reload()
    return RedirectResponse(url=_ingress_safe_redirect(f"/#area-{area_id}"), status_code=303)


@app.post("/space/{area_id}/slot/{measurement}/aggregation")
async def set_aggregation(
    area_id: str,
    measurement: str,
    aggregation: str = Form(...),
) -> RedirectResponse:
    parsed = yaml_io.load()
    try:
        parsed = config_ops.set_aggregation(parsed, area_id, measurement, aggregation)
    except ValueError as err:
        _LOGGER.warning("Bad aggregation: %s", err)
        return RedirectResponse(url=_ingress_safe_redirect(f"/#area-{area_id}"), status_code=303)
    _persist_and_reload(parsed, validate_first=False)
    await _trigger_reload()
    return RedirectResponse(url=_ingress_safe_redirect(f"/#area-{area_id}"), status_code=303)


@app.post("/space/{area_id}/profile")
async def set_profile(
    area_id: str,
    threshold_profile: str = Form(""),
) -> RedirectResponse:
    parsed = yaml_io.load()
    parsed = config_ops.set_space_threshold_profile(
        parsed, area_id, threshold_profile or None
    )
    _persist_and_reload(parsed, validate_first=False)
    await _trigger_reload()
    return RedirectResponse(url=_ingress_safe_redirect(f"/#area-{area_id}"), status_code=303)


@app.post("/space/{area_id}/delete")
async def delete_space(area_id: str) -> RedirectResponse:
    parsed = yaml_io.load()
    parsed = config_ops.remove_space(parsed, area_id)
    _persist_and_reload(parsed, validate_first=False)
    await _trigger_reload()
    return RedirectResponse(url=_ingress_safe_redirect("/"), status_code=303)


@app.get("/discover", response_class=HTMLResponse)
async def discover_form(request: Request) -> HTMLResponse:
    context = await _gather_view(
        request,
        proposal=None,
        proposal_summary=None,
        discovery_error=None,
    )
    return templates.TemplateResponse("discover.html", context)


@app.post("/discover", response_class=HTMLResponse)
async def discover_run(
    request: Request,
    stale_threshold_days: int = Form(30),
    include_stale: bool = Form(False),
) -> HTMLResponse:
    proposal: dict[str, Any] | None = None
    proposal_summary: dict[str, Any] | None = None
    discovery_error: str | None = None
    try:
        result = await ha_client.discover(
            stale_threshold_days=stale_threshold_days,
            include_stale=include_stale,
        )
        proposal_summary = result.get("summary")
        import yaml as _yaml  # noqa: PLC0415
        proposal = _yaml.safe_load(result.get("yaml", "")) or {}
    except Exception as err:  # noqa: BLE001
        _LOGGER.exception("Discovery failed")
        discovery_error = str(err)

    context = await _gather_view(
        request,
        proposal=proposal,
        proposal_summary=proposal_summary,
        discovery_error=discovery_error,
        measurement_labels=MEASUREMENT_LABELS,
    )
    return templates.TemplateResponse("discover.html", context)


@app.post("/discover/apply")
async def discover_apply(
    overwrite: bool = Form(False),
) -> RedirectResponse:
    """Run discovery and merge the proposal into the active config."""
    try:
        result = await ha_client.discover(stale_threshold_days=30, include_stale=False)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Discovery service call failed: %s", err)
        return RedirectResponse(url=_ingress_safe_redirect("/discover"), status_code=303)
    import yaml as _yaml  # noqa: PLC0415
    proposal = _yaml.safe_load(result.get("yaml", "")) or {}
    parsed = yaml_io.load()
    parsed = config_ops.merge_discovery_proposal(
        parsed, proposal, overwrite_slots=overwrite
    )
    errors = _persist_and_reload(parsed)
    if errors:
        _LOGGER.warning("Validation failed applying discovery: %s", errors)
    else:
        await _trigger_reload()
    return RedirectResponse(url=_ingress_safe_redirect("/"), status_code=303)


@app.get("/profiles", response_class=HTMLResponse)
async def profiles_view(request: Request) -> HTMLResponse:
    parsed = yaml_io.load() or {}
    aq = parsed.get("airquality") or {}
    default_profile = (aq.get("defaults") or {}).get("threshold_profile")
    raw_profiles = _profiles_raw_dict(parsed)
    try:
        resolved_map = threshold_profile_utils.resolve_profile_inheritance(raw_profiles)
    except ValueError as err:
        resolved_map = {}
        return templates.TemplateResponse(
            "profiles.html",
            {
                "request": request,
                "profiles": [],
                "profile_names": sorted(raw_profiles.keys()),
                "duplicate_sources": sorted(raw_profiles.keys()),
                "default_profile": default_profile,
                "yaml_path": str(yaml_io.YAML_PATH),
                "validation_errors": [str(err)],
            },
        )

    ref_defaults = threshold_references.default_profile_dict()

    profile_cards: list[dict[str, Any]] = []
    for name in sorted(raw_profiles.keys()):
        raw = raw_profiles[name]
        resolved = resolved_map.get(name, {})
        profile_cards.append(
            _build_profile_edit_model(
                name=name,
                raw=raw,
                resolved=resolved,
                default_name=default_profile,
                ref_defaults=ref_defaults,
            )
        )

    context = {
        "request": request,
        "profiles": profile_cards,
        "profile_names": sorted(raw_profiles.keys()),
        "duplicate_sources": sorted(raw_profiles.keys()),
        "default_profile": default_profile,
        "yaml_path": str(yaml_io.YAML_PATH),
        "validation_errors": [],
    }
    return templates.TemplateResponse("profiles.html", context)


@app.post("/profiles/add")
async def profiles_add(
    profile_name: str = Form(...),
    duplicate_from: str = Form(""),
) -> RedirectResponse:
    name = profile_name.strip()
    if not name:
        return RedirectResponse(url=_ingress_safe_redirect("/profiles"), status_code=303)

    parsed = yaml_io.load()
    try:
        if duplicate_from.strip():
            parsed = config_ops.duplicate_threshold_profile(
                parsed, duplicate_from.strip(), name
            )
        else:
            flat = threshold_profile_utils.materialize_profile_for_save(
                threshold_references.default_profile_dict()
            )
            parsed = config_ops.upsert_threshold_profile(parsed, name, flat)
        errors = _persist_and_reload(parsed)
        if errors:
            _LOGGER.warning("Validation failed adding profile: %s", errors)
        else:
            await _trigger_reload()
    except ValueError as err:
        _LOGGER.warning("Could not add profile: %s", err)
    return RedirectResponse(url=_ingress_safe_redirect("/profiles"), status_code=303)


@app.post("/profiles/{name}")
async def profiles_save(name: str, request: Request) -> HTMLResponse:
    form = await request.form()
    measurements = threshold_profile_utils.parse_profile_form(form)
    order_errs = threshold_profile_utils.validate_full_profile(measurements)

    parsed = yaml_io.load() or {}
    aq = parsed.get("airquality") or {}
    default_profile = (aq.get("defaults") or {}).get("threshold_profile")
    raw_profiles = _profiles_raw_dict(parsed)

    ref_defaults = threshold_references.default_profile_dict()
    try:
        resolved_map = threshold_profile_utils.resolve_profile_inheritance(raw_profiles)
    except ValueError as err:
        return templates.TemplateResponse(
            "profiles.html",
            {
                "request": request,
                "profiles": [],
                "profile_names": sorted(raw_profiles.keys()),
                "duplicate_sources": sorted(raw_profiles.keys()),
                "default_profile": default_profile,
                "yaml_path": str(yaml_io.YAML_PATH),
                "validation_errors": [str(err), *order_errs],
            },
            status_code=400,
        )

    if order_errs:
        profile_cards = []
        for pname in sorted(raw_profiles.keys()):
            raw = raw_profiles[pname]
            resolved = resolved_map.get(pname, {})
            profile_cards.append(
                _build_profile_edit_model(
                    name=pname,
                    raw=raw,
                    resolved=resolved if pname != name else measurements,
                    default_name=default_profile,
                    ref_defaults=ref_defaults,
                )
            )
        return templates.TemplateResponse(
            "profiles.html",
            {
                "request": request,
                "profiles": profile_cards,
                "profile_names": sorted(raw_profiles.keys()),
                "duplicate_sources": sorted(raw_profiles.keys()),
                "default_profile": default_profile,
                "yaml_path": str(yaml_io.YAML_PATH),
                "validation_errors": order_errs,
            },
            status_code=400,
        )

    flat = threshold_profile_utils.materialize_profile_for_save(measurements)
    parsed = config_ops.upsert_threshold_profile(parsed, name, flat)
    schema_errors = _persist_and_reload(parsed)
    if schema_errors:
        profile_cards = []
        for pname in sorted(raw_profiles.keys()):
            raw = raw_profiles[pname]
            resolved = resolved_map.get(pname, {})
            profile_cards.append(
                _build_profile_edit_model(
                    name=pname,
                    raw=raw,
                    resolved=resolved if pname != name else measurements,
                    default_name=default_profile,
                    ref_defaults=ref_defaults,
                )
            )
        _LOGGER.warning("Schema validation failed saving profile: %s", schema_errors)
        return templates.TemplateResponse(
            "profiles.html",
            {
                "request": request,
                "profiles": profile_cards,
                "profile_names": sorted(raw_profiles.keys()),
                "duplicate_sources": sorted(raw_profiles.keys()),
                "default_profile": default_profile,
                "yaml_path": str(yaml_io.YAML_PATH),
                "validation_errors": schema_errors,
            },
            status_code=400,
        )

    reload_err = await _trigger_reload()
    if reload_err:
        _LOGGER.warning("Reload after profile save: %s", reload_err)

    return RedirectResponse(url=_ingress_safe_redirect("/profiles"), status_code=303)


@app.post("/profiles/{name}/delete")
async def delete_profile(name: str) -> RedirectResponse:
    parsed = yaml_io.load()
    parsed = config_ops.delete_threshold_profile(parsed, name)
    _persist_and_reload(parsed, validate_first=False)
    await _trigger_reload()
    return RedirectResponse(url=_ingress_safe_redirect("/profiles"), status_code=303)
