"""Builders for bundles, watches and MDs used across tests."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from custom_components.noaa_spc.api.models import (
    MesoscaleDiscussion,
    TextProduct,
    Watch,
)
from custom_components.noaa_spc.api.outlooks import parse_layer
from custom_components.noaa_spc.api.products import watch_url
from custom_components.noaa_spc.api.spc import AlertBundle, OutlookBundle
from tests.helpers import HOME, collection, empty_feature, feature, square


def outlook_bundle(
    layers: Mapping[str, dict[str, Any]],
    *,
    when: datetime | None = None,
    texts: Mapping[str, TextProduct] | None = None,
    images: Mapping[str, bytes] | None = None,
) -> OutlookBundle:
    when = when or datetime.now(UTC)
    parsed = {key: parse_layer(value) for key, value in layers.items()}
    texts = dict(texts or {})
    images = dict(images or {})
    updated = (
        {f"layer:{k}": when for k in parsed}
        | {f"text:{k}": when for k in texts}
        | {f"image:{k}": when for k in images}
    )
    return OutlookBundle(parsed, texts, images, updated)


def risk_layers(day1: str = "SLGT") -> dict[str, dict[str, Any]]:
    """Layers around HOME: Day 1 `day1` inside TSTM, 5% tornado (sig), 15% wind,
    Day 2 MRGL, Day 3 empty with 5% any-severe, Day 4 15%, Day 5 predictability
    too low. Day 2 hazards and Days 6-8 are absent."""
    near = square(*HOME)
    wide = square(*HOME, half=3.0)
    return {
        "day1_cat": collection(feature("TSTM", wide), feature(day1, near)),
        "day1_torn": collection(feature("0.05", near)),
        "day1_sigtorn": collection(feature("SIGN", near)),
        "day1_wind": collection(feature("0.15", near)),
        "day1_hail": collection(),
        "day2_cat": collection(feature("MRGL", near)),
        "day3_cat": collection(),
        "day3_prob": collection(feature("0.05", near)),
        "day4_prob": collection(feature("0.15", near)),
        "day5_prob": collection(empty_feature("Predictability Too Low")),
    }


def alert_bundle(
    watches: Iterable[Watch] = (),
    mds: Iterable[MesoscaleDiscussion] = (),
    *,
    when: datetime | None = None,
) -> AlertBundle:
    when = when or datetime.now(UTC)
    return AlertBundle(tuple(watches), tuple(mds), when, when)


def make_watch(number: int = 612, kind: str = "tornado", pds: bool = False) -> Watch:
    return Watch(number=number, kind=kind, pds=pds, url=watch_url(number))


def make_md(
    number: int = 2104, center: tuple[float, float] = HOME, half: float = 1.0
) -> MesoscaleDiscussion:
    ring = tuple((x, y) for x, y in square(*center, half))
    return MesoscaleDiscussion(
        number=number,
        areas_affected="central Oklahoma",
        concerning="Severe potential...Watch likely",
        watch_probability=80,
        summary="Storms expected.",
        polygon=(ring,),
        url=f"https://www.spc.noaa.gov/products/md/md{number:04d}.html",
    )
