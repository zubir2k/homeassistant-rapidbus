"""Coordinator for one monitored route."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import logging
from zoneinfo import ZoneInfo

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_CATEGORY, CONF_ROUTE, CONF_SCAN_INTERVAL, CONF_STOP, CONF_TIMETABLE_FALLBACK,
    DEFAULT_SCAN_INTERVAL, DOMAIN, FEED_TZ, NO_STOP, SCHEDULE_HORIZON_H,
)
from .data import get_data
from .gtfs_rt import Vehicle
from .gtfs_static import (
    GtfsStatic, RouteDetail, ScheduledArrival, StopSchedule, eta_to_stop, locate, route_geojson,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class BusState:
    vehicle: Vehicle
    headsign: str | None = None
    eta_min: float | None = None
    distance_km: float | None = None


@dataclass
class RouteData:
    feed_time: datetime | None
    buses: dict[str, BusState] = field(default_factory=dict)  # plate -> state
    upcoming: list[BusState] = field(default_factory=list)  # sorted by ETA
    scheduled: list[ScheduledArrival] = field(default_factory=list)  # timetable, next few
    headway_min: float | None = None


class RouteCoordinator(DataUpdateCoordinator[RouteData]):
    """Polls the realtime feed and filters it to one route."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, static: GtfsStatic, detail: RouteDetail,
                 schedule: StopSchedule | None = None) -> None:
        opts = {**entry.data, **entry.options}
        super().__init__(
            hass, _LOGGER, config_entry=entry,
            name=f"{DOMAIN}_{entry.data[CONF_ROUTE]}",
            update_interval=timedelta(seconds=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        )
        self.category: str = entry.data[CONF_CATEGORY]
        self.static = static
        self.route_key: str = entry.data[CONF_ROUTE]
        stop = opts.get(CONF_STOP) or NO_STOP
        self.stop_id: str | None = None if stop == NO_STOP else stop
        self.detail = detail
        self.route = self.detail.route
        self.stop = self.detail.stops.get(self.stop_id) if self.stop_id else None
        self.route_geojson = route_geojson(self.detail)
        # [lat, lon, name] per stop, for the card's stop dots
        self.route_stops = [[round(st.lat, 6), round(st.lon, 6), st.short_name] for st in self.detail.stops.values()]
        self.schedule = schedule
        self.timetable_fallback: bool = opts.get(CONF_TIMETABLE_FALLBACK, True)
        self._tz = ZoneInfo(FEED_TZ)

    async def _async_update_data(self) -> RouteData:
        try:
            header_ts, vehicles = await get_data(self.hass).async_get_realtime(self.category)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise UpdateFailed(f"Realtime feed error: {err}") from err
        return await self.hass.async_add_executor_job(self._process, header_ts, vehicles)

    def _process(self, header_ts: int, vehicles: list[Vehicle]) -> RouteData:
        out = RouteData(datetime.fromtimestamp(header_ts, timezone.utc) if header_ts else None)
        for v in vehicles:
            if self.static.match_route(v.route_id) != self.route_key:
                continue
            st = BusState(v)
            loc = locate(self.detail, v.latitude, v.longitude, v.bearing)
            if loc:
                st.headsign = loc[0].headsign
            if self.stop_id:
                res = eta_to_stop(self.detail, self.stop_id, v.latitude, v.longitude, v.bearing, v.speed)
                if res:
                    st.eta_min, st.distance_km, _ = res
                    out.upcoming.append(st)
            out.buses[v.plate] = st
        out.upcoming.sort(key=lambda s: s.eta_min)
        if self.schedule:
            now = datetime.now(self._tz)
            out.scheduled = self.schedule.next_arrivals(now, 5, SCHEDULE_HORIZON_H)
            out.headway_min = self.schedule.headway_min(now)
            if out.headway_min is None and len(out.scheduled) >= 2:
                gap = (out.scheduled[1].when - out.scheduled[0].when).total_seconds() / 60
                out.headway_min = round(gap, 1)
        return out
