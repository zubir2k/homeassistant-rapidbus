"""Rapid Bus Tracker: unofficial live tracking of RapidKL, MRT feeder, Rapid Kuantan and Rapid Penang buses for Home Assistant."""
from __future__ import annotations

import aiohttp
import asyncio

from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady

from .card_registration import async_register_card, async_unregister_card
from .const import CONF_CATEGORY, CONF_ROUTE, CONF_STOP, DOMAIN, NO_STOP
from .coordinator import RouteCoordinator
from .data import get_data
from .gtfs_static import build_stop_schedule

PLATFORMS = [Platform.SENSOR, Platform.DEVICE_TRACKER]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the bundled rapidbus-card and register it for dashboards (runs once per HA start)."""
    await async_register_card(hass)
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


async def async_remove_entry(hass: HomeAssistant, entry: PrasaranaConfigEntry) -> None:
    """Remove the card's dashboard resource when the last entry is deleted.

    Not done on unload: reloading an entry should not make the card disappear.
    """
    if not [e for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id != entry.entry_id]:
        await async_unregister_card(hass)
