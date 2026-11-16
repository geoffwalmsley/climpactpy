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
:data:`VERDICT_LIMITS`), the findings of the checks that "look wrong" each with the days
around it, and the "worth a look" rows in groups by variable and calendar month. The
user decides whether the data is fit to continue. Nothing here changes the data.
"""

from __future__ import annotations

import csv
import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext

PAGE_SIZE = 50

# Each check: its file (qc/<key>), its title, which variable's chart its rows show, and
# whether what it finds is almost always a mistake ("error") or may be a real value
# ("review"). In R's order (QC_REPORTS).
CHECKS = (
    ("tmaxmin", gettext_lazy("Minimum at or above maximum"), "error"),
    ("toolarge", gettext_lazy("Values too large"), "error"),
    ("duplicates", gettext_lazy("Repeated dates"), "error"),
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
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return None if value != value else value


def fmt(value: float | None) -> str:
    """A value as the files write it (at most 15 significant digits, no trailing zeros)."""
    if value is None:
        return ""
    text = f"{value:.15g}"
    return "0" if text == "-0" else text


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

    @classmethod
    def read(cls, station_file: Path) -> StationRows:
        from climpact.io.station import merged_rows, read_station_file

        rows = merged_rows(read_station_file(station_file))
        dates = [d.date().isoformat() for d in rows["date"]]
        values = {k: [number(v) for v in rows[k]] for k in ("prcp", "tmax", "tmin")}
        last = {d: i for i, d in enumerate(dates)}
        return cls(dates, values, last, dates[0] if dates else "", dates[-1] if dates else "")

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

    @property
    def help_id(self) -> str:
        return f"qc.{self.key}"

    @property
    def table_id(self) -> str:
        return f"{self.key}-{self.group}" if self.group else self.key

    @property
    def header(self) -> list[tuple[str, bool]]:
        return list(zip(self.columns, self.numeric, strict=True))

    @property
    def file_name(self) -> str:
        return Path(self.file).name if self.file else ""

    @property
    def anchor(self) -> str:
        return f"check-{self.table_id}"

    def page(self, number: int) -> Page:
        pages = max(1, -(-len(self.rows) // PAGE_SIZE))
        number = min(max(1, number), pages)
        start = (number - 1) * PAGE_SIZE
        return Page(self, number, pages, start, self.rows[start : start + PAGE_SIZE])

    def page_of(self, date: str) -> int:
        for i, row in enumerate(self.rows):
            if row.date == date:
                return i // PAGE_SIZE + 1
        return 1


@dataclass
class Page:
    check: Check
    number: int
    pages: int
    start: int
    rows: list[Row]

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
        rows.append(Row(date, cells, variable, f"{variable}-{'high' if high else 'low'}"))
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
        out.append(Row(date, cells, "dtr"))
    return out


def _toolarge_rows(qcfile: QCFile, params) -> list[Row]:
    t, limit = params.temp_max, params.prec_max

    def strong(p, x, n):
        return (
            p is not None and (p > limit or p < 0),
            x is not None and abs(x) > t,
            n is not None and abs(n) > t,
        )

    return [Row(date, cells, chart) for date, cells, chart, *_v in _rows_table(qcfile, strong)]


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
        rows.append(Row(date, cells, "tmax"))
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
        cells = [
            value_cell(this),
            value_cell(nxt),
            text_cell(next_date),
            value_cell(_change(this, nxt), strong=True),
        ]
        rows.append(Row(date, cells, variable))
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
        if pick is not None:
            end = pick + 1
            start = max(0, end - count + 1)
            span = _("%(first)s to %(last)s") % {
                "first": station.dates[start],
                "last": station.dates[end],
            }
        else:
            span = ""
        cells = [value_cell(value, strong=True), Cell(str(count)), text_cell(span)]
        rows.append(Row(date, cells, variable))
    return rows


def _description(key: str, params) -> str:
    n = fmt
    texts = {
        "tmaxmin": _("Days where the minimum temperature is equal to or higher than the maximum."),
        "toolarge": _(
            "Precipitation above %(prec)s mm or below 0 mm, and temperatures above %(temp)s °C "
            "or below -%(temp)s °C."
        )
        % {"prec": n(params.prec_max), "temp": n(params.temp_max)},
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
            "Days where the maximum temperature changes by %(jump)s °C or more to the next "
            "day. The date is the first of the two days."
        )
        % {"jump": n(params.jump)},
        "tn_jumps": _(
            "Days where the minimum temperature changes by %(jump)s °C or more to the next "
            "day. The date is the first of the two days."
        )
        % {"jump": n(params.jump)},
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


def grouped(n: int) -> str:
    from django.utils.formats import number_format

    return number_format(n, force_grouping=True)


@dataclass
class Verdict:
    level: str  # "ready" (green), "usable" (amber) or "fix" (red)
    title: str
    sentences: list[str]  # what it means and what to do
    facts: list[str]  # the counts against what was checked, one line
    values: int  # values checked: PR, TX and TN present on each date
    wrong: int  # rows of the "look wrong" checks (dates, for repeated dates)
    worth: int  # rows of the "worth a look" checks
    years: int
    short_years: int  # years too incomplete for annual values
    too_many_wrong: bool
    too_many_short: bool

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


def verdict(
    checks: list[Check],
    years: list[YearMissing],
    values: int,
    limits: VerdictLimits = VERDICT_LIMITS,
) -> Verdict:
    """Decision B (#174): green when nothing looks wrong, amber when up to
    ``limits.wrong_share`` of the values checked look wrong, red above it or when more than
    ``limits.short_years_share`` of the years are too incomplete for annual values. The
    user can go on whatever the level."""
    wrong = sum(c.count for c in checks if c.kind == "error")
    worth = sum(c.count for c in checks if c.kind == "review")
    short = sum(1 for y in years if y.any_no_annual)
    too_many_wrong = wrong > limits.wrong_share * values
    too_many_short = short > limits.short_years_share * len(years)

    facts = [
        ngettext("%(n)s value checked", "%(n)s values checked", values) % {"n": grouped(values)},
        ngettext("%(n)s looks wrong (%(percent)s)", "%(n)s look wrong (%(percent)s)", wrong)
        % {"n": grouped(wrong), "percent": percent(wrong, values)},
        _("%(n)s worth a look (%(percent)s)")
        % {"n": grouped(worth), "percent": percent(worth, values)},
    ]
    if short:
        facts.append(
            ngettext(
                "%(n)s of %(total)s years too incomplete for annual values",
                "%(n)s of %(total)s years too incomplete for annual values",
                short,
            )
            % {"n": grouped(short), "total": grouped(len(years))}
        )

    if too_many_wrong or too_many_short:
        level, title = "fix", _("Fix the file first")
        sentences = []
        if too_many_wrong:
            sentences.append(
                ngettext(
                    "%(n)s value looks wrong, %(percent)s of the values checked.",
                    "%(n)s values look wrong, %(percent)s of the values checked.",
                    wrong,
                )
                % {"n": grouped(wrong), "percent": percent(wrong, values)}
            )
        if too_many_short:
            sentences.append(
                ngettext(
                    "%(n)s of %(total)s years has too much missing data for annual values.",
                    "%(n)s of %(total)s years have too much missing data for annual values.",
                    short,
                )
                % {"n": grouped(short), "total": grouped(len(years))}
            )
        sentences.append(
            _("Correct the file and upload it again. You can also use the data as it is.")
        )
    elif wrong:
        level = "usable"
        title = ngettext(
            "Usable. %(n)s value looks wrong.", "Usable. %(n)s values look wrong.", wrong
        ) % {"n": grouped(wrong)}
        sentences = [_("Fix them in your file, or go on with the values as they are.")]
    else:
        level, title = "ready", _("Ready to use")
        sentences = [_("Nothing looks wrong.")]
    if worth:
        sentences.append(
            ngettext(
                "%(n)s value is unusual but may be real.",
                "%(n)s values are unusual but may be real.",
                worth,
            )
            % {"n": grouped(worth)}
        )
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
    )


# ---- "Look wrong": each finding with the days around it ------------------------------------

FINDINGS_SHOWN = 10  # rows of a "look wrong" check shown with their chart; all are in its table
WINDOW_DAYS = 7  # days either side of a finding, in its chart and its table
SPARK_W, SPARK_H, SPARK_PAD = 120, 32, 4  # the chart's box (CSS keeps the same ratio)


@dataclass
class Finding:
    row: Row
    text: str  # what looks wrong, in a sentence
    spark: dict  # "lines": [{"variable", "d"}], "ring": {"x", "y"} or None
    days: list[dict]  # the days around it: date, cells (PR, TX, TN texts), this (the day)

    @property
    def date(self) -> str:
        return self.row.date


def _window(station: StationRows, date: str) -> list[tuple[str, dict[str, float | None]]]:
    day = dt.date.fromisoformat(date)
    out = []
    for offset in range(-WINDOW_DAYS, WINDOW_DAYS + 1):
        iso = (day + dt.timedelta(days=offset)).isoformat()
        out.append((iso, station.day(iso)))
    return out


def _spark(window, variables: tuple[str, ...], ring: str, date: str) -> dict:
    """Path data for the chart of a finding: a line per variable over the window (gaps
    where values are missing) and a ring round the flagged value, in integer coordinates."""
    present = [v[k] for _d, v in window for k in variables if v[k] is not None]
    if not present:
        return {}
    low, high = min(present), max(present)
    span = (high - low) or 1.0
    n = len(window)

    def x(i: int) -> int:
        return round(i * SPARK_W / (n - 1))

    def y(v: float) -> int:
        if high == low:
            return SPARK_H // 2
        return round(SPARK_H - SPARK_PAD - (v - low) / span * (SPARK_H - 2 * SPARK_PAD))

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
    value = window[centre][1][ring]
    return {
        "lines": lines,
        "ring": None if value is None else {"x": x(centre), "y": y(value)},
    }


def _finding_text(check: Check, row: Row, params) -> str:
    cells = row.cells
    if check.key == "tmaxmin":
        tx, tn = number(cells[1].text), number(cells[2].text)
        values = {"tn": cells[2].text, "tx": cells[1].text}
        if tx is not None and tn is not None and tn == tx:
            return _("Minimum %(tn)s °C equals the maximum %(tx)s °C") % values
        return _("Minimum %(tn)s °C is above the maximum %(tx)s °C") % values
    if check.key == "toolarge":
        parts = []
        prcp, tmax, tmin = cells[0], cells[1], cells[2]
        if prcp.strong:
            p = number(prcp.text) or 0.0
            parts.append(
                (
                    _("Rain %(value)s mm, below 0 mm")
                    if p < 0
                    else _("Rain %(value)s mm, over the %(limit)s mm limit")
                )
                % {"value": prcp.text, "limit": fmt(params.prec_max)}
            )
        for cell, high_text, low_text in (
            (
                tmax,
                _("Maximum %(value)s °C, over the %(limit)s °C limit"),
                _("Maximum %(value)s °C, under the %(limit)s °C limit"),
            ),
            (
                tmin,
                _("Minimum %(value)s °C, over the %(limit)s °C limit"),
                _("Minimum %(value)s °C, under the %(limit)s °C limit"),
            ),
        ):
            if cell.strong:
                v = number(cell.text) or 0.0
                parts.append(
                    (high_text if v > 0 else low_text)
                    % {
                        "value": cell.text,
                        "limit": fmt(params.temp_max if v > 0 else -params.temp_max),
                    }
                )
        return "; ".join(parts)
    n = int(number(cells[0].text) or 0)
    return ngettext(
        "Given on %(n)s row of the file. The indices use the last.",
        "Given on %(n)s rows of the file. The indices use the last.",
        n,
    ) % {"n": n}


def build_finding(check: Check, row: Row, station: StationRows, params) -> Finding:
    window = _window(station, row.date)
    if check.key == "toolarge":
        variables, ring = (row.chart,), row.chart
    elif check.key == "tmaxmin":
        variables, ring = ("tmax", "tmin"), "tmin"
    else:
        variables, ring = ("tmax", "tmin"), "tmax"
    days = [
        {
            "date": d,
            "cells": [value_cell(v[k]) for k in ("prcp", "tmax", "tmin")],
            "this": d == row.date,
        }
        for d, v in window
    ]
    return Finding(
        row, _finding_text(check, row, params), _spark(window, variables, ring, row.date), days
    )


@dataclass
class FindingList:
    """A "look wrong" check that found something: its first rows as findings, and the
    check (all its rows, in its table, when there are more)."""

    check: Check
    findings: list[Finding]

    @property
    def more(self) -> bool:
        return self.check.count > len(self.findings)


# ---- "Worth a look": groups by variable and direction, with counts by month -----------------


def outlier_titles() -> dict[str, str]:
    return {
        "prcp-high": _("Heavy rain days"),
        "prcp-low": _("Light rain days"),
        "tmax-high": _("High maximum temperatures (TX)"),
        "tmax-low": _("Low maximum temperatures (TX)"),
        "tmin-high": _("High minimum temperatures (TN)"),
        "tmin-low": _("Low minimum temperatures (TN)"),
        "dtr-high": _("Wide daily range (DTR)"),
        "dtr-low": _("Narrow daily range (DTR)"),
    }


@dataclass
class Group:
    """Rows of a "worth a look" check: a variable and direction of ``qc/outliers`` (its
    rows by calendar month), or a whole check (jumps, flat runs)."""

    check: Check  # the group's rows as a check, so it has a table of its own
    title: str
    by_month: list[int] = field(default_factory=list)  # rows in each calendar month, outliers
    mostly: str = ""  # "Mostly in January, February and March", when a few months hold most

    @property
    def count(self) -> int:
        return self.check.count


def _join(items: list[str]) -> str:
    if len(items) < 2:
        return "".join(items)
    return _("%(first)s and %(last)s") % {"first": ", ".join(items[:-1]), "last": items[-1]}


def _mostly(by_month: list[int]) -> str:
    """The calendar months that hold at least half the rows, when there are at most three
    of them: "Mostly in January, February and March"."""
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
        return ""
    names = [str(MONTHS[m + 1]) for m in sorted(picked)]
    if held == total:
        return _("All in %(months)s") % {"months": _join(names)}
    return _("Mostly in %(months)s") % {"months": _join(names)}


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
    )


def worth_groups(checks: list[Check], params) -> list[Group]:
    """The "worth a look" groups, the largest first."""
    groups: list[Group] = []
    titles = outlier_titles()
    for check in checks:
        if check.kind != "review" or not check.rows:
            continue
        if check.key == "outliers":
            by_section: dict[str, list[Row]] = {}
            for row in check.rows:
                by_section.setdefault(row.section, []).append(row)
            for section, rows in by_section.items():
                rows = sorted(rows, key=lambda r: (r.date[5:7], r.date))
                by_month = [0] * 12
                for row in rows:
                    by_month[int(row.date[5:7]) - 1] += 1
                title = titles.get(section, check.title)
                groups.append(
                    Group(
                        _subcheck(check, section, title, rows),
                        title,
                        by_month,
                        _mostly(by_month),
                    )
                )
            continue
        short = short_labels()["tmax" if check.key.startswith("tx") else "tmin"]
        if check.key.endswith("_jumps"):
            title = _("Large day-to-day changes in %(variable)s (%(jump)s °C or more)") % {
                "variable": short,
                "jump": fmt(params.jump),
            }
        else:
            title = _("The same %(variable)s on more than %(days)s days in a row") % {
                "variable": short,
                "days": params.flatline_days,
            }
        groups.append(Group(check, title))
    order = {key: i for i, key in enumerate(CHECK_KEYS)}
    groups.sort(key=lambda g: (-g.count, order[g.check.key]))
    return groups


# ---- Everything --------------------------------------------------------------------------


@dataclass
class Review:
    station: str
    params: object  # climpact.config.QCParams
    checks: list[Check]
    years: list[YearMissing]
    verdict: Verdict
    findings: list[FindingList]  # the "look wrong" checks that found something
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
        """Every table on the screen: the "look wrong" checks and the groups."""
        return [f.check for f in self.findings] + [g.check for g in self.groups]

    def table(self, key: str, group: str = "") -> Check | None:
        return next(
            (t for t in self.tables if t.key == key and t.group == group),
            None,
        )

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
    def years_missing(self) -> list[YearMissing]:
        return [y for y in self.years if y.any_missing]

    @property
    def nastatistics_file(self) -> str | None:
        return next((f for f in self.files if f.endswith("_nastatistics.csv")), None)

    @property
    def nastatistics_name(self) -> str:
        return Path(self.nastatistics_file).name if self.nastatistics_file else ""


def review(job, station_file: Path) -> Review:
    """The review of a succeeded ``qc`` job (``job.result`` lists its files)."""
    from climpact_web.jobs.runners import qc_params

    params = qc_params(job.params.get("qc"))
    station = StationRows.read(station_file)
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
    findings = [
        FindingList(c, [build_finding(c, r, station, params) for r in c.rows[:FINDINGS_SHOWN]])
        for c in checks
        if c.kind == "error" and c.rows
    ]
    return Review(
        station=job.result.get("station", ""),
        params=params,
        checks=checks,
        years=years,
        verdict=verdict(checks, years, values_checked(station)),
        findings=findings,
        groups=worth_groups(checks, params),
        files=list(job.result.get("files", [])),
        zip=job.result.get("zip"),
        rows=station,
    )
