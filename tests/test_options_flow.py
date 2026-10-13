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


async def test_options_change_updates_unique_id(hass: HomeAssistant, mock_api) -> None:
    hass.states.async_set("person.a", "home", {"latitude": 35.2, "longitude": -97.4})
    hass.states.async_set("person.b", "home", {"latitude": 36.0, "longitude": -96.0})
    entry = tracked_entry("person.a", title="A")
    await setup_entry(hass, entry)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "tracked_entity": "person.b",
            "move_threshold_km": 5,
            "groups": ["categorical"],
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.unique_id == "tracked_person.b"
    await hass.async_block_till_done()

    # person.a is free again, so a new location can follow it.
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"next_step_id": "tracked"}
    )
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"name": "A again", "tracked_entity": "person.a"}
    )
    assert flow["type"] is FlowResultType.CREATE_ENTRY


async def test_fixed_options_change_updates_unique_id(
    hass: HomeAssistant, mock_api
) -> None:
    entry = fixed_entry()
    await setup_entry(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"location": {"latitude": 36.0, "longitude": -96.0}, "groups": ["categorical"]},
    )
    assert entry.unique_id == "fixed_36.000_-96.000"


async def test_options_reject_entity_used_by_another_entry(
    hass: HomeAssistant, mock_api
) -> None:
    hass.states.async_set("person.a", "home", {"latitude": 35.2, "longitude": -97.4})
    entry = tracked_entry("person.a", title="A")
    other = tracked_entry("person.b", title="B")
    other.add_to_hass(hass)
    await setup_entry(hass, entry)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "tracked_entity": "person.b",
            "move_threshold_km": 5,
            "groups": ["categorical"],
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "already_configured"}
    assert entry.unique_id == "tracked_person.a"
    assert entry.options == {}

    # Keeping its own entity is not a conflict.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "tracked_entity": "person.a",
            "move_threshold_km": 5,
            "groups": ["categorical"],
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
