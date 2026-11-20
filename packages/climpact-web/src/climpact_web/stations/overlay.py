"""Overlay the series (#276): one index's series at every station of a workspace, on
shared axes, on a page of its own (``/w/<id>/compare/<code>/overlay``, the maintainer's
decision on #276; no board draws it, so it is built from DESIGN.md's chart rules).

Each station with values is a line in a categorical chart slot (``--chart-1`` to
``--chart-8``), in the overview's order, its name in the legend. The slots are a fixed
order and never cycled, so the chart draws **eight stations at most**: with more, the first
eight with values are drawn and the user chooses which eight (``?stations=``); the table
view and the CSV have every station. The series is the one whose trend the trend grid
shows (the card's main series: annual where the index has it, monthly for SPI and SPEI).

Stations are treated as the trend grid treats them (``trend_grid._stations``): a station
whose results are out of date (#279) is drawn and tagged "· out of date"; one whose run made
no index table (#298, #315), one without results and one without the index are left out
and named under the chart ("Not shown: Empty Hill: no indices"), as the interval plot names
them. A station whose values are all missing is named there too.

The chart is drawn here on the server (:func:`chart`, the chart without JavaScript and in
print) and, with JavaScript, by ``charts.js`` from :func:`payload` (the read-out, zoom and
PNG and SVG), as the index page's (#237, #283). Nothing here calculates an index: the
values are the core's, as in the files.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass, field

from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from climpact_web.charts import data as chart_data
from climpact_web.core import numbers
from climpact_web.stations import trend_grid, workspace_files
from climpact_web.stations.index_page import _year_ticks, nice_ticks

# The categorical slots (--chart-1 to --chart-8): a fixed order, never cycled.
SLOTS = 8

# The server's chart: a box as wide as the page's content allows at 1280px, with the index
# page's margins (#237).
CHART_W, CHART_H = 1000, 340
LEFT, RIGHT, TOP, BOTTOM = 64, 988, 16, 300
X_LABEL_Y = 320


@dataclass
class Line:
    """A station with values of the index: its series on the chart's years."""

    name: str
    slug: str
    url: str  # the station's index page
    values: list[float | None]
    out_of_date: bool = False
    slot: int = 0  # 1-8 when drawn, 0 when not
    path: str = ""  # the server chart's path
    dots: list[dict] = field(default_factory=list)  # values with no neighbour: a dot each

    @property
    def drawn(self) -> bool:
        return self.slot > 0

    @property
    def token(self) -> str:
        return f"--chart-{self.slot}" if self.slot else ""


@dataclass
class Overlay:
    choice: trend_grid.Choice
    step: str  # "year" or "month"
    x: list[float]
    lines: list[Line]  # every station with values, in the overview's order
    left_out: list[str]  # "Empty Hill: no indices"
    summary: str = ""
    chart: dict | None = None
    rows: list[dict] = field(default_factory=list)  # the table view, most recent first
    chosen_too_many: bool = False  # more than eight were asked for: the first eight drawn
    unit_source: str = ""  # the index's units, as the card has them

    @property
    def drawn(self) -> list[Line]:
        return [line for line in self.lines if line.drawn]

    @property
    def too_many(self) -> bool:
        """More stations with values than slots: the user chooses which eight are drawn."""
        return len(self.lines) > SLOTS

    @property
    def units(self) -> str:
        return numbers.unit_label(self.unit_source)

    @property
    def axis(self) -> str:
        return f"{self.choice.code} {self.units}".strip()

    @property
    def first_year(self) -> int | None:
        return math.floor(self.x[0]) if self.x else None

    @property
    def last_year(self) -> int | None:
        return math.floor(self.x[-1]) if self.x else None


# ---- the stations' series --------------------------------------------------------------


def _key(x: float) -> float:
    return round(float(x), 6)


def _value(v) -> float | None:
    return None if v is None or v != v else float(v)


def overlay(
    stations: list[trend_grid._Station], choice: trend_grid.Choice, wanted: list[str] | None
) -> Overlay:
    """The overlay of ``choice`` at ``stations`` (``trend_grid._stations``, in the
    overview's order): every station with values as a line, the first eight drawn (or the
    first eight of the slugs ``wanted``), the others named and why."""
    series, left_out, step, units = [], [], "year", ""
    for s in stations:
        entry = s.entry
        card = s.cards.get(choice.code)
        if s.failed:
            left_out.append(_("%(name)s: failed") % {"name": entry.name})
            continue
        if s.no_indices:
            left_out.append(_("%(name)s: no indices") % {"name": entry.name})
            continue
        if entry.source is None:
            left_out.append(_("%(name)s: no results") % {"name": entry.name})
            continue
        plot = s.plots.get(card.main) if card is not None else None
        if plot is None:
            left_out.append(_("%(name)s: not calculated") % {"name": entry.name})
            continue
        values = {_key(x): _value(v) for x, v in zip(plot.x, plot.values, strict=False)}
        if not any(v is not None for v in values.values()):
            left_out.append(_("%(name)s: every value missing") % {"name": entry.name})
            continue
        step, units = plot.step, card.units
        series.append((s, card, values))
    x = sorted({k for _s, _c, values in series for k, v in values.items() if v is not None})
    if x:  # every year (or month) from the first value to the last: gaps stay gaps
        x = sorted({k for _s, _c, values in series for k in values if x[0] <= k <= x[-1]})
    lines = [
        Line(
            name=s.entry.name,
            slug=s.entry.station.slug,
            url=s.entry.station.url("result", card.key),
            values=[values.get(k) for k in x],
            out_of_date=s.out_of_date,
        )
        for s, card, values in series
    ]
    result = Overlay(choice, step, x, lines, left_out, unit_source=units)
    _choose(result, wanted)
    result.summary = summary(result, {s.entry.station.slug: c for s, c, _v in series})
    result.chart = chart(result)
    result.rows = table(result)
    return result


def _choose(result: Overlay, wanted: list[str] | None) -> None:
    """Give the drawn lines their slots, in the overview's order: the stations ``wanted``
    (their first eight), else the first eight."""
    chosen = [line for line in result.lines if wanted and line.slug in set(wanted)]
    result.chosen_too_many = len(chosen) > SLOTS
    if not chosen:
        chosen = result.lines
    keep = {line.slug for line in chosen[:SLOTS]}
    slot = 0
    for line in result.lines:
        if line.slug in keep:
            slot += 1
            line.slot = slot


# ---- the text summary ----------------------------------------------------------------------


def _extreme(result: Overlay, high: bool) -> tuple[float, Line, int] | None:
    best = None
    for line in result.lines:
        for i, v in enumerate(line.values):
            if v is None:
                continue
            if best is None or (v > best[0] if high else v < best[0]):
                best = (v, line, i)
    return best


def _when(result: Overlay, i: int) -> str:
    return chart_data._x_label(result.step, result.x[i])


def summary(result: Overlay, cards: dict) -> str:
    """The chart's text summary: the series and its years, the stations, the highest and
    lowest values with their station and year, and how many stations have a significant
    trend; with more stations than slots, which are drawn."""
    choice, n = result.choice, len(result.lines)
    if not n:
        return _("No station has values of %(code)s.") % {"code": choice.code}
    values = {
        "code": choice.code,
        "name": choice.title,
        "count": n,
        "first": result.first_year,
        "last": result.last_year,
    }
    if result.step == "month":
        text = ngettext(
            "%(code)s %(name)s, monthly values at %(count)s station, %(first)s–%(last)s.",
            "%(code)s %(name)s, monthly values at %(count)s stations, %(first)s–%(last)s.",
            n,
        )
    else:
        text = ngettext(
            "%(code)s %(name)s, annual values at %(count)s station, %(first)s–%(last)s.",
            "%(code)s %(name)s, annual values at %(count)s stations, %(first)s–%(last)s.",
            n,
        )
    parts = [text % values]
    high, low = _extreme(result, True), _extreme(result, False)
    if high and low:
        parts.append(
            _(
                "Highest %(high)s (%(high_station)s, %(high_when)s); "
                "lowest %(low)s (%(low_station)s, %(low_when)s)."
            )
            % {
                "high": numbers.with_unit(numbers.number(high[0]), result.units),
                "high_station": high[1].name,
                "high_when": _when(result, high[2]),
                "low": numbers.with_unit(numbers.number(low[0]), result.units),
                "low_station": low[1].name,
                "low_when": _when(result, low[2]),
            }
        )
    with_trend = [c.trend for c in cards.values() if c.trend and c.trend.get("valid")]
    significant = sum(1 for t in with_trend if t["significant"])
    parts.append(
        ngettext(
            "%(significant)s of %(total)s station has a significant trend.",
            "%(significant)s of %(total)s stations have a significant trend.",
            len(with_trend),
        )
        % {"significant": significant, "total": len(with_trend)}
    )
    stale = [line.name for line in result.lines if line.out_of_date]
    if stale:
        parts.append(
            ngettext(
                "The values of %(names)s are from before the last change.",
                "The values of %(names)s are from before the last change.",
                len(stale),
            )
            % {"names": ", ".join(stale)}
        )
    if result.too_many:
        parts.append(
            _("The chart draws %(drawn)s of the %(count)s; the table has them all.")
            % {"drawn": len(result.drawn), "count": n}
        )
    return " ".join(parts)


# ---- the server's chart --------------------------------------------------------------------


def _path(values: list[float | None], x, y) -> tuple[str, list[dict]]:
    """The line's path, broken where values are missing, and a dot for each value with
    no neighbour (a line of one point draws nothing)."""
    parts, dots, n = [], [], len(values)
    for i, v in enumerate(values):
        if v is None:
            continue
        before = i > 0 and values[i - 1] is not None
        after = i < n - 1 and values[i + 1] is not None
        parts.append(f"{'L' if before else 'M'}{x(i)} {y(v)}")
        if not before and not after:
            dots.append({"x": x(i), "y": y(v)})
    return "".join(parts), dots


def chart(result: Overlay) -> dict | None:
    """The chart drawn on the server: the drawn stations' lines on shared axes (round
    values, the y axis titled with the code and units; the years under it), in the box
    ``CHART_W`` x ``CHART_H``. None without a value."""
    drawn = result.drawn
    present = [v for line in drawn for v in line.values if v is not None]
    if not present:
        return None
    xs = result.x
    ticks = nice_ticks(min(present), max(present))
    low, high = ticks[0], ticks[-1]

    def y(v: float) -> float:
        return round(BOTTOM - (v - low) / (high - low) * (BOTTOM - TOP), 1)

    def at(value: float) -> float:
        if len(xs) == 1 or xs[-1] == xs[0]:
            return (LEFT + RIGHT) / 2
        return round(LEFT + (value - xs[0]) / (xs[-1] - xs[0]) * (RIGHT - LEFT), 1)

    def x(i: int) -> float:
        return at(xs[i])

    for line in drawn:
        line.path, line.dots = _path(line.values, x, y)
    offset = 0.5 / 12 if result.step == "month" else 0.0
    years = _year_ticks(math.floor(xs[0]), math.floor(xs[-1]))
    x_ticks = [{"x": at(year + offset), "text": str(year), "anchor": "middle"} for year in years]
    if x_ticks:
        x_ticks[0]["anchor"] = "start" if x_ticks[0]["x"] <= LEFT + 20 else "middle"
        if len(x_ticks) > 1:
            x_ticks[-1]["anchor"] = "end" if x_ticks[-1]["x"] >= RIGHT - 20 else "middle"
    return {
        "box": f"0 0 {CHART_W} {CHART_H}",
        "left": LEFT,
        "right": RIGHT,
        "top": TOP,
        "bottom": BOTTOM,
        "tick_x": LEFT - 8,
        "label_y": X_LABEL_Y,
        "title_x": 14,
        "title_y": (TOP + BOTTOM) / 2,
        "y_title": result.axis,
        "y_ticks": [{"y": y(t), "text": numbers.number(t)} for t in reversed(ticks)],
        "x_ticks": x_ticks,
        "zero": y(0.0) if low < 0 < high else None,
    }


# ---- the table view and the interactive chart's data ---------------------------------------


def table(result: Overlay) -> list[dict]:
    """The table view: a row a year (or month), most recent first, as the index page's
    values table; a cell a station with values, drawn or not."""
    rows = []
    for i in reversed(range(len(result.x))):
        rows.append(
            {
                "when": _when(result, i),
                "values": [
                    numbers.number(line.values[i]) if line.values[i] is not None else ""
                    for line in result.lines
                ],
            }
        )
    return rows


def payload(result: Overlay) -> dict:
    """The interactive chart's data (``charts.js``, kind ``overlay``): the years (or
    months), each drawn station's values as precise as the read-out writes them, its name
    and slot, the axis's title and the summary. The same lines as :func:`chart`."""
    title = _("%(code)s %(name)s at each station") % {
        "code": result.choice.code,
        "name": result.choice.title,
    }
    return {
        "kind": "overlay",
        "version": chart_data.SCHEMA_VERSION,
        "name": f"{result.choice.code}_all_stations",
        "title": title,
        "units": result.units,
        "axis": result.axis,
        "step": result.step,
        "x": [int(v) if float(v).is_integer() else v for v in result.x],
        "series": [
            {
                "label": _("%(name)s · out of date") % {"name": line.name}
                if line.out_of_date
                else line.name,
                "short": line.name,
                "token": line.token,
                "values": [chart_data.shown(v) for v in line.values],
            }
            for line in result.drawn
        ],
        "summary": result.summary,
    }


# ---- the page ------------------------------------------------------------------------------


def for_index(
    items: list[workspace_files.Entry], code: str, wanted: list[str] | None
) -> Overlay | None:
    """The overlay of the index ``code`` at the workspace's stations (``items``, in the
    overview's order); None when no station has a trend of it (an index the trend grid
    does not offer)."""
    stations = trend_grid._stations(items)
    choice = next((c for c in trend_grid.available(stations) if c.code == code), None)
    if choice is None:
        return None
    return overlay(stations, choice, wanted)


def index_csv(items: list[workspace_files.Entry], code: str) -> str:
    """The workspace's Indices file (``workspace_files.indices_csv``: station, index, year,
    month, value) cut to the rows of one index."""
    reader = csv.reader(io.StringIO(workspace_files.indices_csv(items)))
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(next(reader))
    writer.writerows(r for r in reader if r[1] == code)
    return out.getvalue()
