"""Base-period percentile thresholds, as climdex.pcic and Climpact compute them.

Temperature thresholds are day-of-year percentiles over a window of days centred on
each calendar day, pooled across the base-period years (climdex.pcic
``get.outofbase.quantiles`` / ``zhang.running.qtile`` and the C++
``running_quantile_windowed``). Precipitation thresholds are percentiles of the
base-period wet days (``get.prec.var.quantiles``, R ``quantile(type = 8)``).

The R behaviour reproduced here, all of which affects results:

- The base period is a 365-day year: 29 February is dropped (``get.bootstrap.set``).
- The window wraps around **within the same year**: the window for 1 January takes
  30-31 December of the same year, not of the previous year (``(day + dpy) % dpy`` in
  the C++ code).
- Temperature percentiles use climdex's own C++ ``c_quantile``. It is R's type 8 but
  computed in 0-based arithmetic, with a slightly different fuzz test, and it
  interpolates even between equal neighbours, so it is not bit-identical to R's
  ``quantile(type = 8)``. Precipitation percentiles use R's ``quantile(type = 8)``.
- A day's percentile is missing when fewer than ``min_fraction`` of the window's
  values are present.

The results are computed once per station and cached on the
:class:`~climpact.station.StationRun` (``run.thresholds``). Index code looks up the
threshold for each day of a series with :meth:`Thresholds.daily`. Inside the base
period, the percentile indices use the bootstrapped thresholds of
:meth:`Thresholds.inbase` (climdex.pcic ``running_quantile_windowed_bootstrap``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import xarray as xr

DAYS_PER_YEAR = 365
TEMPERATURE_QUANTILES = (0.05, 0.1, 0.5, 0.9, 0.95)  # Climpact temp.quantiles
PRECIPITATION_QUANTILES = (0.05, 0.1, 0.5, 0.9, 0.95, 0.99)  # Climpact prec.quantiles
TEMPERATURE_WINDOW = 5  # climdex.pcic default n
HEATWAVE_WINDOW = 15  # Climpact climdex.hw
HEATWAVE_QUANTILE = 0.9
MIN_BASE_FRACTION = 0.1  # min.base.data.fraction.present
WET_DAY = 1.0  # mm; wet days for precipitation percentiles
# climdex.pcic refuses to compute thresholds with this many base-period days or fewer.
MIN_BASE_DAYS = 359
TEMPERATURE_VARIABLES = ("tasmax", "tasmin", "tas")

_TYPE8 = 1.0 / 3.0  # a = b = 1/3 for R's quantile type 8
_FUZZ = 4 * np.finfo(float).eps


def quantile_name(q: float) -> str:
    """R's name for a quantile: ``paste("q", q * 100, sep = "")``, e.g. ``q95``."""
    value = q * 100
    return f"q{int(value)}" if float(value).is_integer() else f"q{value:.15g}"


# --- quantile definitions ------------------------------------------------------------


def _c_quantile_positions(n: np.ndarray, q: float):
    """Positions of the two values ``c_quantile`` interpolates between, and the weight.

    ``n`` is the number of values. Returns ``(left, right, h)`` with 0-based positions
    clipped to the values, as the C++ does.
    """
    a = b = _TYPE8
    # C++: a + quantile * (n + 1 - a - b) - 1, with n + 1 an integer
    nppm = a + q * ((n + 1).astype(float) - a - b) - 1
    j = np.floor(nppm + _FUZZ)
    h = np.where(np.abs(nppm - j) <= _FUZZ, 0.0, nppm - j)
    last = np.maximum(n - 1, 0)
    ji = j.astype(np.int64)
    return np.clip(ji, 0, last), np.clip(ji + 1, 0, last), h


def _c_quantile_combine(n, left, right, first, h) -> np.ndarray:
    """``c_quantile``'s result from the values at its two positions (``first`` is the
    smallest value, returned when ``n == 1``)."""
    with np.errstate(invalid="ignore"):
        interp = (1 - h) * left + h * right
    out = np.where(h == 1, right, np.where(h == 0, left, interp))
    out = np.where(n == 1, first, out)
    return np.where(n == 0, np.nan, out)


def climdex_quantile_sorted(rows: np.ndarray, counts: np.ndarray, q: float) -> np.ndarray:
    """climdex.pcic's C++ ``c_quantile`` for each row of ``rows``.

    Each row holds its ``counts[i]`` values sorted in ascending order at the start
    (anything after them is ignored). Rows with no values give NaN. The arithmetic
    follows the C++ exactly so that results are bit-identical.
    """
    rows = np.atleast_2d(np.asarray(rows, dtype=float))
    n = np.asarray(counts, dtype=np.int64).reshape(-1)
    if not 0 <= q <= 1:
        return np.full(n.shape, np.nan)
    left_idx, right_idx, h = _c_quantile_positions(n, q)
    r = np.arange(rows.shape[0])
    return _c_quantile_combine(n, rows[r, left_idx], rows[r, right_idx], rows[:, 0], h)


def climdex_quantile(values, q: float) -> float:
    """climdex.pcic ``climdex.quantile`` (C++ ``c_quantile``) of the non-missing values."""
    x = np.sort(np.asarray(values, dtype=float).ravel())
    x = x[~np.isnan(x)]
    if x.size == 0:
        return float("nan")
    return float(climdex_quantile_sorted(x[np.newaxis, :], np.array([x.size]), q)[0])


def r_quantile_type8(values, probs) -> np.ndarray:
    """R ``quantile(x, probs, type = 8)`` of the non-missing values of ``x``.

    Follows ``quantile.default`` in R 4.6.1 (the reference version), including its
    fuzz tests and its use of the lower value (without interpolating) when both
    neighbours are equal.
    """
    x = np.sort(np.asarray(values, dtype=float).ravel())
    x = x[~np.isnan(x)]
    n = x.size
    probs = np.atleast_1d(np.asarray(probs, dtype=float))
    if n == 0:
        return np.full(probs.shape, np.nan)
    a = b = _TYPE8
    nppm = a + probs * (float(n + 1) - a - b)
    j = np.floor(nppm * (1 + _FUZZ))  # R >= 4.4 floorF(); climdex's C++ adds the fuzz
    h = nppm - j
    h = np.where(np.abs(h) < _FUZZ, 0.0, h)
    ji = j.astype(np.int64)
    # R pads x as c(x[1], x[1], x, x[n], x[n]) and takes x[j + 2] and x[j + 3] (1-based)
    lo = x[np.clip(ji - 1, 0, n - 1)]
    hi = x[np.clip(ji, 0, n - 1)]
    out = np.where(h == 1, hi, lo)
    other = (h > 0) & (h < 1) & (lo != hi)
    return np.where(other, (1 - h) * lo + h * hi, out)


# --- base period and day of year -------------------------------------------------------


def day_of_year(time) -> np.ndarray:
    """climdex.pcic ``jdays`` (``get.jdays.replaced.feb29``): day of year 1-365 for every
    date, where 29 February shares 28 February's day (59) and later days of a leap year
    are shifted back by one."""
    index = pd.DatetimeIndex(time.values if isinstance(time, xr.DataArray) else time)
    doy = index.day_of_year.to_numpy().copy()
    shift = index.is_leap_year & (doy >= 60)
    feb29 = index.is_leap_year & (doy == 60)
    doy[shift] -= 1
    doy[feb29] = 59
    return doy


def base_period_matrix(da: xr.DataArray, base_start: int, base_end: int) -> np.ndarray:
    """Base-period values as a ``(years, 365)`` array, without 29 February.

    Days of the base period outside the data are missing (``create.filled.series``).
    """
    dates = pd.date_range(f"{base_start}-01-01", f"{base_end}-12-31", freq="D")
    dates = dates[~((dates.month == 2) & (dates.day == 29))]
    series = da.to_series().reindex(dates)
    return series.to_numpy(dtype=float).reshape(-1, DAYS_PER_YEAR)


def window_values(base: np.ndarray, window: int) -> np.ndarray:
    """Values in the ``window``-day window around each calendar day, for each year.

    Returns an array of shape ``(365, years, window)``. As in climdex.pcic's C++, the
    window wraps around within the same year: day 1's window includes days 364 and 365
    of the same year.
    """
    half = window // 2
    days = (np.arange(DAYS_PER_YEAR)[:, None] + np.arange(-half, half + 1)[None, :]) % (
        DAYS_PER_YEAR
    )
    return np.transpose(base[:, days], (1, 0, 2))  # base[:, days] is (years, 365, window)


def running_quantiles(
    base: np.ndarray,
    window: int,
    quantiles,
    min_fraction: float = MIN_BASE_FRACTION,
) -> dict[float, np.ndarray]:
    """climdex.pcic ``running_quantile_windowed``: each quantile for each calendar day.

    ``base`` is a ``(years, 365)`` matrix from :func:`base_period_matrix`. Returns
    ``{q: array of 365}``; a day is missing when fewer than ``min_fraction`` of its
    ``years * window`` values are present.
    """
    values = window_values(base, window).reshape(DAYS_PER_YEAR, -1)
    slab = values.shape[1]
    rows = np.sort(values, axis=1)  # NaN sorts last
    counts = np.count_nonzero(~np.isnan(values), axis=1)
    enough = counts / slab >= min_fraction
    out = {}
    for q in quantiles:
        result = climdex_quantile_sorted(rows, counts, q)
        out[q] = np.where(enough, result, np.nan)
    return out


def bootstrap_quantiles(
    base: np.ndarray,
    window: int,
    quantiles,
    min_fraction: float = MIN_BASE_FRACTION,
) -> dict[float, np.ndarray]:
    """climdex.pcic ``running_quantile_windowed_bootstrap``: in-base thresholds.

    The Zhang et al. (2005) bootstrap. For each calendar day, base year ``rm`` and
    other base year ``dup``, the window values of year ``rm`` are replaced by a second
    copy of year ``dup``'s, and the quantile is taken of the result. Returns
    ``{q: array (365, years, years - 1)}``, indexed ``[day, rm, k]`` where ``k`` runs
    over the other years in increasing order (as R's ``dim(d) <- c(dpy, nyears,
    nyears - 1, nq)``). A threshold is missing when fewer than ``min_fraction`` of the
    window's ``years * window`` values remain.

    The replaced sample is never built. The C++ sorts the window values once and then
    drops or duplicates elements in place, so the replaced sample is the sorted values
    with weights 0 (year ``rm``), 2 (year ``dup``) or 1. The value at position ``p`` of
    the replaced sample is the first sorted value whose cumulative weight exceeds ``p``.
    """
    nyears = base.shape[0]
    slab = window * nyears
    pairs = [(rm, dup) for rm in range(nyears) for dup in range(nyears) if dup != rm]
    rm_idx = np.array([p[0] for p in pairs])
    dup_idx = np.array([p[1] for p in pairs])
    out = {q: np.full((DAYS_PER_YEAR, len(pairs)), np.nan) for q in quantiles}

    windows = window_values(base, window)  # (365, years, window)
    year_of = np.repeat(np.arange(nyears), window)
    for day in range(DAYS_PER_YEAR):
        values = windows[day].reshape(-1)
        present = ~np.isnan(values)
        order = np.argsort(values[present], kind="stable")
        data = values[present][order]
        years = year_of[present][order]
        size = data.size
        if size == 0:
            continue
        # cum[y, i]: values of year y among the first i + 1 sorted values
        cum = np.cumsum(years[None, :] == np.arange(nyears)[:, None], axis=1, dtype=np.int32)
        weight = np.arange(1, size + 1, dtype=np.int32)[None, :] - cum[rm_idx] + cum[dup_idx]
        n = size - cum[rm_idx, -1] + cum[dup_idx, -1]
        enough = n / slab >= min_fraction
        for q in quantiles:
            left_pos, right_pos, h = _c_quantile_positions(n, q)
            left = data[np.minimum((weight <= left_pos[:, None]).sum(axis=1), size - 1)]
            right = data[np.minimum((weight <= right_pos[:, None]).sum(axis=1), size - 1)]
            first = data[np.minimum((weight <= 0).sum(axis=1), size - 1)]
            result = _c_quantile_combine(n, left, right, first, h)
            out[q][day] = np.where(enough, result, np.nan)
    return {q: v.reshape(DAYS_PER_YEAR, nyears, nyears - 1) for q, v in out.items()}


# --- thresholds for a station ------------------------------------------------------------


class InsufficientBaseData(ValueError):
    """Raised when there is too little base-period data to compute thresholds."""


@dataclass(frozen=True)
class Thresholds:
    """Base-period thresholds for one station.

    ``temperature[var][q]`` and ``heatwave[var]`` are arrays of 365 day-of-year values
    for ``var`` in ``tasmax``, ``tasmin``, ``tas``; ``precipitation[q]`` is a number.
    ``base[var]`` holds the ``(years, 365)`` base-period data the temperature
    thresholds were computed from; :meth:`inbase` bootstraps it for the in-base years.
    """

    base_start: int
    base_end: int
    temperature: dict[str, dict[float, np.ndarray]]
    precipitation: dict[float, float]
    heatwave: dict[str, np.ndarray]
    base: dict[str, np.ndarray] = field(repr=False)
    window: int = TEMPERATURE_WINDOW
    _inbase: dict = field(default_factory=dict, init=False, repr=False, compare=False)

    def outbase(self, var: str, q: float) -> np.ndarray:
        """Day-of-year thresholds used outside the base period (365 values)."""
        return self.temperature[var][q]

    def inbase(self, var: str, q: float) -> np.ndarray:
        """Bootstrapped thresholds used inside the base period, ``(365, years, years - 1)``
        (see :func:`bootstrap_quantiles`). Computed on first use and cached."""
        key = (var, q)
        if key not in self._inbase:
            self._inbase[key] = bootstrap_quantiles(self.base[var], self.window, [q])[q]
        return self._inbase[key]

    def daily(self, var: str, q: float, time) -> xr.DataArray:
        """The threshold for each date of ``time`` (climdex ``thresholds[jdays]``)."""
        values = self.outbase(var, q)[day_of_year(time) - 1]
        index = time.values if isinstance(time, xr.DataArray) else time
        return xr.DataArray(values, dims="time", coords={"time": index})


def _days_in_base(first: pd.Timestamp, last: pd.Timestamp, base_start: int, base_end: int):
    start = max(first, pd.Timestamp(f"{base_start}-01-01"))
    end = min(last, pd.Timestamp(f"{base_end}-12-31"))
    return max((end - start).days + 1, 0)


def compute_thresholds(ds: xr.Dataset, base_start: int, base_end: int) -> Thresholds:
    """Compute every base-period threshold Climpact uses for a station Dataset.

    Raises :class:`InsufficientBaseData` when the station's dates cover
    ``MIN_BASE_DAYS`` days of the base period or fewer, as climdex.pcic does.
    """
    first = pd.Timestamp(ds.attrs.get("first_date", ds.time.values[0]))
    last = pd.Timestamp(ds.attrs.get("last_date", ds.time.values[-1]))
    if _days_in_base(first, last, base_start, base_end) <= MIN_BASE_DAYS:
        raise InsufficientBaseData(
            f"less than a year of data within the base period {base_start}-{base_end}"
        )

    base = {v: base_period_matrix(ds[v], base_start, base_end) for v in TEMPERATURE_VARIABLES}
    temperature = {
        v: running_quantiles(base[v], TEMPERATURE_WINDOW, TEMPERATURE_QUANTILES)
        for v in TEMPERATURE_VARIABLES
    }
    heatwave = {
        v: running_quantiles(base[v], HEATWAVE_WINDOW, [HEATWAVE_QUANTILE])[HEATWAVE_QUANTILE]
        for v in TEMPERATURE_VARIABLES
    }

    pr = ds.pr
    years = pr.time.dt.year
    in_base = (years >= base_start) & (years <= base_end) & (pr >= WET_DAY)
    wet = pr.values[in_base.values]
    prec = r_quantile_type8(wet, PRECIPITATION_QUANTILES)
    precipitation = dict(zip(PRECIPITATION_QUANTILES, (float(v) for v in prec), strict=True))

    return Thresholds(
        base_start=base_start,
        base_end=base_end,
        temperature=temperature,
        precipitation=precipitation,
        heatwave=heatwave,
        base=base,
    )


__all__ = [
    "InsufficientBaseData",
    "Thresholds",
    "base_period_matrix",
    "bootstrap_quantiles",
    "climdex_quantile",
    "climdex_quantile_sorted",
    "compute_thresholds",
    "day_of_year",
    "quantile_name",
    "r_quantile_type8",
    "running_quantiles",
    "window_values",
]
