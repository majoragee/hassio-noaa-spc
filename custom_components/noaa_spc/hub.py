"""Shared SPC data hub used by every config entry."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api.client import SpcClient
from .api.spc import AlertBundle, OutlookBundle, SpcApi
from .const import (
    CONF_ALERT_INTERVAL,
    CONF_ENTRY_TYPE,
    CONF_OUTLOOK_INTERVAL,
    DEFAULT_ALERT_INTERVAL,
    DEFAULT_OUTLOOK_INTERVAL,
    DOMAIN,
    ENTRY_TYPE_HUB,
)

_LOGGER = logging.getLogger(__name__)


def is_hub_entry(entry: ConfigEntry) -> bool:
    """Return True if the config entry is the shared hub entry."""
    return entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB


class OutlookCoordinator(DataUpdateCoordinator[OutlookBundle]):
    """Polls the SPC convective outlooks."""

    def __init__(self, hass: HomeAssistant, api: SpcApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=None,
            name=f"{DOMAIN} outlooks",
            update_interval=timedelta(minutes=DEFAULT_OUTLOOK_INTERVAL),
        )
        self.api = api

    async def _async_update_data(self) -> OutlookBundle:
        return await self.api.fetch_outlooks(self.data)


class AlertCoordinator(DataUpdateCoordinator[AlertBundle]):
    """Polls SPC watches and mesoscale discussions."""

    def __init__(self, hass: HomeAssistant, api: SpcApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=None,
            name=f"{DOMAIN} alerts",
            update_interval=timedelta(minutes=DEFAULT_ALERT_INTERVAL),
        )
        self.api = api

    async def _async_update_data(self) -> AlertBundle:
        return await self.api.fetch_alerts(self.data)


class SpcHub:
    """Owns the API client and both coordinators."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.api = SpcApi(SpcClient(async_get_clientsession(hass)))
        self.outlooks = OutlookCoordinator(hass, self.api)
        self.alerts = AlertCoordinator(hass, self.api)
        self.users = 0

    def apply_options(self, options: Mapping[str, Any]) -> None:
        """Apply polling intervals from entry options."""
        self.outlooks.update_interval = timedelta(
            minutes=options.get(CONF_OUTLOOK_INTERVAL, DEFAULT_OUTLOOK_INTERVAL)
        )
        self.alerts.update_interval = timedelta(
            minutes=options.get(CONF_ALERT_INTERVAL, DEFAULT_ALERT_INTERVAL)
        )

    async def async_start(self) -> None:
        """Register shutdown hooks and perform the first refresh."""
        # Not tied to a config entry, so stop polling explicitly on HA shutdown.
        await self.outlooks.async_register_shutdown()
        await self.alerts.async_register_shutdown()
        await self.outlooks.async_refresh()
        await self.alerts.async_refresh()

    async def async_stop(self) -> None:
        """Stop both coordinators."""
        await self.outlooks.async_shutdown()
        await self.alerts.async_shutdown()


@dataclass
class _HubState:
    lock: asyncio.Lock
    hub: SpcHub | None = None


def _state(hass: HomeAssistant) -> _HubState:
    return hass.data.setdefault(DOMAIN, _HubState(asyncio.Lock()))


def get_hub(hass: HomeAssistant) -> SpcHub | None:
    """Return the running hub, if any."""
    state = hass.data.get(DOMAIN)
    return state.hub if state else None


async def async_acquire_hub(hass: HomeAssistant) -> SpcHub:
    """Return the shared hub, creating and starting it on first use."""
    state = _state(hass)
    async with state.lock:
        if state.hub is None:
            hub = SpcHub(hass)
            await hub.async_start()
            state.hub = hub
        state.hub.users += 1
        return state.hub


async def async_release_hub(hass: HomeAssistant) -> None:
    """Drop one reference; stop the hub when the last user releases it."""
    state = hass.data.get(DOMAIN)
    if state is None:
        return
    async with state.lock:
        if state.hub is None:
            return
        state.hub.users -= 1
        if state.hub.users <= 0:
            await state.hub.async_stop()
            state.hub = None
