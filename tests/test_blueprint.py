from pathlib import Path

from homeassistant.components.blueprint.models import Blueprint
from homeassistant.components.blueprint.schemas import BLUEPRINT_SCHEMA
from homeassistant.util.yaml import load_yaml_dict

PATH = (
    Path(__file__).parent.parent
    / "blueprints/automation/noaa_spc/notify_severe_risk.yaml"
)


def test_blueprint_is_valid() -> None:
    blueprint = Blueprint(
        load_yaml_dict(str(PATH)), expected_domain="automation", schema=BLUEPRINT_SCHEMA
    )
    assert blueprint.domain == "automation"
    assert set(blueprint.inputs) == {
        "location",
        "threshold",
        "days",
        "include_mds",
        "notify",
    }
