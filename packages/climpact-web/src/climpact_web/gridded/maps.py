"""Exploring the gridded results (#85): the output files, a map of one index at one time
step, and the time series of one cell, drawn on the server as inline SVG.

No map tiles or other network services are used (offline and low bandwidth): the map is
a raster of the grid's cells coloured in the sequential chart tokens, with the cell
values also given as a table. Grids from Climpact runs are small (tens to a few hundred
cells a side); above :data:`MAX_MAP_CELLS` the map shows every n-th row and column and
says so. The time series is a small SVG line chart, the placeholder until the interactive
charts of #75 (``CHART HOOK`` in ``gridded/_explore.html``).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from climpact_web.stations.preview import _nice_ticks, _path, _scale

# Each cell is a link with a tooltip and a table cell (about 550 bytes of HTML), so the cap
# keeps the results page within the size budget (#82, TECHNICAL.md "Size budget"): 2,500
# cells is about 1.4 MB of HTML, 60 KB gzipped. At the map's width, 50 cells a side are
# about 13 px each, so a finer map could not be clicked cell by cell anyway.
MAX_MAP_CELLS = 2_500
MAP_WIDTH = 640  # SVG units; the height follows the grid's aspect
MAX_CELL = 56
LABEL_SPACE = 64  # SVG units a longitude label needs
SERIES_WIDTH, SERIES_HEIGHT = 720, 220
PAD_X, PAD_TOP, PAD_BOTTOM = 52, 12, 28
BINS = 5
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


@dataclass
class Layer:
    """One index variable of one file: what the map and series need to know about it."""

    file: str
    variable: str
    variables: list[dict]  # {"name", "long_name", "units"} of every index variable
    long_name: str
    units: str
    times: list[str]  # a label per time step
    scales: list[str]  # SPI/SPEI: "3 months", ...; else []
    lat: list[float]
    lon: list[float]
    y_dim: str = ""
    x_dim: str = ""


def _decode_times(nc, freq: str) -> list[str]:
    import cftime

    time = nc.variables.get("time")
    if time is None:
        return []
    values = np.asarray(time[:], dtype=float)
    if freq == "DAY":  # tx95t: day of the year
        return [str(int(v)) for v in values]
    units = getattr(time, "units", "")
    calendar = getattr(time, "calendar", "standard")
    try:
        dates = cftime.num2date(values, units, calendar)
    except (ValueError, TypeError):
        return [str(i + 1) for i in range(len(values))]
    if freq == "MON":
        return [f"{d.year:04d}-{d.month:02d}" for d in dates]
    return [f"{d.year:04d}" for d in dates]


def _coordinate(nc, var, axis: str) -> tuple[str, list[float]]:
    names = {"Y": ("lat", "latitude", "y", "rlat"), "X": ("lon", "longitude", "x", "rlon")}
    dims = var.dimensions[-2:]
    dim = dims[0] if axis == "Y" else dims[1]
    coord = nc.variables.get(dim)
    if coord is not None and coord.ndim == 1:
        return dim, [float(v) for v in np.asarray(coord[:], dtype=float)]
    for name in names[axis]:
        if name in nc.variables and nc.variables[name].ndim == 1:
            return dim, [float(v) for v in np.asarray(nc.variables[name][:], dtype=float)]
    return dim, list(range(len(nc.dimensions[dim])))


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


def open_layer(path: Path, rel: str, variable: str | None = None) -> Layer:
    """The layer of ``variable`` (default: the file's first index variable) in ``path``."""
    import netCDF4

    m = FILE_RE.match(path.name)
    freq = m["freq"] if m else "ANN"
    with netCDF4.Dataset(path) as nc:
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
        return Layer(
            file=rel,
            variable=variable,
            variables=variables,
            long_name=meta["long_name"],
            units=meta["units"],
            times=_decode_times(nc, freq),
            scales=scales,
            lat=lat,
            lon=lon,
            y_dim=y_dim,
            x_dim=x_dim,
        )


def _masked(values) -> np.ndarray:
    """Values as float64 with the fill value and non-finite values as NaN (EHF-HWPS can
    be -Inf in R's files; it is shown as no value)."""
    array = np.ma.filled(np.ma.asarray(values, dtype=float), np.nan)
    array = np.where(np.isfinite(array) & (np.abs(array) < 1e19), array, np.nan)
    return array


def grid_values(path: Path, layer: Layer, t: int, scale: int = 0) -> np.ndarray:
    """The ``(y, x)`` values of the layer at time step ``t`` (and SPI/SPEI scale)."""
    import netCDF4

    with netCDF4.Dataset(path) as nc:
        var = nc.variables[layer.variable]
        var.set_auto_mask(True)
        if layer.scales:
            return _masked(var[scale, t, :, :])
        return _masked(var[t, :, :])


def last_step_with_values(path: Path, layer: Layer, scale: int = 0) -> int:
    """The last time step where any cell has a value (heatwave seasons that run into the
    next year leave the last year empty, for example); the last step if none has."""
    for t in range(len(layer.times) - 1, -1, -1):
        if np.isfinite(grid_values(path, layer, t, scale)).any():
            return t
    return max(len(layer.times) - 1, 0)


def cell_series(path: Path, layer: Layer, y: int, x: int, scale: int = 0) -> np.ndarray:
    import netCDF4

    with netCDF4.Dataset(path) as nc:
        var = nc.variables[layer.variable]
        var.set_auto_mask(True)
        if layer.scales:
            return _masked(var[scale, :, y, x])
        return _masked(var[:, y, x])


# ---- Drawing -------------------------------------------------------------------------------


def format_value(value: float | None, digits: int = 2) -> str:
    if value is None or not math.isfinite(value):
        return ""
    if value != 0 and abs(value) < 10**-digits:
        return f"{value:.2g}"
    text = f"{value:.{digits}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


@dataclass
class Bin:
    lo: float
    hi: float
    css: str
    label: str


def bins_for(values: np.ndarray) -> list[Bin]:
    """Five equal classes over the finite values, on rounded limits."""
    finite = values[np.isfinite(values)]
    if not finite.size:
        return []
    lo, hi = float(finite.min()), float(finite.max())
    if hi == lo:
        return [Bin(lo, hi, "gmap__c3", format_value(lo))]
    rough = (hi - lo) / BINS
    magnitude = 10 ** math.floor(math.log10(rough))
    for m in (1, 2, 2.5, 5, 10, 20, 25, 50, 100):
        step = m * magnitude
        if step < rough:
            continue
        start = math.floor(lo / step) * step
        if start + BINS * step >= hi:
            break
    edges = [start + k * step for k in range(BINS + 1)]
    digits = max(0, 1 - math.floor(math.log10(step)))
    return [
        Bin(
            edges[k],
            edges[k + 1],
            f"gmap__c{k + 1}",
            f"{format_value(edges[k], digits)} – {format_value(edges[k + 1], digits)}",
        )
        for k in range(len(edges) - 1)
    ]


def classify(value: float, bins: list[Bin]) -> str:
    if not math.isfinite(value):
        return "gmap__na"
    for b in bins:
        if value <= b.hi:
            return b.css
    return bins[-1].css if bins else "gmap__na"


@dataclass
class MapCell:
    y: int
    x: int
    px: float
    py: float
    css: str
    value: str
    lat: float
    lon: float
    selected: bool = False
    href: str = ""  # the results page for this cell (without JavaScript)
    hx: str = ""  # the explore fragment for this cell (htmx)


@dataclass
class MapDrawing:
    width: float
    height: float
    cell_w: float
    cell_h: float
    cells: list[MapCell]
    bins: list[Bin]
    stride: int
    has_missing: bool
    x_labels: list[dict] = field(default_factory=list)
    y_labels: list[dict] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)  # the table: {"lat", "values": [...]}
    lon_headers: list[str] = field(default_factory=list)
    lo: str = ""
    hi: str = ""

    @property
    def view_box(self) -> str:
        """Room for the latitude labels on the left and the longitude labels below."""
        return f"-64 -6 {self.width + 72:g} {self.height + 30:g}"

    @property
    def natural_width(self) -> float:
        """The SVG's width at one unit per pixel: a small grid is not stretched (its
        labels would grow with it)."""
        return self.width + 72

    @property
    def label_y(self) -> float:
        return round(self.height + 16, 1)


def draw_map(values: np.ndarray, lat: list[float], lon: list[float], selected=None) -> MapDrawing:
    """Cells as rectangles, north at the top (rows are flipped when latitude increases
    with the row index), west at the left."""
    ny, nx = values.shape
    stride = max(1, math.ceil(math.sqrt(ny * nx / MAX_MAP_CELLS)))
    ys = list(range(0, ny, stride))
    xs = list(range(0, nx, stride))
    if len(lat) == ny and len(lat) > 1 and lat[0] < lat[-1]:
        ys = ys[::-1]  # north up
    if len(lon) == nx and len(lon) > 1 and lon[0] > lon[-1]:
        xs = xs[::-1]  # west left
    cell = min(MAX_CELL, MAP_WIDTH / len(xs))
    width, height = cell * len(xs), cell * len(ys)
    shown = values[np.ix_(ys, xs)]
    bins = bins_for(shown)
    cells = []
    for row, y in enumerate(ys):
        for col, x in enumerate(xs):
            v = float(values[y, x])
            cells.append(
                MapCell(
                    y=y,
                    x=x,
                    px=round(col * cell, 2),
                    py=round(row * cell, 2),
                    css=classify(v, bins),
                    value=format_value(v),
                    lat=lat[y] if y < len(lat) else y,
                    lon=lon[x] if x < len(lon) else x,
                    selected=selected == (y, x),
                )
            )
    label_every = max(1, math.ceil(len(xs) / 6), math.ceil(LABEL_SPACE / cell))
    x_labels = [
        {"x": round((col + 0.5) * cell, 1), "text": coord_label(lon[x] if x < len(lon) else x, "E")}
        for col, x in enumerate(xs)
        if col % label_every == 0
    ]
    label_every = max(1, math.ceil(len(ys) / 6))
    y_labels = [
        {"y": round((row + 0.5) * cell, 1), "text": coord_label(lat[y] if y < len(lat) else y, "N")}
        for row, y in enumerate(ys)
        if row % label_every == 0
    ]
    finite = shown[np.isfinite(shown)]
    return MapDrawing(
        width=round(width, 2),
        height=round(height, 2),
        cell_w=round(cell, 2),
        cell_h=round(cell, 2),
        cells=cells,
        bins=bins,
        stride=stride,
        has_missing=bool(np.isnan(shown).any()),
        x_labels=x_labels,
        y_labels=y_labels,
        rows=[
            {
                "lat": coord_label(lat[y] if y < len(lat) else y, "N"),
                "values": [format_value(float(values[y, x])) for x in xs],
            }
            for y in ys
        ],
        lon_headers=[coord_label(lon[x] if x < len(lon) else x, "E") for x in xs],
        lo=format_value(float(finite.min())) if finite.size else "",
        hi=format_value(float(finite.max())) if finite.size else "",
    )


def coord_label(value: float, positive: str) -> str:
    negative = {"N": "S", "E": "W"}[positive]
    if not isinstance(value, float):
        return str(value)
    hemisphere = positive if value >= 0 else negative
    return f"{format_value(abs(value), 2)}°{hemisphere}"


@dataclass
class SeriesDrawing:
    width: int
    height: int
    path: str
    points: list[dict]
    y_labels: list[dict]
    x_labels: list[dict]
    rows: list[dict]
    count: int


def draw_series(values: np.ndarray, labels: list[str]) -> SeriesDrawing | None:
    """A line through the values (broken at missing ones), with dots when there are few."""
    finite = values[np.isfinite(values)]
    if not finite.size:
        return None
    n = len(values)
    lo, hi = float(finite.min()), float(finite.max())
    if lo == hi:
        lo, hi = lo - 1, hi + 1
    ticks = _nice_ticks(lo, hi)
    lo, hi = min(lo, ticks[0]), max(hi, ticks[-1])
    x = _scale(0, max(n - 1, 1), PAD_X, SERIES_WIDTH - 8)
    y = _scale(lo, hi, SERIES_HEIGHT - PAD_BOTTOM, PAD_TOP)
    data = [float(v) if math.isfinite(v) else None for v in values]
    every = max(1, math.ceil(n / 8))
    return SeriesDrawing(
        width=SERIES_WIDTH,
        height=SERIES_HEIGHT,
        path=_path(data, x, y),
        points=[
            {"x": round(x(i), 1), "y": round(y(v), 1)}
            for i, v in enumerate(data)
            if v is not None and n <= 120
        ],
        y_labels=[{"y": round(y(t), 1), "text": format_value(t)} for t in ticks],
        x_labels=[{"x": round(x(i), 1), "text": labels[i]} for i in range(0, n, every)],
        rows=[
            {"time": labels[i], "value": format_value(v) if v is not None else ""}
            for i, v in enumerate(data)
        ],
        count=int(finite.size),
    )
