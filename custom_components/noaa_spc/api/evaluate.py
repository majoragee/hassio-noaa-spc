"""Evaluate SPC products at a point. Must not import Home Assistant."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .geometry import point_in_polygon
from .models import MesoscaleDiscussion, OutlookLayer, RiskLevel
from .outlooks import any_area_at, categorical_at, probability_at

PROBABILITY_KEYS = (
    "day1_torn",
    "day1_wind",
    "day1_hail",
    "day2_torn",
    "day2_wind",
    "day2_hail",
    "day3_prob",
)
EXTENDED_DAYS = range(4, 9)


@dataclass(frozen=True)
class OutlookRisk:
    categorical: Mapping[int, RiskLevel]
    probability: Mapping[str, int]
    significant: Mapping[str, bool]
    predictability_too_low: Mapping[int, bool]

    @property
    def max_next_3_days(self) -> tuple[RiskLevel, int] | None:
        if not self.categorical:
            return None
        day = max(sorted(self.categorical), key=lambda d: self.categorical[d])
        return self.categorical[day], day


@dataclass(frozen=True)
class AlertRisk:
    mds: tuple[MesoscaleDiscussion, ...]


def _significant_key(key: str) -> str:
    """day1_torn -> day1_sigtorn, day3_prob -> day3_sigprob."""
    day, product = key.split("_", 1)
    return f"{day}_sig{product}"


def evaluate_outlooks(
    layers: Mapping[str, OutlookLayer], lat: float, lon: float
) -> OutlookRisk:
    categorical = {
        day: categorical_at(layers[f"day{day}_cat"], lat, lon)
        for day in (1, 2, 3)
        if f"day{day}_cat" in layers
    }
    probability: dict[str, int] = {}
    significant: dict[str, bool] = {}
    for key in PROBABILITY_KEYS:
        if key in layers:
            probability[key] = probability_at(layers[key], lat, lon)
        if (sig := _significant_key(key)) in layers:
            significant[key] = any_area_at(layers[sig], lat, lon)
    predictability_too_low: dict[int, bool] = {}
    for day in EXTENDED_DAYS:
        if (key := f"day{day}_prob") in layers:
            probability[key] = probability_at(layers[key], lat, lon)
            predictability_too_low[day] = layers[key].predictability_too_low
    return OutlookRisk(categorical, probability, significant, predictability_too_low)


def evaluate_alerts(
    mds: Iterable[MesoscaleDiscussion], lat: float, lon: float
) -> AlertRisk:
    return AlertRisk(tuple(m for m in mds if point_in_polygon(lon, lat, m.polygon)))
