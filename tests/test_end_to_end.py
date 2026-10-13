from pathlib import Path

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant

from custom_components.noaa_spc.api.products import (
    IMAGE_PATHS,
    LAYER_PATHS,
    MD_FEED_PATH,
    SPC_BASE,
    TEXT_PATHS,
    WATCH_FEED_PATH,
)
from custom_components.noaa_spc.api.watches import parse_watch_feed
from tests.factories import fixed_entry, setup_entry

LIVE = Path(__file__).parent / "fixtures" / "live"
MD_URL = "https://www.spc.noaa.gov/products/md/md2104.html"
POINT = (47.0, -107.0)  # inside MD 2104


async def test_full_setup_against_live_payloads(
    hass: HomeAssistant, aioclient_mock
) -> None:
    for path in LAYER_PATHS.values():
        name = path.rsplit("/", 1)[-1]
        aioclient_mock.get(SPC_BASE + path, text=(LIVE / "layers" / name).read_text())
    text_files = {
        "day1": "day1otlk.txt",
        "day2": "day2otlk.txt",
        "day3": "day3otlk.txt",
        "day48": "day48.html",
    }
    for key, path in TEXT_PATHS.items():
        aioclient_mock.get(
            SPC_BASE + path, text=(LIVE / "text" / text_files[key]).read_text()
        )
    for key, (path, _) in IMAGE_PATHS.items():
        aioclient_mock.get(SPC_BASE + path, content=b"IMG" + key.encode())

    watch_feed = (LIVE / "spcwwrss.xml").read_text()
    aioclient_mock.get(SPC_BASE + WATCH_FEED_PATH, text=watch_feed)
    aioclient_mock.get(
        SPC_BASE + MD_FEED_PATH,
        text=f'<rss version="2.0"><channel><item><link>{MD_URL}</link></item></channel></rss>',
    )
    aioclient_mock.get(MD_URL, text=(LIVE / "md2104.html").read_text())

    await setup_entry(hass, fixed_entry(*POINT, title="Home"))

    for entity_id in (
        "sensor.spc_home_day_1_risk",
        "sensor.spc_home_day_2_risk",
        "sensor.spc_home_day_3_risk",
        "sensor.spc_home_max_risk_next_3_days",
        "sensor.spc_home_day_1_tornado_probability",
        "sensor.spc_home_day_3_severe_probability",
        "sensor.spc_home_day_8_severe_probability",
        "sensor.noaa_spc_day_1_discussion",
        "sensor.noaa_spc_day_4_8_discussion",
        "image.noaa_spc_day_1_outlook",
    ):
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        assert state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN), entity_id

    assert hass.states.get("binary_sensor.spc_home_mesoscale_discussion").state == "on"
    expected_watches = len(parse_watch_feed(watch_feed))
    assert hass.states.get("sensor.noaa_spc_active_watches").state == str(
        expected_watches
    )
    assert not any(
        "watch" in state.entity_id for state in hass.states.async_all("binary_sensor")
    )
