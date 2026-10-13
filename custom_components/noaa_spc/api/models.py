"""Data models for SPC products. Must not import Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum

Ring = tuple[tuple[float, float], ...]
Polygon = tuple[Ring, ...]


class RiskLevel(IntEnum):
    """SPC categorical risk, ordered by severity."""

    NONE = 0
    TSTM = 1
    MRGL = 2
    SLGT = 3
    ENH = 4
    MDT = 5
    HIGH = 6

    @classmethod
    def from_label(cls, label: str) -> RiskLevel | None:
        try:
            return cls[label.strip().upper()]
        except KeyError:
            return None

    @property
    def state(self) -> str:
        return "none" if self is RiskLevel.NONE else self.name

    @property
    def description(self) -> str:
        return _DESCRIPTIONS[self]


_DESCRIPTIONS = {
    RiskLevel.NONE: "No Risk",
    RiskLevel.TSTM: "General Thunderstorms",
    RiskLevel.MRGL: "Marginal Risk",
    RiskLevel.SLGT: "Slight Risk",
    RiskLevel.ENH: "Enhanced Risk",
    RiskLevel.MDT: "Moderate Risk",
    RiskLevel.HIGH: "High Risk",
}

RISK_STATES = [level.state for level in RiskLevel]


@dataclass(frozen=True)
class OutlookArea:
    label: str
    polygons: tuple[Polygon, ...]


@dataclass(frozen=True)
class OutlookLayer:
    areas: tuple[OutlookArea, ...]
    issued: datetime | None
    valid: datetime | None
    expire: datetime | None
    forecaster: str | None
    predictability_too_low: bool = False


@dataclass(frozen=True)
class TextProduct:
    text: str
    summary: str | None
    forecaster: str | None


@dataclass(frozen=True)
class MesoscaleDiscussion:
    number: int
    areas_affected: str | None
    concerning: str | None
    watch_probability: int | None
    summary: str | None
    polygon: Polygon
    url: str


@dataclass(frozen=True)
class Watch:
    number: int
    kind: str  # "tornado" or "severe_thunderstorm"
    pds: bool
    url: str
