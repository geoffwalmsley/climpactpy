"""The number rules (#226, ``core.numbers``): one test per rule."""

import pytest
from django.template import Context, Template
from django.utils import translation

from climpact_web.core import numbers

MINUS, NBSP = "−", " "


@pytest.fixture(autouse=True)
def english():
    with translation.override("en"):
        yield


def test_minus_is_u2212():
    assert numbers.fixed(-0.22, 2) == f"{MINUS}0.22"
    assert numbers.signed(-1.84, 2) == f"{MINUS}1.84"
    assert numbers.number(-2.5) == f"{MINUS}2.5"
    assert numbers.file_value(-50.0) == f"{MINUS}50"
    assert "-" not in numbers.interval(-0.22, 0.31, "°C")


def test_minus_only_before_a_number():
    assert numbers.minus("-0.5") == f"{MINUS}0.5"
    assert numbers.minus("TN < -2 °C") == f"TN < {MINUS}2 °C"
    assert numbers.minus("(-.5)") == f"({MINUS}.5)"
    # Ranges, dates, codes and words keep their hyphen.
    for text in ("1971-2000", "1963-12-01", "TX90-HWN", "day-to-day", "Rx1day"):
        assert numbers.minus(text) == text


def test_never_minus_zero():
    assert numbers.fixed(-0.001, 2) == "0.00"
    assert numbers.signed(-0.004, 2) == "0.00"
    assert numbers.signed(0.004, 2) == "0.00"
    assert numbers.anomaly(-0.04) == "0.0"
    assert numbers.number(-0.0001) == "0"
    assert numbers.file_value(-0.0) == "0"


def test_slopes_are_signed_per_decade_with_their_units():
    assert numbers.per_decade(0.21, "°C") == f"+0.21{NBSP}°C/decade"
    assert numbers.per_decade(0.21, "degrees_C") == f"+0.21{NBSP}°C/decade"
    assert numbers.per_decade(5.15, "days") == f"+5.15{NBSP}days/decade"
    assert numbers.per_decade(-1.84, "%") == f"{MINUS}1.84{NBSP}pp/decade"
    assert numbers.per_decade(0.02, "") == "+0.02/decade"
    assert numbers.per_decade(0.02, "unitless") == "+0.02/decade"


def test_one_unit_word_for_percentage_points():
    assert numbers.trend_units("%") == "pp"
    assert numbers.trend_units("°C") == "°C" and numbers.trend_units("days") == "days"


def test_decimals_two_in_degrees_days_and_percent_one_in_mm():
    assert numbers.slope(0.2, "°C") == "+0.20"
    assert numbers.slope(3, "days") == "+3.00"
    assert numbers.slope(1.314, "%") == "+1.31"
    assert numbers.slope(4.14, "mm") == "+4.1"
    assert numbers.slope(-34.27, "degree-days") == f"{MINUS}34.3"
    assert numbers.interval(-0.224, 0.31, "°C") == f"{MINUS}0.22 to 0.31"
    assert numbers.interval(-12.04, 3.0, "mm") == f"{MINUS}12.0 to 3.0"


def test_anomalies_one_decimal_with_a_sign():
    assert numbers.anomaly(0.44) == "+0.4"
    assert numbers.anomaly(-1.24) == f"{MINUS}1.2"
    assert numbers.anomaly(0) == "0.0"


def test_coordinates():
    assert numbers.coordinates(-33.86, 151.21) == f"33.86°{NBSP}S 151.21°{NBSP}E"
    assert numbers.coordinates(52.4, -13.06) == f"52.40°{NBSP}N 13.06°{NBSP}W"
    assert numbers.coordinates(0, 0) == f"0.00°{NBSP}N 0.00°{NBSP}E"
    assert numbers.coordinates(None, 1.0) == ""


def test_no_break_space_between_a_value_and_its_unit():
    assert numbers.with_unit("45.8", "°C") == f"45.8{NBSP}°C"
    assert numbers.with_unit("20", "days") == f"20{NBSP}days"
    assert numbers.with_unit("12.5", "%") == "12.5%"  # a percentage takes no space
    assert numbers.with_unit("0.4", "") == "0.4"
    assert numbers.in_text("TN below -2 °C") == f"TN below {MINUS}2{NBSP}°C"
    assert numbers.in_text("for 6 days in a row") == f"for 6{NBSP}days in a row"
    assert numbers.in_text("1 mm or more") == f"1{NBSP}mm or more"


def test_no_break_space_is_not_in_a_message():
    """#205: the no-break space is joined in code, never part of a msgid."""
    from pathlib import Path

    import climpact_web

    po = Path(climpact_web.__file__).parent / "locale/en/LC_MESSAGES/django.po"
    msgids = [
        line for line in po.read_text(encoding="utf-8").splitlines() if line.startswith("msgid")
    ]
    assert not [m for m in msgids if NBSP in m or "\\u00a0" in m]


def test_parse_reads_what_it_writes():
    assert numbers.parse(numbers.fixed(-0.22, 2)) == -0.22
    assert numbers.parse("-50") == -50.0
    assert numbers.parse("missing") is None and numbers.parse(None) is None


def test_localised():
    with translation.override("fr"):
        assert numbers.fixed(-0.22, 2) == f"{MINUS}0,22"


def test_template_filters():
    template = Template("{% load ui %}[{{ v|decimals:4 }}] [{{ lat|coordinates:lon }}]")
    out = template.render(Context({"v": -0.022, "lat": -33.86, "lon": 151.21}))
    assert out == f"[{MINUS}0.0220] [33.86°{NBSP}S 151.21°{NBSP}E]"
    assert Template("{% load ui %}{{ v|decimals:2 }}").render(Context({"v": "n/a"})) == "n/a"
