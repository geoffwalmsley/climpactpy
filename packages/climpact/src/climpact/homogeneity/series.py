"""The series the break detection tests: annual and monthly mean TX and TN, annual PRCP.

Each series has one value per period (year or month) from the first to the last year of
the station's data, missing (NaN) where the climdex.pcic rules say so
(:mod:`climpact.missing`: a month with more than 3 missing days, a year with more than 15
or a missing month), so the means are those of Climpact's TXm and TNm indices. PRCP is
the natural log of the annual total of every day's precipitation (not PRCPTOT, which
counts wet days only): a shift in log precipitation is a ratio of the totals. A year whose
total is zero has no logarithm and is missing.

Monthly series are tested as they are by RHtests, which removes the annual cycle itself.
The Pettitt and SNHT tests get the anomalies from each calendar month's mean
(:func:`anomalies`).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from climpact.missing import valid_periods
from climpact.periods import periods
from climpact.rnumerics import r_mean, r_sum
from climpact.station import StationRun

ANNUAL = "annual"
MONTHLY = "monthly"
FREQUENCIES = (ANNUAL, MONTHLY)
VARIABLES = ("TX", "TN", "PRCP")

# Variable -> (station dataset variable, units of the tested values)
_SOURCES = {"TX": ("tasmax", "degC"), "TN": ("tasmin", "degC"), "PRCP": ("pr", "log(mm)")}
_RULES = {ANNUAL: "YS", MONTHLY: "MS"}


@dataclass(frozen=True, eq=False)
class Series:
    """One tested series: a value per period, NaN where missing.

    ``months`` is the calendar month of each period (1-12) for monthly series and 0 for
    annual ones, as in RHtests' input files.
    """

    variable: str
    freq: str
    years: np.ndarray
    months: np.ndarray
    values: np.ndarray
    units: str

    @property
    def per_year(self) -> int:
        """Periods per year: 1 or 12."""
        return 12 if self.freq == MONTHLY else 1

    @property
    def valid(self) -> np.ndarray:
        """True where the period has a value."""
        return ~np.isnan(self.values)

    def label(self, i: int) -> str:
        """The period at position ``i``: ``"1975"`` or ``"1975-04"``."""
        if self.freq == ANNUAL:
            return f"{self.years[i]:d}"
        return f"{self.years[i]:d}-{self.months[i]:02d}"


def build_series(run: StationRun, variable: str, freq: str) -> Series:
    """The ``freq`` (``"annual"`` or ``"monthly"``) series of ``variable`` for ``run``."""
    name, units = _SOURCES[variable]
    if variable == "PRCP" and freq != ANNUAL:
        raise ValueError("PRCP is tested as annual totals only")
    data = run.data[name].values
    time = run.data["time"]
    rule = _RULES[freq]
    p = periods(time, rule)
    valid = valid_periods(~np.isnan(data), time, rule)
    if variable == "PRCP":
        totals = p.apply(data, r_sum)
        with np.errstate(divide="ignore", invalid="ignore"):
            values = np.where(valid & (totals > 0), np.log(totals), np.nan)
    else:
        values = np.where(valid, p.apply(data, r_mean), np.nan)
    labels = p.labels
    months = labels.month.to_numpy() if freq == MONTHLY else np.zeros(p.size, dtype=int)
    return Series(variable, freq, labels.year.to_numpy(), months, values, units)


def station_series(
    run: StationRun,
    variables: tuple[str, ...] = VARIABLES,
    frequencies: tuple[str, ...] = FREQUENCIES,
) -> list[Series]:
    """Every series tested for ``run``: each variable at each frequency (PRCP annual only)."""
    return [
        build_series(run, variable, freq)
        for variable in variables
        for freq in frequencies
        if not (variable == "PRCP" and freq == MONTHLY)
    ]


def anomalies(series: Series) -> np.ndarray:
    """The values the Pettitt and SNHT tests use: monthly values minus the mean of their
    calendar month (R's ``mean``, over the non-missing values); annual values as they are."""
    if series.freq == ANNUAL:
        return series.values.copy()
    out = series.values.copy()
    for month in range(1, 13):
        rows = (series.months == month) & series.valid
        if rows.any():
            out[rows] = series.values[rows] - r_mean(series.values[rows])
    return out
