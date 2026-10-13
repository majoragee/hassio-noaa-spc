"""Binary sensor platform for NOAA SPC mesoscale discussions."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ALERT_STALE, GROUP_ALERTS
from .entity import (
    SpcLocationEntity,
    async_remove_entities,
    is_fresh,
    md_attributes,
)
from .location import LocationCoordinator

MD_KEY = "mesoscale_discussion"


class MesoscaleDiscussionBinarySensor(SpcLocationEntity, BinarySensorEntity):
    _attr_name = "Mesoscale discussion"
    _unrecorded_attributes = frozenset({"summary", "items"})

    def __init__(self, coordinator: LocationCoordinator) -> None:
        super().__init__(coordinator, MD_KEY)

    def _items(self) -> list[dict[str, Any]]:
        return [md_attributes(md) for md in self.coordinator.data.alerts.mds]

    @property
    def available(self) -> bool:
        data = self.coordinator.data
        return (
            super().available
            and data is not None
            and data.position is not None
            and data.alerts is not None
            and is_fresh(data.mds_updated, ALERT_STALE)
        )

    @property
    def is_on(self) -> bool:
        return bool(self._items())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        items = self._items()
        return {
            **(items[0] if items else {}),
            "items": items,
        }


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: LocationCoordinator = entry.runtime_data
    if GROUP_ALERTS not in coordinator.groups:
        async_remove_entities(
            hass, Platform.BINARY_SENSOR, [f"{entry.entry_id}_{MD_KEY}"]
        )
        return
    async_add_entities([MesoscaleDiscussionBinarySensor(coordinator)])
