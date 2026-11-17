"""The Indices' table and detail pane (#236, the Results board): each index as one row
of the table (unit, slope per decade, 95% interval, significance, mean) and, for the
selected row, its detail: the series drawn on the server with axes, the base period as a
band and Sen's slope dashed, then the statistics and the links to the index's page and
files.

The chart is SVG path data in a ``CHART_W`` x ``CHART_H`` box, as Quality's finding chart
(``qc_review._chart``), so the page needs no chart code; the interactive chart, its table
view and its CSV are on the index's own page. Numbers follow the rules of #226
(:mod:`climpact_web.core.numbers`).
"""

from __future__ import annotations

import math

from django.utils.translation import gettext as _

from climpact_web.charts import data as chart_data
from climpact_web.core import numbers

# The box is about the pane's width in pixels (17-26rem), so its 12px ticks stay
# about that size.
CHART_W, CHART_H = 300, 170
PLOT_LEFT, PLOT_RIGHT, PLOT_TOP, PLOT_BOTTOM = 36, 294, 10, 142
X_LABEL_Y = 160
# Longer series (SPI and SPEI, monthly) are averaged into this many columns, about two
# units of the box each, which keeps the page small.
COLUMNS = 129


def _columns(values: list[float | None]) -> list[float | None]:
    n = len(values)
    if n <= COLUMNS:
        return values
    out = []
    for c in range(COLUMNS):
        chunk = [v for v in values[c * n // COLUMNS : (c + 1) * n // COLUMNS] if v is not None]
        out.append(sum(chunk) / len(chunk) if chunk else None)
    return out


def mean(values) -> float | None:
    """The mean of the values present, None when there are none."""
    present = [float(v) for v in values if v == v]
    return sum(present) / len(present) if present else None


def chart(plot, base: tuple[int, int] | None = None) -> dict:
    """The detail's chart of ``plot`` (a :class:`climpact.plots.IndexPlot`): the series as
    a line (gaps where values are missing), or bars from zero (SPI, SPEI); Sen's slope as
    a line across it when there is a trend; the base period (``base``, first and last
    year) as a band; and axes: three values (the whole numbers around the data and the
    middle) and three times (the first, the middle and the last). {} when every value is
    missing."""
    raw = [None if v != v else float(v) for v in plot.values]
    present = [v for v in raw if v is not None]
    if not present:
        return {}
    n = len(raw)
    ends = None
    if plot.trend is not None and plot.trend.valid:
        ends = (plot.trend.intercept, plot.trend.intercept + plot.trend.slope * (n - 1))
    low, high = min(present), max(present)
    if plot.bars:
        low, high = min(low, 0.0), max(high, 0.0)
    if ends:
        low, high = min(low, *ends), max(high, *ends)
    low, high = math.floor(low), math.ceil(high)
    if high == low:
        high = low + 1

    def y(v: float) -> float:
        return round(PLOT_BOTTOM - (v - low) / (high - low) * (PLOT_BOTTOM - PLOT_TOP), 1)

    cols = _columns(raw)
    m = len(cols)

    def x(i: int, count: int = m) -> float:
        if count == 1:
            return (PLOT_LEFT + PLOT_RIGHT) / 2
        return round(PLOT_LEFT + i * (PLOT_RIGHT - PLOT_LEFT) / (count - 1), 1)

    out: dict = {
        "box": f"0 0 {CHART_W} {CHART_H}",
        "left": PLOT_LEFT,
        "right": PLOT_RIGHT,
        "top": PLOT_TOP,
        "bottom": PLOT_BOTTOM,
        "height": PLOT_BOTTOM - PLOT_TOP,
        "tick_x": PLOT_LEFT - 5,
        "label_y": X_LABEL_Y,
    }
    if plot.bars:
        zero = y(0.0)
        pos, neg = [], []
        for i, v in enumerate(cols):
            if v is not None and y(v) != zero:
                (pos if v > 0 else neg).append(f"M{x(i)} {zero}V{y(v)}")
        out["pos"], out["neg"] = "".join(pos), "".join(neg)
        out["zero"] = zero
        out["bar_width"] = f"{max((PLOT_RIGHT - PLOT_LEFT) / m - 0.4, 0.6):.1f}"
    else:
        parts, pen = [], False
        for i, v in enumerate(cols):
            if v is None:
                pen = False
                continue
            parts.append(f"{'L' if pen else 'M'}{x(i)} {y(v)}")
            pen = True
        out["line"] = "".join(parts)
    if ends:
        out["trend"] = {"y1": y(ends[0]), "y2": y(ends[1])}
    middle = (low + high) / 2
    out["y_ticks"] = [{"y": y(v), "text": numbers.number(v)} for v in (high, middle, low)]
    out["grid_y"] = y(middle)
    xs = [float(v) for v in plot.x]
    mid = (n - 1) // 2
    out["x_ticks"] = [
        {"x": x(0, n), "text": chart_data._x_label(plot.step, xs[0]), "anchor": "start"},
        {"x": x(mid, n), "text": chart_data._x_label(plot.step, xs[mid]), "anchor": "middle"},
        {"x": x(n - 1, n), "text": chart_data._x_label(plot.step, xs[-1]), "anchor": "end"},
    ]
    if base and plot.step in ("year", "month") and n > 1 and xs[-1] > xs[0]:
        # The base period's years: whole years, so from the start of its first to the end
        # of its last (a year's value sits at the year, a month's in the middle of it).
        if plot.step == "year":
            start, end = base[0] - 0.5, base[1] + 0.5
        else:
            start, end = base[0], base[1] + 1

        def at(v: float) -> float:
            return PLOT_LEFT + (v - xs[0]) / (xs[-1] - xs[0]) * (PLOT_RIGHT - PLOT_LEFT)

        left, right = max(at(start), PLOT_LEFT), min(at(end), PLOT_RIGHT)
        if right > left:
            out["band"] = {
                "x": round(left, 1),
                "width": round(right - left, 1),
                "label_x": round((left + right) / 2, 1),
                "label_y": PLOT_TOP + 11,
            }
    return out


def summary(card, plot) -> str:
    """The chart's text alternative: the series, its years, its lowest and highest values
    and its trend in words."""
    present = [(float(v), i) for i, v in enumerate(plot.values) if v == v]
    if not present:
        return ""
    (high, hi), (low, lo) = max(present), min(present)
    when = lambda i: chart_data._x_label(plot.step, float(plot.x[i]))  # noqa: E731
    text = _(
        "%(series)s from %(first)s to %(last)s. Lowest %(low)s in %(low_when)s, highest "
        "%(high)s in %(high_when)s."
    ) % {
        "series": series_name(card, plot),
        "first": when(0),
        "last": when(len(plot.values) - 1),
        "low": numbers.with_unit(numbers.number(low), card.units),
        "low_when": when(lo),
        "high": numbers.with_unit(numbers.number(high), card.units),
        "high_when": when(hi),
    }
    if card.trend and card.trend.get("valid"):
        text += " " + _("Sen's slope %(slope)s, 95%% interval %(interval)s.") % {
            "slope": card.trend["per_decade_text"],
            "interval": card.trend["interval_text"],
        }
    return text


def series_name(card, plot) -> str:
    """ "Annual SU", "Monthly SPI": the series the detail shows."""
    if plot.step == "year":
        return _("Annual %(code)s") % {"code": card.code}
    if plot.step == "month":
        return _("Monthly %(code)s") % {"code": card.code}
    return card.code


def caption(card, plot) -> str:
    """Under the chart: "Annual SU (days), with Sen's slope dashed." """
    name = series_name(card, plot)
    if card.units:
        name = _("%(series)s (%(units)s)") % {"series": name, "units": card.units}
    if plot.trend is not None and plot.trend.valid:
        return _("%(series)s, with Sen's slope dashed.") % {"series": name}
    return _("%(series)s.") % {"series": name}


def values_used(card, plot) -> str:
    """ "80 of 80": the values present out of the series' length."""
    total = len(plot.values)
    present = sum(1 for v in plot.values if v == v)
    return _("%(present)s of %(total)s") % {"present": present, "total": total}


def used_label(plot) -> str:
    """What the values are: years, months or days."""
    if plot.step == "year":
        return _("Years used")
    if plot.step == "month":
        return _("Months used")
    return _("Values used")
