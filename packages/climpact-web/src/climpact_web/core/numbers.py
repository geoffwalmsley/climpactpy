"""Numbers as every page shows them (#226): one set of rules, in one place.

- **Minus** is U+2212 (``−0.22``), never the hyphen-minus, and a value that rounds to
  zero has no sign (never ``−0.0``).
- **Slopes** are per decade, signed, with their units: ``+0.21 °C/decade``,
  ``+5.15 days/decade``, ``+1.31 pp/decade`` (a change in a percentage is in percentage
  points, written ``pp`` everywhere). Slopes and their 95% intervals have two decimals in
  °C, days and %, one in mm (and degree-days): :func:`slope_decimals`.
- **Intervals** are ``−0.22 to 0.31``: two unsigned bounds.
- **Anomalies** have one decimal and a sign: ``+0.4``, ``−1.2``, ``0.0``.
- **Coordinates** are ``33.86° S 151.21° E``.
- **Units** follow a value after a no-break space (``45.8 °C``); a percentage takes none
  (``12.5%``). The no-break space is joined here, never written in a message: older
  xgettext keeps ``\\u00a0`` in a msgid as written and newer versions decode it (#205).

Numbers are localised (the decimal mark and grouping of the interface language). Text
a user types or a file holds (``-99.9`` for missing values) keeps the hyphen-minus: it
is not formatted here. Downloads (CSV) are written as the files are, not with these rules.
"""

from __future__ import annotations

import math
import re
from decimal import ROUND_HALF_UP, Decimal

from django.utils.formats import number_format
from django.utils.translation import gettext as _
from django.utils.translation import pgettext

MINUS = "\u2212"
NBSP = "\u00a0"

# A number followed by a unit in running text: "25 °C", "1 mm", "6 days".
_UNIT_IN_TEXT = re.compile(r"(\d) (°C|mm|days?)(?![\w])")

# Units whose slopes, intervals and values take one decimal (#226): large amounts.
ONE_DECIMAL_UNITS = {"mm", "mm/day", "degree-days"}


def minus(text: str) -> str:
    """``text`` with a leading hyphen-minus (or one after an opening bracket or a space)
    written as U+2212: ``-0.22`` -> ``−0.22``. Only before a digit, so words and ranges
    such as ``1971-2000`` are kept."""
    out = []
    for i, ch in enumerate(text):
        if (
            ch == "-"
            and i + 1 < len(text)
            and (text[i + 1].isdigit() or text[i + 1] == ".")
            and (i == 0 or not text[i - 1].isalnum())
        ):
            out.append(MINUS)
        else:
            out.append(ch)
    return "".join(out)


def in_text(text: str) -> str:
    """Running text from elsewhere (an index's name or definition, from the core's file)
    with the number rules: U+2212 for minus and a no-break space between a number and its
    unit: ``TN below -2 °C`` -> ``TN below −2 °C``."""
    return _UNIT_IN_TEXT.sub(lambda m: f"{m[1]}{NBSP}{m[2]}", minus(str(text)))


def parse(text: str | None) -> float | None:
    """A number written by this module (or a file) back to a float; ``None`` if it is
    not one."""
    if text is None:
        return None
    try:
        value = float(str(text).replace(MINUS, "-"))
    except ValueError:
        return None
    return None if value != value else value


def _localised(value, decimals: int) -> str:
    return minus(number_format(value, decimals))


def _rounded(value: float, decimals: int) -> Decimal:
    """``value`` to ``decimals`` places, half up from the number as written (``0.03125``
    -> ``0.0313``, as a reader rounds the file's value), without the sign of zero."""
    rounded = Decimal(repr(float(value))).quantize(
        Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP
    )
    return abs(rounded) if rounded == 0 else rounded


def fixed(value: float, decimals: int) -> str:
    """``value`` with exactly ``decimals`` places, localised; never ``−0.00``."""
    return _localised(_rounded(value, decimals), decimals)


def signed(value: float, decimals: int) -> str:
    """``+0.21``, ``−0.22``; a value that rounds to zero has no sign: ``0.00``."""
    text = fixed(value, decimals)
    return "+" + text if _rounded(value, decimals) > 0 else text


def number(value: float, decimals: int | None = None) -> str:
    """A number for a summary or a chart: localised, at most ``decimals`` places
    (default: 2 for small values, 1 otherwise), without trailing zeros; never ``−0``."""
    if decimals is None:
        decimals = 2 if abs(value) < 10 else 1
    text = f"{float(value):.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("-0", ""):
        text = "0"
    places = len(text.split(".")[1]) if "." in text else 0
    return _localised(float(text), places)


def file_value(value: float | None) -> str:
    """A value as the files write it (at most 15 significant digits, no trailing zeros),
    with U+2212 for minus: the Quality tables show the file's own precision."""
    if value is None:
        return ""
    text = f"{value:.15g}"
    return "0" if text == "-0" else minus(text)


def slope_decimals(units: str) -> int:
    """Places for a slope, its interval and an index's values: one in mm (and
    degree-days), two otherwise (°C, days, %, events, no units)."""
    return 1 if units in ONE_DECIMAL_UNITS else 2


def unit_label(units: str) -> str:
    """The units as shown: ``degrees_C`` -> ``°C``; ``unitless`` -> none."""
    return {"degrees_C": "°C", "°C^2": "°C²", "unitless": ""}.get(units, units or "")


def trend_units(units: str) -> str:
    """The units of a change: percentage points (``pp``) for a percentage."""
    units = unit_label(units)
    return _("pp") if units == "%" else units


def with_unit(value: str, units: str) -> str:
    """``45.8 °C`` (a no-break space), ``12.5%``, the value alone without units."""
    units = unit_label(units)
    if not units:
        return value
    if units == "%":
        return _("%(value)s%%") % {"value": value}
    return f"{value}{NBSP}{units}"


def slope(value: float, units: str) -> str:
    """The signed slope with the places its units take, no units: ``+0.21``."""
    return signed(value, slope_decimals(unit_label(units)))


def per_decade(value: float, units: str) -> str:
    """``+0.21 °C/decade``, ``+1.31 pp/decade``, ``+0.02/decade`` without units."""
    text = slope(value, units)
    change = trend_units(units)
    if change:
        text = f"{text}{NBSP}{change}"
    return _("%(value)s/decade") % {"value": text}


def interval(lower: float, upper: float, units: str) -> str:
    """A 95% interval: ``−0.22 to 0.31``, with the places of its slope."""
    places = slope_decimals(unit_label(units))
    return _("%(lower)s to %(upper)s") % {
        "lower": fixed(lower, places),
        "upper": fixed(upper, places),
    }


def anomaly(value: float) -> str:
    """An anomaly: one decimal and a sign, ``+0.4``, ``−1.2``, never ``−0.0``."""
    return signed(value, 1)


def _hemisphere(value: float, positive: str) -> str:
    if positive == "N":
        return pgettext("latitude", "N") if value >= 0 else pgettext("latitude", "S")
    return pgettext("longitude", "E") if value >= 0 else pgettext("longitude", "W")


def coordinate(value: float, positive: str) -> str:
    """One coordinate: ``33.86° S``; ``positive`` is ``N`` or ``E``."""
    return f"{fixed(abs(value), 2)}°{NBSP}{_hemisphere(value, positive)}"


def coordinates(latitude: float | None, longitude: float | None) -> str:
    """``33.86° S 151.21° E``; "" when either is unknown."""
    if latitude is None or longitude is None:
        return ""
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        return ""
    return f"{coordinate(latitude, 'N')} {coordinate(longitude, 'E')}"
