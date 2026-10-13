# NOAA SPC Home Assistant Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a HACS-installable Home Assistant custom integration (`noaa_spc`) that exposes SPC outlook maps/discussions nationally and per-location categorical/probabilistic risk and mesoscale discussions, plus a national active-watch count, with events and a notification blueprint. Everything comes from `spc.noaa.gov`; location-specific watches are deliberately out of scope (a separate NWS weather integration covers them).

**Architecture:** A Home-Assistant-free `api/` package fetches (conditional GET) and parses SPC GeoJSON/text/RSS into frozen dataclasses, and evaluates point containment. A reference-counted hub singleton owns two `DataUpdateCoordinator`s (outlooks, alerts) shared by all config entries; one hub config entry hosts national entities, and each location config entry has a `LocationCoordinator` that re-evaluates on hub updates or tracker movement and fires events.

**Tech Stack:** Python 3.13+, Home Assistant ≥ 2025.1 APIs, aiohttp (HA's session), stdlib `xml.etree`/`json`/`re`, pytest + `pytest-homeassistant-custom-component`, `aioresponses` (API tests), ruff.

**Spec:** `docs/superpowers/specs/2026-10-13-noaa-spc-integration-design.md`

## Global Constraints

- Integration domain `noaa_spc`; files under `custom_components/noaa_spc/`.
- No runtime dependencies beyond Home Assistant (`manifest.json` `"requirements": []`).
- `custom_components/noaa_spc/api/` must not import `homeassistant`.
- Declared minimum Home Assistant version: `2025.1.0` (in `hacs.json`).
- Every HTTP request sends `User-Agent: hassio-noaa-spc/0.1.0 (https://github.com/majoragee/hassio-noaa-spc)`.
- Outlook polling default 5 min, watch/MD polling default 2 min.
- Outlook-derived entities unavailable after 3 h without a successful fetch of their source; MD entities and the national watch count after 15 min.
- All requests go to `https://www.spc.noaa.gov/` only — no `api.weather.gov` calls, no per-location watch matching.
- First evaluation after startup/setup fires no events.
- Long text attributes (`text`, `summary`, `items`) excluded from the recorder.
- Never put a personal name or personal email in any file; the author/copyright holder is `majoragee`.
- Commit messages must NOT contain Claude/AI attribution or `Co-Authored-By` trailers (user's global instruction overrides any harness default).
- All commands run from the repo root `/home/craig/dev/hassio-noaa-spc` using the venv at `.venv` (`.venv/bin/pytest`, `.venv/bin/ruff`).

## Review Focus

1. **MD feed link format is unverified while MDs are active** — links may be `md/mdNNNN.html` or `md/YYYY/mdNNNN.html`; the parser must accept both (test in Task 5).
2. **Watch feed format is unverified while watches are active** — `spcwwrss.xml` items may be watch pages, status reports or the "No watches are valid" placeholder, and the same watch may appear twice; the count must be per distinct watch number and the placeholder must yield zero (tests in Task 6).
3. **Watch feed outage** — the bundle must keep the last watch list and timestamp while MD updates continue (test in Task 8); the hub watch sensor goes unavailable only after 15 min via `ALERT_STALE` (Task 14).
4. **Empty layer with stale metadata** — SPC empty layers carry months-old `ISSUE_ISO`; risk must be `none` and the entity available because freshness uses fetch time, not issue time (test in Task 13).
5. **Rapid tracker updates** — two moves in quick succession; the final position must win and the entities must reflect it (test in Task 11).

---

## File Structure

```
custom_components/noaa_spc/
  __init__.py          # async_setup (hub import), entry setup/unload/remove
  manifest.json
  const.py             # DOMAIN, config keys, defaults, event names, staleness windows
  hub.py               # OutlookCoordinator, AlertCoordinator, SpcHub, acquire/release, is_hub_entry
  location.py          # LocationData, LocationCoordinator (position, evaluation, events, repairs)
  entity.py            # base entities, freshness helpers, attribute helpers, registry cleanup
  sensor.py            # location sensors + hub sensors
  binary_sensor.py     # MD binary sensor
  image.py             # outlook map images
  config_flow.py       # config flow (fixed/tracked/outside/import) + options flows
  translations/en.json
  api/
    __init__.py
    products.py        # URLs, product keys, USER_AGENT, in_conus
    models.py          # RiskLevel, OutlookArea, OutlookLayer, TextProduct, MesoscaleDiscussion, Watch
    geometry.py        # point-in-polygon
    outlooks.py        # GeoJSON layer parsing + lookups
    text.py            # outlook discussion text parsing
    mds.py             # MD RSS + page parsing
    watches.py         # SPC watch RSS parsing (national list)
    client.py          # SpcClient (conditional GET), SpcApiError, Fetched
    spc.py             # SpcApi, OutlookBundle, AlertBundle
    evaluate.py        # OutlookRisk, AlertRisk, evaluate_outlooks, evaluate_alerts
blueprints/automation/noaa_spc/notify_severe_risk.yaml
tests/
  __init__.py
  conftest.py
  helpers.py           # GeoJSON builders (no integration imports beyond api)
  factories.py         # bundles, watches, MDs, config entries, mock_api support
  api/__init__.py
  api/test_*.py
  test_*.py
  fixtures/live/...    # captured real SPC responses (Task 17)
pyproject.toml
requirements_test.txt
hacs.json
README.md
LICENSE
.gitignore
.github/workflows/ci.yml
```

---

### Task 1: Dev environment and scaffold

**Files:**
- Create: `pyproject.toml`, `requirements_test.txt`, `.gitignore`, `hacs.json`, `LICENSE`, `README.md`, `.github/workflows/ci.yml`
- Create: `custom_components/noaa_spc/__init__.py`, `custom_components/noaa_spc/manifest.json`, `custom_components/noaa_spc/const.py`, `custom_components/noaa_spc/api/__init__.py`
- Create: `tests/__init__.py`, `tests/api/__init__.py`, `tests/conftest.py`
- Test: `tests/test_scaffold.py`

**Interfaces:**
- Produces: `custom_components.noaa_spc.const` constants used by every later task (listed in Step 5).

- [ ] **Step 1: Install uv and create the venv**

Only Python 3.12 is installed system-wide; current Home Assistant needs a newer Python. Install `uv` (`pipx install uv`, or if pipx is missing, the official installer `curl -LsSf https://astral.sh/uv/install.sh | sh` — ask the user before running a remote installer), then:

```bash
uv venv --python 3.13 .venv
```

- [ ] **Step 2: Write `requirements_test.txt` and install**

```
pytest-homeassistant-custom-component
aioresponses>=0.7.8
ruff>=0.9
```

Run: `uv pip install --python .venv -r requirements_test.txt`

If resolution fails because the latest `pytest-homeassistant-custom-component` needs a newer Python, recreate the venv with that version (`uv venv --python 3.14 .venv`), reinstall, and use that version everywhere this plan says `3.13` (pyproject `requires-python`, ruff `target-version`, CI `python-version`).

Then pin the resolved version: run `.venv/bin/python -m pip show pytest-homeassistant-custom-component 2>/dev/null || uv pip show --python .venv pytest-homeassistant-custom-component`, and replace the first line of `requirements_test.txt` with `pytest-homeassistant-custom-component==<that version>`.

- [ ] **Step 3: Write `pyproject.toml`**

```toml
[project]
name = "hassio-noaa-spc"
version = "0.1.0"
description = "Home Assistant integration for NOAA Storm Prediction Center outlooks and mesoscale discussions"
requires-python = ">=3.13"
license = "MIT"
authors = [{ name = "majoragee" }]

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]
pythonpath = ["."]

[tool.ruff]
target-version = "py313"
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]
ignore = ["E501"]  # ruff format owns line length
```

- [ ] **Step 4: Write `.gitignore`, `LICENSE`, `hacs.json`, `README.md`, manifest**

`.gitignore`:
```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
```

`LICENSE`: the standard MIT license text with the line `Copyright (c) 2026 majoragee`.

`hacs.json`:
```json
{
  "name": "NOAA Storm Prediction Center",
  "homeassistant": "2025.1.0",
  "render_readme": true
}
```

`README.md` (expanded in Task 16):
```markdown
# NOAA Storm Prediction Center for Home Assistant

Custom integration exposing SPC convective outlooks, mesoscale discussions and a national watch count.
Work in progress.
```

`custom_components/noaa_spc/manifest.json`:
```json
{
  "domain": "noaa_spc",
  "name": "NOAA Storm Prediction Center",
  "codeowners": ["@majoragee"],
  "config_flow": true,
  "dependencies": [],
  "documentation": "https://github.com/majoragee/hassio-noaa-spc",
  "integration_type": "service",
  "iot_class": "cloud_polling",
  "issue_tracker": "https://github.com/majoragee/hassio-noaa-spc/issues",
  "requirements": [],
  "version": "0.1.0"
}
```

`custom_components/noaa_spc/__init__.py` (replaced in Task 13):
```python
"""The NOAA Storm Prediction Center integration."""
```

`custom_components/noaa_spc/api/__init__.py`:
```python
"""SPC data access. Must not import Home Assistant."""
```

`tests/__init__.py` and `tests/api/__init__.py`: empty files.

- [ ] **Step 5: Write `const.py`**

```python
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
```

- [ ] **Step 6: Write `tests/conftest.py`**

```python
"""Shared pytest fixtures."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow Home Assistant to load custom_components in every test."""
    yield
```

- [ ] **Step 7: Write the scaffold test**

`tests/test_scaffold.py`:
```python
"""Scaffold sanity checks."""

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from custom_components.noaa_spc.const import DOMAIN


async def test_integration_manifest_loads(hass: HomeAssistant) -> None:
    integration = await async_get_integration(hass, DOMAIN)
    assert integration.domain == "noaa_spc"
    assert integration.config_flow is True
    assert integration.requirements == []
```

- [ ] **Step 8: Run tests and lint**

Run: `.venv/bin/pytest tests/test_scaffold.py -v` — Expected: 1 passed.
Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check .` — Expected: no errors (run `.venv/bin/ruff format .` first if formatting differs).

- [ ] **Step 9: Write CI workflow**

`.github/workflows/ci.yml`:
```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: pip install -r requirements_test.txt
      - run: ruff check .
      - run: ruff format --check .
      - run: pytest

  hassfest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: home-assistant/actions/hassfest@master

  hacs:
    runs-on: ubuntu-latest
    steps:
      - uses: hacs/action@main
        with:
          category: integration
          ignore: brands
```

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "Scaffold noaa_spc custom integration and dev tooling"
```

---

### Task 2: Models and geometry

**Files:**
- Create: `custom_components/noaa_spc/api/models.py`, `custom_components/noaa_spc/api/geometry.py`
- Test: `tests/api/test_models.py`, `tests/api/test_geometry.py`

**Interfaces:**
- Produces:
  - `Ring = tuple[tuple[float, float], ...]` — `(lon, lat)` pairs; `Polygon = tuple[Ring, ...]` — outer ring first, then holes.
  - `RiskLevel(IntEnum)`: `NONE=0, TSTM=1, MRGL=2, SLGT=3, ENH=4, MDT=5, HIGH=6`; `RiskLevel.from_label(str) -> RiskLevel | None`; properties `.state -> str` (`"none"` or the name) and `.description -> str`.
  - `RISK_STATES: list[str]` = `["none", "TSTM", "MRGL", "SLGT", "ENH", "MDT", "HIGH"]`.
  - Frozen dataclasses `OutlookArea(label, polygons)`, `OutlookLayer(areas, issued, valid, expire, forecaster, predictability_too_low=False)`, `TextProduct(text, summary, forecaster)`, `MesoscaleDiscussion(number, areas_affected, concerning, watch_probability, summary, polygon, url)`, `Watch(number, kind, pds, url)`.
  - `point_in_polygon(lon, lat, polygon) -> bool`, `point_in_any(lon, lat, polygons) -> bool`.

- [ ] **Step 1: Write failing tests**

`tests/api/test_models.py`:
```python
from custom_components.noaa_spc.api.models import RISK_STATES, RiskLevel


def test_from_label_parses_known_labels_case_insensitively() -> None:
    assert RiskLevel.from_label("SLGT") is RiskLevel.SLGT
    assert RiskLevel.from_label(" enh ") is RiskLevel.ENH


def test_from_label_returns_none_for_unknown() -> None:
    assert RiskLevel.from_label("0.05") is None
    assert RiskLevel.from_label("") is None


def test_ordering_and_state() -> None:
    assert RiskLevel.HIGH > RiskLevel.MDT > RiskLevel.ENH > RiskLevel.SLGT
    assert RiskLevel.NONE.state == "none"
    assert RiskLevel.MRGL.state == "MRGL"
    assert RiskLevel.ENH.description == "Enhanced Risk"


def test_risk_states_in_level_order() -> None:
    assert RISK_STATES == ["none", "TSTM", "MRGL", "SLGT", "ENH", "MDT", "HIGH"]
```

`tests/api/test_geometry.py`:
```python
from custom_components.noaa_spc.api.geometry import point_in_any, point_in_polygon

SQUARE = (((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)),)
HOLE = ((4.0, 4.0), (6.0, 4.0), (6.0, 6.0), (4.0, 6.0), (4.0, 4.0))
L_SHAPE = (
    ((0.0, 0.0), (10.0, 0.0), (10.0, 2.0), (2.0, 2.0), (2.0, 10.0), (0.0, 10.0),
     (0.0, 0.0)),
)


def test_inside_and_outside_square() -> None:
    assert point_in_polygon(5.0, 5.0, SQUARE)
    assert not point_in_polygon(15.0, 5.0, SQUARE)
    assert not point_in_polygon(5.0, -1.0, SQUARE)


def test_hole_excludes_point() -> None:
    donut = (SQUARE[0], HOLE)
    assert not point_in_polygon(5.0, 5.0, donut)
    assert point_in_polygon(1.0, 1.0, donut)


def test_concave_polygon() -> None:
    assert point_in_polygon(1.0, 9.0, L_SHAPE)
    assert not point_in_polygon(6.0, 6.0, L_SHAPE)


def test_empty_polygon_is_never_inside() -> None:
    assert not point_in_polygon(0.0, 0.0, ())


def test_vertex_does_not_raise() -> None:
    point_in_polygon(0.0, 0.0, SQUARE)
    point_in_polygon(10.0, 10.0, SQUARE)


def test_point_in_any_multipolygon() -> None:
    far = (((20.0, 20.0), (30.0, 20.0), (30.0, 30.0), (20.0, 30.0), (20.0, 20.0)),)
    assert point_in_any(25.0, 25.0, (SQUARE, far))
    assert not point_in_any(15.0, 15.0, (SQUARE, far))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/api/test_models.py tests/api/test_geometry.py -v`
Expected: FAIL / collection error — `ModuleNotFoundError: No module named 'custom_components.noaa_spc.api.models'`.

- [ ] **Step 3: Implement `models.py`**

```python
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
```

- [ ] **Step 4: Implement `geometry.py`**

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/api -v` — Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add custom_components/noaa_spc/api tests/api
git commit -m "Add SPC data models and point-in-polygon geometry"
```

---

### Task 3: Product catalog and outlook layer parsing

**Files:**
- Create: `custom_components/noaa_spc/api/products.py`, `custom_components/noaa_spc/api/outlooks.py`, `tests/helpers.py`
- Test: `tests/api/test_outlooks.py`

**Interfaces:**
- Consumes: Task 2 models, geometry.
- Produces:
  - `products.py`: `SPC_BASE`, `USER_AGENT`, `LAYER_PATHS: dict[str, str]` (keys `day{1,2}_cat`, `day{1,2}_{torn,wind,hail}`, `day{1,2}_sig{torn,wind,hail}`, `day3_cat`, `day3_prob`, `day3_sigprob`, `day{4..8}_prob`), `TEXT_PATHS: dict[str, str]` (keys `day1`, `day2`, `day3`, `day48`), `IMAGE_PATHS: dict[str, tuple[str, str]]` (key → (path, content type); keys `day1`, `day2`, `day3`, `day{1,2}_{torn,wind,hail}`, `day48`), `MD_FEED_PATH`, `WATCH_FEED_PATH`, `watch_url(number) -> str`, `in_conus(lat, lon) -> bool`.
  - `outlooks.py`: `OutlookParseError(ValueError)`, `parse_layer(data) -> OutlookLayer`, `categorical_at(layer, lat, lon) -> RiskLevel`, `parse_percent(label) -> int | None`, `probability_at(layer, lat, lon) -> int`, `any_area_at(layer, lat, lon) -> bool`.
  - `tests/helpers.py`: `ISSUE`, `VALID`, `EXPIRE`, `HOME`, `FAR`, `square(lat, lon, half=1.0)`, `feature(label, *rings, dn=1, forecaster="Smith")`, `empty_feature(label="")`, `collection(*features)`.

- [ ] **Step 1: Write `tests/helpers.py`**

```python
"""GeoJSON builders for tests."""

from __future__ import annotations

from typing import Any

ISSUE = "2026-10-13T12:52:00+00:00"
VALID = "2026-10-13T13:00:00+00:00"
EXPIRE = "2026-10-14T12:00:00+00:00"
HOME = (35.22, -97.44)  # Norman, OK
FAR = (44.0, -110.0)  # Wyoming, outside every test area


def square(lat: float, lon: float, half: float = 1.0) -> list[list[float]]:
    return [
        [lon - half, lat - half],
        [lon + half, lat - half],
        [lon + half, lat + half],
        [lon - half, lat + half],
        [lon - half, lat - half],
    ]


def feature(
    label: str, *rings: list[list[float]], dn: int = 1, forecaster: str = "Smith"
) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": {"type": "MultiPolygon", "coordinates": [[r] for r in rings]},
        "properties": {
            "DN": dn,
            "LABEL": label,
            "LABEL2": "",
            "ISSUE_ISO": ISSUE,
            "VALID_ISO": VALID,
            "EXPIRE_ISO": EXPIRE,
            "FORECASTER": forecaster,
        },
    }


def empty_feature(label: str = "") -> dict[str, Any]:
    """An SPC 'no areas' feature: DN 0, empty geometry, stale timestamps."""
    return {
        "type": "Feature",
        "geometry": {"type": "GeometryCollection", "geometries": []},
        "properties": {
            "DN": 0,
            "LABEL": label,
            "LABEL2": "",
            "ISSUE_ISO": "2026-03-03T12:48:00+00:00",
            "VALID_ISO": "2026-03-03T13:00:00+00:00",
            "EXPIRE_ISO": "2026-03-04T12:00:00+00:00",
            "FORECASTER": "Old",
        },
    }


def collection(*features: dict[str, Any]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": list(features) or [empty_feature()]}
```

- [ ] **Step 2: Write failing tests**

`tests/api/test_outlooks.py`:
```python
from datetime import UTC, datetime

import pytest

from custom_components.noaa_spc.api.models import RiskLevel
from custom_components.noaa_spc.api.outlooks import (
    OutlookParseError,
    any_area_at,
    categorical_at,
    parse_layer,
    parse_percent,
    probability_at,
)
from custom_components.noaa_spc.api.products import (
    IMAGE_PATHS,
    LAYER_PATHS,
    TEXT_PATHS,
    in_conus,
)
from tests.helpers import FAR, HOME, collection, empty_feature, feature, square


def test_parse_layer_metadata_and_areas() -> None:
    layer = parse_layer(collection(feature("SLGT", square(*HOME), forecaster="Mosier")))
    assert layer.issued == datetime(2026, 10, 13, 12, 52, tzinfo=UTC)
    assert layer.valid == datetime(2026, 10, 13, 13, 0, tzinfo=UTC)
    assert layer.expire == datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
    assert layer.forecaster == "Mosier"
    assert [a.label for a in layer.areas] == ["SLGT"]
    assert layer.predictability_too_low is False


def test_nested_categorical_returns_highest_containing_level() -> None:
    layer = parse_layer(
        collection(
            feature("TSTM", square(*HOME, half=5.0)),
            feature("MRGL", square(*HOME, half=3.0)),
            feature("ENH", square(*HOME, half=1.0)),
        )
    )
    assert categorical_at(layer, *HOME) is RiskLevel.ENH
    assert categorical_at(layer, HOME[0] + 2.0, HOME[1]) is RiskLevel.MRGL
    assert categorical_at(layer, *FAR) is RiskLevel.NONE


def test_empty_layer_is_no_risk_not_error() -> None:
    layer = parse_layer(collection(empty_feature()))
    assert layer.areas == ()
    assert categorical_at(layer, *HOME) is RiskLevel.NONE
    assert probability_at(layer, *HOME) == 0


def test_predictability_too_low_flag() -> None:
    layer = parse_layer(collection(empty_feature("Predictability Too Low")))
    assert layer.predictability_too_low is True
    assert layer.areas == ()


def test_polygon_geometry_type_supported() -> None:
    data = collection(feature("SLGT", square(*HOME)))
    data["features"][0]["geometry"] = {"type": "Polygon", "coordinates": [square(*HOME)]}
    assert categorical_at(parse_layer(data), *HOME) is RiskLevel.SLGT


def test_probability_takes_max_and_ignores_sign_labels() -> None:
    layer = parse_layer(
        collection(
            feature("0.02", square(*HOME, half=4.0)),
            feature("0.10", square(*HOME, half=1.0)),
            feature("SIGN", square(*HOME, half=1.0)),
        )
    )
    assert probability_at(layer, *HOME) == 10
    assert probability_at(layer, HOME[0] + 3.0, HOME[1]) == 2


def test_any_area_at_for_significant_layers() -> None:
    layer = parse_layer(collection(feature("SIGN", square(*HOME))))
    assert any_area_at(layer, *HOME)
    assert not any_area_at(layer, *FAR)


@pytest.mark.parametrize(
    ("label", "expected"),
    [("0.05", 5), ("0.15", 15), ("0.30", 30), ("SIGN", None), ("", None), ("1.5", None)],
)
def test_parse_percent(label: str, expected: int | None) -> None:
    assert parse_percent(label) == expected


@pytest.mark.parametrize(
    "data",
    [None, [], {"type": "Feature"}, {"type": "FeatureCollection", "features": "x"}],
)
def test_parse_layer_rejects_malformed(data: object) -> None:
    with pytest.raises(OutlookParseError):
        parse_layer(data)


def test_parse_layer_rejects_bad_coordinates() -> None:
    data = collection(feature("SLGT", square(*HOME)))
    data["features"][0]["geometry"]["coordinates"] = [[["x"]]]
    with pytest.raises(OutlookParseError):
        parse_layer(data)


def test_product_catalog() -> None:
    assert LAYER_PATHS["day1_cat"] == "outlook/day1otlk_cat.lyr.geojson"
    assert LAYER_PATHS["day2_sighail"] == "outlook/day2otlk_sighail.lyr.geojson"
    assert LAYER_PATHS["day3_sigprob"] == "outlook/day3otlk_sigprob.lyr.geojson"
    assert LAYER_PATHS["day8_prob"] == "exper/day4-8/day8prob.lyr.geojson"
    assert len(LAYER_PATHS) == 22
    assert set(TEXT_PATHS) == {"day1", "day2", "day3", "day48"}
    assert IMAGE_PATHS["day1_torn"] == ("outlook/day1probotlk_torn.png", "image/png")
    assert IMAGE_PATHS["day48"] == ("exper/day4-8/day48prob.gif", "image/gif")
    assert len(IMAGE_PATHS) == 10


def test_in_conus() -> None:
    assert in_conus(*HOME)
    assert not in_conus(51.5, -0.12)
    assert not in_conus(61.2, -149.9)  # Anchorage
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/api/test_outlooks.py -v`
Expected: collection error — `No module named 'custom_components.noaa_spc.api.outlooks'`.

- [ ] **Step 4: Implement `products.py`**

```python
"""SPC product catalog. Must not import Home Assistant."""

from __future__ import annotations

SPC_BASE = "https://www.spc.noaa.gov/products/"
USER_AGENT = "hassio-noaa-spc/0.1.0 (https://github.com/majoragee/hassio-noaa-spc)"

HAZARDS = ("torn", "wind", "hail")

LAYER_PATHS: dict[str, str] = {}
for _day in (1, 2):
    LAYER_PATHS[f"day{_day}_cat"] = f"outlook/day{_day}otlk_cat.lyr.geojson"
    for _hazard in HAZARDS:
        LAYER_PATHS[f"day{_day}_{_hazard}"] = (
            f"outlook/day{_day}otlk_{_hazard}.lyr.geojson"
        )
        LAYER_PATHS[f"day{_day}_sig{_hazard}"] = (
            f"outlook/day{_day}otlk_sig{_hazard}.lyr.geojson"
        )
LAYER_PATHS["day3_cat"] = "outlook/day3otlk_cat.lyr.geojson"
LAYER_PATHS["day3_prob"] = "outlook/day3otlk_prob.lyr.geojson"
LAYER_PATHS["day3_sigprob"] = "outlook/day3otlk_sigprob.lyr.geojson"
for _day in range(4, 9):
    LAYER_PATHS[f"day{_day}_prob"] = f"exper/day4-8/day{_day}prob.lyr.geojson"

TEXT_PATHS: dict[str, str] = {
    "day1": "outlook/day1otlk.txt",
    "day2": "outlook/day2otlk.txt",
    "day3": "outlook/day3otlk.txt",
    "day48": "exper/day4-8/",
}

IMAGE_PATHS: dict[str, tuple[str, str]] = {
    "day1": ("outlook/day1otlk.png", "image/png"),
    "day2": ("outlook/day2otlk.png", "image/png"),
    "day3": ("outlook/day3otlk.png", "image/png"),
    **{
        f"day{_day}_{_hazard}": (
            f"outlook/day{_day}probotlk_{_hazard}.png",
            "image/png",
        )
        for _day in (1, 2)
        for _hazard in HAZARDS
    },
    "day48": ("exper/day4-8/day48prob.gif", "image/gif"),
}

MD_FEED_PATH = "spcmdrss.xml"
WATCH_FEED_PATH = "spcwwrss.xml"


def watch_url(number: int) -> str:
    return f"{SPC_BASE}watch/ww{number:04d}.html"


def in_conus(lat: float, lon: float) -> bool:
    """Rough bounding box of SPC outlook coverage (contiguous US)."""
    return 24.0 <= lat <= 50.0 and -125.0 <= lon <= -66.0
```

- [ ] **Step 5: Implement `outlooks.py`**

```python
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
        if percent is not None and percent > best and point_in_any(lon, lat, area.polygons):
            best = percent
    return best


def any_area_at(layer: OutlookLayer, lat: float, lon: float) -> bool:
    return any(point_in_any(lon, lat, area.polygons) for area in layer.areas)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/api -v` — Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add custom_components/noaa_spc/api tests/helpers.py tests/api
git commit -m "Add SPC product catalog and outlook layer parsing"
```

---

### Task 4: Outlook discussion text parsing

**Files:**
- Create: `custom_components/noaa_spc/api/text.py`
- Test: `tests/api/test_text.py`

**Interfaces:**
- Consumes: `TextProduct` (Task 2).
- Produces: `TextParseError(ValueError)`, `extract_pre(raw: str) -> str`, `first_paragraph_after(text: str, marker: str) -> str | None`, `parse_text_product(raw: str) -> TextProduct`. `extract_pre` and `first_paragraph_after` are reused by `mds.py` (Task 5).

- [ ] **Step 1: Write failing tests**

`tests/api/test_text.py`:
```python
import pytest

from custom_components.noaa_spc.api.text import (
    TextParseError,
    first_paragraph_after,
    parse_text_product,
)

DAY1 = """ZCZC SPCSWODY1 ALL
ACUS01 KWNS 131252
SPC AC 131252

Day 1 Convective Outlook
NWS Storm Prediction Center Norman OK
0752 AM CDT Tue Oct 13 2026

Valid 131300Z - 141200Z

...THERE IS A SLIGHT RISK OF SEVERE THUNDERSTORMS FROM PARTS OF
NORTHWEST MISSOURI/KANSAS INTO THE SOUTHERN HIGH PLAINS...

...SUMMARY...
Widely scattered severe storms capable of large hail, damaging
winds, and possibly a tornado are expected.

...Southern High Plains...
Early morning satellite imagery shows a belt of flow.

..Mosier/Wendt.. 10/13/2026

$$
"""

DAY48_HTML = """<html><body><pre>

   ZCZC SPCSWOD48 ALL
   ACUS48 KWNS 130830

   Day 4-8 Convective Outlook
   NWS Storm Prediction Center Norman OK

   ...DISCUSSION...
   ...Day 4/Friday...

   An intense midlevel trough will progress from the Great Lakes &amp; beyond
   by Saturday morning.

   ...Days 5 through 8/Saturday through Tuesday...

   A considerably drier air mass will persist.

   ..Mead.. 10/13/2026

   CLICK TO GET <a href="/x.txt">WUUS48 PTSD48</a> PRODUCT

</pre></body></html>"""


def test_day1_text() -> None:
    product = parse_text_product(DAY1)
    assert product.summary == (
        "Widely scattered severe storms capable of large hail, damaging "
        "winds, and possibly a tornado are expected."
    )
    assert product.forecaster == "Mosier/Wendt"
    assert "ZCZC" not in product.text
    assert "$$" not in product.text
    assert product.text.startswith("ACUS01 KWNS 131252")


def test_day48_html_falls_back_to_discussion_paragraph() -> None:
    product = parse_text_product(DAY48_HTML)
    assert product.summary == (
        "An intense midlevel trough will progress from the Great Lakes & beyond "
        "by Saturday morning."
    )
    assert product.forecaster == "Mead"
    assert "CLICK TO GET" not in product.text
    assert "<a" not in product.text
    assert product.text.startswith("ACUS48 KWNS 130830")


def test_first_paragraph_after_missing_marker() -> None:
    assert first_paragraph_after("nothing here", "...SUMMARY...") is None


def test_empty_text_rejected() -> None:
    with pytest.raises(TextParseError):
        parse_text_product("<pre>\n\n</pre>")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/api/test_text.py -v`
Expected: collection error — `No module named 'custom_components.noaa_spc.api.text'`.

- [ ] **Step 3: Implement `text.py`**

```python
"""SPC text product parsing. Must not import Home Assistant."""

from __future__ import annotations

import html
import re
import textwrap

from .models import TextProduct

_PRE_RE = re.compile(r"<pre[^>]*>(.*?)</pre>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_DROP_RE = re.compile(r"^(ZCZC|\$\$|CLICK TO GET)", re.I)
_FORECASTER_RE = re.compile(r"^\.\.(.+?)\.\.\s+\d{2}/\d{2}/\d{4}\s*$", re.M)
_PARAGRAPH_RE = re.compile(r"\n\s*\n")


class TextParseError(ValueError):
    """Raised when a text product has no usable content."""


def extract_pre(raw: str) -> str:
    """Return the <pre> body of an HTML page (or the raw text), dedented."""
    match = _PRE_RE.search(raw)
    body = match.group(1) if match else raw
    body = html.unescape(_TAG_RE.sub("", body)).replace("\r\n", "\n")
    return textwrap.dedent(body)


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in _PARAGRAPH_RE.split(text) if p.strip()]


def _join_lines(paragraph: str) -> str:
    return " ".join(line.strip() for line in paragraph.splitlines())


def first_paragraph_after(text: str, marker: str) -> str | None:
    """First paragraph after `marker`, skipping '...Heading...' paragraphs."""
    index = text.find(marker)
    if index < 0:
        return None
    for paragraph in _paragraphs(text[index + len(marker) :]):
        if paragraph.startswith("..."):
            continue
        return _join_lines(paragraph)
    return None


def parse_text_product(raw: str) -> TextProduct:
    lines = [
        line.rstrip()
        for line in extract_pre(raw).splitlines()
        if not _DROP_RE.match(line.strip())
    ]
    text = "\n".join(lines).strip()
    if not text:
        raise TextParseError("empty text product")
    summary = first_paragraph_after(text, "...SUMMARY...") or first_paragraph_after(
        text, "...DISCUSSION..."
    )
    forecaster = _FORECASTER_RE.search(text)
    return TextProduct(
        text=text,
        summary=summary,
        forecaster=forecaster.group(1) if forecaster else None,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/api/test_text.py -v` — Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/noaa_spc/api/text.py tests/api/test_text.py
git commit -m "Parse SPC outlook discussion text"
```

---

### Task 5: Mesoscale discussion parsing

**Files:**
- Create: `custom_components/noaa_spc/api/mds.py`
- Test: `tests/api/test_mds.py`

**Interfaces:**
- Consumes: `extract_pre`, `first_paragraph_after` (Task 4); `MesoscaleDiscussion` (Task 2).
- Produces: `MdParseError(ValueError)`, `parse_md_feed(xml: bytes | str) -> list[tuple[int, str]]` (number, absolute URL), `decode_latlon(token: str) -> tuple[float, float]` (returns `(lon, lat)`), `parse_md_page(raw: str, url: str) -> MesoscaleDiscussion`.

- [ ] **Step 1: Write failing tests**

`tests/api/test_mds.py`:
```python
import pytest

from custom_components.noaa_spc.api.geometry import point_in_polygon
from custom_components.noaa_spc.api.mds import (
    MdParseError,
    decode_latlon,
    parse_md_feed,
    parse_md_page,
)

MD_HTML = """<html><body><pre>

   Mesoscale Discussion 2104
   NWS Storm Prediction Center Norman OK
   0431 PM CDT Sun Aug 23 2026

   Areas affected...portions of central and eastern Montana

   Concerning...Severe potential...Watch likely 

   Valid 232131Z - 232230Z

   Probability of Watch Issuance...80 percent

   SUMMARY...Widely scattered thunderstorms (including some supercells)
   will continue eastward. A downstream Watch is likely needed.

   DISCUSSION...As of 2130 UTC, widely scattered thunderstorms were
   ongoing across central MT.

   ..Lyons/Thompson.. 08/23/2026

   LAT...LON   49050884 49250603 49060504 48710487 48380473 47470496
               46050568 45270625 44940708 44760872 44920911 45330913
               46040889 48020883 49050884 

   MOST PROBABLE PEAK WIND GUST...65-80 MPH

</pre></body></html>"""

URL = "https://www.spc.noaa.gov/products/md/md2104.html"


def _feed(*links: str) -> str:
    items = "".join(
        f"<item><link>{link}</link><title>SPC MD</title></item>" for link in links
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'


def test_decode_latlon_adds_100_to_western_longitudes() -> None:
    assert decode_latlon("49050884") == (-108.84, 49.05)
    assert decode_latlon("35229744") == (-97.44, 35.22)
    assert decode_latlon("30008000") == (-80.0, 30.0)


def test_parse_md_page() -> None:
    md = parse_md_page(MD_HTML, URL)
    assert md.number == 2104
    assert md.areas_affected == "portions of central and eastern Montana"
    assert md.concerning == "Severe potential...Watch likely"
    assert md.watch_probability == 80
    assert md.summary == (
        "Widely scattered thunderstorms (including some supercells) "
        "will continue eastward. A downstream Watch is likely needed."
    )
    assert md.url == URL
    assert len(md.polygon[0]) == 13
    assert point_in_polygon(-107.0, 47.0, md.polygon)
    assert not point_in_polygon(-97.44, 35.22, md.polygon)


def test_parse_md_page_without_watch_probability() -> None:
    raw = MD_HTML.replace("   Probability of Watch Issuance...80 percent\n", "")
    assert parse_md_page(raw, URL).watch_probability is None


def test_parse_md_page_without_polygon_rejected() -> None:
    raw = MD_HTML.split("LAT...LON")[0] + "</pre>"
    with pytest.raises(MdParseError):
        parse_md_page(raw, URL)


def test_feed_accepts_both_link_styles_and_dedupes() -> None:
    feed = _feed(
        "https://www.spc.noaa.gov/products/md/md2104.html",
        "https://www.spc.noaa.gov/products/md/2026/md2105.html",
        "https://www.spc.noaa.gov/products/md/md2104.html",
    )
    assert parse_md_feed(feed) == [
        (2104, "https://www.spc.noaa.gov/products/md/md2104.html"),
        (2105, "https://www.spc.noaa.gov/products/md/2026/md2105.html"),
    ]


def test_feed_with_no_mds() -> None:
    feed = _feed("https://www.spc.noaa.gov/products/md/")
    assert parse_md_feed(feed) == []


def test_feed_malformed_xml_rejected() -> None:
    with pytest.raises(MdParseError):
        parse_md_feed(b"<rss><channel>")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/api/test_mds.py -v`
Expected: collection error — `No module named 'custom_components.noaa_spc.api.mds'`.

- [ ] **Step 3: Implement `mds.py`**

```python
"""SPC mesoscale discussion feed and page parsing. Must not import Home Assistant."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .models import MesoscaleDiscussion
from .text import extract_pre, first_paragraph_after

_LINK_RE = re.compile(r"/md/(?:\d{4}/)?md(\d{4})\.html")
_NUMBER_RE = re.compile(r"Mesoscale Discussion (\d+)")
_AREAS_RE = re.compile(r"Areas affected\.\.\.(.+?)\n\s*\n", re.S)
_CONCERNING_RE = re.compile(r"Concerning\.\.\.(.+)")
_PROBABILITY_RE = re.compile(r"Probability of Watch Issuance\.\.\.(\d+) percent")
_LATLON_RE = re.compile(r"LAT\.\.\.LON\s+((?:\d{8}\s*)+)")


class MdParseError(ValueError):
    """Raised when an MD feed or page cannot be parsed."""


def parse_md_feed(xml: bytes | str) -> list[tuple[int, str]]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as err:
        raise MdParseError(f"invalid MD feed XML: {err}") from err
    found: list[tuple[int, str]] = []
    seen: set[int] = set()
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        match = _LINK_RE.search(link)
        if match and (number := int(match.group(1))) not in seen:
            seen.add(number)
            found.append((number, link))
    return found


def decode_latlon(token: str) -> tuple[float, float]:
    """Decode an SPC 'LLLLOOOO' token to (lon, lat); longitudes are west."""
    lat = int(token[:4]) / 100
    lon = int(token[4:]) / 100
    if lon < 50:
        lon += 100
    return (-round(lon, 2), lat)


def _join(value: str) -> str:
    return " ".join(value.split())


def parse_md_page(raw: str, url: str) -> MesoscaleDiscussion:
    text = extract_pre(raw)
    number = _NUMBER_RE.search(text)
    latlon = _LATLON_RE.search(text)
    if number is None or latlon is None:
        raise MdParseError("MD number or LAT...LON block missing")
    ring = tuple(decode_latlon(token) for token in latlon.group(1).split())
    if len(ring) < 3:
        raise MdParseError("MD polygon has fewer than 3 points")
    if ring[0] != ring[-1]:
        ring = (*ring, ring[0])
    areas = _AREAS_RE.search(text)
    concerning = _CONCERNING_RE.search(text)
    probability = _PROBABILITY_RE.search(text)
    return MesoscaleDiscussion(
        number=int(number.group(1)),
        areas_affected=_join(areas.group(1)) if areas else None,
        concerning=concerning.group(1).strip() if concerning else None,
        watch_probability=int(probability.group(1)) if probability else None,
        summary=first_paragraph_after(text, "SUMMARY..."),
        polygon=(ring,),
        url=url,
    )
```

Note: `13` points in the test is correct — the sample's 13th token repeats the first, so no extra closing point is added.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/api/test_mds.py -v` — Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/noaa_spc/api/mds.py tests/api/test_mds.py
git commit -m "Parse SPC mesoscale discussion feed and pages"
```

---

### Task 6: SPC watch feed parsing (national list)

**Files:**
- Create: `custom_components/noaa_spc/api/watches.py`
- Test: `tests/api/test_watches.py`

**Interfaces:**
- Consumes: `Watch` (Task 2).
- Produces: `WatchParseError(ValueError)`, `parse_watch_feed(xml: bytes | str) -> tuple[Watch, ...]` (one per distinct watch number, sorted by number).

Context: watches are national only — a pulse check of how active the day is. There is no per-location watch matching anywhere in this integration (a separate NWS weather integration owns that). The source is SPC's own RSS feed `https://www.spc.noaa.gov/products/spcwwrss.xml`. When nothing is active it carries a single placeholder item whose link is `https://www.spc.noaa.gov/products/watch/` and whose title reads `SPC - No watches are valid as of …` (verified 2026-10-13). Active-watch items link to `watch/wwNNNN.html` (watch pages are titled e.g. `Severe Thunderstorm Watch 150`); the exact item titles have not been observed live, so the parser keys off the link and only uses title/description text for type and PDS, merging every item that mentions the same watch number.

- [ ] **Step 1: Write failing tests**

`tests/api/test_watches.py`:
```python
import pytest

from custom_components.noaa_spc.api.watches import WatchParseError, parse_watch_feed

PLACEHOLDER = (
    "<item><link>https://www.spc.noaa.gov/products/watch/</link>"
    "<title>SPC - No watches are valid as of Sun Oct 11 22:31:02 UTC 2026</title>"
    "<description>No watches are valid as of Sun Oct 11 22:31:02 UTC 2026.</description>"
    "</item>"
)


def _item(link: str, title: str, description: str = "") -> str:
    return (
        f"<item><link>{link}</link><title>{title}</title>"
        f"<description>{description}</description></item>"
    )


def _feed(*items: str) -> str:
    return (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        + "".join(items)
        + "</channel></rss>"
    )


def test_placeholder_feed_has_no_watches() -> None:
    assert parse_watch_feed(_feed(PLACEHOLDER)) == ()


def test_watches_parsed_sorted_with_type() -> None:
    feed = _feed(
        _item(
            "https://www.spc.noaa.gov/products/watch/ww0613.html",
            "SPC Severe Thunderstorm Watch 613",
        ),
        _item("https://www.spc.noaa.gov/products/watch/ww0612.html", "SPC Tornado Watch 612"),
    )
    watches = parse_watch_feed(feed)
    assert [(w.number, w.kind, w.pds) for w in watches] == [
        (612, "tornado", False),
        (613, "severe_thunderstorm", False),
    ]
    assert watches[0].url == "https://www.spc.noaa.gov/products/watch/ww0612.html"


def test_duplicate_and_status_items_merge_into_one_watch() -> None:
    feed = _feed(
        _item("https://www.spc.noaa.gov/products/watch/ww0612.html", "SPC Tornado Watch 612"),
        _item(
            "https://www.spc.noaa.gov/products/watch/2026/ww0612_status.html",
            "SPC Watch 612 Status Report",
        ),
        _item("https://www.spc.noaa.gov/products/watch/ww0612.html", "SPC Tornado Watch 612"),
    )
    (watch,) = parse_watch_feed(feed)
    assert watch.number == 612
    assert watch.kind == "tornado"
    assert watch.url == "https://www.spc.noaa.gov/products/watch/ww0612.html"


@pytest.mark.parametrize(
    ("title", "description"),
    [
        ("SPC PDS Tornado Watch 612", ""),
        ("SPC Tornado Watch 612", "THIS IS A PARTICULARLY DANGEROUS SITUATION"),
    ],
)
def test_pds_detected(title: str, description: str) -> None:
    feed = _feed(
        _item("https://www.spc.noaa.gov/products/watch/ww0612.html", title, description)
    )
    assert parse_watch_feed(feed)[0].pds is True


def test_malformed_feed_rejected() -> None:
    with pytest.raises(WatchParseError):
        parse_watch_feed(b"<rss><channel>")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/api/test_watches.py -v`
Expected: collection error — `No module named 'custom_components.noaa_spc.api.watches'`.

- [ ] **Step 3: Implement `watches.py`**

```python
"""SPC watch RSS feed parsing (national list). Must not import Home Assistant."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from .models import Watch

_LINK_RE = re.compile(r"/watch/(?:\d{4}/)?ww(\d{4})")
_PAGE_RE = re.compile(r"/watch/(?:\d{4}/)?ww\d{4}\.html$")
_PDS_RE = re.compile(r"\bPDS\b|PARTICULARLY DANGEROUS SITUATION")


class WatchParseError(ValueError):
    """Raised when the SPC watch feed cannot be parsed."""


@dataclass
class _Group:
    url: str
    tornado: bool = False
    pds: bool = False


def parse_watch_feed(xml: bytes | str) -> tuple[Watch, ...]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as err:
        raise WatchParseError(f"invalid watch feed XML: {err}") from err
    groups: dict[int, _Group] = {}
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        match = _LINK_RE.search(link)
        if match is None:
            continue
        number = int(match.group(1))
        group = groups.setdefault(number, _Group(url=link))
        if _PAGE_RE.search(link) and not _PAGE_RE.search(group.url):
            group.url = link
        text = f"{item.findtext('title') or ''} {item.findtext('description') or ''}"
        upper = text.upper()
        group.tornado = group.tornado or "TORNADO" in upper
        group.pds = group.pds or bool(_PDS_RE.search(upper))
    return tuple(
        Watch(
            number=number,
            kind="tornado" if group.tornado else "severe_thunderstorm",
            pds=group.pds,
            url=group.url,
        )
        for number, group in sorted(groups.items())
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/api/test_watches.py -v` — Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/noaa_spc/api/watches.py tests/api/test_watches.py
git commit -m "Parse SPC watch feed into a national watch list"
```

---

### Task 7: HTTP client with conditional GET

**Files:**
- Create: `custom_components/noaa_spc/api/client.py`
- Test: `tests/api/test_client.py`

**Interfaces:**
- Consumes: `USER_AGENT` (Task 3).
- Produces: `SpcApiError(Exception)` with `.status: int | None`; `Fetched(body: bytes, changed: bool)`; `SpcClient(session: aiohttp.ClientSession, *, timeout: float = 30.0)` with `async fetch(url: str, *, accept: str | None = None, conditional: bool = True) -> Fetched`.

- [ ] **Step 1: Write failing tests**

`tests/api/test_client.py`:
```python
import aiohttp
import pytest
from aioresponses import aioresponses
from yarl import URL

from custom_components.noaa_spc.api.client import SpcApiError, SpcClient
from custom_components.noaa_spc.api.products import USER_AGENT

URL_A = "https://www.spc.noaa.gov/products/outlook/day1otlk_cat.lyr.geojson"


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as session:
        yield session


def _sent_headers(mock: aioresponses, url: str, index: int) -> dict:
    return mock.requests[("GET", URL(url))][index].kwargs["headers"]


async def test_first_fetch_then_304_returns_cached_body(session) -> None:
    client = SpcClient(session)
    with aioresponses() as mock:
        mock.get(URL_A, status=200, body=b"one", headers={"ETag": '"abc"',
                 "Last-Modified": "Tue, 13 Oct 2026 12:56:15 GMT"})
        mock.get(URL_A, status=304)
        first = await client.fetch(URL_A)
        second = await client.fetch(URL_A)
        assert _sent_headers(mock, URL_A, 0)["User-Agent"] == USER_AGENT
        assert "If-None-Match" not in _sent_headers(mock, URL_A, 0)
        assert _sent_headers(mock, URL_A, 1)["If-None-Match"] == '"abc"'
        assert _sent_headers(mock, URL_A, 1)["If-Modified-Since"] == (
            "Tue, 13 Oct 2026 12:56:15 GMT"
        )
    assert (first.body, first.changed) == (b"one", True)
    assert (second.body, second.changed) == (b"one", False)


async def test_200_with_identical_body_is_unchanged(session) -> None:
    client = SpcClient(session)
    with aioresponses() as mock:
        mock.get(URL_A, status=200, body=b"same", headers={"ETag": '"1"'})
        mock.get(URL_A, status=200, body=b"same", headers={"ETag": '"2"'})
        await client.fetch(URL_A)
        again = await client.fetch(URL_A)
    assert again.changed is False


async def test_non_conditional_fetch_sends_no_validators(session) -> None:
    client = SpcClient(session)
    with aioresponses() as mock:
        mock.get(URL_A, status=200, body=b"x", headers={"ETag": '"1"'}, repeat=True)
        await client.fetch(URL_A, conditional=False, accept="application/geo+json")
        await client.fetch(URL_A, conditional=False)
        headers = _sent_headers(mock, URL_A, 1)
        assert "If-None-Match" not in headers
        assert _sent_headers(mock, URL_A, 0)["Accept"] == "application/geo+json"


async def test_http_error_raises_with_status(session) -> None:
    client = SpcClient(session)
    with aioresponses() as mock:
        mock.get(URL_A, status=404)
        with pytest.raises(SpcApiError) as err:
            await client.fetch(URL_A)
    assert err.value.status == 404


@pytest.mark.parametrize("exc", [aiohttp.ClientConnectionError(), TimeoutError()])
async def test_network_errors_wrapped(session, exc: Exception) -> None:
    client = SpcClient(session)
    with aioresponses() as mock:
        mock.get(URL_A, exception=exc)
        with pytest.raises(SpcApiError) as err:
            await client.fetch(URL_A)
    assert err.value.status is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/api/test_client.py -v`
Expected: collection error — `No module named 'custom_components.noaa_spc.api.client'`.

- [ ] **Step 3: Implement `client.py`**

```python
"""HTTP client with conditional GET caching. Must not import Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass

import aiohttp

from .products import USER_AGENT


class SpcApiError(Exception):
    """A request to SPC failed."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Fetched:
    body: bytes
    changed: bool


class SpcClient:
    def __init__(self, session: aiohttp.ClientSession, *, timeout: float = 30.0) -> None:
        self._session = session
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        # url -> (etag, last_modified, body)
        self._cache: dict[str, tuple[str | None, str | None, bytes]] = {}

    async def fetch(
        self, url: str, *, accept: str | None = None, conditional: bool = True
    ) -> Fetched:
        headers = {"User-Agent": USER_AGENT}
        if accept:
            headers["Accept"] = accept
        cached = self._cache.get(url) if conditional else None
        if cached:
            etag, last_modified, _ = cached
            if etag:
                headers["If-None-Match"] = etag
            if last_modified:
                headers["If-Modified-Since"] = last_modified
        try:
            async with self._session.get(
                url, headers=headers, timeout=self._timeout
            ) as resp:
                if resp.status == 304 and cached:
                    return Fetched(cached[2], changed=False)
                if resp.status >= 300:
                    raise SpcApiError(f"HTTP {resp.status} from {url}", resp.status)
                body = await resp.read()
                etag = resp.headers.get("ETag")
                last_modified = resp.headers.get("Last-Modified")
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SpcApiError(f"{url}: {err!r}") from err
        changed = cached is None or cached[2] != body
        if conditional and (etag or last_modified):
            self._cache[url] = (etag, last_modified, body)
        return Fetched(body, changed=changed)
```

Note on `test_200_with_identical_body_is_unchanged`: the second request sends `If-None-Match`, the mock still returns 200 with the same body, and `changed` is `False` because the body matches the cache.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/api/test_client.py -v` — Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/noaa_spc/api/client.py tests/api/test_client.py
git commit -m "Add SPC HTTP client with conditional GET caching"
```

---

### Task 8: SpcApi bundles with per-product failure isolation

**Files:**
- Create: `custom_components/noaa_spc/api/spc.py`
- Test: `tests/api/test_spc.py`

**Interfaces:**
- Consumes: Tasks 3–7 (`parse_watch_feed`, `WATCH_FEED_PATH`).
- Produces:
  - `OutlookBundle(layers: Mapping[str, OutlookLayer], texts: Mapping[str, TextProduct], images: Mapping[str, bytes], updated: Mapping[str, datetime])` — `updated` keys are `"layer:<layer key>"`, `"text:<text key>"`, `"image:<image key>"`, holding the time of the last successful fetch+parse.
  - `AlertBundle(watches: tuple[Watch, ...], mds: tuple[MesoscaleDiscussion, ...], watches_updated: datetime | None, mds_updated: datetime | None)`.
  - `SpcApi(client: SpcClient, *, max_concurrency: int = 4)` with `async fetch_outlooks(previous: OutlookBundle | None) -> OutlookBundle`, `async fetch_alerts(previous: AlertBundle | None) -> AlertBundle`. `fetch_outlooks`/`fetch_alerts` never raise; failures keep previous values and are logged once per distinct error.

- [ ] **Step 1: Write failing tests**

`tests/api/test_spc.py`:
```python
import json
import logging

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.noaa_spc.api.client import SpcClient
from custom_components.noaa_spc.api.models import RiskLevel
from custom_components.noaa_spc.api.outlooks import categorical_at
from custom_components.noaa_spc.api.products import (
    IMAGE_PATHS,
    LAYER_PATHS,
    MD_FEED_PATH,
    SPC_BASE,
    TEXT_PATHS,
    WATCH_FEED_PATH,
)
from custom_components.noaa_spc.api.spc import SpcApi
from tests.api.test_mds import MD_HTML
from tests.helpers import HOME, collection, feature, square

DAY1_TEXT = "SPC AC 131252\n\n...SUMMARY...\nStorms.\n\n..Smith.. 10/13/2026\n"
MD_URL = "https://www.spc.noaa.gov/products/md/md2104.html"
MD_FEED = (
    '<?xml version="1.0"?><rss version="2.0"><channel>'
    f"<item><link>{MD_URL}</link></item></channel></rss>"
)
WATCH_FEED = (
    '<?xml version="1.0"?><rss version="2.0"><channel><item>'
    "<link>https://www.spc.noaa.gov/products/watch/ww0612.html</link>"
    "<title>SPC Tornado Watch 612</title></item></channel></rss>"
)


@pytest.fixture
async def api():
    async with aiohttp.ClientSession() as session:
        yield SpcApi(SpcClient(session))


def _register_outlooks(mock: aioresponses, overrides: dict[str, dict] | None = None) -> None:
    overrides = overrides or {}
    for key, path in LAYER_PATHS.items():
        if key in overrides:
            mock.get(SPC_BASE + path, **overrides[key])
        else:
            mock.get(SPC_BASE + path, body=json.dumps(collection()), repeat=True)
    for key, path in TEXT_PATHS.items():
        if key not in overrides:
            mock.get(SPC_BASE + path, body=DAY1_TEXT, repeat=True)
    for key, (path, _) in IMAGE_PATHS.items():
        if key not in overrides:
            mock.get(SPC_BASE + path, body=b"PNG" + key.encode(), repeat=True)


async def test_fetch_outlooks_all_products(api: SpcApi) -> None:
    slight = {"body": json.dumps(collection(feature("SLGT", square(*HOME)))), "repeat": True}
    with aioresponses() as mock:
        _register_outlooks(mock, {"day1_cat": slight})
        bundle = await api.fetch_outlooks(None)
    assert set(bundle.layers) == set(LAYER_PATHS)
    assert categorical_at(bundle.layers["day1_cat"], *HOME) is RiskLevel.SLGT
    assert bundle.texts["day1"].summary == "Storms."
    assert bundle.images["day1"] == b"PNGday1"
    assert len(bundle.updated) == len(LAYER_PATHS) + len(TEXT_PATHS) + len(IMAGE_PATHS)


async def test_failed_product_keeps_previous_value_and_timestamp(api: SpcApi) -> None:
    slight = {"body": json.dumps(collection(feature("SLGT", square(*HOME))))}
    with aioresponses() as mock:
        _register_outlooks(mock, {"day1_cat": slight})
        first = await api.fetch_outlooks(None)
    with aioresponses() as mock:
        _register_outlooks(mock, {"day1_cat": {"status": 500}})
        second = await api.fetch_outlooks(first)
    assert categorical_at(second.layers["day1_cat"], *HOME) is RiskLevel.SLGT
    assert second.updated["layer:day1_cat"] == first.updated["layer:day1_cat"]
    assert second.updated["layer:day2_cat"] >= first.updated["layer:day2_cat"]


async def test_malformed_product_logged_once(api: SpcApi, caplog) -> None:
    bad = {"body": "not json", "repeat": True}
    caplog.set_level(logging.WARNING)
    with aioresponses() as mock:
        _register_outlooks(mock, {"day1_cat": bad})
        bundle = await api.fetch_outlooks(None)
        await api.fetch_outlooks(bundle)
    assert "day1_cat" not in bundle.layers
    assert caplog.text.count("layer:day1_cat") == 1


async def test_fetch_alerts_parses_and_caches_md_pages(api: SpcApi) -> None:
    with aioresponses() as mock:
        mock.get(SPC_BASE + WATCH_FEED_PATH, body=WATCH_FEED, repeat=True)
        mock.get(SPC_BASE + MD_FEED_PATH, body=MD_FEED, repeat=True)
        mock.get(MD_URL, body=MD_HTML)  # registered once: a second fetch would fail
        first = await api.fetch_alerts(None)
        second = await api.fetch_alerts(first)
    assert [w.number for w in second.watches] == [612]
    assert [m.number for m in second.mds] == [2104]
    assert second.watches_updated is not None and second.mds_updated is not None


async def test_fetch_alerts_failure_keeps_previous(api: SpcApi) -> None:
    with aioresponses() as mock:
        mock.get(SPC_BASE + WATCH_FEED_PATH, body=WATCH_FEED)
        mock.get(SPC_BASE + MD_FEED_PATH, body=MD_FEED)
        mock.get(MD_URL, body=MD_HTML)
        first = await api.fetch_alerts(None)
    with aioresponses() as mock:
        mock.get(SPC_BASE + WATCH_FEED_PATH, status=503)
        mock.get(SPC_BASE + MD_FEED_PATH, status=503)
        second = await api.fetch_alerts(first)
    assert second.watches == first.watches
    assert second.mds == first.mds
    assert second.watches_updated == first.watches_updated


async def test_watch_feed_failure_does_not_block_mds(api: SpcApi) -> None:
    with aioresponses() as mock:
        mock.get(SPC_BASE + WATCH_FEED_PATH, status=503)
        mock.get(SPC_BASE + MD_FEED_PATH, body=MD_FEED)
        mock.get(MD_URL, body=MD_HTML)
        bundle = await api.fetch_alerts(None)
    assert bundle.watches == ()
    assert bundle.watches_updated is None
    assert [m.number for m in bundle.mds] == [2104]
    assert bundle.mds_updated is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/api/test_spc.py -v`
Expected: collection error — `No module named 'custom_components.noaa_spc.api.spc'`.

- [ ] **Step 3: Implement `spc.py`**

```python
"""High-level SPC fetching. Must not import Home Assistant."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from .client import SpcApiError, SpcClient
from .mds import parse_md_feed, parse_md_page
from .models import MesoscaleDiscussion, OutlookLayer, TextProduct, Watch
from .outlooks import parse_layer
from .products import (
    IMAGE_PATHS,
    LAYER_PATHS,
    MD_FEED_PATH,
    SPC_BASE,
    TEXT_PATHS,
    WATCH_FEED_PATH,
)
from .text import parse_text_product
from .watches import parse_watch_feed

_LOGGER = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class OutlookBundle:
    layers: Mapping[str, OutlookLayer]
    texts: Mapping[str, TextProduct]
    images: Mapping[str, bytes]
    updated: Mapping[str, datetime]


@dataclass(frozen=True)
class AlertBundle:
    watches: tuple[Watch, ...]
    mds: tuple[MesoscaleDiscussion, ...]
    watches_updated: datetime | None
    mds_updated: datetime | None


class SpcApi:
    def __init__(self, client: SpcClient, *, max_concurrency: int = 4) -> None:
        self._client = client
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._logged: set[str] = set()
        self._md_cache: dict[int, MesoscaleDiscussion] = {}

    def _failed(self, key: str, err: Exception) -> None:
        message = f"{key}: {err}"
        if message not in self._logged:
            self._logged.add(message)
            _LOGGER.warning("Failed to update SPC product %s", message)

    def _succeeded(self, key: str) -> None:
        self._logged = {m for m in self._logged if not m.startswith(f"{key}: ")}

    async def _get(self, url: str, **kwargs):
        async with self._semaphore:
            return await self._client.fetch(url, **kwargs)

    async def fetch_outlooks(self, previous: OutlookBundle | None) -> OutlookBundle:
        layers = dict(previous.layers) if previous else {}
        texts = dict(previous.texts) if previous else {}
        images = dict(previous.images) if previous else {}
        updated = dict(previous.updated) if previous else {}

        async def layer(key: str, path: str) -> None:
            name = f"layer:{key}"
            try:
                fetched = await self._get(SPC_BASE + path)
                if fetched.changed or key not in layers:
                    layers[key] = parse_layer(json.loads(fetched.body))
            except (SpcApiError, ValueError) as err:
                self._failed(name, err)
                return
            updated[name] = _now()
            self._succeeded(name)

        async def text(key: str, path: str) -> None:
            name = f"text:{key}"
            try:
                fetched = await self._get(SPC_BASE + path)
                if fetched.changed or key not in texts:
                    texts[key] = parse_text_product(
                        fetched.body.decode("utf-8", "replace")
                    )
            except (SpcApiError, ValueError) as err:
                self._failed(name, err)
                return
            updated[name] = _now()
            self._succeeded(name)

        async def image(key: str, path: str) -> None:
            name = f"image:{key}"
            try:
                fetched = await self._get(SPC_BASE + path)
            except SpcApiError as err:
                self._failed(name, err)
                return
            if fetched.changed or key not in images:
                images[key] = fetched.body
            updated[name] = _now()
            self._succeeded(name)

        await asyncio.gather(
            *(layer(k, p) for k, p in LAYER_PATHS.items()),
            *(text(k, p) for k, p in TEXT_PATHS.items()),
            *(image(k, p) for k, (p, _) in IMAGE_PATHS.items()),
        )
        return OutlookBundle(layers, texts, images, updated)

    async def fetch_alerts(self, previous: AlertBundle | None) -> AlertBundle:
        watches = previous.watches if previous else ()
        mds = previous.mds if previous else ()
        watches_updated = previous.watches_updated if previous else None
        mds_updated = previous.mds_updated if previous else None

        try:
            fetched = await self._get(SPC_BASE + WATCH_FEED_PATH)
            watches = parse_watch_feed(fetched.body)
        except (SpcApiError, ValueError) as err:
            self._failed("watches", err)
        else:
            watches_updated = _now()
            self._succeeded("watches")

        try:
            fetched = await self._get(SPC_BASE + MD_FEED_PATH)
            entries = parse_md_feed(fetched.body)
        except (SpcApiError, ValueError) as err:
            self._failed("mds", err)
        else:
            current: list[MesoscaleDiscussion] = []
            for number, url in entries:
                md = self._md_cache.get(number)
                if md is None:
                    try:
                        page = await self._get(url, conditional=False)
                        md = parse_md_page(page.body.decode("utf-8", "replace"), url)
                    except (SpcApiError, ValueError) as err:
                        self._failed(f"md:{number}", err)
                        continue
                    self._md_cache[number] = md
                current.append(md)
            active = {number for number, _ in entries}
            self._md_cache = {n: m for n, m in self._md_cache.items() if n in active}
            mds = tuple(current)
            mds_updated = _now()
            self._succeeded("mds")

        return AlertBundle(watches, mds, watches_updated, mds_updated)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/api -v` — Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/noaa_spc/api/spc.py tests/api/test_spc.py
git commit -m "Add SpcApi with isolated per-product failures"
```

---

### Task 9: Point evaluation

**Files:**
- Create: `custom_components/noaa_spc/api/evaluate.py`, `tests/factories.py`
- Test: `tests/api/test_evaluate.py`

**Interfaces:**
- Consumes: Tasks 2, 3, 8.
- Produces:
  - `OutlookRisk(categorical: Mapping[int, RiskLevel], probability: Mapping[str, int], significant: Mapping[str, bool], predictability_too_low: Mapping[int, bool])` with property `max_next_3_days -> tuple[RiskLevel, int] | None` (earliest day wins ties). `probability` keys: `day{1,2}_{torn,wind,hail}`, `day3_prob`, `day{4..8}_prob`; `significant` keys: `day{1,2}_{torn,wind,hail}`, `day3_prob`. Only layers present in the input appear.
  - `AlertRisk(mds: tuple[MesoscaleDiscussion, ...])` — per-location alerts are MDs only; watches stay national.
  - `evaluate_outlooks(layers: Mapping[str, OutlookLayer], lat, lon) -> OutlookRisk`; `evaluate_alerts(mds, lat, lon) -> AlertRisk`.
  - `tests/factories.py`: `outlook_bundle(layers, *, when=None, texts=None, images=None) -> OutlookBundle`, `risk_layers() -> dict[str, dict]`, `alert_bundle(watches=(), mds=(), *, when=None) -> AlertBundle`, `make_watch(number=612, kind="tornado", pds=False) -> Watch`, `make_md(number=2104, center=HOME, half=1.0) -> MesoscaleDiscussion`.

- [ ] **Step 1: Write `tests/factories.py`**

```python
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
```

- [ ] **Step 2: Write failing tests**

`tests/api/test_evaluate.py`:
```python
from custom_components.noaa_spc.api.evaluate import (
    OutlookRisk,
    evaluate_alerts,
    evaluate_outlooks,
)
from custom_components.noaa_spc.api.models import RiskLevel
from tests.factories import make_md, outlook_bundle, risk_layers
from tests.helpers import FAR, HOME


def test_evaluate_outlooks_at_home() -> None:
    risk = evaluate_outlooks(outlook_bundle(risk_layers()).layers, *HOME)
    assert risk.categorical == {1: RiskLevel.SLGT, 2: RiskLevel.MRGL, 3: RiskLevel.NONE}
    assert risk.probability["day1_torn"] == 5
    assert risk.probability["day1_wind"] == 15
    assert risk.probability["day1_hail"] == 0
    assert risk.probability["day3_prob"] == 5
    assert risk.probability["day4_prob"] == 15
    assert risk.probability["day5_prob"] == 0
    assert "day2_torn" not in risk.probability
    assert risk.significant == {"day1_torn": True}
    assert risk.predictability_too_low == {4: False, 5: True}
    assert risk.max_next_3_days == (RiskLevel.SLGT, 1)


def test_evaluate_outlooks_far_away() -> None:
    risk = evaluate_outlooks(outlook_bundle(risk_layers()).layers, *FAR)
    assert risk.categorical[1] is RiskLevel.NONE
    assert risk.probability["day1_torn"] == 0
    assert risk.significant["day1_torn"] is False


def test_max_ties_pick_earliest_day_and_empty_is_none() -> None:
    tie = OutlookRisk({1: RiskLevel.MRGL, 2: RiskLevel.ENH, 3: RiskLevel.ENH}, {}, {}, {})
    assert tie.max_next_3_days == (RiskLevel.ENH, 2)
    assert OutlookRisk({}, {}, {}, {}).max_next_3_days is None


def test_evaluate_alerts_by_polygon() -> None:
    mds = (make_md(2104), make_md(2105, center=FAR))
    risk = evaluate_alerts(mds, *HOME)
    assert [m.number for m in risk.mds] == [2104]
    assert evaluate_alerts(mds, FAR[0] + 5.0, FAR[1]).mds == ()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/api/test_evaluate.py -v`
Expected: collection error — `No module named 'custom_components.noaa_spc.api.evaluate'`.

- [ ] **Step 4: Implement `evaluate.py`**

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/api -v` — Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add custom_components/noaa_spc/api/evaluate.py tests/factories.py tests/api/test_evaluate.py
git commit -m "Evaluate outlooks and MDs at a point"
```

---

### Task 10: Shared hub (coordinators + reference-counted singleton)

**Files:**
- Create: `custom_components/noaa_spc/hub.py`
- Modify: `tests/conftest.py` (add `mock_api` fixture)
- Test: `tests/test_hub.py`

**Interfaces:**
- Consumes: `SpcApi`, `SpcClient`, bundles (Task 8); constants (Task 1).
- Produces:
  - `is_hub_entry(entry: ConfigEntry) -> bool`.
  - `OutlookCoordinator(DataUpdateCoordinator[OutlookBundle])`, `AlertCoordinator(DataUpdateCoordinator[AlertBundle])`.
  - `SpcHub` with attributes `api: SpcApi`, `outlooks: OutlookCoordinator`, `alerts: AlertCoordinator`, `users: int`; methods `apply_options(options: Mapping[str, Any]) -> None`, `async_start()`, `async_stop()`.
  - `async_acquire_hub(hass) -> SpcHub`, `async_release_hub(hass) -> None`, `get_hub(hass) -> SpcHub | None`.
  - `tests/conftest.py` fixture `mock_api` → a `SimpleNamespace` with mutable `outlooks: OutlookBundle` and `alerts: AlertBundle`; it patches `SpcApi.fetch_outlooks` and `SpcApi.fetch_alerts` to return them.

- [ ] **Step 1: Add the `mock_api` fixture to `tests/conftest.py`**

Replace the file with:
```python
"""Shared pytest fixtures."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from custom_components.noaa_spc.api.spc import SpcApi
from tests.factories import alert_bundle, outlook_bundle, risk_layers


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow Home Assistant to load custom_components in every test."""
    yield


@pytest.fixture
def mock_api():
    """Patch SpcApi network methods; mutate the returned namespace in tests."""
    state = SimpleNamespace(
        outlooks=outlook_bundle(risk_layers()),
        alerts=alert_bundle(),
    )

    async def fetch_outlooks(self, previous):
        return state.outlooks

    async def fetch_alerts(self, previous):
        return state.alerts

    with (
        patch.object(SpcApi, "fetch_outlooks", fetch_outlooks),
        patch.object(SpcApi, "fetch_alerts", fetch_alerts),
    ):
        yield state
```

- [ ] **Step 2: Write failing tests**

`tests/test_hub.py`:
```python
from datetime import timedelta

from homeassistant.core import HomeAssistant

from custom_components.noaa_spc.const import CONF_ALERT_INTERVAL, CONF_OUTLOOK_INTERVAL
from custom_components.noaa_spc.hub import (
    async_acquire_hub,
    async_release_hub,
    get_hub,
)


async def test_acquire_is_shared_and_starts_coordinators(
    hass: HomeAssistant, mock_api
) -> None:
    hub = await async_acquire_hub(hass)
    again = await async_acquire_hub(hass)
    assert hub is again
    assert hub.users == 2
    assert hub.outlooks.data is mock_api.outlooks
    assert hub.alerts.data is mock_api.alerts
    assert hub.outlooks.update_interval == timedelta(minutes=5)
    assert hub.alerts.update_interval == timedelta(minutes=2)

    await async_release_hub(hass)
    assert get_hub(hass) is hub
    await async_release_hub(hass)
    assert get_hub(hass) is None


async def test_apply_options(hass: HomeAssistant, mock_api) -> None:
    hub = await async_acquire_hub(hass)
    hub.apply_options({CONF_OUTLOOK_INTERVAL: 10, CONF_ALERT_INTERVAL: 1})
    assert hub.outlooks.update_interval == timedelta(minutes=10)
    assert hub.alerts.update_interval == timedelta(minutes=1)
    await async_release_hub(hass)


async def test_release_without_hub_is_noop(hass: HomeAssistant) -> None:
    await async_release_hub(hass)
    assert get_hub(hass) is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_hub.py -v`
Expected: collection error — `No module named 'custom_components.noaa_spc.hub'`.

- [ ] **Step 4: Implement `hub.py`**

```python
"""Shared SPC data hub used by every config entry."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api.client import SpcClient
from .api.spc import AlertBundle, OutlookBundle, SpcApi
from .const import (
    CONF_ALERT_INTERVAL,
    CONF_ENTRY_TYPE,
    CONF_OUTLOOK_INTERVAL,
    DEFAULT_ALERT_INTERVAL,
    DEFAULT_OUTLOOK_INTERVAL,
    DOMAIN,
    ENTRY_TYPE_HUB,
)

_LOGGER = logging.getLogger(__name__)


def is_hub_entry(entry: ConfigEntry) -> bool:
    return entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB


class OutlookCoordinator(DataUpdateCoordinator[OutlookBundle]):
    def __init__(self, hass: HomeAssistant, api: SpcApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=None,
            name=f"{DOMAIN} outlooks",
            update_interval=timedelta(minutes=DEFAULT_OUTLOOK_INTERVAL),
        )
        self.api = api
        # Not tied to a config entry, so stop polling explicitly on HA shutdown.
        self.async_register_shutdown()

    async def _async_update_data(self) -> OutlookBundle:
        return await self.api.fetch_outlooks(self.data)


class AlertCoordinator(DataUpdateCoordinator[AlertBundle]):
    def __init__(self, hass: HomeAssistant, api: SpcApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=None,
            name=f"{DOMAIN} alerts",
            update_interval=timedelta(minutes=DEFAULT_ALERT_INTERVAL),
        )
        self.api = api
        self.async_register_shutdown()

    async def _async_update_data(self) -> AlertBundle:
        return await self.api.fetch_alerts(self.data)


class SpcHub:
    def __init__(self, hass: HomeAssistant) -> None:
        self.api = SpcApi(SpcClient(async_get_clientsession(hass)))
        self.outlooks = OutlookCoordinator(hass, self.api)
        self.alerts = AlertCoordinator(hass, self.api)
        self.users = 0

    def apply_options(self, options: Mapping[str, Any]) -> None:
        self.outlooks.update_interval = timedelta(
            minutes=options.get(CONF_OUTLOOK_INTERVAL, DEFAULT_OUTLOOK_INTERVAL)
        )
        self.alerts.update_interval = timedelta(
            minutes=options.get(CONF_ALERT_INTERVAL, DEFAULT_ALERT_INTERVAL)
        )

    async def async_start(self) -> None:
        await self.outlooks.async_refresh()
        await self.alerts.async_refresh()

    async def async_stop(self) -> None:
        await self.outlooks.async_shutdown()
        await self.alerts.async_shutdown()


@dataclass
class _HubState:
    lock: asyncio.Lock
    hub: SpcHub | None = None


def _state(hass: HomeAssistant) -> _HubState:
    return hass.data.setdefault(DOMAIN, _HubState(asyncio.Lock()))


def get_hub(hass: HomeAssistant) -> SpcHub | None:
    state = hass.data.get(DOMAIN)
    return state.hub if state else None


async def async_acquire_hub(hass: HomeAssistant) -> SpcHub:
    state = _state(hass)
    async with state.lock:
        if state.hub is None:
            hub = SpcHub(hass)
            await hub.async_start()
            state.hub = hub
        state.hub.users += 1
        return state.hub


async def async_release_hub(hass: HomeAssistant) -> None:
    state = hass.data.get(DOMAIN)
    if state is None:
        return
    async with state.lock:
        if state.hub is None:
            return
        state.hub.users -= 1
        if state.hub.users <= 0:
            await state.hub.async_stop()
            state.hub = None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_hub.py -v` — Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add custom_components/noaa_spc/hub.py tests/conftest.py tests/test_hub.py
git commit -m "Add shared reference-counted SPC hub"
```

---

### Task 11: Location coordinator (position, evaluation, events, repairs)

**Files:**
- Create: `custom_components/noaa_spc/location.py`
- Test: `tests/test_location.py`

**Interfaces:**
- Consumes: `SpcHub` shape (`outlooks`, `alerts` coordinators) from Task 10; evaluate (Task 9); constants.
- Produces:
  - `LocationData(position, outlook: OutlookRisk | None, alerts: AlertRisk | None, layers: Mapping[str, OutlookLayer], updated: Mapping[str, datetime], mds_updated: datetime | None)` (frozen dataclass).
  - `position_from_state(state: State | None) -> tuple[float, float] | None`.
  - `LocationCoordinator(DataUpdateCoordinator[LocationData])`, constructed `LocationCoordinator(hass, entry, hub)`; attributes `groups: set[str]`, `mode`, `tracked_entity`; `async async_start()`.
  - Events `noaa_spc_risk_changed` (`config_entry_id, location_name, latitude, longitude, day, old, new, old_level, new_level, upgraded`), `noaa_spc_md_issued` (`… number, concerning, watch_probability, summary, url`).
  - Repair issue id `f"missing_tracker_{entry.entry_id}"`, translation key `missing_tracker`, placeholders `entity_id`, `location`.
  - `tests/factories.py` additions: `fixed_entry(...)`, `tracked_entry(...)`, `FakeHub`.

- [ ] **Step 1: Add entry builders and a fake hub to `tests/factories.py`**

Append:
```python
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.noaa_spc.const import (
    CONF_ENTRY_TYPE,
    CONF_MODE,
    CONF_TRACKED_ENTITY,
    DOMAIN,
    ENTRY_TYPE_LOCATION,
    MODE_FIXED,
    MODE_TRACKED,
)


def fixed_entry(
    lat: float = HOME[0],
    lon: float = HOME[1],
    title: str = "Home",
    options: dict[str, Any] | None = None,
) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title=title,
        unique_id=f"fixed_{lat:.3f}_{lon:.3f}",
        data={
            CONF_ENTRY_TYPE: ENTRY_TYPE_LOCATION,
            CONF_MODE: MODE_FIXED,
            "latitude": lat,
            "longitude": lon,
        },
        options=options or {},
    )


def tracked_entry(
    entity_id: str = "device_tracker.phone",
    title: str = "Phone",
    options: dict[str, Any] | None = None,
) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title=title,
        unique_id=f"tracked_{entity_id}",
        data={
            CONF_ENTRY_TYPE: ENTRY_TYPE_LOCATION,
            CONF_MODE: MODE_TRACKED,
            CONF_TRACKED_ENTITY: entity_id,
        },
        options=options or {},
    )


class FakeHub:
    """Hub stand-in: push bundles with push_outlooks / push_alerts."""

    def __init__(self, hass: HomeAssistant) -> None:
        log = logging.getLogger("tests.fakehub")
        self.outlooks = DataUpdateCoordinator(hass, log, config_entry=None, name="o")
        self.alerts = DataUpdateCoordinator(hass, log, config_entry=None, name="a")

    def push_outlooks(self, bundle: OutlookBundle) -> None:
        self.outlooks.async_set_updated_data(bundle)

    def push_alerts(self, bundle: AlertBundle) -> None:
        self.alerts.async_set_updated_data(bundle)
```

Move the new imports to the top of the file with the existing ones (ruff `I`/`E402` will flag them otherwise).

- [ ] **Step 2: Write failing tests**

`tests/test_location.py`:
```python
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.noaa_spc.api.models import RiskLevel
from custom_components.noaa_spc.const import (
    CONF_GROUPS,
    DOMAIN,
    EVENT_MD_ISSUED,
    EVENT_RISK_CHANGED,
    GROUP_CATEGORICAL,
)
from custom_components.noaa_spc.location import LocationCoordinator
from tests.factories import (
    FakeHub,
    alert_bundle,
    fixed_entry,
    make_md,
    make_watch,
    outlook_bundle,
    risk_layers,
    tracked_entry,
)
from tests.helpers import FAR, HOME


async def _start(hass, entry, hub) -> LocationCoordinator:
    entry.add_to_hass(hass)
    coordinator = LocationCoordinator(hass, entry, hub)
    await coordinator.async_start()
    await hass.async_block_till_done()
    return coordinator


def _hub_with_data(hass, *, day1="SLGT", watches=(), mds=()) -> FakeHub:
    hub = FakeHub(hass)
    hub.outlooks.data = outlook_bundle(risk_layers(day1))
    hub.alerts.data = alert_bundle(watches, mds)
    return hub


async def test_fixed_location_baseline_has_no_events(hass: HomeAssistant) -> None:
    risk_events = async_capture_events(hass, EVENT_RISK_CHANGED)
    md_events = async_capture_events(hass, EVENT_MD_ISSUED)
    hub = _hub_with_data(hass, mds=[make_md()])
    coordinator = await _start(hass, fixed_entry(), hub)

    data = coordinator.data
    assert data.position == HOME
    assert data.outlook.categorical[1] is RiskLevel.SLGT
    assert [m.number for m in data.alerts.mds] == [2104]
    assert data.mds_updated is not None
    assert (risk_events, md_events) == ([], [])


async def test_risk_upgrade_fires_once(hass: HomeAssistant) -> None:
    events = async_capture_events(hass, EVENT_RISK_CHANGED)
    hub = _hub_with_data(hass)
    entry = fixed_entry()
    await _start(hass, entry, hub)

    hub.push_outlooks(outlook_bundle(risk_layers("ENH")))
    hub.push_outlooks(outlook_bundle(risk_layers("ENH")))
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data == {
        "config_entry_id": entry.entry_id,
        "location_name": "Home",
        "latitude": HOME[0],
        "longitude": HOME[1],
        "day": 1,
        "old": "SLGT",
        "new": "ENH",
        "old_level": 3,
        "new_level": 4,
        "upgraded": True,
    }


async def test_downgrade_reports_not_upgraded(hass: HomeAssistant) -> None:
    events = async_capture_events(hass, EVENT_RISK_CHANGED)
    hub = _hub_with_data(hass)
    await _start(hass, fixed_entry(), hub)
    hub.push_outlooks(outlook_bundle(risk_layers("MRGL")))
    await hass.async_block_till_done()
    assert events[0].data["upgraded"] is False


async def test_new_md_fires_once_and_watches_never_fire(hass: HomeAssistant) -> None:
    md_events = async_capture_events(hass, EVENT_MD_ISSUED)
    all_events = async_capture_events(hass, "noaa_spc_watch_issued")
    hub = _hub_with_data(hass)
    await _start(hass, fixed_entry(), hub)

    bundle = alert_bundle([make_watch(612)], [make_md(2104), make_md(2105, center=FAR)])
    hub.push_alerts(bundle)
    hub.push_alerts(bundle)
    await hass.async_block_till_done()

    assert [e.data["number"] for e in md_events] == [2104]
    assert md_events[0].data["watch_probability"] == 80
    assert md_events[0].data["url"].endswith("md2104.html")
    assert all_events == []


async def test_md_that_expires_and_reissues_fires_again(hass: HomeAssistant) -> None:
    md_events = async_capture_events(hass, EVENT_MD_ISSUED)
    hub = _hub_with_data(hass)
    await _start(hass, fixed_entry(), hub)

    hub.push_alerts(alert_bundle(mds=[make_md(2104)]))
    hub.push_alerts(alert_bundle())
    hub.push_alerts(alert_bundle(mds=[make_md(2104)]))
    await hass.async_block_till_done()
    assert [e.data["number"] for e in md_events] == [2104, 2104]


async def test_tracked_move_into_risk_fires_and_jitter_is_ignored(
    hass: HomeAssistant,
) -> None:
    events = async_capture_events(hass, EVENT_RISK_CHANGED)
    hass.states.async_set("device_tracker.phone", "not_home",
                          {"latitude": FAR[0], "longitude": FAR[1]})
    hub = _hub_with_data(hass)
    coordinator = await _start(hass, tracked_entry(), hub)
    assert coordinator.data.outlook.categorical[1] is RiskLevel.NONE

    hass.states.async_set("device_tracker.phone", "not_home",
                          {"latitude": HOME[0], "longitude": HOME[1]})
    await hass.async_block_till_done()
    assert coordinator.data.position == HOME
    assert [e.data["new"] for e in events] == ["SLGT"]

    hass.states.async_set("device_tracker.phone", "not_home",
                          {"latitude": HOME[0] + 0.001, "longitude": HOME[1]})
    await hass.async_block_till_done()
    assert coordinator.data.position == HOME
    assert len(events) == 1


async def test_tracked_without_coordinates_is_unpositioned(hass: HomeAssistant) -> None:
    events = async_capture_events(hass, EVENT_RISK_CHANGED)
    hass.states.async_set("person.alex", "home", {"latitude": HOME[0], "longitude": HOME[1]})
    hub = _hub_with_data(hass)
    coordinator = await _start(hass, tracked_entry("person.alex", "Alex"), hub)

    hass.states.async_set("person.alex", "unknown", {})
    await hass.async_block_till_done()
    assert coordinator.data.position is None
    assert coordinator.data.outlook is None

    hub.push_outlooks(outlook_bundle(risk_layers("HIGH")))
    await hass.async_block_till_done()
    assert events == []


async def test_rapid_moves_last_position_wins(hass: HomeAssistant) -> None:
    hass.states.async_set("device_tracker.phone", "unknown", {})
    hub = _hub_with_data(hass, mds=[make_md(2104), make_md(2105, center=FAR)])
    coordinator = await _start(hass, tracked_entry(), hub)

    hass.states.async_set("device_tracker.phone", "x", {"latitude": FAR[0], "longitude": FAR[1]})
    hass.states.async_set("device_tracker.phone", "x", {"latitude": HOME[0], "longitude": HOME[1]})
    await hass.async_block_till_done()

    assert coordinator.data.position == HOME
    assert coordinator.data.outlook.categorical[1] is RiskLevel.SLGT
    assert [m.number for m in coordinator.data.alerts.mds] == [2104]


async def test_missing_tracker_raises_repair_issue(hass: HomeAssistant) -> None:
    entry = tracked_entry("device_tracker.gone")
    await _start(hass, entry, _hub_with_data(hass))
    issue_id = f"missing_tracker_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    hass.states.async_set("device_tracker.gone", "home", {"latitude": 1.0, "longitude": 1.0})
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_alerts_group_disabled_skips_md_evaluation(hass: HomeAssistant) -> None:
    events = async_capture_events(hass, EVENT_MD_ISSUED)
    hub = _hub_with_data(hass)
    coordinator = await _start(
        hass, fixed_entry(options={CONF_GROUPS: [GROUP_CATEGORICAL]}), hub
    )
    hub.push_alerts(alert_bundle(mds=[make_md()]))
    await hass.async_block_till_done()
    assert coordinator.data.alerts is None
    assert events == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_location.py -v`
Expected: collection error — `No module named 'custom_components.noaa_spc.location'`.

- [ ] **Step 4: Implement `location.py`**

```python
"""Per-location evaluation, events and tracking."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_LATITUDE, ATTR_LONGITUDE, CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
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
        super().__init__(hass, _LOGGER, config_entry=entry, name=f"{DOMAIN} {entry.title}")
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
        entry.async_on_unload(self.hub.outlooks.async_add_listener(self._handle_outlooks))
        entry.async_on_unload(self.hub.alerts.async_add_listener(self._handle_alerts))
        if self.mode == MODE_TRACKED:
            assert self.tracked_entity is not None
            entry.async_on_unload(
                async_track_state_change_event(
                    self.hass, [self.tracked_entity], self._handle_tracker_event
                )
            )
            entry.async_on_unload(
                async_at_started(
                    self.hass,
                    lambda _hass: self._check_tracker_exists(
                        self.hass.states.get(self.tracked_entity)
                    ),
                )
            )
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
        risk = evaluate_outlooks(bundle.layers, *self._position)
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
```

Note: `async_set_updated_data` on a coordinator with no `update_interval` is fine; this coordinator is never refreshed by polling. Position changes are handled synchronously (there is no network call per location), so the last tracker update always wins.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_location.py -v` — Expected: 10 passed.

- [ ] **Step 6: Commit**

```bash
git add custom_components/noaa_spc/location.py tests/factories.py tests/test_location.py
git commit -m "Add location coordinator with events, tracking and repairs"
```

---

### Task 12: Config flow and translations

**Files:**
- Create: `custom_components/noaa_spc/config_flow.py`, `custom_components/noaa_spc/translations/en.json`
- Test: `tests/test_config_flow.py`

**Interfaces:**
- Consumes: constants, `in_conus` (Task 3).
- Produces: `SpcConfigFlow` with steps `user` (menu: `fixed`, `tracked`), `fixed`, `outside`, `tracked`, `import` (hub). Location entry data: `{entry_type: "location", mode: "fixed", latitude, longitude}` or `{entry_type: "location", mode: "tracked", tracked_entity}`; unique ids `fixed_{lat:.3f}_{lon:.3f}`, `tracked_{entity_id}`, hub `hub`. Options flows are added in Task 15.

- [ ] **Step 1: Write failing tests**

`tests/test_config_flow.py`:
```python
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_IMPORT, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.noaa_spc.const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_HUB
from tests.factories import fixed_entry, tracked_entry


@pytest.fixture(autouse=True)
def skip_setup():
    with (
        patch(
            "custom_components.noaa_spc.async_setup",
            new=AsyncMock(return_value=True),
            create=True,
        ),
        patch(
            "custom_components.noaa_spc.async_setup_entry",
            new=AsyncMock(return_value=True),
            create=True,
        ),
    ):
        yield


async def _menu(hass: HomeAssistant, choice: str) -> dict:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["fixed", "tracked"]
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": choice}
    )


async def test_fixed_location(hass: HomeAssistant) -> None:
    result = await _menu(hass, "fixed")
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Home", "location": {"latitude": 35.22, "longitude": -97.44}},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Home"
    assert result["data"] == {
        "entry_type": "location",
        "mode": "fixed",
        "latitude": 35.22,
        "longitude": -97.44,
    }
    assert result["result"].unique_id == "fixed_35.220_-97.440"


async def test_fixed_duplicate_aborts(hass: HomeAssistant) -> None:
    fixed_entry(35.2201, -97.4399).add_to_hass(hass)
    result = await _menu(hass, "fixed")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Again", "location": {"latitude": 35.22, "longitude": -97.44}},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_fixed_outside_conus_warns_then_creates(hass: HomeAssistant) -> None:
    result = await _menu(hass, "fixed")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "London", "location": {"latitude": 51.5, "longitude": -0.12}},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "outside"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["latitude"] == 51.5


async def test_tracked_location_and_duplicate(hass: HomeAssistant) -> None:
    hass.states.async_set("person.alex", "home", {"latitude": 35.2, "longitude": -97.4})
    result = await _menu(hass, "tracked")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Alex", "tracked_entity": "person.alex"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        "entry_type": "location",
        "mode": "tracked",
        "tracked_entity": "person.alex",
    }

    tracked_entry("device_tracker.phone").add_to_hass(hass)
    hass.states.async_set("device_tracker.phone", "home")
    result = await _menu(hass, "tracked")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Phone", "tracked_entity": "device_tracker.phone"}
    )
    assert result["type"] is FlowResultType.ABORT


async def test_import_creates_single_hub(hass: HomeAssistant) -> None:
    data = {CONF_ENTRY_TYPE: ENTRY_TYPE_HUB}
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=data
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "NOAA SPC"
    assert result["data"] == data
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=data
    )
    assert result["type"] is FlowResultType.ABORT
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_config_flow.py -v`
Expected: FAIL — flow init errors with `UnknownHandler` / `Invalid handler specified` because `config_flow.py` does not exist.

- [ ] **Step 3: Implement `config_flow.py`**

```python
"""Config flow for NOAA SPC."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_LATITUDE, CONF_LOCATION, CONF_LONGITUDE, CONF_NAME
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    LocationSelector,
    LocationSelectorConfig,
)

from .api.products import in_conus
from .const import (
    CONF_ENTRY_TYPE,
    CONF_MODE,
    CONF_TRACKED_ENTITY,
    DOMAIN,
    ENTRY_TYPE_HUB,
    ENTRY_TYPE_LOCATION,
    HUB_TITLE,
    HUB_UNIQUE_ID,
    MODE_FIXED,
    MODE_TRACKED,
    TRACKABLE_DOMAINS,
)


class SpcConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._pending: tuple[str, dict[str, Any]] | None = None

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        await self.async_set_unique_id(HUB_UNIQUE_ID)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=HUB_TITLE, data={CONF_ENTRY_TYPE: ENTRY_TYPE_HUB}
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=[MODE_FIXED, MODE_TRACKED])

    async def async_step_fixed(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            location = user_input[CONF_LOCATION]
            lat = float(location[CONF_LATITUDE])
            lon = float(location[CONF_LONGITUDE])
            await self.async_set_unique_id(f"fixed_{lat:.3f}_{lon:.3f}")
            self._abort_if_unique_id_configured()
            self._pending = (
                user_input[CONF_NAME],
                {
                    CONF_ENTRY_TYPE: ENTRY_TYPE_LOCATION,
                    CONF_MODE: MODE_FIXED,
                    CONF_LATITUDE: lat,
                    CONF_LONGITUDE: lon,
                },
            )
            if not in_conus(lat, lon):
                return await self.async_step_outside()
            return self._create_pending()

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=self.hass.config.location_name): str,
                vol.Required(
                    CONF_LOCATION,
                    default={
                        CONF_LATITUDE: self.hass.config.latitude,
                        CONF_LONGITUDE: self.hass.config.longitude,
                    },
                ): LocationSelector(LocationSelectorConfig(radius=False)),
            }
        )
        return self.async_show_form(step_id="fixed", data_schema=schema)

    async def async_step_outside(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self._create_pending()
        return self.async_show_form(step_id="outside", data_schema=vol.Schema({}))

    async def async_step_tracked(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            entity_id = user_input[CONF_TRACKED_ENTITY]
            await self.async_set_unique_id(f"tracked_{entity_id}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={
                    CONF_ENTRY_TYPE: ENTRY_TYPE_LOCATION,
                    CONF_MODE: MODE_TRACKED,
                    CONF_TRACKED_ENTITY: entity_id,
                },
            )
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): str,
                vol.Required(CONF_TRACKED_ENTITY): EntitySelector(
                    EntitySelectorConfig(domain=TRACKABLE_DOMAINS)
                ),
            }
        )
        return self.async_show_form(step_id="tracked", data_schema=schema)

    def _create_pending(self) -> ConfigFlowResult:
        assert self._pending is not None
        title, data = self._pending
        return self.async_create_entry(title=title, data=data)
```

- [ ] **Step 4: Write `translations/en.json`**

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Add an SPC location",
        "menu_options": {
          "fixed": "Fixed location",
          "tracked": "Follow a device tracker, person or zone"
        }
      },
      "fixed": {
        "title": "Fixed location",
        "data": { "name": "Name", "location": "Location" }
      },
      "tracked": {
        "title": "Tracked location",
        "data": { "name": "Name", "tracked_entity": "Entity to follow" }
      },
      "outside": {
        "title": "Outside SPC coverage",
        "description": "This location is outside the contiguous United States. SPC convective outlooks only cover the CONUS, so its risk will always be \"none\". Submit to add it anyway."
      }
    },
    "abort": {
      "already_configured": "This location is already configured."
    }
  },
  "options": {
    "step": {
      "hub": {
        "title": "SPC polling",
        "data": {
          "outlook_interval_min": "Outlook poll interval (minutes)",
          "alert_interval_min": "Mesoscale discussion and watch feed poll interval (minutes)"
        }
      },
      "location": {
        "title": "Location options",
        "data": {
          "location": "Location",
          "tracked_entity": "Entity to follow",
          "move_threshold_km": "Minimum movement before re-evaluating (km)",
          "groups": "Entity groups"
        }
      }
    }
  },
  "selector": {
    "groups": {
      "options": {
        "categorical": "Categorical risk (Days 1–3)",
        "probabilistic": "Tornado / wind / hail probabilities (Days 1–3)",
        "extended": "Days 4–8",
        "alerts": "Mesoscale discussions"
      }
    }
  },
  "issues": {
    "missing_tracker": {
      "title": "SPC location \"{location}\" lost its tracker",
      "description": "The entity {entity_id} that the SPC location \"{location}\" follows no longer exists. Open the NOAA Storm Prediction Center integration, choose Configure on this location and pick a new entity, or delete the location."
    }
  }
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_config_flow.py -v` — Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add custom_components/noaa_spc/config_flow.py custom_components/noaa_spc/translations tests/test_config_flow.py
git commit -m "Add config flow for fixed and tracked locations"
```

---

### Task 13: Integration setup, location sensors and binary sensors

**Files:**
- Modify: `custom_components/noaa_spc/__init__.py` (replace)
- Create: `custom_components/noaa_spc/entity.py`, `custom_components/noaa_spc/sensor.py`, `custom_components/noaa_spc/binary_sensor.py`
- Modify: `tests/factories.py` (add `setup_entry`)
- Test: `tests/test_location_entities.py`

**Interfaces:**
- Consumes: Tasks 10–12.
- Produces:
  - `__init__.py`: `CONFIG_SCHEMA`, `async_setup`, `async_setup_entry`, `async_unload_entry`, `async_remove_entry`; `HUB_PLATFORMS = [Platform.SENSOR]` (Task 14 adds `Platform.IMAGE`), `LOCATION_PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]`. Hub `entry.runtime_data` is `SpcHub`; location `entry.runtime_data` is `LocationCoordinator`.
  - `entity.py`: `SpcLocationEntity(coordinator, key)`, `SpcHubEntity(coordinator, key)`, `is_fresh(ts, max_age) -> bool`, `data_age(ts) -> int | None`, `watch_attributes(watch) -> dict` (used by the hub watch count in Task 14), `md_attributes(md) -> dict`, `async_remove_entities(hass, domain, unique_ids)`.
  - Location entity ids for a location titled "Home": `sensor.spc_home_day_{1,2,3}_risk`, `sensor.spc_home_max_risk_next_3_days`, `sensor.spc_home_day_{1,2}_{tornado,wind,hail}_probability`, `sensor.spc_home_day_3_severe_probability`, `sensor.spc_home_day_{4..8}_severe_probability`, `binary_sensor.spc_home_mesoscale_discussion`. There are no per-location watch entities.
  - `sensor.py` exports `async_setup_entry`, `LOCATION_SENSORS`; Task 14 extends it with hub sensors.

- [ ] **Step 1: Add `setup_entry` to `tests/factories.py`**

Append:
```python
async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
```

- [ ] **Step 2: Write failing tests**

`tests/test_location_entities.py`:
```python
from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.noaa_spc.const import (
    CONF_GROUPS,
    DOMAIN,
    ENTRY_TYPE_HUB,
    GROUP_CATEGORICAL,
)
from custom_components.noaa_spc.hub import get_hub
from tests.factories import (
    alert_bundle,
    fixed_entry,
    make_md,
    outlook_bundle,
    risk_layers,
    setup_entry,
)
from tests.helpers import collection


async def test_setup_creates_hub_entry_and_location_entities(
    hass: HomeAssistant, mock_api
) -> None:
    mock_api.alerts = alert_bundle(mds=[make_md(2104)])
    entry = fixed_entry()
    await setup_entry(hass, entry)

    hubs = [e for e in hass.config_entries.async_entries(DOMAIN)
            if e.data.get("entry_type") == ENTRY_TYPE_HUB]
    assert len(hubs) == 1
    assert hubs[0].state is ConfigEntryState.LOADED

    day1 = hass.states.get("sensor.spc_home_day_1_risk")
    assert day1.state == "SLGT"
    assert day1.attributes["level"] == 3
    assert day1.attributes["label"] == "Slight Risk"
    assert day1.attributes["forecaster"] == "Smith"
    assert day1.attributes["issued"] == "2026-10-13T12:52:00+00:00"
    assert day1.attributes["data_age"] is not None
    assert hass.states.get("sensor.spc_home_day_2_risk").state == "MRGL"
    assert hass.states.get("sensor.spc_home_day_3_risk").state == "none"

    peak = hass.states.get("sensor.spc_home_max_risk_next_3_days")
    assert (peak.state, peak.attributes["day"]) == ("SLGT", 1)

    torn = hass.states.get("sensor.spc_home_day_1_tornado_probability")
    assert torn.state == "5"
    assert torn.attributes["significant"] is True
    assert torn.attributes["unit_of_measurement"] == "%"
    wind = hass.states.get("sensor.spc_home_day_1_wind_probability")
    assert (wind.state, wind.attributes["significant"]) == ("15", False)
    assert hass.states.get("sensor.spc_home_day_3_severe_probability").state == "5"
    assert hass.states.get("sensor.spc_home_day_4_severe_probability").state == "15"
    day5 = hass.states.get("sensor.spc_home_day_5_severe_probability")
    assert (day5.state, day5.attributes["predictability_too_low"]) == ("0", True)
    # Layers absent from the bundle are unavailable, not zero.
    assert (
        hass.states.get("sensor.spc_home_day_2_tornado_probability").state
        == STATE_UNAVAILABLE
    )

    md = hass.states.get("binary_sensor.spc_home_mesoscale_discussion")
    assert md.state == "on"
    assert md.attributes["number"] == 2104
    assert md.attributes["concerning"] == "Severe potential...Watch likely"
    assert len(md.attributes["items"]) == 1
    assert hass.states.get("binary_sensor.spc_home_tornado_watch") is None


async def test_empty_layer_with_stale_metadata_is_none_and_available(
    hass: HomeAssistant, mock_api
) -> None:
    layers = risk_layers()
    layers["day1_cat"] = collection()
    mock_api.outlooks = outlook_bundle(layers)
    await setup_entry(hass, fixed_entry())
    state = hass.states.get("sensor.spc_home_day_1_risk")
    assert state.state == "none"


async def test_outlook_entities_go_unavailable_when_stale(
    hass: HomeAssistant, mock_api, freezer
) -> None:
    await setup_entry(hass, fixed_entry())
    assert hass.states.get("sensor.spc_home_day_1_risk").state == "SLGT"

    freezer.tick(timedelta(minutes=16))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get("sensor.spc_home_day_1_risk").state == "SLGT"
    assert (
        hass.states.get("binary_sensor.spc_home_mesoscale_discussion").state
        == STATE_UNAVAILABLE
    )

    freezer.tick(timedelta(hours=3))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get("sensor.spc_home_day_1_risk").state == STATE_UNAVAILABLE


async def test_disabled_groups_create_no_entities(hass: HomeAssistant, mock_api) -> None:
    await setup_entry(hass, fixed_entry(options={CONF_GROUPS: [GROUP_CATEGORICAL]}))
    assert hass.states.get("sensor.spc_home_day_1_risk") is not None
    assert hass.states.get("sensor.spc_home_day_1_tornado_probability") is None
    assert hass.states.get("binary_sensor.spc_home_mesoscale_discussion") is None


async def test_unloading_all_entries_stops_hub(hass: HomeAssistant, mock_api) -> None:
    entry = fixed_entry()
    await setup_entry(hass, entry)
    assert get_hub(hass) is not None
    for config_entry in hass.config_entries.async_entries(DOMAIN):
        assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert get_hub(hass) is None


async def test_entities_belong_to_location_device(hass: HomeAssistant, mock_api) -> None:
    entry = fixed_entry()
    await setup_entry(hass, entry)
    registry = er.async_get(hass)
    reg_entry = registry.async_get("sensor.spc_home_day_1_risk")
    assert reg_entry.unique_id == f"{entry.entry_id}_day1_risk"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_location_entities.py -v`
Expected: FAIL — entry setup fails / `hass.states.get(...)` returns `None` because `__init__.py` has no `async_setup_entry`.

- [ ] **Step 4: Replace `__init__.py`**

```python
"""The NOAA Storm Prediction Center integration."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.typing import ConfigType

from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_HUB, ISSUE_MISSING_TRACKER
from .hub import async_acquire_hub, async_release_hub, is_hub_entry
from .location import LocationCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

HUB_PLATFORMS = [Platform.SENSOR]
LOCATION_PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    if not any(is_hub_entry(e) for e in hass.config_entries.async_entries(DOMAIN)):
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_IMPORT},
                data={CONF_ENTRY_TYPE: ENTRY_TYPE_HUB},
            )
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hub = await async_acquire_hub(hass)
    if is_hub_entry(entry):
        hub.apply_options(entry.options)
        entry.runtime_data = hub
        platforms = HUB_PLATFORMS
    else:
        coordinator = LocationCoordinator(hass, entry, hub)
        await coordinator.async_start()
        entry.runtime_data = coordinator
        platforms = LOCATION_PLATFORMS
    await hass.config_entries.async_forward_entry_setups(entry, platforms)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    platforms = HUB_PLATFORMS if is_hub_entry(entry) else LOCATION_PLATFORMS
    unloaded = await hass.config_entries.async_unload_platforms(entry, platforms)
    if unloaded:
        await async_release_hub(hass)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_MISSING_TRACKER}_{entry.entry_id}")
```

- [ ] **Step 5: Create `entity.py`**

```python
"""Shared entity helpers for NOAA SPC."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.util import dt as dt_util

from .api.models import MesoscaleDiscussion, Watch
from .const import DOMAIN, MANUFACTURER, SPC_SITE
from .location import LocationCoordinator


def is_fresh(timestamp: datetime | None, max_age: timedelta) -> bool:
    return timestamp is not None and dt_util.utcnow() - timestamp <= max_age


def data_age(timestamp: datetime | None) -> int | None:
    if timestamp is None:
        return None
    return int((dt_util.utcnow() - timestamp).total_seconds())


def watch_attributes(watch: Watch) -> dict[str, Any]:
    return {
        "number": watch.number,
        "type": watch.kind,
        "pds": watch.pds,
        "url": watch.url,
    }


def md_attributes(md: MesoscaleDiscussion) -> dict[str, Any]:
    return {
        "number": md.number,
        "areas_affected": md.areas_affected,
        "concerning": md.concerning,
        "watch_probability": md.watch_probability,
        "summary": md.summary,
        "url": md.url,
    }


def async_remove_entities(
    hass: HomeAssistant, domain: str, unique_ids: Iterable[str]
) -> None:
    registry = er.async_get(hass)
    for unique_id in unique_ids:
        if entity_id := registry.async_get_entity_id(domain, DOMAIN, unique_id):
            registry.async_remove(entity_id)


class SpcLocationEntity(CoordinatorEntity[LocationCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: LocationCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"SPC – {entry.title}",
            manufacturer=MANUFACTURER,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=SPC_SITE,
        )


class SpcHubEntity(CoordinatorEntity[DataUpdateCoordinator[Any]]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: DataUpdateCoordinator[Any], key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"hub_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hub")},
            name="NOAA SPC",
            manufacturer=MANUFACTURER,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=SPC_SITE,
        )
```

- [ ] **Step 6: Create `sensor.py`**

```python
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
        _probability(f"day{day}_{hazard}", f"day{day}_{name}", f"Day {day} {name} probability")
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
            and is_fresh(data.updated.get(self.entity_description.source), OUTLOOK_STALE)
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
```

- [ ] **Step 7: Create `binary_sensor.py`**

```python
"""Binary sensor platform for NOAA SPC mesoscale discussions."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ALERT_STALE, GROUP_ALERTS
from .entity import (
    SpcLocationEntity,
    async_remove_entities,
    data_age,
    is_fresh,
    md_attributes,
)
from .location import LocationCoordinator

MD_KEY = "mesoscale_discussion"


class MesoscaleDiscussionBinarySensor(SpcLocationEntity, BinarySensorEntity):
    _attr_name = "Mesoscale discussion"
    _unrecorded_attributes = frozenset({"summary", "items"})

    def __init__(self, coordinator: LocationCoordinator) -> None:
        super().__init__(coordinator, MD_KEY)

    def _items(self) -> list[dict[str, Any]]:
        return [md_attributes(md) for md in self.coordinator.data.alerts.mds]

    @property
    def available(self) -> bool:
        data = self.coordinator.data
        return (
            super().available
            and data is not None
            and data.position is not None
            and data.alerts is not None
            and is_fresh(data.mds_updated, ALERT_STALE)
        )

    @property
    def is_on(self) -> bool:
        return bool(self._items())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        items = self._items()
        return {
            **(items[0] if items else {}),
            "items": items,
            "data_age": data_age(self.coordinator.data.mds_updated),
        }


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: LocationCoordinator = entry.runtime_data
    if GROUP_ALERTS not in coordinator.groups:
        async_remove_entities(hass, Platform.BINARY_SENSOR, [f"{entry.entry_id}_{MD_KEY}"])
        return
    async_add_entities([MesoscaleDiscussionBinarySensor(coordinator)])
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `.venv/bin/pytest tests -v` — Expected: all pass (including Task 12's config flow tests, which patch `async_setup`/`async_setup_entry`).

- [ ] **Step 9: Commit**

```bash
git add custom_components/noaa_spc tests/factories.py tests/test_location_entities.py
git commit -m "Set up integration with location sensors and MD binary sensor"
```

---

### Task 14: Hub sensors and outlook images

**Files:**
- Modify: `custom_components/noaa_spc/sensor.py` (hub branch), `custom_components/noaa_spc/__init__.py:16` (`HUB_PLATFORMS`)
- Create: `custom_components/noaa_spc/image.py`
- Test: `tests/test_hub_entities.py`

**Interfaces:**
- Consumes: `SpcHubEntity`, `is_fresh`, `data_age`, `watch_attributes`, `md_attributes` (Task 13); `IMAGE_PATHS` (Task 3); `SpcHub` (Task 10).
- Produces: hub entity ids `sensor.noaa_spc_day_{1,2,3}_discussion`, `sensor.noaa_spc_day_4_8_discussion`, `sensor.noaa_spc_active_watches` (national pulse check: state = number of active watches; attributes `tornado`, `severe_thunderstorm`, `pds` counts and `items`), `sensor.noaa_spc_active_mesoscale_discussions`, `image.noaa_spc_day_{1,2,3}_outlook`, `image.noaa_spc_day_4_8_outlook`, and disabled-by-default `image.noaa_spc_day_{1,2}_{tornado,wind,hail}_outlook`.

- [ ] **Step 1: Write failing tests**

`tests/test_hub_entities.py`:
```python
from http import HTTPStatus

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.noaa_spc.api.models import TextProduct
from tests.factories import (
    alert_bundle,
    fixed_entry,
    make_md,
    make_watch,
    outlook_bundle,
    risk_layers,
    setup_entry,
)

TEXT = TextProduct(text="Full discussion", summary="Storms today.", forecaster="Smith")


async def test_hub_sensors(hass: HomeAssistant, mock_api) -> None:
    mock_api.outlooks = outlook_bundle(risk_layers(), texts={"day1": TEXT})
    mock_api.alerts = alert_bundle([make_watch(612, pds=True), make_watch(613, "severe_thunderstorm")],
                                   [make_md(2104)])
    await setup_entry(hass, fixed_entry())

    day1 = hass.states.get("sensor.noaa_spc_day_1_discussion")
    assert day1.state == "2026-10-13T12:52:00+00:00"
    assert day1.attributes["summary"] == "Storms today."
    assert day1.attributes["text"] == "Full discussion"
    assert day1.attributes["forecaster"] == "Smith"
    # day2 text was never fetched -> unavailable
    assert hass.states.get("sensor.noaa_spc_day_2_discussion").state == "unavailable"

    watches = hass.states.get("sensor.noaa_spc_active_watches")
    assert watches.state == "2"
    assert [i["number"] for i in watches.attributes["items"]] == [612, 613]
    assert watches.attributes["tornado"] == 1
    assert watches.attributes["severe_thunderstorm"] == 1
    assert watches.attributes["pds"] == 1
    assert hass.states.get("sensor.noaa_spc_active_mesoscale_discussions").state == "1"


async def test_outlook_images(hass: HomeAssistant, mock_api, hass_client) -> None:
    mock_api.outlooks = outlook_bundle(
        risk_layers(), images={"day1": b"\x89PNGday1", "day48": b"GIF89a"}
    )
    await setup_entry(hass, fixed_entry())

    state = hass.states.get("image.noaa_spc_day_1_outlook")
    assert state is not None and state.state != "unavailable"
    client = await hass_client()
    resp = await client.get("/api/image_proxy/image.noaa_spc_day_1_outlook")
    assert resp.status == HTTPStatus.OK
    assert await resp.read() == b"\x89PNGday1"
    assert resp.content_type == "image/png"

    resp = await client.get("/api/image_proxy/image.noaa_spc_day_4_8_outlook")
    assert resp.content_type == "image/gif"

    registry = er.async_get(hass)
    hazard = registry.async_get("image.noaa_spc_day_1_tornado_outlook")
    assert hazard is not None and hazard.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get("image.noaa_spc_day_2_outlook").state == "unavailable"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_hub_entities.py -v`
Expected: FAIL — `hass.states.get("sensor.noaa_spc_day_1_discussion")` is `None`.

- [ ] **Step 3: Add hub sensors to `sensor.py`**

Add imports:
```python
from datetime import datetime, timedelta

from .const import ALERT_STALE
from .entity import SpcHubEntity, md_attributes, watch_attributes
from .hub import SpcHub
```
(merge into the existing import lines; `OUTLOOK_STALE` is already imported).

Add before `async_setup_entry`:
```python
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
        return layer.issued if layer else None

    def attrs(bundle: Any) -> dict[str, Any]:
        text = bundle.texts.get(text_key)
        if text is None:
            return {}
        return {"text": text.text, "summary": text.summary, "forecaster": text.forecaster}

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
            and is_fresh(self.entity_description.updated_fn(data),
                         self.entity_description.max_age)
        )

    @property
    def native_value(self) -> StateType | datetime:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return {
            **self.entity_description.attrs_fn(data),
            "data_age": data_age(self.entity_description.updated_fn(data)),
        }
```

Replace the hub early-return in `async_setup_entry`:
```python
    if is_hub_entry(entry):
        hub: SpcHub = entry.runtime_data
        async_add_entities(HubSensor(hub, d) for d in HUB_SENSORS)
        return
```

- [ ] **Step 4: Create `image.py`**

```python
"""Outlook map images for NOAA SPC."""

from __future__ import annotations

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .api.products import IMAGE_PATHS
from .const import OUTLOOK_STALE
from .entity import SpcHubEntity, is_fresh
from .hub import OutlookCoordinator, SpcHub

HAZARD_NAMES = {"torn": "tornado", "wind": "wind", "hail": "hail"}


def _name(key: str) -> str:
    if key == "day48":
        return "Day 4–8 outlook"
    day, _, hazard = key.partition("_")
    number = day.removeprefix("day")
    return f"Day {number} {HAZARD_NAMES[hazard]} outlook" if hazard else f"Day {number} outlook"


class SpcImage(SpcHubEntity, ImageEntity):
    coordinator: OutlookCoordinator

    def __init__(self, hass: HomeAssistant, coordinator: OutlookCoordinator, key: str) -> None:
        SpcHubEntity.__init__(self, coordinator, f"image_{key}")
        ImageEntity.__init__(self, hass)
        self._key = key
        self._attr_name = _name(key)
        self._attr_content_type = IMAGE_PATHS[key][1]
        self._attr_entity_registry_enabled_default = "_" not in key
        self._image: bytes | None = None
        self._sync()

    def _sync(self) -> None:
        data = self.coordinator.data
        image = data.images.get(self._key) if data else None
        if image is not None and image != self._image:
            self._image = image
            self._attr_image_last_updated = dt_util.utcnow()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._sync()
        super()._handle_coordinator_update()

    @property
    def available(self) -> bool:
        data = self.coordinator.data
        return (
            super().available
            and data is not None
            and self._image is not None
            and is_fresh(data.updated.get(f"image:{self._key}"), OUTLOOK_STALE)
        )

    async def async_image(self) -> bytes | None:
        return self._image


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: SpcHub = entry.runtime_data
    async_add_entities(SpcImage(hass, hub.outlooks, key) for key in IMAGE_PATHS)
```

- [ ] **Step 5: Add the image platform to the hub**

In `custom_components/noaa_spc/__init__.py` change:
```python
HUB_PLATFORMS = [Platform.SENSOR]
```
to:
```python
HUB_PLATFORMS = [Platform.IMAGE, Platform.SENSOR]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests -v` — Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add custom_components/noaa_spc tests/test_hub_entities.py
git commit -m "Add national discussion sensors and outlook map images"
```

---

### Task 15: Options flows

**Files:**
- Modify: `custom_components/noaa_spc/config_flow.py`
- Test: `tests/test_options_flow.py`

**Interfaces:**
- Consumes: Task 12 flow, Task 13 setup (reload on options change).
- Produces: `HubOptionsFlow` (step `hub`: `outlook_interval_min` 2–60, `alert_interval_min` 1–30); `LocationOptionsFlow` (step `location`: `location` for fixed or `tracked_entity` + `move_threshold_km` 0.1–50 for tracked, plus `groups` multi-select). Fixed location options are stored as `latitude`/`longitude`.

- [ ] **Step 1: Write failing tests**

`tests/test_options_flow.py`:
```python
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.noaa_spc.const import DOMAIN, GROUP_CATEGORICAL
from custom_components.noaa_spc.hub import get_hub, is_hub_entry
from tests.factories import fixed_entry, setup_entry, tracked_entry


async def test_hub_options_change_intervals(hass: HomeAssistant, mock_api) -> None:
    await setup_entry(hass, fixed_entry())
    hub_entry = next(e for e in hass.config_entries.async_entries(DOMAIN) if is_hub_entry(e))

    result = await hass.config_entries.options.async_init(hub_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "hub"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"outlook_interval_min": 10, "alert_interval_min": 1}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    hub = get_hub(hass)
    assert hub.outlooks.update_interval == timedelta(minutes=10)
    assert hub.alerts.update_interval == timedelta(minutes=1)


async def test_fixed_location_options_move_and_drop_groups(
    hass: HomeAssistant, mock_api
) -> None:
    entry = fixed_entry()
    await setup_entry(hass, entry)
    assert er.async_get(hass).async_get("binary_sensor.spc_home_mesoscale_discussion")

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "location"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "location": {"latitude": 36.0, "longitude": -96.0},
            "groups": [GROUP_CATEGORICAL],
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        "latitude": 36.0,
        "longitude": -96.0,
        "groups": [GROUP_CATEGORICAL],
    }
    await hass.async_block_till_done()

    coordinator = entry.runtime_data
    assert coordinator.data.position == (36.0, -96.0)
    assert coordinator.groups == {GROUP_CATEGORICAL}
    assert er.async_get(hass).async_get("binary_sensor.spc_home_mesoscale_discussion") is None
    assert er.async_get(hass).async_get("sensor.spc_home_day_1_tornado_probability") is None


async def test_tracked_location_options(hass: HomeAssistant, mock_api) -> None:
    hass.states.async_set("device_tracker.phone", "home", {"latitude": 35.2, "longitude": -97.4})
    hass.states.async_set("person.alex", "home", {"latitude": 36.0, "longitude": -96.0})
    entry = tracked_entry()
    await setup_entry(hass, entry)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "tracked_entity": "person.alex",
            "move_threshold_km": 5,
            "groups": ["categorical", "alerts"],
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    assert coordinator.tracked_entity == "person.alex"
    assert coordinator.threshold_m == 5000
    assert coordinator.data.position == (36.0, -96.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_options_flow.py -v`
Expected: FAIL — `UnknownHandler` / options flow not supported for this entry.

- [ ] **Step 3: Implement the options flows**

Add to the imports in `config_flow.py`:
```python
from homeassistant.config_entries import ConfigEntry, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
)

from .const import (
    ALL_GROUPS,
    CONF_ALERT_INTERVAL,
    CONF_GROUPS,
    CONF_MOVE_THRESHOLD_KM,
    CONF_OUTLOOK_INTERVAL,
    DEFAULT_ALERT_INTERVAL,
    DEFAULT_MOVE_THRESHOLD_KM,
    DEFAULT_OUTLOOK_INTERVAL,
)
```
(merge with the existing import statements).

Add inside `SpcConfigFlow`:
```python
    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        if config_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB:
            return HubOptionsFlow()
        return LocationOptionsFlow()
```

Append to the module:
```python
def _minutes(minimum: int, maximum: int) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=1,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="min",
        )
    )


class HubOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_hub()

    async def async_step_hub(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_OUTLOOK_INTERVAL,
                    default=options.get(CONF_OUTLOOK_INTERVAL, DEFAULT_OUTLOOK_INTERVAL),
                ): _minutes(2, 60),
                vol.Required(
                    CONF_ALERT_INTERVAL,
                    default=options.get(CONF_ALERT_INTERVAL, DEFAULT_ALERT_INTERVAL),
                ): _minutes(1, 30),
            }
        )
        return self.async_show_form(step_id="hub", data_schema=schema)


class LocationOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_location()

    async def async_step_location(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        conf = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            data = dict(user_input)
            if CONF_LOCATION in data:
                location = data.pop(CONF_LOCATION)
                data[CONF_LATITUDE] = float(location[CONF_LATITUDE])
                data[CONF_LONGITUDE] = float(location[CONF_LONGITUDE])
            return self.async_create_entry(data=data)

        fields: dict[Any, Any] = {}
        if conf[CONF_MODE] == MODE_FIXED:
            fields[
                vol.Required(
                    CONF_LOCATION,
                    default={
                        CONF_LATITUDE: conf[CONF_LATITUDE],
                        CONF_LONGITUDE: conf[CONF_LONGITUDE],
                    },
                )
            ] = LocationSelector(LocationSelectorConfig(radius=False))
        else:
            fields[
                vol.Required(CONF_TRACKED_ENTITY, default=conf[CONF_TRACKED_ENTITY])
            ] = EntitySelector(EntitySelectorConfig(domain=TRACKABLE_DOMAINS))
            fields[
                vol.Required(
                    CONF_MOVE_THRESHOLD_KM,
                    default=conf.get(CONF_MOVE_THRESHOLD_KM, DEFAULT_MOVE_THRESHOLD_KM),
                )
            ] = NumberSelector(
                NumberSelectorConfig(
                    min=0.1,
                    max=50,
                    step=0.1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="km",
                )
            )
        fields[vol.Required(CONF_GROUPS, default=conf.get(CONF_GROUPS, ALL_GROUPS))] = (
            SelectSelector(
                SelectSelectorConfig(
                    options=ALL_GROUPS, multiple=True, translation_key="groups"
                )
            )
        )
        return self.async_show_form(step_id="location", data_schema=vol.Schema(fields))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests -v` — Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/noaa_spc/config_flow.py tests/test_options_flow.py
git commit -m "Add hub and location options flows"
```

---

### Task 16: Notification blueprint and README

**Files:**
- Create: `blueprints/automation/noaa_spc/notify_severe_risk.yaml`
- Modify: `README.md`
- Test: `tests/test_blueprint.py`

**Interfaces:**
- Consumes: event names and payloads from Task 11.
- Produces: blueprint inputs `location`, `threshold`, `days`, `include_mds`, `notify`; variable `message` available to `notify` actions.

- [ ] **Step 1: Write failing test**

`tests/test_blueprint.py`:
```python
from pathlib import Path

from homeassistant.components.blueprint.models import Blueprint
from homeassistant.components.blueprint.schemas import BLUEPRINT_SCHEMA
from homeassistant.util.yaml import load_yaml_dict

PATH = Path(__file__).parent.parent / "blueprints/automation/noaa_spc/notify_severe_risk.yaml"


def test_blueprint_is_valid() -> None:
    blueprint = Blueprint(
        load_yaml_dict(str(PATH)), expected_domain="automation", schema=BLUEPRINT_SCHEMA
    )
    assert blueprint.domain == "automation"
    assert set(blueprint.inputs) == {
        "location", "threshold", "days", "include_mds", "notify",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_blueprint.py -v`
Expected: FAIL — `FileNotFoundError` for the blueprint path.

- [ ] **Step 3: Write the blueprint**

`blueprints/automation/noaa_spc/notify_severe_risk.yaml`:
```yaml
blueprint:
  name: "NOAA SPC: notify on severe weather"
  description: >-
    Runs your notification actions when the SPC categorical risk for a location
    rises to a chosen level, or when an SPC mesoscale discussion newly covers it.
    Use the `message` variable in your actions, for example
    `message: "{{ message }}"`.
  domain: automation
  source_url: https://github.com/majoragee/hassio-noaa-spc/blob/main/blueprints/automation/noaa_spc/notify_severe_risk.yaml
  input:
    location:
      name: SPC location
      selector:
        config_entry:
          integration: noaa_spc
    threshold:
      name: Minimum categorical risk
      default: "4"
      selector:
        select:
          options:
            - label: "TSTM – General thunderstorms"
              value: "1"
            - label: "MRGL – Marginal (1/5)"
              value: "2"
            - label: "SLGT – Slight (2/5)"
              value: "3"
            - label: "ENH – Enhanced (3/5)"
              value: "4"
            - label: "MDT – Moderate (4/5)"
              value: "5"
            - label: "HIGH – High (5/5)"
              value: "6"
    days:
      name: Outlook days
      default: ["1", "2", "3"]
      selector:
        select:
          multiple: true
          options:
            - label: Day 1
              value: "1"
            - label: Day 2
              value: "2"
            - label: Day 3
              value: "3"
    include_mds:
      name: Notify on new mesoscale discussions
      default: true
      selector:
        boolean: {}
    notify:
      name: Notification actions
      description: Actions to run. The text is available as `{{ message }}`.
      selector:
        action: {}

mode: queued

triggers:
  - trigger: event
    event_type: noaa_spc_risk_changed
    event_data:
      config_entry_id: !input location
    id: risk
  - trigger: event
    event_type: noaa_spc_md_issued
    event_data:
      config_entry_id: !input location
    id: md

variables:
  threshold: !input threshold
  days: !input days
  include_mds: !input include_mds
  message: >-
    {% set e = trigger.event.data %}
    {% if trigger.id == 'risk' %}
    Day {{ e.day }} SPC risk for {{ e.location_name }} upgraded to {{ e.new }} (was {{ e.old }}).
    {% else %}
    SPC Mesoscale Discussion #{{ e.number }} covers {{ e.location_name }}: {{ e.concerning }}{% if e.watch_probability is not none %} (watch probability {{ e.watch_probability }}%){% endif %}.
    {% endif %}

conditions:
  - condition: template
    value_template: >-
      {% set e = trigger.event.data %}
      {% if trigger.id == 'risk' %}
      {{ e.upgraded and e.new_level >= (threshold | int) and (e.day | string) in days }}
      {% else %}
      {{ include_mds }}
      {% endif %}

actions: !input notify
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_blueprint.py -v` — Expected: 1 passed.

- [ ] **Step 5: Write the README**

Replace `README.md` with sections (write the prose; keep it factual):
1. **What it does** — national SPC outlook maps/discussions; per-location Day 1–3 categorical risk, Day 1–2 tornado/wind/hail and Day 3 any-severe probabilities with significant flags, Day 4–8 probabilities and mesoscale discussions; national active-watch count; events; blueprint. State plainly that location-specific watches/warnings are out of scope and belong to an NWS alerts integration.
2. **Installation** — HACS → Custom repositories → add `https://github.com/majoragee/hassio-noaa-spc` (category Integration) → install → restart; or copy `custom_components/noaa_spc` manually.
3. **Setup** — Settings → Devices & services → Add integration → "NOAA Storm Prediction Center" → Fixed or Tracked. The "NOAA SPC" hub entry is created automatically.
4. **Entities** — table of location entities (ids from Task 13 Produces) and hub entities (ids from Task 14 Produces) with state and key attributes.
5. **Events** — the two event types with every payload field (from Task 11 Produces).
6. **Blueprint** — import link `https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fmajoragee%2Fhassio-noaa-spc%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fnoaa_spc%2Fnotify_severe_risk.yaml` and an example notify action using `{{ message }}`.
7. **Data sources and limits** — SPC products only (`spc.noaa.gov`, including the `spcwwrss.xml` watch feed for the national count); CONUS only; polling defaults; staleness rules.
8. **Disclaimer** — not affiliated with NOAA/NWS; not for life-safety decisions; always heed official warnings.

- [ ] **Step 6: Commit**

```bash
git add blueprints README.md tests/test_blueprint.py
git commit -m "Add severe weather notification blueprint and README"
```

---

### Task 17: Real-data fixtures and end-to-end smoke test

**Files:**
- Create: `tests/fixtures/live/` (captured files), `tests/api/test_live_fixtures.py`, `tests/test_end_to_end.py`

**Interfaces:**
- Consumes: everything above.
- Produces: regression coverage against real SPC payloads.

- [ ] **Step 1: Capture fixtures**

Run from the repo root (writes only into `tests/fixtures/live/`):
```bash
UA="hassio-noaa-spc/0.1.0 (https://github.com/majoragee/hassio-noaa-spc)"
D=tests/fixtures/live; mkdir -p $D/layers $D/text
B=https://www.spc.noaa.gov/products
for f in day1otlk_cat day1otlk_torn day1otlk_wind day1otlk_hail day1otlk_sigtorn day1otlk_sigwind day1otlk_sighail \
         day2otlk_cat day2otlk_torn day2otlk_wind day2otlk_hail day2otlk_sigtorn day2otlk_sigwind day2otlk_sighail \
         day3otlk_cat day3otlk_prob day3otlk_sigprob; do
  curl -sf -A "$UA" "$B/outlook/$f.lyr.geojson" -o "$D/layers/$f.lyr.geojson"; done
for d in 4 5 6 7 8; do curl -sf -A "$UA" "$B/exper/day4-8/day${d}prob.lyr.geojson" -o "$D/layers/day${d}prob.lyr.geojson"; done
for d in 1 2 3; do curl -sf -A "$UA" "$B/outlook/day${d}otlk.txt" -o "$D/text/day${d}otlk.txt"; done
curl -sf -A "$UA" "$B/exper/day4-8/" -o "$D/text/day48.html"
curl -sf -A "$UA" "$B/md/2026/md2104.html" -o "$D/md2104.html"
curl -sf -A "$UA" "$B/spcwwrss.xml" -o "$D/spcwwrss.xml"
ls -R $D | head -50
```
Expected: 22 layer files, 4 text files, `md2104.html`, `spcwwrss.xml`. The watch feed is captured as-is; on a quiet day it holds only the "No watches are valid" placeholder, which is still a useful regression fixture. If watches happen to be active when you capture, also save a copy as `$D/spcwwrss_active.xml` and report the item titles/links in your task summary so the Task 6 assumptions can be confirmed.

- [ ] **Step 2: Write live-fixture parser tests**

`tests/api/test_live_fixtures.py`:
```python
import json
from pathlib import Path

import pytest

from custom_components.noaa_spc.api.geometry import point_in_polygon
from custom_components.noaa_spc.api.mds import parse_md_page
from custom_components.noaa_spc.api.models import RiskLevel
from custom_components.noaa_spc.api.outlooks import categorical_at, parse_layer
from custom_components.noaa_spc.api.text import parse_text_product
from custom_components.noaa_spc.api.watches import parse_watch_feed

LIVE = Path(__file__).parent.parent / "fixtures" / "live"


@pytest.mark.parametrize("path", sorted((LIVE / "layers").glob("*.geojson")), ids=str)
def test_every_live_layer_parses(path: Path) -> None:
    layer = parse_layer(json.loads(path.read_text()))
    assert layer.issued is not None
    categorical_at(layer, 35.22, -97.44)


def test_live_layer_count() -> None:
    assert len(list((LIVE / "layers").glob("*.geojson"))) == 22


@pytest.mark.parametrize("name", ["day1otlk.txt", "day2otlk.txt", "day3otlk.txt", "day48.html"])
def test_live_text_has_summary_and_forecaster(name: str) -> None:
    product = parse_text_product((LIVE / "text" / name).read_text())
    assert product.summary
    assert product.forecaster


def test_live_md() -> None:
    md = parse_md_page((LIVE / "md2104.html").read_text(), "https://example/md2104.html")
    assert md.number == 2104
    assert md.watch_probability == 80
    assert point_in_polygon(-107.0, 47.0, md.polygon)


def test_live_watch_feed() -> None:
    raw = (LIVE / "spcwwrss.xml").read_bytes()
    watches = parse_watch_feed(raw)
    if b"No watches are valid" in raw:
        assert watches == ()
    else:
        assert watches
        assert all(w.number > 0 and w.url.endswith(".html") for w in watches)


def test_risk_level_labels_in_live_categorical_layers_are_known() -> None:
    for path in (LIVE / "layers").glob("day*otlk_cat.lyr.geojson"):
        for area in parse_layer(json.loads(path.read_text())).areas:
            assert RiskLevel.from_label(area.label) is not None, area.label
```

- [ ] **Step 3: Write the end-to-end test**

`tests/test_end_to_end.py`:
```python
from pathlib import Path

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant

from custom_components.noaa_spc.api.products import (
    IMAGE_PATHS,
    LAYER_PATHS,
    MD_FEED_PATH,
    SPC_BASE,
    TEXT_PATHS,
    WATCH_FEED_PATH,
)
from custom_components.noaa_spc.api.watches import parse_watch_feed
from tests.factories import fixed_entry, setup_entry

LIVE = Path(__file__).parent / "fixtures" / "live"
MD_URL = "https://www.spc.noaa.gov/products/md/md2104.html"
POINT = (47.0, -107.0)  # inside MD 2104


async def test_full_setup_against_live_payloads(hass: HomeAssistant, aioclient_mock) -> None:
    for path in LAYER_PATHS.values():
        name = path.rsplit("/", 1)[-1]
        aioclient_mock.get(SPC_BASE + path, text=(LIVE / "layers" / name).read_text())
    text_files = {"day1": "day1otlk.txt", "day2": "day2otlk.txt",
                  "day3": "day3otlk.txt", "day48": "day48.html"}
    for key, path in TEXT_PATHS.items():
        aioclient_mock.get(SPC_BASE + path, text=(LIVE / "text" / text_files[key]).read_text())
    for key, (path, _) in IMAGE_PATHS.items():
        aioclient_mock.get(SPC_BASE + path, content=b"IMG" + key.encode())

    watch_feed = (LIVE / "spcwwrss.xml").read_text()
    aioclient_mock.get(SPC_BASE + WATCH_FEED_PATH, text=watch_feed)
    aioclient_mock.get(
        SPC_BASE + MD_FEED_PATH,
        text=f'<rss version="2.0"><channel><item><link>{MD_URL}</link></item></channel></rss>',
    )
    aioclient_mock.get(MD_URL, text=(LIVE / "md2104.html").read_text())

    await setup_entry(hass, fixed_entry(*POINT, title="Home"))

    for entity_id in (
        "sensor.spc_home_day_1_risk",
        "sensor.spc_home_day_2_risk",
        "sensor.spc_home_day_3_risk",
        "sensor.spc_home_max_risk_next_3_days",
        "sensor.spc_home_day_1_tornado_probability",
        "sensor.spc_home_day_3_severe_probability",
        "sensor.spc_home_day_8_severe_probability",
        "sensor.noaa_spc_day_1_discussion",
        "sensor.noaa_spc_day_4_8_discussion",
        "image.noaa_spc_day_1_outlook",
    ):
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        assert state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN), entity_id

    assert hass.states.get("binary_sensor.spc_home_mesoscale_discussion").state == "on"
    expected_watches = len(parse_watch_feed(watch_feed))
    assert hass.states.get("sensor.noaa_spc_active_watches").state == str(expected_watches)
    assert not any(
        "watch" in state.entity_id for state in hass.states.async_all("binary_sensor")
    )
```

- [ ] **Step 4: Run the full suite and lint**

Run: `.venv/bin/pytest -v` — Expected: all pass.
Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check .` — Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures tests/api/test_live_fixtures.py tests/test_end_to_end.py
git commit -m "Add live SPC fixtures and end-to-end smoke test"
```

---

## Spec coverage map

| Spec section | Tasks |
|---|---|
| §2 Data sources | 3, 5, 6, 7, 8, 17 |
| §3 Architecture (hub + per-location, api/ HA-free) | 8, 10, 11, 13 |
| §4 Per-location sensors/MD binary sensor/groups | 13, 15 |
| §4 Events + baseline + dedupe | 11 |
| §4 Location resolution, threshold, unavailable without coords | 11 |
| §5 Hub entities (incl. national watch count), images, recorder exclusions | 6, 13, 14 |
| §5 Hub options | 10, 15 |
| §6 Config flow, CONUS warning, duplicates, hub auto-create | 12, 13 |
| §7 Error handling (stale, malformed, empty, repairs, startup) | 8, 11, 13 |
| §8 Layout, CI, no deps | 1, 17 |
| §9 Blueprint | 16 |
| §10 Testing | all |

Note: entity ids follow Home Assistant's `has_entity_name` slugging (e.g. `sensor.spc_home_day_1_tornado_probability` rather than the spec's shorthand `sensor.<loc>_day1_tornado`); unique ids use the spec keys (`day1_tornado`).
