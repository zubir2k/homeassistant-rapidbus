"""Prasarana Bus (RapidKL) live tracking for Home Assistant."""
from __future__ import annotations

import aiohttp
import asyncio
import json
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_CATEGORY, CONF_ROUTE, CONF_STOP, DOMAIN, NO_STOP
from .coordinator import RouteCoordinator
from .data import get_data
from .gtfs_static import build_stop_schedule

PLATFORMS = [Platform.SENSOR, Platform.DEVICE_TRACKER]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
CARD_URL = "/prasarana_bus_static"
_VERSION = json.loads((Path(__file__).parent / "manifest.json").read_text())["version"]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the bundled rapidbus-card and load it in every dashboard (no HACS frontend install needed)."""
    if hass.http is None:  # e.g. tests without http
        return True
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(Path(__file__).parent / "frontend"), True)]
    )
    try:
        from homeassistant.components.frontend import add_extra_js_url
        add_extra_js_url(hass, f"{CARD_URL}/rapidbus-card.js?v={_VERSION}")
    except (ImportError, KeyError):  # frontend not loaded
        pass
    return True

type PrasaranaConfigEntry = ConfigEntry[RouteCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: PrasaranaConfigEntry) -> bool:
    data = get_data(hass)
    try:
        static = await data.async_get_static(entry.data[CONF_CATEGORY])
    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        raise ConfigEntryNotReady(f"Cannot download GTFS static data: {err}") from err
    if entry.data[CONF_ROUTE] not in static.routes:
        raise ConfigEntryNotReady(f"Route {entry.data[CONF_ROUTE]} no longer in GTFS static data")
    detail = await hass.async_add_executor_job(static.detail, entry.data[CONF_ROUTE])
    stop_id = {**entry.data, **entry.options}.get(CONF_STOP) or NO_STOP
    schedule = None
    if stop_id != NO_STOP:
        schedule = await hass.async_add_executor_job(
            build_stop_schedule, static, entry.data[CONF_ROUTE], stop_id)
    coordinator = RouteCoordinator(hass, entry, static, detail, schedule)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))

    if not hass.services.has_service(DOMAIN, "refresh_static"):
        async def _refresh_static(call: ServiceCall) -> None:
            cats = {e.data[CONF_CATEGORY] for e in hass.config_entries.async_entries(DOMAIN)}
            for cat in cats:
                await data.async_get_static(cat, force=True)
            for e in hass.config_entries.async_entries(DOMAIN):
                hass.async_create_task(hass.config_entries.async_reload(e.entry_id))

        hass.services.async_register(DOMAIN, "refresh_static", _refresh_static)
    return True


async def _async_reload(hass: HomeAssistant, entry: PrasaranaConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: PrasaranaConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
