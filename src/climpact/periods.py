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
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd
import xarray as xr

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
        """Number of True days in each period (integers)."""
        flags = np.asarray(flags, dtype=bool)
        return np.bincount(self.codes[flags], minlength=self.size)

    def days(self) -> np.ndarray:
        """Number of days of the time axis in each period."""
        return np.bincount(self.codes, minlength=self.size)

    def reduce(self, values: np.ndarray, stat: str) -> np.ndarray:
        """``"max"`` or ``"min"`` of the non-missing values of each period (NaN if none)."""
        grouped = pd.Series(np.asarray(values, dtype=float)).groupby(self.codes)
        result = getattr(grouped, stat)(skipna=True)
        return result.reindex(range(self.size)).to_numpy(dtype=float)

    def apply(self, values: np.ndarray, func: Callable[[np.ndarray], float]) -> np.ndarray:
        """``func`` of the non-missing values of each period, in date order (NaN if none)."""
        values = np.asarray(values, dtype=float)
        order = np.argsort(self.codes, kind="stable")
        bounds = np.searchsorted(self.codes[order], np.arange(self.size + 1))
        out = np.full(self.size, np.nan)
        for i in range(self.size):
            period = values[order[bounds[i] : bounds[i + 1]]]
            period = period[~np.isnan(period)]
            if period.size:
                out[i] = func(period)
        return out


def periods(time: xr.DataArray | pd.DatetimeIndex | np.ndarray, rule: str) -> Periods:
    """Periods (``"MS"`` monthly or ``"YS"`` annual) of a daily time axis."""
    index = pd.DatetimeIndex(time.values if isinstance(time, xr.DataArray) else time)
    # Periods counted from 1970 in numpy's month or year units.
    unit = {"MS": "M", "YS": "Y"}.get(rule)
    if unit is None:
        raise ValueError(f"periods supports 'MS' or 'YS', got {rule!r}")
    number = index.to_numpy().astype(f"datetime64[{unit}]").astype(np.int64)
    first, last = int(number.min()), int(number.max())
    starts = np.arange(first, last + 1).astype(f"datetime64[{unit}]")
    labels = pd.DatetimeIndex(starts.astype(f"datetime64[{index.unit}]"))
    return Periods(codes=(number - first).astype(np.intp), labels=labels)
