"""Climpact's Tx90 and Tn90 heatwave indices (Perkins and Alexander 2013).

A port of ``climdex.hw`` and ``get.hw.aspects`` in ``climpact.etsci-functions.r``
(lines 674 and 773). :func:`hw_aspects` is the shared machinery that turns daily
heatwave flags into the five annual aspects; the EHF and ECF heatwaves (#21) use it
too.

A heatwave is a run of at least three days whose value exceeds the 15-day-window
90th percentile for the day of year (``Thresholds.heatwave``). Each year's aspects
are taken over its extended summer: November to March (starting in the year) in the
Southern Hemisphere, May to September in the Northern Hemisphere, where latitude 0
counts as southern. 29 February is dropped before anything else.

R quirks reproduced (see TECHNICAL.md, "Heatwaves"):

- Runs shorter than three days are removed over the whole series before the season
  is cut out, and a missing flag counts as FALSE (``select.blocks.gt.length``).
- A heatwave that started before the season counts with only its in-season days.
- A heatwave that starts in the season and runs past its end counts, cut to end at
  most 14 days after the season ends. Only the first such run is considered, and a
  heatwave that already runs on the first day of the season and past its end is not
  counted at all.
- HWA is the peak of the heatwave with the highest mean (the first, on ties), not
  the hottest day of the season.
- HWN and HWF are missing for every year when HWM is missing for every year.
- In the Southern Hemisphere the last year is missing (its summer is incomplete).
- Values are multiplied by the variable's annual climdex missing-data mask; a
  season's own missing days are not otherwise checked.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from climpact.missing import valid_mask
from climpact.outputs import product
from climpact.products.indices import r_compare, select_blocks_gt_length
from climpact.products.tables import period_labels
from climpact.rnumerics import r_mean
from climpact.station import StationRun
from climpact.thresholds import InsufficientBaseData, day_of_year

# Order of the aspects in R's aspect.array, and the file and column name of each.
ASPECTS = ("HWM", "HWA", "HWN", "HWD", "HWF")
ASPECT_NAMES = {
    "HWM": "magnitude",
    "HWA": "amplitude",
    "HWN": "number",
    "HWD": "duration",
    "HWF": "frequency",
}
SUMMER_MONTHS = {True: (5, 6, 7, 8, 9), False: (11, 12, 1, 2, 3)}  # northern -> months
EXTENDED_WINDOW = 90  # days after the season searched for heatwaves that began in it
MAX_DAYS_AFTER_SEASON = 14  # a heatwave running past the season is cut this long after
MIN_LENGTH = 3  # days


def rle(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """R ``rle`` on a logical held as 1/0/NaN: ``(lengths, values)``. Each missing
    value is a run of its own, as in R (``NA != NA`` is ``NA``)."""
    if x.size == 0:
        return np.zeros(0, dtype=np.int64), np.zeros(0)
    nan = np.isnan(x)
    change = (x[1:] != x[:-1]) | nan[1:] | nan[:-1]
    ends = np.concatenate([np.flatnonzero(change), [x.size - 1]])
    lengths = np.diff(np.concatenate([[-1], ends]))
    return lengths.astype(np.int64), x[ends]


def _is(value: float, flag: int) -> bool | None:
    """R ``value == flag`` for a logical: None when ``value`` is NA."""
    if np.isnan(value):
        return None
    return bool(value == flag)


def _r_all(*conditions: bool | None) -> bool:
    """R ``all()`` used in an ``if``: FALSE wins; NA without a FALSE is an error in R."""
    if any(c is False for c in conditions):
        return False
    if any(c is None for c in conditions):
        raise ValueError("missing value where TRUE/FALSE needed (R error)")
    return True


def season_aspects(
    flags: np.ndarray, data: np.ndarray, summer: np.ndarray
) -> tuple[float, float, float, float, float]:
    """One year of ``get.hw.aspects``: ``(HWM, HWA, HWN, HWD, HWF)`` for the season whose
    day indices (0-based, contiguous) are ``summer``.

    ``flags`` is the heatwave flag of every day (1/0/NaN) and ``data`` the daily values
    averaged and maximised over each heatwave. Days past the end of the series are
    missing, as when R indexes past the end of a vector.
    """
    n = flags.size
    start, season_length = int(summer[0]), summer.size
    if start < 2:
        # R would index flags[0] (empty) or flags[-1] (all but the first) here.
        raise ValueError("a season cannot start on the first two days of the series")
    idx = np.arange(start, int(summer[-1]) + EXTENDED_WINDOW + 1)
    inside = idx < n
    ext_flags = np.where(inside, flags[np.minimum(idx, n - 1)], np.nan)
    ext_data = np.where(inside, data[np.minimum(idx, n - 1)], np.nan)
    lengths, values = rle(ext_flags)
    last_day = ext_flags.size - EXTENDED_WINDOW  # = season length
    ends = np.cumsum(lengths)
    is_true = values == 1  # NaN -> False, as which() drops NA

    # Run numbers (1-based) of heatwaves that end inside the season.
    truevals = list(np.flatnonzero((lengths >= MIN_LENGTH) & (ends <= last_day) & is_true) + 1)

    # A heatwave that began before the season with only one or two days inside it.
    # R first checks that the flags it compares are present, except the third day of
    # the season in the first test and the second in the second.
    e1, e2, e3 = ext_flags[:3]
    prev2, prev1 = flags[start - 2], flags[start - 1]
    if not np.isnan([e1, e2, prev1]).any() and _r_all(
        _is(e1, 1), _is(e2, 1), _is(e3, 0), _is(prev1, 1)
    ):
        if not truevals or truevals[0] != 1:
            truevals.insert(0, 1)
    if not np.isnan([e1, prev2, prev1]).any() and _r_all(
        _is(e1, 1), _is(e2, 0), _is(prev2, 1), _is(prev1, 1)
    ):
        if not truevals or truevals[0] != 1:
            truevals.insert(0, 1)

    # The first heatwave that ends after the season, counted if it began inside it.
    extvals = np.flatnonzero((lengths >= MIN_LENGTH) & (ends > last_day) & is_true) + 1
    if ends.size > 1 and extvals.size and extvals[0] > 1 and ends[extvals[0] - 2] < last_day:
        e = int(extvals[0])
        truevals.append(e)
        limit = season_length + MAX_DAYS_AFTER_SEASON
        if ends[e - 1] > limit:
            lengths[e - 1] -= ends[e - 1] - limit
            ends = np.cumsum(lengths)

    nhw = len(truevals)
    if nhw == 0:
        return np.nan, np.nan, 0.0, np.nan, 0.0
    hwm, hwa = np.empty(nhw), np.empty(nhw)
    for i, run in enumerate(truevals):
        i1 = 0 if run == 1 else int(ends[run - 2])
        segment = ext_data[i1 : int(ends[run - 1])]
        segment = segment[~np.isnan(segment)]
        hwm[i] = r_mean(segment) if segment.size else np.nan
        hwa[i] = segment.max() if segment.size else -np.inf
    run_lengths = lengths[np.array(truevals) - 1]
    frequency = float(run_lengths.sum())
    valid = ~np.isnan(hwm)
    if not valid.any():  # R: mean(hwm, na.rm = TRUE) is NaN
        return np.nan, np.nan, float(nhw), np.nan, frequency
    magnitude = r_mean(hwm[valid])
    amplitude = hwa[int(np.nanargmax(hwm))]  # which.max: first maximum, NA skipped
    return magnitude, amplitude, float(nhw), float(run_lengths.max()), frequency


def summer_days(years: np.ndarray, months: np.ndarray, year: int, northern: bool) -> np.ndarray:
    """Indices of the days of ``year``'s extended summer (Nov-Mar starting in ``year`` in
    the south, May-Sep in the north)."""
    if northern:
        sel = (years == year) & np.isin(months, SUMMER_MONTHS[True])
    else:
        sel = ((years == year) & (months >= 11)) | ((years == year + 1) & (months <= 3))
    return np.flatnonzero(sel)


def hw_aspects(
    flags: np.ndarray,
    data: np.ndarray,
    years: np.ndarray,
    months: np.ndarray,
    northern: bool,
    namask: np.ndarray | float = 1.0,
) -> np.ndarray:
    """``get.hw.aspects``: the annual heatwave aspects, as an array ``(5, years)`` in the
    order of :data:`ASPECTS`.

    ``flags`` (1/0/NaN, runs of fewer than three days already removed), ``data``,
    ``years`` and ``months`` are daily, without 29 February. ``namask`` is the annual
    missing-data mask (1 or NaN per year) the result is multiplied by.
    """
    uniq = np.unique(years)
    out = np.full((len(ASPECTS), uniq.size), np.nan)
    if np.isnan(data).all():
        return out
    for k, year in enumerate(range(int(uniq[0]), int(uniq[-1]) + 1)):
        summer = summer_days(years, months, year, northern)
        out[:, k] = season_aspects(flags, data, summer)

    out[[1, 3]] = np.where(np.isneginf(out[[1, 3]]), np.nan, out[[1, 3]])
    if np.isnan(out[0]).all():  # no heatwave magnitude at all: HWN and HWF missing too
        out[[2, 4]] = np.nan
    if not northern:  # the last summer is incomplete
        out[:, -1] = np.nan
    return out * namask


def heatwave_flags(x: np.ndarray, thr: np.ndarray) -> np.ndarray:
    """Days in runs of at least three days with ``x > thr`` (1/0), as ``climdex.hw``:
    ``select.blocks.gt.length(x > thr, 2)`` over the whole series."""
    return select_blocks_gt_length(r_compare(x, thr, ">"), MIN_LENGTH - 1)


def aspect_table(name: str, values: np.ndarray, years: np.ndarray) -> pd.DataFrame:
    """Heatwave file layout (``write.hw.csv``): ``time`` and the aspect, no anomaly."""
    time = pd.to_datetime([f"{y}-01-01" for y in years])
    return pd.DataFrame({"time": period_labels(time, "ANN"), name: values})


@product
def tx90_tn90_heatwaves(run: StationRun) -> dict[str, pd.DataFrame]:
    """TX90-HW{M,A,N,D,F}_ANN and TN90-HW{M,A,N,D,F}_ANN (``climdex.hw``).

    As ``write.hw.csv``, all ten files are written whenever any value is present,
    including files that are missing for every year.
    """
    try:
        th = run.thresholds
    except InsufficientBaseData:
        return {}
    ds = run.data
    time = pd.DatetimeIndex(ds.time.values)
    keep = ~((time.month == 2) & (time.day == 29))
    time = time[keep]
    years, months = time.year.to_numpy(), time.month.to_numpy()
    jday = day_of_year(time) - 1
    northern = run.metadata.northern_hemisphere
    uniq = np.unique(years)

    results = {}
    for label, var in (("TX90", "tasmax"), ("TN90", "tasmin")):
        x = ds[var].values[keep]
        flags = heatwave_flags(x, th.heatwave[var][jday])
        namask = np.where(valid_mask(ds[var], freq="YS").values, 1.0, np.nan)
        results[label] = hw_aspects(flags, x, years, months, northern, namask)

    if all(np.isnan(v).all() for v in results.values()):
        return {}
    return {
        f"indices/{label}-{aspect}_ANN": aspect_table(aspect, values[i], uniq)
        for label, values in results.items()
        for i, aspect in enumerate(ASPECTS)
    }
