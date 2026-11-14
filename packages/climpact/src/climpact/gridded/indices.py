"""Climpact's indices for every cell of a grid, written as its index netCDF files.

A port of ``climpact.ncdf.wrapper.r``, which calls ``create.indices.from.files`` in
Climpact's modified climdex.pcic.ncdf 0.5-4
(``server/pcic_packages/climdex.pcic.ncdf/R/ncdf.R``). R computes each cell with
``climdexInput.raw`` and the index functions the station app uses
(``climpact.etsci-functions.r`` and climdex.pcic), so the values come from the station
index code (:mod:`climpact.products.indices`), whose array functions take the cells of
a block together. What differs from a station run:

- the wrapper's parameters: ``wsdin_n = csdin_n = 5``, ``rxnday_n = 7``,
  ``ntxntn_n = ntxbntnb_n = 3`` (:data:`WRAPPER_PARAMS`);
- the hemisphere of each cell is its latitude ``>= 0`` (``get.northern.hemisphere.booleans``),
  where the station app uses ``> 0`` (gsl and the Tx90/Tn90 heatwaves depend on it);
- SPI and SPEI come from ``climdex.spi``/``climdex.spei`` and the SPEI package's
  ``spi()``/``spei()``, not the station app's ``cspei`` (:mod:`climpact.gridded.drought`),
  at 3, 6 and 12 months; SPEI uses the cell's latitude;
- a cell with every value of TX, TN and precipitation missing gets no index at all
  (``compute.indices.for.stripe``'s fast path);
- thresholds may come from a thresholds file (``climpact gridded-thresholds``), for data
  with no day in the base period only (R's ``check.quantile.validity`` stops otherwise);
  the out-of-base thresholds are then used for every year, the heatwave thresholds and
  the base-period data for SPI and SPEI too (:mod:`climpact.gridded.heatwaves`);
- R stores two kinds of missing value: its ``NA`` as the fill value, and ``NaN`` as
  NaN. :func:`block_indices` reproduces where R has ``NaN`` (see :class:`IndexResult`).

One file is written per index and frequency, named after a CMIP5-style template
(``create.climdex.cmip5.filenames``), with the layout of ``create.ncdf.output.files``:
one variable per file, except ``hw_ANN`` (10 variables), ``hwEHF_ANN`` (8) and
``spi_MON``/``spei_MON`` (a ``scale`` dimension).

Not copied from R: R stops on ``hw`` and ``hwEHF`` for a grid with an all-missing cell,
and on ``hwEHF`` for a cell with TAVG on less than half of the base period. Python writes
missing values for those cells.
"""

from __future__ import annotations

import csv
import os
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import cache
from importlib import resources
from pathlib import Path

import netCDF4
import numpy as np
import pandas as pd

from climpact.config import IndexParams
from climpact.gridded.drought import SCALES, spei_values, spi_values
from climpact.gridded.heatwaves import (
    EHF_FILE_THRESHOLDS,
    EHF_VARIABLES,
    HW_VARIABLES,
    hw_values,
    hwehf_values,
)
from climpact.gridded.io import GriddedInput
from climpact.gridded.thresholds import (
    FILL_VALUE,
    OUTPUT_CHUNK_CACHE,
    _days_since,
    _etccdi_attrs,
    _time_origin,
    check_base_period,
    filled_dates,
)
from climpact.periods import periods
from climpact.products.indices import (
    COUNTS,
    EXTREMES,
    TEMPERATURE_PERCENTILES,
    count_values,
    days_op_threshold_values,
    degree_day_values,
    extreme_values,
    gsl_values,
    means_and_totals_values,
    percent_days_values,
    precipitation_percentile_values,
    running_sums,
    rxnday_values,
    spell_duration_values,
    spell_length_max_values,
    valid_values,
)
from climpact.products.tables import FREQS, format_number
from climpact.progress import Progress
from climpact.thresholds import (
    DAYS_PER_YEAR,
    INBASE_QUANTILES,
    TEMPERATURE_QUANTILES,
    TEMPERATURE_WINDOW,
    base_period_array,
    bootstrap_quantiles,
    running_quantiles,
    take_dates,
    wet_day_quantiles,
)

# climpact.ncdf.wrapper.r's settings (the custom index parameters it passes).
WRAPPER_PARAMS = IndexParams(
    wsdi_days=5,
    csdi_days=5,
    rx_days=7,
    txtn_days=3,
    hdd_base=18.0,
    cdd_base=18.0,
    gdd_base=10.0,
    rnnmm=30.0,
    custom=None,
)
DEFAULT_TEMPLATE = "var_daily_climpactpy_historical_NA_{start}-{end}.nc"
# Indices computed by their own functions (gridded.heatwaves, gridded.drought), and only
# when asked for: they take most of a cell's time.
SEPARATE = ("hw", "hwEHF", "spi", "spei")
DEFAULT_CELLS_PER_BATCH = 8

# get.climdex.variable.list: the indices each variable makes available, in R's order.
_BY_VARIABLE = {
    "tmax": (
        "su", "id", "txx", "txn", "tx10p", "tx90p", "wsdi", "wsdid", "txge30", "txge35",
        "txm", "txgt50p", "tx95t",
    ),
    "tmin": (
        "fd", "tr", "tnx", "tnn", "tn10p", "tn90p", "csdi", "tnlt2", "tnltm2", "tnltm20",
        "csdid", "tnm",
    ),
    "prec": (
        "rx1day", "rx5day", "sdii", "r10mm", "r20mm", "cdd", "cwd", "r95p", "r99p",
        "prcptot", "rxdday", "rnnmm", "r95ptot", "r99ptot", "spei", "spi",
    ),
    "tavg": (
        "gsl", "dtr", "tmge5", "tmlt5", "tmge10", "tmlt10", "hddheatn", "cddcoldn",
        "gddgrown", "txbdtnbd", "txdtnd", "tmm", "hw", "hwEHF",
    ),
}  # fmt: skip
_ANNUAL_ONLY = {
    "txdtnd", "txbdtnbd", "gsl", "wsdi", "wsdid", "csdi", "csdid", "hw", "hwEHF",
    "hddheatn", "cddcoldn", "gddgrown", "sdii", "r95p", "r99p", "r95ptot", "r99ptot",
    "tx95t", "cwd", "cdd",
}  # fmt: skip
_MONTHLY_ONLY = {"spei", "spi"}
# exact_date_indices without cdd, cwd and gsl: written with a day_of_<index> variable.
_DATED = {"tnn", "tnx", "txn", "txx", "rxdday", "rx1day", "rx5day"}


@dataclass(frozen=True)
class IndexFile:
    """One output file (``get.climdex.variable.metadata`` and the renaming in
    ``create.indices.from.files``).

    ``index`` is the short name of ``climate.indices.csv`` (``rxdday``), ``name`` the
    variable and file name (``rx7day``), ``freq`` ``MON``, ``ANN`` or ``DAY``.
    """

    index: str
    name: str
    freq: str
    units: str
    long_name: str
    definition: str
    expert_team: str

    @property
    def key(self) -> str:
        return f"{self.name}_{self.freq}"

    @property
    def dated(self) -> bool:
        """Whether a ``day_of_<name>`` variable is written (the extremes)."""
        return self.index in _DATED

    @property
    def scaled(self) -> bool:
        """Whether the index has a ``scale`` dimension (SPI and SPEI: 3, 6, 12 months)."""
        return self.index in ("spi", "spei")

    @property
    def variables(self) -> tuple[tuple[str, str, str], ...]:
        """``(name, units, long_name)`` of each index variable, in the file's order: one,
        except for ``hw`` and ``hwEHF`` (whose variables get no ``definition``)."""
        if self.index == "hw":
            return HW_VARIABLES
        if self.index == "hwEHF":
            return tuple(
                (name, units, f"{text}, see user guide for definition.")
                for name, _, units, text in EHF_VARIABLES
            )
        return ((self.name, self.units, self.long_name),)

    def filename(self, template: str) -> str:
        """``create.climdex.cmip5.filenames``: ``<name>_<FREQ>_<model>_<emissions>_<run>_
        <start year>-<end year>.nc`` from the parts of ``template``
        (``get.split.filename.cmip5``). R gives monthly files years only too, because
        it looks for ``_mon`` in lower case."""
        parts = Path(template).name.split("_")
        if len(parts) < 6:
            raise ValueError(
                f"template {template!r} is not a CMIP5 file name "
                "(var_freq_model_emissions_run_start-end.nc)"
            )
        model, emissions, run = parts[2:5]
        start, end = parts[-1].split(".")[0].split("-")[:2]
        return f"{self.key}_{model}_{emissions}_{run}_{start[:4]}-{end[:4]}.nc"


@cache
def _definitions() -> dict[tuple[str, str], dict[str, str]]:
    text = resources.files("climpact.data").joinpath("climate.indices.csv").read_text()
    out = {}
    for row in csv.DictReader(text.splitlines(), delimiter="\t"):
        freq = {"T": "ANN", "F": "MON"}.get(row["Annual.flag"], "DAY")
        out[row["Short.name"], freq] = row
    return out


def _renamed(index: str, freq: str, params: IndexParams) -> tuple[str, str | None]:
    """The output name and definition of an index with a user parameter, as
    ``create.indices.from.files`` sets them (None: the definition is unchanged)."""
    period = "monthly" if freq == "MON" else "annual"
    p = params
    n = format_number
    if index == "rxdday":
        return f"rx{p.rx_days}day", f"Maximum {period} {p.rx_days}-day precipitation total"
    if index == "rnnmm":
        mm = n(p.rnnmm)
        return f"r{mm}mm", f"{period} number of days when precipitation >= {mm} mm"
    if index == "txdtnd":
        d = p.txtn_days
        return f"tx{d}tn{d}", (
            f"{period} number of {d} consecutive days where both TX > 95th percentile "
            "and TN > 95th percentile"
        )
    if index == "txbdtnbd":
        d = p.txtn_days
        return f"txb{d}tnb{d}", (
            f"{period} number of {d} consecutive days where both TX < 5th percentile "
            "and TN < 5th percentile"
        )
    if index in ("wsdid", "csdid"):
        d = p.wsdi_days if index == "wsdid" else p.csdi_days
        op, q, var = (">", 90, "TX") if index == "wsdid" else ("<", 10, "TN")
        return f"{index[:4]}{d}", (
            f"Annual number of days contributing to events where {d} or more consecutive "
            f"days experience {var} {op} {q}th percentile"
        )
    if index in ("hddheatn", "cddcoldn", "gddgrown"):
        base = {"hddheatn": p.hdd_base, "cddcoldn": p.cdd_base, "gddgrown": p.gdd_base}[index]
        b = n(base)
        if index == "hddheatn":
            text = f"Annual sum of {b} - TM (where {b} is a user-defined location-specific base temperature and TM < {b})"  # noqa: E501
        else:
            text = f"Annual sum of TM - {b} (where {b} is a user-defined location-specific base temperature and TM > {b})"  # noqa: E501
        return f"{index[:-1]}{b}", text
    return index, None


def index_files(params: IndexParams = WRAPPER_PARAMS) -> list[IndexFile]:
    """The files ``create.indices.from.files`` writes with TX, TN and precipitation, in
    R's order (``get.climdex.variable.list``)."""
    out: list[IndexFile] = []
    seen = set()
    for index in (i for names in _BY_VARIABLE.values() for i in names):
        if index == "tx95t":
            freqs = ["DAY"]
        elif index in _ANNUAL_ONLY:
            freqs = ["ANN"]
        elif index in _MONTHLY_ONLY:
            freqs = ["MON"]
        else:
            freqs = ["MON", "ANN"]
        for freq in freqs:
            row = _definitions()[index, freq]
            name, definition = _renamed(index, freq, params)
            if (name, freq) in seen:  # rxdday with 5 days is rx5day: R writes it twice
                continue
            seen.add((name, freq))
            out.append(
                IndexFile(
                    index=index,
                    name=name,
                    freq=freq,
                    units=row["Units"],
                    long_name=row["Long.name"],
                    definition=row["Definition"] if definition is None else definition,
                    expert_team=row["Expert.team"],
                )
            )
    return out


# --- computing -----------------------------------------------------------------------------


@dataclass
class IndexResult:
    """The values of one output for a block of cells, ``(cells, periods)``, or
    ``(cells, k, periods)`` for the ``k`` variables of ``hw`` and ``hwEHF`` and the three
    scales of SPI and SPEI.

    ``values`` is NaN where R has a missing value; ``nan`` marks where R's missing value
    is ``NaN`` rather than ``NA`` (written as NaN instead of the fill value): a year
    with no data at all in tmm, txm and tnm (R's ``NaN`` mean times the ``NA`` mask is
    ``NaN``), and rNNptot when the year has no wet day (``0 / 0``). ``day`` is the day
    of the month (MON) or year (ANN) of the extreme, for the dated indices.
    """

    values: np.ndarray
    nan: np.ndarray | None = None
    day: np.ndarray | None = None


def _day_numbers(time: pd.DatetimeIndex, position: np.ndarray, freq: str) -> np.ndarray:
    day = (time.day if freq == "MON" else time.day_of_year).to_numpy().astype(float)
    return np.where(position >= 0, day[np.maximum(position, 0)], np.nan)


@dataclass(frozen=True)
class GridThresholds:
    """Thresholds for a block of cells: ``outbase[var][q]`` ``(cells, 365)``,
    ``precipitation[q]`` ``(cells,)`` and ``inbase[var][q]`` ``(cells, 365, years,
    years - 1)`` (empty when the in-base thresholds are not used)."""

    outbase: dict[str, dict[float, np.ndarray]]
    precipitation: dict[float, np.ndarray]
    inbase: dict[str, dict[float, np.ndarray]]


def compute_block_thresholds(
    tx: np.ndarray,
    tn: np.ndarray,
    pr: np.ndarray,
    full: pd.DatetimeIndex,
    base_start: int,
    base_end: int,
) -> GridThresholds:
    """The thresholds ``climdexInput.raw`` computes for each cell (as for a station:
    :func:`climpact.thresholds.compute_thresholds`), for ``(cells, time)`` arrays on
    the whole-year axis ``full``."""
    from climpact.products.indices import _bootstraps

    outbase, inbase = {}, {}
    bootstrap = _bootstraps(full, base_start, base_end)
    for var, x in (("tasmax", tx), ("tasmin", tn)):
        base = base_period_array(x, full, base_start, base_end)
        outbase[var] = running_quantiles(base, TEMPERATURE_WINDOW, TEMPERATURE_QUANTILES)
        inbase[var] = (
            bootstrap_quantiles(base, TEMPERATURE_WINDOW, INBASE_QUANTILES[var])
            if bootstrap
            else {}
        )
    precipitation = wet_day_quantiles(pr, full, base_start, base_end, (0.95, 0.99))
    return GridThresholds(outbase, precipitation, inbase)


def thresholds_from_file(values: Mapping[str, np.ndarray]) -> GridThresholds:
    """:class:`GridThresholds` from the variables of a thresholds file for a block
    (``tx05thresh`` ... as ``(cells, 365)``, ``r95thresh``, ``r99thresh`` as ``(cells,)``);
    ``get.quantiles.object``. No in-base thresholds."""
    outbase = {
        var: {q: values[f"{prefix}{round(q * 100):02d}thresh"] for q in TEMPERATURE_QUANTILES}
        for var, prefix in (("tasmax", "tx"), ("tasmin", "tn"))
    }
    precipitation = {0.95: values["r95thresh"], 0.99: values["r99thresh"]}
    return GridThresholds(outbase, precipitation, {})


THRESHOLD_FILE_VARIABLES = (
    *(f"{p}{q:02d}thresh" for p in ("tx", "tn") for q in (5, 10, 50, 90, 95)),
    "r95thresh",
    "r99thresh",
    "tx90thresh_15days",
    "tn90thresh_15days",
    *EHF_FILE_THRESHOLDS,
    "txraw",
    "tnraw",
    "precraw",
)


def cell_indices(
    tasmax: np.ndarray,
    tasmin: np.ndarray,
    pr: np.ndarray,
    time: pd.DatetimeIndex,
    latitude: np.ndarray,
    base_start: int,
    base_end: int,
    params: IndexParams = WRAPPER_PARAMS,
    thresholds: Mapping[str, np.ndarray] | None = None,
    separate: Sequence[str] = SEPARATE,
) -> dict[str, IndexResult]:
    """Every output of :func:`index_files` for a batch of cells, of :data:`SEPARATE`
    only those in ``separate``.

    ``tasmax``, ``tasmin`` (degrees C) and ``pr`` (kg m-2 d-1) are ``(cells, time)``
    arrays on the input's time axis ``time``; ``latitude`` is ``(cells,)``.
    ``thresholds`` holds the :data:`THRESHOLD_FILE_VARIABLES` of the cells from a
    thresholds file, ``(cells, 365)``, ``(cells,)`` or ``(cells, base days)``, or None
    to compute them. Returns ``{"<name>_<FREQ>": IndexResult}``.
    """
    full = filled_dates(time)
    tx = take_dates(tasmax, time, full)
    tn = take_dates(tasmin, time, full)
    prec = take_dates(pr, time, full)
    tas = (tx + tn) / 2
    if thresholds is None:
        th = compute_block_thresholds(tx, tn, prec, full, base_start, base_end)
    else:
        th = thresholds_from_file(thresholds)

    out: dict[str, IndexResult] = {}
    counts = dict(COUNTS)
    counts[f"r{format_number(params.rnnmm)}mm"] = ("pr", float(params.rnnmm), ">=")
    data = {"tasmax": tx, "tasmin": tn, "tas": tas, "pr": prec}
    shares = {
        name: days_op_threshold_values(
            data[var],
            full,
            th.outbase[var][q],
            th.inbase[var].get(q) if th.inbase else None,
            base_start,
            base_end,
            condition,
        )
        for name, (var, q, condition) in TEMPERATURE_PERCENTILES.items()
    }
    runsums = {n: running_sums(prec, n) for n in sorted({5, params.rx_days})}
    for freq, rule in FREQS.items():
        for name, (var, threshold, condition) in counts.items():
            out[f"{name}_{freq}"] = IndexResult(
                count_values(data[var], threshold, condition, full, rule)
            )

        means = means_and_totals_values(tx, tn, tas, prec, full, freq, float32=True)
        p = periods(full, rule)
        for name, values in means.items():
            nan = None
            if freq == "ANN" and name in ("tmm", "txm", "tnm"):
                series = {"tmm": tas, "txm": tx, "tnm": tn}[name]
                nan = p.count(~np.isnan(series)) == 0
            out[f"{name}_{freq}"] = IndexResult(values, nan)

        for name, (var, stat) in EXTREMES.items():
            values, position = extreme_values(data[var], full, rule, stat)
            out[f"{name}_{freq}"] = IndexResult(values, day=_day_numbers(full, position, freq))
        for ndays, runsum in runsums.items():
            values, position = rxnday_values(prec, full, ndays, rule, runsum)
            out[f"rx{ndays}day_{freq}"] = IndexResult(
                values, day=_day_numbers(full, position, freq)
            )

        for name, (var, _, _) in TEMPERATURE_PERCENTILES.items():
            valid = valid_values(full, rule, data[var])
            values = percent_days_values(shares[name], full, freq, valid, float32=True)
            out[f"{name}_{freq}"] = IndexResult(values)

    for name, values in degree_day_values(tas, full, params).items():
        out[f"{name}_ANN"] = IndexResult(values)
    out["cdd_ANN"] = IndexResult(spell_length_max_values(prec, full, "<"))
    out["cwd_ANN"] = IndexResult(spell_length_max_values(prec, full, ">="))

    rain = precipitation_percentile_values(prec, full, th.precipitation)
    prcptot = out["prcptot_ANN"].values
    for name, values in rain.items():
        nan = (prcptot == 0) if name.endswith("tot") else None
        out[f"{name}_ANN"] = IndexResult(values, nan)

    spell_thresholds = {
        (v, q): th.outbase[v][q] for v in ("tasmax", "tasmin") for q in (0.05, 0.1, 0.9, 0.95)
    }
    for name, values in spell_duration_values(tx, tn, full, spell_thresholds, params).items():
        out[f"{name}_ANN"] = IndexResult(values)

    northern = np.asarray(latitude) >= 0
    out["gsl_ANN"] = IndexResult(gsl_values(tas, full, northern))
    out["tx95t_DAY"] = IndexResult(th.outbase["tasmax"][0.95])
    out.update(
        _separate_indices(tx, tn, prec, full, latitude, base_start, base_end, thresholds, separate)
    )

    # compute.indices.for.stripe: a cell with no data at all has no index.
    empty = (
        np.isnan(tasmax).all(axis=-1) & np.isnan(tasmin).all(axis=-1) & np.isnan(pr).all(axis=-1)
    )
    if empty.any():
        for result in out.values():
            result.values[empty] = np.nan
            if result.nan is not None:
                result.nan[empty] = False
            if result.day is not None:
                result.day[empty] = np.nan
    for result in out.values():
        if result.day is not None:
            result.day = np.where(np.isnan(result.values), np.nan, result.day)
    return out


def _separate_indices(
    tx: np.ndarray,
    tn: np.ndarray,
    prec: np.ndarray,
    full: pd.DatetimeIndex,
    latitude: np.ndarray,
    base_start: int,
    base_end: int,
    thresholds: Mapping[str, np.ndarray] | None,
    separate: Sequence[str],
) -> dict[str, IndexResult]:
    """hw, hwEHF, SPI and SPEI (those in ``separate``) for a batch of cells, as
    ``(cells, variables or scales, periods)``. With a thresholds file, the heatwaves use
    its thresholds and SPI and SPEI its base-period data (``computefuture``)."""
    out = {}
    thr = thresholds
    latitude = np.asarray(latitude, dtype=float)
    if "hw" in separate:
        hw_thr = (
            None
            if thr is None
            else {"tasmax": thr["tx90thresh_15days"], "tasmin": thr["tn90thresh_15days"]}
        )
        out["hw_ANN"] = IndexResult(
            hw_values(tx, tn, full, latitude >= 0, base_start, base_end, hw_thr)
        )
    if "hwEHF" in separate:
        ehf_thr = None if thr is None else {k: thr[k] for k in EHF_FILE_THRESHOLDS}
        out["hwEHF_ANN"] = IndexResult(hwehf_values(tx, tn, full, base_start, base_end, ehf_thr))
    if "spi" in separate:
        raw = None if thr is None else thr["precraw"]
        out["spi_MON"] = IndexResult(spi_values(prec, full, base_start, base_end, raw))
    if "spei" in separate:
        raw = (
            None
            if thr is None
            else {"tasmax": thr["txraw"], "tasmin": thr["tnraw"], "pr": thr["precraw"]}
        )
        out["spei_MON"] = IndexResult(
            spei_values(tx, tn, prec, full, latitude, base_start, base_end, raw)
        )
    return out


def block_indices(
    data: Mapping[str, np.ndarray],
    time: pd.DatetimeIndex,
    latitude: np.ndarray,
    base_start: int,
    base_end: int,
    params: IndexParams = WRAPPER_PARAMS,
    thresholds: Mapping[str, np.ndarray] | None = None,
    pool: ThreadPoolExecutor | None = None,
    cells_per_batch: int = DEFAULT_CELLS_PER_BATCH,
    separate: Sequence[str] = SEPARATE,
) -> dict[str, IndexResult]:
    """:func:`cell_indices` of a block, ``data[var]`` ``(y, x, time)``, latitude and
    thresholds ``(y, x, ...)``; computed in batches of ``cells_per_batch`` cells (on
    ``pool`` if given). Returns results of shape ``(y, x, periods)``."""
    ny, nx, nt = data["tasmax"].shape
    flat = {v: data[v].reshape(ny * nx, nt) for v in ("tasmax", "tasmin", "pr")}
    lat = np.asarray(latitude).reshape(ny * nx)
    thr = (
        None
        if thresholds is None
        else {k: v.reshape(ny * nx, *v.shape[2:]) for k, v in thresholds.items()}
    )
    step = max(cells_per_batch, 1)

    def batch(start: int) -> dict[str, IndexResult]:
        part = slice(start, start + step)
        return cell_indices(
            flat["tasmax"][part],
            flat["tasmin"][part],
            flat["pr"][part],
            time,
            lat[part],
            base_start,
            base_end,
            params,
            None if thr is None else {k: v[part] for k, v in thr.items()},
            separate,
        )

    starts = range(0, ny * nx, step)
    parts = list(pool.map(batch, starts) if pool else map(batch, starts))

    def join(arrays):
        if arrays[0] is None:
            return None
        return np.concatenate(arrays).reshape(ny, nx, *arrays[0].shape[1:])

    return {
        key: IndexResult(
            join([p[key].values for p in parts]),
            join([p[key].nan for p in parts]),
            join([p[key].day for p in parts]),
        )
        for key in parts[0]
    }


# --- writing -------------------------------------------------------------------------------


def _period_bounds(time: pd.DatetimeIndex, freq: str, origin: str) -> tuple[np.ndarray, np.ndarray]:
    """``get.output.time.data``: bounds ``[first day, last day]`` of every month or year
    from January of the first year to December of the last (``nc.make.time.bounds``),
    and their midpoints, in days since ``origin``."""
    start, end = time[0].year, time[-1].year
    rule = FREQS[freq]
    starts = pd.date_range(f"{start}-01-01", f"{end + 1}-01-01", freq=rule)
    first = _days_since(starts[:-1], origin)
    last = _days_since(starts[1:] - pd.Timedelta(days=1), origin)
    bounds = np.stack([first, last], axis=1)
    return bounds, (first + last) / 2


def _input_layout(inp: GriddedInput, exemplar: Path) -> dict:
    """Names and attributes R takes from the exemplar file (the precipitation file)."""
    with netCDF4.Dataset(exemplar) as src:
        src_time = src.variables[inp.time_dim]
        units = src_time.getncattr("units")
        bounds_name = (
            src_time.getncattr("bounds")
            if "bounds" in src_time.ncattrs()
            else f"{inp.time_dim}_bnds"
        )
        bnds_dim = "bnds"
        if bounds_name in src.variables:
            bnds_dim = src.variables[bounds_name].dimensions[-1]
        var = src.variables[inp.names["pr"]]
        return {
            "origin": _time_origin(units),
            "bounds_name": bounds_name,
            "bnds_dim": bnds_dim,
            "time_attrs": {
                k: src_time.getncattr(k) for k in src_time.ncattrs() if k != "_FillValue"
            },
            "coords": {
                dim: (
                    np.asarray(src.variables[dim][:], dtype=float),
                    {
                        k: src.variables[dim].getncattr(k)
                        for k in src.variables[dim].ncattrs()
                        if k not in ("_FillValue", "bounds")
                    },
                )
                for dim in (inp.x_dim, inp.y_dim)
            },
            "var_attrs": {k: var.getncattr(k) for k in var.ncattrs() if k not in _NOT_COPIED},
            "global_attrs": _renamed_globals(src),
        }


# create.ncdf.output.files: attributes of the exemplar variable not copied to an index.
_NOT_COPIED = {
    "units", "long_name", "standard_name", "base_period", "missing_value", "_FillValue",
    "add_", "valid_min", "valid_max", "valid_range", "scale_factor", "add_offset",
    "signedness", "history",
}  # fmt: skip


def _renamed_globals(src: netCDF4.Dataset) -> dict:
    """The exemplar's global attributes, renamed as ``create.ncdf.output.files`` does."""
    rename = {
        "frequency": "input_frequency",
        "creation_date": "input_creation_date",
        "title": "input_title",
        "tracking_id": "input_tracking_id",
    }
    if "institution_id" in src.ncattrs():
        inst = src.getncattr("institution_id")
        rename[f"{inst}_contact"] = "contact"
        rename[f"{inst}_references"] = "references"
    return {rename.get(k, k): src.getncattr(k) for k in src.ncattrs()}


def create_index_file(
    path: Path,
    spec: IndexFile,
    inp: GriddedInput,
    layout: dict,
    base_start: int,
    base_end: int,
    author: Mapping[str, str],
) -> netCDF4.Dataset:
    """Create one index file with everything but the index values
    (``create.ncdf.output.files``), and return it open for writing."""
    ny, nx = inp.shape
    by = max(inp.data.chunks[inp.y_dim])
    bx = max(inp.data.chunks[inp.x_dim])
    origin = layout["origin"]
    nc = netCDF4.Dataset(path, "w", format="NETCDF4")
    try:
        if spec.freq == "DAY":
            nc.createDimension(inp.x_dim, nx)
            nc.createDimension(inp.y_dim, ny)
            nc.createDimension(inp.time_dim, DAYS_PER_YEAR)
            _coordinates(nc, inp, layout)
            t = nc.createVariable(inp.time_dim, "i4", (inp.time_dim,))
            t.setncatts({"long_name": inp.time_dim, "units": "calendar day", "calendar": "365_day"})
            t.setncatts(layout["time_attrs"])
            t.setncattr("units", f"days since {origin}")
            t[:] = np.arange(1, DAYS_PER_YEAR + 1)
            dims = (inp.time_dim, inp.y_dim, inp.x_dim)
            chunks = (DAYS_PER_YEAR, by, bx)
        else:
            bounds, mid = _period_bounds(inp.time, spec.freq, origin)
            nc.createDimension(layout["bnds_dim"], 2)
            nc.createDimension(inp.time_dim, None)
            nc.createDimension(inp.x_dim, nx)
            nc.createDimension(inp.y_dim, ny)
            t = nc.createVariable(inp.time_dim, "f8", (inp.time_dim,))
            t.setncattr("units", f"days since {origin}")
            t.setncatts(layout["time_attrs"])
            t.setncattr("units", f"days since {origin}")
            t[:] = mid
            tb = nc.createVariable(layout["bounds_name"], "f8", (inp.time_dim, layout["bnds_dim"]))
            tb[:] = bounds
            _coordinates(nc, inp, layout)
            dims = (inp.time_dim, inp.y_dim, inp.x_dim)
            chunks = (len(mid), by, bx)
            if spec.scaled:
                # ncdim_def("scale", "3,6,12 months", 1:3): an int coordinate variable
                nc.createDimension("scale", len(SCALES))
                scale = nc.createVariable("scale", "i4", ("scale",))
                scale.setncatts({"units": "3,6,12 months", "long_name": "scale"})
                scale[:] = np.arange(1, len(SCALES) + 1)
                dims = ("scale", *dims)
                chunks = (len(SCALES), *chunks)
        variables = [(name, units, long_name, False) for name, units, long_name in spec.variables]
        if spec.dated:
            variables.append((f"day_of_{spec.name}", "calendar day", spec.long_name, True))
        for name, units, long_name, is_day in variables:
            v = nc.createVariable(
                name, "f4", dims, fill_value=np.float32(FILL_VALUE), zlib=True, complevel=4,
                chunksizes=chunks,
            )  # fmt: skip
            v.set_var_chunk_cache(size=OUTPUT_CHUNK_CACHE, nelems=101, preemption=1.0)
            v.setncatts({"units": units, "long_name": long_name})
            if is_day:
                continue
            if spec.index in ("hw", "hwEHF"):
                # R copies no attribute of the input to these and sets no definition.
                v.setncattr("expert_team", spec.expert_team)
            else:
                v.setncatts(layout["var_attrs"])
                v.setncatts({"definition": spec.definition, "expert_team": spec.expert_team})
        nc.setncatts(layout["global_attrs"])
        frequency = {"MON": "mon", "ANN": "yr", "DAY": "NA"}[spec.freq]
        nc.setncatts(_etccdi_attrs(base_start, base_end, author, frequency))
    except BaseException:
        nc.close()
        raise
    return nc


def _coordinates(nc: netCDF4.Dataset, inp: GriddedInput, layout: dict) -> None:
    for dim in (inp.x_dim, inp.y_dim):
        values, attrs = layout["coords"][dim]
        coord = nc.createVariable(dim, "f8", (dim,))
        coord.setncatts(attrs)
        coord[:] = values


def _write_block(nc: netCDF4.Dataset, spec: IndexFile, block, result: IndexResult) -> None:
    ys, xs = block
    if spec.scaled:  # (y, x, scale, t) -> (scale, t, y, x)
        values = np.moveaxis(result.values, (0, 1), (2, 3))
        nc.variables[spec.name][:, :, ys, xs] = np.ma.masked_invalid(values)
        return
    if len(spec.variables) > 1:  # (y, x, variable, t)
        for i, (name, _, _) in enumerate(spec.variables):
            values = np.moveaxis(result.values[:, :, i], -1, 0)
            # NaN is R's NA; an infinite value (EHF-HWPS with no EHF85) is kept as R's.
            nc.variables[name][:, ys, xs] = np.ma.masked_where(np.isnan(values), values)
        return
    values = np.moveaxis(result.values, -1, 0)  # (y, x, t) -> (t, y, x)
    masked = np.isnan(values)
    if result.nan is not None:
        masked &= ~np.moveaxis(result.nan, -1, 0)  # R's NaN is stored as NaN
    nc.variables[spec.name][:, ys, xs] = np.ma.array(values, mask=masked)
    if spec.dated:
        day = np.moveaxis(result.day, -1, 0)
        nc.variables[f"day_of_{spec.name}"][:, ys, xs] = np.ma.masked_invalid(day)


def _read_thresholds(nc: netCDF4.Dataset, block, inp: GriddedInput) -> dict[str, np.ndarray]:
    """The thresholds of a block from a thresholds file, ``(y, x, 365)``, ``(y, x)`` or
    ``(y, x, base days)``."""
    ys, xs = block
    out = {}
    for name in THRESHOLD_FILE_VARIABLES:
        var = nc.variables[name]
        var.set_auto_mask(True)
        values = np.ma.filled(var[..., ys, xs].astype(float), np.nan)
        out[name] = np.moveaxis(values, 0, -1) if values.ndim == 3 else values
    return out


def check_thresholds_file(path: Path, inp: GriddedInput, base_start: int, base_end: int) -> None:
    """R's requirements for a thresholds file: the grid of the input, and no input day
    in the base period (``check.quantile.validity`` wants in-base thresholds then,
    which a thresholds file does not hold)."""
    full = filled_dates(inp.time)
    if ((full.year >= base_start) & (full.year <= base_end)).any():
        raise ValueError(
            f"a thresholds file can only be used for data outside the base period "
            f"{base_start}-{base_end} (R stops: in-base thresholds are needed)"
        )
    with netCDF4.Dataset(path) as nc:
        missing = [v for v in THRESHOLD_FILE_VARIABLES if v not in nc.variables]
        if missing:
            raise ValueError(f"{path}: missing thresholds {missing}")
        shape = nc.variables["r95thresh"].shape
        if tuple(shape) != inp.shape:
            raise ValueError(f"{path}: grid {tuple(shape)} differs from the input's {inp.shape}")


def write_grid_indices(
    inp: GriddedInput,
    out_dir: str | Path,
    base_start: int = 1971,
    base_end: int = 2000,
    template: str | None = None,
    params: IndexParams = WRAPPER_PARAMS,
    thresholds_file: str | Path | None = None,
    author: Mapping[str, str] | None = None,
    workers: int = 1,
    progress: Progress | None = None,
    cells_per_batch: int = DEFAULT_CELLS_PER_BATCH,
    indices: Sequence[str] | None = None,
) -> list[Path]:
    """Compute the indices of every cell of ``inp`` and write one netCDF file per index
    and frequency to ``out_dir`` (``create.indices.from.files``). Returns the paths.

    ``template`` is the CMIP5-style file name the output names follow (default
    ``var_daily_climpactpy_historical_NA_<first year>-<last year>.nc``). With
    ``thresholds_file`` (written by ``climpact gridded-thresholds``), its thresholds are
    used instead of computing them; the data must then have no day in the base period.
    ``indices`` limits the output to those indices, by short name as in
    ``climate.indices.csv`` (R's ``climdex.vars.subset``, e.g. ``rxdday``, ``wsdid``).
    Blocks are read, computed (by ``workers`` threads, ``cells_per_batch`` cells at a
    time) and written one at a time; ``progress("indices", done, total)`` is called after
    each block (see :mod:`climpact.progress`); the files are written under temporary names and
    renamed when all are complete.
    """
    time = inp.time
    if thresholds_file is None:
        check_base_period(time, base_start, base_end)
    else:
        thresholds_file = Path(thresholds_file)
        check_thresholds_file(thresholds_file, inp, base_start, base_end)
    template = template or DEFAULT_TEMPLATE.format(start=time[0].year, end=time[-1].year)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    specs = index_files(params)
    if indices is not None:
        specs = [s for s in specs if s.index in set(indices)]
    separate = [s.index for s in specs if s.index in SEPARATE]
    layout = _input_layout(inp, inp.files["pr"])
    paths = {s.key: out_dir / s.filename(template) for s in specs}
    tmp = {k: p.with_name(f".{p.name}.{os.getpid()}.tmp") for k, p in paths.items()}
    latitude = inp.cell_latitude().values
    files: dict[str, netCDF4.Dataset] = {}
    thr_nc = None
    try:
        for s in specs:
            files[s.key] = create_index_file(
                tmp[s.key], s, inp, layout, base_start, base_end, author or {}
            )
        thr_nc = netCDF4.Dataset(thresholds_file) if thresholds_file else None
        blocks = list(inp.blocks())
        with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
            for done, block in enumerate(blocks, start=1):
                data = inp.load(block)  # netCDF reads and writes stay in this thread
                thr = _read_thresholds(thr_nc, block, inp) if thr_nc else None
                results = block_indices(
                    data,
                    time,
                    latitude[block],
                    base_start,
                    base_end,
                    params,
                    thr,
                    pool if workers > 1 else None,
                    cells_per_batch,
                    separate,
                )
                del data
                for s in specs:
                    _write_block(files[s.key], s, block, results[s.key])
                del results
                if progress:
                    progress("indices", done, len(blocks))
        for nc in files.values():
            nc.close()
    except BaseException:
        for nc in files.values():
            if nc.isopen():
                nc.close()
        for p in tmp.values():
            p.unlink(missing_ok=True)
        raise
    finally:
        if thr_nc is not None:
            thr_nc.close()
    for key, p in paths.items():
        tmp[key].replace(p)
    return list(paths.values())


__all__ = [
    "SEPARATE",
    "WRAPPER_PARAMS",
    "IndexFile",
    "IndexResult",
    "block_indices",
    "cell_indices",
    "index_files",
    "write_grid_indices",
]
