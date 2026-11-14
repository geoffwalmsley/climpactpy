"""Sector correlation: annual sector data (crop yields, ...) against a station's indices.

Ports step 4 of the R app, ``draw.correlation`` in ``server/sector_correlation.R`` as
``modules/singleStationStep4.R`` calls it after an index run. The user gives a CSV file of
annual sector data, ``Year,<value>`` (Climpact's sample is
``www/sample_data/wheat_yield_nsw_1922-1999.csv``), and R writes to the station's
``corr/`` folder, ``<out>/<station>/corr/``:

- four scatter plots of the sector series against the station's yearly mean TX, mean TN,
  mean of TX and TN together, and number of days with TX > 30 °C, each with its linear
  regression, as ``<station>_corr_{tmin,tmax,t,above30}_<part>.png``, and their data as
  ``.csv`` (``year``, the temperature summary, the sector series);
- a bar chart of the correlation of the sector series with each of 42 annual indices, as
  ``<station>_index-sector_correlation_<part>.png``, and its data as ``.csv`` (``indice``,
  ``cor``, ``category``).

``<part>`` is the sector column's name as ``read.csv`` makes it, lower-cased and cut at the
first ``..``: ``wheat.yield`` for ``Wheat yield (t/ha)``, ``detrended.wheat.yield`` when the
series is detrended (the app's default). The download is ``<out>/<station>_corr.zip``.

R's behaviour is reproduced, including its quirks (see TECHNICAL.md, "Sector
correlation"): the temperature summaries come from the raw station file, not the QC'd
data; the indices are read back from their CSV files, so a missing index value is
correlated as the number ``-99.9`` it is written as; detrending subtracts the
regression slope times the *row number* from the middle row; and the indices correlated
are a fixed list of file names (``hddheat18``, ``tx2tn2``, ``wsdi``, ...), so those written
under other names (another base temperature, ``wsdi3``) are left out.

:func:`sector_correlation` is the calculation, on a station's daily rows and index tables
in memory; :func:`write_sector_correlation` writes its files; and
:func:`run_sector_correlation` does both for a station already run, reading the index CSV
files the run wrote, as the R app does after step 3: it is what ``climpact
sector-correlation`` and the web app call.
"""

from __future__ import annotations

import csv
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np
import pandas as pd

from climpact.io.climpact_csv import MISSING_VALUE, format_r_number, read_climpact_csv
from climpact.io.output_files import is_all_missing
from climpact.progress import Progress, Steps
from climpact.rnumerics import r_mean, r_round

# R's message when the station and the sector data have fewer than 10 years in common
# (and when an index has none), without its "Error: " prefix.
NO_COMMON_DATA = "not able to make a correlation, since there is no data in common!"
MIN_COMMON_YEARS = 10

# The indices R correlates, in its order, with their category (create.correlation.plots).
# They are file names: R reads <station>_<index>_ANN.csv and skips those not written.
_TEMPERATURE = "temperature"
_PRECIPITATION = "precipitation"
_GROUPS = (
    (
        _TEMPERATURE,
        "fd tnlt2 tnltm2 tnltm20 su tr gsl txx tnn wsdi csdi txgt50p tmge5 tmlt5 tmge10 tmlt10 "
        "txge30 txge35 tx2tn2 hddheat18 cddcold18 gddgrow10",
    ),
    (_PRECIPITATION, "cdd r20mm r95ptot"),
    (_TEMPERATURE, "txb2tnb2 dtr tnx txn tmm txm tnm tx10p tx90p tn10p tn90p"),
    (_PRECIPITATION, "cwd r10mm sdii r95p rx1day rx5day"),
)
SECTOR_INDICES: tuple[tuple[str, str], ...] = tuple(
    (name, category) for category, names in _GROUPS for name in names.split()
)

# exact_date_indices (server/global_variables.r): the value column of the indices written
# with dates. Every other index's value column is named after the index.
_VALUE_COLUMNS = {
    "tnn": "val",
    "tnx": "val",
    "txn": "val",
    "txx": "val",
    "rx1day": "val",
    "rx5day": "val",
    "cdd": "duration",
    "cwd": "duration",
    "gsl": "sl",
}

# The four scatter plots: (name in the file name, temperature column, x-axis label).
SCATTERS = (
    ("tmin", "avg_tmin", "Average min temperature"),
    ("tmax", "avg_tmax", "Average max temperature"),
    ("t", "avg_t", "Average temperature"),
    ("above30", "above30", "Days above 30°C"),
)

_DETRENDED = "Detrended"


class SectorCorrelationError(ValueError):
    """The correlation cannot be made; R shows the message to the user instead."""


# ------------------------------------------------------------------------- sector file

# R's reserved words, which make.names follows with a ".".
_R_RESERVED = {
    "if", "else", "repeat", "while", "function", "for", "next", "break", "TRUE", "FALSE",
    "NULL", "Inf", "NaN", "NA", "NA_integer_", "NA_real_", "NA_character_", "in",
}  # fmt: skip


def r_make_names(names: list[str]) -> list[str]:
    """R ``make.names(names, unique = TRUE)``, as ``read.csv`` applies it to the header.

    A name not starting with a letter, or with a dot followed by a digit, gets an ``X``
    in front; every character other than a letter, digit, ``.`` or ``_`` becomes ``.``;
    reserved words get a ``.`` after; repeated names get ``.1``, ``.2`` ... after them
    (``make.unique``).
    """
    out = []
    for name in names:
        first = name[:1]
        if not first or not (first.isalpha() or first == ".") or re.match(r"\.\d", name):
            name = "X" + name
        name = "".join(c if c.isalnum() or c in "._" else "." for c in name)
        if name in _R_RESERVED:
            name += "."
        out.append(name)
    seen: dict[str, int] = {}
    taken = set(out)
    unique = []
    for name in out:
        if name in seen:
            n = seen[name]
            while (candidate := f"{name}.{n}") in taken:
                n += 1
            seen[name] = n + 1
            taken.add(candidate)
            unique.append(candidate)
        else:
            seen[name] = 1
            unique.append(name)
    return unique


def _r_number(text: str, column: str, line: int) -> float:
    text = text.strip()
    if text in ("", "NA"):
        return math.nan
    try:
        return float(text)
    except ValueError:
        raise SectorCorrelationError(
            f"sector file line {line}: {column} value {text!r} is not a number"
        ) from None


@dataclass(frozen=True)
class SectorData:
    """Annual sector data: one value per year, in file order.

    ``column`` is the value column's name as R's ``read.csv`` makes it (for example
    ``Wheat.yield..t.ha.``); it names the column in the output files and the file names'
    ``<part>``. Missing values (``NA``, empty or ``-99.9``) are NaN.
    """

    years: np.ndarray
    values: np.ndarray
    column: str

    def __post_init__(self) -> None:
        years = np.asarray(self.years, dtype=float)
        values = np.asarray(self.values, dtype=float)
        if years.shape != values.shape or years.ndim != 1:
            raise ValueError("years and values must be 1-D and of the same length")
        if np.isnan(years).any():
            raise SectorCorrelationError("the sector data has a missing year")
        if (np.diff(years) <= 0).any():
            raise SectorCorrelationError(
                "the years of the sector data must increase from row to row, with no year "
                "repeated (R pairs the rows with the station's years by position)"
            )
        object.__setattr__(self, "years", years)
        object.__setattr__(self, "values", np.where(values == MISSING_VALUE, np.nan, values))

    @property
    def detrended_column(self) -> str:
        """Name of the detrended series (R's ``getDetrendedColumnName``)."""
        return f"{_DETRENDED}.{self.column}"


def read_sector_file(path: str | Path) -> SectorData:
    """Read a sector CSV file as R's ``read.csv`` does: a header row, then ``Year`` and
    one value per row. ``-99.9`` is missing (R replaces it with ``NA``)."""
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        rows = [row for row in csv.reader(f) if any(field.strip() for field in row)]
    if not rows:
        raise SectorCorrelationError("the sector file is empty")
    header = r_make_names([name.strip() for name in rows[0]])
    if len(header) != 2:
        raise SectorCorrelationError(
            f"the sector file must have two columns, Year and the sector data; it has "
            f"{len(header)} ({', '.join(header)})"
        )
    if header[0] != "Year":
        raise SectorCorrelationError(
            f"the first column of the sector file must be named Year, not {rows[0][0]!r}"
        )
    years, values = [], []
    for line, row in enumerate(rows[1:], start=2):
        if len(row) != 2:
            raise SectorCorrelationError(
                f"sector file line {line}: expected 2 fields, got {len(row)}"
            )
        years.append(_r_number(row[0], "Year", line))
        values.append(_r_number(row[1], header[1], line))
    return SectorData(np.array(years), np.array(values), header[1])


def default_y_label(sector_file: str | Path) -> str:
    """The app's default y-axis label: the sector file name up to its first ``_`` or ``.``
    (``wheat`` for ``wheat_yield_nsw_1922-1999.csv``)."""
    return re.split(r"[_.]", Path(sector_file).name)[0]


def file_part(column: str) -> str:
    """The part of the file names naming a sector column: the column name cut at its
    first ``..``, lower-cased (``gsub("\\\\.{2}.*$", "", ...)``)."""
    return re.sub(r"\.{2}.*$", "", column, count=1).lower()


def detrend(years: np.ndarray, values: np.ndarray) -> np.ndarray:
    """R's ``calculateDeTrendValues``: each value minus the regression slope times its
    row's distance from the middle row.

    The slope is that of ``lm(values ~ years)`` (rows with a missing value left out), here
    the exact least-squares slope rounded once to a double; R's QR decomposition can
    differ from it in the last bit. The distance is counted in rows, not years, from row
    ``(n + 1) / 2`` when the number of rows ``n`` is odd and ``(n + 2) / 2`` when it is
    even. A missing value stays missing; with fewer than two values, or one year only, R's
    slope is ``NA`` and so is every result.
    """
    years = np.asarray(years, dtype=float)
    values = np.asarray(values, dtype=float)
    ok = ~(np.isnan(years) | np.isnan(values))
    xs = [Fraction(v) for v in years[ok].tolist()]
    ys = [Fraction(v) for v in values[ok].tolist()]
    n = len(values)
    if len(xs) < 2:
        return np.full(n, np.nan)
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return np.full(n, np.nan)
    slope = float(sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx)
    middle = (n + 1) / 2 if n % 2 == 1 else (n + 2) / 2
    rows = np.arange(1, n + 1, dtype=float)
    return values - (rows - middle) * slope


# ------------------------------------------------------------------ station temperatures


def annual_temperature(rows: pd.DataFrame) -> pd.DataFrame:
    """The yearly temperature summaries R correlates with the sector data.

    ``rows`` has ``year``, ``tmax`` and ``tmin`` columns (NaN for missing), one row per
    day, as R's ``read_user_file`` reads the station file
    (:func:`climpact.io.station.read_station_rows`). Returns, per year in increasing order:
    ``avg_tmax`` and ``avg_tmin`` (means of the values present), ``avg_t`` (the mean of
    every TX and TN value of the year together) and ``above30`` (days with TX > 30).
    """
    out = []
    for year, group in rows.groupby("year", sort=True):
        tmax = group["tmax"].to_numpy(dtype=float)
        tmin = group["tmin"].to_numpy(dtype=float)
        both = np.concatenate([tmax, tmin])
        out.append(
            {
                "year": float(year),
                "avg_tmax": r_mean(tmax[~np.isnan(tmax)]),
                "avg_tmin": r_mean(tmin[~np.isnan(tmin)]),
                "avg_t": r_mean(both[~np.isnan(both)]),
                "above30": int(np.count_nonzero(tmax > 30)),
            }
        )
    columns = ["year", "avg_tmax", "avg_tmin", "avg_t", "above30"]
    return pd.DataFrame(out, columns=columns)


# --------------------------------------------------------------------------- calculation


@dataclass(frozen=True)
class Regression:
    """``lm(sector ~ temperature)`` as R annotates a scatter plot (rounded to 2 decimals)."""

    slope: float
    intercept: float
    r_squared: float


@dataclass(frozen=True)
class Scatter:
    """One scatter plot: a temperature summary against the sector series."""

    name: str  # "tmin", "tmax", "t" or "above30"
    x_label: str
    table: pd.DataFrame  # year, the temperature summary, the sector series
    regression: Regression | None  # None: fewer than two complete rows


@dataclass(frozen=True)
class SectorCorrelation:
    """The result of :func:`sector_correlation`: what R writes to the ``corr/`` folder."""

    station: str
    sector_column: str  # the series correlated: the sector column or its detrended one
    scatters: tuple[Scatter, ...]
    correlations: pd.DataFrame  # indice, cor, category: one row per index found

    @property
    def detrended(self) -> bool:
        # R checks the column name (grepl("Detrended", sectorCol)), for the file names
        # and for which correlation it takes.
        return _DETRENDED in self.sector_column

    @property
    def file_part(self) -> str:
        return file_part(self.sector_column)

    def file_stem(self, name: str) -> str:
        """File name without suffix: ``scatter`` names (``tmin`` ...) or ``"bar"``."""
        if name == "bar":
            return f"{self.station}_index-sector_correlation_{self.file_part}"
        return f"{self.station}_corr_{name}_{self.file_part}"


def _as_written(values: np.ndarray) -> np.ndarray:
    """Index values as R reads them back from the CSV file: 15 significant digits, and
    a missing value as the number -99.9."""
    return np.array(
        [MISSING_VALUE if math.isnan(v) else float(format_r_number(v)) for v in values.tolist()]
    )


def _r_cor(x: np.ndarray, y: np.ndarray) -> float:
    """R ``cor(x, y)`` (Pearson, ``use = "everything"``): NA when either has a missing
    value or no variation."""
    if len(x) < 2 or np.isnan(x).any() or np.isnan(y).any():
        return math.nan
    dx = x - r_mean(x)
    dy = y - r_mean(y)
    sxx = math.fsum(dx * dx)
    syy = math.fsum(dy * dy)
    if sxx == 0 or syy == 0:
        return math.nan
    r = math.fsum(dx * dy) / math.sqrt(sxx * syy)
    return max(-1.0, min(1.0, r))


def regression(x: np.ndarray, y: np.ndarray) -> Regression | None:
    """``lm(y ~ x)`` on the years with both values, rounded to 2 decimals as R annotates
    the scatter plots; ``None`` with fewer than two such years or no variation in x."""
    ok = ~(np.isnan(x) | np.isnan(y))
    x, y = x[ok], y[ok]
    if len(x) < 2 or np.ptp(x) == 0:
        return None
    dx, dy = x - x.mean(), y - y.mean()
    slope = float((dx * dy).sum() / (dx * dx).sum())
    intercept = float(y.mean() - slope * x.mean())
    syy = float((dy * dy).sum())
    r2 = 1 - float(((dy - slope * dx) ** 2).sum()) / syy if syy > 0 else math.nan
    slope, intercept, r2 = r_round(np.array([slope, intercept, r2]), 2).tolist()
    return Regression(slope, intercept, r2)


def _index_values(table: pd.DataFrame, index: str) -> tuple[np.ndarray, np.ndarray]:
    column = _VALUE_COLUMNS.get(index, index)
    if "time" not in table or column not in table:
        raise SectorCorrelationError(f"the {index} table has no time or {column} column")
    years = pd.to_numeric(table["time"]).to_numpy(dtype=float)
    return years, _as_written(table[column].to_numpy(dtype=float))


def sector_correlation(
    rows: pd.DataFrame,
    index_tables: Mapping[str, pd.DataFrame],
    sector: SectorData,
    station: str,
    detrend_sector: bool = True,
) -> SectorCorrelation:
    """Correlate annual sector data with a station's temperatures and indices, as R's
    ``create.correlation.plots``.

    ``rows`` are the station's daily rows (``year``, ``tmax``, ``tmin``; R uses the raw
    station file, :func:`climpact.io.station.read_station_rows`), ``index_tables`` the
    run's index tables keyed ``indices/<name>_ANN`` (as ``build_all`` returns them, or read
    back from the files). Tables missing in every year are left out, as R writes no file
    for them. ``detrend_sector`` correlates the detrended series, the app's default.

    Raises :class:`SectorCorrelationError` with R's message when the station and the
    sector data have fewer than 10 years in common, or an index has none.
    """
    temperature = annual_temperature(rows)
    common = np.intersect1d(temperature["year"].to_numpy(), sector.years)
    if len(common) < MIN_COMMON_YEARS:
        raise SectorCorrelationError(NO_COMMON_DATA)

    # Detrended over the whole sector file, then cut to the station's years.
    detrended = detrend(sector.years, sector.values)
    in_common = np.isin(sector.years, common)
    years = sector.years[in_common]
    raw, detrended = sector.values[in_common], detrended[in_common]
    temperature = temperature[temperature["year"].isin(common)].reset_index(drop=True)

    column = sector.detrended_column if detrend_sector else sector.column
    series = detrended if _DETRENDED in column else raw
    scatters = []
    for name, x_column, x_label in SCATTERS:
        x = temperature[x_column].to_numpy()
        table = pd.DataFrame({"year": temperature["year"], x_column: x, column: series})
        scatters.append(Scatter(name, x_label, table, regression(x.astype(float), series)))

    rows_out = []
    for index, category in SECTOR_INDICES:
        table = index_tables.get(f"indices/{index}_ANN")
        if table is None or is_all_missing(table):
            continue  # R: "File does not exist"
        index_years, values = _index_values(table, index)
        both = np.intersect1d(index_years, years)
        if len(both) == 0:
            raise SectorCorrelationError(NO_COMMON_DATA)
        values = values[np.isin(index_years, both)]
        chosen = series[np.isin(years, both)]
        if len(values) != len(chosen):
            raise SectorCorrelationError(f"the {index} table has a year more than once")
        cor = float(r_round(np.array([_r_cor(chosen, values)]), 2)[0])
        rows_out.append({"indice": index, "cor": cor, "category": category})
    correlations = pd.DataFrame(rows_out, columns=["indice", "cor", "category"])
    return SectorCorrelation(station, column, tuple(scatters), correlations)


# ------------------------------------------------------------------------------- writing


def _r_csv_field(value) -> str:
    if isinstance(value, str):
        return '"' + value.replace('"', '""') + '"'
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "NA"
    return format_r_number(value)


def write_r_csv(path: str | Path, table: pd.DataFrame) -> Path:
    """Write a table as R's ``write.csv(row.names = FALSE)``: quoted header and strings,
    numbers to 15 significant digits, ``NA`` for missing values (NaN too)."""
    lines = [",".join(_r_csv_field(str(name)) for name in table.columns)]
    for row in table.itertuples(index=False):
        lines.append(",".join(_r_csv_field(v) for v in row))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path


def corr_dir(out_dir: str | Path, station: str) -> Path:
    """The station's correlation folder, ``<out_dir>/<station>/corr`` (R's ``corrdir``)."""
    return Path(out_dir) / station / "corr"


def corr_zip(out_dir: str | Path, station: str) -> Path:
    """R's download of the correlation folder, ``<out_dir>/<station>_corr.zip``."""
    return Path(out_dir) / f"{station}_corr.zip"


def sector_steps(zip: bool = False) -> list[str]:
    """The progress stages of :func:`run_sector_correlation`."""
    stages = ["read", "correlate"]
    stages += [f"write:{name}" for name, _, _ in SCATTERS] + ["write:index-sector"]
    return stages + (["zip"] if zip else [])


def write_sector_correlation(
    result: SectorCorrelation,
    folder: str | Path,
    title: str | None = None,
    y_label: str = "",
    plots: bool = True,
    progress: Steps | None = None,
) -> dict[str, Path]:
    """Write R's correlation files to ``folder`` (R's ``corr/``): each scatter's and the bar
    chart's CSV and, with ``plots``, PNG. ``title`` (default: the station name) and
    ``y_label`` label the plots. Returns the paths keyed by file name without suffix
    and station (``corr_tmin_wheat.yield``, ``corr_tmin_wheat.yield.png``, ...)."""
    folder = Path(folder)
    title = result.station if title is None else title
    drawer = _Drawer() if plots else None
    written: dict[str, Path] = {}

    def add(stem: str, suffix: str, path: Path) -> None:
        written[stem.removeprefix(f"{result.station}_") + suffix] = path

    for scatter in result.scatters:
        stem = result.file_stem(scatter.name)
        add(stem, "", write_r_csv(folder / f"{stem}.csv", scatter.table))
        if drawer is not None:
            path = folder / f"{stem}.png"
            drawer.scatter(scatter, result.sector_column, title, y_label, path)
            add(stem, ".png", path)
        if progress is not None:
            progress.done(f"write:{scatter.name}")
    stem = result.file_stem("bar")
    add(stem, "", write_r_csv(folder / f"{stem}.csv", result.correlations))
    if drawer is not None:
        path = folder / f"{stem}.png"
        drawer.bar(result.correlations, title, path)
        add(stem, ".png", path)
    if progress is not None:
        progress.done("write:index-sector")
    return written


def read_index_tables(indices_dir: str | Path, station: str) -> dict[str, pd.DataFrame]:
    """The index tables R's correlation reads, from a run's ``indices/`` folder: the
    ``<station>_<index>_ANN.csv`` files of :data:`SECTOR_INDICES` that exist."""
    tables = {}
    for index, _ in SECTOR_INDICES:
        path = Path(indices_dir) / f"{station}_{index}_ANN.csv"
        if path.is_file():
            tables[f"indices/{index}_ANN"] = read_climpact_csv(path).data
    return tables


def run_sector_correlation(
    station_file: str | Path,
    sector_file: str | Path,
    out_dir: str | Path,
    station: str,
    detrend_sector: bool = True,
    title: str | None = None,
    y_label: str | None = None,
    index_tables: Mapping[str, pd.DataFrame] | None = None,
    plots: bool = False,
    zip: bool = False,
    progress: Progress | None = None,
) -> dict[str, Path]:
    """Sector correlation for a station already run, as the app's step 4.

    ``station_file`` is the station's input file and ``out_dir`` the folder the run wrote
    ``<station>/`` to. The index tables are read from ``<out_dir>/<station>/indices/``
    unless ``index_tables`` gives them (a run's tables in memory). The files go to
    ``<out_dir>/<station>/corr/``; ``zip`` then zips that folder to
    ``<out_dir>/<station>_corr.zip`` (under ``"zip"`` in the result). ``title`` defaults
    to the station name and ``y_label`` to :func:`default_y_label`, as in the app.
    ``progress(stage, step, total)`` is called after each stage of :func:`sector_steps`.

    Raises :class:`SectorCorrelationError` when R would show an error instead.
    """
    from climpact.io.station import read_station_rows

    if plots:
        from climpact.plots import require_matplotlib

        require_matplotlib()
    steps = Steps(progress, len(sector_steps(zip)))
    rows = read_station_rows(station_file)
    sector = read_sector_file(sector_file)
    if index_tables is None:
        index_tables = read_index_tables(Path(out_dir) / station / "indices", station)
    steps.done("read")
    result = sector_correlation(rows, index_tables, sector, station, detrend_sector)
    steps.done("correlate")
    label = default_y_label(sector_file) if y_label is None else y_label
    folder = corr_dir(out_dir, station)
    written = write_sector_correlation(result, folder, title, label, plots, steps)
    if zip:
        from climpact.plots import zip_folder

        written["zip"] = zip_folder(folder, corr_zip(out_dir, station), exclude_suffix=".zip")
        steps.done("zip")
    return written


# ------------------------------------------------------------------------------- drawing


def _number(value: float) -> str:
    return "NA" if math.isnan(value) else format_r_number(value)


def regression_text(regression: Regression | None) -> str:
    """R's annotation, ``Y= 0.05 X - 0.32``, ``R2: 0.04``, on one line."""
    if regression is None:
        return "No regression: fewer than two years with both values."
    sign = "+" if regression.intercept >= 0 else "-"
    return (
        f"Y = {_number(regression.slope)} X {sign} {_number(abs(regression.intercept))}"
        f"   R² = {_number(regression.r_squared)}"
    )


class _Drawer:
    """Draws the scatter and bar plots in the style of :mod:`climpact.plots`."""

    def __init__(self) -> None:
        from climpact.plots import require_matplotlib

        self.matplotlib = require_matplotlib()

    def _figure(self, width: float, height: float):
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure

        from climpact import plots

        fig = Figure(figsize=(width, height), dpi=plots._DPI, facecolor="white")
        FigureCanvasAgg(fig)
        return fig

    def _style(self, ax) -> None:
        from climpact import plots

        ax.grid(axis="y", color=plots._GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.tick_params(length=3, labelsize=10)

    def _footer(self, fig, right: float) -> None:
        from climpact import __version__, plots

        fig.text(
            right,
            0.02,
            f"climpactpy {__version__}  ·  Climpact {plots.CLIMPACT_VERSION}",
            color=plots._INK_3,
            fontsize=8,
            ha="right",
        )

    def scatter(
        self, scatter: Scatter, sector_column: str, title: str, y_label: str, path: Path
    ) -> None:
        from climpact import plots

        with self.matplotlib.rc_context(plots._RC_PNG):
            fig = self._figure(8.0, 6.0)
            left, right = 0.11, 0.96
            fig.text(left, 0.945, title, color=plots._INK, fontsize=12.5, weight="bold")
            fig.text(
                left, 0.905, f"{sector_column} against {scatter.x_label.lower()}",
                color=plots._INK_2, fontsize=10,
            )  # fmt: skip
            ax = fig.add_axes((left, 0.17, right - left, 0.69))
            self._style(ax)
            ax.grid(axis="x", color=plots._GRID, linewidth=0.5)
            table = scatter.table
            x = table.iloc[:, 1].to_numpy(dtype=float)
            y = table.iloc[:, 2].to_numpy(dtype=float)
            ax.plot(
                x, y, linestyle="none", marker="o", markersize=5, color=plots._SERIES,
                markerfacecolor="white", markeredgewidth=1.3, zorder=3,
            )  # fmt: skip
            reg = scatter.regression
            if reg is not None:
                # The unrounded fit, as R's geom_smooth draws it.
                ok = ~(np.isnan(x) | np.isnan(y))
                slope, intercept = np.polyfit(x[ok], y[ok], 1)
                ends = np.array([np.nanmin(x), np.nanmax(x)])
                ax.plot(ends, intercept + slope * ends, color=plots._TREND, linewidth=2, zorder=4)
            ax.set_xlabel(scatter.x_label, fontsize=11)
            ax.set_ylabel(y_label, fontsize=11)
            fig.text(left, 0.06, regression_text(reg), color=plots._INK, fontsize=10.5)
            self._footer(fig, right)
            plots._save_png(fig, path)

    def bar(self, correlations: pd.DataFrame, title: str, path: Path) -> None:
        from matplotlib.patches import Patch

        from climpact import plots

        colours = {_TEMPERATURE: plots._DRY, _PRECIPITATION: plots._WET}
        with self.matplotlib.rc_context(plots._RC_PNG):
            fig = self._figure(12.0, 7.5)
            left, right = 0.07, 0.98
            fig.text(left, 0.945, title, color=plots._INK, fontsize=12.5, weight="bold")
            fig.text(
                left, 0.91, "Correlation of the sector data with each index",
                color=plots._INK_2, fontsize=10,
            )  # fmt: skip
            ax = fig.add_axes((left, 0.2, right - left, 0.66))
            self._style(ax)
            n = len(correlations)
            cor = correlations["cor"].to_numpy(dtype=float)
            heights = np.nan_to_num(cor)
            ax.bar(
                np.arange(n), heights, width=0.75,
                color=[colours[c] for c in correlations["category"]], zorder=2,
            )  # fmt: skip
            ax.axhline(0, color=plots._AXIS, linewidth=0.8, zorder=2)
            top = max(0.1, float(np.max(np.abs(heights))) if n else 0.1) * 1.15
            for i, (h, v) in enumerate(zip(heights, cor, strict=True)):
                # The value at the end of its bar (R writes it inside, halfway up).
                ax.text(
                    i, h + (0.01 if h >= 0 else -0.01) * top / 0.35, _number(v),
                    ha="center", va="bottom" if h >= 0 else "top", fontsize=6.5,
                    color=plots._INK_2, zorder=3,
                )  # fmt: skip
            ax.set_xticks(np.arange(n), correlations["indice"], rotation=90, fontsize=9)
            ax.set_xlim(-0.6, n - 0.4)
            ax.set_ylim(-top, top)
            ax.set_ylabel("Correlation", fontsize=11)
            ax.legend(
                handles=[Patch(color=colours[c], label=c) for c in colours],
                loc="upper right", frameon=False, fontsize=9, labelcolor=plots._INK_2,
            )  # fmt: skip
            self._footer(fig, right)
            plots._save_png(fig, path)


__all__ = [
    "MIN_COMMON_YEARS",
    "NO_COMMON_DATA",
    "SCATTERS",
    "SECTOR_INDICES",
    "Regression",
    "Scatter",
    "SectorCorrelation",
    "SectorCorrelationError",
    "SectorData",
    "annual_temperature",
    "corr_dir",
    "corr_zip",
    "default_y_label",
    "detrend",
    "file_part",
    "r_make_names",
    "read_index_tables",
    "read_sector_file",
    "run_sector_correlation",
    "sector_correlation",
    "sector_steps",
    "write_r_csv",
    "write_sector_correlation",
]
