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
    tie = OutlookRisk(
        {1: RiskLevel.MRGL, 2: RiskLevel.ENH, 3: RiskLevel.ENH}, {}, {}, {}
    )
    assert tie.max_next_3_days == (RiskLevel.ENH, 2)
    assert OutlookRisk({}, {}, {}, {}).max_next_3_days is None


def test_evaluate_alerts_by_polygon() -> None:
    mds = (make_md(2104), make_md(2105, center=FAR))
    risk = evaluate_alerts(mds, *HOME)
    assert [m.number for m in risk.mds] == [2104]
    assert evaluate_alerts(mds, FAR[0] + 5.0, FAR[1]).mds == ()
