"""Fixtures for Rapid Bus Tracker tests."""
try:
    import pycares

    if hasattr(pycares, "_shutdown_manager"):
        pycares._shutdown_manager.start()
    else:
        pycares.Channel()
except Exception:
    pass

from unittest.mock import patch
import pytest

from homeassistant.config_entries import ConfigEntryState
from custom_components.prasarana_bus.const import DOMAIN

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def no_http_server():
    """Don't open a real port during tests."""
    with patch("homeassistant.components.http.HomeAssistantHTTP.start"):
        yield


@pytest.fixture(autouse=True)
async def cleanup_entries(hass):
    """Clean up and unload any config entries after each test."""
    yield
    for entry in list(hass.config_entries.async_entries(DOMAIN)):
        if entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(entry.entry_id)
            await hass.async_block_till_done()
