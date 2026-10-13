from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.noaa_spc.const import DOMAIN, GROUP_CATEGORICAL
from custom_components.noaa_spc.hub import get_hub, is_hub_entry
from tests.factories import fixed_entry, setup_entry, tracked_entry


async def test_hub_options_change_intervals(hass: HomeAssistant, mock_api) -> None:
    await setup_entry(hass, fixed_entry())
    hub_entry = next(
        e for e in hass.config_entries.async_entries(DOMAIN) if is_hub_entry(e)
    )

    result = await hass.config_entries.options.async_init(hub_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "hub"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"outlook_interval_min": 10, "alert_interval_min": 1}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    hub = get_hub(hass)
    assert hub.outlooks.update_interval == timedelta(minutes=10)
    assert hub.alerts.update_interval == timedelta(minutes=1)


async def test_fixed_location_options_move_and_drop_groups(
    hass: HomeAssistant, mock_api
) -> None:
    entry = fixed_entry()
    await setup_entry(hass, entry)
    assert er.async_get(hass).async_get("binary_sensor.spc_home_mesoscale_discussion")

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "location"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "location": {"latitude": 36.0, "longitude": -96.0},
            "groups": [GROUP_CATEGORICAL],
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        "latitude": 36.0,
        "longitude": -96.0,
        "groups": [GROUP_CATEGORICAL],
    }
    await hass.async_block_till_done()

    coordinator = entry.runtime_data
    assert coordinator.data.position == (36.0, -96.0)
    assert coordinator.groups == {GROUP_CATEGORICAL}
    assert (
        er.async_get(hass).async_get("binary_sensor.spc_home_mesoscale_discussion")
        is None
    )
    assert (
        er.async_get(hass).async_get("sensor.spc_home_day_1_tornado_probability")
        is None
    )


async def test_tracked_location_options(hass: HomeAssistant, mock_api) -> None:
    hass.states.async_set(
        "device_tracker.phone", "home", {"latitude": 35.2, "longitude": -97.4}
    )
    hass.states.async_set("person.alex", "home", {"latitude": 36.0, "longitude": -96.0})
    entry = tracked_entry()
    await setup_entry(hass, entry)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "tracked_entity": "person.alex",
            "move_threshold_km": 5,
            "groups": ["categorical", "alerts"],
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    assert coordinator.tracked_entity == "person.alex"
    assert coordinator.threshold_m == 5000
    assert coordinator.data.position == (36.0, -96.0)
