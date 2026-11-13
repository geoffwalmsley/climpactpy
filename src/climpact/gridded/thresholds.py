"""Base-period thresholds of every cell of a grid, written as Climpact's thresholds netCDF.

A port of ``climpact.ncdf.thresholds.wrapper.r``, which calls
``create.thresholds.from.file`` in Climpact's modified climdex.pcic.ncdf 0.5-4
(``server/pcic_packages/climdex.pcic.ncdf/R/ncdf.R``). For each cell,
``get.quantiles.for.stripe`` computes:

- TX and TN 5th, 10th, 50th, 90th and 95th percentiles over a 5-day window
  (``get.outofbase.quantiles``), and the 90th percentile of TX, TN and TAVG over a
  15-day window: the station thresholds (:mod:`climpact.thresholds`), with the same code;
- the 95th and 99th percentiles of the base-period wet days (``r95thresh``,
  ``r99thresh``), also as for stations;
- the 5th and 95th percentiles (type 7) of TAVG over every base-period day, and the
  85th percentile of the positive base-period EHF (``calculate_EHF``, the same formula
  as the station EHF, :func:`climpact.products.ehf.excess_factors`);
- the base-period TX, TN and precipitation themselves (``txraw``, ``tnraw``,
  ``precraw``), for the gridded SPI and SPEI.

``create.thresholds.file`` writes them with the dimensions, coordinates and attributes
reproduced by :func:`write_grid_thresholds`. Cells are processed in blocks (the dask
chunks of :class:`~climpact.gridded.io.GriddedInput`), vectorised within a block, and
written as each block completes, so memory does not grow with the grid.
"""

from __future__ import annotations

import datetime as dt
import getpass
import os
import time as time_module
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import netCDF4
import numpy as np
import pandas as pd

from climpact import __version__
from climpact.gridded.io import GriddedInput
from climpact.io.output_files import CLIMPACT_VERSION
from climpact.products.ehf import excess_factors
from climpact.progress import Progress
from climpact.thresholds import (
    DAYS_PER_YEAR,
    HEATWAVE_QUANTILE,
    HEATWAVE_WINDOW,
    MIN_BASE_DAYS,
    TEMPERATURE_QUANTILES,
    TEMPERATURE_WINDOW,
    InsufficientBaseData,
    base_period_array,
    r_quantile_type7_rows,
    running_quantiles,
    take_dates,
    wet_day_quantiles,
)

CLIMDEX_PCIC_VERSION = "1.2.0"  # the climdex.pcic whose results are reproduced
CLIMPACT_GITHUB = "https://github.com/ARCCSS-extremes/climpact"
FILL_VALUE = 1e20
EHF_QUANTILE = 0.85
TAVG_QUANTILES = (0.05, 0.95)
PRECIPITATION_QUANTILES = (0.95, 0.99)  # get.outofbase.quantiles' default prec.qtiles
# Cells computed together: about 10 MB of working memory each for 60 years of data.
DEFAULT_CELLS_PER_BATCH = 8
OUTPUT_CHUNK_CACHE = 1 << 20  # bytes per output variable


@dataclass(frozen=True)
class ThresholdVariable:
    """One variable of the thresholds file (``get.thresholds.metadata``).

    ``kind`` is ``"day"`` (365 days of year, on ``time``), ``"cell"`` (one value per
    cell) or ``"base"`` (every base-period day, on ``base_time``).
    """

    name: str
    units: str
    long_name: str
    kind: str


def _running(name: str, var: str, q: str, days: str = "") -> ThresholdVariable:
    return ThresholdVariable(
        name, "degrees_C", f"{q}_percentile_running_baseline_{var}{days}", "day"
    )


# In the order of get.thresholds.metadata, which is the order R writes them.
THRESHOLD_VARIABLES = (
    *(_running(f"tx{q}thresh", "tasmax", f"{q}th") for q in ("05", "10", "50", "90", "95")),
    *(_running(f"tn{q}thresh", "tasmin", f"{q}th") for q in ("05", "10", "50", "90", "95")),
    _running("tx90thresh_15days", "tasmax", "90th", "_15days"),
    _running("tn90thresh_15days", "tasmin", "90th", "_15days"),
    _running("tavg90thresh_15days", "tasavg", "90th", "_15days"),
    ThresholdVariable("tavg05thresh", "degrees_C", "05th_percentile_baseline_tasavg", "cell"),
    ThresholdVariable("tavg95thresh", "degrees_C", "95th_percentile_baseline_tasavg", "cell"),
    ThresholdVariable("ehf85thresh", "degrees_C^2", "85th_percentile_baseline_EHF", "cell"),
    ThresholdVariable("r95thresh", "kg m-2 d-1", "95th_percentile_baseline_wet_day_pr", "cell"),
    ThresholdVariable("r99thresh", "kg m-2 d-1", "99th_percentile_baseline_wet_day_pr", "cell"),
    ThresholdVariable("txraw", "degrees_C", "tasmax_baseline", "base"),
    ThresholdVariable("tnraw", "degrees_C", "tasmin_baseline", "base"),
    ThresholdVariable("precraw", "kg m-2 d-1", "prec_baseline", "base"),
)


def filled_dates(time: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """1 January of the first year to 31 December of the last (``date.series``)."""
    return pd.date_range(f"{time[0].year}-01-01", f"{time[-1].year}-12-31", freq="D")


def check_base_period(time: pd.DatetimeIndex, base_start: int, base_end: int) -> None:
    """climdex.pcic stops when the dates cover ``MIN_BASE_DAYS`` days of the base
    period or fewer (``get.num.days.in.range``)."""
    years = time.year
    if np.count_nonzero((years >= base_start) & (years <= base_end)) <= MIN_BASE_DAYS:
        raise InsufficientBaseData(
            f"less than a year of data within the base period {base_start}-{base_end}"
        )


def cell_thresholds(
    tasmax: np.ndarray,
    tasmin: np.ndarray,
    pr: np.ndarray,
    time: pd.DatetimeIndex,
    base_start: int,
    base_end: int,
) -> dict[str, np.ndarray]:
    """Every threshold of :data:`THRESHOLD_VARIABLES` for a block of cells.

    The inputs are ``(..., time)`` arrays in degrees C and kg m-2 d-1 (any leading
    dimensions, the cells). Returns ``{name: array}`` of shape ``(..., 365)`` for the
    day-of-year thresholds, ``(...)`` for the single values and ``(..., base days)``
    for the base-period data.
    """
    full = filled_dates(time)
    tx = take_dates(tasmax, time, full)
    tn = take_dates(tasmin, time, full)
    prec = take_dates(pr, time, full)
    tavg = (tx + tn) / 2
    in_base = (full.year >= base_start) & (full.year <= base_end)
    out: dict[str, np.ndarray] = {}

    for prefix, series in (("tx", tx), ("tn", tn)):
        base = base_period_array(series, full, base_start, base_end)
        for q, values in running_quantiles(base, TEMPERATURE_WINDOW, TEMPERATURE_QUANTILES).items():
            out[f"{prefix}{round(q * 100):02d}thresh"] = values
    for prefix, series in (("tx", tx), ("tn", tn), ("tavg", tavg)):
        base = base_period_array(series, full, base_start, base_end)
        hw = running_quantiles(base, HEATWAVE_WINDOW, [HEATWAVE_QUANTILE])[HEATWAVE_QUANTILE]
        out[f"{prefix}90thresh_15days"] = hw

    tavg_base = tavg[..., in_base]
    t05, t95 = (r_quantile_type7_rows(tavg_base, q) for q in TAVG_QUANTILES)
    out["tavg05thresh"], out["tavg95thresh"] = t05, t95
    ehf, _ = excess_factors(tavg, t95, t05)
    ehf_base = ehf[..., in_base]
    with np.errstate(invalid="ignore"):
        positive = np.where(ehf_base > 0, ehf_base, np.nan)
    out["ehf85thresh"] = r_quantile_type7_rows(positive, EHF_QUANTILE)

    wet = wet_day_quantiles(prec, full, base_start, base_end, PRECIPITATION_QUANTILES)
    out["r95thresh"], out["r99thresh"] = wet[0.95], wet[0.99]

    out["txraw"] = tx[..., in_base]
    out["tnraw"] = tn[..., in_base]
    out["precraw"] = prec[..., in_base]
    return out


# --- writing -----------------------------------------------------------------------------


def _time_origin(units: str) -> str:
    """R: ``strsplit(time.units, " ")[[1]][3]``, the date of ``<unit> since <date> ...``."""
    parts = units.split(" ")
    if len(parts) < 3 or parts[1] != "since":
        raise ValueError(f"unsupported time units {units!r}")
    return parts[2]


def _days_since(dates, origin: str) -> np.ndarray:
    origin_day = pd.Timestamp(origin).normalize()
    return ((pd.DatetimeIndex(dates) - origin_day) / pd.Timedelta(days=1)).to_numpy(float)


def _copy_attrs(src, dst, skip=()) -> None:
    for name in src.ncattrs():
        if name not in skip:
            dst.setncattr(name, src.getncattr(name))


def _etccdi_attrs(base_start: int, base_end: int, author: Mapping[str, str]) -> dict:
    """``put.ETCCDI.atts``: the global attributes added to the copied ones."""
    attrs = {"index_calculation_frequency": "days", "base_period": f"{base_start}-{base_end}"}
    for key, name in (
        ("institution", "author_institution"),
        ("institution_id", "author_institution_id"),
        ("indices_archive", "ETCCDI_indices_archive"),
        ("contact", "contact"),
        ("references", "references"),
    ):
        if author.get(key):
            attrs[name] = author[key]
    attrs["file_created"] = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        attrs["file_created_by_userid"] = getpass.getuser()
    except Exception:  # noqa: BLE001 - no user name (e.g. in a container): leave it out
        pass
    attrs["climpactpy_version"] = __version__
    attrs["climdex.pcic_version"] = CLIMDEX_PCIC_VERSION
    attrs["Climpact_version"] = CLIMPACT_VERSION
    attrs["Climpact_github"] = CLIMPACT_GITHUB
    return attrs


def create_thresholds_file(
    path: str | Path,
    inp: GriddedInput,
    base_start: int,
    base_end: int,
    author: Mapping[str, str] | None = None,
) -> netCDF4.Dataset:
    """Create the thresholds file with everything but the threshold values
    (``create.thresholds.file``), and return it open for writing."""
    author = author or {}
    nbase = _base_dates(inp.time, base_start, base_end).size
    ny, nx = inp.shape
    by = max(inp.data.chunks[inp.y_dim])
    bx = max(inp.data.chunks[inp.x_dim])
    history = f"Created by climpactpy {__version__} on {time_module.ctime()}"

    with netCDF4.Dataset(inp.exemplar) as src:
        src_time = src.variables[inp.time_dim]
        units = src_time.getncattr("units")
        origin = _time_origin(units)
        bounds_name = (
            src_time.getncattr("bounds") if "bounds" in src_time.ncattrs() else "time_bnds"
        )
        mid = (base_start + base_end) // 2  # R: floor(mean(base.range))
        day = pd.to_timedelta(np.arange(DAYS_PER_YEAR), unit="D")
        out_time = _days_since(pd.Timestamp(f"{mid}-01-01") + day, origin)
        out_bounds = np.stack(
            [
                _days_since(pd.Timestamp(f"{base_start}-01-01") + day, origin),
                _days_since(pd.Timestamp(f"{base_end}-01-01") + day, origin),
            ],
            axis=1,
        )
        base_time = _days_since(_base_dates(inp.time, base_start, base_end), origin)

        nc = netCDF4.Dataset(path, "w", format="NETCDF4")
        try:
            nc.createDimension("bnds", 2)
            nc.createDimension("time", None)
            nc.createDimension(inp.x_dim, nx)
            nc.createDimension(inp.y_dim, ny)
            nc.createDimension("base_time", None)

            t = nc.createVariable("time", "f8", ("time",))
            t.setncatts(
                {
                    "long_name": "time",
                    "units": f"days since {origin}",
                    "calendar": "proleptic_gregorian",
                }
            )
            # R copies every attribute of the input time, including units in hours or
            # seconds although the values are in days; only "days since" units are kept.
            skip = {"_FillValue"} | ({"units"} if not units.startswith("days ") else set())
            _copy_attrs(src_time, t, skip)
            t[:] = out_time
            tb = nc.createVariable(bounds_name, "f8", ("time", "bnds"))
            tb[:] = out_bounds
            for dim in (inp.x_dim, inp.y_dim):
                if dim not in src.variables:
                    raise ValueError(f"dimension {dim!r} has no coordinate variable")
                coord = nc.createVariable(dim, "f8", (dim,))
                if "units" in src.variables[dim].ncattrs():
                    coord.setncattr("units", src.variables[dim].getncattr("units"))
                _copy_attrs(src.variables[dim], coord, {"_FillValue", "bounds"})
                coord[:] = np.asarray(src.variables[dim][:], dtype=float)

            _copy_attrs(src, nc)
            nc.setncatts(_etccdi_attrs(base_start, base_end, author))

            dims = {
                "day": ("time", inp.y_dim, inp.x_dim),
                "cell": (inp.y_dim, inp.x_dim),
                "base": ("base_time", inp.y_dim, inp.x_dim),
            }
            chunks = {
                "day": (DAYS_PER_YEAR, by, bx),
                "cell": (by, bx),
                "base": (max(nbase, 1), by, bx),
            }
            for var in THRESHOLD_VARIABLES:
                if var.kind == "base" and "base_time" not in nc.variables:
                    bt = nc.createVariable("base_time", "f8", ("base_time",))
                    bt.setncatts(
                        {
                            "units": f"days since {origin}",
                            "long_name": "time",
                            "calendar": "proleptic_gregorian",
                        }
                    )
                    bt[:] = base_time
                v = nc.createVariable(
                    var.name,
                    "f8",
                    dims[var.kind],
                    fill_value=FILL_VALUE,
                    zlib=True,
                    complevel=4,
                    chunksizes=chunks[var.kind],
                )
                # Blocks are written whole chunks at a time, so a chunk need not stay
                # cached once written; HDF5's default (64 MB per variable) would keep
                # up to 1.3 GB of written chunks for the 21 variables.
                v.set_var_chunk_cache(size=OUTPUT_CHUNK_CACHE, nelems=101, preemption=1.0)
                v.setncatts(
                    {
                        "units": var.units,
                        "long_name": var.long_name,
                        "history": history,
                        "base_period": f"{base_start}-{base_end}",
                    }
                )
        except BaseException:
            nc.close()
            raise
    return nc


def _base_dates(time: pd.DatetimeIndex, base_start: int, base_end: int) -> pd.DatetimeIndex:
    full = filled_dates(time)
    return full[(full.year >= base_start) & (full.year <= base_end)]


def _write_block(nc: netCDF4.Dataset, block, result: dict[str, np.ndarray]) -> None:
    ys, xs = block
    for var in THRESHOLD_VARIABLES:
        values = result[var.name]
        if var.kind != "cell":
            values = np.moveaxis(values, -1, 0)  # (y, x, t) -> (t, y, x)
        index = (ys, xs) if var.kind == "cell" else (slice(None), ys, xs)
        nc.variables[var.name][index] = np.ma.masked_invalid(values)


def block_thresholds(
    data: Mapping[str, np.ndarray],
    time: pd.DatetimeIndex,
    base_start: int,
    base_end: int,
    pool: ThreadPoolExecutor | None = None,
    cells_per_batch: int = DEFAULT_CELLS_PER_BATCH,
) -> dict[str, np.ndarray]:
    """:func:`cell_thresholds` of a block, ``{variable: (y, x, time)}``, computed in
    batches of ``cells_per_batch`` cells (on ``pool`` if given) to bound the memory used.
    """
    ny, nx, nt = data["tasmax"].shape
    flat = {v: data[v].reshape(ny * nx, nt) for v in ("tasmax", "tasmin", "pr")}
    starts = range(0, ny * nx, max(cells_per_batch, 1))

    def batch(start: int) -> dict[str, np.ndarray]:
        part = {v: a[start : start + cells_per_batch] for v, a in flat.items()}
        return cell_thresholds(
            part["tasmax"], part["tasmin"], part["pr"], time, base_start, base_end
        )

    parts = list(pool.map(batch, starts) if pool else map(batch, starts))
    return {
        name: np.concatenate([p[name] for p in parts]).reshape(ny, nx, *parts[0][name].shape[1:])
        for name in parts[0]
    }


def write_grid_thresholds(
    inp: GriddedInput,
    path: str | Path,
    base_start: int = 1971,
    base_end: int = 2000,
    author: Mapping[str, str] | None = None,
    workers: int = 1,
    progress: Progress | None = None,
    cells_per_batch: int = DEFAULT_CELLS_PER_BATCH,
) -> Path:
    """Compute the thresholds of every cell of ``inp`` and write them to ``path`` in the
    layout of Climpact's thresholds netCDF (``create.thresholds.from.file``).

    The blocks of ``inp`` (its dask chunks) are read one at a time, computed in batches
    of ``cells_per_batch`` cells by ``workers`` threads, and written before the next
    block is read, so memory is bounded by one block and ``workers`` batches whatever
    the size of the grid. ``author`` may give ``institution``, ``institution_id``,
    ``indices_archive``, ``contact`` and ``references`` (R's ``author.data``).
    ``progress("thresholds", done, total)`` is called after each block (see
    :mod:`climpact.progress`). The file is written under a
    temporary name and renamed when complete.
    """
    time = inp.time
    check_base_period(time, base_start, base_end)
    path = Path(path)
    blocks = list(inp.blocks())
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    nc = create_thresholds_file(tmp, inp, base_start, base_end, author)
    try:
        with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
            for done, block in enumerate(blocks, start=1):
                data = inp.load(block)  # netCDF reads and writes stay in this thread
                result = block_thresholds(
                    data,
                    time,
                    base_start,
                    base_end,
                    pool if workers > 1 else None,
                    cells_per_batch,
                )
                del data
                _write_block(nc, block, result)
                del result
                if progress:
                    progress("thresholds", done, len(blocks))
        nc.close()
    except BaseException:
        nc.close()
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(path)
    return path


__all__ = [
    "THRESHOLD_VARIABLES",
    "ThresholdVariable",
    "block_thresholds",
    "cell_thresholds",
    "check_base_period",
    "create_thresholds_file",
    "write_grid_thresholds",
]
