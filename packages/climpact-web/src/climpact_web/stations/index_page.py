"""One index's page (#237, the Index board): where an expert checks a trend.

The page shows one series of the index (annual, or monthly where the index has it) as a
chart drawn here on the server, in an ``CHART_W`` x ``CHART_H`` box: the values, or their
anomalies from the base-period mean; the base period as a band; an 11-year running mean;
Sen's slope dashed, with its 95% interval as a shaded band; and the years (or months) left
out as incomplete as open points. Beside it the statistics (slope, interval, significance,
years used, base-period mean, record, and why any year was left out), and under it the
values as a table, the chart's table view: value, anomaly, rank, the date of the extreme
(from the core's ``day_of_`` tables, where the index has them) and a note.

Numbers follow the rules of #226 (:mod:`climpact_web.core.numbers`). Nothing here
calculates an index: the values and the trend are the core's
(:func:`climpact.plots.index_plots`), as in the files.
"""

from __future__ import annotations

import datetime
import math
from dataclasses import dataclass

from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from climpact_web.charts import data as chart_data
from climpact_web.core import numbers

CHART_W, CHART_H = 860, 340
LEFT, RIGHT, TOP, BOTTOM = 64, 848, 16, 300
X_LABEL_Y = 320
# The running mean's window: 11 years, of years or of months.
RUNNING_YEARS = 11
# An anomaly's places (numbers.anomaly): the payload's anomaly view is rounded to them
# once, so the chart's read-out and the statistics give the same number (#349).
ANOMALY_DIGITS = 1
# Where the record is the lowest value: the coldest indices, and drought (SPI, SPEI).
LOW_RECORDS = frozenset({"tnn", "txn"})
# How many left-out years the statistics name; the table has them all.
LEFT_OUT_NAMED = 3


def low_is_record(key: str) -> bool:
    """Whether the record of the index ``key`` is its lowest value (TNn, TXn, SPI, SPEI)."""
    return key in LOW_RECORDS or key.endswith(("_spi", "_spei"))


def _values(plot) -> list[float | None]:
    return [None if v != v else float(v) for v in plot.values]


def _month(plot, i: int) -> int:
    """The calendar month (0-11) of a monthly series' ``i``-th value."""
    x = float(plot.x[i])
    return min(11, max(0, round((x - math.floor(x)) * 12 - 0.5)))


def _year(plot, i: int) -> int:
    return math.floor(float(plot.x[i]))


# ---- the base period ---------------------------------------------------------------------


def base_means(plot, base: tuple[int, int] | None) -> list[float | None] | None:
    """The mean of each value's reference: the base period's mean of the series (annual),
    or of the value's calendar month (monthly), so a monthly anomaly is not the season.
    One entry per value; None when the series has no base period (daily) or the base
    period has no values."""
    if base is None or plot.step not in ("year", "month"):
        return None
    values = _values(plot)
    groups: dict[int, list[float]] = {}
    for i, v in enumerate(values):
        if v is not None and base[0] <= _year(plot, i) <= base[1]:
            groups.setdefault(_month(plot, i) if plot.step == "month" else 0, []).append(v)
    if not groups:
        return None
    means = {k: sum(g) / len(g) for k, g in groups.items()}
    if plot.step == "year":
        return [means[0]] * len(values)
    return [means.get(_month(plot, i)) for i in range(len(values))]


def base_mean(plot, base: tuple[int, int] | None) -> float | None:
    """The base period's mean of the series' values (all months for a monthly series)."""
    if base is None or plot.step not in ("year", "month"):
        return None
    present = [
        v
        for i, v in enumerate(_values(plot))
        if v is not None and base[0] <= _year(plot, i) <= base[1]
    ]
    return sum(present) / len(present) if present else None


def anomalies(plot, base) -> list[float | None] | None:
    """Each value less its base-period mean (:func:`base_means`); None without one."""
    means = base_means(plot, base)
    if means is None:
        return None
    return [
        None if v is None or m is None else v - m for v, m in zip(_values(plot), means, strict=True)
    ]


def has_anomalies(plot, base) -> bool:
    """Whether the page offers the anomaly view: annual or monthly values (not SPI's
    bars, already standardised) with a base period inside the series."""
    return not plot.bars and base_means(plot, base) is not None


# ---- the chart ---------------------------------------------------------------------------


def running_mean(values: list[float | None], window: int) -> list[float | None]:
    """The centred mean of ``window`` values (odd), where at least half of them are
    present; None at the ends, where the window does not fit."""
    half = window // 2
    out: list[float | None] = [None] * len(values)
    for i in range(half, len(values) - half):
        chunk = [v for v in values[i - half : i + half + 1] if v is not None]
        if len(chunk) * 2 >= window:
            out[i] = sum(chunk) / len(chunk)
    return out


def nice_ticks(low: float, high: float, count: int = 4) -> list[float]:
    """Round values from at or below ``low`` to at or above ``high``, about ``count``
    steps apart: steps of 1, 2, 2.5 or 5 times a power of ten."""
    if high <= low:
        high = low + 1
    raw = (high - low) / count
    power = 10 ** math.floor(math.log10(raw))
    step = next(m * power for m in (1, 2, 2.5, 5, 10) if m * power >= raw)
    first = math.floor(low / step + 1e-9) * step
    last = math.ceil(high / step - 1e-9) * step
    n = round((last - first) / step)
    return [round(first + k * step, 10) for k in range(n + 1)]


def _year_ticks(first: int, last: int) -> list[int]:
    """The years under the axis: the first, every 5, 10, 20... years after it, and the
    last; one too close to the last is left out."""
    span = last - first
    if span <= 0:
        return [first]
    step = next((s for s in (1, 2, 5, 10, 20, 25, 50, 100) if span / s <= 5), 200)
    years = list(range(first, last, step))
    if years and last - years[-1] < step / 2 and len(years) > 1:
        years.pop()
    return [*years, last]


@dataclass
class Chart:
    """What the chart template draws: SVG coordinates and path data."""

    box: str
    left: int
    right: int
    top: int
    bottom: int
    height: int
    tick_x: int
    label_y: int
    title_x: int
    title_y: float
    y_title: str
    y_ticks: list[dict]
    x_ticks: list[dict]
    line: str = ""
    pos: str = ""
    neg: str = ""
    bar_width: str = ""
    zero: float | None = None
    smooth: str = ""
    trend: dict | None = None
    interval: str = ""
    band: dict | None = None
    gaps: list[dict] | None = None


def chart(card, plot, base, anomaly: bool = False) -> Chart | None:
    """The page's chart of ``plot``: its values (or anomalies from the base-period mean,
    ``anomaly``) as a line, with gaps where values are missing, or as bars from zero
    (SPI, SPEI); the 11-year running mean; Sen's slope dashed across it, its 95%
    interval as a band (the lines of the lower and upper slopes through the slope's
    middle); the base period as a band; the values left out as open points at the
    base-period mean (or zero, as anomalies); and axes with round values, the y axis
    titled with the code and units. None when every value is missing."""
    values = _values(plot)
    means = base_means(plot, base)
    if anomaly:
        values = anomalies(plot, base) or values
    present = [v for v in values if v is not None]
    if not present:
        return None
    n = len(values)
    step = plot.step
    smooth: list[float | None] = []
    if step in ("year", "month") and not plot.bars:
        window = RUNNING_YEARS * (12 if step == "month" else 1)
        smooth = running_mean(values, window + (1 - window % 2))
    trend = plot.trend if plot.trend is not None and plot.trend.valid else None
    lines = {}
    if trend is not None:
        mid = (n - 1) / 2
        centre = trend.intercept + trend.slope * mid
        if anomaly and means:
            reference = [m for m in means if m is not None]
            centre -= sum(reference) / len(reference)
        for key, slope in (("slope", trend.slope), ("lower", trend.lower), ("upper", trend.upper)):
            lines[key] = (centre - slope * mid, centre, centre + slope * (n - 1 - mid))
    gap_level = []
    if step in ("year", "month") and not plot.bars:
        for i, v in enumerate(values):
            if v is None:
                level = 0.0 if anomaly else (means[i] if means else None)
                if level is None:
                    level = sum(present) / len(present)
                gap_level.append((i, level))
    extent = present + [v for v in smooth if v is not None] + [lv for _i, lv in gap_level]
    for ends in lines.values():
        extent += [ends[0], ends[2]]
    if plot.bars or anomaly:
        extent.append(0.0)
    ticks = nice_ticks(min(extent), max(extent))
    low, high = ticks[0], ticks[-1]

    def y(v: float) -> float:
        return round(BOTTOM - (v - low) / (high - low) * (BOTTOM - TOP), 1)

    def x(i: float) -> float:
        if n == 1:
            return (LEFT + RIGHT) / 2
        return round(LEFT + i * (RIGHT - LEFT) / (n - 1), 1)

    units = numbers.unit_label(card.units)
    if anomaly:
        y_title = _("Anomaly %(units)s") % {"units": units} if units else _("Anomaly")
    else:
        y_title = f"{card.code} {units}".strip()
    out = Chart(
        box=f"0 0 {CHART_W} {CHART_H}",
        left=LEFT,
        right=RIGHT,
        top=TOP,
        bottom=BOTTOM,
        height=BOTTOM - TOP,
        tick_x=LEFT - 8,
        label_y=X_LABEL_Y,
        title_x=14,
        title_y=(TOP + BOTTOM) / 2,
        y_title=y_title,
        y_ticks=[{"y": y(t), "text": _tick_text(t, anomaly)} for t in reversed(ticks)],
        x_ticks=_x_ticks(plot, x),
    )
    if plot.bars:
        zero = y(0.0)
        pos, neg = [], []
        for i, v in enumerate(values):
            if v is not None and y(v) != zero:
                (pos if v > 0 else neg).append(f"M{x(i)} {zero}V{y(v)}")
        out.pos, out.neg, out.zero = "".join(pos), "".join(neg), zero
        out.bar_width = f"{max((RIGHT - LEFT) / n - 0.3, 0.5):.1f}"
    else:
        out.line = _path(values, x, y)
        if anomaly:
            out.zero = y(0.0)
    out.smooth = _path(smooth, x, y)
    if lines:
        a, _m, b = lines["slope"]
        out.trend = {"x1": x(0), "y1": y(a), "x2": x(n - 1), "y2": y(b)}
        lo, mid_y, hi = lines["lower"], lines["slope"][1], lines["upper"]
        xm = x((n - 1) / 2)
        out.interval = " ".join(
            f"{px},{py}"
            for px, py in (
                (x(0), y(max(lo[0], hi[0]))),
                (xm, y(mid_y)),
                (x(n - 1), y(max(lo[2], hi[2]))),
                (x(n - 1), y(min(lo[2], hi[2]))),
                (xm, y(mid_y)),
                (x(0), y(min(lo[0], hi[0]))),
            )
        )
    out.band = _base_band(plot, base, x)
    out.gaps = [{"x": x(i), "y": y(level)} for i, level in gap_level]
    return out


def _tick_text(value: float, anomaly: bool) -> str:
    text = numbers.number(value)
    return "+" + text if anomaly and value > 0 else text


def _path(values: list[float | None], x, y) -> str:
    parts, pen = [], False
    for i, v in enumerate(values):
        if v is None:
            pen = False
            continue
        parts.append(f"{'L' if pen else 'M'}{x(i)} {y(v)}")
        pen = True
    return "".join(parts)


def _position(plot, x):
    """Where a fractional year falls on the chart's x axis, by the series' own x."""
    xs = [float(v) for v in plot.x]
    n = len(xs)

    def at(value: float) -> float:
        if n == 1 or xs[-1] == xs[0]:
            return x(0)
        return round(LEFT + (value - xs[0]) / (xs[-1] - xs[0]) * (RIGHT - LEFT), 1)

    return xs, at


def _x_ticks(plot, x) -> list[dict]:
    xs, at = _position(plot, x)
    if plot.step in ("year", "month"):
        # A month's value sits in the middle of its month: a year's tick at its January.
        offset = 0.5 / 12 if plot.step == "month" else 0.0
        years = _year_ticks(math.floor(xs[0]), math.floor(xs[-1]))
        ticks = [{"x": at(year + offset), "text": str(year), "anchor": "middle"} for year in years]
    else:
        n = len(xs)
        ticks = [
            {"x": x(i), "text": chart_data._x_label(plot.step, xs[i]), "anchor": "middle"}
            for i in sorted({0, n // 4, n // 2, 3 * n // 4, n - 1})
        ]
    if ticks:
        ticks[0]["anchor"] = "start" if ticks[0]["x"] <= LEFT + 20 else "middle"
        if len(ticks) > 1:
            ticks[-1]["anchor"] = "end" if ticks[-1]["x"] >= RIGHT - 20 else "middle"
    return ticks


def _base_band(plot, base, x) -> dict | None:
    """The base period's years as a band: whole years, from the start of the first to
    the end of the last (a year's value sits at the year, a month's in its middle)."""
    if not base or plot.step not in ("year", "month") or len(plot.x) < 2:
        return None
    _xs, at = _position(plot, x)
    if plot.step == "year":
        start, end = base[0] - 0.5, base[1] + 0.5
    else:
        start, end = base[0], base[1] + 1
    left, right = max(at(start), LEFT), min(at(end), RIGHT)
    if right <= left:
        return None
    return {
        "x": round(left, 1),
        "width": round(right - left, 1),
        "label_x": round((left + right) / 2, 1),
        "label_y": TOP + 13,
    }


def _rounded(values: list[float | None], digits: int | None = None) -> list[float | None]:
    """Values for the page's JSON, as precise as the read-out writes them (``digits``: an
    anomaly's places)."""
    return [chart_data.shown(v, digits) for v in values]


def payload(card, plot, base, gone: list[dict], day_plot=None, name: str = "") -> dict:
    """The interactive chart's data (#283): the ``index`` payload of
    :mod:`climpact_web.charts.data` (``x``, ``y``, ``trend``, ``dates``, ``summary``) with
    the layers this page draws (``layers``: the base period, the 11-year running mean,
    the values left out with their level and why), and the anomaly view (``views``:
    each view's values, running mean, ``[index, level]`` of the values left out, the y
    axis's title and how far its trend line is moved). Values are as precise as the
    read-out writes them, anomalies rounded once to their one place (as
    ``numbers.anomaly``, so the read-out shows the statistics' number, #349); the notes
    are ``[index, why]``. Built from what :func:`chart`
    draws, so the interactive chart and the server's SVG show the same marks."""
    values = _values(plot)
    step = plot.step
    means = base_means(plot, base)
    notes = {g["index"]: g["note"] for g in gone}
    units = numbers.unit_label(card.units)

    def view(series: list[float | None], anomaly: bool) -> dict:
        present = [v for v in series if v is not None]
        smooth: list[float | None] = []
        if step in ("year", "month") and not plot.bars:
            window = RUNNING_YEARS * (12 if step == "month" else 1)
            smooth = running_mean(series, window + (1 - window % 2))
        gaps: list[list] = []  # [index, level] of each value left out
        if step in ("year", "month") and not plot.bars and present:
            for i, v in enumerate(series):
                if v is None:
                    level = 0.0 if anomaly else (means[i] if means else None)
                    level = sum(present) / len(present) if level is None else level
                    gaps.append([i, chart_data.shown(level)])
        offset = 0.0
        if anomaly and means:
            reference = [m for m in means if m is not None]
            offset = sum(reference) / len(reference)
        if anomaly:
            axis = _("Anomaly %(units)s") % {"units": units} if units else _("Anomaly")
        else:
            axis = f"{card.code} {units}".strip()
        digits = ANOMALY_DIGITS if anomaly else None
        out = {
            "y": _rounded(series, digits),
            "smooth": _rounded(smooth, digits) if any(v is not None for v in smooth) else None,
            "gaps": gaps or None,
            "axis": axis,
            "offset": offset,
        }
        if anomaly:
            out["signed_digits"] = ANOMALY_DIGITS
        return out

    trend = plot.trend if plot.trend is not None and plot.trend.valid else None
    x = [int(v) if float(v).is_integer() else round(float(v), 6) for v in plot.x]
    views = {"values": view(values, False)}
    anomaly = anomalies(plot, base) if has_anomalies(plot, base) else None
    if anomaly is not None:
        views["anomaly"] = view(anomaly, True)
    band = None
    if base and step in ("year", "month") and len(x) > 1:
        start, end = (base[0] - 0.5, base[1] + 0.5) if step == "year" else (base[0], base[1] + 1)
        start, end = max(start, x[0]), min(end, x[-1])
        if end > start:
            band = {"from": start, "to": end, "label": _("base period")}
    dates = None
    if day_plot is not None:
        dates = [_date(plot, day_plot, i) or None for i in range(len(values))]
    out = {
        "kind": "index",
        "version": chart_data.SCHEMA_VERSION,
        "name": name or plot.name,
        "title": card.code,
        "units": units,
        "axis": views["values"]["axis"],
        "step": step,
        "bars": bool(plot.bars),
        "x": x,
        "y": views["values"]["y"],
        "label": card.code,
        "trend": None,
        "summary": chart_label(card, plot, base),
        "layers": {
            "base": band,
            "smooth_label": _("11-year running mean"),
            "gap_label": _("Month left out: incomplete")
            if step == "month"
            else _("Year left out: incomplete"),
            "notes": [[i, note] for i, note in sorted(notes.items())] or None,
            "anomaly_label": _("Anomaly"),
            "interval": trend is not None,
        },
        "views": views,
    }
    if dates and any(dates):
        out["dates"] = dates
    if trend is not None:
        out["trend"] = {
            "slope": trend.slope,
            "lower": trend.lower,
            "upper": trend.upper,
            "intercept": trend.intercept,
            "label": _("Sen's slope, with 95% interval shaded"),
        }
    return out


def chart_label(card, plot, base, anomaly: bool = False) -> str:
    """The chart's text alternative: the series, its years, its lowest and highest
    values and its trend in words, and what the anomalies are from."""
    from climpact_web.stations import index_detail

    text = index_detail.summary(card, plot)
    if anomaly and base:
        text += " " + _("Shown as anomalies from the %(start)s–%(end)s mean.") % {
            "start": base[0],
            "end": base[1],
        }
    return text


# ---- the statistics and the table --------------------------------------------------------


def missing_days(analysis, needs: tuple[str, ...]) -> dict[int, int]:
    """The days each year misses of the variables an index needs (the most of any of
    them), from the file's summary; {} when the summary has no years."""
    out = {}
    for row in (analysis.summary or {}).get("years") or []:
        days = int(row.get("days") or 0)
        missing = [days - int(row.get(v) or 0) for v in needs if v in row]
        out[int(row["year"])] = max(missing, default=0)
    return out


def left_out(plot, missing: dict[int, int]) -> list[dict]:
    """The values left out (missing) and why, in the series' order: for a year, the days
    the file misses, which fail the completeness rule (more than 15 days, or more than 3
    in a month); for a month after the first value, the completeness rule (more than 3
    days missing); before it (SPI's and SPEI's first months, which a scale of n months
    leaves without a value) and otherwise, no value."""
    out = []
    values = _values(plot)
    first = next((i for i, v in enumerate(values) if v is not None), len(values))
    for i, v in enumerate(values):
        if v is not None:
            continue
        when = chart_data._x_label(plot.step, float(plot.x[i]))
        days = missing.get(_year(plot, i), 0) if plot.step == "year" else 0
        if days:
            note = ngettext(
                "Left out: %(days)s day missing", "Left out: %(days)s days missing", days
            ) % {"days": days}
            sentence = ngettext(
                "%(when)s left out: %(days)s day missing, so the year fails the completeness rule.",
                "%(when)s left out: %(days)s days missing, so the year fails the "
                "completeness rule.",
                days,
            ) % {"when": when, "days": days}
        elif plot.step == "month" and i > first:
            note = _("Left out: incomplete")
            sentence = _("%(when)s left out: the month fails the completeness rule.") % {
                "when": when
            }
        else:
            note = _("No value")
            sentence = _("%(when)s has no value.") % {"when": when}
        out.append({"index": i, "when": when, "note": note, "sentence": sentence})
    return out


def left_out_summary(plot, gone: list[dict]) -> list[str]:
    """The statistics' lines on the values left out: each one's sentence, up to
    ``LEFT_OUT_NAMED``; more than that, a count and the table."""
    if not gone:
        return []
    if len(gone) <= LEFT_OUT_NAMED:
        return [g["sentence"] for g in gone]
    if plot.step == "month":
        text = ngettext(
            "%(count)s month has no value. The table says why.",
            "%(count)s months have no value. The table says why.",
            len(gone),
        )
    else:
        text = ngettext(
            "%(count)s year has no value. The table says why.",
            "%(count)s years have no value. The table says why.",
            len(gone),
        )
    return [text % {"count": len(gone)}]


def _ranks(values: list[float | None], low: bool) -> list[int | None]:
    """Each value's rank, 1 the record (the highest, or the lowest when ``low``); tied
    values share the better rank."""
    present = sorted((v for v in values if v is not None), reverse=not low)
    first = {}
    for r, v in enumerate(present, 1):
        first.setdefault(v, r)
    return [None if v is None else first[v] for v in values]


def _date(plot, day_plot, i: int) -> str:
    """The date of the ``i``-th value's extreme, from its ``day_of_`` series: the day of
    the year (annual) or of the month (monthly)."""
    if day_plot is None or i >= len(day_plot.values):
        return ""
    day = day_plot.values[i]
    if day != day:
        return ""
    year = _year(plot, i)
    try:
        if plot.step == "month":
            return datetime.date(year, _month(plot, i) + 1, int(day)).isoformat()
        return (datetime.date(year, 1, 1) + datetime.timedelta(days=int(day) - 1)).isoformat()
    except (ValueError, OverflowError):
        return ""


def table(card, plot, day_plot, base, gone: list[dict]) -> list[dict]:
    """The values as the table shows them, most recent first: when, the value, its
    anomaly from the base-period mean, its rank, the date of the extreme and a note
    ("Record", or why the value was left out)."""
    values = _values(plot)
    anomaly = anomalies(plot, base) if has_anomalies(plot, base) else None
    ranks = _ranks(values, low_is_record(card.key))
    notes = {g["index"]: g["note"] for g in gone}
    rows = []
    # A day of the year's threshold (TX95t) in the year's order; years and months most
    # recent first.
    order = range(len(values)) if plot.step == "day" else reversed(range(len(values)))
    for i in order:
        v = values[i]
        rows.append(
            {
                "when": chart_data._x_label(plot.step, float(plot.x[i])),
                "value": "–" if v is None else numbers.number(v),
                "anomaly": "–"
                if anomaly is None or anomaly[i] is None
                else numbers.anomaly(anomaly[i]),
                "rank": "–" if ranks[i] is None else str(ranks[i]),
                "date": _date(plot, day_plot, i) or "–",
                "note": notes.get(i)
                or (_("Record") if ranks[i] == 1 and plot.step != "day" else ""),
                "missing": v is None,
            }
        )
    return rows


def record(card, plot) -> str:
    """The record value with its unit and when: "45.8 °C, 2013"; "" without values or
    for a day of the year's threshold (TX95t), which is no record."""
    values = _values(plot) if plot.step in ("year", "month") else []
    present = [(v, i) for i, v in enumerate(values) if v is not None]
    if not present:
        return ""
    value, i = (min if low_is_record(card.key) else max)(present, key=lambda p: (p[0], -p[1]))
    return _("%(value)s, %(when)s") % {
        "value": numbers.with_unit(numbers.number(value), card.units),
        "when": chart_data._x_label(plot.step, float(plot.x[i])),
    }


def citation(analysis, card, plot, base, version: str, today: datetime.date) -> str:
    """The citation "Copy citation" copies: the station, the index, its years and base
    period, the software and the date."""
    station = analysis.station_name or analysis.file_name
    first = chart_data._x_label("year", float(plot.x[0])) if plot.step != "day" else ""
    last = chart_data._x_label("year", float(plot.x[-1])) if plot.step != "day" else ""
    parts = {
        "station": station,
        "code": card.code,
        "name": card.title,
        "first": first,
        "last": last,
        "version": version,
        "date": today.isoformat(),
    }
    if base and first:
        parts.update(start=base[0], end=base[1])
        text = _(
            "%(station)s, %(code)s (%(name)s), %(first)s–%(last)s, base period "
            "%(start)s–%(end)s. Calculated with Climpact (climpact %(version)s), ET-SCI "
            "indices; trend by Sen's slope. Accessed %(date)s."
        )
    elif first:
        text = _(
            "%(station)s, %(code)s (%(name)s), %(first)s–%(last)s. Calculated with "
            "Climpact (climpact %(version)s), ET-SCI indices; trend by Sen's slope. "
            "Accessed %(date)s."
        )
    else:
        text = _(
            "%(station)s, %(code)s (%(name)s). Calculated with Climpact (climpact "
            "%(version)s), ET-SCI indices. Accessed %(date)s."
        )
    return text % parts
