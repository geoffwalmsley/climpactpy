"""The trend file, ``trend/trend``: Sen's slope and its 95% bounds for every plotted series.

R writes the trend file as a side effect of plotting (``index.calc`` in
``services/calculate_indices.R``, ``plot.call`` in ``services/plot_indices.R``,
``plot.precindex`` in ``services/plot_prec_index.R`` and ``calculate.custom.index``).
The rows follow ``climate.indices.csv``, and R passes the trend between those functions
in global variables (``mktrend``, ``DJFtrend`` ... ``SONtrend``), which decides which
rows are written. This module replays that sequence:

- **Index rows.** For each index file ``index.calc`` writes, ``plot.call`` sets
  ``mktrend`` unless the plotted series (the value column; ``val``, ``duration`` or ``sl``
  for the indices with dates) is missing throughout, and ``index.calc`` writes a row
  ``<name>,<annual|monthly|NA>,<first year>,<last year>,<lower>,<slope>,<upper>`` when
  ``mktrend`` exists, then removes it. So there is a row exactly when the series has a
  value, and its bounds are ``NA`` when ``min_trend_data`` fails (fewer than 10 values or
  less than 70% of the series). ``tx95t`` has frequency ``NA``.
- **Seasonal rows.** After the row of a monthly index (not ``tx95t``) come DJF, MAM, JJA
  and SON rows: seasonal values from the monthly ones (:func:`seasonal_series`), with
  their own ``min_trend_data`` check.
- **Heatwaves.** ``plot.hw`` writes nothing (its trend line is commented out) and
  removes ``mktrend``. ``calculate.hwEHF`` calls ``plot.call`` for the eight EHF aspects
  and writes nothing, but does not remove ``mktrend``: the last aspect with a value
  leaves its trend behind, and the next row written from ``mktrend`` uses it (only
  reachable when neither SPI nor SPEI plots a scale and ``tmm`` is missing in every year).
- **SPI and SPEI** (``plot.precindex``): no row for the whole series. For the 3-month
  scale, the February, May, August and November values (labelled ``FEB``, ``MAY``,
  ``AUG``, ``NOV``); for 6 months, August and October labelled ``APR`` and ``OCT``; for
  12 months, January and December labelled ``JUN`` and ``DEC``. The custom scale writes
  rows only when it is 3, 6 or 12, which repeats those rows. SPEI comes before SPI.
- **Custom index** (``calculate.custom.index``): annual and monthly rows, as an index.

Numbers are written with ``paste``, which formats them as ``as.character`` does (15
significant digits, :func:`climpact.io.climpact_csv.format_r_number`); missing ones as
``NA``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

import numpy as np
import pandas as pd

from climpact.io.output_files import index_files
from climpact.outputs import derived
from climpact.rnumerics import r_mean, r_sum
from climpact.station import StationRun
from climpact.trends import NA_TREND, sen_trend

COLUMNS = ("Index", "Frequency", "StartYear", "EndYear", "Lower bound", "Slope", "Upper bound")
SEASONS = ("DJF", "MAM", "JJA", "SON")
MIN_MONTHS = 3  # months a season needs to have a value

# plot.call picks the seasonal function by the *output* name, so rx3day (rxnday's output)
# and r30mm (rnnmm's) are averaged, not maximised or summed.
_SEASON_MAX = {"txx", "tnx", "rx1day", "rx5day", "rxnday", "cwd", "cdd"}
_SEASON_MIN = {"tnn", "txn"}
_SEASON_SUM = {"su", "tr", "txge30", "txge35", "r10mm", "r20mm", "rnnmm", "prcptot"}

# calculate.hwEHF's plot.call order.
_HW = ("HWM", "HWA", "HWN", "HWD", "HWF")
_EHF_ORDER = ("HWD", "HWMD", "HWPS", "HWPI", "HWLS", "HWLI", "HWN", "HWF")

# plot.precindex: scale -> (calendar month, label) pairs, in the order written.
_PRECINDEX_ROWS = {
    3: ((2, "FEB"), (5, "MAY"), (8, "AUG"), (11, "NOV")),
    6: ((8, "APR"), (10, "OCT")),
    12: ((1, "JUN"), (12, "DEC")),
}

Trend = tuple[float, float, float]


def season_function(name: str) -> Callable[[np.ndarray], float]:
    """The function ``plot.call`` applies to a season's three monthly values."""
    if name in _SEASON_MAX:
        return lambda x: float(np.max(x))
    if name in _SEASON_MIN:
        return lambda x: float(np.min(x))
    if name in _SEASON_SUM:
        return r_sum
    return r_mean


def seasonal_series(
    values: np.ndarray, months: np.ndarray, years: np.ndarray, func: Callable
) -> dict[str, np.ndarray]:
    """DJF, MAM, JJA and SON series from monthly values, as ``plot.call`` builds them.

    R shifts each month forward by one (``as.yearqtr(yearmon + 1/12)``), drops the last
    month, and groups by quarter, so DJF of year Y is December of Y - 1 with January and
    February of Y. A season with fewer than three values is missing; otherwise ``func``
    of its values (in calendar order). The first DJF has only January and February, so
    it is always missing; the last December is in no season.
    """
    months = months.astype(int)
    q_year = np.where(months == 12, years.astype(int) + 1, years.astype(int))  # Dec -> Y + 1
    quarter = (months % 12) // 3  # Dec, Jan, Feb -> 0 (Q1) ... Sep, Oct, Nov -> 3 (Q4)
    values, q_year, quarter = values[:-1], q_year[:-1], quarter[:-1]
    out = {}
    for q, season in enumerate(SEASONS):
        series = []
        for year in np.unique(q_year[quarter == q]):
            group = values[(quarter == q) & (q_year == year)]
            ok = ~np.isnan(group)
            series.append(func(group) if ok.sum() >= MIN_MONTHS else np.nan)
        out[season] = np.array(series, dtype=float)
    return out


def _value_column(table: pd.DataFrame) -> np.ndarray:
    # The plotted column: val, duration or sl for the indices with dates
    # (exact_date_indices), otherwise the index itself (the second column).
    column = next((c for c in ("val", "duration", "sl") if c in table), table.columns[1])
    return table[column].to_numpy(dtype=float)


def _months_years(table: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    time = table["time"].astype(str)
    return time.str[5:7].astype(int).to_numpy(), time.str[:4].astype(int).to_numpy()


class _TrendWriter:
    """R's trend globals and the rows written so far."""

    def __init__(self, start: int, end: int) -> None:
        self.start, self.end = start, end
        self.rows: list[tuple] = []
        self.mktrend: Trend | None = None
        self.seasons: dict[str, Trend] = {}

    def row(self, name: str, frequency: str, trend: Trend) -> None:
        self.rows.append((name, frequency, self.start, self.end, *trend))

    def plot_call(self, name: str, table: pd.DataFrame | None) -> None:
        """``plot.call``: set ``mktrend`` (and the seasonal trends of a monthly series)."""
        if table is None:
            return
        values = _value_column(table)
        if np.isnan(values).all():
            return  # "NO DATA FOR ...": returns before any trend
        self.mktrend = sen_trend(values)
        time = table["time"]
        if time.dtype == object and time.astype(str).str.len().eq(7).all():
            months, years = _months_years(table)
            for season, series in seasonal_series(
                values, months, years, season_function(name)
            ).items():
                self.seasons[season] = sen_trend(series)  # NA unless min_trend_data passes

    def index(self, name: str, frequency: str, table: pd.DataFrame | None, seasonal: bool):
        """One index of ``index.calc`` (or ``calculate.custom.index``)."""
        self.plot_call(name, table)
        if self.mktrend is None:
            return
        self.row(name, frequency, self.mktrend)
        if seasonal:
            for season in SEASONS:
                self.row(name, season, self.seasons.get(season, NA_TREND))
        self.mktrend = None

    def precindex(self, index: str, scales: tuple[int, ...], tables: Mapping[str, pd.DataFrame]):
        """``plot.precindex`` for SPI or SPEI."""
        for scale in scales:
            table = tables.get(f"indices/{scale}month_{index}_MON")
            if table is None:
                continue
            values = table[index].to_numpy(dtype=float)
            if np.isnan(values).all():
                continue
            months, _ = _months_years(table)
            for month, label in _PRECINDEX_ROWS.get(scale, ()):
                self.row(f"{index}{scale}", label, sen_trend(values[months == month]))
            self.mktrend = None  # remove(mktrend)


@derived
def trend_file(run: StationRun, tables: Mapping[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """``trend/trend``: one row per trend R writes, in R's order."""
    years = pd.DatetimeIndex(run.data.time.values).year
    writer = _TrendWriter(int(years[0]), int(years[-1]))
    for short, name, suffix, frequency, _ in index_files(run.params, special=True):
        if short == "hw":
            # plot.hw computes a trend for each aspect with a value, writes none, and
            # removes mktrend.
            if any(
                not np.isnan(_value_column(tables[key])).all()
                for key in (f"indices/{d}-{a}_ANN" for d in ("TX90", "TN90") for a in _HW)
                if key in tables
            ):
                writer.mktrend = None
        elif short == "hwEHF":
            for aspect in _EHF_ORDER:
                writer.plot_call(f"EHF-{aspect}", tables.get(f"indices/EHF-{aspect}_ANN"))
        elif short in ("spei", "spi"):
            writer.precindex(short, (3, 6, 12, run.params.spei_months), tables)
        else:
            writer.index(
                name,
                "NA" if frequency is None else frequency,
                tables.get(f"indices/{name}_{suffix}"),
                seasonal=frequency == "monthly" and short != "tx95t",
            )

    if (spec := run.params.custom) is not None:
        for suffix, frequency in (("ANN", "annual"), ("MON", "monthly")):
            writer.index(
                spec.name,
                frequency,
                tables.get(f"indices/{spec.name}_{suffix}"),
                seasonal=frequency == "monthly",
            )

    return {"trend/trend": pd.DataFrame(writer.rows, columns=list(COLUMNS))}
