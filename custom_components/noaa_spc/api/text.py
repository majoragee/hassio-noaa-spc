"""SPC text product parsing. Must not import Home Assistant."""

from __future__ import annotations

import html
import re
import textwrap

from .models import TextProduct

_PRE_RE = re.compile(r"<pre[^>]*>(.*?)</pre>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_DROP_RE = re.compile(r"^(ZCZC|\$\$|CLICK TO GET)", re.I)
_FORECASTER_RE = re.compile(r"^\.\.(.+?)\.\.\s+\d{2}/\d{2}/\d{4}\s*$", re.M)
_PARAGRAPH_RE = re.compile(r"\n\s*\n")


class TextParseError(ValueError):
    """Raised when a text product has no usable content."""


def extract_pre(raw: str) -> str:
    """Return the <pre> body of an HTML page (or the raw text), dedented."""
    match = _PRE_RE.search(raw)
    body = match.group(1) if match else raw
    body = html.unescape(_TAG_RE.sub("", body)).replace("\r\n", "\n")
    return textwrap.dedent(body)


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in _PARAGRAPH_RE.split(text) if p.strip()]


def _join_lines(paragraph: str) -> str:
    return " ".join(line.strip() for line in paragraph.splitlines())


def first_paragraph_after(text: str, marker: str) -> str | None:
    """First paragraph after `marker`, skipping '...Heading...' paragraphs."""
    index = text.find(marker)
    if index < 0:
        return None
    for paragraph in _paragraphs(text[index + len(marker) :]):
        if paragraph.startswith("..."):
            continue
        return _join_lines(paragraph)
    return None


def parse_text_product(raw: str) -> TextProduct:
    """Parse an SPC text product (raw text or HTML page) into a TextProduct."""
    lines = [
        line.rstrip()
        for line in extract_pre(raw).splitlines()
        if not _DROP_RE.match(line.strip())
    ]
    text = "\n".join(lines).strip()
    if not text:
        raise TextParseError("empty text product")
    summary = first_paragraph_after(text, "...SUMMARY...") or first_paragraph_after(
        text, "...DISCUSSION..."
    )
    forecaster = _FORECASTER_RE.search(text)
    return TextProduct(
        text=text,
        summary=summary,
        forecaster=forecaster.group(1) if forecaster else None,
    )
