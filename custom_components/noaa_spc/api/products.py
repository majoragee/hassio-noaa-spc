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
