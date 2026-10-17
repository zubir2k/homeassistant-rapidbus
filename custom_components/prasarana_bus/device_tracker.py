"""One device_tracker per live bus, so buses show on the HA map."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_STALE_MINUTES, DEFAULT_STALE_MINUTES, DOMAIN
from .coordinator import RouteCoordinator
from .entity import RouteEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: RouteCoordinator = entry.runtime_data
    stale = timedelta(minutes={**entry.data, **entry.options}.get(CONF_STALE_MINUTES, DEFAULT_STALE_MINUTES))
    trackers: dict[str, BusTracker] = {}
    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_bus_"

    # Clean up buses left over from a previous run; live ones get re-added.
    for ent in er.async_entries_for_config_entry(registry, entry.entry_id):
        if ent.domain == "device_tracker" and ent.unique_id.startswith(prefix):
            registry.async_remove(ent.entity_id)

    @callback
    def _sync() -> None:
        now = datetime.now(timezone.utc)
        new = []
        for plate in coordinator.data.buses:
            if plate not in trackers:
                trackers[plate] = BusTracker(coordinator, plate)
                new.append(trackers[plate])
            trackers[plate].last_seen = now
        if new:
            async_add_entities(new)
        for plate, tr in list(trackers.items()):
            if plate not in coordinator.data.buses and now - tr.last_seen > stale:
                trackers.pop(plate)
                if tr.entity_id and registry.async_get(tr.entity_id):
                    registry.async_remove(tr.entity_id)
                else:
                    hass.async_create_task(tr.async_remove())

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))


class BusTracker(RouteEntity, TrackerEntity):
    _attr_icon = "mdi:bus"

    def __init__(self, coordinator: RouteCoordinator, plate: str) -> None:
        super().__init__(coordinator)
        self.plate = plate
        self.last_seen = datetime.now(timezone.utc)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_bus_{plate}"
        self._attr_name = plate
        self._set_entity_id("device_tracker", plate)

    @property
    def _bus(self):
        return self.coordinator.data.buses.get(self.plate)

    @property
    def available(self) -> bool:
        return super().available and self._bus is not None

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        return self._bus.vehicle.latitude if self._bus else None

    @property
    def longitude(self) -> float | None:
        return self._bus.vehicle.longitude if self._bus else None

    @property
    def location_accuracy(self) -> int:
        return 20

    @property
    def extra_state_attributes(self) -> dict:
        b = self._bus
        if not b:
            return {}
        v = b.vehicle
        attrs = {
            "route": self.coordinator.route.short_name,
            "plate": v.plate,
            "speed_kmh": v.speed,
            "bearing": v.bearing,
            "heading_to": b.headsign,
            "trip_id": v.trip_id,
            "last_seen": datetime.fromtimestamp(v.timestamp, timezone.utc).isoformat() if v.timestamp else None,
        }
        if b.eta_min is not None:
            attrs["eta_min"] = b.eta_min
            attrs["distance_km"] = b.distance_km
        return attrs
