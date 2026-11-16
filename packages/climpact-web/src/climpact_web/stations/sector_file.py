"""Step 5, sector data (#90): checking an uploaded sector file and the step's form.

The core (:func:`climpact.sector.read_sector_file`) stays the authority on what a sector
file means, but it stops at the first problem with a message written for the command line,
and the web server does not import the core (it imports xclim). This module walks the file
with the same rules as R's ``read.csv`` and the core (a header row, then ``Year`` and one
value per row, comma-separated; ``-99.9``, ``NA`` or nothing for a missing value; blank lines
skipped) and reports every problem in plain language with the **line of the file** and the
line itself, as step 1 does for station files (:mod:`climpact_web.stations.station_file`).

It also checks what R checks only once the calculation runs: at least 10 years in common
with the station file (R's "not able to make a correlation, since there is no data in
common!"), counting years whose value is missing, as R does.

The accepted file is stored as UTF-8 without a byte-order mark (:attr:`SectorInspection.text`).
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from django import forms
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext

from climpact_web.stations.station_file import Inspection, Problem, decode, shorten

SAMPLE_NAME = "wheat_yield_nsw_1922-1999.csv"
SAMPLE_FILE = Path(__file__).parent / "sample_data" / SAMPLE_NAME
SECTOR_FILE = "sector.csv"  # the name in the job's input/ folder
MIN_COMMON_YEARS = 10  # climpact.sector.MIN_COMMON_YEARS (checked by a test)
R_NO_COMMON_DATA = "not able to make a correlation, since there is no data in common!"
MISSING_TEXT = {"", "NA", "-99.9"}
_INTEGER = re.compile(r"^[+-]?\d+$")
ACCEPT = ".csv,.txt,text/csv,text/plain"


@dataclass
class SectorInspection(Inspection):
    years: list[int] = field(default_factory=list)
    values: int = 0  # years with a value
    column: str = ""  # the data column's name, as written in the file
    common: list[int] = field(default_factory=list)  # years in common with the station


def default_y_label(file_name: str) -> str:
    """R's default y-axis label: the file name up to its first ``_`` or ``.``
    (``climpact.sector.default_y_label``)."""
    return re.split(r"[_.]", Path(file_name).name)[0]


def _number(text: str) -> float | None:
    try:
        value = float(text)
    except ValueError:
        return None
    return value if value == value and abs(value) != float("inf") else None


def inspect_sector_bytes(raw: bytes, station_years: list[int] | None = None) -> SectorInspection:
    """Check a sector file's contents; with ``station_years``, also that it has at least
    ``MIN_COMMON_YEARS`` years in common with the station."""
    result = SectorInspection()
    if not raw.strip():
        result.add(Problem(_("The file is empty.")))
        return result
    text = decode(raw)
    if text is None:
        result.add(
            Problem(
                _(
                    "This is not a text file. Save your sector data as CSV (comma-separated "
                    "values), for example with “Save as” in a spreadsheet, and load that file."
                )
            )
        )
        return result
    result.text = text
    lines = [(n, line) for n, line in enumerate(text.splitlines(), start=1) if line.strip()]
    if not lines:
        result.add(Problem(_("The file is empty.")))
        return result

    head_line, head = lines[0]
    header = next(csv.reader([head]))
    first = header[0].strip() if header else ""
    if _number(first) is not None:
        result.add(
            Problem(
                _(
                    "Line %(line)s: the first line must hold the column names, Year and the "
                    "name of your data, for example: Year,Wheat yield (t/ha)"
                )
                % {"line": head_line},
                head_line,
                shorten(head),
            )
        )
        return result
    if len(header) != 2:
        hint = ""
        if len(header) == 1 and (";" in head or "\t" in head):
            hint = " " + _("Separate the columns with a comma, not a semicolon or a tab.")
        result.add(
            Problem(
                ngettext(
                    "Line %(line)s has %(n)s column name; the file needs two columns, Year "
                    "and your data, separated by a comma.",
                    "Line %(line)s has %(n)s column names; the file needs two columns, Year "
                    "and your data, separated by a comma.",
                    len(header),
                )
                % {"line": head_line, "n": len(header)}
                + hint,
                head_line,
                shorten(head),
            )
        )
        return result
    if first != "Year":
        result.add(
            Problem(
                _("Line %(line)s: the first column must be named Year, not “%(name)s”.")
                % {"line": head_line, "name": first},
                head_line,
                shorten(head),
            )
        )
    result.column = header[1].strip()

    seen: dict[int, int] = {}
    previous: int | None = None
    for line_no, line in lines[1:]:
        row = next(csv.reader([line]))
        if len(row) != 2:
            message = ngettext(
                "Line %(line)s has %(n)s value; each line needs two, the year and your value.",
                "Line %(line)s has %(n)s values; each line needs two, the year and your value.",
                len(row),
            ) % {"line": line_no, "n": len(row)}
            if len(row) == 3 and _INTEGER.match(row[2].strip() or "x"):
                message += " " + _(
                    "If a number has a decimal comma, write it with a point (0.66, not 0,66)."
                )
            result.add(Problem(message, line_no, shorten(line)))
            continue
        year_text, value_text = row[0].strip(), row[1].strip()
        if not _INTEGER.match(year_text):
            result.add(
                Problem(
                    _("Line %(line)s: the year “%(year)s” is not a whole number.")
                    % {"line": line_no, "year": year_text},
                    line_no,
                    shorten(line),
                )
            )
            continue
        year = int(year_text)
        if value_text not in MISSING_TEXT:
            value = _number(value_text)
            if value is None:
                result.add(
                    Problem(
                        _(
                            "Line %(line)s: “%(value)s” is not a number. Write a missing "
                            "value as -99.9."
                        )
                        % {"line": line_no, "value": value_text},
                        line_no,
                        shorten(line),
                    )
                )
            elif value != -99.9:
                result.values += 1
        if year in seen:
            result.add(
                Problem(
                    _("Line %(line)s: the year %(year)s is repeated (first on line %(first)s).")
                    % {"line": line_no, "year": year, "first": seen[year]},
                    line_no,
                    shorten(line),
                )
            )
        elif previous is not None and year < previous:
            result.add(
                Problem(
                    _(
                        "Line %(line)s: the year %(year)s comes after %(previous)s. Put the "
                        "years in order, oldest first."
                    )
                    % {"line": line_no, "year": year, "previous": previous},
                    line_no,
                    shorten(line),
                )
            )
        seen.setdefault(year, line_no)
        previous = year if previous is None else max(previous, year)
        result.years.append(year)

    if not result.ok:
        return result
    if not result.years:
        result.add(Problem(_("The file has no data under the column names.")))
        return result
    if not result.values:
        result.add(Problem(_("Every value in the file is missing.")))
        return result
    if station_years is not None:
        station = set(station_years)
        result.common = sorted(y for y in result.years if y in station)
        if len(result.common) < MIN_COMMON_YEARS:
            span = (
                _("%(first)s to %(last)s") % {"first": min(station), "last": max(station)}
                if station
                else _("none")
            )
            result.add(
                Problem(
                    ngettext(
                        "Your data (%(first)s to %(last)s) and the station (%(station)s) have "
                        "%(n)s year in common; at least %(min)s are needed. Climpact for R "
                        "stops with: “%(r)s”",
                        "Your data (%(first)s to %(last)s) and the station (%(station)s) have "
                        "%(n)s years in common; at least %(min)s are needed. Climpact for R "
                        "stops with: “%(r)s”",
                        len(result.common),
                    )
                    % {
                        "first": result.years[0],
                        "last": result.years[-1],
                        "station": span,
                        "n": len(result.common),
                        "min": MIN_COMMON_YEARS,
                        "r": R_NO_COMMON_DATA,
                    }
                )
            )
            return result
        missing = len(result.years) - result.values
        if missing:
            result.warnings.append(
                ngettext(
                    "%(n)s year has no value (-99.9 or empty).",
                    "%(n)s years have no value (-99.9 or empty).",
                    missing,
                )
                % {"n": missing}
            )
    result.text = "\n".join(line for _n, line in lines) + "\n"
    return result


def read_sample() -> bytes:
    return SAMPLE_FILE.read_bytes()


def _station_years(summary: dict | None) -> list[int]:
    """The years of the station file, as R's ``group_by(year)`` sees them."""
    return [row["year"] for row in (summary or {}).get("years", [])]


class SectorForm(forms.Form):
    """R's step 4 inputs: the sector file, the plot title, the y-axis label and "Detrend
    data". The file is not required when the sample is chosen (the ``sample`` button)."""

    sector_file = forms.FileField(
        label=gettext_lazy("Sector data file"),
        required=False,
        help_text=gettext_lazy(
            "CSV. A first line Year,<name of your data>, then one line per year. Missing "
            "values are -99.9."
        ),
        widget=forms.ClearableFileInput(attrs={"accept": ACCEPT, "data-sector-file": ""}),
        error_messages={"empty": gettext_lazy("The file is empty.")},
    )
    title = forms.CharField(
        label=gettext_lazy("Title"),
        required=False,
        max_length=200,
        help_text=gettext_lazy("Leave empty to use the station name."),
    )
    y_label = forms.CharField(
        label=gettext_lazy("Label for y axis"),
        required=False,
        max_length=200,
        help_text=gettext_lazy("The name and units of your data, e.g. Wheat yield (t/ha)."),
        widget=forms.TextInput(attrs={"data-sector-label": ""}),
    )
    detrend = forms.BooleanField(
        label=gettext_lazy("Detrend data"),
        required=False,
        initial=True,
        help_text=gettext_lazy("Recommended."),
    )

    def __init__(self, *args, summary: dict | None = None, sample: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.summary = summary
        self.sample = sample
        self.inspection: SectorInspection | None = None
        self.file_name = ""

    def clean(self):
        data = super().clean()
        upload = data.get("sector_file")
        if self.sample:
            raw, self.file_name = read_sample(), SAMPLE_NAME
        elif upload:
            raw, self.file_name = upload.read(), Path(upload.name).name
        else:
            if "sector_file" not in self.errors:
                self.add_error(
                    "sector_file", _("Choose a sector data file, or use the sample data.")
                )
            return data
        self.inspection = inspect_sector_bytes(raw, _station_years(self.summary))
        if not self.inspection.ok:
            # Shown by stations/_problems.html, not as a field error list.
            self.add_error(None, _("The sector file has problems."))
        return data

    def job_params(self, station_name: str) -> dict:
        data = self.cleaned_data
        return {
            "title": data["title"].strip() or station_name,
            "y_label": data["y_label"].strip() or default_y_label(self.file_name),
            "detrend": bool(data["detrend"]),
            "file_name": self.file_name,
            "column": self.inspection.column,
            "years": [self.inspection.years[0], self.inspection.years[-1]],
            "common": len(self.inspection.common),
            "plots": True,
            "zip": True,
        }

    @property
    def text_bytes(self) -> bytes:
        return self.inspection.text.encode("utf-8")
