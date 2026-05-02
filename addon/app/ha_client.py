"""Client for calling Home Assistant services from inside the add-on.

Uses SUPERVISOR_TOKEN to authenticate against http://supervisor/core/api/.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

_LOGGER = logging.getLogger(__name__)

_SUPERVISOR_API = "http://supervisor/core/api"


def _token() -> str:
    """Return the supervisor token (set in the addon's container env)."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise RuntimeError("SUPERVISOR_TOKEN is not set — addon must run inside HA Supervisor.")
    return token


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_token()}",
        "Content-Type": "application/json",
    }


async def call_service(
    domain: str,
    service: str,
    data: dict[str, Any] | None = None,
    *,
    return_response: bool = False,
) -> Any:
    """Call a HA service. If return_response, fetches the service response data."""
    url = f"{_SUPERVISOR_API}/services/{domain}/{service}"
    if return_response:
        url += "?return_response"

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=data or {}, headers=_headers())
        resp.raise_for_status()
        body = resp.json()

    if return_response:
        # HA returns {"changed_states": [...], "service_response": {...}}
        if isinstance(body, dict) and "service_response" in body:
            return body["service_response"]
    return body


async def discover(
    *,
    stale_threshold_days: int = 30,
    include_stale: bool = False,
) -> dict[str, Any]:
    """Run the airquality.discover service and return its response data."""
    return await call_service(
        "airquality",
        "discover",
        {
            "stale_threshold_days": stale_threshold_days,
            "include_stale": include_stale,
            "write_to_file": False,
        },
        return_response=True,
    )


async def reload() -> None:
    """Trigger airquality.reload."""
    await call_service("airquality", "reload")
