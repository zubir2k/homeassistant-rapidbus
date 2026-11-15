"""Diagnostics support for Rapid Bus Tracker."""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import PrasaranaConfigEntry
from .sensor import _bus_attr


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PrasaranaConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "entry_data": dict(entry.data),
        "entry_options": dict(entry.options),
        "route": {
            "key": coordinator.route.key,
            "short_name": coordinator.route.short_name,
            "long_name": coordinator.route.long_name,
            "shapes_count": len(coordinator.detail.shapes),
            "stops_count": len(coordinator.detail.stops),
        },
        "stop": {
            "stop_id": coordinator.stop.stop_id,
            "name": coordinator.stop.name,
            "lat": coordinator.stop.lat,
            "lon": coordinator.stop.lon,
        }
        if coordinator.stop
        else None,
        "realtime": {
            "feed_time": data.feed_time.isoformat() if data and data.feed_time else None,
            "active_buses_count": len(data.buses) if data else 0,
            "buses": [_bus_attr(b) for b in data.buses.values()] if data else [],
            "upcoming_count": len(data.upcoming) if data else 0,
            "headway_min": data.headway_min if data else None,
            "scheduled_next": [
                {
                    "when": a.when.isoformat(),
                    "headsign": a.headsign,
                    "frequency_based": a.frequency_based,
                }
                for a in (data.scheduled if data else [])
            ],
        },
    }
