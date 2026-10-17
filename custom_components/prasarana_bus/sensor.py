"""Sensors: active bus count, next bus ETA, feed time."""
from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.components.sensor import (
    SensorDeviceClass, SensorEntity, SensorStateClass,
)
from homeassistant.const import ATTR_LATITUDE, ATTR_LONGITUDE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BusState, RouteCoordinator
from .entity import RouteEntity


def _bus_attr(s: BusState) -> dict:
    v = s.vehicle
    d = {
        "plate": v.plate,
        "latitude": v.latitude,
        "longitude": v.longitude,
        "speed_kmh": v.speed,
        "bearing": v.bearing,
        "heading_to": s.headsign,
        "last_seen": datetime.fromtimestamp(v.timestamp, timezone.utc).isoformat() if v.timestamp else None,
    }
    if s.eta_min is not None:
        d["eta_min"] = s.eta_min
        d["distance_km"] = s.distance_km
    return d


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: RouteCoordinator = entry.runtime_data
    entities: list[SensorEntity] = [ActiveBusesSensor(coordinator), FeedTimeSensor(coordinator)]
    if coordinator.stop:
        entities += [NextBusEtaSensor(coordinator), NextBusDistanceSensor(coordinator), NextBusStatusSensor(coordinator)]
        if coordinator.schedule:
            entities.append(NextScheduledSensor(coordinator))
    async_add_entities(entities)


class ActiveBusesSensor(RouteEntity, SensorEntity):
    _attr_translation_key = "active_buses"
    _attr_icon = "mdi:bus-multiple"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "buses"
    # Route line is large and static: keep it out of the database.
    _unrecorded_attributes = frozenset({"route_geojson", "buses", "route_stops"})

    def __init__(self, coordinator: RouteCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_active"
        self._set_entity_id("sensor", "active_buses")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.buses)

    @property
    def extra_state_attributes(self) -> dict:
        r = self.coordinator.route
        return {
            "route": r.short_name,
            "route_name": r.long_name,
            "buses": [_bus_attr(s) for s in self.coordinator.data.buses.values()],
            "route_geojson": self.coordinator.route_geojson,
            "route_stops": self.coordinator.route_stops,
        }


class NextBusEtaSensor(RouteEntity, SensorEntity):
    _attr_translation_key = "next_bus_eta"
    _attr_icon = "mdi:bus-clock"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: RouteCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_eta"
        self._set_entity_id("sensor", "next_bus_eta")

    @property
    def native_value(self) -> float | None:
        up = self.coordinator.data.upcoming
        if up:
            return up[0].eta_min
        nxt = _fallback(self.coordinator)
        return _minutes_until(nxt.when) if nxt else None

    @property
    def extra_state_attributes(self) -> dict:
        stop = self.coordinator.stop
        data = self.coordinator.data
        up = data.upcoming
        attrs = {
            "stop_id": stop.stop_id,
            "stop_name": stop.name,
            ATTR_LATITUDE: stop.lat,  # lets the map card pin the stop
            ATTR_LONGITUDE: stop.lon,
            "estimated": True,
            "status": _status(self.coordinator),
            "eta_source": None,
            "upcoming": [_bus_attr(s) for s in up[:5]],
            "headway_min": data.headway_min,
        }
        if up:
            attrs["eta_source"] = "live"
            attrs["plate"] = up[0].vehicle.plate
            attrs["heading_to"] = up[0].headsign
        elif nxt := _fallback(self.coordinator):
            attrs["eta_source"] = "scheduled"
            attrs["scheduled_time"] = nxt.when.isoformat()
            attrs["heading_to"] = nxt.headsign
            attrs["frequency_based"] = nxt.frequency_based
        return attrs


AT_STOP_KM = 0.15
STATUS_OPTIONS = ["approaching", "at_stop", "scheduled", "none_heading_here", "no_buses", "no_service"]


def _minutes_until(when: datetime) -> float:
    return round(max(0.0, (when - datetime.now(timezone.utc)).total_seconds() / 60), 1)


def _fallback(coordinator: RouteCoordinator):
    """Next timetable arrival, when the fallback is on and no live bus is approaching."""
    if coordinator.timetable_fallback and coordinator.data.scheduled:
        return coordinator.data.scheduled[0]
    return None


def _status(coordinator: RouteCoordinator) -> str:
    data = coordinator.data
    if data.upcoming:
        return "at_stop" if data.upcoming[0].distance_km <= AT_STOP_KM else "approaching"
    if _fallback(coordinator):
        return "scheduled"
    if data.buses:
        return "none_heading_here"
    if coordinator.schedule and not data.scheduled:
        return "no_service"  # nothing in the timetable for the next few hours either
    return "no_buses"


class NextBusStatusSensor(RouteEntity, SensorEntity):
    """Human-readable state for when the ETA has no number to show."""

    _attr_translation_key = "next_bus_status"
    _attr_icon = "mdi:bus-stop"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATUS_OPTIONS

    def __init__(self, coordinator: RouteCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_status"
        self._set_entity_id("sensor", "next_bus_status")

    @property
    def native_value(self) -> str:
        return _status(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict:
        up = self.coordinator.data.upcoming
        if up:
            return {"plate": up[0].vehicle.plate, "eta_min": up[0].eta_min, "distance_km": up[0].distance_km}
        if nxt := _fallback(self.coordinator):
            return {"scheduled_time": nxt.when.isoformat(), "eta_min": _minutes_until(nxt.when)}
        return {}


class NextBusDistanceSensor(RouteEntity, SensorEntity):
    _attr_translation_key = "next_bus_distance"
    _attr_icon = "mdi:map-marker-distance"
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_native_unit_of_measurement = "km"
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: RouteCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_distance"
        self._set_entity_id("sensor", "next_bus_distance")

    @property
    def native_value(self) -> float | None:
        up = self.coordinator.data.upcoming
        return up[0].distance_km if up else None


class FeedTimeSensor(RouteEntity, SensorEntity):
    _attr_translation_key = "feed_time"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: RouteCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_feed_time"
        self._set_entity_id("sensor", "feed_updated")

    @property
    def native_value(self):
        return self.coordinator.data.feed_time


class NextScheduledSensor(RouteEntity, SensorEntity):
    """Next arrival at the stop according to the published timetable (never live GPS)."""

    _attr_translation_key = "next_scheduled"
    _attr_icon = "mdi:timetable"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: RouteCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_next_scheduled"
        self._set_entity_id("sensor", "next_scheduled_bus")

    @property
    def native_value(self) -> datetime | None:
        sch = self.coordinator.data.scheduled
        return sch[0].when if sch else None

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        return {
            "headway_min": data.headway_min,
            "frequency_based": data.scheduled[0].frequency_based if data.scheduled else None,
            "upcoming": [
                {"time": a.when.strftime("%H:%M"), "datetime": a.when.isoformat(), "heading_to": a.headsign}
                for a in data.scheduled
            ],
        }
