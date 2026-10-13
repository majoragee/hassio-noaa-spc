"""Scaffold sanity checks."""

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from custom_components.noaa_spc.const import DOMAIN


async def test_integration_manifest_loads(hass: HomeAssistant) -> None:
    integration = await async_get_integration(hass, DOMAIN)
    assert integration.domain == "noaa_spc"
    assert integration.config_flow is True
    assert integration.requirements == []
