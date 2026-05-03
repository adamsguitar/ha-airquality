"""Config flow for the Air Quality integration.

Single-instance only: one config entry drives the whole integration.
The YAML file path is fixed at /config/airquality.yaml — there is nothing
for the user to configure in the flow other than confirming setup.
"""
from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.exceptions import ConfigEntryError

from .const import DOMAIN, YAML_FILENAME

_LOGGER = logging.getLogger(__name__)


class AirQualityConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Air Quality."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        """Handle the initial user step."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title="Air Quality", data={})

        yaml_path = Path(self.hass.config.config_dir) / YAML_FILENAME
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
            description_placeholders={
                "yaml_path": str(yaml_path),
                "file_status": (
                    "found — existing configuration will be loaded"
                    if yaml_path.exists()
                    else "not found — an example configuration will be created"
                ),
            },
        )
