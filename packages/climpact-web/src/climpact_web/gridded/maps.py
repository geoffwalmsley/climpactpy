"""The gridded results (#85, #295): the output files, one index variable of one file as a
layer, a map of it at one time step and the series of one cell.

The map (#295, the GridMap board) draws every cell, never thinned: the field is a PNG
with one pixel per cell (:mod:`climpact_web.gridded.map_image`), scaled up in the page
without smoothing, under an SVG of the coastline and a few places
(:mod:`climpact_web.gridded.outline`), the axes in degrees and the selected cell's
outline. No map tiles or other network services are used (offline and low bandwidth).

- :func:`open_layer` reads a variable's metadata: its times (years, months or days of
  the year), SPI and SPEI's scales and the grid's coordinates; :func:`grid_values` one
  time step and :func:`cell_series` one cell's series.
- :func:`kind_of` chooses the colour scale by the index's kind (temperature, warm counts,
  cold counts, wet, dry; SPI and SPEI their standard classes) and :func:`edges_for` its
  eight bins' breaks: fixed for the file (round numbers over the values of every year,
  of the month for a monthly file), so the years compare.
- :class:`Frame` is the map's geometry: north up and west left whatever the order of the
  file's rows and columns, the latitude's cosine correcting the cells' aspect.
"""

from __future__ import annotations

import math
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from climpact_web.core import numbers
from climpact_web.gridded import netcdf, outline

FILE_RE = re.compile(r"^(?P<name>.+?)_(?P<freq>ANN|MON|DAY)_")
SKIP_VARIABLES = {"time", "time_bnds", "time_bounds", "bnds", "scale", "nb2"}


@dataclass
class OutputFile:
    path: str  # relative to the job's output folder
    name: str  # file name
    size: int
    index: str = ""  # e.g. txx, rx7day; "" for other files
    freq: str = ""  # ANN, MON, DAY


def output_files(job) -> list[OutputFile]:
    """The files a finished job wrote, index files sorted by name and frequency."""
    out = []
    for rel in job.result.get("files", []):
        path = job.output_dir / rel
        try:
            size = path.stat().st_size
        except OSError:
            continue
        m = FILE_RE.match(Path(rel).name)
        out.append(
            OutputFile(
                path=rel,
                name=Path(rel).name,
                size=size,
                index=m["name"] if m else "",
                freq=m["freq"] if m else "",
            )
        )
    order = {"ANN": 0, "MON": 1, "DAY": 2, "": 3}
    out.sort(key=lambda f: (f.index == "", f.index.lower(), order[f.freq]))
    return out


# ---- A layer: one index variable of one file ---------------------------------------------------


@dataclass
class Layer:
    """One index variable of one file: what the map and series need to know about it."""

    file: str
    variable: str
    variables: list[dict]  # {"name", "long_name", "units"} of every index variable
    long_name: str
    units: str
    times: list[str]  # a label per time step: "2019", "2019-12", the day of the year
    scales: list[str]  # SPI/SPEI: "3", "6", "12" (months); else []
    lat: list[float]
    lon: list[float]
    y_dim: str = ""
    x_dim: str = ""
    freq: str = "ANN"
    years: list[int] = field(default_factory=list)  # per time step (ANN, MON)
    months: list[int] = field(default_factory=list)  # per time step (MON), 1-12

    @property
    def geographic(self) -> bool:
        """Whether the grid's axes are latitude and longitude (not rotated or projected)."""
        return self.y_dim.lower() in ("lat", "latitude") and self.x_dim.lower() in (
            "lon",
            "longitude",
        )

    def step_of(self, year: int | None, month: int | None = None) -> int | None:
        """The time step of ``year`` (and ``month``); None when the file has no such step."""
        if year is None:
            return None
        for t, y in enumerate(self.years):
            if y == year and (not self.months or self.months[t] == (month or 12)):
                return t
        return None


def _decode_times(nc, freq: str) -> tuple[list[str], list[int], list[int]]:
    """The labels, years and months of the file's time steps."""
    import cftime

    time = nc.variables.get("time")
    if time is None:
        return [], [], []
    values = np.asarray(time[:], dtype=float)
    if freq == "DAY":  # tx95t: day of the year
        return [str(int(v)) for v in values], [], []
    units = getattr(time, "units", "")
    calendar = getattr(time, "calendar", "standard")
    try:
        dates = cftime.num2date(values, units, calendar)
    except (ValueError, TypeError):
        return [str(i + 1) for i in range(len(values))], [], []
    years = [int(d.year) for d in dates]
    if freq == "MON":
        months = [int(d.month) for d in dates]
        return [f"{y:04d}-{m:02d}" for y, m in zip(years, months, strict=True)], years, months
    return [f"{y:04d}" for y in years], years, []


def _coordinate(nc, var, axis: str) -> tuple[str, list[float]]:
    names = {"Y": ("lat", "latitude", "y", "rlat"), "X": ("lon", "longitude", "x", "rlon")}
    dims = var.dimensions[-2:]
    dim = dims[0] if axis == "Y" else dims[1]
    coord = nc.variables.get(dim)
    if coord is not None and coord.ndim == 1:
        return dim, [float(v) for v in np.asarray(coord[:], dtype=float)]
    for name in names[axis]:
        if name in nc.variables and nc.variables[name].ndim == 1:
            return name, [float(v) for v in np.asarray(nc.variables[name][:], dtype=float)]
    return dim, [float(i) for i in range(len(nc.dimensions[dim]))]


def index_variables(nc) -> list[dict]:
    out = []
    for name, var in nc.variables.items():
        if name in SKIP_VARIABLES or name.startswith("day_of_") or var.ndim < 3:
            continue
        if name in nc.dimensions:
            continue
        out.append(
            {
                "name": name,
                "long_name": str(getattr(var, "long_name", "") or name),
                "units": str(getattr(var, "units", "") or ""),
            }
        )
    return out


def data_variables(nc) -> list[str]:
    """The names of a file's gridded variables, as the run's Files tab lists them (#289):
    the index variables and the days they happened on (``txx``, ``day_of_txx``)."""
    return [
        name
        for name, var in nc.variables.items()
        if name not in SKIP_VARIABLES and name not in nc.dimensions and var.ndim >= 3
    ]


def open_layer(path: Path, rel: str, variable: str | None = None) -> Layer:
    """The layer of ``variable`` (default: the file's first index variable) in ``path``."""

    m = FILE_RE.match(path.name)
    freq = m["freq"] if m else "ANN"
    with netcdf.dataset(path) as nc:
        variables = index_variables(nc)
        if not variables:
            raise ValueError("no index variable")
        names = [v["name"] for v in variables]
        variable = variable if variable in names else names[0]
        var = nc.variables[variable]
        meta = variables[names.index(variable)]
        scales = []
        if "scale" in var.dimensions:
            scale = nc.variables.get("scale")
            values = [int(v) for v in scale[:]] if scale is not None else [1, 2, 3]
            months = {1: 3, 2: 6, 3: 12}
            scales = [str(months.get(v, v)) for v in values]
        y_dim, lat = _coordinate(nc, var, "Y")
        x_dim, lon = _coordinate(nc, var, "X")
        labels, years, month_numbers = _decode_times(nc, freq)
        return Layer(
            file=rel,
            variable=variable,
            variables=variables,
            long_name=meta["long_name"],
            units=meta["units"],
            times=labels,
            scales=scales,
            lat=lat,
            lon=lon,
            y_dim=y_dim,
            x_dim=x_dim,
            freq=freq,
            years=years,
            months=month_numbers,
        )


def _masked(values) -> np.ndarray:
    """Values as float32 with the fill value and non-finite values as NaN (EHF-HWPS can
    be -Inf in R's files; it is shown as no value)."""
    array = np.ma.filled(np.ma.asarray(values, dtype=np.float32), np.nan)
    array[~(np.isfinite(array) & (np.abs(array) < 1e19))] = np.nan
    return array


# The index files hold each cell's whole series in one chunk (the core writes them so),
# so one year's map reads and decompresses the whole file. A variable is therefore read
# once, whole, and kept in memory for the map's later requests (other years, the PNG, the
# values, the cell's series, the breaks): the most recently used ones, up to
# CACHE_BYTES in all. A variable larger than that is read a step or a cell at a time.
CACHE_BYTES = 256 * 1024 * 1024
_cache: OrderedDict[tuple, np.ndarray] = OrderedDict()
_cache_lock = threading.Lock()
_read_lock = threading.Lock()


def _key(path: Path, variable: str, scale: int) -> tuple:
    return (str(path), path.stat().st_mtime_ns, variable, scale)


def variable_values(path: Path, layer: Layer, scale: int = 0) -> np.ndarray | None:
    """The layer's values ``(time, y, x)`` as float32 (NaN where a cell has no value),
    read once and kept (see ``CACHE_BYTES``); None when the variable is too large."""

    key = _key(path, layer.variable, scale if layer.scales else 0)
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    with _read_lock:  # one read at a time: the page's image and values ask together
        with _cache_lock:
            if key in _cache:
                return _cache[key]
        with netcdf.dataset(path) as nc:
            var = nc.variables[layer.variable]
            shape = var.shape[1:] if layer.scales else var.shape
            if int(np.prod(shape)) * 4 > CACHE_BYTES:
                return None
            # Unmasked and cleaned in place: a masked array of a large grid costs more
            # than reading it.
            var.set_auto_mask(False)
            values = np.asarray(var[scale] if layer.scales else var[:], dtype=np.float32)
            for name in ("_FillValue", "missing_value"):
                if name in var.ncattrs():
                    values[values == np.float32(var.getncattr(name))] = np.nan
            values[~(np.abs(values) < 1e19)] = np.nan  # also NaN and infinities
        values.setflags(write=False)
        with _cache_lock:
            _cache[key] = values
            while sum(v.nbytes for v in _cache.values()) > CACHE_BYTES and len(_cache) > 1:
                _cache.popitem(last=False)
    return values


def grid_values(path: Path, layer: Layer, t: int, scale: int = 0) -> np.ndarray:
    """The ``(y, x)`` values of the layer at time step ``t`` (and SPI/SPEI scale), in the
    file's order."""

    whole = variable_values(path, layer, scale)
    if whole is not None:
        return whole[t]
    with netcdf.dataset(path) as nc:
        var = nc.variables[layer.variable]
        var.set_auto_mask(True)
        if layer.scales:
            return _masked(var[scale, t, :, :])
        return _masked(var[t, :, :])


def last_step_with_values(path: Path, layer: Layer, scale: int = 0, month: int | None = None):
    """The last time step (of ``month``, for a monthly file) where any cell has a value
    (heatwave seasons that run into the next year leave the last year empty, for example);
    the last step if none has."""
    steps = [
        t for t in range(len(layer.times)) if month is None or not layer.months
        or layer.months[t] == month
    ]  # fmt: skip
    for t in reversed(steps):
        if np.isfinite(grid_values(path, layer, t, scale)).any():
            return t
    return steps[-1] if steps else 0


def cell_series(path: Path, layer: Layer, y: int, x: int, scale: int = 0) -> np.ndarray:
    """The series of the file's cell ``(y, x)``, as float64."""

    whole = variable_values(path, layer, scale)
    if whole is not None:
        return whole[:, y, x].astype(float)
    with netcdf.dataset(path) as nc:
        var = nc.variables[layer.variable]
        var.set_auto_mask(True)
        if layer.scales:
            return _masked(var[scale, :, y, x]).astype(float)
        return _masked(var[:, y, x]).astype(float)


def format_value(value: float | None, digits: int = 2) -> str:
    """A value for the CSV files: up to ``digits`` places, no trailing zeros."""
    if value is None or not math.isfinite(value):
        return ""
    if value != 0 and abs(value) < 10**-digits:
        return f"{value:.2g}"
    text = f"{value:.{digits}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


# ---- The colour scale --------------------------------------------------------------------------

BINS = 8
# SPI and SPEI in their standard classes (McKee et al. 1993): extremely, severely and
# moderately dry, near normal, moderately, very and extremely wet. The ends are drawn at
# -3 and 3; values beyond them are in the end classes.
SPI_EDGES = (-3.0, -2.0, -1.5, -1.0, 1.0, 1.5, 2.0, 3.0)
# The units of the core's files, as the number rules write them (numbers.unit_label).
UNITS = {"degC": "degrees_C", "degC^2": "°C^2", "degrees_C": "degrees_C", "calendar day": "days"}
# Indices of no headline theme (averages, growing season and degree days) by what more of
# them means: warmer or cooler.
COOL_OTHERS = ("hddheatn", "tmlt5", "tmlt10")
# Values sampled to find a file's breaks: at most this many time steps and cells each.
SAMPLE_STEPS, SAMPLE_CELLS = 20, 250_000


def units_of(raw: str) -> str:
    """A file's units as the rest of the app names them (``degC`` is ``degrees_C``)."""
    return UNITS.get(raw, raw)


def kind_of(short: str, units: str, theme: str) -> str:
    """The colour scale of an index: ``spi`` for SPI and SPEI; ``temp`` for values in
    °C; else by its theme, ``warm`` (Heat), ``cool`` (Cold), ``wet`` (Rain), ``dry``
    (Drought); the other indices ``warm``, or ``cool`` where more means cooler."""
    if short in ("spi", "spei"):
        return "spi"
    if units_of(units) == "degrees_C":
        return "temp"
    if theme in ("cold",) or short in COOL_OTHERS:
        return "cool"
    return {"rain": "wet", "drought": "dry"}.get(theme, "warm")


def nice_edges(low: float, high: float, bins: int = BINS) -> list[float]:
    """``bins + 1`` round breaks a round step apart (1, 2, 2.5 or 5 times a power of ten),
    the first at or below ``low`` and the last at or above ``high``."""
    if not (math.isfinite(low) and math.isfinite(high)):
        return [float(k) for k in range(bins + 1)]
    if high <= low:
        spread = abs(low) * 0.1 or 1.0
        low, high = low - spread, high + spread
    rough = (high - low) / bins
    power = 10 ** math.floor(math.log10(rough))
    for m in (1, 2, 2.5, 5, 10, 20, 25, 50):
        step = m * power
        start = math.floor(low / step + 1e-9) * step
        if start + bins * step >= high - 1e-9 * step:
            break
    return [round(start + k * step, 10) for k in range(bins + 1)]


def _sampled_range(path: Path, layer: Layer, scale: int, steps: list[int]):
    """The 2nd and 98th percentiles of the values of ``steps``, from at most
    ``SAMPLE_CELLS`` cells each (every n-th row and column of a larger grid)."""
    ny, nx = len(layer.lat), len(layer.lon)
    stride = max(1, math.ceil(math.sqrt(ny * nx / SAMPLE_CELLS)))
    whole = variable_values(path, layer, scale)
    if whole is not None:
        sample = whole[steps, ::stride, ::stride]
    else:
        sample = np.stack([grid_values(path, layer, t, scale)[::stride, ::stride] for t in steps])
    found = sample[np.isfinite(sample)]
    if not found.size:
        return None
    low, high = np.percentile(found, [2, 98])
    return float(low), float(high)


_edges: dict[tuple, list[float] | None] = {}


def edges_for(path: Path, layer: Layer, kind: str, scale: int = 0, month: int | None = None):
    """The breaks of the layer's bins: SPI's classes, or round numbers over the values of
    every year (every year's ``month`` for a monthly file), so the map of one year
    compares with another's. None when the file has no value. Kept for the file."""
    if kind == "spi":
        return list(SPI_EDGES)
    key = (*_key(path, layer.variable, scale if layer.scales else 0), month)
    if key in _edges:
        return _edges[key]
    steps = [
        t for t in range(len(layer.times))
        if month is None or not layer.months or layer.months[t] == month
    ]  # fmt: skip
    if len(steps) > SAMPLE_STEPS:
        steps = sorted({steps[round(i * (len(steps) - 1) / (SAMPLE_STEPS - 1))]
                        for i in range(SAMPLE_STEPS)})  # fmt: skip
    found = _sampled_range(path, layer, scale if layer.scales else 0, steps)
    edges = None
    if found is not None:
        edges = nice_edges(*found)
        if found[0] >= 0 and edges[0] < 0:  # counts and amounts start at zero
            edges = nice_edges(0.0, found[1])
    if len(_edges) > 1024:
        _edges.clear()
    _edges[key] = edges
    return edges


def classify(values: np.ndarray, edges: list[float]) -> np.ndarray:
    """The bin of each value (0 to ``len(edges) - 2``, values beyond the ends in the end
    bins), 255 where there is no value."""
    inner = np.asarray(edges[1:-1], dtype=float)
    out = np.searchsorted(inner, np.nan_to_num(values, nan=0.0), side="right").astype(np.uint8)
    out[~np.isfinite(values)] = 255
    return out


def palette(kind: str, theme: str = "light") -> list[str]:
    """The bins' colours, from the tokens (chart-palette.json's values): the kind's
    ``--map-seq-*`` scale, or for SPI the seven-step diverging scale reversed, so dry is
    red and wet blue."""
    from climpact_web.core import tokens

    values = tokens.chart_palette()[theme]
    if kind == "spi":
        return list(reversed(values["diverging"]))
    return list(values["map_sequential"][kind])


def legend_ticks(edges: list[float]) -> list[str]:
    """The breaks as the legend writes them: as many places as the step needs."""
    step = min(b - a for a, b in zip(edges, edges[1:], strict=False))
    places = 0
    while places < 4 and abs(round(step, places) - step) > 1e-9 * max(abs(step), 1):
        places += 1
    return [numbers.fixed(e, places) for e in edges]


# ---- The map's frame ---------------------------------------------------------------------------

PLOT_W = 720.0  # SVG units: about the map's width in pixels at 1280-1440px
LEFT, RIGHT, TOP, BOTTOM = 56.0, 12.0, 8.0, 26.0
MAX_ASPECT = 2.5  # a taller grid is drawn this tall and scrolls with the page


def _step(values: list[float]) -> float:
    if len(values) < 2:
        return 1.0
    return abs(values[-1] - values[0]) / (len(values) - 1) or 1.0


def _ticks(low: float, high: float, least: int = 4, most: int = 7) -> list[float]:
    """Round values inside ``low`` to ``high`` for an axis: the widest step of 1, 2, 3 or
    5 times a power of ten (or 15, 30, 45, 60 or 90 degrees) that gives at least ``least``
    of them (at most ``most``)."""
    span = high - low
    if span <= 0:
        return []
    power = 10 ** math.floor(math.log10(span))
    steps = {m * power / 10**k for k in range(0, 3) for m in (5, 3, 2, 1)}
    if span >= 60:  # whole degrees in steps that divide a turn
        steps = {10, 15, 20, 30, 45, 60, 90}
    for step in sorted((s for s in steps if s <= span), reverse=True):
        first = math.ceil(low / step - 1e-9) * step
        values = []
        v = first
        while v <= high + 1e-9 * step:
            values.append(round(v, 10))
            v += step
        if len(values) >= least:
            return values if len(values) <= most else values[:: math.ceil(len(values) / most)]
    return []


def degrees(value: float, positive: str, geographic: bool = True) -> str:
    """An axis label: ``30° S``, ``150° E``, ``170° W`` (a longitude past 180° turned
    west); a plain number on a grid that is not in degrees."""
    if not geographic:
        return numbers.number(value)
    if positive == "E":
        value = (value + 180) % 360 - 180
    hemisphere = numbers._hemisphere(value, positive)
    return f"{numbers.number(abs(value))}°{numbers.NBSP}{hemisphere}"


@dataclass
class Frame:
    """The map's geometry in SVG units: the plot (``left``, ``top``, ``plot_w`` x
    ``plot_h``) where the PNG goes, the axes' ticks, the coastline, the places and the
    selected cell. ``rows`` and ``cols`` are the file's row and column of each row and
    column drawn (north first, west first)."""

    nx: int
    ny: int
    rows: list[int]
    cols: list[int]
    box: outline.Box
    geographic: bool
    plot_w: float
    plot_h: float
    left: float = LEFT
    top: float = TOP
    x_ticks: list[dict] = field(default_factory=list)
    y_ticks: list[dict] = field(default_factory=list)
    coast: str = ""
    places: list[dict] = field(default_factory=list)

    @property
    def width(self) -> float:
        return round(LEFT + self.plot_w + RIGHT, 1)

    @property
    def height(self) -> float:
        return round(TOP + self.plot_h + BOTTOM, 1)

    @property
    def view_box(self) -> str:
        return f"0 0 {self.width:g} {self.height:g}"

    @property
    def cell_w(self) -> float:
        return self.plot_w / self.nx

    @property
    def cell_h(self) -> float:
        return self.plot_h / self.ny

    @property
    def label_y(self) -> float:
        return round(TOP + self.plot_h + 17, 1)

    @property
    def tick_x(self) -> float:
        return LEFT - 6

    def cell_rect(self, y: int, x: int) -> dict:
        """The rectangle of the file's cell ``(y, x)``."""
        r, c = self.rows.index(y), self.cols.index(x)
        return {
            "x": round(LEFT + c * self.cell_w, 2),
            "y": round(TOP + r * self.cell_h, 2),
            "w": round(self.cell_w, 2),
            "h": round(self.cell_h, 2),
        }

    def x_of(self, lon: float) -> float:
        return LEFT + (lon - self.box.west) / (self.box.east - self.box.west) * self.plot_w

    def y_of(self, lat: float) -> float:
        return TOP + (self.box.north - lat) / (self.box.north - self.box.south) * self.plot_h


def frame(layer: Layer) -> Frame:
    """The frame of the layer's grid: north up and west left, the cells' aspect corrected
    by the cosine of the grid's mean latitude, with its axes, coastline and places."""
    lat, lon = layer.lat, layer.lon
    ny, nx = len(lat), len(lon)
    rows = list(range(ny))
    if ny > 1 and lat[0] < lat[-1]:
        rows.reverse()  # north up
    cols = list(range(nx))
    if nx > 1 and lon[0] > lon[-1]:
        cols.reverse()  # west left
    dlat, dlon = _step(lat), _step(lon)
    box = outline.Box(
        west=min(lon) - dlon / 2,
        east=max(lon) + dlon / 2,
        south=min(lat) - dlat / 2,
        north=max(lat) + dlat / 2,
    )
    geographic = layer.geographic
    cosine = 1.0
    if geographic:
        cosine = max(math.cos(math.radians((box.north + box.south) / 2)), 0.2)
    aspect = (box.north - box.south) / ((box.east - box.west) * cosine)
    plot_h = PLOT_W * min(aspect, MAX_ASPECT)
    out = Frame(nx, ny, rows, cols, box, geographic, PLOT_W, round(plot_h, 2))
    out.x_ticks = [
        {"x": round(out.x_of(v), 1), "text": degrees(v, "E", geographic), "value": v}
        for v in _ticks(box.west, box.east)
    ]
    out.y_ticks = [
        {"y": round(out.y_of(v), 1), "text": degrees(v, "N", geographic), "value": v}
        for v in _ticks(box.south, box.north, 3 if plot_h < 300 else 4)
    ]
    if geographic:
        per_unit = (box.east - box.west) / PLOT_W
        parts = []
        for line in outline.coastline(box, tolerance=1.5 * per_unit):
            xs = LEFT + (line[:, 0] - box.west) / (box.east - box.west) * PLOT_W
            ys = TOP + (box.north - line[:, 1]) / (box.north - box.south) * out.plot_h
            points = " ".join(f"{x:.1f} {y:.1f}" for x, y in zip(xs, ys, strict=True))
            parts.append(f"M{points}")
        out.coast = "".join(parts)
        for p in outline.places(box):
            x, y = out.x_of(p.lon), out.y_of(p.lat)
            east = x > LEFT + PLOT_W * 0.7
            out.places.append(
                {
                    "name": p.name,
                    "x": round(x, 1),
                    "y": round(y, 1),
                    "tx": round(x - 6 if east else x + 6, 1),
                    "ty": round(y + 4, 1),
                    "anchor": "end" if east else "start",
                }
            )
    return out


def display_order(values: np.ndarray, f: Frame) -> np.ndarray:
    """The ``(y, x)`` values of the file in the frame's order: north first, west first."""
    return values[np.ix_(f.rows, f.cols)]


def nearest_cell(layer: Layer, lat: float, lon: float) -> tuple[int, int] | None:
    """The file's cell nearest ``(lat, lon)``, None when the point is outside the grid
    (beyond half a cell from its edge). Longitudes are matched a turn either way."""
    if not layer.lat or not layer.lon:
        return None
    lats = np.asarray(layer.lat)
    lons = np.asarray(layer.lon)
    dlat, dlon = _step(layer.lat), _step(layer.lon)
    if not (lats.min() - dlat / 2 <= lat <= lats.max() + dlat / 2):
        return None
    for shift in (0.0, 360.0, -360.0):
        if lons.min() - dlon / 2 <= lon + shift <= lons.max() + dlon / 2:
            return int(np.argmin(np.abs(lats - lat))), int(np.argmin(np.abs(lons - (lon + shift))))
    return None


def cell_bounds(layer: Layer, y: int, x: int) -> tuple[float, float, float, float]:
    """``(south, north, west, east)`` of the file's cell ``(y, x)``."""
    dlat, dlon = _step(layer.lat), _step(layer.lon)
    lat, lon = layer.lat[y], layer.lon[x]
    return lat - dlat / 2, lat + dlat / 2, lon - dlon / 2, lon + dlon / 2


__all__ = [
    "Frame",
    "Layer",
    "OutputFile",
    "cell_series",
    "classify",
    "edges_for",
    "frame",
    "grid_values",
    "kind_of",
    "nice_edges",
    "open_layer",
    "output_files",
    "palette",
]
