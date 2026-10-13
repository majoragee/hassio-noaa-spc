from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.noaa_spc.const import (
    CONF_GROUPS,
    DOMAIN,
    ENTRY_TYPE_HUB,
    GROUP_CATEGORICAL,
)
from custom_components.noaa_spc.hub import get_hub
from tests.factories import (
    alert_bundle,
    fixed_entry,
    make_md,
    outlook_bundle,
    risk_layers,
    setup_entry,
)
from tests.helpers import collection


async def test_setup_creates_hub_entry_and_location_entities(
    hass: HomeAssistant, mock_api
) -> None:
    mock_api.alerts = alert_bundle(mds=[make_md(2104)])
    entry = fixed_entry()
    await setup_entry(hass, entry)

    hubs = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.data.get("entry_type") == ENTRY_TYPE_HUB
    ]
    assert len(hubs) == 1
    assert hubs[0].state is ConfigEntryState.LOADED

    day1 = hass.states.get("sensor.spc_home_day_1_risk")
    assert day1.state == "SLGT"
    assert day1.attributes["level"] == 3
    assert day1.attributes["label"] == "Slight Risk"
    assert day1.attributes["forecaster"] == "Smith"
    assert day1.attributes["issued"] == "2026-10-13T12:52:00+00:00"
    assert day1.attributes["data_age"] is not None
    assert hass.states.get("sensor.spc_home_day_2_risk").state == "MRGL"
    assert hass.states.get("sensor.spc_home_day_3_risk").state == "none"

    peak = hass.states.get("sensor.spc_home_max_risk_next_3_days")
    assert (peak.state, peak.attributes["day"]) == ("SLGT", 1)

    torn = hass.states.get("sensor.spc_home_day_1_tornado_probability")
    assert torn.state == "5"
    assert torn.attributes["significant"] is True
    assert torn.attributes["unit_of_measurement"] == "%"
    wind = hass.states.get("sensor.spc_home_day_1_wind_probability")
    assert (wind.state, wind.attributes["significant"]) == ("15", False)
    assert hass.states.get("sensor.spc_home_day_3_severe_probability").state == "5"
    assert hass.states.get("sensor.spc_home_day_4_severe_probability").state == "15"
    day5 = hass.states.get("sensor.spc_home_day_5_severe_probability")
    assert (day5.state, day5.attributes["predictability_too_low"]) == ("0", True)
    # Layers absent from the bundle are unavailable, not zero.
    assert (
        hass.states.get("sensor.spc_home_day_2_tornado_probability").state
        == STATE_UNAVAILABLE
    )

    md = hass.states.get("binary_sensor.spc_home_mesoscale_discussion")
    assert md.state == "on"
    assert md.attributes["number"] == 2104
    assert md.attributes["concerning"] == "Severe potential...Watch likely"
    assert len(md.attributes["items"]) == 1
    assert hass.states.get("binary_sensor.spc_home_tornado_watch") is None


async def test_empty_layer_with_stale_metadata_is_none_and_available(
    hass: HomeAssistant, mock_api
) -> None:
    layers = risk_layers()
    layers["day1_cat"] = collection()
    mock_api.outlooks = outlook_bundle(layers)
    await setup_entry(hass, fixed_entry())
    state = hass.states.get("sensor.spc_home_day_1_risk")
    assert state.state == "none"


async def test_outlook_entities_go_unavailable_when_stale(
    hass: HomeAssistant, mock_api, freezer
) -> None:
    await setup_entry(hass, fixed_entry())
    assert hass.states.get("sensor.spc_home_day_1_risk").state == "SLGT"

    freezer.tick(timedelta(minutes=16))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get("sensor.spc_home_day_1_risk").state == "SLGT"
    assert (
        hass.states.get("binary_sensor.spc_home_mesoscale_discussion").state
        == STATE_UNAVAILABLE
    )

    freezer.tick(timedelta(hours=3))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get("sensor.spc_home_day_1_risk").state == STATE_UNAVAILABLE


async def test_disabled_groups_create_no_entities(
    hass: HomeAssistant, mock_api
) -> None:
    await setup_entry(hass, fixed_entry(options={CONF_GROUPS: [GROUP_CATEGORICAL]}))
    assert hass.states.get("sensor.spc_home_day_1_risk") is not None
    assert hass.states.get("sensor.spc_home_day_1_tornado_probability") is None
    assert hass.states.get("binary_sensor.spc_home_mesoscale_discussion") is None


async def test_unloading_all_entries_stops_hub(hass: HomeAssistant, mock_api) -> None:
    entry = fixed_entry()
    await setup_entry(hass, entry)
    assert get_hub(hass) is not None
    for config_entry in hass.config_entries.async_entries(DOMAIN):
        assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert get_hub(hass) is None


async def test_entities_belong_to_location_device(
    hass: HomeAssistant, mock_api
) -> None:
    entry = fixed_entry()
    await setup_entry(hass, entry)
    registry = er.async_get(hass)
    reg_entry = registry.async_get("sensor.spc_home_day_1_risk")
    assert reg_entry.unique_id == f"{entry.entry_id}_day1_risk"
