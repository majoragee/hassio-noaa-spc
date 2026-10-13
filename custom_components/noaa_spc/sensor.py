"""Sensor platform for NOAA SPC."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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

from .api.models import RISK_STATES
from .const import (
    GROUP_CATEGORICAL,
    GROUP_EXTENDED,
    GROUP_PROBABILISTIC,
    OUTLOOK_STALE,
)
from .entity import SpcLocationEntity, async_remove_entities, data_age, is_fresh
from .hub import is_hub_entry
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
        data = self.coordinator.data
        return {
            **self.entity_description.attrs_fn(data),
            "data_age": data_age(data.updated.get(self.entity_description.source)),
        }


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    if is_hub_entry(entry):
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
