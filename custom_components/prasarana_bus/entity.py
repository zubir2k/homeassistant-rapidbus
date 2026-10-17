"""Base entity."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import CATEGORIES, DOMAIN
from .coordinator import RouteCoordinator


class RouteEntity(CoordinatorEntity[RouteCoordinator]):
    _attr_has_entity_name = True
    _attr_attribution = "Data: Prasarana via data.gov.my (CC BY 4.0)"

    def __init__(self, coordinator: RouteCoordinator) -> None:
        super().__init__(coordinator)
        # Object-id base: rapidbus_<route>[_<stop>], e.g. rapidbus_t455, rapidbus_450_kl_sentral
        base = f"rapidbus_{slugify(coordinator.route.short_name)}"
        if coordinator.stop:
            base += f"_{slugify(coordinator.stop.short_name)}"
        self._object_base = base
        entry = coordinator.config_entry
        r = coordinator.route
        name = f"Bus {r.short_name}"
        if coordinator.stop:
            name += f" @ {coordinator.stop.short_name}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=name,
            manufacturer="Prasarana",
            model=CATEGORIES.get(coordinator.category, coordinator.category),
            entry_type=DeviceEntryType.SERVICE,
        )

    def _set_entity_id(self, domain: str, suffix: str) -> None:
        """Suggest a predictable entity_id (users can still rename it)."""
        self.entity_id = f"{domain}.{self._object_base}_{slugify(suffix)}"
