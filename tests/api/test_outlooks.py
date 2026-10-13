from datetime import UTC, datetime

import pytest

from custom_components.noaa_spc.api.models import RiskLevel
from custom_components.noaa_spc.api.outlooks import (
    OutlookParseError,
    any_area_at,
    categorical_at,
    parse_layer,
    parse_percent,
    probability_at,
)
from custom_components.noaa_spc.api.products import (
    IMAGE_PATHS,
    LAYER_PATHS,
    TEXT_PATHS,
    in_conus,
)
from tests.helpers import FAR, HOME, collection, empty_feature, feature, square


def test_parse_layer_metadata_and_areas() -> None:
    layer = parse_layer(collection(feature("SLGT", square(*HOME), forecaster="Mosier")))
    assert layer.issued == datetime(2026, 10, 13, 12, 52, tzinfo=UTC)
    assert layer.valid == datetime(2026, 10, 13, 13, 0, tzinfo=UTC)
    assert layer.expire == datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
    assert layer.forecaster == "Mosier"
    assert [a.label for a in layer.areas] == ["SLGT"]
    assert layer.predictability_too_low is False


def test_nested_categorical_returns_highest_containing_level() -> None:
    layer = parse_layer(
        collection(
            feature("TSTM", square(*HOME, half=5.0)),
            feature("MRGL", square(*HOME, half=3.0)),
            feature("ENH", square(*HOME, half=1.0)),
        )
    )
    assert categorical_at(layer, *HOME) is RiskLevel.ENH
    assert categorical_at(layer, HOME[0] + 2.0, HOME[1]) is RiskLevel.MRGL
    assert categorical_at(layer, *FAR) is RiskLevel.NONE


def test_empty_layer_is_no_risk_not_error() -> None:
    layer = parse_layer(collection(empty_feature()))
    assert layer.areas == ()
    assert categorical_at(layer, *HOME) is RiskLevel.NONE
    assert probability_at(layer, *HOME) == 0


def test_predictability_too_low_flag() -> None:
    layer = parse_layer(collection(empty_feature("Predictability Too Low")))
    assert layer.predictability_too_low is True
    assert layer.areas == ()


def test_polygon_geometry_type_supported() -> None:
    data = collection(feature("SLGT", square(*HOME)))
    data["features"][0]["geometry"] = {
        "type": "Polygon",
        "coordinates": [square(*HOME)],
    }
    assert categorical_at(parse_layer(data), *HOME) is RiskLevel.SLGT


def test_probability_takes_max_and_ignores_sign_labels() -> None:
    layer = parse_layer(
        collection(
            feature("0.02", square(*HOME, half=4.0)),
            feature("0.10", square(*HOME, half=1.0)),
            feature("SIGN", square(*HOME, half=1.0)),
        )
    )
    assert probability_at(layer, *HOME) == 10
    assert probability_at(layer, HOME[0] + 3.0, HOME[1]) == 2


def test_any_area_at_for_significant_layers() -> None:
    layer = parse_layer(collection(feature("SIGN", square(*HOME))))
    assert any_area_at(layer, *HOME)
    assert not any_area_at(layer, *FAR)


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("0.05", 5),
        ("0.15", 15),
        ("0.30", 30),
        ("SIGN", None),
        ("", None),
        ("1.5", None),
    ],
)
def test_parse_percent(label: str, expected: int | None) -> None:
    assert parse_percent(label) == expected


@pytest.mark.parametrize(
    "data",
    [None, [], {"type": "Feature"}, {"type": "FeatureCollection", "features": "x"}],
)
def test_parse_layer_rejects_malformed(data: object) -> None:
    with pytest.raises(OutlookParseError):
        parse_layer(data)


def test_parse_layer_rejects_bad_coordinates() -> None:
    data = collection(feature("SLGT", square(*HOME)))
    data["features"][0]["geometry"]["coordinates"] = [[["x"]]]
    with pytest.raises(OutlookParseError):
        parse_layer(data)


def test_product_catalog() -> None:
    assert LAYER_PATHS["day1_cat"] == "outlook/day1otlk_cat.lyr.geojson"
    assert LAYER_PATHS["day2_sighail"] == "outlook/day2otlk_sighail.lyr.geojson"
    assert LAYER_PATHS["day3_sigprob"] == "outlook/day3otlk_sigprob.lyr.geojson"
    assert LAYER_PATHS["day8_prob"] == "exper/day4-8/day8prob.lyr.geojson"
    assert len(LAYER_PATHS) == 22
    assert set(TEXT_PATHS) == {"day1", "day2", "day3", "day48"}
    assert IMAGE_PATHS["day1_torn"] == ("outlook/day1probotlk_torn.png", "image/png")
    assert IMAGE_PATHS["day48"] == ("exper/day4-8/day48prob.gif", "image/gif")
    assert len(IMAGE_PATHS) == 10


def test_in_conus() -> None:
    assert in_conus(*HOME)
    assert not in_conus(51.5, -0.12)
    assert not in_conus(61.2, -149.9)  # Anchorage
