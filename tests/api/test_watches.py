import pytest

from custom_components.noaa_spc.api.watches import WatchParseError, parse_watch_feed

PLACEHOLDER = (
    "<item><link>https://www.spc.noaa.gov/products/watch/</link>"
    "<title>SPC - No watches are valid as of Sun Oct 11 22:31:02 UTC 2026</title>"
    "<description>No watches are valid as of Sun Oct 11 22:31:02 UTC 2026.</description>"
    "</item>"
)


def _item(link: str, title: str, description: str = "") -> str:
    return (
        f"<item><link>{link}</link><title>{title}</title>"
        f"<description>{description}</description></item>"
    )


def _feed(*items: str) -> str:
    return (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        + "".join(items)
        + "</channel></rss>"
    )


def test_placeholder_feed_has_no_watches() -> None:
    assert parse_watch_feed(_feed(PLACEHOLDER)) == ()


def test_watches_parsed_sorted_with_type() -> None:
    feed = _feed(
        _item(
            "https://www.spc.noaa.gov/products/watch/ww0613.html",
            "SPC Severe Thunderstorm Watch 613",
        ),
        _item(
            "https://www.spc.noaa.gov/products/watch/ww0612.html",
            "SPC Tornado Watch 612",
        ),
    )
    watches = parse_watch_feed(feed)
    assert [(w.number, w.kind, w.pds) for w in watches] == [
        (612, "tornado", False),
        (613, "severe_thunderstorm", False),
    ]
    assert watches[0].url == "https://www.spc.noaa.gov/products/watch/ww0612.html"


def test_duplicate_and_status_items_merge_into_one_watch() -> None:
    feed = _feed(
        _item(
            "https://www.spc.noaa.gov/products/watch/ww0612.html",
            "SPC Tornado Watch 612",
        ),
        _item(
            "https://www.spc.noaa.gov/products/watch/2026/ww0612_status.html",
            "SPC Watch 612 Status Report",
        ),
        _item(
            "https://www.spc.noaa.gov/products/watch/ww0612.html",
            "SPC Tornado Watch 612",
        ),
    )
    (watch,) = parse_watch_feed(feed)
    assert watch.number == 612
    assert watch.kind == "tornado"
    assert watch.url == "https://www.spc.noaa.gov/products/watch/ww0612.html"


@pytest.mark.parametrize(
    ("title", "description"),
    [
        ("SPC PDS Tornado Watch 612", ""),
        ("SPC Tornado Watch 612", "THIS IS A PARTICULARLY DANGEROUS SITUATION"),
    ],
)
def test_pds_detected(title: str, description: str) -> None:
    feed = _feed(
        _item("https://www.spc.noaa.gov/products/watch/ww0612.html", title, description)
    )
    assert parse_watch_feed(feed)[0].pds is True


def test_malformed_feed_rejected() -> None:
    with pytest.raises(WatchParseError):
        parse_watch_feed(b"<rss><channel>")


def test_svr_watch_mentioning_tornado_stays_severe_thunderstorm() -> None:
    feed = _feed(
        _item(
            "https://www.spc.noaa.gov/products/watch/ww0613.html",
            "SPC Severe Thunderstorm Watch 613",
            "A tornado or two are possible in the watch area.",
        )
    )
    assert parse_watch_feed(feed)[0].kind == "severe_thunderstorm"


def test_ordinary_text_is_not_pds() -> None:
    feed = _feed(
        _item(
            "https://www.spc.noaa.gov/products/watch/ww0612.html",
            "SPC Tornado Watch 612",
            "Scattered severe storms with large hail are possible.",
        )
    )
    assert parse_watch_feed(feed)[0].pds is False


def test_placeholder_mixed_with_active_watch_yields_only_watch() -> None:
    feed = _feed(
        PLACEHOLDER,
        _item(
            "https://www.spc.noaa.gov/products/watch/ww0612.html",
            "SPC Tornado Watch 612",
        ),
    )
    watches = parse_watch_feed(feed)
    assert [(w.number, w.kind) for w in watches] == [(612, "tornado")]
