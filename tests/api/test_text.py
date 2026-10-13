import pytest

from custom_components.noaa_spc.api.text import (
    TextParseError,
    first_paragraph_after,
    parse_text_product,
)

DAY1 = """ZCZC SPCSWODY1 ALL
ACUS01 KWNS 131252
SPC AC 131252

Day 1 Convective Outlook
NWS Storm Prediction Center Norman OK
0752 AM CDT Tue Oct 13 2026

Valid 131300Z - 141200Z

...THERE IS A SLIGHT RISK OF SEVERE THUNDERSTORMS FROM PARTS OF
NORTHWEST MISSOURI/KANSAS INTO THE SOUTHERN HIGH PLAINS...

...SUMMARY...
Widely scattered severe storms capable of large hail, damaging
winds, and possibly a tornado are expected.

...Southern High Plains...
Early morning satellite imagery shows a belt of flow.

..Mosier/Wendt.. 10/13/2026

$$
"""

DAY48_HTML = """<html><body><pre>

   ZCZC SPCSWOD48 ALL
   ACUS48 KWNS 130830

   Day 4-8 Convective Outlook
   NWS Storm Prediction Center Norman OK

   ...DISCUSSION...
   ...Day 4/Friday...

   An intense midlevel trough will progress from the Great Lakes &amp; beyond
   by Saturday morning.

   ...Days 5 through 8/Saturday through Tuesday...

   A considerably drier air mass will persist.

   ..Mead.. 10/13/2026

   CLICK TO GET <a href="/x.txt">WUUS48 PTSD48</a> PRODUCT

</pre></body></html>"""


def test_day1_text() -> None:
    product = parse_text_product(DAY1)
    assert product.summary == (
        "Widely scattered severe storms capable of large hail, damaging "
        "winds, and possibly a tornado are expected."
    )
    assert product.forecaster == "Mosier/Wendt"
    assert "ZCZC" not in product.text
    assert "$$" not in product.text
    assert product.text.startswith("ACUS01 KWNS 131252")


def test_day48_html_falls_back_to_discussion_paragraph() -> None:
    product = parse_text_product(DAY48_HTML)
    assert product.summary == (
        "An intense midlevel trough will progress from the Great Lakes & beyond "
        "by Saturday morning."
    )
    assert product.forecaster == "Mead"
    assert "CLICK TO GET" not in product.text
    assert "<a" not in product.text
    assert product.text.startswith("ACUS48 KWNS 130830")


def test_first_paragraph_after_missing_marker() -> None:
    assert first_paragraph_after("nothing here", "...SUMMARY...") is None


def test_empty_text_rejected() -> None:
    with pytest.raises(TextParseError):
        parse_text_product("<pre>\n\n</pre>")
