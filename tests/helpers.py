"""GeoJSON builders for tests."""

from __future__ import annotations

from typing import Any

ISSUE = "2026-10-13T12:52:00+00:00"
VALID = "2026-10-13T13:00:00+00:00"
EXPIRE = "2099-01-01T12:00:00+00:00"
HOME = (35.22, -97.44)  # Norman, OK
FAR = (44.0, -110.0)  # Wyoming, outside every test area


def square(lat: float, lon: float, half: float = 1.0) -> list[list[float]]:
    return [
        [lon - half, lat - half],
        [lon + half, lat - half],
        [lon + half, lat + half],
        [lon - half, lat + half],
        [lon - half, lat - half],
    ]


def feature(
    label: str, *rings: list[list[float]], dn: int = 1, forecaster: str = "Smith"
) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": {"type": "MultiPolygon", "coordinates": [[r] for r in rings]},
        "properties": {
            "DN": dn,
            "LABEL": label,
            "LABEL2": "",
            "ISSUE_ISO": ISSUE,
            "VALID_ISO": VALID,
            "EXPIRE_ISO": EXPIRE,
            "FORECASTER": forecaster,
        },
    }


def empty_feature(label: str = "") -> dict[str, Any]:
    """An SPC 'no areas' feature: DN 0, empty geometry, stale timestamps."""
    return {
        "type": "Feature",
        "geometry": {"type": "GeometryCollection", "geometries": []},
        "properties": {
            "DN": 0,
            "LABEL": label,
            "LABEL2": "",
            "ISSUE_ISO": "2026-03-03T12:48:00+00:00",
            "VALID_ISO": "2026-03-03T13:00:00+00:00",
            "EXPIRE_ISO": "2026-03-04T12:00:00+00:00",
            "FORECASTER": "Old",
        },
    }


def collection(*features: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": list(features) or [empty_feature()],
    }
