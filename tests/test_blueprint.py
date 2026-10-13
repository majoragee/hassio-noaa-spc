from pathlib import Path
from types import SimpleNamespace

from homeassistant.components.blueprint.models import Blueprint
from homeassistant.components.blueprint.schemas import BLUEPRINT_SCHEMA
from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template
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


def test_location_input_warns_against_choosing_the_hub() -> None:
    inputs = load_yaml_dict(str(PATH))["blueprint"]["input"]
    assert "not the NOAA SPC hub" in inputs["location"]["description"]


def _md_message(hass: HomeAssistant, concerning: str | None) -> str:
    template = load_yaml_dict(str(PATH))["variables"]["message"]
    data = {
        "number": 2104,
        "location_name": "Home",
        "concerning": concerning,
        "watch_probability": None,
    }
    trigger = SimpleNamespace(id="md", event=SimpleNamespace(data=data))
    return Template(template, hass).async_render({"trigger": trigger}).strip()


def test_md_message_handles_missing_concerning(hass: HomeAssistant) -> None:
    assert _md_message(hass, None) == (
        "SPC Mesoscale Discussion #2104 covers Home: n/a."
    )
    assert _md_message(hass, "Watch likely") == (
        "SPC Mesoscale Discussion #2104 covers Home: Watch likely."
    )
