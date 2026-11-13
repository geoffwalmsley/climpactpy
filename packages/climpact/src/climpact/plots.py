"""Static index plots, the combined PDF and the zip archive: R's plot and zip outputs.

R draws a PNG of every index series it writes, with its Sen's slope trend line, and the
same pages in ``<station>_all_plots.pdf`` (``index.calc`` in
``services/calculate_indices.R``, ``plot.call`` and ``plot.hw`` in
``services/plot_indices.R``, ``plot.precindex`` in ``services/plot_prec_index.R``). Then
it zips the station folder (``services/zipFiles.R``). This module writes the same files,
under the same names, from a run's output tables:

- ``<out>/<station>/plots/<station>_<name>.png``, one per plotted series, where
  ``<name>`` is the index file name (``fd_ANN``, ``txx_MON``, ``tx95t_DAY``,
  ``TX90-HWM_ANN``, ``EHF-HWD_ANN``, ``3month_spi_MON``, ``TNgt0_ANN`` ...) or, for the
  indices with dates other than ``cwd``, ``cdd`` and ``gsl``, ``day_of_<name>`` (the
  calendar day of the event: day of the year for annual values, of the month for
  monthly ones);
- ``<out>/<station>/plots/<station>_all_plots.pdf``, every plot as one page, in R's
  order (the rows of ``climate.indices.csv``);
- ``<out>/<station>.zip`` (:func:`zip_station`), the station folder.

A series is plotted when its table exists and the plotted values are not all missing,
as R skips a series that is ("NO DATA FOR ... NOT PLOTTING"). The plotted values are
those of the trend file (:mod:`climpact.products.trends`), and the trend is
:func:`climpact.trends.plot_trend`: the trend file's Sen's slope and 95% bounds, with
``zyp.sen``'s intercept and Kendall's Mann-Kendall p-value. ``tx95t`` and the
``day_of_`` plots have no trend, as in R.

The plots show what R's show (station, coordinates, index definition, units, values,
missing values, trend line, slope with its bounds and the p-value) but are drawn
differently: see TECHNICAL.md, "Differences between Python and R".

matplotlib is an optional dependency (``pip install climpactpy[plots]``). It is imported
only when plots are drawn, and drawn on an Agg canvas without ``pyplot``, so the
caller's matplotlib backend is never changed.
"""

from __future__ import annotations

import logging
import os
import textwrap
import zipfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from climpact import __version__
from climpact.config import IndexParams, StationMetadata
from climpact.io.climpact_csv import format_r_number
from climpact.io.output_files import CLIMPACT_VERSION, _index_definitions, index_files
from climpact.products.trends import _value_column
from climpact.trends import PlotTrend, plot_trend

# exact_date_indices (server/global_variables.r): the indices written with dates. All but
# cwd, cdd and gsl also get a day_of_ plot.
_DATED = {"tnn", "tnx", "txn", "txx", "rxdday", "rx1day", "rx5day", "cdd", "cwd", "gsl"}
_NO_DAY_OF = {"cdd", "cwd", "gsl"}

# plot.hw: aspect -> (long name, R's description, units).
_HW_ASPECTS = {
    "HWM": ("Magnitude", "mean temperature of all heatwave events", "°C"),
    "HWA": ("Amplitude", "peak temperature of the hottest heatwave event", "°C"),
    "HWN": ("Number", "number of discreet heatwave events", "heatwaves"),
    "HWD": ("Duration", "length of longest heatwave event", "days"),
    "HWF": ("Frequency", "number of days contributing to heatwave events", "days"),
}

# calculate.hwEHF: aspect -> (R's description, units), in R's plot order.
_EHF_ASPECTS = {
    "HWD": ("EHF-HWD (Heatwave Duration): Duration of the longest EHF heatwave.", "days"),
    "HWMD": ("EHF-HWMD (Heatwave Mean Duration): Mean EHF heatwave duration.", "days"),
    "HWPS": (
        "EHF-HWPS (Heatwave Peak Severity): Mean of the maximum severity of each EHF heatwave.",
        "unitless",
    ),
    "HWPI": (
        "EHF-HWPI (Heatwave Peak Intensity): Mean of the maximum intensity of each EHF heatwave.",
        "°C^2",
    ),
    "HWLS": ("EHF-HWLS (Heatwave Load Severity): Sum of EHF heatwave severities.", "unitless"),
    "HWLI": ("EHF-HWLI (Heatwave Load Intensity): Sum of EHF heatwave intensities.", "°C^2"),
    "HWN": ("EHF-HWN (Heatwave Number): Number of EHF heatwaves.", "heatwaves"),
    "HWF": ("EHF-HWF (Heatwave Frequency): Number of days contributing to EHF heatwaves.", "days"),
}

# Units as R labels the y axis -> as drawn here.
_UNIT_LABELS = {
    "degrees_C": "°C",
    "°C^2": "°C²",
    "degree-days": "degree-days",
    "unitless": "",
}

Step = Literal["year", "month", "day"]


@dataclass(frozen=True)
class IndexPlot:
    """One plotted series: a PNG file and a page of the combined PDF."""

    name: str  # file name without the station prefix, e.g. "txx_MON"
    description: str  # R's subtitle, e.g. "txx: Monthly warmest daily TX"
    units: str  # R's y-axis label, e.g. "degrees_C"
    x: np.ndarray  # positions: decimal years, or day of the year for tx95t
    values: np.ndarray
    step: Step  # time step of the series (the slope is per step)
    bars: bool = False  # SPI/SPEI are drawn as bars
    trend: PlotTrend | None = None  # None: no trend (tx95t and the day_of_ plots)


def plot_file(out_dir: str | Path, station: str, name: str, suffix: str = ".png") -> Path:
    """Path R writes plot ``name`` (e.g. ``txx_MON``) to."""
    return Path(out_dir) / station / "plots" / f"{station}_{name}{suffix}"


def pdf_file(out_dir: str | Path, station: str) -> Path:
    """Path of the combined PDF, ``<station>_all_plots.pdf``."""
    return plot_file(out_dir, station, "all_plots", ".pdf")


def plot_steps(params: IndexParams) -> list[str]:
    """The progress stages of :func:`write_plots`: one per row of ``climate.indices.csv``
    (``plots:fd_ANN``, ``plots:hw``, ``plots:spei`` ...), then the custom index."""
    stages = []
    for short, name, suffix, _, _ in index_files(params, special=True):
        stages.append(short if short in ("hw", "hwEHF", "spei", "spi") else f"{name}_{suffix}")
    if params.custom is not None:
        stages += [f"{params.custom.name}_ANN", f"{params.custom.name}_MON"]
    return [f"plots:{s}" for s in stages]


def _positions(table: pd.DataFrame) -> tuple[np.ndarray, Step]:
    time = table["time"]
    if not pd.api.types.is_numeric_dtype(time):  # "1936-01": the middle of the month
        text = time.astype(str)
        years = text.str[:4].astype(int).to_numpy()
        months = text.str[5:7].astype(int).to_numpy()
        return years + (months - 0.5) / 12, "month"
    return time.to_numpy(dtype=float), "year"


def _series(
    name: str,
    description: str,
    units: str,
    table: pd.DataFrame | None,
    values: np.ndarray | None = None,
    trend: bool = True,
) -> IndexPlot | None:
    if table is None:
        return None
    if values is None:
        values = _value_column(table)
    if np.isnan(values).all():
        return None
    x, step = _positions(table)
    return IndexPlot(
        name, description, units, x, values, step, trend=plot_trend(values) if trend else None
    )


def _day_of(table: pd.DataFrame, monthly: bool) -> np.ndarray:
    dates = pd.to_datetime(table["ymd"], format="%Y-%m-%d", errors="coerce")
    days = dates.dt.day if monthly else dates.dt.day_of_year
    return days.to_numpy(dtype=float, na_value=np.nan)


def index_plots(
    tables: Mapping[str, pd.DataFrame], params: IndexParams
) -> Iterator[tuple[str, list[IndexPlot]]]:
    """The plots of a run, in R's order, grouped by the stages of :func:`plot_steps`."""
    units = [row["Units"] for row in _index_definitions()]
    stages = iter(plot_steps(params))
    for (short, name, suffix, frequency, definition), unit in zip(
        index_files(params, special=True), units, strict=True
    ):
        plots: list[IndexPlot | None] = []
        if short == "hw":
            for definition_name in ("TX90", "TN90"):
                for aspect, (long, text, hw_unit) in _HW_ASPECTS.items():
                    key = f"{definition_name}-{aspect}_ANN"
                    description = f"{definition_name}-{aspect} (Heatwave {long}): {text}"
                    plots.append(_series(key, description, hw_unit, tables.get(f"indices/{key}")))
        elif short == "hwEHF":
            for aspect, (description, ehf_unit) in _EHF_ASPECTS.items():
                key = f"EHF-{aspect}_ANN"
                plots.append(_series(key, description, ehf_unit, tables.get(f"indices/{key}")))
        elif short in ("spei", "spi"):
            for scale in dict.fromkeys((3, 6, 12, params.spei_months)):
                key = f"{scale}month_{short}_MON"
                plot = _series(
                    key, f"{scale}-month {short}: {definition}", unit, tables.get(f"indices/{key}")
                )
                plots.append(plot and replace(plot, bars=True))
        else:
            key = f"{name}_{suffix}"
            table = tables.get(f"indices/{key}")
            description = f"{name}: {definition}"
            if short == "tx95t":
                plot = _series(key, description, unit, table, trend=False)
                if plot is not None:
                    days = np.arange(1, len(plot.values) + 1, dtype=float)
                    plot = replace(plot, x=days, step="day")
                plots.append(plot)
            else:
                plots.append(_series(key, description, unit, table))
                if short in _DATED and short not in _NO_DAY_OF and table is not None:
                    plots.append(
                        _series(
                            f"day_of_{key}",
                            f"The calendar day of occurrence of {definition.lower()}",
                            "Calendar day",
                            table,
                            _day_of(table, frequency == "monthly"),
                            trend=False,
                        )
                    )
        yield next(stages), [p for p in plots if p is not None]

    if (spec := params.custom) is not None:
        threshold = format_r_number(spec.threshold)
        description = f"Number of days where {spec.variable} {spec.operator} {threshold}"
        for suffix in ("ANN", "MON"):
            key = f"{spec.name}_{suffix}"
            plot = _series(key, description, "days", tables.get(f"indices/{key}"))
            yield next(stages), [plot] if plot is not None else []


# ---------------------------------------------------------------------------- drawing

# Colours: the dataviz reference palette (blue and orange validated as a pair for
# colour-vision deficiency), with neutral inks for text, grid and axes.
_INK = "#0b0b0b"
_INK_2 = "#52514e"
_INK_3 = "#8a8985"
_GRID = "#e6e5e0"
_AXIS = "#b5b4ad"
_SERIES = "#2a78d6"
_WET = "#2a78d6"
_DRY = "#eb6834"
_TREND = "#e34948"
_TREND_ON_BARS = "#0b0b0b"

_WIDTH, _HEIGHT, _DPI = 10.0, 6.25, 120  # 1200 x 750 pixels
# PNGs are saved with a palette of 128 colours: about half the encoding time of
# matplotlib's RGBA PNGs, and files under half the size, with no visible difference.
_PNG_COLOURS = 128

_RC = {
    "font.size": 10,
    "axes.edgecolor": _AXIS,
    "axes.labelcolor": _INK_2,
    "xtick.color": _INK_2,
    "ytick.color": _INK_2,
    "path.simplify": True,
}
# PNG: matplotlib's DejaVu Sans, unhinted (smooth at this resolution, and about a third
# faster to render than hinted glyphs).
_RC_PNG = {**_RC, "font.family": "DejaVu Sans", "text.hinting": "none"}
# PDF: the standard Helvetica, which PDF viewers provide, so no font is embedded: half
# the time of embedding DejaVu Sans.
_RC_PDF = {
    **_RC,
    "font.family": "Helvetica",
    "pdf.use14corefonts": True,
    "axes.unicode_minus": False,  # not in the standard fonts' character set
}


def require_matplotlib():
    try:
        import matplotlib
    except ImportError:
        raise ImportError(
            "plots need matplotlib: install it with `pip install climpactpy[plots]`"
        ) from None
    return matplotlib


def station_title(metadata: StationMetadata) -> str:
    """``name  ·  33.86°S, 151.21°E``: R's ``title.station`` (``quality_control_checks.R``)
    without the minus sign R also keeps for south and west."""
    lat, lon = metadata.latitude, metadata.longitude
    lat_text = f"{format_r_number(abs(lat))}°{'S' if lat < 0 else 'N'}"
    lon_text = f"{format_r_number(abs(lon))}°{'W' if lon < 0 else 'E'}"
    return f"{metadata.name}  ·  {lat_text}, {lon_text}"


def _number(value: float) -> str:
    """3 decimals, as R rounds them, or 3 significant digits for smaller values."""
    if value == 0:
        return "0"
    if abs(value) < 0.0005:
        return f"{value:.2e}".replace("e-0", "e-")
    return f"{value:.3f}"


def trend_text(plot: IndexPlot) -> str:
    """The trend line of text under a plot (R's ``subtit``)."""
    trend = plot.trend
    if trend is None:
        return ""
    if not trend.valid:
        return "No linear trend: requires at least 10 values and 70% of the series to be valid."
    unit = _UNIT_LABELS.get(plot.units, plot.units)
    per = f"{unit} per {plot.step}" if unit else f"per {plot.step}"
    p = "p < 0.001" if trend.p_value < 0.0005 else f"p = {trend.p_value:.3f}"
    return (
        f"Sen's slope {_number(trend.slope)} {per}  "
        f"(95% CI {_number(trend.lower)} to {_number(trend.upper)}),  Mann-Kendall {p}"
    )


class _Canvas:
    """One figure, reused for every plot: its artists are created once and each plot only
    updates their data and text, which is several times faster than building a new
    figure per plot. Each plot is then saved as a PNG and as a PDF page."""

    _LEFT, _RIGHT, _BOTTOM = 0.085, 0.97, 0.2

    def __init__(self, metadata: StationMetadata) -> None:
        require_matplotlib()
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.collections import PolyCollection
        from matplotlib.figure import Figure
        from matplotlib.transforms import blended_transform_factory

        fig = self.figure = Figure(figsize=(_WIDTH, _HEIGHT), dpi=_DPI, facecolor="white")
        FigureCanvasAgg(fig)
        left, right = self._LEFT, self._RIGHT
        fig.text(left, 0.945, station_title(metadata), color=_INK_2, fontsize=10)
        self.title = fig.text(left, 0.915, "", color=_INK, fontsize=12.5, weight="bold", va="top")
        self.trend_text = fig.text(left, 0.105, "", color=_INK, fontsize=10.5)
        fig.text(
            right,
            0.025,
            f"climpactpy {__version__}  ·  Climpact {CLIMPACT_VERSION}",
            color=_INK_3,
            fontsize=8,
            ha="right",
        )

        ax = self.ax = fig.add_axes((left, self._BOTTOM, right - left, 0.6))
        ax.set_autoscale_on(False)
        ax.grid(axis="y", color=_GRID, linewidth=0.8)
        ax.grid(axis="x", color=_GRID, linewidth=0.5)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.tick_params(length=3, labelsize=10)
        ax.yaxis.label.set_fontsize(11)

        # SPI/SPEI: one collection of bars, not a patch per bar (~1000 bars).
        self.bars = PolyCollection([], linewidths=0, antialiaseds=False, zorder=2)
        ax.add_collection(self.bars, autolim=False)
        self.zero = ax.axhline(0, color=_AXIS, linewidth=0.8, zorder=2)
        (self.line,) = ax.plot([], [], color=_SERIES, marker="o", zorder=3)
        (self.trend,) = ax.plot([], [], linewidth=2, zorder=4, solid_capstyle="round")
        self.rug_style = {"marker": "|", "markersize": 7, "markeredgewidth": 1.2, "color": _INK_3}
        (self.rug,) = ax.plot(
            [],
            [],
            transform=blended_transform_factory(ax.transData, ax.transAxes),
            linestyle="none",
            clip_on=False,
            zorder=5,
            **self.rug_style,
        )
        self.legend = None

    def draw(self, plot: IndexPlot) -> None:
        from matplotlib.lines import Line2D
        from matplotlib.patches import Patch
        from matplotlib.ticker import AutoLocator, MaxNLocator

        fig, ax = self.figure, self.ax
        title = textwrap.wrap(plot.description, 88)
        self.title.set_text("\n".join(title))
        top = 0.885 - 0.038 * len(title)
        ax.set_position((self._LEFT, self._BOTTOM, self._RIGHT - self._LEFT, top - self._BOTTOM))

        x, y = plot.x, plot.values
        missing = np.isnan(y)
        spacing = {"year": 1.0, "month": 1 / 12, "day": 1.0}[plot.step]
        low, high = float(np.nanmin(y)), float(np.nanmax(y))
        handles = []

        self.bars.set_visible(plot.bars)
        self.zero.set_visible(plot.bars)
        self.line.set_visible(not plot.bars)
        if plot.bars:
            ok = ~missing
            x0, x1, h = x[ok] - spacing / 2, x[ok] + spacing / 2, y[ok]
            zero = np.zeros_like(h)
            self.bars.set_verts(
                np.stack([np.c_[x0, zero], np.c_[x0, h], np.c_[x1, h], np.c_[x1, zero]], 1)
            )
            self.bars.set_facecolors(np.where(h >= 0, _WET, _DRY))
            low, high = min(low, 0.0), max(high, 0.0)
            handles += [Patch(color=_WET, label="wet (> 0)"), Patch(color=_DRY, label="dry (< 0)")]
        else:
            monthly = plot.step == "month"
            self.line.set_data(x, y)
            self.line.set(
                linewidth=0.7 if monthly else 1.4,
                markersize=2.2 if monthly else 4,
                markerfacecolor=_SERIES if monthly else "white",
                markeredgewidth=0 if monthly else 1.2,
            )

        trend = plot.trend
        if trend is not None and trend.valid:
            # x counted from 0 at the first value, one per time step.
            ends = [trend.intercept, trend.intercept + trend.slope * (len(x) - 1)]
            colour = _TREND_ON_BARS if plot.bars else _TREND
            self.trend.set_data([x[0], x[-1]], ends)
            self.trend.set_color(colour)
            self.trend.set_visible(True)
            low, high = min(low, *ends), max(high, *ends)
            handles.append(Line2D([], [], color=colour, linewidth=2, label="Sen's slope trend"))
        else:
            self.trend.set_visible(False)

        self.rug.set_data(x[missing], np.full(missing.sum(), 0.012))
        if missing.any():
            label = f"missing ({missing.sum()} of {len(y)})"
            handles.append(Line2D([], [], linestyle="none", label=label, **self.rug_style))

        pad = 0.05 * (high - low) if high > low else 1.0  # a constant series: +-1
        ax.set_ylim(low - pad, high + pad)
        ax.set_xlim(x[0] - spacing / 2, x[-1] + spacing / 2)
        ax.yaxis.set_major_locator(MaxNLocator(nbins=7))
        if plot.step == "day":
            ax.xaxis.set_major_locator(AutoLocator())
            ax.set_xlabel("Day of the year", fontsize=10)
        else:
            ax.xaxis.set_major_locator(MaxNLocator(nbins=12, integer=True, steps=[1, 2, 5, 10]))
            ax.set_xlabel("")
        ax.set_ylabel(_UNIT_LABELS.get(plot.units, plot.units))

        self.trend_text.set_text(trend_text(plot))
        if self.legend is not None:
            self.legend.remove()
            self.legend = None
        if handles:
            self.legend = fig.legend(
                handles=handles,
                loc="lower left",
                bbox_to_anchor=(self._LEFT - 0.006, 0.012),
                ncol=len(handles),
                frameon=False,
                fontsize=9,
                handlelength=1.6,
                borderaxespad=0,
                labelcolor=_INK_2,
            )


def write_plots(
    tables: Mapping[str, pd.DataFrame],
    metadata: StationMetadata,
    params: IndexParams,
    out_dir: str | Path,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Path]:
    """Draw every plot of a run as R names them, and the combined PDF.

    ``tables`` are the run's output tables (as returned by ``build_all``). Writes
    ``<out_dir>/<station>/plots/<station>_<name>.png`` for each plot and
    ``<station>_all_plots.pdf`` with every plot as a page, in R's order. Returns the path
    of each plot by name, and of the PDF under ``"all_plots"``. ``progress(stage)`` is
    called after each stage of :func:`plot_steps`. Needs matplotlib.
    """
    matplotlib = require_matplotlib()
    from matplotlib.backends.backend_pdf import PdfPages

    station = metadata.name
    pdf_path = pdf_file(out_dir, station)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with matplotlib.rc_context(_RC_PNG):
        png_canvas = _Canvas(metadata)
    with matplotlib.rc_context(_RC_PDF), _quiet_font_manager():
        pdf_canvas = _Canvas(metadata)
    written: dict[str, Path] = {}
    with PdfPages(pdf_path, metadata={"Title": f"{station}: Climpact index plots"}) as pdf:
        for stage, plots in index_plots(tables, params):
            for plot in plots:
                path = plot_file(out_dir, station, plot.name)
                with matplotlib.rc_context(_RC_PNG):
                    png_canvas.draw(plot)
                    _save_png(png_canvas.figure, path)
                with matplotlib.rc_context(_RC_PDF), _quiet_font_manager():
                    pdf_canvas.draw(plot)
                    pdf.savefig(pdf_canvas.figure)
                written[plot.name] = path
            if progress is not None:
                progress(stage)
    written["all_plots"] = pdf_path
    return written


def _save_png(figure, path: Path) -> None:
    from PIL import Image

    figure.canvas.draw()
    image = Image.fromarray(np.asarray(figure.canvas.buffer_rgba())).convert("RGB")
    image = image.quantize(_PNG_COLOURS, method=Image.Quantize.FASTOCTREE)
    image.save(path, "png", compress_level=3, dpi=(_DPI, _DPI))


@contextmanager
def _quiet_font_manager() -> Iterator[None]:
    """Silence the font manager's warnings that the weight asked for is not Helvetica's
    exact weight: it finds Helvetica anyway, and the PDF names the standard font."""
    logger = logging.getLogger("matplotlib.font_manager")
    level = logger.level
    logger.setLevel(logging.ERROR)
    try:
        yield
    finally:
        logger.setLevel(level)


# ---------------------------------------------------------------------------- zip


def zip_folder(folder: str | Path, zip_path: str | Path, exclude_suffix: str | None = None) -> Path:
    """Zip the contents of ``folder`` (not the folder itself) to ``zip_path``.

    As R's ``zipFiles``, which runs ``zip -r9X`` in the folder: entries are relative to
    the folder, folders have their own entries, and files ending in ``exclude_suffix``
    are left out (R's ``excludePattern = "*.zip"``). Entries are sorted, so the archive
    does not depend on the order the file system lists them. CSV files are deflated at
    zip's level 9, as R's; PNG and PDF files, compressed already, are stored.
    """
    folder, zip_path = Path(folder), Path(zip_path)
    entries: list[tuple[Path, str]] = []
    for root, dirs, files in os.walk(folder):
        dirs.sort()
        base = Path(root)
        rel = base.relative_to(folder)
        if rel != Path("."):
            entries.append((base, rel.as_posix() + "/"))
        for name in sorted(files):
            if exclude_suffix and name.endswith(exclude_suffix):
                continue
            path = base / name
            if path.resolve() == zip_path.resolve():
                continue
            entries.append((path, (rel / name).as_posix()))
    tmp = zip_path.with_name(zip_path.name + ".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, arcname in sorted(entries, key=lambda e: e[1]):
            # PNG and PDF files are compressed already: stored, they zip twice as fast.
            stored = path.suffix in (".png", ".pdf")
            archive.write(path, arcname, zipfile.ZIP_STORED if stored else None)
    tmp.replace(zip_path)
    return zip_path


def zip_station(out_dir: str | Path, station: str) -> Path:
    """``<out_dir>/<station>.zip``: the station folder, as R's single-station download.

    R (``singleStationStep3.R``) zips the station folder into the folder above it as
    ``<station>.zip``, with entries ``indices/...``, ``plots/...`` and so on, and leaves
    out any ``.zip`` file in it.
    """
    out_dir = Path(out_dir)
    return zip_folder(out_dir / station, out_dir / f"{station}.zip", exclude_suffix=".zip")


def zip_batch(out_dir: str | Path) -> Path:
    """``<parent>/<name>.zip`` next to the batch folder ``<parent>/<name>``, as R's batch
    download (``batchStep1.R``): entries ``<station>/...`` and the error files."""
    out_dir = Path(out_dir)
    return zip_folder(out_dir, out_dir.parent / f"{out_dir.name}.zip")


__all__ = [
    "IndexPlot",
    "index_plots",
    "pdf_file",
    "plot_file",
    "plot_steps",
    "station_title",
    "trend_text",
    "write_plots",
    "zip_batch",
    "zip_folder",
    "zip_station",
]
