from datetime import timedelta

from homeassistant.core import HomeAssistant

from custom_components.noaa_spc.const import CONF_ALERT_INTERVAL, CONF_OUTLOOK_INTERVAL
from custom_components.noaa_spc.hub import (
    async_acquire_hub,
    async_release_hub,
    get_hub,
)


async def test_acquire_is_shared_and_starts_coordinators(
    hass: HomeAssistant, mock_api
) -> None:
    hub = await async_acquire_hub(hass)
    again = await async_acquire_hub(hass)
    assert hub is again
    assert hub.users == 2
    assert hub.outlooks.data is mock_api.outlooks
    assert hub.alerts.data is mock_api.alerts
    assert hub.outlooks.update_interval == timedelta(minutes=5)
    assert hub.alerts.update_interval == timedelta(minutes=2)

    await async_release_hub(hass)
    assert get_hub(hass) is hub
    await async_release_hub(hass)
    assert get_hub(hass) is None


async def test_apply_options(hass: HomeAssistant, mock_api) -> None:
    hub = await async_acquire_hub(hass)
    hub.apply_options({CONF_OUTLOOK_INTERVAL: 10, CONF_ALERT_INTERVAL: 1})
    assert hub.outlooks.update_interval == timedelta(minutes=10)
    assert hub.alerts.update_interval == timedelta(minutes=1)
    await async_release_hub(hass)


async def test_release_without_hub_is_noop(hass: HomeAssistant) -> None:
    await async_release_hub(hass)
    assert get_hub(hass) is None
