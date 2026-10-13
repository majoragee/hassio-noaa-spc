import json
import logging

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.noaa_spc.api.client import SpcClient
from custom_components.noaa_spc.api.models import RiskLevel
from custom_components.noaa_spc.api.outlooks import categorical_at
from custom_components.noaa_spc.api.products import (
    IMAGE_PATHS,
    LAYER_PATHS,
    MD_FEED_PATH,
    SPC_BASE,
    TEXT_PATHS,
    WATCH_FEED_PATH,
)
from custom_components.noaa_spc.api.spc import SpcApi
from tests.api.test_mds import MD_HTML
from tests.helpers import HOME, collection, feature, square

DAY1_TEXT = "SPC AC 131252\n\n...SUMMARY...\nStorms.\n\n..Smith.. 10/13/2026\n"
MD_URL = "https://www.spc.noaa.gov/products/md/md2104.html"
MD_FEED = (
    '<?xml version="1.0"?><rss version="2.0"><channel>'
    f"<item><link>{MD_URL}</link></item></channel></rss>"
)
WATCH_FEED = (
    '<?xml version="1.0"?><rss version="2.0"><channel><item>'
    "<link>https://www.spc.noaa.gov/products/watch/ww0612.html</link>"
    "<title>SPC Tornado Watch 612</title></item></channel></rss>"
)


@pytest.fixture
async def api():
    async with aiohttp.ClientSession() as session:
        yield SpcApi(SpcClient(session))


def _register_outlooks(
    mock: aioresponses, overrides: dict[str, dict] | None = None
) -> None:
    overrides = overrides or {}
    for key, path in LAYER_PATHS.items():
        if key in overrides:
            mock.get(SPC_BASE + path, **overrides[key])
        else:
            mock.get(SPC_BASE + path, body=json.dumps(collection()), repeat=True)
    for key, path in TEXT_PATHS.items():
        if key not in overrides:
            mock.get(SPC_BASE + path, body=DAY1_TEXT, repeat=True)
    for key, (path, _) in IMAGE_PATHS.items():
        if key not in overrides:
            mock.get(SPC_BASE + path, body=b"PNG" + key.encode(), repeat=True)


async def test_fetch_outlooks_all_products(api: SpcApi) -> None:
    slight = {
        "body": json.dumps(collection(feature("SLGT", square(*HOME)))),
        "repeat": True,
    }
    with aioresponses() as mock:
        _register_outlooks(mock, {"day1_cat": slight})
        bundle = await api.fetch_outlooks(None)
    assert set(bundle.layers) == set(LAYER_PATHS)
    assert categorical_at(bundle.layers["day1_cat"], *HOME) is RiskLevel.SLGT
    assert bundle.texts["day1"].summary == "Storms."
    assert bundle.images["day1"] == b"PNGday1"
    assert len(bundle.updated) == len(LAYER_PATHS) + len(TEXT_PATHS) + len(IMAGE_PATHS)


async def test_failed_product_keeps_previous_value_and_timestamp(api: SpcApi) -> None:
    slight = {"body": json.dumps(collection(feature("SLGT", square(*HOME))))}
    with aioresponses() as mock:
        _register_outlooks(mock, {"day1_cat": slight})
        first = await api.fetch_outlooks(None)
    with aioresponses() as mock:
        _register_outlooks(mock, {"day1_cat": {"status": 500}})
        second = await api.fetch_outlooks(first)
    assert categorical_at(second.layers["day1_cat"], *HOME) is RiskLevel.SLGT
    assert second.updated["layer:day1_cat"] == first.updated["layer:day1_cat"]
    assert second.updated["layer:day2_cat"] >= first.updated["layer:day2_cat"]


async def test_malformed_product_logged_once(api: SpcApi, caplog) -> None:
    bad = {"body": "not json", "repeat": True}
    caplog.set_level(logging.WARNING)
    with aioresponses() as mock:
        _register_outlooks(mock, {"day1_cat": bad})
        bundle = await api.fetch_outlooks(None)
        await api.fetch_outlooks(bundle)
    assert "day1_cat" not in bundle.layers
    assert caplog.text.count("layer:day1_cat") == 1


async def test_fetch_alerts_parses_and_caches_md_pages(api: SpcApi) -> None:
    with aioresponses() as mock:
        mock.get(SPC_BASE + WATCH_FEED_PATH, body=WATCH_FEED, repeat=True)
        mock.get(SPC_BASE + MD_FEED_PATH, body=MD_FEED, repeat=True)
        mock.get(MD_URL, body=MD_HTML)  # registered once: a second fetch would fail
        first = await api.fetch_alerts(None)
        second = await api.fetch_alerts(first)
    assert [w.number for w in second.watches] == [612]
    assert [m.number for m in second.mds] == [2104]
    assert second.watches_updated is not None and second.mds_updated is not None


async def test_fetch_alerts_failure_keeps_previous(api: SpcApi) -> None:
    with aioresponses() as mock:
        mock.get(SPC_BASE + WATCH_FEED_PATH, body=WATCH_FEED)
        mock.get(SPC_BASE + MD_FEED_PATH, body=MD_FEED)
        mock.get(MD_URL, body=MD_HTML)
        first = await api.fetch_alerts(None)
    with aioresponses() as mock:
        mock.get(SPC_BASE + WATCH_FEED_PATH, status=503)
        mock.get(SPC_BASE + MD_FEED_PATH, status=503)
        second = await api.fetch_alerts(first)
    assert second.watches == first.watches
    assert second.mds == first.mds
    assert second.watches_updated == first.watches_updated


async def test_watch_feed_failure_does_not_block_mds(api: SpcApi) -> None:
    with aioresponses() as mock:
        mock.get(SPC_BASE + WATCH_FEED_PATH, status=503)
        mock.get(SPC_BASE + MD_FEED_PATH, body=MD_FEED)
        mock.get(MD_URL, body=MD_HTML)
        bundle = await api.fetch_alerts(None)
    assert bundle.watches == ()
    assert bundle.watches_updated is None
    assert [m.number for m in bundle.mds] == [2104]
    assert bundle.mds_updated is not None
