"""The NOAA Storm Prediction Center integration."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.typing import ConfigType

from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_HUB, ISSUE_MISSING_TRACKER
from .hub import async_acquire_hub, async_release_hub, is_hub_entry
from .location import LocationCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

HUB_PLATFORMS = [Platform.SENSOR]
LOCATION_PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    if not any(is_hub_entry(e) for e in hass.config_entries.async_entries(DOMAIN)):
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_IMPORT},
                data={CONF_ENTRY_TYPE: ENTRY_TYPE_HUB},
            )
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hub = await async_acquire_hub(hass)
    if is_hub_entry(entry):
        hub.apply_options(entry.options)
        entry.runtime_data = hub
        platforms = HUB_PLATFORMS
    else:
        coordinator = LocationCoordinator(hass, entry, hub)
        await coordinator.async_start()
        entry.runtime_data = coordinator
        platforms = LOCATION_PLATFORMS
    await hass.config_entries.async_forward_entry_setups(entry, platforms)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    platforms = HUB_PLATFORMS if is_hub_entry(entry) else LOCATION_PLATFORMS
    unloaded = await hass.config_entries.async_unload_platforms(entry, platforms)
    if unloaded:
        await async_release_hub(hass)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_MISSING_TRACKER}_{entry.entry_id}")
