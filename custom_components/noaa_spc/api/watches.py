"""SPC watch RSS feed parsing (national list). Must not import Home Assistant."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from .models import Watch

_LINK_RE = re.compile(r"/watch/(?:\d{4}/)?ww(\d{4})")
_PAGE_RE = re.compile(r"/watch/(?:\d{4}/)?ww\d{4}\.html$")
_PDS_RE = re.compile(r"\bPDS\b|PARTICULARLY DANGEROUS SITUATION")


_TORNADO_PHRASE = "TORNADO WATCH"
_SVR_PHRASE = "SEVERE THUNDERSTORM WATCH"


class WatchParseError(ValueError):
    """Raised when the SPC watch feed cannot be parsed."""


@dataclass
class _Group:
    url: str
    title_tornado: bool = False
    title_svr: bool = False
    desc_tornado: bool = False
    desc_svr: bool = False
    pds: bool = False


def _kind(group: _Group) -> str:
    if group.title_tornado:
        return "tornado"
    if group.title_svr:
        return "severe_thunderstorm"
    if group.desc_tornado:
        return "tornado"
    return "severe_thunderstorm"


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
        title = (item.findtext("title") or "").upper()
        desc = (item.findtext("description") or "").upper()
        group.title_tornado |= _TORNADO_PHRASE in title
        group.title_svr |= _SVR_PHRASE in title
        group.desc_tornado |= _TORNADO_PHRASE in desc
        group.desc_svr |= _SVR_PHRASE in desc
        group.pds = group.pds or bool(_PDS_RE.search(f"{title} {desc}"))
    return tuple(
        Watch(
            number=number,
            kind=_kind(group),
            pds=group.pds,
            url=group.url,
        )
        for number, group in sorted(groups.items())
    )
