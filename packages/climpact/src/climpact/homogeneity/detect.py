"""The built-in homogeneity module ``detect``: break detection (#34).

Climpact R has no homogeneity check. This module looks for likely breaks (artificial
shifts, for example from a station move or a new instrument) in a station's series and
reports them; it does not adjust the data (adjustment is #35), so the indices are
calculated from the data as it is. It is selected with ``--homogeneity detect``
(``ModuleSelection(homogeneity="detect")``); the default module is still ``none``.

Series (:mod:`~climpact.homogeneity.series`): annual and monthly mean TX and TN, and the
log of annual PRCP totals, with the climdex missing-data rules.

Methods, each selectable:

- ``pettitt``: Pettitt's rank test (R ``trend::pettitt.test``), :mod:`.pettitt`;
- ``snht``: the standard normal homogeneity test, absolute form (R ``trend::snh.test``),
  :mod:`.snht`;
- ``pmf``: RHtestsV4's penalised maximal F test (``FindU``, PMFred), which fits a common
  linear trend and needs no reference series, :mod:`.rhtests`;
- ``pmt``: RHtestsV4's penalised maximal t test (``FindU.wRef``, PMTred) on the series'
  anomalies, assuming no trend, :mod:`.rhtests`.

Pettitt and SNHT find one break per test; several are found by binary segmentation
(:mod:`.segmentation`) with segments of at least ``min_years``. RHtests' own search finds
several changepoints. Pettitt and SNHT test monthly series as anomalies from each
calendar month's mean; RHtests removes the annual cycle itself.

Outputs (``<out>/<station>/homogeneity/``):

- ``homogeneity/breaks``: one row per break: the variable, series and method, the last
  period before the break and the first after it, the significance (``yes``; RHtests also
  ``maybe``, significant only if the station history supports it, and ``no``), the test
  statistic, its critical value, the p-value (Pettitt and SNHT), the size of the shift
  (degC, or % of the PRCP total) and the station history events within a year of it;
- ``homogeneity/tests``: one row per series and method: the values tested, the number of
  breaks and possible breaks, a status (``breaks found``, ``no breaks found`` or ``not
  tested``) and why a series was not tested. A run has breaks when any row says ``breaks
  found`` (:func:`breaks_found`).

The station history (option ``station_history``) is a CSV file with the columns ``date``
(``YYYY-MM-DD``, ``YYYY-MM`` or ``YYYY``) and ``event``, and optionally ``station``: then
only the rows whose station is the run's station name are used.
"""

from __future__ import annotations

import csv
import datetime as dt
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from climpact.homogeneity.pettitt import pettitt
from climpact.homogeneity.rhtests import RHtestsError, pmf, pmt
from climpact.homogeneity.segmentation import binary_segmentation
from climpact.homogeneity.series import (
    FREQUENCIES,
    VARIABLES,
    Series,
    anomalies,
    station_series,
)
from climpact.homogeneity.snht import snht
from climpact.io.output_files import FileFormat, with_file_format
from climpact.modules import HomogeneityResult, Option, Tables
from climpact.rnumerics import r_mean
from climpact.station import StationRun

METHODS = ("pettitt", "snht", "pmf", "pmt")
LEVELS = (0.75, 0.8, 0.9, 0.95, 0.99, 0.9999)  # the levels RHtests has critical values for
HISTORY_WINDOW_DAYS = 366  # station history events this close to a break are shown with it

BREAK_COLUMNS = [
    "variable",
    "series",
    "method",
    "last_before",
    "first_after",
    "significance",
    "statistic",
    "critical_value",
    "p_value",
    "shift",
    "units",
    "station_history",
]
TEST_COLUMNS = [
    "variable",
    "series",
    "method",
    "first",
    "last",
    "values",
    "breaks",
    "possible",
    "status",
    "note",
]
BREAKS_FOUND = "breaks found"
NO_BREAKS = "no breaks found"
NOT_TESTED = "not tested"
_SIGNIFICANCE = {"Yes": "yes", "?": "maybe", "No": "no"}


def _subset(allowed: tuple[str, ...]) -> Callable[[str], str]:
    """Check a comma-separated subset of ``allowed``; returns it normalised."""

    def check(value: str) -> str:
        items = [item.strip() for item in value.split(",") if item.strip()]
        for item in items:
            if item not in allowed:
                raise ValueError(f"{item!r} is not one of {', '.join(allowed)}")
        if not items:
            raise ValueError(f"choose at least one of {', '.join(allowed)}")
        return ",".join(dict.fromkeys(items))

    return check


def _at_least_one(value: int) -> int:
    if value < 1:
        raise ValueError(f"expected at least 1, got {value}")
    return value


@dataclass(frozen=True)
class CheckedOption(Option):
    """An :class:`~climpact.modules.Option` whose converted value is also passed through
    ``check``, which returns the value to use or raises ``ValueError``."""

    check: Callable[[Any], Any] | None = None

    def convert(self, value: Any) -> Any:
        value = super().convert(value)
        return value if self.check is None else self.check(value)


@dataclass(frozen=True)
class Event:
    """A station history event."""

    date: dt.date
    text: str


def read_station_history(path: str | Path, station: str) -> list[Event]:
    """The events of ``station`` in a station history file (see the module docstring)."""
    path = Path(path)
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            columns = {(name or "").strip().lower() for name in reader.fieldnames or ()}
            rows = list(reader)
    except FileNotFoundError:
        raise ValueError(f"station history file not found: {path}") from None
    if not {"date", "event"} <= columns:
        raise ValueError(f"{path}: the station history needs the columns date and event")
    events = []
    for line, row in enumerate(rows, start=2):
        if None in row:
            raise ValueError(
                f"{path}, line {line}: more fields than columns (put an event with a comma "
                "in double quotes)"
            )
        row = {k.strip().lower(): (v or "").strip() for k, v in row.items()}
        if "station" in columns and row["station"] != station:
            continue
        events.append(Event(_history_date(row["date"], path, line), row["event"]))
    return sorted(events, key=lambda e: e.date)


def _history_date(text: str, path: Path, line: int) -> dt.date:
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"{path}, line {line}: date {text!r} is not YYYY-MM-DD, YYYY-MM or YYYY")


def _period_start(series: Series, i: int) -> dt.date:
    return dt.date(int(series.years[i]), max(int(series.months[i]), 1), 1)


def _nearby(events: list[Event], series: Series, first_after: int) -> str:
    """The events within :data:`HISTORY_WINDOW_DAYS` of the start of the period after a
    break, as ``date: text`` joined with ``"; "`` (commas become semicolons, since the
    file's fields are not quoted)."""
    at = _period_start(series, first_after)
    near = [e for e in events if abs((e.date - at).days) <= HISTORY_WINDOW_DAYS]
    return "; ".join(f"{e.date.isoformat()}: {e.text.replace(',', ';')}" for e in near)


@dataclass(frozen=True)
class Break:
    """A break found in a series: between the periods at positions ``last_before`` and
    ``first_after`` (the last value before it and the first after it; periods between
    them are missing). ``shift`` is the change of the mean, in the series' units."""

    last_before: int
    first_after: int
    significance: str
    statistic: float
    critical_value: float
    p_value: float
    shift: float


def find_breaks(
    series: Series, method: str, level: float = 0.95, min_years: int = 5
) -> tuple[list[Break] | None, str]:
    """The breaks ``method`` finds in ``series``; ``None`` and the reason when the series
    cannot be tested (too few values for the segmentation, or a series RHtests refuses).

    Pettitt and SNHT split off no segment shorter than ``min_years``; RHtests uses its own
    minimum lengths (10 values for PMF, 5 for PMT)."""
    if method not in METHODS:
        raise ValueError(f"unknown method {method!r} (methods: {', '.join(METHODS)})")
    valid = np.flatnonzero(series.valid)
    if method in ("pettitt", "snht"):
        found = _segmentation_breaks(series, valid, method, level, min_years)
    else:
        found = _rhtests_breaks(series, method, level)
    if isinstance(found, str):
        return None, found
    breaks = []
    for last_before, significance, statistic, critical, p, shift in found:
        first_after = int(valid[np.searchsorted(valid, last_before, side="right")])
        breaks.append(Break(last_before, first_after, significance, statistic, critical, p, shift))
    return breaks, ""


def _segmentation_breaks(
    series: Series, valid: np.ndarray, method: str, level: float, min_years: int
) -> list[tuple] | str:
    """Pettitt or SNHT with binary segmentation, on the series' anomalies."""
    values = anomalies(series)[valid]
    min_n = min_years * series.per_year
    if values.size < 2 * min_n:
        return f"{values.size} values; at least {2 * min_n} are needed"
    test = pettitt if method == "pettitt" else snht
    accepted = sorted(
        (t for t in binary_segmentation(values, test, level, min_n) if t.accepted),
        key=lambda t: t.split,
    )
    bounds = [0, *(t.split for t in accepted), values.size]
    means = [r_mean(values[a:b]) for a, b in zip(bounds[:-1], bounds[1:], strict=True)]
    return [
        (
            int(valid[t.split - 1]),
            "yes",
            t.result.statistic,
            t.result.critical_value,
            t.result.p_value,
            means[i + 1] - means[i],
        )
        for i, t in enumerate(accepted)
    ]


def _rhtests_breaks(series: Series, method: str, level: float) -> list[tuple] | str:
    """RHtests' PMFred or PMTred changepoints."""
    detect = pmf if method == "pmf" else pmt
    try:
        result = detect(series.years, series.months, series.values, level)
    except RHtestsError as exc:
        return f"RHtests: {exc}"
    return [
        (c.position, _SIGNIFICANCE[c.label], c.statistic, c.cv, np.nan, c.step)
        for c in result.changepoints
    ]


def _shift(series: Series, shift: float) -> tuple[float, str]:
    """A shift in the units reported: degC, or the PRCP shift (in log mm) as a % change."""
    if series.variable == "PRCP":
        return 100 * (np.exp(shift) - 1), "%"
    return shift, series.units


def detect_breaks(
    run: StationRun,
    methods: tuple[str, ...] = METHODS,
    variables: tuple[str, ...] = VARIABLES,
    frequencies: tuple[str, ...] = FREQUENCIES,
    level: float = 0.95,
    min_years: int = 5,
    history: list[Event] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The breaks and tests tables (see the module docstring) for ``run``."""
    if level not in LEVELS:
        raise ValueError(f"level must be one of {', '.join(map(str, LEVELS))}")
    history = history or []
    break_rows: list[dict[str, Any]] = []
    test_rows: list[dict[str, Any]] = []
    order = [m for m in METHODS if m in methods]
    for series in station_series(run, tuple(variables), tuple(frequencies)):
        valid = np.flatnonzero(series.valid)
        for method in order:
            breaks, note = find_breaks(series, method, level, min_years)
            test_rows.append(_test_row(series, method, valid, breaks, note))
            for b in breaks or ():
                shift, units = _shift(series, b.shift)
                break_rows.append(
                    {
                        "variable": series.variable,
                        "series": series.freq,
                        "method": method,
                        "last_before": series.label(b.last_before),
                        "first_after": series.label(b.first_after),
                        "significance": b.significance,
                        "statistic": b.statistic,
                        "critical_value": b.critical_value,
                        "p_value": b.p_value,
                        "shift": shift,
                        "units": units,
                        "station_history": _nearby(history, series, b.first_after),
                    }
                )
    breaks = pd.DataFrame(break_rows, columns=BREAK_COLUMNS)
    tests = pd.DataFrame(test_rows, columns=TEST_COLUMNS)
    return breaks, tests


def _test_row(series: Series, method: str, valid: np.ndarray, breaks, note: str) -> dict:
    tested = breaks is not None
    found = sum(b.significance == "yes" for b in breaks) if tested else np.nan
    possible = sum(b.significance == "maybe" for b in breaks) if tested else np.nan
    if not tested:
        status = NOT_TESTED
    else:
        status = BREAKS_FOUND if found else NO_BREAKS
    return {
        "variable": series.variable,
        "series": series.freq,
        "method": method,
        "first": series.label(valid[0]) if valid.size else "",
        "last": series.label(valid[-1]) if valid.size else "",
        "values": int(valid.size),
        "breaks": found,
        "possible": possible,
        "status": status,
        "note": note.replace(",", ";"),
    }


def breaks_found(tables: Mapping[str, pd.DataFrame]) -> bool:
    """True when the ``detect`` module's tests table reports a break in any series."""
    tests = tables.get("homogeneity/tests")
    return tests is not None and bool((tests["status"] == BREAKS_FOUND).any())


def summary(tests: pd.DataFrame) -> str:
    """One line for the command line: which tests found breaks."""
    found = tests[tests["status"] == BREAKS_FOUND]
    untested = int((tests["status"] == NOT_TESTED).sum())
    if found.empty:
        text = f"no breaks found by {len(tests) - untested} tests"
    else:
        series = ", ".join(
            f"{row.variable} {row.series} ({row.method})" for row in found.itertuples()
        )
        text = f"breaks found by {len(found)} of {len(tests) - untested} tests: {series}"
    if untested:
        text += f"; {untested} not tested"
    return text


_BREAKS_FORMAT = FileFormat(
    "Candidate breaks found by homogeneity tests (detection only: the data are not adjusted)",
    sep=",",
    na="NA",
)
_TESTS_FORMAT = FileFormat(
    "Homogeneity tests run on each series, and the breaks they found", sep=",", na="NA"
)


class BreakDetection:
    """The built-in ``detect`` homogeneity module: finds breaks, leaves the data unchanged."""

    name = "detect"
    options = (
        CheckedOption(
            "methods",
            str,
            ",".join(METHODS),
            "tests to run, comma-separated: pettitt, snht, pmf, pmt",
            check=_subset(METHODS),
        ),
        CheckedOption(
            "variables",
            str,
            ",".join(VARIABLES),
            "variables to test, comma-separated: TX, TN, PRCP (PRCP annual only)",
            check=_subset(VARIABLES),
        ),
        CheckedOption(
            "series",
            str,
            ",".join(FREQUENCIES),
            "series to test, comma-separated: annual, monthly",
            check=_subset(FREQUENCIES),
        ),
        Option("level", float, 0.95, "confidence level of the tests", choices=LEVELS),
        CheckedOption(
            "min_years",
            int,
            5,
            "shortest segment Pettitt and SNHT split off, in years",
            check=_at_least_one,
        ),
        Option(
            "station_history",
            str,
            "",
            "CSV file of station history events (date, event, optional station), shown "
            "next to breaks within a year of them",
        ),
    )

    def homogenise(
        self, run: StationRun, tables: Tables, options: Mapping[str, Any] | None = None
    ) -> HomogeneityResult:
        options = {o.name: o.default for o in self.options} | dict(options or {})
        history = (
            read_station_history(options["station_history"], run.metadata.name)
            if options["station_history"]
            else []
        )
        breaks, tests = detect_breaks(
            run,
            methods=tuple(options["methods"].split(",")),
            variables=tuple(options["variables"].split(",")),
            frequencies=tuple(options["series"].split(",")),
            level=options["level"],
            min_years=options["min_years"],
            history=history,
        )
        return HomogeneityResult(
            tables={
                "homogeneity/breaks": with_file_format(breaks, _BREAKS_FORMAT),
                "homogeneity/tests": with_file_format(tests, _TESTS_FORMAT),
            }
        )


DETECT = BreakDetection()
