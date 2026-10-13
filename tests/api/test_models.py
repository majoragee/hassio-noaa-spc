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
