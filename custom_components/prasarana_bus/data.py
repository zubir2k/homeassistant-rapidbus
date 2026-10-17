"""Shared fetching/caching of static and realtime feeds."""
from __future__ import annotations

import asyncio
import logging
import os
import time

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, RT_URL, STATIC_MAX_AGE, STATIC_URL
from .gtfs_rt import Vehicle, parse_feed
from .gtfs_static import GtfsStatic

_LOGGER = logging.getLogger(__name__)
RT_CACHE_SECONDS = 10


class PrasaranaData:
    """One instance per HA, shared by all config entries."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._static: dict[str, GtfsStatic] = {}
        self._static_lock = asyncio.Lock()
        self._rt: dict[str, tuple[float, int, list[Vehicle]]] = {}
        self._rt_locks: dict[str, asyncio.Lock] = {}

    def _path(self, category: str) -> str:
        return self.hass.config.path(".storage", DOMAIN, f"{category}.zip")

    async def async_get_static(self, category: str, force: bool = False) -> GtfsStatic:
        """Load static GTFS from disk cache, downloading when old or missing."""
        async with self._static_lock:
            if not force and category in self._static:
                return self._static[category]
            path = self._path(category)

            def _read_cached() -> bytes | None:
                if os.path.exists(path) and time.time() - os.path.getmtime(path) < STATIC_MAX_AGE.total_seconds():
                    with open(path, "rb") as fh:
                        return fh.read()
                return None

            raw = None if force else await self.hass.async_add_executor_job(_read_cached)
            if raw is None:
                session = async_get_clientsession(self.hass)
                try:
                    async with session.get(STATIC_URL.format(category=category), timeout=aiohttp.ClientTimeout(total=120)) as resp:
                        resp.raise_for_status()
                        raw = await resp.read()

                    def _write() -> None:
                        os.makedirs(os.path.dirname(path), exist_ok=True)
                        with open(path, "wb") as fh:
                            fh.write(raw)

                    await self.hass.async_add_executor_job(_write)
                except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                    if os.path.exists(path):  # fall back to stale copy
                        _LOGGER.warning("Static GTFS download failed (%s), using cached copy", err)
                        raw = await self.hass.async_add_executor_job(lambda: open(path, "rb").read())
                    else:
                        raise
            static = await self.hass.async_add_executor_job(GtfsStatic, raw)
            self._static[category] = static
            return static

    async def async_get_realtime(self, category: str) -> tuple[int, list[Vehicle]]:
        """Fetch realtime vehicles, de-duplicated across entries for a few seconds."""
        lock = self._rt_locks.setdefault(category, asyncio.Lock())
        async with lock:
            cached = self._rt.get(category)
            if cached and time.monotonic() - cached[0] < RT_CACHE_SECONDS:
                return cached[1], cached[2]
            session = async_get_clientsession(self.hass)
            async with session.get(RT_URL.format(category=category), timeout=aiohttp.ClientTimeout(total=20)) as resp:
                resp.raise_for_status()
                raw = await resp.read()
            header_ts, vehicles = parse_feed(raw)
            self._rt[category] = (time.monotonic(), header_ts, vehicles)
            return header_ts, vehicles


def get_data(hass: HomeAssistant) -> PrasaranaData:
    data = hass.data.get(DOMAIN)
    if data is None:
        data = hass.data[DOMAIN] = PrasaranaData(hass)
    return data
