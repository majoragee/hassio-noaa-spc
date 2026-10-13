"""The release version must agree everywhere it is written."""

import json
import re
import tomllib
from pathlib import Path

from custom_components.noaa_spc.api.products import USER_AGENT

ROOT = Path(__file__).parent.parent


def test_versions_match() -> None:
    manifest = json.loads(
        (ROOT / "custom_components/noaa_spc/manifest.json").read_text()
    )["version"]
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    agent = re.search(r"hassio-noaa-spc/(\S+) ", USER_AGENT).group(1)
    assert manifest == project == agent
