"""Trends across stations (#238, the Workspace board): the trend grid and the interval
plot.

The **trend grid** is a table of the workspace's stations by indices (by default TXx, TNn,
TN90p, TX10p, SU, TR, WSDI, PRCPTOT, Rx1day, R95p and CDD; the user chooses others). Each
cell is the station's Sen's slope per decade, always written, so colour is never the only
cue: filled on the trend scale when the 95% interval excludes zero (orange for an increase,
blue for a decrease, the strong step for a slope at least half the largest in its column),
a dashed edge when it does not, hatched for a station without results. A station whose
results are out of date (``workspace_files.Entry.out_of_date``: its recalculation failed, or
was not run or cancelled) is tagged "· out of date" after its name, in the grid and in the
plot, as Files and its Indices say (#279). A station whose run made no index table (every
index skipped, as for a file whose values are all missing) is hatched and tagged "· no
indices", as its row on the overview and its Indices tab say (#298, #315).

The **interval plot** is the selected column: each station's slope as a dot and its 95%
interval as a line about a zero line, on an axis shared by the stations (symmetric about
zero, round ends), each station's name a link to its index page.

Both read the results each station shows (``workspace_files.entries``), so the grid, its
CSV and the per-station trend files agree. On the overview and on Compare an index
(``views_workspace.compare_page``).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from django.utils.translation import gettext as _

from climpact_web.core import numbers
from climpact_web.stations import workspace_files
from climpact_web.stations.index_page import nice_ticks

# The board's columns, in its order (the ticket's defaults).
DEFAULT_CODES = (
    "TXx",
    "TNn",
    "TN90p",
    "TX10p",
    "SU",
    "TR",
    "WSDI",
    "PRCPTOT",
    "Rx1day",
    "R95p",
    "CDD",
)
SESSION_KEY = "trend_grid:{}"  # the columns a user chose for a workspace

# A failed station's out-of-date trends (#279): shown and tagged "· out of date" (True), as
# its Indices keep them under "The recalculation failed"; or hidden, its row hatched and
# tagged "· failed" as the Calculate board draws a failed row (False). The maintainer's
# decision (#279).
SHOW_FAILED_OUT_OF_DATE = True

# The interval plot's box (the board's): 360 x 16, zero in the middle, 6 at either end.
PLOT_WIDTH, PLOT_MIDDLE, PLOT_REACH = 360, 180, 172


@dataclass
class Choice:
    """An index the grid can show: one with a trend at some station."""

    code: str
    key: str
    title: str  # the short name: "Hottest day"
    units: str  # the slope's: "°C", "pp", "days"; "" without
    units_title: str  # "percentage points" for pp, for its abbr
    theme: str
    theme_label: str
    hue: str


@dataclass
class Cell:
    state: str  # increase-2, increase-1, decrease-1, decrease-2, not-significant, invalid, none
    text: str = ""
    label: str = ""  # for screen readers and the title: the slope, interval, significant
    url: str = ""  # the station's index page


@dataclass
class GridRow:
    name: str
    url: str
    cells: list[Cell]
    has_results: bool
    why: str = ""  # without results: "not run", "failed"...
    out_of_date: bool = False  # its results are from before a change (#279)
    failed: bool = False  # hatched though it has results: they are out of date and it failed
    no_indices: bool = False  # hatched: its run made no index table (#298, #315)


@dataclass
class Bar:
    name: str
    url: str
    slope: str  # "+0.21"
    interval: str  # "0.10 to 0.33"
    state: str  # increase, decrease, not-significant
    x: str
    low: str
    high: str
    label: str
    out_of_date: bool = False


@dataclass
class IntervalPlot:
    choice: Choice
    bars: list[Bar]
    left_out: list[str]  # "Moruya Heads: no results"
    ticks: list[dict]  # {"x": "6.0", "text": "−0.5", "anchor": "start"}
    summary: str
    csv_url: str = ""
    selected: bool = False


@dataclass
class Grid:
    columns: list[Choice]
    rows: list[GridRow]
    plots: list[IntervalPlot]
    selected: str  # the code of the plotted column
    choices: list[dict] = field(default_factory=list)  # by theme: {"label", "items"}
    chosen: set = field(default_factory=set)
    has_results: bool = False
    choice_count: int = 0

    @property
    def plot(self) -> IntervalPlot | None:
        return next((p for p in self.plots if p.selected), None)


# ---- the stations' trends -------------------------------------------------------------


@dataclass
class _Station:
    entry: workspace_files.Entry  # or anything with name, source, why and station.url
    cards: dict  # code -> results.Card with a trend
    out_of_date: bool = False  # the trends shown are from before a change (#279)
    failed: bool = False  # out of date and failed, hidden (``SHOW_FAILED_OUT_OF_DATE``)
    no_indices: bool = False  # its run made no index table (#298): nothing to show

    @property
    def has_results(self) -> bool:
        return self.entry.source is not None and not self.failed and not self.no_indices


def _stations(items: list[workspace_files.Entry]) -> list[_Station]:
    out = []
    for entry in items:
        cards = {}
        # A run that skipped every index (#298) has no trend to show, out of date or not.
        no_indices = entry.source is not None and not entry.source.has_tables
        out_of_date = entry.source is not None and entry.out_of_date and not no_indices
        failed = out_of_date and entry.failed and not SHOW_FAILED_OUT_OF_DATE
        if entry.source is not None and not failed and not no_indices:
            run = workspace_files._results(entry)
            ordered = [c for theme in run.themes() for c in theme.cards]
            cards = {c.code: c for c in ordered if c.trend is not None}
        out.append(_Station(entry, cards, out_of_date and not failed, failed, no_indices))
    return out


def available(stations: list[_Station]) -> list[Choice]:
    """Every index with a trend at some station, in the catalogue's order by theme (the
    Indices' rail), the first station's order first."""
    from climpact_web.stations import themes

    seen: dict[str, Choice] = {}
    labels = {t.key: str(t.label) for t in themes.THEMES}
    for station in stations:
        for code, card in station.cards.items():
            if code not in seen:
                seen[code] = Choice(
                    code=code,
                    key=card.key,
                    title=card.title,
                    units=card.trend_units,
                    units_title=card.trend_units_title,
                    theme=card.theme,
                    theme_label=labels.get(card.theme, ""),
                    hue=card.hue,
                )
    order = {t.key: i for i, t in enumerate(themes.THEMES)}
    return sorted(seen.values(), key=lambda c: order.get(c.theme, len(order)))


def columns_for(choices: list[Choice], wanted: list[str] | None) -> list[Choice]:
    """The grid's columns: the indices ``wanted``, else the defaults that some station
    has, else the first eleven offered. Always in one order: the defaults' (the board's)
    first, then the others as offered, so a choice that holds the defaults keeps them as
    they open."""
    rank = {code: i for i, code in enumerate(DEFAULT_CODES)}
    offered = {c.code: i for i, c in enumerate(choices)}

    def order(c: Choice):
        return (rank.get(c.code, len(rank)), offered[c.code])

    if wanted:
        picked = [c for c in choices if c.code in set(wanted)]
        if picked:
            return sorted(picked, key=order)
    picked = [c for c in choices if c.code in rank]
    return sorted(picked, key=order) or choices[: len(DEFAULT_CODES)]


# ---- the grid ---------------------------------------------------------------------------


def _scale(stations: list[_Station], code: str) -> float:
    """The largest significant slope of a column, without its sign: a cell takes the strong
    step from half of it (the board's two steps per index)."""
    sizes = [
        abs(s.cards[code].trend["slope"])
        for s in stations
        if code in s.cards and s.cards[code].trend.get("valid") and s.cards[code].significant
    ]
    return max(sizes, default=0.0)


def _label(choice: Choice, trend: dict) -> str:
    values = {
        "code": choice.code,
        "slope": trend["per_decade_text"],
        "interval": trend["interval_text"],
    }
    if trend["significant"]:
        return _("%(code)s %(slope)s, 95%% interval %(interval)s, significant") % values
    return _("%(code)s %(slope)s, 95%% interval %(interval)s, not significant") % values


def _out_of_date(station: _Station, label: str) -> str:
    """A cell's or a dot's words, with "out of date" when its station's trends are."""
    if station.out_of_date:
        return _("%(label)s, out of date") % {"label": label}
    return label


def _cell(station: _Station, choice: Choice, scale: float) -> Cell:
    entry = station.entry
    if station.failed:
        return Cell("none", label=_("%(code)s: failed") % {"code": choice.code})
    if station.no_indices:
        return Cell("none", label=_("%(code)s: no indices") % {"code": choice.code})
    if entry.source is None:
        return Cell("none", label=_("%(code)s: no results") % {"code": choice.code})
    card = station.cards.get(choice.code)
    url = entry.station.url("result", card.key) if card is not None else ""
    if card is None:
        return Cell("invalid", "–", _("%(code)s: not calculated") % {"code": choice.code})
    trend = card.trend
    if not trend.get("valid"):
        label = _("%(code)s: too few values for a trend") % {"code": choice.code}
        return Cell("invalid", "–", _out_of_date(station, label), url)
    text, label = trend["slope_text"], _out_of_date(station, _label(choice, trend))
    if not trend["significant"]:
        return Cell("not-significant", text, label, url)
    strong = scale > 0 and abs(trend["slope"]) >= scale / 2
    direction = "increase" if trend["slope"] > 0 else "decrease"
    return Cell(f"{direction}-{2 if strong else 1}", text, label, url)


# ---- the interval plot ------------------------------------------------------------------


def _x(value: float, end: float) -> str:
    x = PLOT_MIDDLE + value / end * PLOT_REACH
    return f"{max(6.0, min(PLOT_WIDTH - 6.0, x)):.1f}"


def _axis_end(stations: list[_Station], code: str) -> float:
    """A round end for the plot's axis, symmetric about zero, past every interval."""
    reach = 0.0
    for s in stations:
        card = s.cards.get(code)
        if card is not None and card.trend.get("valid"):
            t = card.trend
            reach = max(reach, abs(t["lower"]), abs(t["upper"]), abs(t["slope"]))
    if reach <= 0:
        return 1.0
    return nice_ticks(0.0, reach, 2)[-1]


def _tick_text(value: float) -> str:
    text = numbers.number(abs(value))
    if value > 0:
        return f"+{text}"
    if value < 0:
        return f"{numbers.MINUS}{text}"
    return "0"


def interval_plot(stations: list[_Station], choice: Choice) -> IntervalPlot:
    end = _axis_end(stations, choice.code)
    bars, left_out = [], []
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
        if card is None:
            left_out.append(_("%(name)s: not calculated") % {"name": entry.name})
            continue
        trend = card.trend
        if not trend.get("valid"):
            left_out.append(_("%(name)s: too few values for a trend") % {"name": entry.name})
            continue
        if trend["significant"]:
            state = "increase" if trend["slope"] > 0 else "decrease"
        else:
            state = "not-significant"
        bars.append(
            Bar(
                name=entry.name,
                url=entry.station.url("result", card.key),
                slope=trend["slope_text"],
                interval=trend["interval_text"],
                state=state,
                x=_x(trend["slope"], end),
                low=_x(trend["lower"], end),
                high=_x(trend["upper"], end),
                label=f"{entry.name}: {_out_of_date(s, _label(choice, trend))}",
                out_of_date=s.out_of_date,
            )
        )
    ticks = [
        {"x": _x(-end, end), "text": _tick_text(-end), "anchor": "start"},
        {"x": _x(0.0, end), "text": "0", "anchor": "middle"},
        {"x": _x(end, end), "text": _tick_text(end), "anchor": "end"},
    ]
    significant = sum(1 for b in bars if b.state != "not-significant")
    summary = _("%(code)s: %(significant)s of %(total)s stations with a significant trend.") % {
        "code": choice.code,
        "significant": significant,
        "total": len(bars),
    }
    return IntervalPlot(choice, bars, left_out, ticks, summary)


# ---- the whole ----------------------------------------------------------------------------


def grid(
    items: list[workspace_files.Entry], wanted: list[str] | None, selected: str | None
) -> Grid:
    """The trend grid of the workspace's stations (``items``, in the overview's order):
    the columns ``wanted`` (else the defaults), the plot of ``selected`` (else the first
    column's). Every column's plot is made, so a column is shown in place."""
    return grid_of(_stations(items), wanted, selected)


def grid_of(stations: list[_Station], wanted: list[str] | None, selected: str | None) -> Grid:
    """:func:`grid` of stations whose trends are read (the pattern library's are made up)."""
    choices = available(stations)
    columns = columns_for(choices, wanted)
    scales = {c.code: _scale(stations, c.code) for c in columns}
    rows = []
    for s in stations:
        cells = [_cell(s, c, scales[c.code]) for c in columns]
        url = s.entry.station.url("results")
        rows.append(
            GridRow(
                s.entry.name,
                url,
                cells,
                s.has_results,
                s.entry.why,
                s.out_of_date,
                s.failed,
                s.no_indices,
            )
        )
    codes = [c.code for c in columns]
    by_code = {c.code: c for c in choices}
    if selected not in by_code:
        selected = codes[0] if codes else ""
    plotted = list(columns)
    if selected and selected not in codes:  # an index chosen on Compare, not a column
        plotted.append(by_code[selected])
    plots = [interval_plot(stations, c) for c in plotted]
    for plot in plots:
        plot.selected = plot.choice.code == selected
    groups: dict[str, dict] = {}
    for c in choices:
        groups.setdefault(c.theme, {"label": c.theme_label, "hue": c.hue, "items": []})
        groups[c.theme]["items"].append(c)
    return Grid(
        columns=columns,
        rows=rows,
        plots=plots,
        selected=selected,
        choices=list(groups.values()),
        chosen=set(codes),
        choice_count=len(choices),
        has_results=any(s.has_results for s in stations),
    )


def grid_csv(items: list[workspace_files.Entry], codes: list[str]) -> str:
    """The grid's indices of every station as the workspace's Trends file has them
    (``workspace_files.trends_csv``: per decade, the interval, significant, the years used,
    the units and whether they are out of date), in the grid's order: a column of the grid
    is a block of rows."""
    text = workspace_files.trends_csv(items)
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    order = {code: i for i, code in enumerate(codes)}
    # A stable sort: the stations stay in the overview's order within an index.
    rows = sorted((r for r in reader if r[1] in order), key=lambda r: order[r[1]])
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue()
