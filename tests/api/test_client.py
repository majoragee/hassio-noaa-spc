import aiohttp
import pytest
from aioresponses import aioresponses
from yarl import URL

from custom_components.noaa_spc.api.client import SpcApiError, SpcClient
from custom_components.noaa_spc.api.products import USER_AGENT

URL_A = "https://www.spc.noaa.gov/products/outlook/day1otlk_cat.lyr.geojson"


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as session:
        yield session


def _sent_headers(mock: aioresponses, url: str, index: int) -> dict:
    return mock.requests[("GET", URL(url))][index].kwargs["headers"]


async def test_first_fetch_then_304_returns_cached_body(session) -> None:
    client = SpcClient(session)
    with aioresponses() as mock:
        mock.get(
            URL_A,
            status=200,
            body=b"one",
            headers={
                "ETag": '"abc"',
                "Last-Modified": "Tue, 13 Oct 2026 12:56:15 GMT",
            },
        )
        mock.get(URL_A, status=304)
        first = await client.fetch(URL_A)
        second = await client.fetch(URL_A)
        assert _sent_headers(mock, URL_A, 0)["User-Agent"] == USER_AGENT
        assert "If-None-Match" not in _sent_headers(mock, URL_A, 0)
        assert _sent_headers(mock, URL_A, 1)["If-None-Match"] == '"abc"'
        assert _sent_headers(mock, URL_A, 1)["If-Modified-Since"] == (
            "Tue, 13 Oct 2026 12:56:15 GMT"
        )
    assert (first.body, first.changed) == (b"one", True)
    assert (second.body, second.changed) == (b"one", False)


async def test_200_with_identical_body_is_unchanged(session) -> None:
    client = SpcClient(session)
    with aioresponses() as mock:
        mock.get(URL_A, status=200, body=b"same", headers={"ETag": '"1"'})
        mock.get(URL_A, status=200, body=b"same", headers={"ETag": '"2"'})
        await client.fetch(URL_A)
        again = await client.fetch(URL_A)
    assert again.changed is False


async def test_non_conditional_fetch_sends_no_validators(session) -> None:
    client = SpcClient(session)
    with aioresponses() as mock:
        mock.get(URL_A, status=200, body=b"x", headers={"ETag": '"1"'}, repeat=True)
        await client.fetch(URL_A, conditional=False, accept="application/geo+json")
        await client.fetch(URL_A, conditional=False)
        headers = _sent_headers(mock, URL_A, 1)
        assert "If-None-Match" not in headers
        assert _sent_headers(mock, URL_A, 0)["Accept"] == "application/geo+json"


async def test_http_error_raises_with_status(session) -> None:
    client = SpcClient(session)
    with aioresponses() as mock:
        mock.get(URL_A, status=404)
        with pytest.raises(SpcApiError) as err:
            await client.fetch(URL_A)
    assert err.value.status == 404


@pytest.mark.parametrize("exc", [aiohttp.ClientConnectionError(), TimeoutError()])
async def test_network_errors_wrapped(session, exc: Exception) -> None:
    client = SpcClient(session)
    with aioresponses() as mock:
        mock.get(URL_A, exception=exc)
        with pytest.raises(SpcApiError) as err:
            await client.fetch(URL_A)
    assert err.value.status is None
