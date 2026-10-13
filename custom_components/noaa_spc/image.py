"""Outlook map images for NOAA SPC."""

from __future__ import annotations

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .api.products import IMAGE_PATHS
from .const import OUTLOOK_STALE
from .entity import SpcHubEntity, is_fresh
from .hub import OutlookCoordinator, SpcHub

HAZARD_NAMES = {"torn": "tornado", "wind": "wind", "hail": "hail"}


def _name(key: str) -> str:
    if key == "day48":
        return "Day 4–8 outlook"
    day, _, hazard = key.partition("_")
    number = day.removeprefix("day")
    if hazard:
        return f"Day {number} {HAZARD_NAMES[hazard]} outlook"
    return f"Day {number} outlook"


class SpcImage(SpcHubEntity, ImageEntity):
    coordinator: OutlookCoordinator

    def __init__(
        self, hass: HomeAssistant, coordinator: OutlookCoordinator, key: str
    ) -> None:
        SpcHubEntity.__init__(self, coordinator, f"image_{key}")
        ImageEntity.__init__(self, hass)
        self._key = key
        self._attr_name = _name(key)
        self._attr_content_type = IMAGE_PATHS[key][1]
        self._attr_entity_registry_enabled_default = "_" not in key
        self._image: bytes | None = None
        self._sync()

    def _sync(self) -> None:
        data = self.coordinator.data
        image = data.images.get(self._key) if data else None
        if image is not None and image != self._image:
            self._image = image
            self._attr_image_last_updated = dt_util.utcnow()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._sync()
        super()._handle_coordinator_update()

    @property
    def available(self) -> bool:
        data = self.coordinator.data
        return (
            super().available
            and data is not None
            and self._image is not None
            and is_fresh(data.updated.get(f"image:{self._key}"), OUTLOOK_STALE)
        )

    async def async_image(self) -> bytes | None:
        return self._image


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: SpcHub = entry.runtime_data
    async_add_entities(SpcImage(hass, hub.outlooks, key) for key in IMAGE_PATHS)
