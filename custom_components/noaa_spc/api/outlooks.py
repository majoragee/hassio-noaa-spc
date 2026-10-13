"""SPC outlook GeoJSON parsing and point lookups. Must not import Home Assistant."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .geometry import point_in_any
from .models import OutlookArea, OutlookLayer, Polygon, RiskLevel

PREDICTABILITY_TOO_LOW = "predictability too low"


class OutlookParseError(ValueError):
    """Raised when an outlook layer is not valid SPC GeoJSON."""


def _parse_dt(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _polygon(rings: Any) -> Polygon:
    return tuple(
        tuple((float(point[0]), float(point[1])) for point in ring) for ring in rings
    )


def _polygons(geometry: Any) -> tuple[Polygon, ...]:
    if not isinstance(geometry, dict):
        return ()
    kind = geometry.get("type")
    if kind == "Polygon":
        return (_polygon(geometry["coordinates"]),)
    if kind == "MultiPolygon":
        return tuple(_polygon(rings) for rings in geometry["coordinates"])
    if kind == "GeometryCollection":
        return tuple(
            polygon
            for child in geometry.get("geometries", [])
            for polygon in _polygons(child)
        )
    return ()


def parse_layer(data: Any) -> OutlookLayer:
    if (
        not isinstance(data, dict)
        or data.get("type") != "FeatureCollection"
        or not isinstance(data.get("features"), list)
    ):
        raise OutlookParseError("not a GeoJSON FeatureCollection")
    try:
        areas: list[OutlookArea] = []
        meta: dict[str, Any] = {}
        predictability_too_low = False
        for feature in data["features"]:
            props = feature.get("properties") or {}
            if not meta:
                meta = props
            label = str(props.get("LABEL") or "").strip()
            if label.lower() == PREDICTABILITY_TOO_LOW:
                predictability_too_low = True
            if not label or props.get("DN") == 0:
                continue
            polygons = _polygons(feature.get("geometry"))
            if polygons:
                areas.append(OutlookArea(label, polygons))
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as err:
        raise OutlookParseError(f"malformed feature: {err}") from err
    return OutlookLayer(
        areas=tuple(areas),
        issued=_parse_dt(meta.get("ISSUE_ISO")),
        valid=_parse_dt(meta.get("VALID_ISO")),
        expire=_parse_dt(meta.get("EXPIRE_ISO")),
        forecaster=meta.get("FORECASTER") or None,
        predictability_too_low=predictability_too_low,
    )


def categorical_at(layer: OutlookLayer, lat: float, lon: float) -> RiskLevel:
    level = RiskLevel.NONE
    for area in layer.areas:
        candidate = RiskLevel.from_label(area.label)
        if (
            candidate is not None
            and candidate > level
            and point_in_any(lon, lat, area.polygons)
        ):
            level = candidate
    return level


def parse_percent(label: str) -> int | None:
    try:
        value = float(label)
    except ValueError:
        return None
    return round(value * 100) if 0 < value <= 1 else None


def probability_at(layer: OutlookLayer, lat: float, lon: float) -> int:
    best = 0
    for area in layer.areas:
        percent = parse_percent(area.label)
        if (
            percent is not None
            and percent > best
            and point_in_any(lon, lat, area.polygons)
        ):
            best = percent
    return best


def any_area_at(layer: OutlookLayer, lat: float, lon: float) -> bool:
    return any(point_in_any(lon, lat, area.polygons) for area in layer.areas)
