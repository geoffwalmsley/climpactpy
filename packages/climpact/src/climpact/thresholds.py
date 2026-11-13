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
# Quantiles used inside the base period (tx10p, txgt50p, tx90p, tn10p, tn90p).
INBASE_QUANTILES = {"tasmax": (0.1, 0.5, 0.9), "tasmin": (0.1, 0.9)}
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


def _sorted_rows(values) -> tuple[np.ndarray, np.ndarray]:
    """Each row of ``values`` (the last axis) sorted with missing values last, and the
    number of non-missing values in each row."""
    x = np.sort(np.asarray(values, dtype=float), axis=-1)  # NaN sorts last
    return x, np.count_nonzero(~np.isnan(x), axis=-1)


def _take_rows(x: np.ndarray, index: np.ndarray) -> np.ndarray:
    return np.take_along_axis(x, index[..., np.newaxis], axis=-1)[..., 0]


def r_quantile_type8_rows(values, prob: float) -> np.ndarray:
    """R ``quantile(x, prob, type = 8, na.rm = TRUE)`` along the last axis of ``values``.

    Follows ``quantile.default`` in R 4.6.1 (the reference version), including its
    fuzz tests and its use of the lower value (without interpolating) when both
    neighbours are equal. Rows with no values give NaN.
    """
    x, n = _sorted_rows(values)
    if x.shape[-1] == 0:
        return np.full(n.shape, np.nan)
    a = b = _TYPE8
    nppm = a + prob * ((n + 1).astype(float) - a - b)
    j = np.floor(nppm * (1 + _FUZZ))  # R >= 4.4 floorF(); climdex's C++ adds the fuzz
    h = nppm - j
    h = np.where(np.abs(h) < _FUZZ, 0.0, h)
    ji = j.astype(np.int64)
    # R pads x as c(x[1], x[1], x, x[n], x[n]) and takes x[j + 2] and x[j + 3] (1-based)
    last = np.maximum(n - 1, 0)
    lo = _take_rows(x, np.clip(ji - 1, 0, last))
    hi = _take_rows(x, np.clip(ji, 0, last))
    out = np.where(h == 1, hi, lo)
    other = (h > 0) & (h < 1) & (lo != hi)
    with np.errstate(invalid="ignore"):
        out = np.where(other, (1 - h) * lo + h * hi, out)
    return np.where(n == 0, np.nan, out)


def r_quantile_type8(values, probs) -> np.ndarray:
    """R ``quantile(x, probs, type = 8)`` of the non-missing values of ``x`` (see
    :func:`r_quantile_type8_rows`)."""
    x = np.asarray(values, dtype=float).ravel()
    probs = np.atleast_1d(np.asarray(probs, dtype=float))
    return np.array([float(r_quantile_type8_rows(x, p)) for p in probs])


def r_quantile_type7_rows(values, prob: float) -> np.ndarray:
    """R ``quantile(x, prob, na.rm = TRUE)`` (type 7) along the last axis of ``values``,
    as ``quantile.default`` computes it: ``(1 - h) * x[lo] + h * x[hi]``, and ``x[lo]``
    when the neighbours are equal. Rows with no values give NaN."""
    x, n = _sorted_rows(values)
    if x.shape[-1] == 0:
        return np.full(n.shape, np.nan)
    index = 1 + (np.maximum(n, 1) - 1) * prob
    lo = np.floor(index).astype(np.int64)
    hi = np.ceil(index).astype(np.int64)
    qs = _take_rows(x, lo - 1)
    upper = _take_rows(x, hi - 1)
    h = index - lo
    interpolate = (index > lo) & (upper != qs)
    with np.errstate(invalid="ignore"):
        qs = np.where(interpolate, (1 - h) * qs + h * upper, qs)
    return np.where(n == 0, np.nan, qs)


def r_quantile_type7(values: np.ndarray, prob: float) -> float:
    """R ``quantile(x, prob, na.rm = TRUE)`` (type 7) of the values (see
    :func:`r_quantile_type7_rows`)."""
    return float(r_quantile_type7_rows(np.asarray(values, dtype=float).ravel(), prob))


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


def base_period_dates(base_start: int, base_end: int) -> pd.DatetimeIndex:
    """The days of the base period without 29 February (``get.bootstrap.set``)."""
    dates = pd.date_range(f"{base_start}-01-01", f"{base_end}-12-31", freq="D")
    return dates[~((dates.month == 2) & (dates.day == 29))]


def take_dates(values: np.ndarray, time, dates: pd.DatetimeIndex) -> np.ndarray:
    """The values on ``dates`` (last axis of ``values`` runs along ``time``), missing
    where a date is not in ``time`` (``create.filled.series``)."""
    index = pd.DatetimeIndex(time.values if isinstance(time, xr.DataArray) else time)
    pos = index.get_indexer(dates)
    out = np.take(np.asarray(values, dtype=float), np.maximum(pos, 0), axis=-1)
    out[..., pos < 0] = np.nan
    return out


def base_period_matrix(da: xr.DataArray, base_start: int, base_end: int) -> np.ndarray:
    """Base-period values as a ``(years, 365)`` array, without 29 February.

    Days of the base period outside the data are missing (``create.filled.series``).
    """
    return base_period_array(da.values, da.time, base_start, base_end)


def base_period_array(values: np.ndarray, time, base_start: int, base_end: int) -> np.ndarray:
    """:func:`base_period_matrix` for an array whose last axis runs along ``time``:
    returns ``(..., years, 365)``."""
    out = take_dates(values, time, base_period_dates(base_start, base_end))
    return out.reshape(*out.shape[:-1], -1, DAYS_PER_YEAR)


def window_values(base: np.ndarray, window: int) -> np.ndarray:
    """Values in the ``window``-day window around each calendar day, for each year.

    ``base`` is ``(..., years, 365)``; returns ``(..., 365, years, window)``. As in
    climdex.pcic's C++, the window wraps around within the same year: day 1's window
    includes days 364 and 365 of the same year.
    """
    half = window // 2
    days = (np.arange(DAYS_PER_YEAR)[:, None] + np.arange(-half, half + 1)[None, :]) % (
        DAYS_PER_YEAR
    )
    return np.swapaxes(base[..., days], -3, -2)  # base[..., days] is (..., years, 365, window)


def running_quantiles(
    base: np.ndarray,
    window: int,
    quantiles,
    min_fraction: float = MIN_BASE_FRACTION,
) -> dict[float, np.ndarray]:
    """climdex.pcic ``running_quantile_windowed``: each quantile for each calendar day.

    ``base`` is a ``(..., years, 365)`` matrix from :func:`base_period_matrix` or
    :func:`base_period_array` (any leading dimensions, for example grid cells). Returns
    ``{q: array (..., 365)}``; a day is missing when fewer than ``min_fraction`` of its
    ``years * window`` values are present.
    """
    values = window_values(base, window)
    lead = values.shape[:-3]
    slab = values.shape[-2] * values.shape[-1]
    rows, counts = _sorted_rows(values.reshape(-1, slab))
    enough = counts / slab >= min_fraction
    out = {}
    for q in quantiles:
        result = climdex_quantile_sorted(rows, counts, q)
        out[q] = np.where(enough, result, np.nan).reshape(*lead, DAYS_PER_YEAR)
    return out


def wet_day_quantiles(pr: np.ndarray, time, base_start: int, base_end: int, quantiles):
    """climdex.pcic ``get.prec.var.quantiles``: R ``quantile(type = 8)`` of the wet days
    (>= 1 mm) of the base-period years, 29 February included. ``pr``'s last axis runs
    along ``time``; returns ``{q: array (...)}``."""
    years = pd.DatetimeIndex(time.values if isinstance(time, xr.DataArray) else time).year
    in_base = (years >= base_start) & (years <= base_end)
    values = np.asarray(pr, dtype=float)[..., in_base]
    with np.errstate(invalid="ignore"):
        wet = np.where(values >= WET_DAY, values, np.nan)
    return {q: r_quantile_type8_rows(wet, q) for q in quantiles}


def bootstrap_quantiles(
    base: np.ndarray,
    window: int,
    quantiles,
    min_fraction: float = MIN_BASE_FRACTION,
) -> dict[float, np.ndarray]:
    """climdex.pcic ``running_quantile_windowed_bootstrap``: in-base thresholds.

    The Zhang et al. (2005) bootstrap. For each calendar day, base year ``rm`` and
    other base year ``dup``, the window values of year ``rm`` are replaced by a second
    copy of year ``dup``'s, and the quantile is taken of the result. ``base`` is
    ``(..., years, 365)`` (any leading dimensions, for example grid cells). Returns
    ``{q: array (..., 365, years, years - 1)}``, indexed ``[..., day, rm, k]`` where
    ``k`` runs over the other years in increasing order (as R's ``dim(d) <- c(dpy,
    nyears, nyears - 1, nq)``). A threshold is missing when fewer than
    ``min_fraction`` of the window's ``years * window`` values remain.

    The replaced sample is never built. The C++ sorts the window values once and then
    drops or duplicates elements in place, so the replaced sample is the sorted values
    with weights 0 (year ``rm``), 2 (year ``dup``) or 1. The value at position ``p`` of
    the replaced sample is the first sorted value whose cumulative weight exceeds ``p``.
    Missing values sort last and belong to no year, so their cumulative weights are
    above every position: series of different lengths are handled together.
    """
    base = np.asarray(base, dtype=float)
    lead = base.shape[:-2]
    nyears = base.shape[-2]
    flat = base.reshape(-1, nyears, DAYS_PER_YEAR)
    out = {
        q: np.full((flat.shape[0], DAYS_PER_YEAR, nyears, nyears - 1), np.nan) for q in quantiles
    }
    for cell in range(flat.shape[0]):
        result = _bootstrap_cell(flat[cell], window, quantiles, min_fraction)
        for q in quantiles:
            out[q][cell] = result[q]
    return {q: v.reshape(*lead, DAYS_PER_YEAR, nyears, nyears - 1) for q, v in out.items()}


def _weighted_value(data: np.ndarray, weight: np.ndarray, pos: np.ndarray) -> np.ndarray:
    """For each row of ``weight`` (cumulative weights of the sorted ``data``), the first
    value whose cumulative weight exceeds the row's position ``pos``."""
    count = np.count_nonzero(weight <= pos[:, None], axis=1)
    return data[np.minimum(count, data.size - 1)]


def _bootstrap_cell(
    base: np.ndarray, window: int, quantiles, min_fraction: float
) -> dict[float, np.ndarray]:
    """:func:`bootstrap_quantiles` of one ``(years, 365)`` series."""
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
        first = _weighted_value(data, weight, np.zeros(len(pairs), dtype=np.int64))
        for q in quantiles:
            left_pos, right_pos, h = _c_quantile_positions(n, q)
            left = _weighted_value(data, weight, left_pos)
            right = _weighted_value(data, weight, right_pos)
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
            # All the in-base quantiles of a variable share the sorting and weights of
            # each day, so they are computed together.
            qs = sorted({q, *INBASE_QUANTILES.get(var, ())})
            for k, v in bootstrap_quantiles(self.base[var], self.window, qs).items():
                self._inbase.setdefault((var, k), v)
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

    prec = wet_day_quantiles(ds.pr.values, ds.time, base_start, base_end, PRECIPITATION_QUANTILES)
    precipitation = {q: float(v) for q, v in prec.items()}

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
    "base_period_array",
    "base_period_dates",
    "base_period_matrix",
    "bootstrap_quantiles",
    "climdex_quantile",
    "climdex_quantile_sorted",
    "compute_thresholds",
    "day_of_year",
    "quantile_name",
    "r_quantile_type7",
    "r_quantile_type7_rows",
    "r_quantile_type8",
    "r_quantile_type8_rows",
    "running_quantiles",
    "take_dates",
    "wet_day_quantiles",
    "window_values",
]
