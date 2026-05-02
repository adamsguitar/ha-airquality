"""Pytest configuration and shared fixtures for Air Quality integration tests."""
from __future__ import annotations

import pytest

DOMAIN = "airquality"

try:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(enable_custom_integrations):
        """Enable custom integrations for all tests in this package."""
        return

    @pytest.fixture
    def mock_config_entry() -> MockConfigEntry:
        """Return a minimal config entry for the integration."""
        return MockConfigEntry(domain=DOMAIN, data={}, unique_id=DOMAIN)

except ImportError:
    # pytest-homeassistant-custom-component not installed (e.g. CI lightweight run).
    # HA-dependent fixtures will be unavailable; pure-Python tests still run.
    pass
