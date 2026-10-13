"""Point-in-polygon tests on (lon, lat) rings. Must not import Home Assistant."""

from __future__ import annotations

from collections.abc import Iterable

from .models import Polygon, Ring


def _in_ring(lon: float, lat: float, ring: Ring) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat):
            x_cross = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < x_cross:
                inside = not inside
        j = i
    return inside


def point_in_polygon(lon: float, lat: float, polygon: Polygon) -> bool:
    if not polygon or not _in_ring(lon, lat, polygon[0]):
        return False
    return not any(_in_ring(lon, lat, hole) for hole in polygon[1:])


def point_in_any(lon: float, lat: float, polygons: Iterable[Polygon]) -> bool:
    return any(point_in_polygon(lon, lat, polygon) for polygon in polygons)
