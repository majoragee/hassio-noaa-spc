# NOAA Storm Prediction Center for Home Assistant

Custom integration that brings Storm Prediction Center (SPC) convective outlooks, mesoscale discussions and a national watch count into Home Assistant. Requires Home Assistant 2026.2 or newer.

## What it does

- National SPC outlook map images and the forecaster discussion text for Day 1, Day 2, Day 3 and Day 4-8.
- Per-location categorical risk for Day 1-3, plus a "max risk next 3 days" sensor.
- Per-location probabilities: Day 1-2 tornado, wind and hail (with significant-hazard flags), Day 3 any-severe, and Day 4-8 severe probability.
- A per-location mesoscale discussion binary sensor, and a national list of active mesoscale discussions.
- A national active-watch count (tornado, severe thunderstorm, PDS) as a pulse check.
- Two events, `noaa_spc_risk_changed` and `noaa_spc_md_issued`, and a ready-made notification blueprint.

Locations can be fixed coordinates or tracked (a `device_tracker`, `person` or `zone` entity).

**Out of scope:** location-specific watches and warnings. The watch count is national only. Use an NWS alerts integration for watches and warnings that apply to your location.

## Installation

HACS:

1. HACS -> three-dot menu -> Custom repositories.
2. Add `https://github.com/majoragee/hassio-noaa-spc` with category Integration.
3. Install "NOAA Storm Prediction Center" and restart Home Assistant.

Manual: copy `custom_components/noaa_spc` into your `config/custom_components` directory and restart.

## Setup

Settings -> Devices & services -> Add integration -> "NOAA Storm Prediction Center", then choose Fixed or Tracked and follow the prompts. The shared "NOAA SPC" hub entry is created automatically; it owns the national sensors, images and polling intervals (its options). Each location entry has options for the entity groups it exposes (categorical, probabilistic, extended, alerts), and tracked locations have a movement threshold (default 1 km).

## Entities

Examples use a location titled "Home". Entity ids are derived from the device name "SPC – Home".

### Location entities

| Entity | State | Key attributes |
| --- | --- | --- |
| `sensor.spc_home_day_1_risk`, `_day_2_risk`, `_day_3_risk` | Enum: `none`, `TSTM`, `MRGL`, `SLGT`, `ENH`, `MDT`, `HIGH` | `level` (0-6), `label`, `issued`, `valid`, `expire`, `forecaster` |
| `sensor.spc_home_max_risk_next_3_days` | Highest categorical risk over Days 1-3 | `level`, `day` |
| `sensor.spc_home_day_1_tornado_probability`, `_wind_`, `_hail_`; same for Day 2 | Percent | `significant`, `issued`, `valid`, `expire`, `forecaster` |
| `sensor.spc_home_day_3_severe_probability` | Percent | `significant`, plus the fields above |
| `sensor.spc_home_day_4_severe_probability` ... `day_8_` | Percent | `predictability_too_low`, plus the fields above |
| `binary_sensor.spc_home_mesoscale_discussion` | On while an MD covers the location | `number`, `areas_affected`, `concerning`, `watch_probability`, `summary`, `url` (first MD), `items` (all) |

### Hub entities

| Entity | State | Key attributes |
| --- | --- | --- |
| `sensor.noaa_spc_day_1_discussion`, `_day_2_`, `_day_3_`, `_day_4_8_discussion` | Timestamp the outlook was issued | `valid`, `text`, `summary`, `forecaster` |
| `sensor.noaa_spc_active_watches` | Number of active watches nationwide | `tornado`, `severe_thunderstorm`, `pds`, `items` (number, type, pds, url) |
| `sensor.noaa_spc_active_mesoscale_discussions` | Number of active MDs nationwide | `items` |
| `image.noaa_spc_day_1_outlook`, `_day_2_outlook`, `_day_3_outlook`, `_day_4_8_outlook` | Outlook map | enabled by default |
| `image.noaa_spc_day_1_tornado_outlook`, `_wind_`, `_hail_`; same for Day 2 | Probabilistic hazard maps | disabled by default |

Long text attributes (`text`, `summary`, `items`) are excluded from the recorder. Entities become unavailable when data is stale (see below).

## Events

### `noaa_spc_risk_changed`

Fired when a location's categorical risk for a day changes. The first evaluation after startup or setup fires nothing.

| Field | Description |
| --- | --- |
| `config_entry_id`, `location_name`, `latitude`, `longitude` | The location |
| `day` | Outlook day (1-3) |
| `old`, `new` | Risk state names |
| `old_level`, `new_level` | Numeric levels (0-6) |
| `upgraded` | `true` if the risk increased |

### `noaa_spc_md_issued`

Fired when a new mesoscale discussion first covers a location. Disabling the "alerts" (mesoscale discussions) group for a location also stops this event for that location. `noaa_spc_risk_changed` fires regardless of which groups are enabled.

| Field | Description |
| --- | --- |
| `config_entry_id`, `location_name`, `latitude`, `longitude` | The location |
| `number` | MD number |
| `concerning` | Subject line (for example a watch being considered) |
| `watch_probability` | Percent, or `null` |
| `summary`, `url` | Summary text and link |

## Blueprint

[Import the blueprint](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fmajoragee%2Fhassio-noaa-spc%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fnoaa_spc%2Fnotify_severe_risk.yaml).

Inputs: `location`, `threshold` (minimum categorical risk), `days`, `include_mds` and `notify` (your actions). The variable `message` is available to the actions:

```yaml
action: notify.mobile_app_phone
data:
  title: "SPC"
  message: "{{ message }}"
```

## Data sources and limits

- SPC products only, from `www.spc.noaa.gov`, including the `spcwwrss.xml` watch feed used for the national count. No other service is contacted.
- Contiguous US only.
- Polling defaults: outlooks every 5 minutes, watches and MDs every 2 minutes (configurable on the hub).
- Staleness: outlook-derived entities become unavailable after 3 hours without a successful fetch; MD entities and the watch count after 15 minutes.

## Disclaimer

This project is not affiliated with or endorsed by NOAA or the National Weather Service. It is not for life-safety decisions. Always heed official watches, warnings and local authorities.

## Releasing

Day-to-day work is pushed to the Gitea `origin` only. GitHub (the `github`
remote, which HACS installs from) is updated only when a release is cut:

```bash
scripts/release.sh 0.1.0
```

The script requires a clean `main`, bumps the version in `manifest.json`,
`pyproject.toml` and the User-Agent, runs lint and tests, commits and tags
`v0.1.0`, pushes `main` and the tag to both remotes, and publishes a GitHub
release with generated notes.
