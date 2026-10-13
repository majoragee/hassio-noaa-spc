from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_IMPORT, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.noaa_spc.const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_HUB
from tests.factories import fixed_entry, tracked_entry


@pytest.fixture(autouse=True)
def skip_setup():
    with (
        patch(
            "custom_components.noaa_spc.async_setup",
            new=AsyncMock(return_value=True),
            create=True,
        ),
        patch(
            "custom_components.noaa_spc.async_setup_entry",
            new=AsyncMock(return_value=True),
            create=True,
        ),
    ):
        yield


async def _menu(hass: HomeAssistant, choice: str) -> dict:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["fixed", "tracked"]
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": choice}
    )


async def test_fixed_location(hass: HomeAssistant) -> None:
    result = await _menu(hass, "fixed")
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Home", "location": {"latitude": 35.22, "longitude": -97.44}},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Home"
    assert result["data"] == {
        "entry_type": "location",
        "mode": "fixed",
        "latitude": 35.22,
        "longitude": -97.44,
    }
    assert result["result"].unique_id == "fixed_35.220_-97.440"


async def test_fixed_duplicate_aborts(hass: HomeAssistant) -> None:
    fixed_entry(35.2201, -97.4399).add_to_hass(hass)
    result = await _menu(hass, "fixed")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Again", "location": {"latitude": 35.22, "longitude": -97.44}},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_fixed_outside_conus_warns_then_creates(hass: HomeAssistant) -> None:
    result = await _menu(hass, "fixed")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "London", "location": {"latitude": 51.5, "longitude": -0.12}},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "outside"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["latitude"] == 51.5


async def test_tracked_location_and_duplicate(hass: HomeAssistant) -> None:
    hass.states.async_set("person.alex", "home", {"latitude": 35.2, "longitude": -97.4})
    result = await _menu(hass, "tracked")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Alex", "tracked_entity": "person.alex"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        "entry_type": "location",
        "mode": "tracked",
        "tracked_entity": "person.alex",
    }

    tracked_entry("device_tracker.phone").add_to_hass(hass)
    hass.states.async_set("device_tracker.phone", "home")
    result = await _menu(hass, "tracked")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Phone", "tracked_entity": "device_tracker.phone"}
    )
    assert result["type"] is FlowResultType.ABORT


async def test_import_creates_single_hub(hass: HomeAssistant) -> None:
    data = {CONF_ENTRY_TYPE: ENTRY_TYPE_HUB}
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=data
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "NOAA SPC"
    assert result["data"] == data
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=data
    )
    assert result["type"] is FlowResultType.ABORT
