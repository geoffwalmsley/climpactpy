"""Climpact's Excess Heat Factor (EHF) heatwaves and the daily EHF and ECF series.

A port of ``climdex.hwEHF`` (``climpact.etsci-functions.r``, line 936; Nairn and
Fawcett 2015), driven by ``services/calculate/calculate_hwEHF.R`` and written by
``write.hwEHF.csv`` (``services/write_indices.R``).

Climpact 3.4.3 does not use ``get.hw.aspects`` (see :mod:`climpact.products.heatwaves`)
for EHF: heatwaves are counted in calendar years, not in an extended summer, and the
aspects are HWN, HWF, HWD, HWMD (mean duration), HWPI, HWLI (peak and load intensity)
and HWPS, HWLS (peak and load severity).

- TAVG is ``(TX + TN) / 2`` on every day, 29 February included.
- ``T95`` and ``T05`` are single numbers: R ``quantile(type = 7)`` of TAVG over every
  day of the base-period years. They are not the day-of-year ``HW_TAVG90`` thresholds.
- From the 33rd day of the series, with ``T3`` the mean of TAVG over the day and the two
  before it (missing if any is missing) and ``T30`` the sum of the non-missing TAVG on
  the 30 days before those, divided by 30 whatever the number of missing days::

      EHF = max(1, T3 - T30) * (T3 - T95)
      ECF = min(-1, T3 - T30) * -(T3 - T05)

- A heatwave is a run of days with EHF > 0 plus the two days before it. Heatwaves less
  than three days apart are joined, a heatwave crossing 31 December is split into one
  heatwave per year, and each piece counts in its own year.
- Severity is EHF divided by ``EHF85``, the 85th percentile (type 7) of the positive
  base-period EHF values.
- The annual values are multiplied by the TX and TN climdex annual masks, and the first
  year is always missing.
- Nothing is written when less than half of the base period has TAVG, or when HWF is
  missing in every year.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from climpact.calendars import days_per_year
from climpact.missing import valid_mask
from climpact.outputs import product
from climpact.products.heatwaves import aspect_table
from climpact.rnumerics import r_mean, r_sum, r_window_sums
from climpact.station import StationRun
from climpact.thresholds import r_quantile_type7

FIRST_DAY = 32  # 0-based: EHF needs the 32 days before it (R loops from a = 33)
ACCLIMATISATION_DAYS = 30
MIN_BASE_FRACTION = 0.5
# Annual aspects, in the order write.hwEHF.csv writes them.
ASPECTS = ("HWPS", "HWPI", "HWLS", "HWLI", "HWD", "HWMD", "HWN", "HWF")
# Daily files and their value column.
DAILY = {"EHFdaily": "Excess Heat Factor", "ECFdaily": "Excess Cold Factor"}


def excess_factors(tavg: np.ndarray, t95, t05) -> tuple[np.ndarray, np.ndarray]:
    """Daily EHF and ECF, as the loop in ``climdex.hwEHF``; missing before day 33.

    ``tavg``'s last axis is time (any leading dimensions, for example grid cells, with
    ``t95`` and ``t05`` one per series). The three-day sum is R ``sum(a, b, c)`` of three
    arguments, accumulated in double precision; the 30-day sum is one
    ``sum(..., na.rm = TRUE)``, accumulated in extended precision
    (:func:`~climpact.rnumerics.r_window_sums`).
    """
    tavg = np.asarray(tavg, dtype=float)
    n = tavg.shape[-1]
    ehf = np.full(tavg.shape, np.nan)
    ecf = np.full(tavg.shape, np.nan)
    if n <= FIRST_DAY:
        return ehf, ecf
    t95 = np.asarray(t95, dtype=float)[..., np.newaxis]
    t05 = np.asarray(t05, dtype=float)[..., np.newaxis]
    with np.errstate(invalid="ignore"):
        # days a, a - 1 and a - 2 for a = 32 ... n - 1
        t3 = (
            (tavg[..., FIRST_DAY:] + tavg[..., FIRST_DAY - 1 : -1]) + tavg[..., FIRST_DAY - 2 : -2]
        ) / 3
    # the 30 days before the three: days a - 32 ... a - 3 for a = 32 ... n - 1
    t30 = r_window_sums(tavg, ACCLIMATISATION_DAYS)[..., : n - FIRST_DAY]
    accl = t3 - t30 / ACCLIMATISATION_DAYS
    # R max(1, NA) and min(-1, NA) are NA; accl is missing only where t3 is.
    with np.errstate(invalid="ignore"):
        ehf[..., FIRST_DAY:] = np.maximum(1.0, accl) * (t3 - t95)
        ecf[..., FIRST_DAY:] = np.minimum(-1.0, accl) * (-1 * (t3 - t05))
    return ehf, ecf


def _runs(flags: np.ndarray) -> list[tuple[int, int]]:
    """``(first, last)`` 0-based days of each run of TRUE (``flags == 1``)."""
    true = np.concatenate([[False], flags, [False]])
    edges = np.flatnonzero(true[1:] != true[:-1])
    return list(zip(edges[::2].tolist(), (edges[1::2] - 1).tolist(), strict=True))


def heatwaves(ehf: np.ndarray, years: np.ndarray) -> list[tuple[int, int]]:
    """Heatwaves as ``(first, last)`` 0-based days, in the order R's final loop takes
    them.

    Each run of EHF > 0 starts two days early (R's first loop); a heatwave starting no
    later than the day after the previous one ends is joined to it. Heatwaves crossing
    31 December are then split by calendar year (R's second loop): heatwaves within one
    year keep their place, and the pieces of split ones are appended at the end, in
    order, as R appends them to ``heatwave_stats``.
    """
    with np.errstate(invalid="ignore"):
        positive = ehf > 0
    joined: list[tuple[int, int]] = []
    for first, last in _runs(positive):
        start = first - 2
        if joined and start <= joined[-1][1] + 1:
            start = joined.pop()[0]
        joined.append((max(start, 0), last))

    kept, pieces = [], []
    for start, end in joined:
        if years[start] == years[end]:
            kept.append((start, end))
            continue
        for year in np.unique(years[start : end + 1]):
            days = np.flatnonzero(years[start : end + 1] == year) + start
            pieces.append((int(days[0]), int(days[-1])))
    return kept + pieces


def annual_aspects(ehf: np.ndarray, years: np.ndarray, ehf85: float) -> dict[str, np.ndarray]:
    """The eight annual EHF heatwave aspects, before the missing-data mask, one value per
    calendar year of ``years``."""
    uniq = np.unique(years)
    per_year: dict[int, dict[str, list[float]]] = {
        int(y): {k: [] for k in ("dur", "ps", "pi", "ls", "li")} for y in uniq
    }
    for start, end in heatwaves(ehf, years):
        values = ehf[start : end + 1]
        acc = per_year[int(years[start])]
        acc["dur"].append(float(values.size))
        with np.errstate(invalid="ignore"):
            pos = values[values > 0]
        if pos.size == 0:
            # R: a piece with no positive EHF (the two leading days of a heatwave that
            # starts on 1 or 2 January) has a duration only. With a missing value among
            # them R stops (`if (NA)`); here it is treated the same way.
            continue
        # With EHF85 missing (no positive base-period EHF, or a missing threshold from a
        # gridded thresholds file) every severity is NA: R's max(na.rm = TRUE) is -Inf
        # and sum(na.rm = TRUE) is 0.
        severities = pos / ehf85
        severities = severities[~np.isnan(severities)]
        acc["pi"].append(float(np.nanmax(values)))
        acc["li"].append(r_sum(pos))
        acc["ps"].append(float(severities.max()) if severities.size else -np.inf)
        acc["ls"].append(r_sum(severities))

    def stat(key: str, func) -> np.ndarray:
        def value(x: list[float]) -> float:
            if not x:
                return np.nan
            if not np.isfinite(x).all():  # -Inf peak severity: R's mean is -Inf too
                return float(np.mean(x))
            return func(x)

        return np.array([value(per_year[int(y)][key]) for y in uniq])

    return {
        "HWPS": stat("ps", r_mean),
        "HWPI": stat("pi", r_mean),
        "HWLS": stat("ls", r_sum),
        "HWLI": stat("li", r_sum),
        "HWD": stat("dur", max),
        "HWMD": stat("dur", r_mean),
        "HWN": np.array([float(len(per_year[int(y)]["dur"])) for y in uniq]),
        "HWF": np.array([float(sum(per_year[int(y)]["dur"])) for y in uniq]),
    }


def base_data_sufficient(
    tavg_base: np.ndarray, base_start: int, base_end: int, calendar: str | None = None
) -> bool:
    """R's check: TAVG present on at least half of the days from 1 January of the first
    base year to 31 December of the last (``difftime`` of the two dates). In the
    ``noleap`` and ``360_day`` calendars (gridded data) the last day is the calendar's
    last day of the year, so the difference is ``years * dpy - 1`` days."""
    if calendar is None:
        ideal = (dt.date(base_end, 12, 31) - dt.date(base_start, 1, 1)).days
    else:
        ideal = (base_end - base_start + 1) * days_per_year(calendar) - 1
    return np.count_nonzero(~np.isnan(tavg_base)) / ideal >= MIN_BASE_FRACTION


@product
def ehf_heatwaves(run: StationRun) -> dict[str, pd.DataFrame]:
    """EHF-HW{PS,PI,LS,LI,D,MD,N,F}_ANN, EHFdaily and ECFdaily (``climdex.hwEHF``).

    As ``write.hwEHF.csv``, all ten files are written unless HWF is missing in every
    year, so an aspect can be missing in every year.
    """
    ds = run.data
    meta = run.metadata
    time = pd.DatetimeIndex(ds.time.values)
    years = time.year.to_numpy()
    tavg = ds.tas.values.astype(float)
    in_base = (years >= meta.base_start) & (years <= meta.base_end)
    if not base_data_sufficient(tavg[in_base], meta.base_start, meta.base_end):
        return {}
    t95 = r_quantile_type7(tavg[in_base], 0.95)
    t05 = r_quantile_type7(tavg[in_base], 0.05)
    ehf, ecf = excess_factors(tavg, t95, t05)
    base_ehf = ehf[in_base]
    with np.errstate(invalid="ignore"):
        ehf85 = r_quantile_type7(base_ehf[base_ehf > 0], 0.85)

    aspects = annual_aspects(ehf, years, ehf85)
    namask = np.where(
        valid_mask(ds.tasmin, freq="YS").values & valid_mask(ds.tasmax, freq="YS").values,
        1.0,
        np.nan,
    )
    namask[0] = np.nan  # R: the first month of EHF is missing, which the mask ignores
    aspects = {name: values * namask for name, values in aspects.items()}
    if np.isnan(aspects["HWF"]).all():
        return {}

    uniq = np.unique(years)
    tables = {
        f"indices/EHF-{name}_ANN": aspect_table(name, aspects[name], uniq) for name in ASPECTS
    }
    dates = time.strftime("%Y-%m-%d")
    for name, values in (("EHFdaily", ehf), ("ECFdaily", ecf)):
        tables[f"indices/{name}"] = pd.DataFrame({"date": dates, DAILY[name]: values})
    return tables
