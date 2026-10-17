"""Config flow: category -> route -> optional stop."""
from __future__ import annotations

import asyncio
import re
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector, NumberSelector, NumberSelectorConfig, NumberSelectorMode,
    SelectOptionDict, SelectSelector, SelectSelectorConfig, SelectSelectorMode,
)

from .const import (
    CATEGORIES, CONF_CATEGORY, CONF_ROUTE, CONF_SCAN_INTERVAL, CONF_STALE_MINUTES, CONF_TIMETABLE_FALLBACK, CONF_STOP,
    DEFAULT_SCAN_INTERVAL, DEFAULT_STALE_MINUTES, DOMAIN, MIN_SCAN_INTERVAL, NO_STOP,
)
from .data import get_data
from .gtfs_static import GtfsStatic, RouteDetail


def _natural(s: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def _stop_options(detail: RouteDetail) -> list[SelectOptionDict]:
    opts = [SelectOptionDict(value=NO_STOP, label="No stop (tracking only)")]
    seen = set()
    for sh in detail.shapes:
        for stop_id, _ in sh.stops:
            if stop_id in seen:
                continue
            seen.add(stop_id)
            s = detail.stops[stop_id]
            opts.append(SelectOptionDict(value=stop_id, label=f"{s.name} ({stop_id}) → {sh.headsign}"))
    return opts


class PrasaranaConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._category: str | None = None
        self._static: GtfsStatic | None = None
        self._route: str | None = None
        self._detail: RouteDetail | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._category = user_input[CONF_CATEGORY]
            try:
                self._static = await get_data(self.hass).async_get_static(self._category)
            except (aiohttp.ClientError, asyncio.TimeoutError):
                errors["base"] = "cannot_connect"
            else:
                return await self.async_step_route()
        schema = vol.Schema({
            vol.Required(CONF_CATEGORY, default="rapid-bus-kl"): SelectSelector(SelectSelectorConfig(
                options=[SelectOptionDict(value=k, label=v) for k, v in CATEGORIES.items()],
                mode=SelectSelectorMode.LIST)),
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_route(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._static
        if user_input is not None:
            self._route = user_input[CONF_ROUTE]
            self._detail = await self.hass.async_add_executor_job(self._static.detail, self._route)
            return await self.async_step_stop()
        routes = sorted(self._static.routes.values(), key=lambda r: _natural(r.short_name))
        schema = vol.Schema({
            vol.Required(CONF_ROUTE): SelectSelector(SelectSelectorConfig(
                options=[SelectOptionDict(value=r.key, label=r.label) for r in routes],
                mode=SelectSelectorMode.DROPDOWN)),
        })
        return self.async_show_form(step_id="route", data_schema=schema)

    async def async_step_stop(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._detail and self._category and self._route
        if user_input is not None:
            stop = user_input.get(CONF_STOP, NO_STOP)
            await self.async_set_unique_id(f"{self._category}_{self._route}_{stop}")
            self._abort_if_unique_id_configured()
            r = self._detail.route
            title = f"Bus {r.short_name}"
            if stop != NO_STOP:
                title += f" @ {self._detail.stops[stop].short_name}"
            return self.async_create_entry(title=title, data={
                CONF_CATEGORY: self._category, CONF_ROUTE: self._route, CONF_STOP: stop,
            })
        schema = vol.Schema({
            vol.Required(CONF_STOP, default=NO_STOP): SelectSelector(SelectSelectorConfig(
                options=_stop_options(self._detail), mode=SelectSelectorMode.DROPDOWN)),
        })
        return self.async_show_form(step_id="stop", data_schema=schema,
                                    description_placeholders={"route": self._detail.route.label})

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return PrasaranaOptionsFlow()


class PrasaranaOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        cur = {**self.config_entry.data, **self.config_entry.options}
        schema = vol.Schema({
            vol.Required(CONF_SCAN_INTERVAL, default=cur.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)):
                NumberSelector(NumberSelectorConfig(min=MIN_SCAN_INTERVAL, max=600, step=5,
                                                    unit_of_measurement="s", mode=NumberSelectorMode.BOX)),
            vol.Required(CONF_STALE_MINUTES, default=cur.get(CONF_STALE_MINUTES, DEFAULT_STALE_MINUTES)):
                NumberSelector(NumberSelectorConfig(min=1, max=120, step=1,
                                                    unit_of_measurement="min", mode=NumberSelectorMode.BOX)),
            vol.Required(CONF_TIMETABLE_FALLBACK, default=cur.get(CONF_TIMETABLE_FALLBACK, True)): BooleanSelector(),
        })
        return self.async_show_form(step_id="init", data_schema=schema)
