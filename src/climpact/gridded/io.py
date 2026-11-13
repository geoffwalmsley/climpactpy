"""Read gridded daily data from CF netCDF files, as climdex.pcic.ncdf does.

Climpact's gridded code (its modified climdex.pcic.ncdf 0.5-4, ``create.file.metadata``
and ``get.data``) reads TX, TN and precipitation with ncdf4 and converts them with
udunits2. Reproduced here, because it changes the values the thresholds are computed
from:

- **Missing values** (ncdf4 ``ncvar_get``): the variable's ``missing_value`` attribute,
  or else its ``_FillValue``, or else 1e30 for float and double variables. Float and
  double values within ``1e-5 * |missing value|`` of it are missing (``1e-10`` if it is
  0); integer values only when equal to it. The netCDF default fill value is *not*
  missing unless an attribute says so.
- **Packing:** ``value * scale_factor + add_offset`` in double precision, after masking.
- **Units** (udunits2 ``ud.convert``): temperatures to ``degrees_C`` (from kelvin,
  ``value - 273.15``), precipitation to ``kg m-2 d-1`` (from ``kg m-2 s-1``,
  ``value * 86400``). Both are exactly what udunits computes.
- **Time** is truncated to whole days; all files must have the same time axis.

Each variable is converted to float64 before any arithmetic, as R reads every value as
a double. The data are opened lazily with dask, chunked in blocks of cells with the
whole time series in each chunk (percentiles need every day of a cell), so a grid of
any size is processed one block at a time.
"""

from __future__ import annotations

import math
import re
import warnings
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

VARIABLES = ("tasmax", "tasmin", "pr")
DEFAULT_NAMES = {"tasmax": "tasmax", "tasmin": "tasmin", "pr": "pr"}
# Values (cells x days x 3 variables) read at once; climdex.pcic.ncdf's max.vals.millions
# is 10 million.
DEFAULT_MAX_VALUES = 5_000_000

NCDF4_DEFAULT_MISSING = 1e30  # ncdf4 default_missval_ncdf4(), for float and double

_CELSIUS = {
    "degc",
    "deg_c",
    "degree_c",
    "degrees_c",
    "celsius",
    "degree_celsius",
    "degrees_celsius",
}
_KELVIN = {"k", "kelvin", "degk", "deg_k", "degree_k", "degrees_k"}
_PER_DAY = {"kg m-2 d-1", "kg m-2 day-1", "kg m^-2 d^-1", "kg/m2/d", "kg/m2/day", "kg/m^2/d"}
_PER_SECOND = {"kg m-2 s-1", "kg m^-2 s^-1", "kg/m2/s", "kg/m^2/s"}
# Not convertible by udunits, so refused by R; accepted here as the same as kg m-2 d-1.
_MM_PER_DAY = {"mm/day", "mm/d", "mm d-1", "mm day-1", "mm"}

_AXIS_NAMES = {
    "T": {"time", "t"},
    "Y": {"lat", "latitude", "y", "rlat", "nav_lat", "yc", "j"},
    "X": {"lon", "longitude", "x", "rlon", "nav_lon", "xc", "i"},
}
_AXIS_STANDARD_NAMES = {
    "T": {"time"},
    "Y": {"latitude", "projection_y_coordinate", "grid_latitude"},
    "X": {"longitude", "projection_x_coordinate", "grid_longitude"},
}


def _normalise_units(units: str) -> str:
    return re.sub(r"\s+", " ", units.strip()).lower()


def unit_conversion(variable: str, units: str | None) -> tuple[float, float]:
    """``(scale, offset)`` that convert ``variable`` from ``units`` to Climpact's units
    (``degrees_C``, ``kg m-2 d-1``) as ``value * scale + offset``.

    Raises ``ValueError`` for units R's udunits2 conversion would not accept (``mm/day``
    and similar are accepted as ``kg m-2 d-1``).
    """
    if units is None:
        raise ValueError(f"{variable} has no units attribute")
    u = _normalise_units(units)
    if variable in ("tasmax", "tasmin"):
        if u in _CELSIUS:
            return 1.0, 0.0
        if u in _KELVIN:
            return 1.0, -273.15
        raise ValueError(f"{variable}: unsupported units {units!r} (use K or degrees_C)")
    if u in _PER_DAY or u in _MM_PER_DAY:
        return 1.0, 0.0
    if u in _PER_SECOND:
        return 86400.0, 0.0
    raise ValueError(f"{variable}: unsupported units {units!r} (use kg m-2 d-1 or kg m-2 s-1)")


def _scalar_attr(value) -> float:
    return float(np.asarray(value).ravel()[0])


def decode_ncdf4(raw: xr.DataArray) -> xr.DataArray:
    """Mask and unpack ``raw`` (opened with ``mask_and_scale=False``) as ncdf4's
    ``ncvar_get`` does, returning float64."""
    attrs = raw.attrs
    kind = raw.dtype.kind
    if "missing_value" in attrs:
        missing = _scalar_attr(attrs["missing_value"])
    elif "_FillValue" in attrs:
        missing = _scalar_attr(attrs["_FillValue"])
    elif kind == "f":
        missing = NCDF4_DEFAULT_MISSING
    else:
        missing = None
    x = raw.astype(np.float64)
    if missing is not None and not math.isnan(missing):
        if kind == "f":
            tolerance = 1e-10 if missing == 0 else abs(missing) * 1e-5
            x = x.where(~(np.abs(x - missing) < tolerance))
        else:
            x = x.where(x != missing)
    if "scale_factor" in attrs or "add_offset" in attrs:
        scale = _scalar_attr(attrs.get("scale_factor", 1.0))
        offset = _scalar_attr(attrs.get("add_offset", 0.0))
        x = x * scale + offset
    return x


def _axis(ds: xr.Dataset, dim: str) -> str | None:
    """The CF axis (T, Y or X) of a dimension, from its coordinate variable's ``axis``
    or ``standard_name`` attribute, or else its name (as ncdf4.helpers does)."""
    attrs = ds[dim].attrs if dim in ds.variables else {}
    if str(attrs.get("axis", "")).upper() in ("T", "Y", "X"):
        return str(attrs["axis"]).upper()
    for axis, names in _AXIS_STANDARD_NAMES.items():
        if attrs.get("standard_name") in names:
            return axis
    for axis, names in _AXIS_NAMES.items():
        if dim.lower() in names:
            return axis
    return None


@dataclass(frozen=True)
class GriddedInput:
    """Daily TX, TN and precipitation on a grid, read lazily.

    ``data`` holds ``tasmax``, ``tasmin`` (degrees C) and ``pr`` (kg m-2 d-1) as float64
    dask arrays with dimensions ``(time, y_dim, x_dim)``, chunked in blocks of cells
    with the whole time series in each chunk. ``files`` and ``names`` give the file and
    netCDF variable name of each; the file of ``tasmax`` is R's exemplar file, whose
    coordinates and attributes outputs copy.
    """

    data: xr.Dataset
    files: Mapping[str, Path]
    names: Mapping[str, str]
    time_dim: str
    y_dim: str
    x_dim: str

    @property
    def exemplar(self) -> Path:
        return self.files["tasmax"]

    @property
    def time(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(self.data[self.time_dim].values)

    @property
    def shape(self) -> tuple[int, int]:
        return self.data.sizes[self.y_dim], self.data.sizes[self.x_dim]

    def blocks(self) -> Iterator[tuple[slice, slice]]:
        """The blocks of cells, ``(y slice, x slice)``, matching the dask chunks."""
        y_chunks, x_chunks = (self.data.chunks[self.y_dim], self.data.chunks[self.x_dim])
        y0 = 0
        for ny in y_chunks:
            x0 = 0
            for nx in x_chunks:
                yield slice(y0, y0 + ny), slice(x0, x0 + nx)
                x0 += nx
            y0 += ny

    def load(self, block: tuple[slice, slice]) -> dict[str, np.ndarray]:
        """The values of one block, ``{variable: array (y, x, time)}``."""
        ys, xs = block
        sub = self.data.isel({self.y_dim: ys, self.x_dim: xs})
        sub = sub.transpose(self.y_dim, self.x_dim, self.time_dim)
        return {v: sub[v].compute(scheduler="synchronous").values for v in VARIABLES}

    def cell_latitude(self) -> xr.DataArray:
        """The latitude of every cell, ``(y_dim, x_dim)``.

        From the Y coordinate when it is latitude, or else from a two-dimensional
        latitude variable of the exemplar file over ``(y, x)`` (climdex.pcic.ncdf
        ``get.northern.hemisphere.booleans`` with ``project.lat2d.coords = FALSE``).
        """
        y = self.data[self.y_dim]
        ys = str(y.attrs.get("standard_name", ""))
        units = str(y.attrs.get("units", ""))
        if ys == "latitude" or (units.startswith("degree") and "north" in units):
            return y.broadcast_like(self.data[self.x_dim]).transpose(self.y_dim, self.x_dim)
        with xr.open_dataset(self.exemplar, decode_times=False) as ds:
            for var in ds.variables.values():
                if var.attrs.get("standard_name") == "latitude" and set(var.dims) == {
                    self.y_dim,
                    self.x_dim,
                }:
                    return var.load().transpose(self.y_dim, self.x_dim)
        raise NotImplementedError("projected grid without a two-dimensional latitude variable")


def _find(datasets: dict[Path, xr.Dataset], name: str) -> Path:
    found = [path for path, ds in datasets.items() if name in ds.data_vars]
    if not found:
        raise ValueError(f"variable {name!r} not found in {[str(p) for p in datasets]}")
    if len(found) > 1:
        raise ValueError(f"variable {name!r} is present in more than one input file")
    return found[0]


def _block_shape(ny: int, nx: int, cells: int) -> tuple[int, int]:
    """Rows of the whole width when they fit in ``cells``, else part of one row."""
    if cells >= nx:
        return min(ny, cells // nx), nx
    return 1, max(cells, 1)


def open_grid(
    files: Sequence[str | Path],
    names: Mapping[str, str] | None = None,
    max_values: int = DEFAULT_MAX_VALUES,
) -> GriddedInput:
    """Open TX, TN and precipitation from one or more CF netCDF files.

    ``names`` maps ``tasmax``, ``tasmin`` and ``pr`` to the netCDF variable names
    (default: the same names). Each variable must be in exactly one file, with
    dimensions time, Y and X, and the files must share the time axis. Times must use
    the standard (Gregorian) calendar.

    The data are chunked in blocks of whole Y rows (or parts of a row) holding at most
    ``max_values`` values of the three variables, like climdex.pcic.ncdf's stripes
    (``axis.to.split.on = "Y"``, ``max.vals.millions``). A block is the unit read from
    the files; it is computed in smaller batches of cells.
    """
    names = {**DEFAULT_NAMES, **(names or {})}
    paths = [Path(f) for f in files]
    if not paths:
        raise ValueError("at least one input file is needed")
    datasets = {p: xr.open_dataset(p, mask_and_scale=False, decode_times=True) for p in paths}
    where = {v: _find(datasets, names[v]) for v in VARIABLES}

    first = datasets[where["tasmax"]][names["tasmax"]]
    axes = {}
    for dim in first.dims:
        axis = _axis(datasets[where["tasmax"]], dim)
        if axis is None or axis in axes:
            raise ValueError(f"{names['tasmax']}: cannot tell the axis of dimension {dim!r}")
        axes[axis] = dim
    if set(axes) != {"T", "Y", "X"}:
        raise ValueError(f"{names['tasmax']}: expected dimensions time, Y and X, got {first.dims}")
    time_dim, y_dim, x_dim = axes["T"], axes["Y"], axes["X"]

    cells = max_values // (len(VARIABLES) * first.sizes[time_dim])
    by, bx = _block_shape(first.sizes[y_dim], first.sizes[x_dim], cells)
    chunks = {time_dim: -1, y_dim: by, x_dim: bx}
    # Opened again with the blocks as dask chunks, so that reading a block reads only its
    # cells (rechunking from the file's own chunks would read whole time slices).
    for path in set(where.values()):
        with warnings.catch_warnings():
            # Blocks that split the files' own chunks are intended.
            warnings.filterwarnings("ignore", "The specified chunks separate", UserWarning)
            datasets[path] = xr.open_dataset(
                path, mask_and_scale=False, decode_times=True, chunks=chunks
            )
    time = None
    variables = {}
    for v in VARIABLES:
        raw = datasets[where[v]][names[v]]
        if set(raw.dims) != set(first.dims):
            raise ValueError(f"{names[v]} does not have the dimensions of {names['tasmax']}")
        t = raw[time_dim].values
        if not np.issubdtype(t.dtype, np.datetime64):
            raise NotImplementedError(
                f"{names[v]}: only the standard (Gregorian) calendar is supported"
            )
        t = pd.DatetimeIndex(t).normalize()
        if time is None:
            time = t
        elif not time.equals(t):
            raise ValueError("the input files do not have the same time axis")
        if raw.sizes != first.sizes:
            raise ValueError(f"{names[v]} does not have the grid of {names['tasmax']}")
        scale, offset = unit_conversion(v, raw.attrs.get("units"))
        x = decode_ncdf4(raw.transpose(time_dim, y_dim, x_dim))
        if offset != 0.0:
            x = x + offset  # udunits: value - 273.15
        elif scale != 1.0:
            x = x * scale  # udunits: value * 86400
        x.attrs = {"units": "kg m-2 d-1" if v == "pr" else "degrees_C"}
        variables[v] = x.drop_vars(time_dim).assign_coords({time_dim: time})
    if not time.is_unique:
        raise ValueError("the time axis has a day more than once")
    data = xr.Dataset(variables)
    return GriddedInput(
        data=data,
        files=where,
        names={v: names[v] for v in VARIABLES},
        time_dim=time_dim,
        y_dim=y_dim,
        x_dim=x_dim,
    )


__all__ = [
    "DEFAULT_MAX_VALUES",
    "GriddedInput",
    "VARIABLES",
    "decode_ncdf4",
    "open_grid",
    "unit_conversion",
]
