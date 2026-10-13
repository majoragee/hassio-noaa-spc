"""Shared entity helpers for NOAA SPC."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.util import dt as dt_util

from .api.models import MesoscaleDiscussion, Watch
from .const import DOMAIN, MANUFACTURER, SPC_SITE
from .location import LocationCoordinator


def is_fresh(timestamp: datetime | None, max_age: timedelta) -> bool:
    return timestamp is not None and dt_util.utcnow() - timestamp <= max_age


def watch_attributes(watch: Watch) -> dict[str, Any]:
    return {
        "number": watch.number,
        "type": watch.kind,
        "pds": watch.pds,
        "url": watch.url,
    }


def md_attributes(md: MesoscaleDiscussion) -> dict[str, Any]:
    return {
        "number": md.number,
        "areas_affected": md.areas_affected,
        "concerning": md.concerning,
        "watch_probability": md.watch_probability,
        "summary": md.summary,
        "url": md.url,
    }


def async_remove_entities(
    hass: HomeAssistant, domain: str, unique_ids: Iterable[str]
) -> None:
    registry = er.async_get(hass)
    for unique_id in unique_ids:
        if entity_id := registry.async_get_entity_id(domain, DOMAIN, unique_id):
            registry.async_remove(entity_id)


class SpcLocationEntity(CoordinatorEntity[LocationCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: LocationCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"SPC – {entry.title}",
            manufacturer=MANUFACTURER,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=SPC_SITE,
        )


class SpcHubEntity(CoordinatorEntity[DataUpdateCoordinator[Any]]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: DataUpdateCoordinator[Any], key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"hub_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hub")},
            name="NOAA SPC",
            manufacturer=MANUFACTURER,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=SPC_SITE,
        )
