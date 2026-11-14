"""Climpact's Tx90/Tn90 and EHF heatwaves for the cells of a grid (``hw_ANN``,
``hwEHF_ANN``).

R computes them per cell with the station functions ``climdex.hw`` and ``climdex.hwEHF``
(``climpact.etsci-functions.r``), so the station code does the work
(:mod:`climpact.products.heatwaves`, :mod:`climpact.products.ehf`), including the R
behaviour the station port deliberately does not copy (#51). What differs from a
station run:

- the hemisphere is the cell's latitude ``>= 0`` (``get.northern.hemisphere.booleans``);
- with a thresholds file, ``climdex.hw`` uses its ``tx90thresh_15days`` and
  ``tn90thresh_15days`` instead of recomputing them, and ``climdex.hwEHF`` its
  ``tavg95thresh``, ``tavg05thresh`` and ``ehf85thresh``, and then skips the check that
  half of the base period has data;
- in the ``noleap`` and ``360_day`` calendars no day is dropped (R drops 29 February
  only in the standard calendar), and ``climdex.hw`` looks up each day's threshold by
  its month and day in a 365-day year (:func:`hw_threshold_days`), which in the
  ``360_day`` calendar is not the day the threshold was computed for;
- R stops (``write.climdex.results`` indexes a missing result) on a grid with an
  all-missing cell, and on ``hwEHF`` for a cell with less than half of the base period.
  Python writes missing values for such cells instead (see TECHNICAL.md).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from climpact.calendars import CalendarDays, calendar_of
from climpact.missing import valid_periods
from climpact.products.ehf import annual_aspects, base_data_sufficient, excess_factors
from climpact.products.heatwaves import ASPECTS, heatwave_flags, hw_aspects
from climpact.thresholds import (
    HEATWAVE_QUANTILE,
    HEATWAVE_WINDOW,
    base_period_array,
    day_of_year,
    r_quantile_type7_rows,
    running_quantiles,
)

# hw_ANN's variables, in the file's order (create.ncdf.output.files): (name, units,
# long name), aspect-major, Tx90 before Tn90.
_HW_ASPECT_UNITS = {"HWM": "degC", "HWA": "degC", "HWN": "heatwaves", "HWD": "days", "HWF": "days"}
_HW_ASPECT_NAMES = {
    "HWM": "magnitude",
    "HWA": "amplitude",
    "HWN": "number",
    "HWD": "duration",
    "HWF": "frequency",
}
HW_DEFINITIONS = (("tx90", "tasmax", "Tx90"), ("tn90", "tasmin", "Tn90"))
HW_VARIABLES = tuple(
    (
        f"{aspect.lower()}_{key}",
        _HW_ASPECT_UNITS[aspect],
        f"Heatwave {_HW_ASPECT_NAMES[aspect]} for {label} heatwaves, see user guide for "
        "definition.",
    )
    for aspect in ASPECTS
    for key, _, label in HW_DEFINITIONS
)
# hwEHF_ANN's variables, in the file's order, and the station aspect each holds.
EHF_VARIABLES = (
    ("EHF-HWMD", "HWMD", "days", "Mean EHF heatwave duration"),
    ("EHF-HWD", "HWD", "days", "Duration of the longest EHF heatwave"),
    ("EHF-HWPS", "HWPS", "unitless", "Mean of the maximum severity of each EHF heatwave"),
    ("EHF-HWPI", "HWPI", "degC^2", "Mean of the maximum intensity of each EHF heatwave"),
    ("EHF-HWLS", "HWLS", "unitless", "Sum of EHF heatwave severities"),
    ("EHF-HWLI", "HWLI", "degC^2", "Sum of EHF heatwave intensities"),
    ("EHF-HWN", "HWN", "heatwaves", "Number of EHF heatwaves"),
    ("EHF-HWF", "HWF", "days", "Number of days contributing to EHF heatwaves"),
)
EHF_FILE_THRESHOLDS = ("tavg95thresh", "tavg05thresh", "ehf85thresh")


def _annual_mask(*arrays: np.ndarray, time: pd.DatetimeIndex) -> np.ndarray:
    """The climdex annual mask (1 or NaN) of all ``arrays`` together, ``(cells, years)``."""
    valid = None
    for x in arrays:
        v = valid_periods(~np.isnan(x), time, "YS")
        valid = v if valid is None else valid & v
    return np.where(valid, 1.0, np.nan)


def hw_threshold_days(days, dpy: int) -> np.ndarray:
    """The 0-based index of each day's threshold in ``climdex.hw`` (-1: none), for the
    days of ``days`` it keeps.

    R takes ``tx90p[match(fact2, fact)]``: the position of the day's month and day
    (``"%m-%d"``) in the days of 2001. In the standard calendar (29 February dropped) and
    ``noleap`` that is its day of year. In ``360_day`` it is not: 30 January is day 30
    but takes the threshold of day 30, while 1 February takes day 32's, and so on, and
    29 and 30 February (not in 2001) and the days past ``dpy`` (27-30 December) get none.
    Kept for R parity (see TECHNICAL.md)."""
    if not isinstance(days, CalendarDays):
        return day_of_year(days) - 1
    in_2001 = pd.to_datetime(
        {"year": 2001, "month": days.month.to_numpy(), "day": days.day.to_numpy()},
        errors="coerce",
    )
    position = in_2001.dt.day_of_year.to_numpy(dtype=float, na_value=np.nan) - 1
    return np.where(np.isnan(position) | (position >= dpy), -1, position).astype(np.int64)


def hw_values(
    tx: np.ndarray,
    tn: np.ndarray,
    full: pd.DatetimeIndex,
    northern: np.ndarray,
    base_start: int,
    base_end: int,
    thresholds: dict[str, np.ndarray] | None = None,
) -> np.ndarray:
    """``climdex.hw`` for ``(cells, time)`` TX and TN on the whole-year axis ``full``:
    ``(cells, 10, years)``, in the order of :data:`HW_VARIABLES`.

    ``thresholds`` holds the cells' 15-day-window 90th percentiles ``(cells, dpy)`` by
    variable (``tasmax``, ``tasmin``) from a thresholds file; None computes them from
    the base period as ``get.outofbase.quantiles(n = 15)`` does.
    """
    if isinstance(full, CalendarDays):
        keep = np.ones(full.size, dtype=bool)
    else:
        keep = ~((full.month == 2) & (full.day == 29))
    days = full[keep]
    years, months = days.year.to_numpy(), days.month.to_numpy()
    n_years = np.unique(years).size
    data = {"tasmax": tx, "tasmin": tn}
    out = np.full((tx.shape[0], len(HW_VARIABLES), n_years), np.nan)
    for d, (_, var, _) in enumerate(HW_DEFINITIONS):
        x = data[var]
        if thresholds is None:
            base = base_period_array(x, full, base_start, base_end)
            thr = running_quantiles(base, HEATWAVE_WINDOW, [HEATWAVE_QUANTILE])[HEATWAVE_QUANTILE]
        else:
            thr = thresholds[var]
        jday = hw_threshold_days(days, thr.shape[-1])
        # A day without a threshold reads the NaN column added at the end.
        thr = np.concatenate([thr, np.full((thr.shape[0], 1), np.nan)], axis=1)
        namask = _annual_mask(x, time=full)
        for cell in range(x.shape[0]):
            values = x[cell, keep]
            daily_thr = thr[cell, jday]
            flags = heatwave_flags(values, daily_thr)
            # As the station product: a day without a threshold has no usable value (#51).
            values = np.where(np.isnan(daily_thr), np.nan, values)
            aspects = hw_aspects(flags, values, years, months, bool(northern[cell]), namask[cell])
            out[cell, d :: len(HW_DEFINITIONS)] = aspects
    return out


def hwehf_values(
    tx: np.ndarray,
    tn: np.ndarray,
    full: pd.DatetimeIndex,
    base_start: int,
    base_end: int,
    thresholds: dict[str, np.ndarray] | None = None,
) -> np.ndarray:
    """``climdex.hwEHF`` (``ehfdef = "NF13"``) for ``(cells, time)`` TX and TN on
    ``full``: ``(cells, 8, years)``, in the order of :data:`EHF_VARIABLES`.

    ``thresholds`` holds the cells' :data:`EHF_FILE_THRESHOLDS` ``(cells,)`` from a
    thresholds file; None computes them from the base period, and a cell with TAVG on
    less than half of the base period gets missing values (R stops).
    """
    tavg = (tx + tn) / 2
    years = full.year.to_numpy()
    in_base = (years >= base_start) & (years <= base_end)
    if thresholds is None:
        base = tavg[:, in_base]
        t95 = r_quantile_type7_rows(base, 0.95)
        t05 = r_quantile_type7_rows(base, 0.05)
        sufficient = np.array(
            [base_data_sufficient(row, base_start, base_end, calendar_of(full)) for row in base],
            dtype=bool,
        )
    else:
        t95, t05 = thresholds["tavg95thresh"], thresholds["tavg05thresh"]
        sufficient = np.ones(tavg.shape[0], dtype=bool)
    ehf, _ = excess_factors(tavg, t95, t05)
    if thresholds is None:
        base_ehf = ehf[:, in_base]
        with np.errstate(invalid="ignore"):
            ehf85 = r_quantile_type7_rows(np.where(base_ehf > 0, base_ehf, np.nan), 0.85)
    else:
        ehf85 = thresholds["ehf85thresh"]

    namask = _annual_mask(tn, tx, time=full)
    namask[:, 0] = np.nan  # R: the first month of EHF is missing, which the mask ignores
    out = np.full((tx.shape[0], len(EHF_VARIABLES), np.unique(years).size), np.nan)
    for cell in np.flatnonzero(sufficient):
        aspects = annual_aspects(ehf[cell], years, float(ehf85[cell]))
        out[cell] = [aspects[key] for _, key, _, _ in EHF_VARIABLES]
    return out * namask[:, np.newaxis, :]
