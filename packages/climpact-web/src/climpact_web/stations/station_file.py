"""Checking an uploaded station file before it is accepted (step 1, #76).

The core reader (:func:`climpact.io.station.read_station_file`) stays the authority on
what a station file means, but its errors are written for the command line ("data row 7
has 3 fields, expected 6", or numpy's "could not convert string to float"). This module
walks the file first with the same rules (commas are separators, blank lines are
skipped, a first row whose first field is not an integer is a header) and reports every
problem in plain language with the **line number in the file** and the line itself.
Only a file with no problems is handed to the core, whose remaining errors (no valid
dates, rows not in date order) are translated too.

It also prepares what the page shows about the data: the period, the days and share
missing per variable, the days with data in each year, monthly means for the preview,
and warnings for things R accepts silently (impossible dates, repeated dates, rows out of
order).

The accepted file is stored as UTF-8 without a byte-order mark (:attr:`Inspection.text`):
the core reads text with Python's default encoding, and a BOM would make it take the
first data row for a header.
"""

from __future__ import annotations

import calendar
import datetime as dt
import math
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from django.utils.translation import gettext as _
from django.utils.translation import ngettext

MAX_PROBLEMS_SHOWN = 10
MAX_LINE_SHOWN = 80
MISSING_VALUE = -99.9
NA_STRING = "NA"  # also missing, as R's read.table (na.strings = "NA") reads it
COLUMNS = ("year", "month", "day", "prcp", "tmax", "tmin")
VARIABLES = ("prcp", "tmax", "tmin")
_INTEGER = re.compile(r"^[+-]?\d+$")


def column_label(column: str) -> str:
    return {
        "year": _("year"),
        "month": _("month"),
        "day": _("day"),
        "prcp": _("precipitation"),
        "tmax": _("maximum temperature"),
        "tmin": _("minimum temperature"),
    }[column]


def variable_label(variable: str) -> str:
    return {
        "prcp": _("Precipitation"),
        "tmax": _("Maximum temperature"),
        "tmin": _("Minimum temperature"),
    }[variable]


@dataclass
class Problem:
    """Something that stops the file being used, at a line of the file (or the whole
    file when ``line`` is None)."""

    message: str
    line: int | None = None
    text: str = ""
    short: str = ""  # the problem in a few words, for a table cell (Add stations, #233)


@dataclass
class Inspection:
    problems: list[Problem] = field(default_factory=list)
    problem_count: int = 0  # all problems, including those not listed
    warnings: list[str] = field(default_factory=list)
    summary: dict | None = None
    text: str = ""  # the file as accepted (UTF-8, no BOM, "\n" line ends)
    repeats: int = 0  # dates that appear more than once (a warning, #233's Read column)

    @property
    def ok(self) -> bool:
        return not self.problem_count

    @property
    def hidden_problems(self) -> int:
        return self.problem_count - len(self.problems)

    def add(self, problem: Problem) -> None:
        self.problem_count += 1
        if len(self.problems) < MAX_PROBLEMS_SHOWN:
            self.problems.append(problem)


def shorten(line: str) -> str:
    line = line.strip()
    return line if len(line) <= MAX_LINE_SHOWN else line[: MAX_LINE_SHOWN - 1] + "…"


def decode(raw: bytes) -> str | None:
    """The file's text, or None when it is not a text file."""
    if raw[:4] == b"PK\x03\x04" or raw[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return None  # a zip (xlsx, ods) or an old Excel workbook
    if b"\x00" in raw[:8192]:
        return None
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")  # only a header line is likely to have such text
    return "\n".join(text.splitlines()) + "\n"


def inspect_station_bytes(raw: bytes) -> Inspection:
    """Check a station file's contents and summarise its data."""
    result = Inspection()
    if not raw.strip():
        result.add(Problem(_("The file is empty.")))
        return result
    text = decode(raw)
    if text is None:
        result.add(
            Problem(
                _(
                    "This is not a text file. If it is a spreadsheet, save it as text "
                    "(tab-delimited or CSV) with the six columns year, month, day, "
                    "precipitation, maximum and minimum temperature."
                )
            )
        )
        return result
    result.text = text

    rows = _check_lines(text, result)
    if not result.ok:
        return result
    if not rows:
        result.add(Problem(_("The file has no data rows, only a header.")))
        return result

    df = _read_with_core(text, result)
    if df is None:
        return result
    _warn_about_rows(rows, result)
    result.summary = summarise(df)
    _warn_about_variables(result)
    return result


def _check_lines(text: str, result: Inspection) -> list[tuple[int, list[float]]]:
    """Every data line as (line number, six numbers), adding a problem for each line that
    the core could not read."""
    rows = []
    first = True
    for number, line in enumerate(text.split("\n"), start=1):
        fields = line.replace(",", "\t").split()
        if not fields:
            continue
        if first:
            first = False
            if not _INTEGER.match(fields[0]):
                continue  # a header row, skipped as R does
        if len(fields) != len(COLUMNS):
            result.add(
                Problem(
                    ngettext(
                        "Line %(line)d has %(count)d value; each line needs 6: year, "
                        "month, day, precipitation, maximum and minimum temperature.",
                        "Line %(line)d has %(count)d values; each line needs 6: year, "
                        "month, day, precipitation, maximum and minimum temperature.",
                        len(fields),
                    )
                    % {"line": number, "count": len(fields)}
                    + (
                        " " + _("Commas separate values, so write decimals with a point (.).")
                        if "," in line and len(fields) > len(COLUMNS)
                        else ""
                    ),
                    number,
                    shorten(line),
                    ngettext(
                        "line %(line)d has %(count)d value, expected 6 (year month day PR TX TN)",
                        "line %(line)d has %(count)d values, expected 6 (year month day PR TX TN)",
                        len(fields),
                    )
                    % {"line": number, "count": len(fields)},
                )
            )
            continue
        values = []
        for column, value in zip(COLUMNS, fields, strict=True):
            if value == NA_STRING:
                values.append(math.nan)  # missing, as R's read.table reads it
                continue
            try:
                number_value = float(value)
            except ValueError:
                number_value = None
            if number_value is None or math.isinf(number_value):
                if value.upper() in {"NA", "N/A", "NULL", "-", "."}:
                    message = _(
                        "Line %(line)d: “%(value)s” in the %(column)s column is not a "
                        "number. Write missing values as -99.9 (or NA, in capitals)."
                    )
                else:
                    message = _(
                        "Line %(line)d: “%(value)s” in the %(column)s column is not a number."
                    )
                result.add(
                    Problem(
                        message
                        % {"line": number, "value": value[:20], "column": column_label(column)},
                        number,
                        shorten(line),
                        _("line %(line)d: “%(value)s” is not a number")
                        % {"line": number, "value": value[:20]},
                    )
                )
                break
            values.append(number_value)
        else:
            rows.append((number, values))
    return rows


def _read_with_core(text: str, result: Inspection):
    """The core's reading of the file (rows in file order, invalid dates dropped), or
    None after adding a problem for the core's own errors."""
    from climpact.io.station import merged_rows, read_station_file

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "station.txt"
        path.write_text(text, encoding="utf-8")
        try:
            df = read_station_file(path)
            merged_rows(df)
        except ValueError as exc:
            result.add(Problem(core_error_message(str(exc))))
            return None
    return df


def core_error_message(message: str) -> str:
    """The core reader's error in plain language."""
    if "no valid dates" in message:
        return _(
            "None of the rows has a valid date. Check that the first three columns are "
            "year, month and day."
        )
    date = r"\((\d{4}-\d\d-\d\d)\)"
    match = re.search(date + " is dated before the first " + date, message)
    if match:
        return _(
            "The rows are not in date order: the last row (%(last)s) is dated before the "
            "first (%(first)s). Sort the file by date."
        ) % {"last": match.group(1), "first": match.group(2)}
    match = re.search(r"data row (\d+) has (\d+) fields", message)
    if match:  # caught line by line before the core runs; kept for completeness
        return _("Data row %(row)s has %(count)s values; each row needs 6.") % {
            "row": match.group(1),
            "count": match.group(2),
        }
    return _("The file could not be read: %(error)s") % {"error": message}


def _date(values: list[float]) -> dt.date | None:
    year, month, day = values[:3]
    if not all(float(v).is_integer() for v in (year, month, day)):
        return None
    try:
        return dt.date(int(year), int(month), int(day))
    except ValueError:
        return None


def _date_part(value: float) -> str:
    if math.isnan(value):
        return NA_STRING
    return f"{int(value)}" if value.is_integer() else f"{value}"


def _warn_about_rows(rows: list[tuple[int, list[float]]], result: Inspection) -> None:
    """Warnings for rows R accepts but silently drops or reorders."""
    invalid = [(n, v) for n, v in rows if _date(v) is None]
    if invalid:
        line, values = invalid[0]
        shown = "-".join(_date_part(v) for v in values[:3])
        result.warnings.append(
            ngettext(
                "%(count)d row has a date that does not exist (line %(line)d: %(date)s). "
                "It is left out, as in Climpact for R.",
                "%(count)d rows have dates that do not exist (the first is line %(line)d: "
                "%(date)s). They are left out, as in Climpact for R.",
                len(invalid),
            )
            % {"count": len(invalid), "line": line, "date": shown}
        )
    dated = [(n, d) for n, v in rows if (d := _date(v)) is not None]
    if not dated:
        return
    first, last = dated[0][1], dated[-1][1]
    outside = [(n, d) for n, d in dated if d < first or d > last]
    if outside:
        result.warnings.append(
            ngettext(
                "%(count)d row is dated outside the range from the first row (%(first)s) "
                "to the last (%(last)s) (line %(line)d) and is left out, as in Climpact "
                "for R. Sort the file by date to keep it.",
                "%(count)d rows are dated outside the range from the first row (%(first)s) "
                "to the last (%(last)s) (the first is line %(line)d) and are left out, as "
                "in Climpact for R. Sort the file by date to keep them.",
                len(outside),
            )
            % {"count": len(outside), "first": first, "last": last, "line": outside[0][0]}
        )
    elif any(b[1] < a[1] for a, b in zip(dated, dated[1:], strict=False)):
        result.warnings.append(_("The rows are not in date order. They are sorted by date."))
    lines_by_date: dict[dt.date, list[int]] = {}
    for n, d in dated:
        lines_by_date.setdefault(d, []).append(n)
    repeats = [(d, lines) for d, lines in lines_by_date.items() if len(lines) > 1]
    result.repeats = len(repeats)
    if repeats:
        date, lines = repeats[0]
        result.warnings.append(
            ngettext(
                "%(count)d date appears more than once (%(date)s, lines %(lines)s). The "
                "quality checks list it; the indices use its last row.",
                "%(count)d dates appear more than once (the first is %(date)s, lines "
                "%(lines)s). The quality checks list them; the indices use the last row "
                "of each.",
                len(repeats),
            )
            % {"count": len(repeats), "date": date, "lines": ", ".join(map(str, lines[:5]))}
        )


def _warn_about_variables(result: Inspection) -> None:
    for variable in result.summary["variables"]:
        if variable["present"] == 0:
            result.warnings.append(
                _("The file has no %(variable)s values: every value is missing.")
                % {"variable": column_label(variable["key"])}
            )


def summarise(df) -> dict:
    """What step 1 shows about the data, as JSON: from the rows R's quality control works
    on (:func:`climpact.io.station.merged_rows`, every day from the first row's date to the
    last row's), one value per date (the last row of a repeated date, as the indices use).
    """
    import numpy as np
    import pandas as pd

    from climpact.io.station import merged_rows

    rows = merged_rows(df).drop_duplicates(subset="date", keep="last").set_index("date")
    first, last = rows.index[0], rows.index[-1]
    days = len(rows)
    variables = []
    for key in VARIABLES:
        present = int(rows[key].notna().sum())
        variables.append(
            {
                "key": key,
                "present": present,
                "missing": days - present,
                "percent_missing": round(100 * (days - present) / days, 1),
            }
        )

    years = []
    for year in range(first.year, last.year + 1):
        in_year = rows[rows.index.year == year]
        length = 366 if calendar.isleap(year) else 365
        years.append(
            {"year": year, "days": length, **{k: int(in_year[k].notna().sum()) for k in VARIABLES}}
        )

    monthly = rows.resample("MS")
    counts = monthly.count()

    def series(values, minimum_days=20):
        # A month with fewer than ``minimum_days`` values is a gap in the preview.
        out = []
        for value, count in zip(values, counts[values.name], strict=True):
            out.append(None if count < minimum_days or pd.isna(value) else round(float(value), 2))
        return out

    preview = {
        "start": f"{first.year}-{first.month:02d}",
        "tmax": series(monthly["tmax"].mean()),
        "tmin": series(monthly["tmin"].mean()),
        "prcp": series(monthly["prcp"].sum(min_count=1)),
    }
    return {
        "first_date": str(first.date()),
        "last_date": str(last.date()),
        "first_year": int(first.year),
        "last_year": int(last.year),
        "days": int(days),
        "variables": variables,
        "years": years,
        "preview": preview,
        "rows": int(np.int64(len(df))),
    }


def base_period_days(summary: dict, start: int, end: int) -> int:
    """Days of the base period between the data's first and last dates: the core's (and
    climdex.pcic's) test for computing thresholds (``thresholds._days_in_base``)."""
    first = dt.date.fromisoformat(summary["first_date"])
    last = dt.date.fromisoformat(summary["last_date"])
    begin = max(first, dt.date(max(start, 1), 1, 1))
    finish = min(last, dt.date(min(end, 9999), 12, 31))
    return max((finish - begin).days + 1, 0)
