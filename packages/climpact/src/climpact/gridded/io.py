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
- **Time** is truncated to whole days; all files must have the same time axis. The
  ``noleap`` (``365_day``) and ``360_day`` calendars are read as a
  :class:`~climpact.calendars.CalendarDays` axis, as PCICt reads them in R.

Each variable is converted to float64 before any arithmetic, as R reads every value as
a double. The data are opened lazily with dask, chunked in blocks of cells with the
whole time series in each chunk (percentiles need every day of a cell), so a grid of
any size is processed one block at a time.

Files chunked by time step over the whole grid (common in model output) would be read in
full for every block. :meth:`GriddedInput.block_reader` then first copies the raw values,
one slab of time steps at a time, to a temporary file of tiles (time slab x block) and
reads the blocks from it (see :data:`RECHUNK_AMPLIFICATION`). The values read are the
same either way.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import tempfile
import warnings
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import netCDF4
import numpy as np
import pandas as pd
import xarray as xr

from climpact.calendars import CalendarDays, DayAxis, canonical_calendar
from climpact.progress import Progress, Steps

VARIABLES = ("tasmax", "tasmin", "pr")
DEFAULT_NAMES = {"tasmax": "tasmax", "tasmin": "tasmin", "pr": "pr"}
# Values (cells x days x 3 variables) read at once; climdex.pcic.ncdf's max.vals.millions
# is 10 million.
DEFAULT_MAX_VALUES = 5_000_000

# Rechunk automatically when reading the blocks straight from the files would decompress
# their data at least this many times over (see GriddedInput.read_amplification).
RECHUNK_AMPLIFICATION = 4.0

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


def _to_climpact_units(raw: xr.DataArray, variable: str) -> xr.DataArray:
    """``raw`` (as opened with ``mask_and_scale=False``) decoded as ncdf4 does and
    converted to Climpact's units as udunits does, in float64."""
    scale, offset = unit_conversion(variable, raw.attrs.get("units"))
    x = decode_ncdf4(raw)
    if offset != 0.0:
        x = x + offset  # udunits: value - 273.15
    elif scale != 1.0:
        x = x * scale  # udunits: value * 86400
    x.attrs = {"units": "kg m-2 d-1" if variable == "pr" else "degrees_C"}
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

    ``max_values``, ``rechunk`` and ``tmp_dir`` are :func:`open_grid`'s options of the
    same names, used by :meth:`block_reader`. ``calendar_days`` holds the time axis of
    data in the ``noleap`` or ``360_day`` calendar (``data`` then has no time
    coordinate); None for the standard calendar.
    """

    data: xr.Dataset
    files: Mapping[str, Path]
    names: Mapping[str, str]
    time_dim: str
    y_dim: str
    x_dim: str
    max_values: int = DEFAULT_MAX_VALUES
    rechunk: bool | None = None
    tmp_dir: Path | None = None
    calendar_days: CalendarDays | None = None

    @property
    def exemplar(self) -> Path:
        return self.files["tasmax"]

    @property
    def time(self) -> DayAxis:
        """The days of the data: a ``DatetimeIndex``, or a
        :class:`~climpact.calendars.CalendarDays` in the ``noleap`` and ``360_day``
        calendars."""
        if self.calendar_days is not None:
            return self.calendar_days
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

    def read_amplification(self) -> float:
        """How many times over reading every block straight from the files decompresses
        their data: the largest, over the three variables, of the area of the files'
        chunks the blocks touch divided by the area of the grid. 1 for files chunked by
        cell or by block, about the number of blocks for files chunked by time step over
        the whole grid. Contiguous (and netCDF-3) variables count as 1.
        """
        ny, nx = self.shape
        blocks = list(self.blocks())
        worst = 1.0
        for v in VARIABLES:
            with netCDF4.Dataset(self.files[v]) as nc:
                var = nc.variables[self.names[v]]
                chunking = var.chunking()
                dims = var.dimensions
            if not isinstance(chunking, list):
                continue
            size = dict(zip(dims, chunking, strict=True))
            cy, cx = size[self.y_dim], size[self.x_dim]
            area = 0
            for ys, xs in blocks:
                rows = (ys.stop - 1) // cy - ys.start // cy + 1
                cols = (xs.stop - 1) // cx - xs.start // cx + 1
                area += min(rows * cy, ny) * min(cols * cx, nx)
            worst = max(worst, area / (ny * nx))
        return worst

    def rechunk_bytes(self) -> int:
        """Size of the temporary file a rechunk writes: the raw values of the three
        variables, in their file types."""
        nt = self.data.sizes[self.time_dim]
        ny, nx = self.shape
        total = 0
        for v in VARIABLES:
            with netCDF4.Dataset(self.files[v]) as nc:
                total += nt * ny * nx * nc.variables[self.names[v]].dtype.itemsize
        return total

    def will_rechunk(self) -> bool:
        """Whether :meth:`block_reader` rechunks: always with ``rechunk=True``, never
        with ``False``, and with ``None`` (automatic) when :meth:`read_amplification` is
        at least :data:`RECHUNK_AMPLIFICATION` and the temporary directory has room for
        the copy (with a warning when it has not)."""
        if self.rechunk is not None:
            return self.rechunk
        if self.read_amplification() < RECHUNK_AMPLIFICATION:
            return False
        need, free = self.rechunk_bytes(), _free_bytes(self.tmp_dir)
        if need > 0.9 * free:
            warnings.warn(
                f"not rechunking the input: it needs {need / 1e9:.1f} GB in "
                f"{self.tmp_dir or tempfile.gettempdir()}, {free / 1e9:.1f} GB free; "
                "every block reads the whole file instead",
                RuntimeWarning,
                stacklevel=2,
            )
            return False
        return True

    @contextmanager
    def block_reader(
        self, progress: Progress | None = None, blocks: int | None = None
    ) -> Iterator[BlockReader]:
        """A :class:`BlockReader` for the blocks of this input, rechunked first to a
        temporary file when :meth:`will_rechunk`.

        ``progress("rechunk", step, total)`` is called after each time slab copied, and
        ``total`` also counts the ``blocks`` (default: every block) that the caller
        reports with ``reader.steps.done(stage)``. The temporary file, in ``tmp_dir``
        (default: the system's temporary directory), is deleted when the context exits,
        also on error.
        """
        if blocks is None:
            blocks = sum(1 for _ in self.blocks())
        if not self.will_rechunk():
            yield BlockReader(self, Steps(progress, blocks))
            return
        need, free = self.rechunk_bytes(), _free_bytes(self.tmp_dir)
        if need > free:
            raise OSError(
                f"rechunking the input needs {need / 1e9:.1f} GB in "
                f"{self.tmp_dir or tempfile.gettempdir()}, {free / 1e9:.1f} GB free"
            )
        slabs = _time_slabs(self)
        steps = Steps(progress, len(slabs) + blocks)
        fd, name = tempfile.mkstemp(prefix="climpact-rechunk-", suffix=".bin", dir=self.tmp_dir)
        try:
            # Removed from the directory at once where the system allows it (not Windows),
            # so that the space is freed however the process ends, even when killed.
            os.unlink(name)
            unlinked = True
        except OSError:
            unlinked = False
        try:
            with os.fdopen(fd, "w+b", buffering=0) as f:
                tiles = _TileFile.write(self, f, slabs, steps)
                yield BlockReader(self, steps, tiles)
        finally:
            if not unlinked:
                Path(name).unlink(missing_ok=True)

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


class BlockReader:
    """Reads the blocks of a :class:`GriddedInput`, from its files or from a rechunked
    temporary copy; made by :meth:`GriddedInput.block_reader`. ``steps`` counts the
    run's progress steps (see :mod:`climpact.progress`); ``rechunked`` says whether the
    blocks come from the temporary copy."""

    def __init__(self, inp: GriddedInput, steps: Steps, tiles: _TileFile | None = None):
        self.inp = inp
        self.steps = steps
        self._tiles = tiles

    @property
    def rechunked(self) -> bool:
        return self._tiles is not None

    def load(self, block: tuple[slice, slice]) -> dict[str, np.ndarray]:
        """The values of one block, ``{variable: array (y, x, time)}``, identical to
        :meth:`GriddedInput.load`."""
        if self._tiles is None:
            return self.inp.load(block)
        return self._tiles.load(block)


def _free_bytes(directory: Path | None) -> int:
    return shutil.disk_usage(directory or tempfile.gettempdir()).free


def _time_slabs(inp: GriddedInput) -> list[tuple[int, int]]:
    """Slabs of time steps of the whole grid holding at most ``max_values`` values of one
    variable (at least one time step), a multiple of the files' time chunks if they fit,
    so that each chunk is decompressed once."""
    nt = inp.data.sizes[inp.time_dim]
    ny, nx = inp.shape
    length = max(1, inp.max_values // (ny * nx))
    chunk = 1
    for v in VARIABLES:
        with netCDF4.Dataset(inp.files[v]) as nc:
            var = nc.variables[inp.names[v]]
            chunking = var.chunking()
            if isinstance(chunking, list):
                chunk = max(chunk, dict(zip(var.dimensions, chunking, strict=True))[inp.time_dim])
    if chunk <= length:
        length -= length % chunk
    return [(t0, min(t0 + length, nt)) for t0 in range(0, nt, length)]


def _block_key(block: tuple[slice, slice]) -> tuple[int, int, int, int]:
    ys, xs = block  # slices are not hashable before Python 3.12
    return ys.start, ys.stop, xs.start, xs.stop


class _TileFile:
    """The raw values of the three variables in a temporary file of tiles: for each time
    slab, each variable and each block, the block's values for the slab's days, in the
    file's own type, ``(time, y, x)``. Written in one sequential pass over the input;
    a block is read back with one read per slab and variable."""

    def __init__(self, inp, f, slabs, blocks, offsets, dtypes, attrs):
        self.inp = inp
        self.f = f
        self.slabs = slabs
        self.blocks = blocks
        self.offsets = offsets
        self.dtypes = dtypes
        self.attrs = attrs

    @classmethod
    def write(cls, inp: GriddedInput, f, slabs, steps: Steps) -> _TileFile:
        dims = (inp.time_dim, inp.y_dim, inp.x_dim)
        blocks = {_block_key(b): i for i, b in enumerate(inp.blocks())}
        offsets = np.zeros((len(slabs), len(VARIABLES), len(blocks)), dtype=np.int64)
        dtypes, attrs = {}, {}
        for v in VARIABLES:
            # The raw variable as open_grid sees it (its type and attributes decide the
            # decoding).
            with xr.open_dataset(inp.files[v], mask_and_scale=False, decode_times=True) as ds:
                dtypes[v] = ds[inp.names[v]].dtype
                attrs[v] = dict(ds[inp.names[v]].attrs)
        opened: dict[Path, netCDF4.Dataset] = {}
        try:
            variables = {}
            for v in VARIABLES:
                path = inp.files[v]
                if path not in opened:
                    opened[path] = netCDF4.Dataset(path)
                var = opened[path].variables[inp.names[v]]
                var.set_auto_maskandscale(False)
                variables[v] = var
            position = 0
            for k, (t0, t1) in enumerate(slabs):
                for j, v in enumerate(VARIABLES):
                    var = variables[v]
                    index = tuple(
                        slice(t0, t1) if d == inp.time_dim else slice(None) for d in var.dimensions
                    )
                    order = [var.dimensions.index(d) for d in dims]
                    slab = np.asarray(var[index], dtype=dtypes[v]).transpose(order)
                    for ys, xs in inp.blocks():
                        i = blocks[_block_key((ys, xs))]
                        tile = np.ascontiguousarray(slab[:, ys, xs])
                        offsets[k, j, i] = position
                        f.write(memoryview(tile).cast("B"))
                        position += tile.nbytes
                    del slab
                steps.done("rechunk")
        finally:
            for nc in opened.values():
                nc.close()
        return cls(inp, f, slabs, blocks, offsets, dtypes, attrs)

    def load(self, block: tuple[slice, slice]) -> dict[str, np.ndarray]:
        inp = self.inp
        i = self.blocks[_block_key(block)]
        ys, xs = block
        shape = (inp.data.sizes[inp.time_dim], ys.stop - ys.start, xs.stop - xs.start)
        out = {}
        for j, v in enumerate(VARIABLES):
            values = np.empty(shape, dtype=self.dtypes[v])
            for k, (t0, t1) in enumerate(self.slabs):
                view = memoryview(values[t0:t1]).cast("B")
                self.f.seek(int(self.offsets[k, j, i]))
                done = 0
                while done < len(view):
                    n = self.f.readinto(view[done:])
                    if not n:
                        raise OSError("rechunked file is truncated")
                    done += n
            raw = xr.DataArray(
                values, dims=(inp.time_dim, inp.y_dim, inp.x_dim), attrs=self.attrs[v]
            )
            x = _to_climpact_units(raw, v)
            out[v] = x.transpose(inp.y_dim, inp.x_dim, inp.time_dim).values
        return out


def _find(datasets: dict[Path, xr.Dataset], name: str) -> Path:
    found = [path for path, ds in datasets.items() if name in ds.data_vars]
    if not found:
        raise ValueError(f"variable {name!r} not found in {[str(p) for p in datasets]}")
    if len(found) > 1:
        raise ValueError(f"variable {name!r} is present in more than one input file")
    return found[0]


def _days(coord: xr.DataArray, name: str) -> DayAxis:
    """The decoded time coordinate truncated to days: a ``DatetimeIndex``, or a
    :class:`~climpact.calendars.CalendarDays` for the ``noleap`` and ``360_day``
    calendars (decoded by xarray to cftime dates)."""
    t = coord.values
    if np.issubdtype(t.dtype, np.datetime64):
        return pd.DatetimeIndex(t).normalize()
    calendar = getattr(t[0], "calendar", None) if t.size else None
    if not calendar:
        raise ValueError(f"{name}: cannot decode the time axis")
    canonical = canonical_calendar(calendar)
    if canonical is None:  # standard dates outside numpy's range
        raise NotImplementedError(f"{name}: dates outside the years 1678-2261")
    return CalendarDays.from_cftime(t, canonical)


def _block_shape(ny: int, nx: int, cells: int) -> tuple[int, int]:
    """Rows of the whole width when they fit in ``cells``, else part of one row."""
    if cells >= nx:
        return min(ny, cells // nx), nx
    return 1, max(cells, 1)


def open_grid(
    files: Sequence[str | Path],
    names: Mapping[str, str] | None = None,
    max_values: int = DEFAULT_MAX_VALUES,
    rechunk: bool | None = None,
    tmp_dir: str | Path | None = None,
) -> GriddedInput:
    """Open TX, TN and precipitation from one or more CF netCDF files.

    ``names`` maps ``tasmax``, ``tasmin`` and ``pr`` to the netCDF variable names
    (default: the same names). Each variable must be in exactly one file, with
    dimensions time, Y and X, and the files must share the time axis. Times may use the
    standard (Gregorian), ``noleap`` (``365_day``) or ``360_day`` calendar.

    The data are chunked in blocks of whole Y rows (or parts of a row) holding at most
    ``max_values`` values of the three variables, like climdex.pcic.ncdf's stripes
    (``axis.to.split.on = "Y"``, ``max.vals.millions``). A block is the unit read from
    the files; it is computed in smaller batches of cells.

    ``rechunk`` says whether the blocks are read from a temporary copy of the input
    rechunked by block (``True``), straight from the files (``False``) or, by default,
    whichever is faster (see :meth:`GriddedInput.will_rechunk`); ``tmp_dir`` is where
    the copy is written (default: the system's temporary directory).
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
        t = _days(raw[time_dim], names[v])
        if time is None:
            time = t
        elif not time.equals(t):
            raise ValueError("the input files do not have the same time axis")
        if raw.sizes != first.sizes:
            raise ValueError(f"{names[v]} does not have the grid of {names['tasmax']}")
        x = _to_climpact_units(raw.transpose(time_dim, y_dim, x_dim), v).drop_vars(time_dim)
        variables[v] = x if isinstance(time, CalendarDays) else x.assign_coords({time_dim: time})
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
        max_values=max_values,
        rechunk=rechunk,
        tmp_dir=None if tmp_dir is None else Path(tmp_dir),
        calendar_days=time if isinstance(time, CalendarDays) else None,
    )


__all__ = [
    "DEFAULT_MAX_VALUES",
    "RECHUNK_AMPLIFICATION",
    "BlockReader",
    "GriddedInput",
    "VARIABLES",
    "decode_ncdf4",
    "open_grid",
    "unit_conversion",
]
