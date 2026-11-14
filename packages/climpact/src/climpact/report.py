"""A PDF report of one station's run: what the run used, what the quality checks found, and
every index with its plot and trends, in one file to read, print or send.

Climpact for R has no report: it gives a zip of the output folder (``services/zipFiles.R``)
and the combined PDF of the plots (``<station>_all_plots.pdf``). This module adds one
(#79), read back from the files a run wrote to ``<out>/<station>/``:

1. a cover: the station, its coordinates, the period of the data, the base period, the
   date, the software versions, the index parameters and the quality-control thresholds;
2. the contents, each entry a link to its page;
3. the quality-control summary: the rows each ``qc/`` file lists, with what the check
   looks for, and the missing days per year (``qc/nastatistics``);
4. a page per index (``txx``, ``TX90-HWN``, ``3month_spi``, the custom index ...), in R's
   order: the index's first plotted series drawn as in :mod:`climpact.plots` and a table
   of its trends: Sen's slope, its 95% interval and the Mann-Kendall p-value of each
   plotted series, and the seasonal rows of the trend file;
5. the plots not drawn because every value is missing.

The report is written to ``<out>/<station>_report.pdf``, beside the station folder rather
than in it, so the station's zip (:func:`climpact.plots.zip_station`) keeps R's file list.

The PDF has a title, author, subject and language, bookmarks for every section and index,
and links from the contents; its text is real text in the standard Helvetica font, so it
can be searched, copied and read aloud. matplotlib cannot write a tagged PDF (a structure
tree), so the report is not PDF/UA. The text is English, as the plots and output files
are. Needs matplotlib (``pip install climpactpy[plots]``).
"""

from __future__ import annotations

import datetime as dt
import logging
import math
import re
import textwrap
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from climpact import __version__
from climpact.config import IndexParams, QCParams, StationMetadata
from climpact.io.climpact_csv import format_r_number, read_climpact_csv
from climpact.io.output_files import CLIMPACT_VERSION
from climpact.plots import (
    _INK,
    _INK_2,
    _INK_3,
    _RC_PDF,
    _UNIT_LABELS,
    IndexPlot,
    _Canvas,
    _number,
    _quiet_font_manager,
    index_plots,
    require_matplotlib,
    station_title,
)

log = logging.getLogger(__name__)

REPORT_SUFFIX = "_report.pdf"

# A4 landscape, in inches, the same shape as the plots.
_W, _H = 11.69, 8.27
_LEFT, _RIGHT = 0.6, _W - 0.6
_RULE = "#d9d8d2"
_LINK = "#1f5fae"

_SEASONS = {
    "DJF": "December to February",
    "MAM": "March to May",
    "JJA": "June to August",
    "SON": "September to November",
}


def report_file(out_dir: str | Path, station: str) -> Path:
    """Path of the report of ``station``: ``<out_dir>/<station>_report.pdf``."""
    return Path(out_dir) / f"{station}{REPORT_SUFFIX}"


# ---------------------------------------------------------------------------- reading


class _FolderTables(Mapping):
    """A station's index tables, ``indices/<name>`` keys as in the core, read from
    ``<out>/<station>/indices/`` when asked for."""

    def __init__(self, station_dir: Path, station: str):
        self.folder = station_dir / "indices"
        self.prefix = f"{station}_"
        self.names = sorted(
            p.stem[len(self.prefix) :] for p in self.folder.glob(f"{self.prefix}*.csv")
        )
        self.cache: dict[str, object] = {}

    def __getitem__(self, key: str):
        name = key.removeprefix("indices/")
        if not key.startswith("indices/") or name not in self.names:
            raise KeyError(key)
        if name not in self.cache:
            path = self.folder / f"{self.prefix}{name}.csv"
            self.cache[name] = read_climpact_csv(path).data
        return self.cache[name]

    def __iter__(self) -> Iterator[str]:
        return (f"indices/{n}" for n in self.names)

    def __len__(self) -> int:
        return len(self.names)


_SUFFIX = re.compile(r"_(ANN|MON|DAY)$")
_SCALE = re.compile(r"^(\d+)month_(spi|spei)$")


def index_key(series: str) -> str:
    """The index a plotted series belongs to: ``day_of_txx_MON`` -> ``txx``,
    ``3month_spi_MON`` -> ``3month_spi``, ``TX90-HWN_ANN`` -> ``TX90-HWN``."""
    return _SUFFIX.sub("", series.removeprefix("day_of_"))


@dataclass
class _Index:
    key: str
    plots: list[IndexPlot] = field(default_factory=list)

    @property
    def main(self) -> IndexPlot:
        return self.plots[0]

    @property
    def definition(self) -> str:
        description = self.main.description
        head, sep, rest = description.partition(": ")
        return rest if sep and len(head) < 40 else description


def _indices(tables: Mapping, params: IndexParams) -> tuple[list[_Index], list[str]]:
    """The indices with a plot, in R's order, and the plot stages with no values."""
    indices: dict[str, _Index] = {}
    empty = []
    for stage, plots in index_plots(tables, params):
        if not plots:
            empty.append(stage.removeprefix("plots:"))
        for plot in plots:
            indices.setdefault(index_key(plot.name), _Index(index_key(plot.name))).plots.append(
                plot
            )
    return list(indices.values()), empty


@dataclass(frozen=True)
class TrendRow:
    label: str
    years: str
    slope: float
    lower: float
    upper: float
    unit: str  # "°C per year"
    p_value: float | None = None  # None: not computed (the trend file's seasons)

    @property
    def valid(self) -> bool:
        return not any(math.isnan(v) for v in (self.slope, self.lower, self.upper))

    @property
    def significant(self) -> bool:
        return self.valid and (self.lower > 0 or self.upper < 0)


def _per(units: str, step: str) -> str:
    unit = _UNIT_LABELS.get(units, units)
    return f"{unit} per {step}" if unit else f"per {step}"


def _years(plot: IndexPlot) -> str:
    present = plot.x[~np.isnan(plot.values)]
    return f"{int(present[0])}-{int(present[-1])}" if len(present) else ""


def _trend_rows(index: _Index, trend_table) -> list[TrendRow]:
    """Each plotted series' trend, then the trend file's seasonal rows of the index."""
    rows = []
    for plot in index.plots:
        trend = plot.trend
        if trend is None:
            continue
        label = {"year": "Yearly", "month": "Monthly"}.get(plot.step, plot.step)
        rows.append(
            TrendRow(
                f"{label} ({plot.name})",
                _years(plot),
                trend.slope if trend.valid else math.nan,
                trend.lower if trend.valid else math.nan,
                trend.upper if trend.valid else math.nan,
                _per(plot.units, plot.step),
                trend.p_value if trend.valid else None,
            )
        )
    if trend_table is None or not rows:
        return rows
    m = _SCALE.match(index.key)
    wanted = f"{m.group(2)}{m.group(1)}" if m else index.key
    unit = _per(index.main.units, "year")
    for row in trend_table[trend_table["Index"] == wanted].itertuples(index=False):
        season = str(row[1])
        if season not in _SEASONS:
            continue
        start, end = row[2], row[3]
        years = "" if math.isnan(start) else f"{int(start)}-{int(end)}"
        rows.append(TrendRow(f"{season} ({_SEASONS[season]})", years, row[5], row[4], row[6], unit))
    return rows


# The QC files: name -> (check, what it looks for, from the thresholds).
def _qc_checks(qc: QCParams) -> list[tuple[str, str, str]]:
    n = format_r_number
    return [
        ("duplicates", "Repeated dates", "Dates that appear more than once in the file"),
        ("tmaxmin", "TX at or below TN", "Days whose maximum temperature is not above the minimum"),
        (
            "toolarge",
            "Values too large",
            f"Precipitation above {n(qc.prec_max)} mm or below 0, or a temperature beyond "
            f"+/-{n(qc.temp_max)} °C",
        ),
        (
            "outliers",
            "Outliers",
            f"Beyond the month's box-plot whiskers: {n(qc.iqr_temp)} interquartile ranges for "
            f"temperature, {n(qc.iqr_prec)} for precipitation",
        ),
        ("tx_jumps", "TX jumps", f"Day-to-day changes in TX of {n(qc.jump)} °C or more"),
        ("tn_jumps", "TN jumps", f"Day-to-day changes in TN of {n(qc.jump)} °C or more"),
        (
            "tx_flatline",
            "TX flat runs",
            f"TX values repeated more than {qc.flatline_days} times in a row",
        ),
        (
            "tn_flatline",
            "TN flat runs",
            f"TN values repeated more than {qc.flatline_days} times in a row",
        ),
    ]


@dataclass(frozen=True)
class QCSummary:
    checks: list[tuple[str, str, int | None]]  # (check, what it looks for, rows; None: no file)
    missing: list[tuple[int, int, int, int]]  # (year, prec, tx, tn) for years with any missing
    first_year: int | None
    last_year: int | None
    totals: tuple[int, int, int] | None  # missing days of prec, tx, tn


def qc_summary(station_dir: Path, station: str, qc: QCParams) -> QCSummary:
    """What the ``qc/`` files of a run list."""
    folder = station_dir / "qc"
    checks = []
    for name, check, what in _qc_checks(qc):
        path = folder / f"{station}_{name}.csv"
        rows = len(read_climpact_csv(path).data) if path.is_file() else None
        checks.append((check, what, rows))
    missing, first, last, totals = [], None, None, None
    path = folder / f"{station}_nastatistics.csv"
    if path.is_file():
        table = read_climpact_csv(path).data
        if len(table):
            years = table["Year"].to_numpy(dtype=int)
            values = table[["Prec", "TX", "TN"]].fillna(0).to_numpy(dtype=int)
            first, last = int(years.min()), int(years.max())
            totals = tuple(int(v) for v in values.sum(axis=0))
            missing = [
                (int(y), *map(int, v)) for y, v in zip(years, values, strict=True) if v.any()
            ]
    return QCSummary(checks, missing, first, last, totals)


# ---------------------------------------------------------------------------- drawing


class _Page:
    """One report page, a figure in inches from the bottom left."""

    def __init__(self, footer: str, number: int):
        from matplotlib.figure import Figure

        self.figure = Figure(figsize=(_W, _H), facecolor="white")
        self.links: list[tuple[tuple[float, float, float, float], str]] = []
        self.text(_LEFT, 0.38, footer, size=8, color=_INK_3)
        self.text(_RIGHT, 0.38, f"Page {number}", size=8, color=_INK_3, ha="right")

    def text(self, x: float, y: float, s: str, size: float = 10, color: str = _INK, **kw):
        return self.figure.text(x / _W, y / _H, s, fontsize=size, color=color, **kw)

    def rule(self, y: float, x0: float = _LEFT, x1: float = _RIGHT, color: str = _RULE) -> None:
        from matplotlib.lines import Line2D

        self.figure.add_artist(
            Line2D([x0 / _W, x1 / _W], [y / _H, y / _H], color=color, linewidth=0.6)
        )

    def heading(self, title: str, eyebrow: str = "") -> None:
        if eyebrow:
            self.text(_LEFT, _H - 0.62, eyebrow.upper(), size=8.5, color=_INK_2, weight="bold")
        self.text(_LEFT, _H - 0.98, title, size=20, weight="bold")

    def link(self, rect: tuple[float, float, float, float], target: str) -> None:
        """A link over ``rect`` (x0, y0, x1, y1 in inches) to the page of ``target``."""
        self.links.append((rect, target))


def _table(page: _Page, top: float, columns, rows, row_height=0.2, size=9.5) -> float:
    """A plain table: ``columns`` [(header, x, align)], ``rows`` lists of strings (a
    tuple ``(text, weight)`` for bold). Returns the y below it."""
    for header, x, align in columns:
        page.text(x, top, header, size=size - 0.5, color=_INK_2, weight="bold", ha=align)
    y = top - 0.09
    page.rule(y, columns[0][1], _RIGHT, color=_INK_3)
    y -= row_height
    for row in rows:
        for (_, x, align), cell in zip(columns, row, strict=True):
            text, weight = cell if isinstance(cell, tuple) else (cell, "normal")
            page.text(x, y + 0.05, text, size=size, weight=weight, ha=align)
        page.rule(y - 0.02, columns[0][1], _RIGHT)
        y -= row_height
    return y


@dataclass
class _Report:
    station_dir: Path
    metadata: StationMetadata
    params: IndexParams
    qc: QCParams
    title: str | None
    date: dt.date
    pages: list[_Page] = field(default_factory=list)
    targets: dict[str, int] = field(default_factory=dict)  # target -> page index

    @property
    def footer(self) -> str:
        return (
            f"{self.metadata.name}  ·  Climpact report  ·  climpactpy {__version__}, "
            f"Climpact {CLIMPACT_VERSION}  ·  {self.date.isoformat()}"
        )

    def new_page(self, target: str | None = None) -> _Page:
        page = _Page(self.footer, len(self.pages) + 1)
        if target is not None:
            self.targets[target] = len(self.pages)
        self.pages.append(page)
        return page


def _params_rows(params: IndexParams) -> list[tuple[str, str]]:
    n = format_r_number
    custom = params.custom
    return [
        ("Days for WSDId", f"{params.wsdi_days} (wsdi{params.wsdi_days})"),
        ("Days for CSDId", f"{params.csdi_days} (csdi{params.csdi_days})"),
        ("Days for Rxdday", f"{params.rx_days} (rx{params.rx_days}day)"),
        ("Days for TXdTNd and TXbdTNbd", str(params.txtn_days)),
        ("Base temperature for HDDheat", f"{n(params.hdd_base)} °C"),
        ("Base temperature for CDDcold", f"{n(params.cdd_base)} °C"),
        ("Base temperature for GDDgrow", f"{n(params.gdd_base)} °C"),
        ("Precipitation amount for Rnnmm", f"{n(params.rnnmm)} mm"),
        ("Extra SPI and SPEI time scale", f"{params.spei_months} months"),
        (
            "Custom threshold index",
            f"{custom.variable} {custom.operator} {n(custom.threshold)} ({custom.name})"
            if custom
            else "none",
        ),
    ]


def _qc_rows(qc: QCParams) -> list[tuple[str, str]]:
    n = format_r_number
    return [
        ("Outliers, temperature", f"{n(qc.iqr_temp)} interquartile ranges"),
        ("Outliers, precipitation", f"{n(qc.iqr_prec)} interquartile ranges"),
        ("Largest precipitation", f"{n(qc.prec_max)} mm"),
        ("Largest temperature", f"{n(qc.temp_max)} °C"),
        ("Flat run length", f"{qc.flatline_days} days"),
        ("Largest day-to-day change", f"{n(qc.jump)} °C"),
    ]


def _cover(report: _Report, summary: QCSummary, n_indices: int) -> None:
    m = report.metadata
    page = report.new_page("cover")
    page.text(_LEFT, _H - 0.9, "CLIMPACT REPORT", size=10, color=_INK_2, weight="bold")
    page.text(_LEFT, _H - 1.55, m.name, size=26, weight="bold")
    page.text(_LEFT, _H - 1.95, station_title(m).split("  ·  ", 1)[-1], size=13, color=_INK_2)
    if report.title:
        page.text(_LEFT, _H - 2.3, report.title, size=11, color=_INK_2)
    page.rule(_H - 2.55)
    period = (
        f"{summary.first_year} to {summary.last_year}" if summary.first_year is not None else ""
    )
    facts = [
        ("Data", period or "see the quality-control files"),
        ("Base period", f"{m.base_start} to {m.base_end}"),
        ("Indices plotted", str(n_indices)),
        ("Calculated", report.date.strftime("%d %B %Y").lstrip("0")),
        ("Software", f"climpactpy {__version__}, a Python port of Climpact {CLIMPACT_VERSION}"),
    ]
    y = _H - 2.95
    for label, value in facts:
        page.text(_LEFT, y, label, size=10, color=_INK_2)
        page.text(_LEFT + 1.6, y, value, size=10.5)
        y -= 0.28

    col = _W / 2 + 0.2
    page.text(_LEFT, 3.05, "Index parameters", size=12, weight="bold")
    page.text(col, 3.05, "Quality-control thresholds", size=12, weight="bold")
    y = 2.75
    for label, value in _params_rows(report.params):
        page.text(_LEFT, y, label, size=9.5, color=_INK_2)
        page.text(_LEFT + 2.6, y, value, size=9.5)
        y -= 0.22
    y = 2.75
    for label, value in _qc_rows(report.qc):
        page.text(col, y, label, size=9.5, color=_INK_2)
        page.text(col + 2.2, y, value, size=9.5)
        y -= 0.22


_CONTENTS_TOP = _H - 1.45
_CONTENTS_ROW = 0.205
_CONTENTS_ROWS = int((_CONTENTS_TOP - 0.75) // _CONTENTS_ROW)  # per column
_CONTENTS_COLUMNS = 2


def _contents_pages(entries: int) -> int:
    return max(1, math.ceil(entries / (_CONTENTS_ROWS * _CONTENTS_COLUMNS)))


def _contents(report: _Report, entries: list[tuple[str, str, str, int]]) -> None:
    """``entries``: (target, name, definition, page number)."""
    per_page = _CONTENTS_ROWS * _CONTENTS_COLUMNS
    width = (_RIGHT - _LEFT - 0.4) / _CONTENTS_COLUMNS
    for start in range(0, len(entries), per_page):
        page = report.new_page("contents" if start == 0 else None)
        page.heading("Contents")
        for i, (target, name, definition, number) in enumerate(entries[start : start + per_page]):
            column, row = divmod(i, _CONTENTS_ROWS)
            x = _LEFT + column * (width + 0.4)
            y = _CONTENTS_TOP - row * _CONTENTS_ROW
            bold = target in ("qc", "indices", "empty")
            page.text(x, y, name, size=9.5, weight="bold" if bold else "normal", color=_LINK)
            if definition:
                short = textwrap.shorten(definition, 58, placeholder="...")
                page.text(x + 1.15, y, short, size=8.5, color=_INK_2)
            page.text(x + width, y, str(number), size=9.5, ha="right", color=_LINK)
            page.link((x, y - 0.05, x + width, y + 0.15), target)


def _qc_page(report: _Report, summary: QCSummary) -> None:
    station = report.metadata.name
    page = report.new_page("qc")
    page.heading("Quality-control summary", "Quality control")
    page.text(
        _LEFT,
        _H - 1.4,
        "Rows listed in each quality-control file (qc/ in the zip). A listed value is not "
        "necessarily wrong: check it against the station's records.",
        size=9.5,
        color=_INK_2,
    )
    columns = [("Check", _LEFT, "left"), ("What it looks for", _LEFT + 1.7, "left")]
    columns.append(("Rows", _LEFT + 7.9, "right"))
    rows = []
    for check, what, n in summary.checks:
        rows.append([(check, "bold"), what, "no file" if n is None else str(n)])
    y = _table(page, _H - 1.85, columns, rows)

    y -= 0.3
    page.text(_LEFT, y, "Missing days", size=12, weight="bold")
    y -= 0.3
    if summary.totals is None:
        page.text(_LEFT, y, f"No file qc/{station}_nastatistics.csv.", size=9.5)
        return
    prec, tx, tn = summary.totals
    years = len(summary.missing)
    text = (
        f"{summary.first_year} to {summary.last_year}: {prec} days without precipitation, "
        f"{tx} without TX and {tn} without TN; {years} years have missing days. A year with "
        "more than 15 missing days, or a month with more than 3, gets no annual value."
    )
    lines = textwrap.wrap(text, 150)
    page.text(_LEFT, y, "\n".join(lines), size=9.5, color=_INK_2, va="top", linespacing=1.4)
    y -= 0.2 * len(lines) + 0.3
    if not summary.missing:
        return
    blocks = 4
    per_block = max(1, int((y - 0.75) // 0.18))
    shown = summary.missing[: blocks * per_block]
    block_width = (_RIGHT - _LEFT) / blocks
    for b in range(blocks):
        part = shown[b * per_block : (b + 1) * per_block]
        if not part:
            break
        x = _LEFT + b * block_width
        yy = y
        for header, dx in (("Year", 0), ("Prec", 0.9), ("TX", 1.45), ("TN", 2.0)):
            page.text(x + dx, yy, header, size=8.5, color=_INK_2, weight="bold", ha="left")
        yy -= 0.2
        for year, *values in part:
            page.text(x, yy, str(year), size=8.5)
            for dx, v in zip((0.9, 1.45, 2.0), values, strict=True):
                page.text(x + dx, yy, str(v), size=8.5, color=_INK if v else _INK_3)
            yy -= 0.18
    if len(summary.missing) > len(shown):
        rest = len(summary.missing) - len(shown)
        page.text(
            _LEFT,
            0.62,
            f"... and {rest} more years: see qc/{station}_nastatistics.csv.",
            size=8.5,
            color=_INK_2,
        )


def _fmt(value: float) -> str:
    return "" if math.isnan(value) else _number(value)


def _index_page(report: _Report, index: _Index, canvas_factory, trend_table) -> None:
    from matplotlib.gridspec import GridSpec

    page = report.new_page(f"index:{index.key}")
    page.heading(index.key, "Index")
    others = [p.name for p in index.plots[1:]]
    line = f"Plotted: {index.main.name}."
    if others:
        line += f" Also in the zip's plots/ folder: {', '.join(others)}."
    page.text(_LEFT + 0.02, _H - 1.28, line, size=8.5, color=_INK_2)

    # The plot's part of the page. Subfigures ignore a grid's margins, so the part is the
    # middle cell of a 3 x 3 grid.
    top, bottom, left, right = _H - 1.42, 2.15, 0.35, _W - 0.18
    grid = GridSpec(
        3,
        3,
        figure=page.figure,
        width_ratios=[left, right - left, _W - right],
        height_ratios=[_H - top, top - bottom, bottom],
        wspace=0,
        hspace=0,
        left=0,
        right=1,
        top=1,
        bottom=0,
    )
    canvas = canvas_factory(page.figure.add_subfigure(grid[1, 1]))
    canvas.draw(index.main)

    rows = _trend_rows(index, trend_table)
    if not rows:
        page.text(_LEFT, bottom - 0.2, "No trend is calculated for this index.", size=9.5)
        return
    columns = [
        ("Trend", _LEFT, "left"),
        ("Years", _LEFT + 3.3, "left"),
        ("Sen's slope", _LEFT + 5.2, "right"),
        ("95% interval", _LEFT + 5.5, "left"),
        ("Mann-Kendall p", _LEFT + 8.0, "right"),
        ("Significant", _LEFT + 8.4, "left"),
    ]
    cells = []
    for row in rows:
        if row.valid:
            p = (
                ""
                if row.p_value is None
                else ("< 0.001" if row.p_value < 0.0005 else f"{row.p_value:.3f}")
            )
            cells.append(
                [
                    row.label,
                    row.years,
                    f"{_fmt(row.slope)}",
                    f"{_fmt(row.lower)} to {_fmt(row.upper)} {row.unit}",
                    p,
                    ("Yes", "bold") if row.significant else "No",
                ]
            )
        else:
            cells.append([row.label, row.years, "", "too few values for a trend", "", ""])
    y = _table(page, bottom - 0.12, columns, cells, row_height=0.19, size=9)
    page.text(
        _LEFT,
        y + 0.02,
        "Slopes are Sen's slopes, as in the trend file; significant: the 95% interval excludes "
        "zero. The seasonal rows come from the trend file, which has no p-value.",
        size=7.5,
        color=_INK_2,
    )


def _empty_page(report: _Report, empty: list[str]) -> None:
    page = report.new_page("empty")
    page.heading("Plots not drawn", "Indices")
    page.text(
        _LEFT,
        _H - 1.4,
        "Every value of these is missing, so Climpact draws no plot (and writes no table for "
        "most of them): a variable the file does not have, too little data in the base "
        "period for the percentiles, or the missing-data rules.",
        size=9.5,
        color=_INK_2,
        wrap=True,
    )
    for i, name in enumerate(empty):
        column, row = divmod(i, 28)
        page.text(_LEFT + column * 2.6, _H - 1.9 - row * 0.2, name, size=9.5)


# ---------------------------------------------------------------------------- PDF


def _add_navigation(pdf, pages: list[_Page], targets: dict[str, int], outline, lang: str):
    """Bookmarks, links and the document language, which matplotlib does not write.

    This uses ``PdfPages``' private ``PdfFile`` (checked on matplotlib 3.11): the link
    annotations are added to the pages' annotation lists, which are written when the file
    is closed, and the catalogue is written again, later in the file, with the outline,
    the language and the viewer preferences (the cross-reference table points to the last
    copy). If matplotlib changes these, the report is written without them."""
    from matplotlib.backends.backend_pdf import Name

    try:
        f = pdf._file
        page_refs = f.pageList
        annotations = f._annotations
        f.endStream()
        if len(page_refs) != len(pages) or len(annotations) != len(pages):
            raise AttributeError("unexpected page count")
    except AttributeError as exc:  # pragma: no cover - a matplotlib that changed
        log.warning("report written without bookmarks and links: %s", exc)
        return

    def dest(target: str):
        return [page_refs[targets[target]], Name("Fit")]

    points = 72.0
    for i, page in enumerate(pages):
        for (x0, y0, x1, y1), target in page.links:
            annotations[i][1].append(
                {
                    "Type": Name("Annot"),
                    "Subtype": Name("Link"),
                    "Rect": [x0 * points, y0 * points, x1 * points, y1 * points],
                    "Border": [0, 0, 0],
                    "Dest": dest(target),
                }
            )

    root = f.reserveObject("outlines")

    def write_items(items, parent) -> tuple:
        refs = [f.reserveObject("outline item") for _ in items]
        for k, ((title, target, children), ref) in enumerate(zip(items, refs, strict=True)):
            entry = {"Title": title, "Parent": parent, "Dest": dest(target)}
            if k:
                entry["Prev"] = refs[k - 1]
            if k + 1 < len(refs):
                entry["Next"] = refs[k + 1]
            if children:
                first, last, count = write_items(children, ref)
                entry.update({"First": first, "Last": last, "Count": -count})
            f.writeObject(ref, entry)
        return refs[0], refs[-1], len(refs)

    first, last, count = write_items(outline, root)
    f.writeObject(root, {"Type": Name("Outlines"), "First": first, "Last": last, "Count": count})
    f.writeObject(
        f.rootObject,
        {
            "Type": Name("Catalog"),
            "Pages": f.pagesObject,
            "Outlines": root,
            "PageMode": Name("UseOutlines"),
            "Lang": lang,
            "ViewerPreferences": {"DisplayDocTitle": True},
        },
    )


def write_report(
    out_dir: str | Path,
    metadata: StationMetadata,
    params: IndexParams,
    path: str | Path | None = None,
    qc: QCParams | None = None,
    title: str | None = None,
    date: dt.date | None = None,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Write the PDF report of the run in ``<out_dir>/<metadata.name>/``.

    Reads the run's files (``indices/``, ``qc/``, ``trend/``); ``params`` are the index
    parameters the run used (the parameterised indices' file names depend on them) and
    ``qc`` its quality-control thresholds (default: R's), which the report states.
    ``title`` is R's "Plot title", printed on the plots and the cover. Writes to ``path``,
    by default :func:`report_file` (``<out_dir>/<station>_report.pdf``), and returns it.
    ``progress(stage)`` is called once, with ``"report"``, when it is written. Needs
    matplotlib.
    """
    matplotlib = require_matplotlib()
    from matplotlib.backends.backend_pdf import PdfPages

    out_dir = Path(out_dir)
    station = metadata.name
    station_dir = out_dir / station
    if not station_dir.is_dir():
        raise FileNotFoundError(f"no outputs of station {station!r} in {out_dir}")
    path = Path(path) if path is not None else report_file(out_dir, station)
    qc = qc or QCParams()
    report = _Report(station_dir, metadata, params, qc, title, date or dt.date.today())

    tables = _FolderTables(station_dir, station)
    indices, empty = _indices(tables, params)
    summary = qc_summary(station_dir, station, qc)
    trend_path = station_dir / "trend" / f"{station}_trend.csv"
    trend_table = read_climpact_csv(trend_path).data if trend_path.is_file() else None

    # Page numbers: cover, contents, quality control, the indices, the plots not drawn.
    entries_count = 1 + (1 + len(indices) if indices else 0) + (1 if empty else 0)
    contents_pages = _contents_pages(entries_count)
    first_index = 2 + contents_pages + 1
    entries = [("qc", "Quality control", "What the quality checks found", 2 + contents_pages)]
    if indices:
        entries.append(("indices", "Indices", "", first_index))
        entries += [
            (f"index:{ix.key}", ix.key, ix.definition, first_index + i)
            for i, ix in enumerate(indices)
        ]
    if empty:
        entries.append(("empty", "Plots not drawn", "No values", first_index + len(indices)))

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    info = {
        "Title": f"{station}: Climpact report",
        "Author": "climpactpy",
        "Subject": f"Climate extremes indices of {station}, base period "
        f"{metadata.base_start}-{metadata.base_end}",
        "Keywords": "Climpact, climate extremes, indices, ETCCDI, ET-SCI",
        "Creator": f"climpactpy {__version__}",
    }
    with matplotlib.rc_context(_RC_PDF), _quiet_font_manager():
        _cover(report, summary, len(indices))
        _contents(report, entries)
        _qc_page(report, summary)

        def canvas(figure):
            c = _Canvas(metadata, title, figure=figure)
            c.footer.set_visible(False)
            return c

        for index in indices:
            _index_page(report, index, canvas, trend_table)
        if empty:
            _empty_page(report, empty)

        outline = [("Cover", "cover", []), ("Contents", "contents", [])]
        outline.append(("Quality control", "qc", []))
        if indices:
            children = [(ix.key, f"index:{ix.key}", []) for ix in indices]
            outline.append(("Indices", f"index:{indices[0].key}", children))
        if empty:
            outline.append(("Plots not drawn", "empty", []))
        if indices:
            report.targets["indices"] = report.targets[f"index:{indices[0].key}"]

        with PdfPages(tmp, metadata=info) as pdf:
            for page in report.pages:
                pdf.savefig(page.figure)
            _add_navigation(pdf, report.pages, report.targets, outline, "en")
    tmp.replace(path)
    if progress is not None:
        progress("report")
    return path


__all__ = ["REPORT_SUFFIX", "index_key", "qc_summary", "report_file", "write_report"]
