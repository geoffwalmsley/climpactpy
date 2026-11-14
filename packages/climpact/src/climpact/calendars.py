"""Daily time axes in the CF calendars without leap years: ``noleap`` (``365_day``)
and ``360_day``.

Climate model output often uses them. Climpact's gridded code reads them as PCICt
dates, and climdex.pcic then works with ``dpy`` days per year (``attr(ts, "dpy")``):
365 or 360 day-of-year thresholds, years that end on the last day of December of the
calendar (``get.last.monthday.of.year``: 30 December for ``360_day``), and day numbers
``1..dpy`` (``as.POSIXlt(dates)$yday + 1``).

A :class:`CalendarDays` stands in for the :class:`pandas.DatetimeIndex` the index code
works with, since such dates (30 February) cannot be held by one. It has the parts of
its interface that code uses: ``year``, ``month``, ``day``, ``day_of_year``, the size,
indexing and slicing, and :meth:`CalendarDays.get_indexer`. Standard-calendar data
keep using a ``DatetimeIndex``, so nothing changes for them; the helpers here accept
either.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
import xarray as xr

# CF calendar names, by the canonical name used here.
CALENDAR_NAMES = {
    "noleap": {"noleap", "365_day"},
    "360_day": {"360_day"},
}
STANDARD_CALENDARS = {"standard", "gregorian", "proleptic_gregorian"}
DAYS_PER_YEAR = {"noleap": 365, "360_day": 360}
_MONTH_LENGTHS = {
    "noleap": np.array([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]),
    "360_day": np.full(12, 30),
}


def canonical_calendar(name: str | None) -> str | None:
    """``"noleap"`` or ``"360_day"`` for those calendars (any CF spelling), None for the
    standard calendar (or no calendar attribute); raises ``NotImplementedError`` for
    any other (``all_leap``, ``julian``)."""
    if name is None:
        return None
    key = str(name).strip().lower()
    if key in STANDARD_CALENDARS:
        return None
    for canonical, names in CALENDAR_NAMES.items():
        if key in names:
            return canonical
    raise NotImplementedError(f"the {name!r} calendar is not supported")


@dataclass(frozen=True)
class CalendarDate:
    """One date of a :class:`CalendarDays`."""

    year: int
    month: int
    day: int

    def __str__(self) -> str:
        return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"

    def __format__(self, spec: str) -> str:
        """``%Y``, ``%m`` and ``%d`` as ``strftime``; no spec gives ``YYYY-MM-DD``."""
        if not spec:
            return str(self)
        return (
            spec.replace("%Y", f"{self.year:04d}")
            .replace("%m", f"{self.month:02d}")
            .replace("%d", f"{self.day:02d}")
        )


class CalendarDays:
    """A daily time axis in the ``noleap`` or ``360_day`` calendar (see the module)."""

    __slots__ = ("calendar", "_year", "_month", "_day")

    def __init__(self, calendar: str, year, month, day):
        self.calendar = calendar
        self._year = np.asarray(year, dtype=np.int64)
        self._month = np.asarray(month, dtype=np.int64)
        self._day = np.asarray(day, dtype=np.int64)

    @classmethod
    def whole_years(cls, calendar: str, first: int, last: int) -> CalendarDays:
        """Every day from 1 January of ``first`` to the last day of ``last``."""
        dpy = DAYS_PER_YEAR[calendar]
        lengths = _MONTH_LENGTHS[calendar]
        month = np.repeat(np.arange(1, 13), lengths)
        day = np.concatenate([np.arange(1, n + 1) for n in lengths])
        years = np.arange(first, last + 1)
        return cls(
            calendar,
            np.repeat(years, dpy),
            np.tile(month, years.size),
            np.tile(day, years.size),
        )

    @classmethod
    def from_cftime(cls, dates: Sequence, calendar: str) -> CalendarDays:
        """From cftime dates (truncated to days)."""
        return cls(
            calendar,
            [d.year for d in dates],
            [d.month for d in dates],
            [d.day for d in dates],
        )

    @property
    def dpy(self) -> int:
        return DAYS_PER_YEAR[self.calendar]

    @property
    def year(self) -> pd.Index:
        return pd.Index(self._year)

    @property
    def month(self) -> pd.Index:
        return pd.Index(self._month)

    @property
    def day(self) -> pd.Index:
        return pd.Index(self._day)

    @property
    def day_of_year(self) -> pd.Index:
        """1 to :attr:`dpy` (climdex.pcic ``get.jdays``)."""
        start = np.concatenate([[0], np.cumsum(_MONTH_LENGTHS[self.calendar])[:-1]])
        return pd.Index(start[self._month - 1] + self._day)

    @property
    def ordinal(self) -> np.ndarray:
        """Days since 1 January of year 0 in the calendar."""
        return self._year * self.dpy + self.day_of_year.to_numpy() - 1

    @property
    def size(self) -> int:
        return self._year.size

    def __len__(self) -> int:
        return self.size

    def __getitem__(self, key):
        if isinstance(key, (int, np.integer)):
            return CalendarDate(int(self._year[key]), int(self._month[key]), int(self._day[key]))
        return CalendarDays(self.calendar, self._year[key], self._month[key], self._day[key])

    def __repr__(self) -> str:
        if not self.size:
            return f"CalendarDays({self.calendar!r}, empty)"
        return f"CalendarDays({self.calendar!r}, {self[0]} .. {self[-1]}, {self.size} days)"

    def get_indexer(self, target: CalendarDays) -> np.ndarray:
        """Position of each date of ``target`` in this axis, -1 where absent."""
        return pd.Index(self.ordinal).get_indexer(target.ordinal)

    def equals(self, other) -> bool:
        return (
            isinstance(other, CalendarDays)
            and other.calendar == self.calendar
            and np.array_equal(other.ordinal, self.ordinal)
        )

    @property
    def is_unique(self) -> bool:
        return pd.Index(self.ordinal).is_unique

    def days_since(self, origin: CalendarDate) -> np.ndarray:
        """Days from ``origin`` (a date of the same calendar) to each date, as float."""
        o = CalendarDays(self.calendar, [origin.year], [origin.month], [origin.day])
        return (self.ordinal - o.ordinal[0]).astype(float)


DayAxis = pd.DatetimeIndex | CalendarDays


def as_days(time) -> DayAxis:
    """``time`` as a :class:`CalendarDays` (unchanged) or a ``DatetimeIndex``."""
    if isinstance(time, CalendarDays):
        return time
    return pd.DatetimeIndex(time.values if isinstance(time, xr.DataArray) else time)


def calendar_of(time) -> str | None:
    """The calendar of a day axis: ``"noleap"``, ``"360_day"``, or None (standard)."""
    return time.calendar if isinstance(time, CalendarDays) else None


def days_per_year(calendar: str | None) -> int:
    """climdex.pcic's ``dpy``: 365 for the standard calendar (29 February dropped)."""
    return 365 if calendar is None else DAYS_PER_YEAR[calendar]


def whole_years(time) -> DayAxis:
    """1 January of the first year of ``time`` to the last day of its last year
    (climdex.pcic's ``date.series``), in its calendar."""
    time = as_days(time)
    if isinstance(time, CalendarDays):
        return CalendarDays.whole_years(time.calendar, time[0].year, time[-1].year)
    return pd.date_range(f"{time[0].year}-01-01", f"{time[-1].year}-12-31", freq="D")


def year_range(calendar: str | None, first: int, last: int) -> DayAxis:
    """Every day of the years ``first`` to ``last`` in ``calendar``."""
    if calendar is None:
        return pd.date_range(f"{first}-01-01", f"{last}-12-31", freq="D")
    return CalendarDays.whole_years(calendar, first, last)


__all__ = [
    "CalendarDate",
    "CalendarDays",
    "DayAxis",
    "as_days",
    "calendar_of",
    "canonical_calendar",
    "days_per_year",
    "whole_years",
    "year_range",
]
