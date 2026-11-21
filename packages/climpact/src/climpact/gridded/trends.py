"""Per-cell trends and base-period means of the gridded indices (``trends.nc``).

R's gridded code writes no trends. This module applies the station trends
(:mod:`climpact.trends`, the port of zyp's ``zyp.sen`` and ``confint.zyp``) to every cell
of the annual index files a gridded run writes, and to each calendar month of the monthly
ones (#348), and adds what the map needs: the base-period mean of each cell and a
cos-latitude weighted mean over the grid.

- :func:`sen_trends` computes :func:`climpact.trends.sen_trend` for many series at once,
  with the same arithmetic, so each cell's slope and bounds are those of the station
  function on that cell's values, bit for bit. Series it cannot vectorise exactly (an
  infinite value, more than :data:`MAX_VECTOR_YEARS` years, a bound index outside the
  slopes) are passed to :func:`~climpact.trends.sen_trend` one at a time.
- :func:`base_means` and :func:`grid_means` are the base-period mean per cell and the
  weighted mean over the cells with a value, per year.
- :func:`write_grid_trends` reads the index files and writes ``trends.nc``: the annual
  series' variables (``<index>_slope(y, x)`` and the like, in float64) and, for each
  monthly file, the same per calendar month (``<index>_MON_slope(month, y, x)`` and the
  like, in float32).
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import netCDF4
import numpy as np

from climpact import __version__
from climpact.progress import Progress
from climpact.rdist import qnorm
from climpact.rnumerics import r_mean
from climpact.trends import MIN_TREND, MIN_TREND_PROPORTION, sen_trend

TRENDS_FILE = "trends.nc"
FILL_VALUE = 1e20
DECADE = 10.0  # the slopes are per year (x counts years); the file has them per decade
# Var(S) is computed in float32 by Kendall's TAUK2. Its tie sums are integers below
# n (n - 1) (2n + 5), exact in float32 (and so independent of the order TAUK2 adds them
# in) while that is below 2**24, i.e. up to 200 values.
MAX_VECTOR_YEARS = 200
CELLS_PER_CHUNK = 512  # series per vectorised batch: 512 x 1770 slopes (7 MB) for 60 years
MAX_CELLS = 100_000  # cells read from an index file at once
_Z = qnorm(1 - (1 - 0.95) / 2)  # confint.zyp's zstat at level 0.95
# SPI and SPEI have no annual file: their annual series is the 12-month scale's December
# value (the calendar year), which the station trend file also has (``spi12``, ``DEC``).
_SCALE_12 = 2  # position of the 12-month scale in the files' scale dimension (3, 6, 12)
MONTHS = 12
MONTHLY = "_MON"  # a monthly file's variables in trends.nc: <index>_MON_slope(month, y, x)


# --- the calculation --------------------------------------------------------------------------


def _mean_of_two(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """R's ``mean(c(a, b))`` for pairs of doubles (``r_median`` of an even count).

    When ``a + b`` is exact in R's 64-bit extended significand (both zero, or exponents
    at most 10 apart) R's two-pass mean is the exact mean rounded to a double, which is
    ``(a + b) / 2`` in double precision. Other pairs go to :func:`r_mean`."""
    with np.errstate(over="ignore", invalid="ignore"):
        out = (a + b) * 0.5
    _, ea = np.frexp(a)
    _, eb = np.frexp(b)
    tiny = 2.0**-1000
    exact = (
        (a == 0) | (b == 0) | ((np.abs(ea - eb) <= 10) & (np.abs(a) > tiny) & (np.abs(b) > tiny))
    ) & np.isfinite(out)
    for i in np.flatnonzero(~exact):
        out[i] = r_mean(np.array([a[i], b[i]]))
    return out


def _pairs(n: int) -> tuple[np.ndarray, np.ndarray]:
    return np.triu_indices(n, 1)


def _chunk_trends(y: np.ndarray, x0: int = 0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """:func:`sen_trends` for one batch of series ``(cells, n)``."""
    cells, n = y.shape
    lower = np.full(cells, np.nan)
    slope = np.full(cells, np.nan)
    upper = np.full(cells, np.nan)
    valid = ~np.isnan(y)
    m = valid.sum(axis=1)
    # min_trend_data: at least 70% of the series and at least 10 values.
    ok = (m / n >= MIN_TREND_PROPORTION) & (m >= MIN_TREND) if n else np.zeros(cells, bool)
    scalar = ok & (np.isinf(y).any(axis=1) | (n > MAX_VECTOR_YEARS))
    vector = ok & ~scalar
    rows = np.flatnonzero(vector)
    if rows.size:
        yv = y[rows]
        mv = m[rows]
        k = mv * (mv - 1) // 2  # the number of slopes (none is infinite or NaN)
        # Kendall's Var(S) in float32. x has no ties (whole years), so its tie sums are
        # 0 and Var(S) = (n (n - 1) (2n + 5) - sum t (t - 1) (2t + 5)) / 18 over the tie
        # groups of y (ties decided in float32): each value of a group of t adds
        # (t - 1) (2t + 5). A constant y gives 0 either way, as TAUK2 leaves it.
        yf = yv.astype(np.float32)
        counts = (yf[:, :, None] == yf[:, None, :]).sum(axis=2).astype(float)  # NaN: 0
        tied = np.where(valid[rows], (counts - 1) * (2 * counts + 5), 0.0).sum(axis=1)
        nf = mv.astype(float)
        full = nf * (nf - 1) * (2 * nf + 5)
        var_s = ((full - tied).astype(np.float32) / np.float32(18)).astype(float)
        var_s[tied == full] = 0.0  # constant: TAUK2 sets no Var(S)
        # confint.zyp: the bounds are the slopes at (1-based) positions
        # round((n' -+ c) / 2), rounded half to even; the median those at (k + 1) %/% 2
        # (and the next one when k is even).
        c_alpha = np.sqrt(var_s) * _Z
        kf = k.astype(float)
        idx_lo = np.rint((kf - c_alpha) / 2).astype(np.int64)
        idx_hi = np.rint((kf + c_alpha) / 2).astype(np.int64)
        half = (k + 1) // 2
        inside = (idx_lo >= 1) & (idx_hi <= k)
        scalar[rows[~inside]] = True  # confint.zyp's edge cases: the station function
        yv, k, idx_lo, idx_hi, half, rows = (v[inside] for v in (yv, k, idx_lo, idx_hi, half, rows))
        # zyp.sen's slopes (y[j] - y[j+i]) / (x[j] - x[j+i]) over the series without its
        # missing values are the slopes of every pair of valid values, earlier first; the
        # pairs with a missing value are NaN here and go last. Only four order statistics
        # are needed, so the rows that need the same positions are partitioned together.
        i, j = _pairs(n)
        x = np.arange(n, dtype=float) + x0
        with np.errstate(invalid="ignore"):
            slopes = (yv[:, i] - yv[:, j]) / (x[i] - x[j])
        last = slopes.shape[1] - 1
        positions = np.stack([idx_lo - 1, half - 1, np.minimum(half, last), idx_hi - 1], axis=1)
        picked = np.empty(positions.shape)
        groups, which = np.unique(positions, axis=0, return_inverse=True)
        for g, kth in enumerate(groups):
            members = np.flatnonzero(which.ravel() == g)
            part = np.partition(slopes[members], np.unique(kth), axis=1)
            picked[members] = part[:, kth]
        lo, hi = picked[:, 1], picked[:, 2]
        med = lo.copy()
        even = np.flatnonzero(k % 2 == 0)
        if even.size:  # R's median of an even count: R's mean of the two middle values
            med[even] = _mean_of_two(lo[even], hi[even])
        lower[rows] = picked[:, 0]
        slope[rows] = med
        upper[rows] = picked[:, 3]
    for r in np.flatnonzero(scalar):
        lower[r], slope[r], upper[r] = sen_trend(y[r], x0)
    return lower, slope, upper


def sen_trends(
    values: np.ndarray,
    x0: int = 0,
    pool: ThreadPoolExecutor | None = None,
    cells_per_chunk: int = CELLS_PER_CHUNK,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(lower, slope, upper)`` of every series of ``values`` ``(cells, n)``, each
    ``(cells,)``: :func:`climpact.trends.sen_trend` of each row, vectorised.

    The slopes are per step of ``x`` (per year for annual series). Rows that fail
    ``min_trend_data`` are missing. Batches of ``cells_per_chunk`` rows are computed on
    ``pool``'s threads when one is given.
    """
    y = np.asarray(values, dtype=float)
    if y.ndim != 2:
        raise ValueError("values must be (cells, n)")
    starts = range(0, y.shape[0], max(cells_per_chunk, 1))

    def run(s: int):
        return _chunk_trends(y[s : s + cells_per_chunk], x0)

    parts = list(pool.map(run, starts) if pool is not None else map(run, starts))
    if not parts:
        empty = np.empty(0)
        return empty, empty.copy(), empty.copy()
    return tuple(np.concatenate([p[i] for p in parts]) for i in range(3))  # type: ignore[return-value]


def base_means(values: np.ndarray, years: Sequence[int], base_start: int, base_end: int):
    """The mean of each series ``(cells, n)`` over the years of the base period that have
    a (finite) value, as the station index page's base-period mean; missing without one."""
    y = np.asarray(values, dtype=float)
    years = np.asarray(years)
    base = y[:, (years >= base_start) & (years <= base_end)]
    finite = np.isfinite(base)
    count = finite.sum(axis=1)
    total = np.where(finite, base, 0.0).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(count > 0, total / np.maximum(count, 1), np.nan)


def cell_weights(latitude: np.ndarray) -> np.ndarray:
    """Area weights of the cells: the cosine of their latitude (at least 0)."""
    return np.maximum(np.cos(np.deg2rad(np.asarray(latitude, dtype=float))), 0.0)


def _weighted_sums(values: np.ndarray, weights: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per time step of ``values`` ``(time, cells)``: the sum of weight x value and the sum
    of the weights, over the cells with a (finite) value."""
    v = np.asarray(values, dtype=float)
    finite = np.isfinite(v)
    w = np.where(finite, np.asarray(weights, dtype=float)[None, :], 0.0)
    return (np.where(finite, v, 0.0) * w).sum(axis=1), w.sum(axis=1)


def _ratio(total: np.ndarray, wsum: np.ndarray) -> np.ndarray:
    return np.where(wsum > 0, total / np.where(wsum > 0, wsum, 1.0), np.nan)


def grid_means(values: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """The weighted mean over the cells with a (finite) value of each time step of
    ``values`` ``(time, cells)``; missing when no cell has one."""
    return _ratio(*_weighted_sums(values, weights))


# --- the index files ----------------------------------------------------------------------


@dataclass(frozen=True)
class Series:
    """One annual series of an index file: variable ``name`` of ``path``, with its
    ``units`` and ``long_name``; ``months`` selects the December values of the 12-month
    scale of a monthly SPI or SPEI file (None for an annual file). With ``monthly``, the
    twelve series (one per calendar month) of a monthly file's variable."""

    path: Path
    name: str
    units: str
    long_name: str
    months: np.ndarray | None = None
    monthly: bool = False

    @property
    def key(self) -> str:
        """The start of its variables' names in trends.nc: ``txx``, ``txx_MON``."""
        return f"{self.name}{MONTHLY}" if self.monthly else self.name


def _dates(nc: netCDF4.Dataset, time_dim: str):
    t = nc.variables[time_dim]
    calendar = t.getncattr("calendar") if "calendar" in t.ncattrs() else "standard"
    return netCDF4.num2date(t[:], t.getncattr("units"), calendar)


def _attr(var, name: str, default: str = "") -> str:
    return str(var.getncattr(name)) if name in var.ncattrs() else default


def annual_series(paths: Iterable[str | Path]) -> list[Series]:
    """The annual series of the index files ``paths``, in their order: every index
    variable of each annual file (``hw_ANN`` and ``hwEHF_ANN`` hold several; the
    ``day_of_`` variables are dates, not series), and the 12-month December values of
    the SPI and SPEI files. Monthly files with an annual counterpart and ``tx95t`` (a
    day-of-year climatology) have no annual series of their own."""
    out = []
    for path in map(Path, paths):
        with netCDF4.Dataset(path) as nc:
            freq = _attr(nc, "index_calculation_frequency")
            for name, var in nc.variables.items():
                if name in nc.dimensions or name.startswith("day_of_") or var.ndim < 3:
                    continue
                if freq == "yr" and var.ndim == 3:
                    out.append(
                        Series(path, name, _attr(var, "units"), _attr(var, "long_name", name))
                    )
                elif freq == "mon" and var.ndim == 4 and var.dimensions[0] == "scale":
                    months = np.array([d.month for d in _dates(nc, var.dimensions[1])])
                    long_name = _attr(var, "long_name", name)
                    out.append(
                        Series(
                            path,
                            name,
                            _attr(var, "units"),
                            f"{long_name} (12-month scale, December)",
                            np.flatnonzero(months == 12),
                        )
                    )
    return out


def monthly_series(paths: Iterable[str | Path]) -> list[Series]:
    """The monthly series of the index files ``paths``, in their order: the index
    variable of each monthly file without a scale dimension (``txx_MON``, ``prcptot_MON``;
    not SPI and SPEI, whose annual series :func:`annual_series` takes from their 12-month
    scale), each to be split into its twelve calendar months."""
    out = []
    for path in map(Path, paths):
        with netCDF4.Dataset(path) as nc:
            if _attr(nc, "index_calculation_frequency") != "mon":
                continue
            for name, var in nc.variables.items():
                if name in nc.dimensions or name.startswith("day_of_") or var.ndim != 3:
                    continue
                long_name = _attr(var, "long_name", name)
                out.append(Series(path, name, _attr(var, "units"), long_name, monthly=True))
    return out


def _month_steps(series: Series, years: np.ndarray) -> np.ndarray:
    """``(12, years)``: the time step of each calendar month of each of ``years`` in the
    monthly series' file, -1 where the file has none."""
    with netCDF4.Dataset(series.path) as nc:
        dates = _dates(nc, nc.variables[series.name].dimensions[0])
    position = {int(y): k for k, y in enumerate(years)}
    steps = np.full((MONTHS, len(years)), -1, dtype=np.int64)
    for t, d in enumerate(dates):
        k = position.get(int(d.year))
        if k is None:
            raise ValueError(f"{series.path.name}: its years differ from the annual files'")
        steps[d.month - 1, k] = t
    return steps


def _read(series: Series, ys: slice) -> np.ndarray:
    """The series of the cells of rows ``ys``: ``(time, y, x)`` as float64, NaN missing."""
    with netCDF4.Dataset(series.path) as nc:
        var = nc.variables[series.name]
        var.set_auto_mask(True)
        if series.months is None:
            values = var[:, ys, :]
        else:
            values = var[_SCALE_12, :, ys, :][series.months]
        return np.ma.filled(np.ma.asarray(values).astype(float), np.nan)


def _layout(series: Series) -> dict:
    """The time, X and Y of the series' file, as the index files hold them."""
    with netCDF4.Dataset(series.path) as nc:
        var = nc.variables[series.name]
        time_dim, y_dim, x_dim = var.dimensions[-3:]
        t = nc.variables[time_dim]
        times = np.asarray(t[:], dtype=float)
        dates = _dates(nc, time_dim)
        bounds_name = _attr(t, "bounds")
        bounds = (
            np.asarray(nc.variables[bounds_name][:], dtype=float)
            if bounds_name in nc.variables
            else None
        )
        if series.months is not None:
            times, dates = times[series.months], dates[series.months]
            bounds = bounds[series.months] if bounds is not None else None
        coords = {}
        for dim in (y_dim, x_dim):
            v = nc.variables[dim]
            coords[dim] = (
                np.asarray(v[:], dtype=float),
                {k: v.getncattr(k) for k in v.ncattrs() if k not in ("_FillValue", "bounds")},
            )
        return {
            "time_dim": time_dim,
            "y_dim": y_dim,
            "x_dim": x_dim,
            "times": times,
            "years": np.array([d.year for d in dates]),
            "time_attrs": {k: t.getncattr(k) for k in t.ncattrs() if k != "_FillValue"},
            "bounds_name": bounds_name or f"{time_dim}_bnds",
            "bounds": bounds,
            "coords": coords,
            "shape": (len(coords[y_dim][0]), len(coords[x_dim][0])),
        }


def _create(path: Path, layout: dict, series: list[Series], base: tuple[int, int],
            month_rows: int = 1):  # fmt: skip
    nc = netCDF4.Dataset(path, "w", format="NETCDF4")
    try:
        td, yd, xd = layout["time_dim"], layout["y_dim"], layout["x_dim"]
        nc.createDimension(td, len(layout["times"]))
        nc.createDimension(yd, layout["shape"][0])
        nc.createDimension(xd, layout["shape"][1])
        t = nc.createVariable(td, "f8", (td,))
        t.setncatts(layout["time_attrs"])
        t[:] = layout["times"]
        if layout["bounds"] is not None:
            nc.createDimension("bnds", 2)
            t.setncattr("bounds", layout["bounds_name"])
            nc.createVariable(layout["bounds_name"], "f8", (td, "bnds"))[:] = layout["bounds"]
        elif "bounds" in t.ncattrs():
            t.delncattr("bounds")
        for dim in (yd, xd):
            values, attrs = layout["coords"][dim]
            c = nc.createVariable(dim, "f8", (dim,))
            c.setncatts(attrs)
            c[:] = values
        first, last = int(layout["years"][0]), int(layout["years"][-1])
        b0, b1 = base
        if any(s.monthly for s in series):
            nc.createDimension("month", MONTHS)
            m = nc.createVariable("month", "i4", ("month",))
            m.setncatts({"long_name": "calendar month", "units": "1"})
            m[:] = np.arange(1, MONTHS + 1)
        for s in series:
            # A monthly file's variables are per calendar month and in float32 (#348):
            # the month first, one month of a stripe of rows a chunk, so a month reads
            # alone and each stripe writes whole chunks.
            month, of = (("month",), " in each calendar month") if s.monthly else ((), "")
            for suffix, dims, units, long_name in (
                ("slope", (*month, yd, xd), f"{s.units} per decade",
                 f"Sen's slope per decade of {s.long_name}{of}, {first}-{last}"),
                ("lower", (*month, yd, xd), f"{s.units} per decade",
                 f"Lower bound of the 95% confidence interval of the slope of "
                 f"{s.long_name}{of}"),
                ("upper", (*month, yd, xd), f"{s.units} per decade",
                 f"Upper bound of the 95% confidence interval of the slope of "
                 f"{s.long_name}{of}"),
                ("base_mean", (*month, yd, xd), s.units,
                 f"Mean of {s.long_name}{of} over the base period {b0}-{b1}"),
                ("grid_mean", (*month, td), s.units,
                 f"Mean of {s.long_name}{of} over the grid's cells with a value, weighted "
                 "by the cosine of latitude"),
            ):  # fmt: skip
                if s.monthly:
                    chunks = (1, month_rows, layout["shape"][1]) if suffix != "grid_mean" else None
                    v = nc.createVariable(
                        f"{s.key}_{suffix}", "f4", dims, fill_value=np.float32(FILL_VALUE),
                        zlib=True, complevel=4, chunksizes=chunks,
                    )  # fmt: skip
                else:
                    v = nc.createVariable(
                        f"{s.name}_{suffix}", "f8", dims, fill_value=FILL_VALUE, zlib=True,
                        complevel=4,
                    )  # fmt: skip
                v.setncatts({"units": units, "long_name": long_name, "index_file": s.path.name})
                if suffix == "base_mean":
                    v.setncattr("cell_methods", f"{td}: mean (base period {b0}-{b1})")
                elif suffix == "grid_mean":
                    v.setncattr("cell_methods", f"{yd}: {xd}: mean (weighted by cos(latitude))")
        nc.setncatts(
            {
                "title": "Climpact trends and base-period means of the gridded indices",
                "base_period": f"{b0}-{b1}",
                "trend_period": f"{first}-{last}",
                "trend_method": (
                    "Sen's slope (zyp.sen) and its 95% confidence interval (confint.zyp) of "
                    "each cell's annual series, as Climpact's station trend file computes "
                    f"them, per decade; missing unless at least {MIN_TREND} values and "
                    f"{MIN_TREND_PROPORTION:.0%} of the years have a value"
                    + (
                        "; for each monthly file, the same of each calendar month's series "
                        "(the <index>_MON_ variables, with a month dimension, in float32)"
                        if any(s.monthly for s in series)
                        else ""
                    )
                ),
                "source": "climpact (Python) gridded trends; R's Climpact has no counterpart",
                "climpact_python_version": __version__,
                "file_created": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
    except BaseException:
        nc.close()
        raise
    return nc


def _write_monthly(nc, s: Series, steps: np.ndarray, ys: slice, years, base, weights, run,
                   sums) -> None:  # fmt: skip
    """A monthly series' fields for the cells of rows ``ys``: the stripe read once, its
    twelve months' series computed together (``run``: :func:`sen_trends` on the pool)."""
    values = _read(s, ys)  # (time, rows, x)
    rows, nx = values.shape[1:]
    by_month = np.where(
        (steps >= 0)[:, :, None, None], values[np.maximum(steps, 0)], np.nan
    )  # (12, years, rows, x)
    cells = by_month.transpose(0, 2, 3, 1).reshape(MONTHS * rows * nx, len(years))
    lower, slope, upper = run(cells)
    shape = (MONTHS, rows, nx)
    for suffix, result in (
        ("slope", slope * DECADE),
        ("lower", lower * DECADE),
        ("upper", upper * DECADE),
        ("base_mean", base_means(cells, years, *base)),
    ):
        field = np.ma.masked_invalid(result.reshape(shape).astype(np.float32))
        nc.variables[f"{s.key}_{suffix}"][:, ys, :] = field
    w = weights[ys].reshape(-1)
    total, wsum = sums
    for m in range(MONTHS):
        t, ws = _weighted_sums(by_month[m].reshape(len(years), -1), w)
        total[m] += t
        wsum[m] += ws


def write_grid_trends(
    index_paths: Iterable[str | Path],
    out_path: str | Path,
    base_start: int,
    base_end: int,
    latitude: np.ndarray | None = None,
    workers: int = 1,
    progress: Progress | None = None,
    max_cells: int = MAX_CELLS,
    cells_per_chunk: int = CELLS_PER_CHUNK,
) -> Path | None:
    """Write ``trends.nc`` for the index files ``index_paths`` of one gridded run.

    For each annual series (:func:`annual_series`), per cell: ``<name>_slope``,
    ``<name>_lower`` and ``<name>_upper`` (Sen's slope per decade and its 95% interval,
    :func:`sen_trends`) and ``<name>_base_mean`` (:func:`base_means`); and
    ``<name>_grid_mean(time)``, the mean over the cells with a value weighted by
    :func:`cell_weights` of ``latitude`` ``(y, x)`` (default: the files' Y coordinate).
    And the same for each calendar month of every monthly file
    (:func:`monthly_series`), in float32 with a ``month`` dimension:
    ``<name>_MON_slope(month, y, x)``, ``_lower``, ``_upper``, ``_base_mean`` and
    ``<name>_MON_grid_mean(month, time)``, each month's series over the annual files'
    years. Rows of cells are read ``max_cells`` cells at a time (a twelfth of that for a
    monthly file, whose stripes hold twelve times the steps) and computed by ``workers``
    threads; ``progress("trends", done, total)`` is called after each series. The file
    is written under a temporary name and renamed when complete. Returns its path, or
    None (nothing written) when no file has an annual series.
    """
    index_paths = list(index_paths)
    series = annual_series(index_paths)
    if not series:
        return None
    layout = _layout(series[0])
    ny, nx = layout["shape"]
    years = layout["years"]
    for s in series[1:]:
        other = _layout(s)
        if other["shape"] != (ny, nx) or not np.array_equal(other["years"], years):
            raise ValueError(f"{s.path.name}: its grid or years differ from {series[0].path.name}")
    months = monthly_series(index_paths)
    month_steps = {}
    for s in months:
        if _layout(s)["shape"] != (ny, nx):
            raise ValueError(f"{s.path.name}: its grid differs from {series[0].path.name}")
        month_steps[s] = _month_steps(s, years)
    if latitude is None:
        latitude = np.broadcast_to(layout["coords"][layout["y_dim"]][0][:, None], (ny, nx))
    latitude = np.asarray(latitude, dtype=float)
    if latitude.shape != (ny, nx):
        raise ValueError(f"latitude has shape {latitude.shape}, the grid is {(ny, nx)}")
    weights = cell_weights(latitude)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(f".{out_path.name}.{os.getpid()}.tmp")
    rows = max(1, max_cells // max(nx, 1))
    stripes = [slice(y, min(y + rows, ny)) for y in range(0, ny, rows)]
    month_rows = min(ny, max(1, max_cells // max(MONTHS * nx, 1)))
    month_stripes = [slice(y, min(y + month_rows, ny)) for y in range(0, ny, month_rows)]
    base = (base_start, base_end)
    nc = _create(tmp, layout, [*series, *months], base, month_rows)
    total_series = len(series) + len(months)
    try:
        with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:

            def run(cells: np.ndarray):
                return sen_trends(
                    cells, pool=pool if workers > 1 else None, cells_per_chunk=cells_per_chunk
                )

            for done, s in enumerate(series, start=1):
                wsum = np.zeros(len(years))
                total = np.zeros(len(years))
                for ys in stripes:
                    values = _read(s, ys)  # (time, rows, x)
                    cells = values.reshape(len(years), -1).T  # (cells, time)
                    lower, slope, upper = run(cells)
                    shape = (ys.stop - ys.start, nx)
                    for suffix, result in (
                        ("slope", slope * DECADE),
                        ("lower", lower * DECADE),
                        ("upper", upper * DECADE),
                        ("base_mean", base_means(cells, years, base_start, base_end)),
                    ):
                        nc.variables[f"{s.name}_{suffix}"][ys, :] = np.ma.masked_invalid(
                            result.reshape(shape)
                        )
                    t, w = _weighted_sums(cells.T, weights[ys].reshape(-1))
                    total += t
                    wsum += w
                nc.variables[f"{s.name}_grid_mean"][:] = np.ma.masked_invalid(_ratio(total, wsum))
                if progress is not None:
                    progress("trends", done, total_series)
            for done, s in enumerate(months, start=len(series) + 1):
                sums = (np.zeros((MONTHS, len(years))), np.zeros((MONTHS, len(years))))
                for ys in month_stripes:
                    _write_monthly(nc, s, month_steps[s], ys, years, base, weights, run, sums)
                mean = _ratio(*sums).astype(np.float32)
                nc.variables[f"{s.key}_grid_mean"][:] = np.ma.masked_invalid(mean)
                if progress is not None:
                    progress("trends", done, total_series)
        nc.close()
    except BaseException:
        if nc.isopen():
            nc.close()
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(out_path)
    return out_path


__all__ = [
    "TRENDS_FILE",
    "Series",
    "annual_series",
    "base_means",
    "cell_weights",
    "grid_means",
    "monthly_series",
    "sen_trends",
    "write_grid_trends",
]
