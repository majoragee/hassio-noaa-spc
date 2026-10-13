import pytest

from custom_components.noaa_spc.api.geometry import point_in_polygon
from custom_components.noaa_spc.api.mds import (
    MdParseError,
    decode_latlon,
    parse_md_feed,
    parse_md_page,
)

MD_HTML = """<html><body><pre>

   Mesoscale Discussion 2104
   NWS Storm Prediction Center Norman OK
   0431 PM CDT Sun Aug 23 2026

   Areas affected...portions of central and eastern Montana

   Concerning...Severe potential...Watch likely 

   Valid 232131Z - 232230Z

   Probability of Watch Issuance...80 percent

   SUMMARY...Widely scattered thunderstorms (including some supercells)
   will continue eastward. A downstream Watch is likely needed.

   DISCUSSION...As of 2130 UTC, widely scattered thunderstorms were
   ongoing across central MT.

   ..Lyons/Thompson.. 08/23/2026

   LAT...LON   49050884 49250603 49060504 48710487 48380473 47470496
               46050568 45270625 44940708 44760872 44920911 45330913
               46040889 48020883 49050884 

   MOST PROBABLE PEAK WIND GUST...65-80 MPH

</pre></body></html>"""

URL = "https://www.spc.noaa.gov/products/md/md2104.html"


def _feed(*links: str) -> str:
    items = "".join(
        f"<item><link>{link}</link><title>SPC MD</title></item>" for link in links
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'


def test_decode_latlon_adds_100_to_western_longitudes() -> None:
    assert decode_latlon("49050884") == (-108.84, 49.05)
    assert decode_latlon("35229744") == (-97.44, 35.22)
    assert decode_latlon("30008000") == (-80.0, 30.0)


def test_parse_md_page() -> None:
    md = parse_md_page(MD_HTML, URL)
    assert md.number == 2104
    assert md.areas_affected == "portions of central and eastern Montana"
    assert md.concerning == "Severe potential...Watch likely"
    assert md.watch_probability == 80
    assert md.summary == (
        "Widely scattered thunderstorms (including some supercells) "
        "will continue eastward. A downstream Watch is likely needed."
    )
    assert md.url == URL
    assert len(md.polygon[0]) == 15
    assert point_in_polygon(-107.0, 47.0, md.polygon)
    assert not point_in_polygon(-97.44, 35.22, md.polygon)


def test_parse_md_page_without_watch_probability() -> None:
    raw = MD_HTML.replace("   Probability of Watch Issuance...80 percent\n", "")
    assert parse_md_page(raw, URL).watch_probability is None


def test_parse_md_page_without_polygon_rejected() -> None:
    raw = MD_HTML.split("LAT...LON")[0] + "</pre>"
    with pytest.raises(MdParseError):
        parse_md_page(raw, URL)


def test_feed_accepts_both_link_styles_and_dedupes() -> None:
    feed = _feed(
        "https://www.spc.noaa.gov/products/md/md2104.html",
        "https://www.spc.noaa.gov/products/md/2026/md2105.html",
        "https://www.spc.noaa.gov/products/md/md2104.html",
    )
    assert parse_md_feed(feed) == [
        (2104, "https://www.spc.noaa.gov/products/md/md2104.html"),
        (2105, "https://www.spc.noaa.gov/products/md/2026/md2105.html"),
    ]


def test_feed_with_no_mds() -> None:
    feed = _feed("https://www.spc.noaa.gov/products/md/")
    assert parse_md_feed(feed) == []


def test_feed_malformed_xml_rejected() -> None:
    with pytest.raises(MdParseError):
        parse_md_feed(b"<rss><channel>")
