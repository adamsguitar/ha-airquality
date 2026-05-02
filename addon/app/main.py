"""Air Quality UI — FastAPI app served behind HA ingress.

Routes:
  GET  /                  — overview (current config + actions)
  GET  /edit              — raw YAML editor
  POST /save              — validate + save YAML, trigger reload
  GET  /discover          — discovery form
  POST /discover          — run discovery, return YAML proposal + diff
  POST /apply             — apply a proposed YAML (writes + reloads)
  GET  /healthz           — liveness probe
"""
from __future__ import annotations

import difflib
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import ha_client
import yaml_io
from schema_validator import validate

logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger("airquality_ui")

APP_DIR = Path(__file__).parent

app = FastAPI(title="Air Quality UI")
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


def _summarize(data: Any) -> dict[str, Any]:
    """Build a flat summary of the parsed config for the overview page."""
    if not data or "airquality" not in data:
        return {"spaces": [], "profile_count": 0, "loaded": False}

    aq = data["airquality"]
    spaces = []
    for sp in aq.get("spaces") or []:
        slot_summary = []
        for slot in sp.get("slots") or []:
            slot_summary.append({
                "measurement": slot.get("measurement"),
                "aggregation": slot.get("aggregation", "single"),
                "entity_count": len(slot.get("entities") or []),
                "entities": list(slot.get("entities") or []),
            })
        spaces.append({
            "area": sp.get("area"),
            "name": sp.get("name"),
            "threshold_profile": sp.get("threshold_profile"),
            "slots": slot_summary,
        })

    return {
        "spaces": spaces,
        "profile_count": len(aq.get("threshold_profiles") or {}),
        "loaded": True,
    }


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    data = yaml_io.load()
    summary = _summarize(data)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "summary": summary,
            "yaml_path": str(yaml_io.YAML_PATH),
        },
    )


@app.get("/edit", response_class=HTMLResponse)
async def edit_form(request: Request) -> HTMLResponse:
    text = yaml_io.load_text()
    return templates.TemplateResponse(
        "edit.html",
        {"request": request, "yaml_text": text, "errors": [], "saved": False},
    )


@app.post("/save", response_class=HTMLResponse)
async def save(request: Request, yaml_text: str = Form(...)) -> HTMLResponse:
    """Validate and save raw YAML. Triggers airquality.reload on success."""
    try:
        parsed = yaml_io.parse_text(yaml_text)
    except Exception as err:  # noqa: BLE001
        return templates.TemplateResponse(
            "edit.html",
            {
                "request": request,
                "yaml_text": yaml_text,
                "errors": [f"YAML parse error: {err}"],
                "saved": False,
            },
        )

    errors = validate(parsed)
    if errors:
        return templates.TemplateResponse(
            "edit.html",
            {
                "request": request,
                "yaml_text": yaml_text,
                "errors": errors,
                "saved": False,
            },
        )

    yaml_io.save(parsed)
    reload_error: str | None = None
    try:
        await ha_client.reload()
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("airquality.reload failed: %s", err)
        reload_error = str(err)

    return templates.TemplateResponse(
        "edit.html",
        {
            "request": request,
            "yaml_text": yaml_text,
            "errors": [],
            "saved": True,
            "reload_error": reload_error,
        },
    )


@app.get("/discover", response_class=HTMLResponse)
async def discover_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "discover.html",
        {"request": request, "result": None, "diff_lines": [], "error": None},
    )


@app.post("/discover", response_class=HTMLResponse)
async def discover_run(
    request: Request,
    stale_threshold_days: int = Form(30),
    include_stale: bool = Form(False),
) -> HTMLResponse:
    try:
        result = await ha_client.discover(
            stale_threshold_days=stale_threshold_days,
            include_stale=include_stale,
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.exception("Discovery failed")
        return templates.TemplateResponse(
            "discover.html",
            {
                "request": request,
                "result": None,
                "diff_lines": [],
                "error": f"Discovery service call failed: {err}",
            },
        )

    proposed_yaml = result.get("yaml", "")
    current_text = yaml_io.load_text()
    diff_lines = list(
        difflib.unified_diff(
            current_text.splitlines(keepends=False),
            proposed_yaml.splitlines(keepends=False),
            fromfile="current /config/airquality.yaml",
            tofile="proposed (from airquality.discover)",
            lineterm="",
        )
    )

    return templates.TemplateResponse(
        "discover.html",
        {
            "request": request,
            "result": result,
            "proposed_yaml": proposed_yaml,
            "diff_lines": diff_lines,
            "error": None,
        },
    )


@app.post("/apply", response_class=HTMLResponse)
async def apply_proposal(request: Request, proposed_yaml: str = Form(...)) -> HTMLResponse:
    """Write a proposed YAML to /config/airquality.yaml and reload."""
    try:
        parsed = yaml_io.parse_text(proposed_yaml)
    except Exception as err:  # noqa: BLE001
        return templates.TemplateResponse(
            "discover.html",
            {
                "request": request,
                "result": {"yaml": proposed_yaml, "summary": {}},
                "proposed_yaml": proposed_yaml,
                "diff_lines": [],
                "error": f"Proposed YAML failed to parse: {err}",
            },
        )

    errors = validate(parsed)
    if errors:
        return templates.TemplateResponse(
            "discover.html",
            {
                "request": request,
                "result": {"yaml": proposed_yaml, "summary": {}},
                "proposed_yaml": proposed_yaml,
                "diff_lines": [],
                "error": "Validation failed: " + "; ".join(errors),
            },
        )

    yaml_io.save(parsed)
    try:
        await ha_client.reload()
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("airquality.reload after apply failed: %s", err)

    return RedirectResponse(url="/", status_code=303)
