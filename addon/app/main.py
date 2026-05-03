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
import yaml_io
from schema_validator import validate

logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger("airquality_ui")

APP_DIR = Path(__file__).parent

app = FastAPI(title="Air Quality UI")
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


MEASUREMENT_LABELS: dict[str, str] = {
    "temperature": "Temperature",
    "temperature_f": "Temperature (°F)",
    "temperature_c": "Temperature (°C)",
    "humidity": "Humidity",
    "pm25": "PM2.5",
    "pm10": "PM10",
    "co2": "CO₂",
    "voc": "VOC",
    "no2": "NO₂",
    "o3": "O₃",
    "radon": "Radon",
}

AGGREGATIONS = list(config_ops.VALID_AGGREGATIONS)


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
    return RedirectResponse(url=f"/#area-{area_id}", status_code=303)


@app.post("/space/{area_id}/slot/{measurement}/delete")
async def delete_slot(area_id: str, measurement: str) -> RedirectResponse:
    parsed = yaml_io.load()
    parsed = config_ops.remove_slot(parsed, area_id, measurement)
    _persist_and_reload(parsed, validate_first=False)
    await _trigger_reload()
    return RedirectResponse(url=f"/#area-{area_id}", status_code=303)


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
    return RedirectResponse(url=f"/#area-{area_id}", status_code=303)


@app.post("/space/{area_id}/slot/{measurement}/entity/delete")
async def delete_entity(
    area_id: str,
    measurement: str,
    entity_id: str = Form(...),
) -> RedirectResponse:
    parsed = yaml_io.load()
    parsed = config_ops.remove_entity(parsed, area_id, measurement, entity_id)
    _persist_and_reload(parsed, validate_first=False)
    await _trigger_reload()
    return RedirectResponse(url=f"/#area-{area_id}", status_code=303)


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
        return RedirectResponse(url=f"/#area-{area_id}", status_code=303)
    _persist_and_reload(parsed, validate_first=False)
    await _trigger_reload()
    return RedirectResponse(url=f"/#area-{area_id}", status_code=303)


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
    return RedirectResponse(url=f"/#area-{area_id}", status_code=303)


@app.post("/space/{area_id}/delete")
async def delete_space(area_id: str) -> RedirectResponse:
    parsed = yaml_io.load()
    parsed = config_ops.remove_space(parsed, area_id)
    _persist_and_reload(parsed, validate_first=False)
    await _trigger_reload()
    return RedirectResponse(url="/", status_code=303)


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
        return RedirectResponse(url="/discover", status_code=303)
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
    return RedirectResponse(url="/", status_code=303)


@app.get("/profiles", response_class=HTMLResponse)
async def profiles_view(request: Request) -> HTMLResponse:
    parsed = yaml_io.load() or {}
    aq = parsed.get("airquality") or {}
    profiles = aq.get("threshold_profiles") or {}
    profile_list = []
    for name in sorted(profiles.keys()):
        profile_list.append({"name": name, "data": dict(profiles[name])})

    context = {
        "request": request,
        "profiles": profile_list,
        "default_profile": (aq.get("defaults") or {}).get("threshold_profile"),
        "yaml_path": str(yaml_io.YAML_PATH),
    }
    return templates.TemplateResponse("profiles.html", context)


@app.post("/profiles/{name}/delete")
async def delete_profile(name: str) -> RedirectResponse:
    parsed = yaml_io.load()
    parsed = config_ops.delete_threshold_profile(parsed, name)
    _persist_and_reload(parsed, validate_first=False)
    await _trigger_reload()
    return RedirectResponse(url="/profiles", status_code=303)
