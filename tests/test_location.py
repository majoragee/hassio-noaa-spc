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
    hass.states.async_set(
        "device_tracker.phone",
        "not_home",
        {"latitude": FAR[0], "longitude": FAR[1]},
    )
    hub = _hub_with_data(hass)
    coordinator = await _start(hass, tracked_entry(), hub)
    assert coordinator.data.outlook.categorical[1] is RiskLevel.NONE

    hass.states.async_set(
        "device_tracker.phone",
        "not_home",
        {"latitude": HOME[0], "longitude": HOME[1]},
    )
    await hass.async_block_till_done()
    assert coordinator.data.position == HOME
    # Day 1 NONE -> SLGT and Day 2 NONE -> MRGL (risk_layers has both at HOME)
    assert [(e.data["day"], e.data["new"]) for e in events] == [
        (1, "SLGT"),
        (2, "MRGL"),
    ]

    hass.states.async_set(
        "device_tracker.phone",
        "not_home",
        {"latitude": HOME[0] + 0.001, "longitude": HOME[1]},
    )
    await hass.async_block_till_done()
    assert coordinator.data.position == HOME
    assert len(events) == 2


async def test_tracked_without_coordinates_is_unpositioned(hass: HomeAssistant) -> None:
    events = async_capture_events(hass, EVENT_RISK_CHANGED)
    hass.states.async_set(
        "person.alex", "home", {"latitude": HOME[0], "longitude": HOME[1]}
    )
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

    hass.states.async_set(
        "device_tracker.phone", "x", {"latitude": FAR[0], "longitude": FAR[1]}
    )
    hass.states.async_set(
        "device_tracker.phone", "x", {"latitude": HOME[0], "longitude": HOME[1]}
    )
    await hass.async_block_till_done()

    assert coordinator.data.position == HOME
    assert coordinator.data.outlook.categorical[1] is RiskLevel.SLGT
    assert [m.number for m in coordinator.data.alerts.mds] == [2104]


async def test_missing_tracker_raises_repair_issue(hass: HomeAssistant) -> None:
    entry = tracked_entry("device_tracker.gone")
    await _start(hass, entry, _hub_with_data(hass))
    issue_id = f"missing_tracker_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    hass.states.async_set(
        "device_tracker.gone", "home", {"latitude": 1.0, "longitude": 1.0}
    )
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
