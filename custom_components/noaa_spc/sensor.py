"""Sensor platform for NOAA SPC."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .api.models import RISK_STATES
from .api.outlooks import is_current
from .const import (
    ALERT_STALE,
    GROUP_CATEGORICAL,
    GROUP_EXTENDED,
    GROUP_PROBABILISTIC,
    OUTLOOK_STALE,
)
from .entity import (
    SpcHubEntity,
    SpcLocationEntity,
    async_remove_entities,
    is_fresh,
    md_attributes,
    watch_attributes,
)
from .hub import SpcHub, is_hub_entry
from .location import LocationCoordinator, LocationData


@dataclass(frozen=True, kw_only=True)
class LocationSensorDescription(SensorEntityDescription):
    group: str
    source: str
    value_fn: Callable[[LocationData], StateType]
    attrs_fn: Callable[[LocationData], dict[str, Any]]


def _layer_attrs(data: LocationData, layer_key: str) -> dict[str, Any]:
    layer = data.layers.get(layer_key)
    if layer is None:
        return {}
    if not is_current(layer, dt_util.utcnow()):
        # SPC serves months-old files for empty outlooks; don't report them.
        return dict.fromkeys(("issued", "valid", "expire", "forecaster"))
    return {
        "issued": layer.issued.isoformat() if layer.issued else None,
        "valid": layer.valid.isoformat() if layer.valid else None,
        "expire": layer.expire.isoformat() if layer.expire else None,
        "forecaster": layer.forecaster,
    }


def _categorical(day: int) -> LocationSensorDescription:
    layer_key = f"day{day}_cat"

    def value(data: LocationData) -> StateType:
        level = data.outlook.categorical.get(day)
        return level.state if level is not None else None

    def attrs(data: LocationData) -> dict[str, Any]:
        level = data.outlook.categorical.get(day)
        if level is None:
            return {}
        return {
            "level": int(level),
            "label": level.description,
            **_layer_attrs(data, layer_key),
        }

    return LocationSensorDescription(
        key=f"day{day}_risk",
        name=f"Day {day} risk",
        device_class=SensorDeviceClass.ENUM,
        options=RISK_STATES,
        group=GROUP_CATEGORICAL,
        source=f"layer:{layer_key}",
        value_fn=value,
        attrs_fn=attrs,
    )


def _max_risk() -> LocationSensorDescription:
    def value(data: LocationData) -> StateType:
        peak = data.outlook.max_next_3_days
        return peak[0].state if peak else None

    def attrs(data: LocationData) -> dict[str, Any]:
        peak = data.outlook.max_next_3_days
        return {"level": int(peak[0]), "day": peak[1]} if peak else {}

    return LocationSensorDescription(
        key="max_risk_next_3_days",
        name="Max risk next 3 days",
        device_class=SensorDeviceClass.ENUM,
        options=RISK_STATES,
        group=GROUP_CATEGORICAL,
        source="layer:day1_cat",
        value_fn=value,
        attrs_fn=attrs,
    )


def _probability(prob_key: str, key: str, name: str) -> LocationSensorDescription:
    def value(data: LocationData) -> StateType:
        return data.outlook.probability.get(prob_key)

    def attrs(data: LocationData) -> dict[str, Any]:
        return {
            "significant": data.outlook.significant.get(prob_key, False),
            **_layer_attrs(data, prob_key),
        }

    return LocationSensorDescription(
        key=key,
        name=name,
        native_unit_of_measurement=PERCENTAGE,
        group=GROUP_PROBABILISTIC,
        source=f"layer:{prob_key}",
        value_fn=value,
        attrs_fn=attrs,
    )


def _extended(day: int) -> LocationSensorDescription:
    prob_key = f"day{day}_prob"

    def value(data: LocationData) -> StateType:
        return data.outlook.probability.get(prob_key)

    def attrs(data: LocationData) -> dict[str, Any]:
        return {
            "predictability_too_low": data.outlook.predictability_too_low.get(
                day, False
            ),
            **_layer_attrs(data, prob_key),
        }

    return LocationSensorDescription(
        key=f"day{day}_severe",
        name=f"Day {day} severe probability",
        native_unit_of_measurement=PERCENTAGE,
        group=GROUP_EXTENDED,
        source=f"layer:{prob_key}",
        value_fn=value,
        attrs_fn=attrs,
    )


HAZARD_NAMES = {"torn": "tornado", "wind": "wind", "hail": "hail"}

LOCATION_SENSORS: tuple[LocationSensorDescription, ...] = (
    *(_categorical(day) for day in (1, 2, 3)),
    _max_risk(),
    *(
        _probability(
            f"day{day}_{hazard}", f"day{day}_{name}", f"Day {day} {name} probability"
        )
        for day in (1, 2)
        for hazard, name in HAZARD_NAMES.items()
    ),
    _probability("day3_prob", "day3_severe", "Day 3 severe probability"),
    *(_extended(day) for day in range(4, 9)),
)


class LocationSensor(SpcLocationEntity, SensorEntity):
    entity_description: LocationSensorDescription

    def __init__(
        self, coordinator: LocationCoordinator, description: LocationSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        data = self.coordinator.data
        return (
            super().available
            and data is not None
            and data.position is not None
            and data.outlook is not None
            and is_fresh(
                data.updated.get(self.entity_description.source), OUTLOOK_STALE
            )
        )

    @property
    def native_value(self) -> StateType:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.entity_description.attrs_fn(self.coordinator.data)


@dataclass(frozen=True, kw_only=True)
class HubSensorDescription(SensorEntityDescription):
    feed: str  # "outlooks" or "alerts"
    value_fn: Callable[[Any], StateType | datetime]
    attrs_fn: Callable[[Any], dict[str, Any]]
    updated_fn: Callable[[Any], datetime | None]
    max_age: timedelta


def _discussion(text_key: str, layer_key: str, name: str) -> HubSensorDescription:
    def value(bundle: Any) -> datetime | None:
        layer = bundle.layers.get(layer_key)
        if layer is None or not is_current(layer, dt_util.utcnow()):
            return None
        return layer.issued

    def attrs(bundle: Any) -> dict[str, Any]:
        text = bundle.texts.get(text_key)
        if text is None:
            return {}
        layer = bundle.layers.get(layer_key)
        valid = (
            layer.valid
            if layer is not None and is_current(layer, dt_util.utcnow())
            else None
        )
        return {
            "valid": valid.isoformat() if valid else None,
            "text": text.text,
            "summary": text.summary,
            "forecaster": text.forecaster,
        }

    return HubSensorDescription(
        key=f"{text_key}_discussion",
        name=name,
        device_class=SensorDeviceClass.TIMESTAMP,
        feed="outlooks",
        value_fn=value,
        attrs_fn=attrs,
        updated_fn=lambda bundle: bundle.updated.get(f"text:{text_key}"),
        max_age=OUTLOOK_STALE,
    )


HUB_SENSORS: tuple[HubSensorDescription, ...] = (
    _discussion("day1", "day1_cat", "Day 1 discussion"),
    _discussion("day2", "day2_cat", "Day 2 discussion"),
    _discussion("day3", "day3_cat", "Day 3 discussion"),
    _discussion("day48", "day4_prob", "Day 4–8 discussion"),
    HubSensorDescription(
        key="active_watches",
        name="Active watches",
        feed="alerts",
        value_fn=lambda bundle: len(bundle.watches),
        attrs_fn=lambda bundle: {
            "tornado": sum(w.kind == "tornado" for w in bundle.watches),
            "severe_thunderstorm": sum(
                w.kind == "severe_thunderstorm" for w in bundle.watches
            ),
            "pds": sum(w.pds for w in bundle.watches),
            "items": [watch_attributes(w) for w in bundle.watches],
        },
        updated_fn=lambda bundle: bundle.watches_updated,
        max_age=ALERT_STALE,
    ),
    HubSensorDescription(
        key="active_mds",
        name="Active mesoscale discussions",
        feed="alerts",
        value_fn=lambda bundle: len(bundle.mds),
        attrs_fn=lambda bundle: {"items": [md_attributes(m) for m in bundle.mds]},
        updated_fn=lambda bundle: bundle.mds_updated,
        max_age=ALERT_STALE,
    ),
)


class HubSensor(SpcHubEntity, SensorEntity):
    entity_description: HubSensorDescription
    _unrecorded_attributes = frozenset({"text", "summary", "items"})

    def __init__(self, hub: SpcHub, description: HubSensorDescription) -> None:
        coordinator = hub.outlooks if description.feed == "outlooks" else hub.alerts
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        data = self.coordinator.data
        return (
            super().available
            and data is not None
            and is_fresh(
                self.entity_description.updated_fn(data),
                self.entity_description.max_age,
            )
        )

    @property
    def native_value(self) -> StateType | datetime:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.entity_description.attrs_fn(self.coordinator.data)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    if is_hub_entry(entry):
        hub: SpcHub = entry.runtime_data
        async_add_entities(HubSensor(hub, d) for d in HUB_SENSORS)
        return
    coordinator: LocationCoordinator = entry.runtime_data
    async_remove_entities(
        hass,
        Platform.SENSOR,
        (
            f"{entry.entry_id}_{d.key}"
            for d in LOCATION_SENSORS
            if d.group not in coordinator.groups
        ),
    )
    async_add_entities(
        LocationSensor(coordinator, d)
        for d in LOCATION_SENSORS
        if d.group in coordinator.groups
    )
