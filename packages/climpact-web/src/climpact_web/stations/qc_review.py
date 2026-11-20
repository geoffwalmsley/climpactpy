"""The quality-control review (step 2, #77): what the ``qc/`` files of a finished ``qc``
job say, arranged for the screen.

The tables are read back from the files the job wrote (the files the user downloads), so
every row of every file is on the screen. Each row is given context from the station's
daily rows (:func:`climpact.io.station.merged_rows`): the values either side of a jump,
the dates a run of repeated values covers, the usual range of the month an outlier lies
outside, the rows of a repeated date. R's column slips are not shown as such: the file
of TX jumps holds the change and that of TN jumps the value of the day; the screen shows
both values, the change and the date for each.

:func:`review` returns a :class:`Review`: the checks in R's order with their rows, the
missing data per year (``qc/nastatistics`` with the climdex rules applied), and the
screen's worklist (#174): a verdict in proportion to the values checked (decision B,
:data:`VERDICT_LIMITS`), and the checks as a rail (#264): the "look wrong" checks and
the "worth a look" rows in groups by variable and direction, each with its values by
calendar month, its values table (only the columns that check needs, largest first),
its When chart and its selected value with the days around it. The user decides
whether the data is fit to continue. Nothing here changes the data.
"""

from __future__ import annotations

import csv
import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext

from climpact_web.charts import data as chart_data
from climpact_web.core import numbers

PAGE_SIZE = 12  # rows of a check's values table a page (#264)
SORTS = ("size", "date")  # largest first (the default), or by date

# Each check: its file (qc/<key>), its title, which variable's chart its rows show, and
# whether what it finds is almost always a mistake ("error") or may be a real value
# ("review"). In R's order (QC_REPORTS).
CHECKS = (
    ("tmaxmin", gettext_lazy("TN ≥ TX"), "error"),
    ("toolarge", gettext_lazy("Out of range"), "error"),
    ("duplicates", gettext_lazy("Repeated date"), "error"),
    ("outliers", gettext_lazy("Outliers"), "review"),
    ("tx_jumps", gettext_lazy("Jumps in maximum temperature"), "review"),
    ("tn_jumps", gettext_lazy("Jumps in minimum temperature"), "review"),
    ("tx_flatline", gettext_lazy("Repeated maximum temperatures"), "review"),
    ("tn_flatline", gettext_lazy("Repeated minimum temperatures"), "review"),
)
CHECK_KEYS = tuple(key for key, _title, _kind in CHECKS)

# The daily charts of the screen, one per variable (charts:station_daily ?variable=).
CHART_VARIABLES = ("tmax", "tmin", "dtr", "prcp")

MONTHLY_RULE_DAYS = 3  # climdex: a month with more than 3 missing days has no value
ANNUAL_RULE_DAYS = 15  # and a year with more than 15


def chart_id(variable: str) -> str:
    return f"qc-chart-{variable}"


def variable_labels() -> dict[str, str]:
    return {
        "prcp": _("Precipitation"),
        "tmax": _("Maximum temperature (TX)"),
        "tmin": _("Minimum temperature (TN)"),
        "dtr": _("Diurnal temperature range (DTR)"),
    }


def short_labels() -> dict[str, str]:
    return {"prcp": _("PR"), "tmax": _("TX"), "tmin": _("TN"), "dtr": _("DTR")}


# ---- Reading the files ------------------------------------------------------------------


@dataclass
class QCFile:
    """A Climpact QC file: its header values, column names and rows (each with the
    section it is listed under, for ``qc/outliers``), or the "NO ... FOUND" line."""

    meta: dict[str, str]
    columns: list[str]
    rows: list[tuple[str, list[str]]]
    empty_message: str = ""


def read_qc_file(path: Path) -> QCFile:
    """Read a file written by :func:`climpact.io.climpact_csv.write_climpact_csv` with a
    QC file format: ``"Key: ","value"`` header lines, the column names, then the rows; a
    line with one value is a section title (``qc/outliers``) or the "NO ... FOUND"
    message."""
    meta: dict[str, str] = {}
    columns: list[str] = []
    rows: list[tuple[str, list[str]]] = []
    empty = ""
    section = ""
    with path.open(newline="", encoding="utf-8") as handle:
        for values in csv.reader(handle):
            values = [v.strip() for v in values]
            if not values or values == [""]:
                continue
            if not columns and len(values) == 2 and values[0].endswith(":"):
                meta[values[0].rstrip(":").strip()] = values[1]
                continue
            if not columns:
                columns = values
                continue
            if len(values) == 1 and values[0].startswith("NO ") and values[0].endswith(" FOUND"):
                empty = values[0]
                continue
            if len(values) == 1 and len(columns) > 1:
                section = values[0]
                continue
            rows.append((section, values))
    return QCFile(meta, columns, rows, empty)


def iso_date(r_date: str) -> str:
    """``1961-1-3`` (R's ``paste``) -> ``1961-01-03``."""
    year, month, day = (int(p) for p in r_date.split("-"))
    return dt.date(year, month, day).isoformat()


def number(text: str) -> float | None:
    """A file's or a cell's number (a cell writes minus as U+2212); None if not one."""
    return numbers.parse(text)


# A value as the files write it (at most 15 significant digits, no trailing zeros), with
# U+2212 for minus (#226). Shown only: the downloads are the files themselves.
fmt = numbers.file_value


def _deg(text: str) -> str:
    """``12.6 °C``, with a no-break space (#226)."""
    return numbers.with_unit(text, "°C")


def _mm(text: str) -> str:
    return numbers.with_unit(text, "mm")


# ---- The station's rows -------------------------------------------------------------------


@dataclass
class StationRows:
    """The station's rows as the QC checks see them: every row in file order (repeated
    dates kept) and, by date, the row the indices use (the last)."""

    dates: list[str]  # ISO date of each merged row
    values: dict[str, list[float | None]]  # prcp, tmax, tmin per merged row
    last: dict[str, int] = field(default_factory=dict)  # date -> index of its last row
    first_date: str = ""
    last_date: str = ""
    lines: dict[str, list[int]] = field(default_factory=dict)  # date -> its lines in the file

    @classmethod
    def read(cls, station_file: Path) -> StationRows:
        from climpact.io.station import merged_rows, read_station_file

        rows = merged_rows(read_station_file(station_file))
        dates = [d.date().isoformat() for d in rows["date"]]
        values = {k: [number(v) for v in rows[k]] for k in ("prcp", "tmax", "tmin")}
        last = {d: i for i, d in enumerate(dates)}
        return cls(
            dates,
            values,
            last,
            dates[0] if dates else "",
            dates[-1] if dates else "",
            file_lines(station_file),
        )

    def day(self, date: str) -> dict[str, float | None]:
        i = self.last.get(date)
        if i is None:
            return {"prcp": None, "tmax": None, "tmin": None, "dtr": None}
        return self.row(i)

    def row(self, i: int) -> dict[str, float | None]:
        p, x, n = (self.values[k][i] for k in ("prcp", "tmax", "tmin"))
        return {"prcp": p, "tmax": x, "tmin": n, "dtr": None if x is None or n is None else x - n}

    def indices_of(self, date: str) -> list[int]:
        return [i for i, d in enumerate(self.dates) if d == date]


def file_lines(station_file: Path) -> dict[str, list[int]]:
    """The lines of the station file (numbered from 1, as an editor numbers them) that
    give each date, so a finding can say where to correct it. Lines whose first three
    fields are not a date are skipped, as the reader skips them."""
    out: dict[str, list[int]] = {}
    try:
        text = station_file.read_text()
    except (OSError, UnicodeDecodeError):
        return out
    for number_, line in enumerate(text.splitlines(), start=1):
        fields = line.replace(",", "\t").split()
        try:
            day = dt.date(int(fields[0]), int(fields[1]), int(fields[2]))
        except (IndexError, ValueError):
            continue
        out.setdefault(day.isoformat(), []).append(number_)
    return out


# ---- Rows of the tables ------------------------------------------------------------------


@dataclass
class Cell:
    text: str
    numeric: bool = True
    strong: bool = False  # the value the check flagged
    missing: bool = False


@dataclass
class Row:
    date: str  # ISO, the date the file reports
    cells: list[Cell]  # after the date column
    chart: str  # the variable whose chart shows it
    section: str = ""  # qc/outliers: the variable and direction, "tmax-high"
    # The check's detail (#264): the cells of its values table (only the columns that
    # check needs, after the date), how far it is from what the check expects (the
    # "largest first" order) and its value on the When chart.
    values: list[Cell] = field(default_factory=list)
    size: float = 0.0
    plot: float | None = None
    limit: float | None = None  # what it is checked against, on its 7-day chart (PR)

    @property
    def chart_id(self) -> str:
        return chart_id(self.chart)


def value_cell(value: float | None, strong: bool = False) -> Cell:
    if value is None:
        return Cell(_("missing"), missing=True)
    return Cell(fmt(value), strong=strong)


def text_cell(text: str) -> Cell:
    return Cell(text, numeric=False)


@dataclass
class Check:
    key: str
    title: str
    kind: str  # "error" or "review"
    description: str  # what the check looks for, with the thresholds used
    columns: list[str]  # after the date column
    numeric: list[bool]
    rows: list[Row]
    file: str | None  # path in the job's output folder
    count: int  # what the verdict counts: rows, or dates for duplicates
    group: str = ""  # a part of the check with a table of its own ("worth a look" groups)
    value_columns: list[tuple[str, bool]] = field(default_factory=list)  # (label, numeric)

    @property
    def help_id(self) -> str:
        return f"qc.{self.key}"

    @property
    def table_id(self) -> str:
        return f"{self.key}-{self.group}" if self.group else self.key

    @property
    def file_name(self) -> str:
        return Path(self.file).name if self.file else ""

    @property
    def anchor(self) -> str:
        return f"check-{self.table_id}"

    def sorted_rows(self, sort: str = "size") -> list[Row]:
        """Its rows largest first (the default, #264; ties by date) or by date."""
        if sort == "date":
            return sorted(self.rows, key=lambda r: r.date)
        return sorted(self.rows, key=lambda r: (-r.size, r.date))

    def page(self, number: int, sort: str = "size") -> Page:
        sort = sort if sort in SORTS else "size"
        rows = self.sorted_rows(sort)
        pages = max(1, -(-len(rows) // PAGE_SIZE))
        number = min(max(1, number), pages)
        start = (number - 1) * PAGE_SIZE
        return Page(self, number, pages, start, rows[start : start + PAGE_SIZE], sort)

    def page_of(self, date: str, sort: str = "size") -> int:
        for i, row in enumerate(self.sorted_rows(sort)):
            if row.date == date:
                return i // PAGE_SIZE + 1
        return 1

    def row_of(self, date: str) -> Row | None:
        return next((r for r in self.rows if r.date == date), None)


@dataclass
class Page:
    check: Check
    number: int
    pages: int
    start: int
    rows: list[Row]
    sort: str = "size"

    @property
    def first(self) -> int:
        return self.start + 1 if self.rows else 0

    @property
    def last(self) -> int:
        return self.start + len(self.rows)

    @property
    def previous(self) -> int | None:
        return self.number - 1 if self.number > 1 else None

    @property
    def next(self) -> int | None:
        return self.number + 1 if self.number < self.pages else None


# ---- Building each check -----------------------------------------------------------------


def _change(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    from climpact.rnumerics import r_round

    return abs(float(r_round(b - a, 1)))


def _monthly_ranges(station: StationRows, params) -> dict[str, dict[int, tuple[float, float]]]:
    """The whiskers of the monthly box plots ``qc/outliers`` uses: (lower, upper) per
    variable and month."""
    import numpy as np

    from climpact import qc

    months = np.array([int(d[5:7]) for d in station.dates])
    arrays = {
        k: np.array([np.nan if v is None else v for v in station.values[k]]) for k in station.values
    }
    arrays["dtr"] = arrays["tmax"] - arrays["tmin"]
    out: dict[str, dict[int, tuple[float, float]]] = {}
    for variable, coef in (
        ("prcp", params.iqr_prec),
        ("tmax", params.iqr_temp),
        ("tmin", params.iqr_temp),
        ("dtr", params.iqr_temp),
    ):
        x = arrays[variable]
        with np.errstate(invalid="ignore"):
            use = x > 0 if variable == "prcp" else ~np.isnan(x)
        out[variable] = {}
        for m in range(1, 13):
            stats = qc.boxplot_stats(x[use & (months == m)], coef)
            if not np.isnan(stats[0]):
                out[variable][m] = (float(stats[0]), float(stats[4]))
    return out


_SECTION_VARIABLES = {"Prec": "prcp", "TX": "tmax", "TN": "tmin", "DTR": "dtr"}


def _outlier_rows(qcfile: QCFile, station: StationRows, params) -> list[Row]:
    ranges = _monthly_ranges(station, params)
    shorts = short_labels()
    rows = []
    for section, values in qcfile.rows:
        name, _sep, direction = section.partition(" ")
        variable = _SECTION_VARIABLES.get(name, "tmax")
        date = iso_date(values[0])
        nums = [number(v) for v in values[1:5]]
        flagged = dict(zip(("prcp", "tmax", "tmin", "dtr"), nums, strict=False))
        high = direction == "up"
        label = (_("%(variable)s, high") if high else _("%(variable)s, low")) % {
            "variable": shorts[variable]
        }
        month_range = ranges.get(variable, {}).get(int(date[5:7]))
        if month_range is None:
            usual = ""
        elif variable == "prcp":
            usual = _("up to %(high)s") % {"high": fmt(round(month_range[1], 2))}
        else:
            usual = _("%(low)s to %(high)s") % {
                "low": fmt(round(month_range[0], 2)),
                "high": fmt(round(month_range[1], 2)),
            }
        cells = [text_cell(label)]
        cells += [
            value_cell(flagged[k], strong=k == variable) for k in ("prcp", "tmax", "tmin", "dtr")
        ]
        cells.append(Cell(usual))
        # The detail's columns (#264): the value, what it is checked against and how far
        # beyond it, one decimal for what is worked out.
        value = flagged[variable]
        limit = None if month_range is None else month_range[1 if high else 0]
        beyond = None
        if value is not None and limit is not None:
            beyond = value - limit if high else limit - value
        if variable == "prcp":
            middle = Cell(numbers.fixed(limit, 1)) if limit is not None else Cell("")
        elif month_range is not None:
            low, top = (numbers.fixed(v, 1) for v in month_range)
            middle = Cell(_("%(low)s to %(high)s") % {"low": low, "high": top})
        else:
            middle = Cell("")
        if beyond is None:
            by = Cell("")
        elif variable == "prcp" and high:
            by = Cell(numbers.signed(beyond, 1))
        else:
            by = Cell(numbers.fixed(beyond, 1))
        rows.append(
            Row(
                date,
                cells,
                variable,
                f"{variable}-{'high' if high else 'low'}",
                values=[value_cell(value, strong=True), middle, by],
                size=beyond or 0.0,
                plot=value,
                limit=limit,
            )
        )
    return rows


def _rows_table(qcfile: QCFile, strong) -> list[Row]:
    """``tmaxmin`` and ``toolarge``: Date, Prec, TX, TN."""
    rows = []
    for _section, values in qcfile.rows:
        date = iso_date(values[0])
        p, x, n = (number(v) for v in values[1:4])
        marks = strong(p, x, n)
        cells = [value_cell(v, strong=m) for v, m in zip((p, x, n), marks, strict=True)]
        chart = ("prcp", "tmax", "tmin")[marks.index(True)] if True in marks else "tmax"
        rows.append((date, cells, chart, p, x, n))
    return rows


def _tmaxmin_rows(qcfile: QCFile) -> list[Row]:
    out = []
    for date, cells, _chart, _p, x, n in _rows_table(qcfile, lambda p, x, n: (False, True, True)):
        cells.append(value_cell(None if x is None or n is None else round(x - n, 10), strong=True))
        over = None if x is None or n is None else n - x
        values = [
            value_cell(n, strong=True),
            value_cell(x),
            Cell(numbers.signed(over, 1)) if over is not None else Cell(""),
        ]
        out.append(Row(date, cells, "dtr", values=values, size=over or 0.0, plot=over))
    return out


def _toolarge_rows(qcfile: QCFile, params) -> list[Row]:
    t, limit = params.temp_max, params.prec_max

    def strong(p, x, n):
        return (
            p is not None and (p > limit or p < 0),
            x is not None and abs(x) > t,
            n is not None and abs(n) > t,
        )

    def beyond(p, x, n) -> float:
        """How far its values are beyond the limits, the largest (mm or °C)."""
        out = [0.0]
        if p is not None:
            out.append(p - limit if p > limit else -p)
        out += [abs(v) - t for v in (x, n) if v is not None]
        return max(out)

    rows = []
    for date, cells, chart, p, x, n in _rows_table(qcfile, strong):
        size = beyond(p, x, n)
        limit_of = (0.0 if (p or 0) < 0 else limit) if chart == "prcp" else None
        rows.append(
            Row(date, cells, chart, values=list(cells), size=size, plot=size, limit=limit_of)
        )
    return rows


def _duplicate_rows(qcfile: QCFile, station: StationRows) -> list[Row]:
    rows = []
    for date in dict.fromkeys(iso_date(values[0]) for _s, values in qcfile.rows):
        listed = []
        for i in station.indices_of(date):
            row = station.row(i)
            listed.append(
                ", ".join(
                    f"{label} {fmt(row[k]) if row[k] is not None else _('missing')}"
                    for k, label in zip(
                        ("prcp", "tmax", "tmin"), (_("PR"), _("TX"), _("TN")), strict=True
                    )
                )
            )
        times = len(listed)
        cells = [
            Cell(str(times)),
            text_cell("; ".join(listed)),
        ]
        lines = text_cell(", ".join(str(n) for n in station.lines.get(date, [])))
        rows.append(
            Row(date, cells, "tmax", values=[Cell(str(times)), lines], size=times, plot=times)
        )
    return rows


def _jump_rows(qcfile: QCFile, station: StationRows, variable: str, params) -> list[Row]:
    rows = []
    values = station.values[variable]
    for _section, file_values in qcfile.rows:
        date = iso_date(file_values[0])
        # The jump compares the reported row with the next one; for a repeated date, the
        # row whose change reaches the threshold.
        candidates = [i for i in station.indices_of(date) if i + 1 < len(values)]
        pick = next(
            (
                i
                for i in candidates
                if (c := _change(values[i], values[i + 1])) is not None and c >= params.jump
            ),
            candidates[0] if candidates else None,
        )
        this = values[pick] if pick is not None else None
        nxt = values[pick + 1] if pick is not None else None
        next_date = station.dates[pick + 1] if pick is not None else ""
        change = _change(this, nxt)
        cells = [
            value_cell(this),
            value_cell(nxt),
            text_cell(next_date),
            value_cell(change, strong=True),
        ]
        # The detail drops the next day's date, always the day after (#264).
        values = [value_cell(this), value_cell(nxt), value_cell(change, strong=True)]
        rows.append(Row(date, cells, variable, values=values, size=change or 0.0, plot=change))
    return rows


def _flatline_rows(qcfile: QCFile, station: StationRows, variable: str) -> list[Row]:
    rows = []
    values = station.values[variable]
    for _section, file_values in qcfile.rows:
        date = iso_date(file_values[0])
        value = number(file_values[1])
        count = int(number(file_values[2]) or 0)
        # Reported on the second-last day of the run: the run ends on the next row.
        candidates = [i for i in station.indices_of(date) if i + 1 < len(values)]
        pick = next(
            (i for i in candidates if values[i + 1] == value), candidates[0] if candidates else None
        )
        first = ""
        if pick is not None:
            end = pick + 1
            start = max(0, end - count + 1)
            first = station.dates[start]
            span = _("%(first)s to %(last)s") % {
                "first": first,
                "last": station.dates[end],
            }
        else:
            span = ""
        cells = [value_cell(value, strong=True), Cell(str(count)), text_cell(span)]
        # The detail gives the run's first day; its last is the day after the date (#264).
        values = [value_cell(value, strong=True), Cell(str(count)), text_cell(first)]
        rows.append(Row(date, cells, variable, values=values, size=count, plot=count))
    return rows


def _description(key: str, params) -> str:
    n = fmt
    texts = {
        "tmaxmin": _("Days where the minimum temperature is equal to or higher than the maximum."),
        "toolarge": _(
            "Precipitation above %(prec)s or below %(zero)s, and temperatures above %(high)s "
            "or below %(low)s."
        )
        % {
            "prec": _mm(n(params.prec_max)),
            "zero": _mm(n(0)),
            "high": _deg(n(params.temp_max)),
            "low": _deg(n(-params.temp_max)),
        },
        "duplicates": _(
            "Dates given on more than one row of the file. The indices use the last row of "
            "each date."
        ),
        "outliers": _(
            "Values outside the usual range for their calendar month: more than %(temp)s "
            "interquartile ranges beyond the monthly box for temperatures and DTR, and more "
            "than %(prec)s for precipitation (days with rain only)."
        )
        % {"temp": n(params.iqr_temp), "prec": n(params.iqr_prec)},
        "tx_jumps": _(
            "Days where the maximum temperature changes by %(jump)s or more to the next "
            "day. The date is the first of the two days."
        )
        % {"jump": _deg(n(params.jump))},
        "tn_jumps": _(
            "Days where the minimum temperature changes by %(jump)s or more to the next "
            "day. The date is the first of the two days."
        )
        % {"jump": _deg(n(params.jump))},
        "tx_flatline": _(
            "The same maximum temperature on more than %(days)s days in a row. The date is "
            "the second-last day of the run."
        )
        % {"days": params.flatline_days},
        "tn_flatline": _(
            "The same minimum temperature on more than %(days)s days in a row. The date is "
            "the second-last day of the run."
        )
        % {"days": params.flatline_days},
    }
    return texts[key]


def _columns(key: str) -> tuple[list[str], list[bool]]:
    s = short_labels()
    values = [_("PR (mm)"), _("TX (°C)"), _("TN (°C)")]
    columns = {
        "tmaxmin": ([*values, _("TX − TN (°C)")], [True] * 4),
        "toolarge": (values, [True] * 3),
        "duplicates": ([_("Rows"), _("Values on each row, in file order")], [True, False]),
        "outliers": (
            [_("Flagged"), *values, _("DTR (°C)"), _("Usual range for the month")],
            [False, True, True, True, True, True],
        ),
        "tx_jumps": (
            [_("TX that day"), _("TX next day"), _("Next day"), _("Change (°C)")],
            [True, True, False, True],
        ),
        "tn_jumps": (
            [_("TN that day"), _("TN next day"), _("Next day"), _("Change (°C)")],
            [True, True, False, True],
        ),
        "tx_flatline": ([_("TX (°C)"), _("Equal values"), _("Days")], [True, True, False]),
        "tn_flatline": ([_("TN (°C)"), _("Equal values"), _("Days")], [True, True, False]),
    }
    del s
    return columns[key]


def value_columns(key: str, section: str = "") -> list[tuple[str, bool]]:
    """The columns of a check's values table after the date (#264): only those the check
    needs. ``section`` is an outliers group's variable and direction."""

    def deg(text: str) -> str:
        return numbers.with_unit(text, "°C")

    def mm(text: str) -> str:
        return numbers.with_unit(text, "mm")

    s = short_labels()
    if key == "tmaxmin":
        return [(deg(s["tmin"]), True), (deg(s["tmax"]), True), (deg(_("TN − TX")), True)]
    if key == "toolarge":
        return [(mm(s["prcp"]), True), (deg(s["tmax"]), True), (deg(s["tmin"]), True)]
    if key == "duplicates":
        return [(_("Rows"), True), (_("Lines in the file"), False)]
    if key.endswith("_jumps"):
        v = s["tmax" if key.startswith("tx") else "tmin"]
        return [(deg(v), True), (deg(_("Next day")), True), (deg(_("Change")), True)]
    if key.endswith("_flatline"):
        v = s["tmax" if key.startswith("tx") else "tmin"]
        return [(deg(v), True), (_("Days in a row"), True), (_("From"), False)]
    variable, _sep, direction = section.partition("-")
    if variable == "prcp":
        by = _("Over by") if direction == "high" else _("Under by")
        return [(mm(s["prcp"]), True), (mm(_("Month's limit")), True), (mm(by), True)]
    return [
        (deg(s.get(variable, variable)), True),
        (deg(_("Usual range")), True),
        (deg(_("Beyond by")), True),
    ]


def build_check(
    key: str, qcfile: QCFile | None, station: StationRows, params, file: str | None
) -> Check:
    title, kind = next((t, k) for c, t, k in CHECKS if c == key)
    if qcfile is None:
        rows: list[Row] = []
    elif key == "outliers":
        rows = _outlier_rows(qcfile, station, params)
    elif key == "tmaxmin":
        rows = _tmaxmin_rows(qcfile)
    elif key == "toolarge":
        rows = _toolarge_rows(qcfile, params)
    elif key == "duplicates":
        rows = _duplicate_rows(qcfile, station)
    elif key.endswith("_jumps"):
        rows = _jump_rows(qcfile, station, "tmax" if key.startswith("tx") else "tmin", params)
    else:
        rows = _flatline_rows(qcfile, station, "tmax" if key.startswith("tx") else "tmin")
    columns, numeric = _columns(key)
    return Check(
        key=key,
        title=str(title),
        kind=kind,
        description=_description(key, params),
        columns=columns,
        numeric=numeric,
        rows=rows,
        file=file,
        count=len(rows),
        value_columns=value_columns(key),
    )


# ---- Missing data ------------------------------------------------------------------------


@dataclass
class YearMissing:
    year: int
    days: dict[str, int]  # prcp, tmax, tmin: days missing (qc/nastatistics)
    months: dict[str, int]  # months with more than 3 days missing
    no_annual: dict[str, bool]  # the year gets no annual index value from that variable

    @property
    def cells(self) -> list[dict]:
        return [
            {
                "key": k,
                "days": self.days.get(k, 0),
                "months": self.months.get(k, 0),
                "no_annual": self.no_annual.get(k, False),
            }
            for k in ("prcp", "tmax", "tmin")
        ]

    @property
    def any_missing(self) -> bool:
        return any(self.days.values())

    @property
    def any_no_annual(self) -> bool:
        return any(self.no_annual.values())


def missing_by_year(nastatistics: QCFile | None, station: StationRows) -> list[YearMissing]:
    """Each year of ``qc/nastatistics`` (missing days per variable), with the months that
    have more than 3 missing days and whether the climdex rules leave the year without an
    annual value (more than 15 missing days, or such a month)."""
    if nastatistics is None:
        return []
    import calendar

    present: dict[str, dict[tuple[int, int], int]] = {k: {} for k in ("prcp", "tmax", "tmin")}
    for date, i in station.last.items():
        ym = (int(date[:4]), int(date[5:7]))
        for k in present:
            if station.values[k][i] is not None:
                present[k][ym] = present[k].get(ym, 0) + 1
    out = []
    keys = {"Prec": "prcp", "TX": "tmax", "TN": "tmin"}
    for _section, values in nastatistics.rows:
        row = dict(zip(nastatistics.columns, values, strict=False))
        year = int(float(row["Year"]))
        days = {keys[c]: int(float(row[c])) for c in keys if c in row}
        months = {}
        for k in days:
            months[k] = sum(
                1
                for m in range(1, 13)
                if calendar.monthrange(year, m)[1] - present[k].get((year, m), 0)
                > MONTHLY_RULE_DAYS
            )
        no_annual = {k: days[k] > ANNUAL_RULE_DAYS or months[k] > 0 for k in days}
        out.append(YearMissing(year, days, months, no_annual))
    return out


# ---- The verdict (#174) -------------------------------------------------------------------


@dataclass(frozen=True)
class VerdictLimits:
    """Where the verdict turns red (decision B, #174). Only the checks whose findings are
    almost always mistakes (``kind == "error"``: minimum at or above maximum, values too
    large, repeated dates) count against ``wrong_share``. Outliers, jumps and flat runs
    are counted in the text and never change the level."""

    wrong_share: float = 0.001  # red above 0.1% of the values checked looking wrong
    short_years_share: float = 0.10  # red above 10% of years without annual values


VERDICT_LIMITS = VerdictLimits()


def percent(n: int, total: int) -> str:
    """``n`` as a share of ``total`` for the screen: "under 0.01%", "0.46%", "1.2%"."""
    from django.utils.formats import number_format

    if not n or not total:
        return _("%(percent)s%%") % {"percent": 0}
    share = 100 * n / total
    if share < 0.01:
        return _("under 0.01%")
    digits = 2 if share < 1 else 1
    return _("%(percent)s%%") % {"percent": number_format(round(share, digits))}


grouped = numbers.grouped


@dataclass
class Verdict:
    level: str  # "ready" (green), "usable" (amber) or "fix" (red)
    title: str  # the level in words, in bold before the sentence: "Usable."
    sentences: list[str]  # what it means, after the title
    facts: list[str]  # the counts against what was checked, one mono line
    values: int  # values checked: PR, TX and TN present on each date
    wrong: int  # rows of the "look wrong" checks (dates, for repeated dates)
    worth: int  # rows of the "worth a look" checks
    years: int
    short_years: int  # years too incomplete for annual values
    too_many_wrong: bool
    too_many_short: bool
    missing: int = 0  # values missing: PR, TX and TN absent on each date

    @property
    def alert_kind(self) -> str:
        return {"ready": "success", "usable": "warning", "fix": "error"}[self.level]

    @property
    def message(self) -> str:
        return " ".join(self.sentences)


def values_checked(station: StationRows) -> int:
    """The values the checks looked at: PR, TX and TN present on each date (the row the
    indices use, for a repeated date)."""
    return sum(
        1
        for i in station.last.values()
        for k in ("prcp", "tmax", "tmin")
        if station.values[k][i] is not None
    )


def values_missing(station: StationRows) -> int:
    """PR, TX and TN missing on each date from the first to the last (#235)."""
    return sum(
        1
        for i in station.last.values()
        for k in ("prcp", "tmax", "tmin")
        if station.values[k][i] is None
    )


def verdict(
    checks: list[Check],
    years: list[YearMissing],
    values: int,
    limits: VerdictLimits = VERDICT_LIMITS,
    missing: int = 0,
) -> Verdict:
    """Decision B (#174): green when nothing looks wrong, amber when up to
    ``limits.wrong_share`` of the values checked look wrong, red above it or when more than
    ``limits.short_years_share`` of the years are too incomplete for annual values. The
    user can go on whatever the level. Its words are the verdict strip's (#235): the level
    in bold, one sentence, then the counts on one line."""
    wrong = sum(c.count for c in checks if c.kind == "error")
    worth = sum(c.count for c in checks if c.kind == "review")
    short = sum(1 for y in years if y.any_no_annual)
    too_many_wrong = wrong > limits.wrong_share * values
    too_many_short = short > limits.short_years_share * len(years)

    facts = [
        ngettext("%(n)s value checked", "%(n)s values checked", values)
        % {"n": numbers.grouped(values)},
        ngettext("%(n)s looks wrong (%(percent)s)", "%(n)s look wrong (%(percent)s)", wrong)
        % {"n": numbers.grouped(wrong), "percent": percent(wrong, values)},
        _("%(n)s worth a look") % {"n": numbers.grouped(worth)},
        _("%(n)s missing (%(percent)s)")
        % {"n": numbers.grouped(missing), "percent": percent(missing, values + missing)},
    ]
    if short:
        facts.append(
            ngettext(
                "%(n)s of %(total)s years too incomplete for annual values",
                "%(n)s of %(total)s years too incomplete for annual values",
                short,
            )
            % {"n": numbers.grouped(short), "total": numbers.grouped(len(years))}
        )

    if too_many_wrong or too_many_short:
        level, title = "fix", _("Fix the file first.")
        sentences = []
        if too_many_wrong:
            sentences.append(
                ngettext(
                    "%(n)s value looks wrong, %(percent)s of the values checked.",
                    "%(n)s values look wrong, %(percent)s of the values checked.",
                    wrong,
                )
                % {"n": numbers.grouped(wrong), "percent": percent(wrong, values)}
            )
        if too_many_short:
            sentences.append(
                ngettext(
                    "%(n)s of %(total)s years has too much missing data for annual values.",
                    "%(n)s of %(total)s years have too much missing data for annual values.",
                    short,
                )
                % {"n": numbers.grouped(short), "total": numbers.grouped(len(years))}
            )
    elif wrong:
        level, title = "usable", _("Usable.")
        sentences = [
            ngettext(
                "%(n)s value looks wrong; the indices can run with it as it is.",
                "%(n)s values look wrong; the indices can run with them as they are.",
                wrong,
            )
            % {"n": numbers.grouped(wrong)}
        ]
    else:
        level, title = "ready", _("Ready to use.")
        sentences = [_("Nothing looks wrong.")]
    return Verdict(
        level=level,
        title=title,
        sentences=sentences,
        facts=facts,
        values=values,
        wrong=wrong,
        worth=worth,
        years=len(years),
        short_years=short,
        too_many_wrong=too_many_wrong,
        too_many_short=too_many_short,
        missing=missing,
    )


# ---- A check's selected value, with the days around it (#235, #264) ------------------------

WINDOW_DAYS = 3  # days either side of the selected value: its 7-day chart and table (#264)
# The selected value's chart: its box, and the plot inside it, left of which are the
# values' ticks and under which the dates'.
CHART_W, CHART_H = 420, 150
PLOT_LEFT, PLOT_RIGHT, PLOT_TOP, PLOT_BOTTOM = 36, 412, 10, 128
UNITS = {"prcp": "mm", "tmax": "°C", "tmin": "°C", "dtr": "°C"}


@dataclass
class Finding:
    """A check's selected value (#264; a "look wrong" finding before it, #235): what it
    is in a sentence, the days around it as a chart and a table, its lines in the file,
    and for a repeated date the values on each of its rows."""

    row: Row
    text: str  # the selected value's title
    days: list[dict]  # the days around it: date, cells (PR, TX, TN texts), this, flagged
    chart: dict = field(default_factory=dict)  # :func:`_chart` or :func:`_bar_chart`
    variables: tuple[str, ...] = ()  # the variables its chart draws
    lines: list[int] = field(default_factory=list)  # its lines in the station file
    rows_listed: list[str] = field(default_factory=list)  # a repeated date's rows

    @property
    def date(self) -> str:
        return self.row.date

    @property
    def day(self) -> dt.date:
        return dt.date.fromisoformat(self.row.date)

    @property
    def legend(self) -> list[dict]:
        """The variables of its chart, with their codes and units: "TX °C"."""
        shorts = short_labels()
        return [
            {"variable": v, "label": numbers.with_unit(shorts[v], UNITS[v])} for v in self.variables
        ]

    @property
    def chart_label(self) -> str:
        """The chart's text alternative: "TX and TN, daily, 1962-04-07 to 1962-04-13"."""
        shorts = short_labels()
        days = self.days
        text = _("%(variables)s, daily, %(first)s to %(last)s") % {
            "variables": _join([shorts[v] for v in self.variables]),
            "first": days[0]["date"] if days else "",
            "last": days[-1]["date"] if days else "",
        }
        if self.chart.get("limit_text"):
            text += _(", with the limit of %(limit)s") % {"limit": self.chart["limit_text"]}
        return text

    @property
    def month(self) -> str:
        """The chart's caption: "April 1962, daily"."""
        from django.utils.formats import date_format

        return _("%(month)s, daily") % {"month": date_format(self.day, "F Y")}

    @property
    def lines_text(self) -> str:
        """Where to find it in the file: "Line 459 in the file"."""
        if not self.lines:
            return ""
        return ngettext(
            "Line %(lines)s in the file", "Lines %(lines)s in the file", len(self.lines)
        ) % {"lines": _join([str(n) for n in self.lines])}


def _window(
    station: StationRows, date: str, days: int = WINDOW_DAYS
) -> list[tuple[str, dict[str, float | None]]]:
    day = dt.date.fromisoformat(date)
    out = []
    for offset in range(-days, days + 1):
        iso = (day + dt.timedelta(days=offset)).isoformat()
        out.append((iso, station.day(iso)))
    return out


def _nice(low: float, high: float, zero: bool = False) -> tuple[float, float, float]:
    """An axis of three ticks around ``low`` to ``high``: (bottom, top, middle), its step
    1, 2, 2.5 or 5 times a power of ten; from zero when ``zero``."""
    import math

    if zero:
        low, high = min(0.0, low), max(0.0, high)
    if high - low <= 0:
        high = low + 1
    magnitude = 10 ** math.floor(math.log10((high - low) / 2))
    for step in (m * magnitude * k for k in (1, 10, 100) for m in (1, 2, 2.5, 5)):
        bottom = math.floor(low / step + 1e-9) * step
        if bottom + 2 * step >= high - 1e-9:
            return bottom, bottom + 2 * step, bottom + step
    return low, high, (low + high) / 2


def _chart(window, variables: tuple[str, ...], ring: str | None, date: str) -> dict:
    """The selected value's chart of temperatures (#235): a line per variable over the
    window (gaps where values are missing), the day itself as a band with the flagged
    value ringed, and axes: three values and three dates (the first, the day, the last).
    Coordinates in the box ``CHART_W`` x ``CHART_H``."""
    present = [v[k] for _d, v in window for k in variables if v[k] is not None]
    if not present:
        return {}
    low, high, middle = _nice(min(present), max(present))
    n = len(window)
    step = (PLOT_RIGHT - PLOT_LEFT) / (n - 1)

    def x(i: int) -> float:
        return round(PLOT_LEFT + i * step, 1)

    def y(v: float) -> float:
        return round(PLOT_BOTTOM - (v - low) / (high - low) * (PLOT_BOTTOM - PLOT_TOP), 1)

    lines = []
    for k in variables:
        parts, pen = [], False
        for i, (_d, v) in enumerate(window):
            if v[k] is None:
                pen = False
                continue
            parts.append(f"{'L' if pen else 'M'}{x(i)} {y(v[k])}")
            pen = True
        lines.append({"variable": k, "d": "".join(parts)})
    centre = next(i for i, (d, _v) in enumerate(window) if d == date)
    value = window[centre][1][ring] if ring else None
    return {
        "xs": [x(i) for i in range(n)],
        "lines": lines,
        "ring": None if value is None else {"x": x(centre), "y": y(value)},
        "band": {"x": round(x(centre) - step / 2, 1), "width": round(step, 1)},
        "y_ticks": [{"y": y(v), "text": numbers.number(v)} for v in (high, middle, low)],
        "grid_y": y(middle),
        "x_ticks": [
            {"x": x(0), "text": window[0][0][5:], "anchor": "start"},
            {"x": x(centre), "text": window[centre][0][5:], "anchor": "middle"},
            {"x": x(n - 1), "text": window[-1][0][5:], "anchor": "end"},
        ],
    }


def _bar_chart(window, date: str, limit: float | None) -> dict:
    """The selected value's chart of rain (#264): a bar a day, the day's in the rain
    colour and the others muted, the limit it is checked against dashed, and axes."""
    present = [v["prcp"] for _d, v in window if v["prcp"] is not None]
    if not present:
        return {}
    marks = present + ([limit] if limit is not None else [])
    low, high, middle = _nice(min(marks), max(marks), zero=True)
    n = len(window)
    step = (PLOT_RIGHT - PLOT_LEFT) / n
    width = round(step * 0.4, 1)

    def x(i: int) -> float:
        return round(PLOT_LEFT + (i + 0.5) * step, 1)

    def y(v: float) -> float:
        return round(PLOT_BOTTOM - (v - low) / (high - low) * (PLOT_BOTTOM - PLOT_TOP), 1)

    bars = []
    for i, (d, v) in enumerate(window):
        if v["prcp"] is None:
            continue
        top, base = y(v["prcp"]), y(0)
        bars.append(
            {
                "x": round(x(i) - width / 2, 1),
                "y": min(top, base),
                "h": max(round(abs(base - top), 1), 0.5),
                "this": d == date,
            }
        )
    centre = next(i for i, (d, _v) in enumerate(window) if d == date)
    return {
        "xs": [x(i) for i in range(n)],
        "bars": bars,
        "bar_width": width,
        "limit_y": None if limit is None else y(limit),
        "limit_text": "" if limit is None else numbers.with_unit(numbers.fixed(limit, 1), "mm"),
        "band": {"x": round(x(centre) - step / 2, 1), "width": round(step, 1)},
        "y_ticks": [{"y": y(v), "text": numbers.number(v)} for v in (high, middle, low)],
        "grid_y": y(middle),
        "x_ticks": [
            {"x": x(0), "text": window[0][0][5:], "anchor": "middle"},
            {"x": x(centre), "text": window[centre][0][5:], "anchor": "middle"},
            {"x": x(n - 1), "text": window[-1][0][5:], "anchor": "middle"},
        ],
    }


def _toolarge_parts(cells: list[Cell], params) -> list[tuple[str, str, str, str]]:
    """Each value of a ``toolarge`` row out of range: (variable, value, its limit, the
    sentence)."""
    shorts = short_labels()
    out = []
    for key, cell in zip(("prcp", "tmax", "tmin"), cells[:3], strict=True):
        if not cell.strong:
            continue
        v = number(cell.text) or 0.0
        if key == "prcp":
            limit = 0 if v < 0 else params.prec_max
            text = (
                _("%(variable)s %(value)s, below %(limit)s")
                if v < 0
                else _("%(variable)s %(value)s, over the %(limit)s limit")
            )
        else:
            limit = params.temp_max if v > 0 else -params.temp_max
            text = (
                _("%(variable)s %(value)s, over the %(limit)s limit")
                if v > 0
                else _("%(variable)s %(value)s, under the %(limit)s limit")
            )
        value = numbers.with_unit(cell.text, UNITS[key])
        limit_text = numbers.with_unit(fmt(limit), UNITS[key])
        out.append(
            (
                shorts[key],
                value,
                limit_text,
                text % {"variable": shorts[key], "value": value, "limit": limit_text},
            )
        )
    return out


def _value_text(check: Check, row: Row, params) -> str:
    """The selected value in a sentence, codes first, a no-break space before each unit:
    "TN 9.5 °C is above TX 8.2 °C", "PR 120.3 mm, 80.2 mm over the limit for July"."""
    from django.utils.dates import MONTHS

    cells, shorts = row.cells, short_labels()
    if check.key == "tmaxmin":
        tx, tn = number(cells[1].text), number(cells[2].text)
        values = {"tn": _deg(cells[2].text), "tx": _deg(cells[1].text)}
        if tx is not None and tn is not None and tn == tx:
            return _("TN %(tn)s equals TX %(tx)s") % values
        return _("TN %(tn)s is above TX %(tx)s") % values
    if check.key == "toolarge":
        return "; ".join(p[3] for p in _toolarge_parts(cells, params))
    if check.key == "duplicates":
        n = int(number(cells[0].text) or 0)
        return ngettext(
            "Given on %(n)s row of the file. The indices use the last.",
            "Given on %(n)s rows of the file. The indices use the last.",
            n,
        ) % {"n": n}
    if check.key == "outliers":
        variable, _sep, direction = row.section.partition("-")
        unit = UNITS[variable]
        values = {
            "variable": shorts[variable],
            "value": numbers.with_unit(row.values[0].text, unit),
            "by": numbers.with_unit(numbers.fixed(row.size, 1), unit),
            "month": str(MONTHS[int(row.date[5:7])]),
        }
        if variable == "prcp":
            if direction == "high":
                return _("%(variable)s %(value)s, %(by)s over the limit for %(month)s") % values
            return _("%(variable)s %(value)s, %(by)s under the limit for %(month)s") % values
        if direction == "high":
            return _("%(variable)s %(value)s, %(by)s above the usual range for %(month)s") % values
        return _("%(variable)s %(value)s, %(by)s below the usual range for %(month)s") % values
    variable = shorts["tmax" if check.key.startswith("tx") else "tmin"]
    if check.key.endswith("_jumps"):
        return _("%(variable)s %(value)s, then %(next)s the next day: a change of %(change)s") % {
            "variable": variable,
            "value": _deg(cells[0].text),
            "next": _deg(cells[1].text),
            "change": _deg(cells[3].text),
        }
    values = {
        "variable": variable,
        "value": _deg(cells[0].text),
        "n": cells[1].text,
        "first": row.values[2].text,
    }
    if not values["first"]:
        return _("%(variable)s %(value)s on %(n)s days in a row") % values
    return _("%(variable)s %(value)s on %(n)s days in a row, from %(first)s") % values


def _day_cell(value: float | None) -> Cell:
    """A value of the days-around table: one decimal (#225), or "missing"."""
    if value is None:
        return Cell(_("missing"), missing=True)
    return Cell(numbers.fixed(value, 1))


def days_readout(days: list[dict], xs: list[float], date: str) -> str:
    """The 7-day chart's read-out (#283): each day's PR, TX and TN, codes first."""
    shorts = short_labels()
    points = []
    for day, x in zip(days, xs, strict=True):
        parts = []
        for key, cell in zip(("prcp", "tmax", "tmin"), day["cells"], strict=True):
            text = cell.text if cell.missing else numbers.with_unit(cell.text, UNITS[key])
            parts.append(f"{shorts[key]} {text}")
        points.append([x, None, day["date"], " · ".join(parts)])
    start = next((i for i, d in enumerate(days) if d["date"] == date), 0)
    return _json({"points": points, "top": PLOT_TOP, "bottom": PLOT_BOTTOM, "start": start})


def build_finding(
    check: Check, row: Row, station: StationRows, params, flagged: set[str] | None = None
) -> Finding:
    """A check's value with its context (#264): the days around it as a chart (PR bars
    with the limit, or TX and TN lines) and a table; ``flagged`` holds the dates the check
    also found, marked in the table."""
    window = _window(station, row.date)
    if row.chart == "prcp":
        variables: tuple[str, ...] = ("prcp",)
        chart = _bar_chart(window, row.date, row.limit)
    else:
        variables = ("tmax", "tmin")
        ring = {"tmaxmin": "tmin", "duplicates": None}.get(check.key, row.chart)
        chart = _chart(window, variables, ring if ring in variables else None, row.date)
    flagged = flagged or set()
    days = [
        {
            "date": d,
            "cells": [_day_cell(v[k]) for k in ("prcp", "tmax", "tmin")],
            "this": d == row.date,
            "flagged": d in flagged,
        }
        for d, v in window
    ]
    if chart:
        chart["readout"] = days_readout(days, chart["xs"], row.date)
    lines = station.lines.get(row.date, [])
    listed = []
    if check.key == "duplicates":
        values = row.cells[1].text.split("; ")
        listed = [
            _("Line %(line)s: %(values)s") % {"line": line, "values": v}
            for line, v in zip(lines, values, strict=False)
        ] or values
    return Finding(
        row,
        _value_text(check, row, params),
        days,
        chart=chart,
        variables=variables,
        lines=lines,
        rows_listed=listed,
    )


# ---- The checks' charts (#264): when each value is, and by calendar month ---------------------

WHEN_W, WHEN_H = 640, 170  # the When chart's box, and its plot
WHEN_LEFT, WHEN_RIGHT, WHEN_TOP, WHEN_BOTTOM = 44, 632, 8, 146
MONTHS_W, MONTHS_H = 360, 170  # the By calendar month chart's box, and its plot
MONTHS_LEFT, MONTHS_RIGHT, MONTHS_TOP, MONTHS_BOTTOM = 30, 354, 16, 146


def when_chart(rows: list[Row], first: str, last: str, zero: bool, selected: Row | None) -> dict:
    """Each value of a check against its date across the record, the selected one
    ringed (#264): a dot each, three value ticks and up to seven years. Coordinates in
    the box ``WHEN_W`` x ``WHEN_H``."""
    values = [r.plot for r in rows if r.plot is not None]
    if not values or not first or not last:
        return {}
    low, high, middle = _nice(min(values), max(values), zero)
    start, end = dt.date.fromisoformat(first), dt.date.fromisoformat(last)
    span = max(1, (end - start).days)

    def x(day: dt.date) -> float:
        return round(WHEN_LEFT + (day - start).days / span * (WHEN_RIGHT - WHEN_LEFT), 1)

    def y(v: float) -> float:
        return round(WHEN_BOTTOM - (v - low) / (high - low) * (WHEN_BOTTOM - WHEN_TOP), 1)

    def point(row: Row) -> dict | None:
        if row.plot is None:
            return None
        return {"x": x(dt.date.fromisoformat(row.date)), "y": y(row.plot)}

    dots = "".join(
        f"M{p['x'] - 3.2:.1f} {p['y']}a3.2 3.2 0 1 0 6.4 0a3.2 3.2 0 1 0 -6.4 0z"
        for p in map(point, rows)
        if p
    )
    years = list(range(start.year, end.year + 1))
    k = min(7, len(years))
    if k > 1:
        ticks = sorted({years[round(i * (len(years) - 1) / (k - 1))] for i in range(k)})
    else:
        ticks = years
    x_ticks = []
    for year in ticks:
        # The first year at the start, the last at the end, the others at 1 January.
        if year == start.year:
            day, anchor = start, "start"
        elif year == end.year:
            day, anchor = end, "end"
        else:
            day, anchor = dt.date(year, 1, 1), "middle"
        x_ticks.append({"x": x(day), "text": year, "anchor": anchor})
    return {
        "dots": dots,
        "ring": point(selected) if selected else None,
        "y_ticks": [{"y": y(v), "text": numbers.number(v)} for v in (high, middle, low)],
        "x_ticks": x_ticks,
        "first": start.year,
        "last": end.year,
        "low": low,
        "high": high,
        "start": first,
        "span": span,
    }


_json = chart_data.attr_json


def when_readout(group: Group, chart: dict, selected: Row | None) -> str:
    """The When chart's read-out (#283, js/chart-readout.js) as JSON: each value by date
    (day offsets from the record's first day) and its value, named by the chart's y
    label; the nearest dot to the pointer, and the selected one first for the keyboard. A
    value picked selects its row in the values table (qc.js)."""
    start = dt.date.fromisoformat(chart["start"])
    rows = sorted((r for r in group.check.rows if r.plot is not None), key=lambda r: r.date)
    selected_date = selected.date if selected else ""
    return _json(
        {
            "x0": WHEN_LEFT,
            "dx": (WHEN_RIGHT - WHEN_LEFT) / chart["span"],
            "low": chart["low"],
            "high": chart["high"],
            "top": WHEN_TOP,
            "bottom": WHEN_BOTTOM,
            "d": [(dt.date.fromisoformat(r.date) - start).days for r in rows],
            "v": [chart_data.shown(r.plot) for r in rows],
            "when": {"step": "date", "first": chart["start"]},
            "label": _("%(label)s:") % {"label": group.y_label},
            "unit": "",
            "near": "xy",
            "pick": True,
            "start": next((i for i, r in enumerate(rows) if r.date == selected_date), None),
        }
    )


def months_readout(group: Group, chart: dict) -> str:
    """The By calendar month chart's read-out (#283): each month's count."""
    points = []
    for bar in chart["bars"]:
        if group.wrong:
            text = ngettext("%(n)s row", "%(n)s rows", bar["n"])
        else:
            text = ngettext("%(n)s value", "%(n)s values", bar["n"])
        points.append([bar["cx"], None, bar["name"], text % {"n": numbers.grouped(bar["n"])}])
    return _json({"points": points, "top": MONTHS_TOP, "bottom": MONTHS_BOTTOM, "start": 0})


def month_names() -> list[str]:
    """The calendar months, short: "Jan" (the By calendar month chart and table)."""
    from django.utils.formats import date_format

    return [date_format(dt.date(2001, m, 1), "M") for m in range(1, 13)]


def months_chart(by_month: list[int]) -> dict:
    """A check's values by calendar month as twelve bars, with axes (#264). Coordinates
    in the box ``MONTHS_W`` x ``MONTHS_H``."""
    names = month_names()
    top = max(2, -(-max(by_month, default=0) // 2) * 2)
    height = MONTHS_BOTTOM - MONTHS_TOP

    def y(n: float) -> float:
        return round(MONTHS_BOTTOM - n / top * height, 1)

    bars = []
    for m, n in enumerate(by_month):
        x = MONTHS_LEFT + 6 + m * 27
        h = round(n / top * height, 1)
        bars.append({"x": x, "cx": x + 9, "y": y(n), "h": h, "n": n, "name": names[m]})
    return {
        "bars": bars,
        "y_ticks": [{"y": y(v), "text": numbers.grouped(v)} for v in (top, top // 2, 0)],
    }


# ---- The checks as a rail: each with its values by calendar month ----------------------------


def outlier_titles() -> dict[str, str]:
    return {
        "prcp-high": _("Heavy rain days"),
        "prcp-low": _("Light rain days"),
        "tmax-high": _("High maximum"),
        "tmax-low": _("Low maximum"),
        "tmin-high": _("High minimum"),
        "tmin-low": _("Low minimum"),
        "dtr-high": _("Wide daily range"),
        "dtr-low": _("Narrow daily range"),
    }


@dataclass
class Group:
    """A check in the rail (#264) and its detail: a "look wrong" check, a variable and
    direction of ``qc/outliers`` (its rows by calendar month), or another "worth a look"
    check (jumps, flat runs)."""

    check: Check  # the group's rows as a check, so it has a table of its own
    title: str
    by_month: list[int] = field(default_factory=list)  # rows in each calendar month
    mostly: str = ""  # "Mostly May and June", "All year": when its rows fall (#235)
    variable: str = ""  # its variables, short: "PR", "TX", "PR TX TN", "all rows"
    rail_title: str = ""  # its name in the rail, when shorter than its title
    y_label: str = ""  # the When chart's values, with their unit
    zero: bool = True  # the When chart's axis starts at zero
    lede: str = ""  # what the check means and what to look at first

    @property
    def id(self) -> str:
        return self.check.table_id

    @property
    def count(self) -> int:
        return self.check.count

    @property
    def wrong(self) -> bool:
        return self.check.kind == "error"

    @property
    def bars(self) -> list[dict]:
        """The rows by calendar month as the rail's small chart (#235, #264): x, y and
        height in a box of ``BARS_W`` x ``BARS_H``; a month without rows keeps a thin
        mark, so the twelve months read as a year."""
        top = max(self.by_month, default=0)
        if not top:
            return []
        out = []
        for m, n in enumerate(self.by_month):
            h = max(2.0, n / top * BARS_H) if n else 0.6
            out.append({"x": m * 5, "y": round(BARS_H - h, 1), "h": round(h, 1)})
        return out


BARS_W, BARS_H = 60, 14  # the box of a check's bars by month (12 bars 3.5 wide, 5 apart)


def _by_month(rows: list[Row]) -> list[int]:
    by_month = [0] * 12
    for row in rows:
        by_month[int(row.date[5:7]) - 1] += 1
    return by_month


def _join(items: list[str]) -> str:
    if len(items) < 2:
        return "".join(items)
    return _("%(first)s and %(last)s") % {"first": ", ".join(items[:-1]), "last": items[-1]}


def _mostly(by_month: list[int]) -> str:
    """When a group's rows fall, for its sentence (#235): the calendar months that hold
    at least half the rows when there are at most three of them ("Mostly May and June",
    "All in December"); "All year" when they are spread wider; nothing for fewer than
    three rows."""
    from django.utils.dates import MONTHS

    total = sum(by_month)
    if total < 3:
        return ""
    ranked = sorted(range(12), key=lambda m: (-by_month[m], m))
    picked, held = [], 0
    for m in ranked:
        picked.append(m)
        held += by_month[m]
        if 2 * held >= total:
            break
    if len(picked) > 3:
        return _("All year")
    names = [str(MONTHS[m + 1]) for m in sorted(picked)]
    if held == total:
        return _("All in %(months)s") % {"months": _join(names)}
    return _("Mostly %(months)s") % {"months": _join(names)}


def _lede(check: Check, section: str, params) -> str:
    """What a check means and what to look at first: the detail's sentence (#264)."""
    n = fmt
    if check.key == "tmaxmin":
        return _(
            "The minimum is at or above the maximum of the same day. This is almost always "
            "swapped columns or a typing error; a run of days suggests columns swapped for "
            "a stretch."
        )
    if check.key == "toolarge":
        hint = _("These are almost always typing errors or missing-value codes.")
        return f"{check.description} {hint}"
    if check.key == "duplicates":
        return _(
            "Dates given on more than one row of the file; the indices use the last row of "
            "each. Keep the right row and remove the others."
        )
    if check.key.endswith("_jumps"):
        hint = _(
            "Look first at the largest: a day out of line with both its neighbours is "
            "usually a typing error."
        )
        return f"{check.description} {hint}"
    if check.key.endswith("_flatline"):
        hint = _("Long runs of one value are often missing data filled in.")
        return f"{check.description} {hint}"
    variable, _sep, direction = section.partition("-")
    values = {"iqr": n(params.iqr_prec if variable == "prcp" else params.iqr_temp)}
    if variable == "prcp" and direction == "high":
        return (
            _(
                "More than %(iqr)s interquartile ranges above the usual box for the calendar "
                "month (days with rain only). Many are real storms: look first at the largest, "
                "and at any with no rain on the days either side."
            )
            % values
        )
    if variable == "prcp":
        return (
            _(
                "More than %(iqr)s interquartile ranges below the usual box for the calendar "
                "month (days with rain only). Look for values in the wrong unit."
            )
            % values
        )
    if direction == "high":
        return (
            _(
                "More than %(iqr)s interquartile ranges above the usual box for the calendar "
                "month. Look first at the largest, and at any far from the days either side."
            )
            % values
        )
    return (
        _(
            "More than %(iqr)s interquartile ranges below the usual box for the calendar month. "
            "Look first at the largest, and at any far from the days either side."
        )
        % values
    )


def _subcheck(check: Check, group: str, title: str, rows: list[Row]) -> Check:
    return Check(
        key=check.key,
        title=title,
        kind=check.kind,
        description=check.description,
        columns=check.columns,
        numeric=check.numeric,
        rows=rows,
        file=check.file,
        count=len(rows),
        group=group,
        value_columns=value_columns(check.key, group),
    )


def wrong_groups(checks: list[Check], params) -> list[Group]:
    """The "look wrong" checks that found something, in R's order (#264)."""
    shorts = short_labels()
    out = []
    for check in checks:
        if check.kind != "error" or not check.rows:
            continue
        by_month = _by_month(check.rows)
        if check.key == "tmaxmin":
            variable, y_label = shorts["tmin"], _deg(_("TN − TX"))
        elif check.key == "toolarge":
            found = {
                k
                for row in check.rows
                for k, cell in zip(("prcp", "tmax", "tmin"), row.cells[:3], strict=True)
                if cell.strong
            }
            variable = " ".join(shorts[k] for k in ("prcp", "tmax", "tmin") if k in found)
            y_label = _("Beyond the limit")
        else:
            variable, y_label = _("all rows"), _("Rows")
        out.append(
            Group(
                check,
                check.title,
                by_month,
                _mostly(by_month),
                variable,
                y_label=y_label,
                lede=_lede(check, "", params),
            )
        )
    return out


def worth_groups(checks: list[Check], params) -> list[Group]:
    """The "worth a look" groups, the largest first."""
    groups: list[Group] = []
    titles = outlier_titles()
    shorts = short_labels()
    for check in checks:
        if check.kind != "review" or not check.rows:
            continue
        if check.key == "outliers":
            by_section: dict[str, list[Row]] = {}
            for row in check.rows:
                by_section.setdefault(row.section, []).append(row)
            for section, rows in by_section.items():
                rows = sorted(rows, key=lambda r: (r.date[5:7], r.date))
                by_month = _by_month(rows)
                title = titles.get(section, check.title)
                variable = section.split("-")[0]
                code = shorts.get(variable, "")
                groups.append(
                    Group(
                        _subcheck(check, section, title, rows),
                        title,
                        by_month,
                        _mostly(by_month),
                        code,
                        y_label=numbers.with_unit(code, UNITS.get(variable, "")),
                        zero=variable == "prcp",
                        lede=_lede(check, section, params),
                    )
                )
            continue
        short = shorts["tmax" if check.key.startswith("tx") else "tmin"]
        if check.key.endswith("_jumps"):
            title = _("Large day-to-day change ≥ %(jump)s") % {"jump": _deg(fmt(params.jump))}
            rail_title, y_label = _("Large day-to-day change"), _deg(_("Change"))
        else:
            # More than flatline_days equal values in a row (climpact.qc.flatline).
            title = _("Same %(variable)s %(days)s+ days") % {
                "variable": short,
                "days": params.flatline_days + 1,
            }
            rail_title, y_label = "", _("Days in a row")
        by_month = _by_month(check.rows)
        groups.append(
            Group(
                check,
                title,
                by_month,
                _mostly(by_month),
                short,
                rail_title=rail_title,
                y_label=y_label,
                lede=_lede(check, "", params),
            )
        )
    order = {key: i for i, key in enumerate(CHECK_KEYS)}
    groups.sort(key=lambda g: (-g.count, order[g.check.key]))
    return groups


# ---- The rail and its details (#202, #264) ---------------------------------------------------


@dataclass
class Item:
    """One check of the rail on Quality, whose detail shows beside it (#264). ``id`` is
    its address (``?show=``)."""

    id: str
    group: Group

    @property
    def check(self) -> Check:
        return self.group.check

    @property
    def anchor(self) -> str:
        """The id of its detail: the check's anchor (#174)."""
        return self.check.anchor

    @property
    def wrong(self) -> bool:
        return self.group.wrong


# ---- Everything --------------------------------------------------------------------------


@dataclass
class Review:
    station: str
    params: object  # climpact.config.QCParams
    checks: list[Check]
    years: list[YearMissing]
    verdict: Verdict
    wrong: list[Group]  # the "look wrong" checks that found something
    groups: list[Group]  # "worth a look"
    files: list[str]  # every file in the job's output folder (relative)
    zip: str | None
    rows: StationRows

    def check(self, key: str) -> Check:
        return next(c for c in self.checks if c.key == key)

    @property
    def quiet(self) -> list[Check]:
        """The checks that found nothing."""
        return [c for c in self.checks if not c.count]

    @property
    def tables(self) -> list[Check]:
        """Every values table on the screen: one a check in the rail."""
        return [g.check for g in self.wrong + self.groups]

    @property
    def items(self) -> list[Item]:
        """The rail, in order: each "look wrong" check, then each "worth a look" group.
        Every row of every check is in one of their tables."""
        return [Item(g.id, g) for g in self.wrong + self.groups]

    def item(self, key: str) -> Item | None:
        """The item ``key`` (``?show=``), or the first."""
        items = self.items
        return next((i for i in items if i.id == key), items[0] if items else None)

    def table(self, key: str, group: str = "") -> Check | None:
        return next(
            (t for t in self.tables if t.key == key and t.group == group),
            None,
        )

    def group_of(self, check: Check) -> Group:
        return next(g for g in self.wrong + self.groups if g.check is check)

    def value(self, check: Check, row: Row | None) -> Finding | None:
        """The selected value of a check's detail, with the days around it."""
        if row is None:
            return None
        flagged = {r.date for r in check.rows}
        return build_finding(check, row, self.rows, self.params, flagged)

    def when(self, group: Group, selected: Row | None) -> dict:
        chart = when_chart(
            group.check.rows, self.rows.first_date, self.rows.last_date, group.zero, selected
        )
        if chart:
            chart["readout"] = when_readout(group, chart, selected)
        return chart

    @property
    def years_short(self) -> list[YearMissing]:
        return [y for y in self.years if y.any_no_annual]

    @property
    def years_short_text(self) -> str:
        """The years too incomplete for annual values, the first ten of them."""
        years = [str(y.year) for y in self.years_short]
        if len(years) > 10:
            return _("%(years)s and %(n)s more") % {
                "years": ", ".join(years[:10]),
                "n": len(years) - 10,
            }
        return _join(years)

    @property
    def quiet_titles(self) -> str:
        return _join([c.title for c in self.quiet])

    @property
    def coverage(self) -> list[dict]:
        """The coverage strip (#235): for PR, TX and TN, each year's missing days as a
        step (1: none, 2: 1–3 days, 3: 4 or more; ``--chart-coverage-*``) and the total."""
        shorts = short_labels()
        out = []
        for key in ("prcp", "tmax", "tmin"):
            cells = []
            for i, year in enumerate(self.years):
                days = year.days.get(key, 0)
                step = 1 if not days else 2 if days <= 3 else 3
                cells.append({"x": i, "year": year.year, "days": days, "step": step})
            total = sum(c["days"] for c in cells)
            out.append(
                {
                    "name": shorts[key],
                    "cells": cells,
                    "total": ngettext("%(n)s day", "%(n)s days", total)
                    % {"n": numbers.grouped(total)},
                }
            )
        return out

    @property
    def coverage_years(self) -> list[int]:
        """The years under the strip: up to seven, evenly spaced from the first to the
        last, so they line up when spread across its width."""
        years = [y.year for y in self.years]
        if len(years) < 2:
            return years
        k = min(7, len(years))
        return [years[round(i * (len(years) - 1) / (k - 1))] for i in range(k)]

    @property
    def years_missing(self) -> list[YearMissing]:
        return [y for y in self.years if y.any_missing]

    @property
    def nastatistics_file(self) -> str | None:
        return next((f for f in self.files if f.endswith("_nastatistics.csv")), None)

    @property
    def nastatistics_name(self) -> str:
        return Path(self.nastatistics_file).name if self.nastatistics_file else ""


def checked_file(job) -> Path:
    """The station file a ``qc`` job read: the copy saved in its ``input/`` folder when it
    was queued (``params["station_file"]``). Out-of-date checks are reviewed against it, not
    against the file that replaced it (#308)."""
    return job.input_dir / job.params["station_file"]


def review(job, station_file: Path | None = None) -> Review:
    """The review of a succeeded ``qc`` job (``job.result`` lists its files), with the
    station's rows from the file it read (:func:`checked_file`, unless ``station_file`` is
    given): the checks, the year table and the counts all describe that file, also once
    another has replaced it. :class:`FileNotFoundError` if the file is missing."""
    from climpact_web.jobs.runners import qc_params

    params = qc_params(job.params.get("qc"))
    station = StationRows.read(station_file or checked_file(job))
    reports = job.result.get("reports", {})
    output = Path(job.output_dir)

    def load(key: str) -> tuple[QCFile | None, str | None]:
        relative = reports.get(f"qc/{key}")
        if relative is None or not (output / relative).is_file():
            return None, None
        return read_qc_file(output / relative), relative

    checks = []
    for key in CHECK_KEYS:
        qcfile, relative = load(key)
        checks.append(build_check(key, qcfile, station, params, relative))
    nastatistics, _relative = load("nastatistics")
    years = missing_by_year(nastatistics, station)
    return Review(
        station=job.result.get("station", ""),
        params=params,
        checks=checks,
        years=years,
        verdict=verdict(checks, years, values_checked(station), missing=values_missing(station)),
        wrong=wrong_groups(checks, params),
        groups=worth_groups(checks, params),
        files=list(job.result.get("files", [])),
        zip=job.result.get("zip"),
        rows=station,
    )


# ---- The flagged values as one CSV (#235) ---------------------------------------------------

FLAGGED_COLUMNS = ("date", "check", "kind", "variable", "value", "units", "detail")


def _plain(text: str) -> str:
    """Screen text as a file writes it: hyphen-minus, plain spaces (#226)."""
    return str(text).replace(numbers.MINUS, "-").replace(numbers.NBSP, " ")


def flagged_rows(review: Review, key: str = "", group: str = "") -> list[list[str]]:
    """Every value the checks flagged, one row each, in R's order of the checks: the
    Quality verdict's "Flagged values (CSV)"; with ``key`` (and ``group``, an outliers
    group) only that check's, a check detail's "These values (CSV)" (#264). ``kind`` is
    "look wrong" or "worth a look"; values as the file has them, hyphen-minus for
    minus."""
    shorts = short_labels()
    out: list[list[str]] = []
    for check in review.checks:
        if key and check.key != key:
            continue
        kind = "look wrong" if check.kind == "error" else "worth a look"
        for row in check.rows:
            if group and row.section != group:
                continue
            c = [cell.text for cell in row.cells]

            def add(variable: str, value: str, detail: str, row=row, check=check, kind=kind):
                out.append(
                    [
                        row.date,
                        str(check.title),
                        kind,
                        shorts.get(variable, variable),
                        _plain(value),
                        UNITS.get(variable, ""),
                        _plain(detail),
                    ]
                )

            if check.key == "tmaxmin":
                add("tmin", c[2], f"TX {c[1]}")
            elif check.key == "toolarge":
                keys = [
                    k
                    for k, cell in zip(("prcp", "tmax", "tmin"), row.cells[:3], strict=True)
                    if cell.strong
                ]
                for name, part in zip(keys, _toolarge_parts(row.cells, review.params), strict=True):
                    value = row.cells[("prcp", "tmax", "tmin").index(name)].text
                    add(name, value, f"limit {part[2]}")
            elif check.key == "duplicates":
                add("all", c[0], _plain(c[1]))
            elif check.key == "outliers":
                variable = row.section.split("-")[0]
                value = next((cell.text for cell in row.cells[1:5] if cell.strong), "")
                add(variable, value, c[5])
            elif check.key.endswith("_jumps"):
                variable = "tmax" if check.key.startswith("tx") else "tmin"
                add(variable, c[0], f"next day {c[2]}: {c[1]}, change {c[3]}")
            else:
                variable = "tmax" if check.key.startswith("tx") else "tmin"
                add(variable, c[0], f"{c[1]} equal values, {c[2]}")
    return out
