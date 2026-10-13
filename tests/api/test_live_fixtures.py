import json
from pathlib import Path

import pytest

from custom_components.noaa_spc.api.geometry import point_in_polygon
from custom_components.noaa_spc.api.mds import parse_md_page
from custom_components.noaa_spc.api.models import RiskLevel
from custom_components.noaa_spc.api.outlooks import categorical_at, parse_layer
from custom_components.noaa_spc.api.text import parse_text_product
from custom_components.noaa_spc.api.watches import parse_watch_feed

LIVE = Path(__file__).parent.parent / "fixtures" / "live"


@pytest.mark.parametrize("path", sorted((LIVE / "layers").glob("*.geojson")), ids=str)
def test_every_live_layer_parses(path: Path) -> None:
    layer = parse_layer(json.loads(path.read_text()))
    assert layer.issued is not None
    categorical_at(layer, 35.22, -97.44)


def test_live_layer_count() -> None:
    assert len(list((LIVE / "layers").glob("*.geojson"))) == 22


@pytest.mark.parametrize(
    "name", ["day1otlk.txt", "day2otlk.txt", "day3otlk.txt", "day48.html"]
)
def test_live_text_has_summary_and_forecaster(name: str) -> None:
    product = parse_text_product((LIVE / "text" / name).read_text())
    assert product.summary
    assert product.forecaster


def test_live_md() -> None:
    md = parse_md_page(
        (LIVE / "md2104.html").read_text(), "https://example/md2104.html"
    )
    assert md.number == 2104
    assert md.watch_probability == 80
    assert point_in_polygon(-107.0, 47.0, md.polygon)


def test_live_watch_feed() -> None:
    raw = (LIVE / "spcwwrss.xml").read_bytes()
    watches = parse_watch_feed(raw)
    if b"No watches are valid" in raw:
        assert watches == ()
    else:
        assert watches
        assert all(w.number > 0 and w.url.endswith(".html") for w in watches)


def test_risk_level_labels_in_live_categorical_layers_are_known() -> None:
    for path in (LIVE / "layers").glob("day*otlk_cat.lyr.geojson"):
        for area in parse_layer(json.loads(path.read_text())).areas:
            assert RiskLevel.from_label(area.label) is not None, area.label
