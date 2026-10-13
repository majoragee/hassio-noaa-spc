"""Constants for the NOAA SPC integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "noaa_spc"
MANUFACTURER = "NOAA Storm Prediction Center"
SPC_SITE = "https://www.spc.noaa.gov/"

CONF_ENTRY_TYPE = "entry_type"
ENTRY_TYPE_HUB = "hub"
ENTRY_TYPE_LOCATION = "location"
HUB_UNIQUE_ID = "hub"
HUB_TITLE = "NOAA SPC"

CONF_MODE = "mode"
MODE_FIXED = "fixed"
MODE_TRACKED = "tracked"
CONF_TRACKED_ENTITY = "tracked_entity"
CONF_MOVE_THRESHOLD_KM = "move_threshold_km"
DEFAULT_MOVE_THRESHOLD_KM = 1.0
TRACKABLE_DOMAINS = ["device_tracker", "person", "zone"]

CONF_GROUPS = "groups"
GROUP_CATEGORICAL = "categorical"
GROUP_PROBABILISTIC = "probabilistic"
GROUP_EXTENDED = "extended"
GROUP_ALERTS = "alerts"
ALL_GROUPS = [GROUP_CATEGORICAL, GROUP_PROBABILISTIC, GROUP_EXTENDED, GROUP_ALERTS]

CONF_OUTLOOK_INTERVAL = "outlook_interval_min"
CONF_ALERT_INTERVAL = "alert_interval_min"
DEFAULT_OUTLOOK_INTERVAL = 5
DEFAULT_ALERT_INTERVAL = 2

OUTLOOK_STALE = timedelta(hours=3)
ALERT_STALE = timedelta(minutes=15)

EVENT_RISK_CHANGED = "noaa_spc_risk_changed"
EVENT_MD_ISSUED = "noaa_spc_md_issued"

ISSUE_MISSING_TRACKER = "missing_tracker"
