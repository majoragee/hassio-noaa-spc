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
