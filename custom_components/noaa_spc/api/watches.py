"""SPC watch RSS feed parsing (national list). Must not import Home Assistant."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from .models import Watch

_LINK_RE = re.compile(r"/watch/(?:\d{4}/)?ww(\d{4})")
_PAGE_RE = re.compile(r"/watch/(?:\d{4}/)?ww\d{4}\.html$")
_PDS_RE = re.compile(r"\bPDS\b|PARTICULARLY DANGEROUS SITUATION")


class WatchParseError(ValueError):
    """Raised when the SPC watch feed cannot be parsed."""


@dataclass
class _Group:
    url: str
    tornado: bool = False
    pds: bool = False


def parse_watch_feed(xml: bytes | str) -> tuple[Watch, ...]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as err:
        raise WatchParseError(f"invalid watch feed XML: {err}") from err
    groups: dict[int, _Group] = {}
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        match = _LINK_RE.search(link)
        if match is None:
            continue
        number = int(match.group(1))
        group = groups.setdefault(number, _Group(url=link))
        if _PAGE_RE.search(link) and not _PAGE_RE.search(group.url):
            group.url = link
        text = f"{item.findtext('title') or ''} {item.findtext('description') or ''}"
        upper = text.upper()
        group.tornado = group.tornado or "TORNADO" in upper
        group.pds = group.pds or bool(_PDS_RE.search(upper))
    return tuple(
        Watch(
            number=number,
            kind="tornado" if group.tornado else "severe_thunderstorm",
            pds=group.pds,
            url=group.url,
        )
        for number, group in sorted(groups.items())
    )
