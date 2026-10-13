from http import HTTPStatus

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.noaa_spc.api.models import TextProduct
from tests.factories import (
    alert_bundle,
    fixed_entry,
    make_md,
    make_watch,
    outlook_bundle,
    risk_layers,
    setup_entry,
)

TEXT = TextProduct(text="Full discussion", summary="Storms today.", forecaster="Smith")


async def test_hub_sensors(hass: HomeAssistant, mock_api) -> None:
    mock_api.outlooks = outlook_bundle(
        risk_layers(), texts={"day1": TEXT, "day48": TEXT}
    )
    mock_api.alerts = alert_bundle(
        [make_watch(612, pds=True), make_watch(613, "severe_thunderstorm")],
        [make_md(2104)],
    )
    await setup_entry(hass, fixed_entry())

    day1 = hass.states.get("sensor.noaa_spc_day_1_discussion")
    assert day1.state == "2026-10-13T12:52:00+00:00"
    assert day1.attributes["summary"] == "Storms today."
    assert day1.attributes["text"] == "Full discussion"
    assert day1.attributes["forecaster"] == "Smith"
    assert day1.attributes["valid"] == "2026-10-13T13:00:00+00:00"
    day48 = hass.states.get("sensor.noaa_spc_day_4_8_discussion")
    assert day48.state != "unavailable"
    assert day48.attributes["summary"] == "Storms today."
    assert "data_age" not in day1.attributes
    # day2 text was never fetched -> unavailable
    assert hass.states.get("sensor.noaa_spc_day_2_discussion").state == "unavailable"

    watches = hass.states.get("sensor.noaa_spc_active_watches")
    assert watches.state == "2"
    assert [i["number"] for i in watches.attributes["items"]] == [612, 613]
    assert watches.attributes["tornado"] == 1
    assert watches.attributes["severe_thunderstorm"] == 1
    assert watches.attributes["pds"] == 1
    assert hass.states.get("sensor.noaa_spc_active_mesoscale_discussions").state == "1"


async def test_outlook_images(hass: HomeAssistant, mock_api, hass_client) -> None:
    mock_api.outlooks = outlook_bundle(
        risk_layers(), images={"day1": b"\x89PNGday1", "day48": b"GIF89a"}
    )
    await setup_entry(hass, fixed_entry())

    state = hass.states.get("image.noaa_spc_day_1_outlook")
    assert state is not None and state.state != "unavailable"
    client = await hass_client()
    resp = await client.get("/api/image_proxy/image.noaa_spc_day_1_outlook")
    assert resp.status == HTTPStatus.OK
    assert await resp.read() == b"\x89PNGday1"
    assert resp.content_type == "image/png"

    resp = await client.get("/api/image_proxy/image.noaa_spc_day_4_8_outlook")
    assert resp.content_type == "image/gif"

    registry = er.async_get(hass)
    hazard = registry.async_get("image.noaa_spc_day_1_tornado_outlook")
    assert hazard is not None
    assert hazard.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get("image.noaa_spc_day_2_outlook").state == "unavailable"


async def test_discussion_of_expired_layer_has_no_issue_time(
    hass: HomeAssistant, mock_api
) -> None:
    # risk_layers() day3_cat is an expired "no areas" file.
    mock_api.outlooks = outlook_bundle(
        risk_layers(), texts={"day1": TEXT, "day3": TEXT}
    )
    await setup_entry(hass, fixed_entry())

    day3 = hass.states.get("sensor.noaa_spc_day_3_discussion")
    assert day3.state == "unknown"
    assert day3.attributes["valid"] is None
    assert day3.attributes["summary"] == "Storms today."
    assert hass.states.get("sensor.noaa_spc_day_1_discussion").state != "unknown"
