"""The gridded map's four views (#296, the GridMap board) and the grid mean, from the
run's ``trends.nc`` (#290, :mod:`climpact.gridded.trends`).

- **Year** (#295): the index in one year (or month); the index's sequential scale.
- **Base mean**: each cell's mean over the base period (``<index>_base_mean``), on the
  same sequential scale.
- **Anomaly**: the chosen year minus the base mean, on a diverging scale centred on zero.
- **Trend**: Sen's slope per decade over the run's years (``<index>_slope``), on a
  diverging scale; a dot on each cell whose 95% interval (``_lower`` to ``_upper``)
  excludes zero.

``trends.nc`` holds the annual series only: every annual file's variables, and SPI and
SPEI's 12-month scale in December. So the three views are offered for an annual file
and for SPI and SPEI (at the 12-month scale, in December); not for a monthly file, a
day-of-year file or a run without ``trends.nc`` (calculated before #290, or with the
trends turned off), which keep Year and say why (:func:`unavailable`).

The diverging scales (:func:`palette`) have eight bins symmetric about zero, with fixed
breaks for the file (:func:`symmetric_edges`, round numbers over the values of every
year), so the years compare: temperature blue to red (``--map-div-temp-*``) for the
temperature and count indices, brown to teal (``--map-div-wet-*``) for rain, drought,
SPI and SPEI; reversed where more means cooler or drier (the ``cool`` and ``dry`` kinds:
FD, ID, CSDI, TX10p, TN10p, CDD and the like), so warmer and wetter read the same way on
every map.

Every read of ``trends.nc`` holds :data:`climpact_web.gridded.netcdf.LOCK` (through
:func:`netcdf.dataset`); the fields are kept in memory for the map's later requests.
"""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from django.utils.translation import gettext as _

from climpact_web.gridded import maps, netcdf

TRENDS_FILE = "trends.nc"  # climpact.gridded.trends.TRENDS_FILE, without importing the core
VIEWS = ("year", "base", "anomaly", "trend")
TREND_VIEWS = ("base", "anomaly", "trend")
SPI_SCALE = "12"  # trends.nc holds SPI and SPEI's 12-month scale ...
SPI_MONTH = 12  # ... in December
# The cool and dry kinds: more of them means cooler or drier, so their diverging scale
# is reversed (an increase in frost days is blue, in dry days brown).
REVERSED_KINDS = ("cool", "dry")
WET_KINDS = ("wet", "dry", "spi")
CACHE_BYTES = 128 * 1024 * 1024


@dataclass
class Trends:
    """One index of ``trends.nc``: per cell (the index file's ``(y, x)``) its slope per
    decade and 95% interval, and its base-period mean; the grid mean per year."""

    slope: np.ndarray
    lower: np.ndarray
    upper: np.ndarray
    base_mean: np.ndarray
    grid_mean: np.ndarray
    years: list[int]
    base: tuple[int, int] | None
    period: tuple[int, int] | None

    @property
    def significant(self) -> np.ndarray:
        """Cells whose 95% interval excludes zero (False where there is no trend)."""
        with np.errstate(invalid="ignore"):
            return (self.lower > 0) | (self.upper < 0)

    @property
    def nbytes(self) -> int:
        return sum(a.nbytes for a in (self.slope, self.lower, self.upper, self.base_mean))


def trends_path(job) -> Path | None:
    """The run's ``trends.nc``, None when its indices job wrote none."""
    if job is None or TRENDS_FILE not in (job.result or {}).get("files", []):
        return None
    path = job.output_dir / TRENDS_FILE
    return path if path.is_file() else None


def _period(text) -> tuple[int, int] | None:
    try:
        first, last = (int(v) for v in str(text).split("-"))
    except ValueError:
        return None
    return first, last


def _field(nc, name: str) -> np.ndarray:
    var = nc.variables[name]
    var.set_auto_mask(True)
    values = np.ma.filled(np.ma.asarray(var[:], dtype=float), np.nan)
    values[~(np.abs(values) < 1e19)] = np.nan
    return values


_cache: OrderedDict[tuple, Trends | None] = OrderedDict()
_cache_lock = threading.Lock()


def read_trends(path: Path | None, variable: str) -> Trends | None:
    """``variable``'s fields in ``trends.nc`` at ``path``, None when the file has no such
    index. Read once (holding the netCDF lock) and kept."""
    if path is None:
        return None
    key = (str(path), path.stat().st_mtime_ns, variable)
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    import cftime

    with netcdf.dataset(path) as nc:
        if f"{variable}_slope" not in nc.variables:
            found = None
        else:
            time = nc.variables["time"] if "time" in nc.variables else None
            years: list[int] = []
            if time is not None:
                calendar = getattr(time, "calendar", "standard")
                dates = cftime.num2date(np.asarray(time[:], float), time.units, calendar)
                years = [int(d.year) for d in dates]
            found = Trends(
                slope=_field(nc, f"{variable}_slope"),
                lower=_field(nc, f"{variable}_lower"),
                upper=_field(nc, f"{variable}_upper"),
                base_mean=_field(nc, f"{variable}_base_mean"),
                grid_mean=_field(nc, f"{variable}_grid_mean"),
                years=years,
                base=_period(getattr(nc, "base_period", "")),
                period=_period(getattr(nc, "trend_period", "")),
            )
    with _cache_lock:
        _cache[key] = found
        while len(_cache) > 1 and sum(t.nbytes for t in _cache.values() if t) > CACHE_BYTES:
            _cache.popitem(last=False)
    return found


def is_spi(short: str) -> bool:
    return short in ("spi", "spei")


def unavailable(job, layer: maps.Layer, short: str, has_annual: bool) -> str:
    """Why Base mean, Anomaly, Trend and the grid mean are not offered for ``layer``; ""
    when they are (``trends.nc`` has its annual series)."""
    from climpact_web.gridded.stages import has_trends

    if layer.freq == "DAY":
        return _("Base mean, Anomaly and Trend are of an index's years, not of its days.")
    path = trends_path(job)
    if path is None:
        if not has_trends(job):
            return _(
                "This run was calculated without its trends, so it has no base mean, "
                "anomaly or trend."
            )
        return _(
            "This run has no trends file (trends.nc): it was calculated before Climpact "
            "wrote one. Start it again on Set-up to add one."
        )
    if layer.freq == "MON" and not is_spi(short):
        if has_annual:
            return _("Base mean, Anomaly and Trend are of the annual series: choose Annual.")
        return _("Base mean, Anomaly and Trend are of the annual series; this index has none.")
    if read_trends(path, layer.variable) is None:
        return _("The run's trends file has no trend of this index.")
    return ""


# ---- The scales --------------------------------------------------------------------------------


def scale_of(kind: str, view: str) -> str:
    """The colour scale of a view: the kind's sequential scale for Year and Base mean
    (SPI and SPEI ``div-wet``, their classes); ``div-temp`` or ``div-wet`` for Anomaly
    and Trend, ``-r`` (reversed) for the cool and dry kinds."""
    if view in ("year", "base") and kind != "spi":
        return kind
    family = "div-wet" if kind in WET_KINDS else "div-temp"
    return f"{family}-r" if view in ("anomaly", "trend") and kind in REVERSED_KINDS else family


def palette(scale: str, theme: str = "light") -> list[str]:
    """The bins' colours of a scale (:func:`scale_of`), from the tokens."""
    from climpact_web.core import tokens

    values = tokens.chart_palette()[theme]
    if scale.startswith("div-"):
        colours = list(values["map_diverging"][scale.split("-")[1]])
        return colours[::-1] if scale.endswith("-r") else colours
    return list(values["map_sequential"][scale])


def symmetric_edges(magnitude: float, bins: int = maps.BINS) -> list[float]:
    """``bins + 1`` breaks symmetric about zero, a round step apart (1, 2, 2.5 or 5 times
    a power of ten), the last at or above ``magnitude``."""
    half = bins // 2
    if not (math.isfinite(magnitude) and magnitude > 0):
        return [float(k) for k in range(-half, half + 1)]
    rough = magnitude / half
    power = 10 ** math.floor(math.log10(rough))
    step = next(m * power for m in (1, 2, 2.5, 5, 10) if m * power * half >= magnitude * (1 - 1e-9))
    return [round(k * step, 10) for k in range(-half, half + 1)]


def _magnitude(values: np.ndarray) -> float | None:
    """The 98th percentile of the values' size, None without a value."""
    found = np.abs(values[np.isfinite(values)])
    return float(np.percentile(found, 98)) if found.size else None


def sequential_edges(values: np.ndarray) -> list[float] | None:
    """Round breaks over a field's 2nd to 98th percentiles (counts start at zero), as
    :func:`maps.edges_for` sets the Year view's; None without a value."""
    found = values[np.isfinite(values)]
    if not found.size:
        return None
    low, high = (float(v) for v in np.percentile(found, [2, 98]))
    edges = maps.nice_edges(low, high)
    if low >= 0 and edges[0] < 0:
        edges = maps.nice_edges(0.0, high)
    return edges


_edges: dict[tuple, list[float] | None] = {}


def anomaly_edges(path: Path, layer: maps.Layer, base_mean: np.ndarray, scale: int, steps):
    """The Anomaly view's breaks: symmetric over the anomalies of every year (at most
    :data:`maps.SAMPLE_STEPS` of them, of ``steps``), so one year's map compares with
    another's. Kept for the file."""
    key = (*maps._key(path, layer.variable, scale), "anomaly", tuple(steps))
    if key in _edges:
        return _edges[key]
    if len(steps) > maps.SAMPLE_STEPS:
        n = maps.SAMPLE_STEPS
        steps = sorted({steps[round(i * (len(steps) - 1) / (n - 1))] for i in range(n)})
    whole = maps.variable_values(path, layer, scale)
    if whole is not None:
        sample = whole[list(steps)] - base_mean[None, :, :]
    else:
        sample = np.stack([maps.grid_values(path, layer, t, scale) - base_mean for t in steps])
    magnitude = _magnitude(sample)
    edges = symmetric_edges(magnitude) if magnitude is not None else None
    if len(_edges) > 1024:
        _edges.clear()
    _edges[key] = edges
    return edges


# ---- One view of one layer ---------------------------------------------------------------------


@dataclass
class Field:
    """What the map draws in a view: the ``(y, x)`` values in the file's order, the bins'
    breaks and scale, and on Trend the cells whose interval excludes zero."""

    view: str
    values: np.ndarray
    edges: list[float] | None
    scale: str
    significant: np.ndarray | None = None

    def colours(self, theme: str) -> list[str]:
        return palette(self.scale, theme)


def field(path: Path, layer: maps.Layer, kind: str, view: str, t: int, scale: int,
          month: int | None, trends: Trends | None) -> Field:  # fmt: skip
    """The field of ``view`` (Year when ``trends`` is None)."""
    if trends is None or view == "year":
        values = maps.grid_values(path, layer, t, scale)
        edges = maps.edges_for(path, layer, kind, scale, month)
        return Field("year", values, edges, scale_of(kind, "year"))
    if view == "base":
        values = trends.base_mean
        if kind == "spi":
            magnitude = _magnitude(values)
            edges = symmetric_edges(magnitude) if magnitude is not None else None
        else:
            edges = sequential_edges(values)
        return Field(view, values, edges, scale_of(kind, view))
    if view == "anomaly":
        values = maps.grid_values(path, layer, t, scale) - trends.base_mean
        steps = [i for i in range(len(layer.times)) if not layer.months or layer.months[i] == month]
        edges = anomaly_edges(path, layer, trends.base_mean, scale, steps)
        return Field(view, values, edges, scale_of(kind, view))
    magnitude = _magnitude(trends.slope)
    edges = symmetric_edges(magnitude) if magnitude is not None else None
    return Field(view, trends.slope, edges, scale_of(kind, view), trends.significant)


# ---- Dots on Trend -----------------------------------------------------------------------------

DOT_PIXELS = 4_000_000  # at most this many pixels in the map's image with dots
PIXEL = 1.5  # about this many SVG units (page pixels) a pixel of the image, at most
DOT = 3.5  # the dot's diameter in SVG units


def dot_factor(ny: int, nx: int, cell: float = 0.0) -> int:
    """How many pixels a side each cell takes in an image with dots: enough that a pixel
    is about :data:`PIXEL` SVG units for a cell ``cell`` units wide (at least 2, at most
    64), fewer on a large grid (where the dots make a texture over the cells that have
    one)."""
    wanted = max(2, min(64, round(cell / PIXEL)))
    most = max(2, math.floor(math.sqrt(DOT_PIXELS / max(ny * nx, 1))))
    return int(min(wanted, most))


def _luminance(colour: str) -> float:
    value = colour.lstrip("#")
    channels = [int(value[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def dot_mask(k: int, cell: float) -> np.ndarray:
    """The dot in a cell of ``k`` x ``k`` pixels drawn ``cell`` SVG units wide: a disc
    about :data:`DOT` units across in the middle, at most half the cell; one pixel when
    the pixels are larger (and on a large grid, where the dots make a texture)."""
    size = cell / k if cell else PIXEL
    d = min(DOT / size, k / 2)
    mask = np.zeros((k, k), bool)
    if d < 1.5:
        mask[k // 2, k // 2] = True
        return mask
    centre = (k - 1) / 2
    y, x = np.mgrid[0:k, 0:k]
    return (y - centre) ** 2 + (x - centre) ** 2 <= (d / 2) ** 2 + 0.25


def with_dots(bins: np.ndarray, significant: np.ndarray, colours: list[str], text: str,
              surface: str, cell: float = 0.0) -> tuple[np.ndarray, list[str]]:  # fmt: skip
    """The bins (``(rows, columns)``, the frame's order) drawn :func:`dot_factor` pixels
    a side for cells ``cell`` SVG units wide, with a dot in the middle of each significant
    cell: in the text colour or the surface's, whichever stands out more from the cell's
    bin. Returns the pixels and the colours (the bins', then the two dots')."""
    rows, cols = bins.shape
    k = dot_factor(rows, cols, cell)
    out = np.repeat(np.repeat(bins, k, axis=0), k, axis=1)
    n = len(colours)
    dark = np.array(
        [n if contrast(c, text) >= contrast(c, surface) else n + 1 for c in colours], np.uint8
    )
    dots = significant & (bins != 255)
    if dots.any():
        dot = dark[np.where(dots, bins, 0)]
        for dy, dx in np.argwhere(dot_mask(k, cell)):
            block = out[dy::k, dx::k]
            block[dots] = dot[dots]
    return out, [*colours, text, surface]


__all__ = [
    "Field",
    "Trends",
    "field",
    "palette",
    "read_trends",
    "scale_of",
    "symmetric_edges",
    "trends_path",
    "unavailable",
    "with_dots",
]
