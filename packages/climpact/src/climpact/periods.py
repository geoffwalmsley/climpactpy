"""Monthly and annual reductions of a daily station series.

xarray's ``resample`` (without the optional flox package) reduces each period through
its own xarray objects, about 0.1 ms per month, which made it most of a station run's
time. These functions group a 1-D daily series by integer period codes and reduce it
with numpy and pandas instead. They return the same periods and labels as
``resample(time=rule)``: every month (``"MS"``) or year (``"YS"``) from the first date's
period to the last date's, labelled by its first day, including periods with no dates.

Only reductions whose result does not depend on the order of the arithmetic are done
here (counts, maximum, minimum), or a Python function applied to each period's values
(:func:`apply`), so results are identical to ``resample``'s.

Every reduction takes values whose last axis runs along the time axis, with any
leading dimensions (the cells of a grid block), and returns ``(..., periods)``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd
import xarray as xr

from climpact.calendars import CalendarDays

RULES = ("MS", "YS")


@dataclass(frozen=True)
class Periods:
    """The period of each day of a daily time axis."""

    codes: np.ndarray  # period number of each day, 0 for the first period
    labels: pd.DatetimeIndex  # first day of each period

    @property
    def size(self) -> int:
        return len(self.labels)

    def wrap(self, values: np.ndarray) -> xr.DataArray:
        """A per-period array as a DataArray with the period labels as ``time``."""
        return xr.DataArray(values, dims="time", coords={"time": self.labels})

    def count(self, flags: np.ndarray) -> np.ndarray:
        """Number of True days in each period (integers), along the last axis."""
        flags = np.asarray(flags, dtype=bool)
        if flags.ndim == 1:
            return np.bincount(self.codes[flags], minlength=self.size)
        lead = flags.shape[:-1]
        rows = flags.reshape(-1, flags.shape[-1])
        row, day = np.nonzero(rows)
        counts = np.bincount(row * self.size + self.codes[day], minlength=rows.shape[0] * self.size)
        return counts.reshape(*lead, self.size)

    def days(self) -> np.ndarray:
        """Number of days of the time axis in each period."""
        return np.bincount(self.codes, minlength=self.size)

    def grouping(self) -> tuple[np.ndarray, np.ndarray]:
        """Days in period order, and where each period starts and ends in that order."""
        order = np.argsort(self.codes, kind="stable")
        return order, np.searchsorted(self.codes[order], np.arange(self.size + 1))

    def reduce(self, values: np.ndarray, stat: str) -> np.ndarray:
        """``"max"`` or ``"min"`` of the non-missing values of each period (NaN if none),
        along the last axis."""
        values = np.asarray(values, dtype=float)
        if values.ndim == 1:
            grouped = pd.Series(values).groupby(self.codes)
            result = getattr(grouped, stat)(skipna=True)
            return result.reindex(range(self.size)).to_numpy(dtype=float)
        order, bounds = self.grouping()
        ufunc = {"max": np.fmax, "min": np.fmin}[stat]  # ignore NaN unless all are
        out = np.full((*values.shape[:-1], self.size), np.nan)
        filled = np.diff(bounds) > 0
        if filled.any():
            with np.errstate(invalid="ignore"):
                reduced = ufunc.reduceat(values[..., order], bounds[:-1][filled], axis=-1)
            out[..., filled] = reduced
        return out

    def first_extreme(self, values: np.ndarray, stat: str) -> np.ndarray:
        """Position in the time axis of the first maximum (``"max"``) or minimum
        (``"min"``) of each period, skipping missing days (R ``which.max`` /
        ``which.min``); -1 for a period with no data. Along the last axis."""
        values = np.asarray(values, dtype=float)
        extreme = self.reduce(values, stat)
        order, bounds = self.grouping()
        days = values[..., order]
        period = self.codes[order]
        with np.errstate(invalid="ignore"):
            hit = days == extreme[..., period]
        position = np.where(hit, order, np.iinfo(np.int64).max)
        out = np.full(extreme.shape, -1, dtype=np.int64)
        filled = np.diff(bounds) > 0
        if filled.any():
            first = np.minimum.reduceat(position, bounds[:-1][filled], axis=-1)
            out[..., filled] = np.where(first == np.iinfo(np.int64).max, -1, first)
        return out

    def apply(self, values: np.ndarray, func: Callable[[np.ndarray], float]) -> np.ndarray:
        """``func`` of the non-missing values of each period, in date order (NaN if none),
        along the last axis (``func`` is called once per period and leading index)."""
        values = np.asarray(values, dtype=float)
        order, bounds = self.grouping()
        lead = values.shape[:-1]
        rows = values.reshape(-1, values.shape[-1])
        out = np.full((rows.shape[0], self.size), np.nan)
        for r, row in enumerate(rows):
            for i in range(self.size):
                period = row[order[bounds[i] : bounds[i + 1]]]
                period = period[~np.isnan(period)]
                if period.size:
                    out[r, i] = func(period)
        return out.reshape(*lead, self.size)


def periods(time: xr.DataArray | pd.DatetimeIndex | np.ndarray, rule: str) -> Periods:
    """Periods (``"MS"`` monthly or ``"YS"`` annual) of a daily time axis.

    For a :class:`~climpact.calendars.CalendarDays` axis (``noleap``, ``360_day``) the
    periods are its months or years and the labels their first days as standard dates,
    which always exist."""
    unit = {"MS": "M", "YS": "Y"}.get(rule)
    if unit is None:
        raise ValueError(f"periods supports 'MS' or 'YS', got {rule!r}")
    if isinstance(time, CalendarDays):
        year, month = time.year.to_numpy(), time.month.to_numpy()
        number = year * 12 + month - 1 if unit == "M" else year
        first, last = int(number.min()), int(number.max())
        codes = np.arange(first, last + 1)
        labels = pd.to_datetime(
            {"year": codes // 12, "month": codes % 12 + 1, "day": 1}
            if unit == "M"
            else {"year": codes, "month": 1, "day": 1}
        )
        return Periods(codes=(number - first).astype(np.intp), labels=pd.DatetimeIndex(labels))
    index = pd.DatetimeIndex(time.values if isinstance(time, xr.DataArray) else time)
    # Periods counted from 1970 in numpy's month or year units.
    number = index.to_numpy().astype(f"datetime64[{unit}]").astype(np.int64)
    first, last = int(number.min()), int(number.max())
    starts = np.arange(first, last + 1).astype(f"datetime64[{unit}]")
    labels = pd.DatetimeIndex(starts.astype(f"datetime64[{index.unit}]"))
    return Periods(codes=(number - first).astype(np.intp), labels=labels)
