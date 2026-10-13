# NOAA SPC Home Assistant Integration — Design

Date: 2026-10-13
Status: Draft for review

## 1. Purpose

A Home Assistant custom integration (`noaa_spc`, distributed via HACS) that:

1. Pulls national NOAA Storm Prediction Center (SPC) products — outlook maps and
   forecaster discussion text — for dashboard display and spoken/LLM briefings.
2. Tracks the categorical and probabilistic convective risk, plus active
   mesoscale discussions (MDs), for one or more locations. A location is
   either fixed (lat/lon) or follows a `device_tracker`, `person`, or `zone`
   entity.
3. Reports a national count of active SPC watches as a pulse check on the day's
   storm activity.

The integration is scoped to SPC products and talks only to `spc.noaa.gov`.
Location-specific watches and warnings are NWS alert products and are left to a
separate NWS weather integration, so the two never duplicate each other.

Both use cases matter equally: **automations/alerts** (reliable states and
events) and **dashboard display** (maps, readable text).

### Success criteria

- A user can add "Home" and "My Phone" as separate locations and see, for each,
  the Day 1–3 categorical risk, Day 1–2 tornado/wind/hail probabilities, Day 3
  any-severe probability, Day 4–8 probability, and whether the location is in an
  active MD.
- An automation can trigger on "risk for my location rose to ENH or higher" or
  "an MD now covers my phone" without diffing states, via events.
- A dashboard can show how many watches SPC has active nationwide (and how many
  are tornado / PDS).
- National outlook maps and discussion text are available once (not duplicated
  per location).
- SPC products are downloaded once regardless of the number of locations, and
  unchanged products cost a 304 response.
- No dependencies beyond Home Assistant itself.

### Non-goals (v1)

- Fire weather outlooks, thunderstorm (TSTM) probability outlooks, local storm
  reports, convective watch probability graphics beyond MD watch-probability text.
- Non-CONUS coverage (SPC does not issue outlooks there).
- Location-specific watches, warnings or any other NWS alert products, and any
  use of `api.weather.gov` (owned by a separate NWS integration).
- Generating speech or LLM output directly — the integration exposes text
  attributes for users' own TTS/LLM automations.

## 2. Data sources (verified 2026-10-13)

All under `https://www.spc.noaa.gov/products/`. Server supports conditional GET
(ETag + Last-Modified → `304`).

| Product | URL |
|---|---|
| Day 1/2 categorical | `outlook/day{1,2}otlk_cat.lyr.geojson` |
| Day 1/2 tornado/wind/hail | `outlook/day{1,2}otlk_{torn,wind,hail}.lyr.geojson` |
| Day 1/2 significant | `outlook/day{1,2}otlk_sig{torn,wind,hail}.lyr.geojson` |
| Day 3 categorical | `outlook/day3otlk_cat.lyr.geojson` |
| Day 3 any-severe prob / sig | `outlook/day3otlk_prob.lyr.geojson`, `outlook/day3otlk_sigprob.lyr.geojson` |
| Day 4–8 prob | `exper/day4-8/day{4..8}prob.lyr.geojson` |
| Outlook text | `outlook/day{1,2,3}otlk.txt`; Day 4–8 text from `exper/day4-8/` |
| Outlook images | `outlook/day{1,2,3}otlk.png` (+ per-hazard images), Day 4–8 image |
| Watches (national list) | `spcwwrss.xml` → items linking to `watch/wwNNNN.html`; a single "No watches are valid" placeholder item when none are active |
| MD feed | `spcmdrss.xml` → links to `md/mdNNNN.html`; the `<pre>` text includes a `LAT...LON` polygon |
| Per-hazard images | `outlook/day{1,2}probotlk_{torn,wind,hail}.png` |
| Day 4–8 text / image | `<pre>` block of `exper/day4-8/` page; `exper/day4-8/day48prob.gif` |

GeoJSON features carry `LABEL` (e.g. `SLGT`, `0.05`, `SIGN`), `LABEL2`, `DN`,
`VALID_ISO`, `EXPIRE_ISO`, `ISSUE_ISO`, `FORECASTER`. An empty layer is a single
`DN: 0` feature with an empty `GeometryCollection` (its timestamps may be stale);
Day 4–8 uses `LABEL: "Predictability Too Low"` on that feature when applicable.

Watches are national only: each distinct watch number in the feed counts once,
with type (tornado / severe thunderstorm) and PDS taken from the item text. They
are never matched to a location. MDs are matched to locations by
point-in-polygon.

All requests send a User-Agent identifying the integration and repo URL.

## 3. Architecture

Approach A: **one shared hub entry + one config entry per location.**

```
            ┌───────────────────────── HubCoordinator ─────────────────────────┐
SPC HTTP ──►│ outlooks (5 min, conditional GET)   watches/MDs (2 min, RSS)     │
            │ parsed in-memory snapshot of polygons, text, image bytes         │
            └──────────────┬───────────────────────────────┬───────────────────┘
                           │ snapshot updates              │
                National entities                 LocationCoordinator × N
                (images, discussions,             (point-in-polygon on snapshot;
                 national counts)                  re-evaluates on snapshot change
                                                   or tracked-entity movement)
                                                          │
                                              per-location entities + events
```

- `api/` package has no Home Assistant imports so it is unit-testable in
  isolation and could later be extracted to PyPI.
- Location coordinators make no network calls; they evaluate the hub's
  in-memory snapshot.

## 4. Per-location entities

Device: "SPC – <location name>".

### Sensors

| Entity | State | Key attributes |
|---|---|---|
| `day{1,2,3}_risk` | enum: `none`, `TSTM`, `MRGL`, `SLGT`, `ENH`, `MDT`, `HIGH` | `level` (0–6), `label` (e.g. "Slight Risk"), `valid`, `expire`, `issued`, `forecaster` |
| `day{1,2}_{tornado,wind,hail}` | probability % (0 if outside) | `significant` (bool) |
| `day3_severe` | any-severe probability % | `significant` |
| `day{4..8}_severe` | `0`, `15`, `30` % | `predictability_too_low` (bool) |
| `max_risk_next_3_days` | highest categorical across Days 1–3 | `day` of peak |

Staleness is conveyed by entity unavailability (see §6), not by an age attribute: a changing age would force a state write per entity on every hub tick.

Outlook layers past their `expire` time are treated as "not current": they contribute no risk, and their issued/valid/expire/forecaster are reported as null.

### Binary sensors

- `mesoscale_discussion`: on while inside an active MD. Attributes: `number`,
  `concerning`, `watch_probability`, `summary`, `url`. If multiple MDs apply,
  attributes list all of them.

### Entity groups (toggleable in options)

categorical, probabilistic (Day 1–3), Day 4–8, MDs.

### Events

All events include `config_entry_id`, `location_name`, `latitude`, `longitude`.

- `noaa_spc_risk_changed`: `day`, `old`, `new`, `old_level`, `new_level`,
  `upgraded` (bool). Fired when a day's categorical level changes for the
  location (whether due to a new outlook or the location moving).
- `noaa_spc_md_issued`: `number`, `concerning`, `watch_probability`, `summary`,
  `url`. Fired the first time a given MD covers the location.

The first evaluation after startup or entry setup establishes a baseline and
fires no events. MD "issued" events are deduplicated per location by product
number for the life of the product.

### Location resolution

- Fixed: configured lat/lon (defaults to HA home).
- Tracked: `latitude`/`longitude` attributes of the tracked entity, listened to
  via state-change events. Re-evaluation happens only when the position moves
  more than the movement threshold (default 1 km) from the last evaluated point.
- Tracked entity without coordinates → location entities `unavailable`, no
  events; resumes when coordinates return.

## 5. Hub (national) entities

Device: "NOAA SPC".

- `image.spc_day{1,2,3}_outlook` — categorical PNGs.
- `image.spc_day{1,2}_{tornado,wind,hail}` — disabled by default.
- `image.spc_day4_8_outlook`.
- `sensor.spc_day{1,2,3}_discussion` — state is issue timestamp; attributes:
  `text` (full discussion), `summary`, `forecaster`, `valid`.
- `sensor.spc_day4_8_discussion` — same shape.
- `sensor.spc_active_watches` — national pulse check: state is the number of
  active watches; attributes `tornado`, `severe_thunderstorm` and `pds` counts
  and `items` (number, type, pds, url).
- `sensor.spc_active_mds` — national MD count; attribute `items` with number,
  concerning, watch probability, url.

`image` entities (not `camera`) are used; `image_last_updated` changes only
when the image content changes.

Hub options: outlook poll interval (default 5 min), MD/watch feed poll interval
(default 2 min). Per-hazard image entities always exist but are disabled by
default in the entity registry.

Long text attributes (`text`, `summary`) are excluded from the recorder.

## 6. Config flow

1. User adds the integration → chooses **Fixed** or **Tracked**.
2. Fixed: name + location selector (default HA home). Tracked: name + entity
   selector restricted to `device_tracker`, `person`, `zone`.
3. Validation: warn (not block) when outside CONUS; abort on duplicate (same
   tracked entity, or coordinates equal when rounded to 3 decimals).
4. Hub entry is created automatically if absent. It persists when the last
   location is removed.

Location options: coordinates/tracked entity, movement threshold (tracked only),
enabled entity groups. The location name is changed with Home Assistant's
built-in config entry rename.

The hub entry is created by an import flow triggered from the integration's
`async_setup` when no hub entry exists. The hub runtime is a reference-counted
singleton acquired by every entry (hub or location), so setup order between hub
and location entries does not matter.

## 7. Error handling

- **Fetch failure / outage:** keep last good data. Outlook-derived entities go
  `unavailable` after 3 h without a successful fetch; watch/MD entities after
  15 min.
- **Malformed product:** skip that product only, log once per distinct error,
  keep other products updating.
- **Empty outlooks:** valid "no risk" state, not an error.
- **Tracked entity removed:** raise a Repairs issue prompting reconfiguration.
- **Startup:** baseline evaluation fires no events.

## 8. Project layout

```
custom_components/noaa_spc/
  __init__.py
  api/
    __init__.py
    client.py        # async fetch, conditional-GET cache, User-Agent
    outlooks.py      # GeoJSON → OutlookArea models (Days 1–8)
    watches.py       # SPC watch RSS → national watch list
    mds.py           # MD feed + LAT...LON parsing
    geometry.py      # point-in-(multi)polygon with holes, pure Python
    models.py        # RiskLevel enum, Outlook, Watch, MesoscaleDiscussion
  coordinator.py     # HubCoordinator, LocationCoordinator
  config_flow.py
  sensor.py
  binary_sensor.py
  image.py
  events.py
  const.py
  manifest.json
  translations/en.json
blueprints/automation/noaa_spc/notify_severe_risk.yaml
tests/
  fixtures/          # real SPC files: quiet, busy, empty, day4-8 low predictability, active MD, watch feed
  api/
  ...
hacs.json
README.md
LICENSE              # MIT, © majoragee
.github/workflows/   # pytest, ruff, hassfest, HACS validation
```

Dependencies: none beyond Home Assistant (aiohttp session from HA,
`xml.etree` for RSS, custom geometry). Minimum HA version 2025.1, to be
confirmed against APIs used.

## 9. Blueprint

"NOAA SPC: notify on severe weather"

- Inputs: location, categorical threshold (default ENH), days to watch,
  include MDs (bool), notify actions.
- Triggers: `noaa_spc_risk_changed` with `upgraded: true` and
  `new_level >= threshold`; `noaa_spc_md_issued`; both filtered by the selected
  location's config entry.
- Message composed from event data.

## 10. Testing

- TDD, module by module.
- `api/` unit tests against captured fixtures: parsing every product type,
  empty/`DN: 0` handling, geometry edge cases (holes, multipolygons, boundary
  points), watch feed placeholder/duplicates, conditional-GET cache behavior.
- Integration tests with `pytest-homeassistant-custom-component`: config flow
  paths, entity states, event firing and deduplication, no events on baseline,
  tracked device moving into/out of an MD or risk area, staleness → unavailable, Repairs
  issue on removed tracker.
- CI: pytest, ruff, hassfest, HACS validation.
