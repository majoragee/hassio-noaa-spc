from custom_components.noaa_spc.api.evaluate import (
    OutlookRisk,
    evaluate_alerts,
    evaluate_outlooks,
)
from datetime import UTC, datetime

from custom_components.noaa_spc.api.models import RiskLevel
from custom_components.noaa_spc.api.outlooks import parse_layer
from tests.factories import make_md, outlook_bundle, risk_layers
from tests.helpers import FAR, HOME, collection, feature, square


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


def test_expired_layers_contribute_no_risk() -> None:
    layers = outlook_bundle(risk_layers()).layers
    risk = evaluate_outlooks(layers, *HOME, now=datetime(2100, 1, 1, tzinfo=UTC))
    assert risk.categorical == {1: RiskLevel.NONE, 2: RiskLevel.NONE, 3: RiskLevel.NONE}
    assert risk.probability["day1_torn"] == 0
    assert risk.probability["day4_prob"] == 0
    assert risk.significant == {"day1_torn": False}
    assert risk.predictability_too_low == {4: False, 5: True}


def test_expired_significant_layer_alone_is_not_significant() -> None:
    near = square(*HOME)
    layers = {
        "day3_prob": parse_layer(collection(feature("0.05", near))),
        "day3_sigprob": parse_layer(collection(feature("SIGN", near))),
    }
    now = datetime(2026, 10, 13, tzinfo=UTC)
    assert evaluate_outlooks(layers, *HOME, now=now).significant == {"day3_prob": True}
    expired = {**layers, "day3_sigprob": parse_layer(collection(feature("SIGN", near)))}
    expired["day3_sigprob"] = type(expired["day3_sigprob"])(
        areas=expired["day3_sigprob"].areas,
        issued=None,
        valid=None,
        expire=datetime(2026, 3, 5, tzinfo=UTC),
        forecaster=None,
    )
    assert evaluate_outlooks(expired, *HOME, now=now).significant == {
        "day3_prob": False
    }


def test_significant_requires_base_probability() -> None:
    near = square(*HOME)
    layers = {
        "day3_prob": parse_layer(collection()),
        "day3_sigprob": parse_layer(collection(feature("SIGN", near))),
    }
    risk = evaluate_outlooks(layers, *HOME, now=datetime(2026, 10, 13, tzinfo=UTC))
    assert risk.probability["day3_prob"] == 0
    assert risk.significant == {"day3_prob": False}
