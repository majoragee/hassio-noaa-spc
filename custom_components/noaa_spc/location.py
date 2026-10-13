"""Per-location evaluation, events and tracking."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
    CONF_LATITUDE,
    CONF_LONGITUDE,
)
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util
from homeassistant.util.location import distance

from .api.evaluate import AlertRisk, OutlookRisk, evaluate_alerts, evaluate_outlooks
from .api.models import MesoscaleDiscussion, OutlookLayer
from .const import (
    ALL_GROUPS,
    CONF_GROUPS,
    CONF_MODE,
    CONF_MOVE_THRESHOLD_KM,
    CONF_TRACKED_ENTITY,
    DEFAULT_MOVE_THRESHOLD_KM,
    DOMAIN,
    EVENT_MD_ISSUED,
    EVENT_RISK_CHANGED,
    GROUP_ALERTS,
    ISSUE_MISSING_TRACKER,
    MODE_TRACKED,
)

if TYPE_CHECKING:
    from .hub import SpcHub

_LOGGER = logging.getLogger(__name__)

Position = tuple[float, float]


@dataclass(frozen=True)
class LocationData:
    position: Position | None
    outlook: OutlookRisk | None
    alerts: AlertRisk | None
    layers: Mapping[str, OutlookLayer]
    updated: Mapping[str, datetime]
    mds_updated: datetime | None


def position_from_state(state: State | None) -> Position | None:
    if state is None:
        return None
    lat = state.attributes.get(ATTR_LATITUDE)
    lon = state.attributes.get(ATTR_LONGITUDE)
    if lat is None or lon is None:
        return None
    try:
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None


class LocationCoordinator(DataUpdateCoordinator[LocationData]):
    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, hub: SpcHub) -> None:
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=f"{DOMAIN} {entry.title}"
        )
        self.hub = hub
        conf = {**entry.data, **entry.options}
        self.mode: str = conf[CONF_MODE]
        self.tracked_entity: str | None = conf.get(CONF_TRACKED_ENTITY)
        self.fixed_position: Position | None = (
            None
            if self.mode == MODE_TRACKED
            else (float(conf[CONF_LATITUDE]), float(conf[CONF_LONGITUDE]))
        )
        self.threshold_m = (
            float(conf.get(CONF_MOVE_THRESHOLD_KM, DEFAULT_MOVE_THRESHOLD_KM)) * 1000
        )
        self.groups: set[str] = set(conf.get(CONF_GROUPS, ALL_GROUPS))
        self._position: Position | None = None
        self._outlook: OutlookRisk | None = None
        self._alerts: AlertRisk | None = None
        self._levels: dict[int, Any] | None = None
        self._seen_mds: set[int] | None = None

    @property
    def _issue_id(self) -> str:
        return f"{ISSUE_MISSING_TRACKER}_{self.config_entry.entry_id}"

    async def async_start(self) -> None:
        entry = self.config_entry
        entry.async_on_unload(
            self.hub.outlooks.async_add_listener(self._handle_outlooks)
        )
        entry.async_on_unload(self.hub.alerts.async_add_listener(self._handle_alerts))
        if self.mode == MODE_TRACKED:
            assert self.tracked_entity is not None
            entry.async_on_unload(
                async_track_state_change_event(
                    self.hass, [self.tracked_entity], self._handle_tracker_event
                )
            )
            entry.async_on_unload(async_at_started(self.hass, self._handle_started))
            self._set_position(
                position_from_state(self.hass.states.get(self.tracked_entity))
            )
        else:
            self._set_position(self.fixed_position)

    # --- hub / tracker callbacks -------------------------------------------

    @callback
    def _handle_outlooks(self) -> None:
        self._evaluate_outlooks()
        self._publish()

    @callback
    def _handle_alerts(self) -> None:
        self._evaluate_alerts()
        self._publish()

    @callback
    def _handle_started(self, _hass: HomeAssistant) -> None:
        assert self.tracked_entity is not None
        self._check_tracker_exists(self.hass.states.get(self.tracked_entity))

    @callback
    def _handle_tracker_event(self, event: Event[EventStateChangedData]) -> None:
        new_state = event.data["new_state"]
        self._check_tracker_exists(new_state)
        self._set_position(position_from_state(new_state))

    # --- position ----------------------------------------------------------

    @callback
    def _set_position(self, position: Position | None) -> None:
        if position is None:
            self._position = None
            self._publish()
            return
        if (
            self._position is not None
            and (distance(*self._position, *position) or 0.0) < self.threshold_m
        ):
            return
        self._position = position
        self._evaluate_outlooks()
        self._evaluate_alerts()
        self._publish()

    # --- evaluation and events ----------------------------------------------

    def _event_base(self) -> dict[str, Any]:
        assert self._position is not None
        return {
            "config_entry_id": self.config_entry.entry_id,
            "location_name": self.config_entry.title,
            "latitude": self._position[0],
            "longitude": self._position[1],
        }

    def _evaluate_outlooks(self) -> None:
        bundle = self.hub.outlooks.data
        if bundle is None or self._position is None:
            return
        risk = evaluate_outlooks(bundle.layers, *self._position, now=dt_util.utcnow())
        if self._levels is not None:
            for day, new in risk.categorical.items():
                old = self._levels.get(day)
                if old is not None and old != new:
                    self.hass.bus.async_fire(
                        EVENT_RISK_CHANGED,
                        {
                            **self._event_base(),
                            "day": day,
                            "old": old.state,
                            "new": new.state,
                            "old_level": int(old),
                            "new_level": int(new),
                            "upgraded": new > old,
                        },
                    )
        self._levels = {**(self._levels or {}), **risk.categorical}
        self._outlook = risk

    def _fire_md(self, md: MesoscaleDiscussion) -> None:
        self.hass.bus.async_fire(
            EVENT_MD_ISSUED,
            {
                **self._event_base(),
                "number": md.number,
                "concerning": md.concerning,
                "watch_probability": md.watch_probability,
                "summary": md.summary,
                "url": md.url,
            },
        )

    def _evaluate_alerts(self) -> None:
        bundle = self.hub.alerts.data
        if GROUP_ALERTS not in self.groups or bundle is None or self._position is None:
            return
        risk = evaluate_alerts(bundle.mds, *self._position)
        if self._seen_mds is not None:
            for md in risk.mds:
                if md.number not in self._seen_mds:
                    self._fire_md(md)
        active_mds = {m.number for m in bundle.mds}
        self._seen_mds = (
            (self._seen_mds or set()) | {m.number for m in risk.mds}
        ) & active_mds
        self._alerts = risk

    @callback
    def _publish(self) -> None:
        outlooks = self.hub.outlooks.data
        alerts = self.hub.alerts.data
        positioned = self._position is not None
        self.async_set_updated_data(
            LocationData(
                position=self._position,
                outlook=self._outlook if positioned else None,
                alerts=self._alerts if positioned else None,
                layers=outlooks.layers if outlooks else {},
                updated=outlooks.updated if outlooks else {},
                mds_updated=alerts.mds_updated if alerts else None,
            )
        )

    # --- repairs -------------------------------------------------------------

    @callback
    def _check_tracker_exists(self, state: State | None) -> None:
        assert self.tracked_entity is not None
        missing = (
            state is None
            and er.async_get(self.hass).async_get(self.tracked_entity) is None
        )
        if missing:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_MISSING_TRACKER,
                translation_placeholders={
                    "entity_id": self.tracked_entity,
                    "location": self.config_entry.title,
                },
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)
