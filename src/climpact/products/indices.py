"""Climpact's day-count, mean, extreme, spell, percentile and growing-season indices.

Missing data follows the climdex.pcic rules (:func:`climpact.missing.valid_mask`).
Index definitions follow ``climpact.etsci-functions.r`` and climdex.pcic 1.2-0; where
the two differ, Climpact's definition is used because it is the one that runs.
Monthly and annual reductions use :mod:`climpact.periods`, not xarray's ``resample``,
for speed.
"""

from __future__ import annotations

import operator
from collections.abc import Callable

import numpy as np
import pandas as pd
import xarray as xr

from climpact.missing import valid_mask
from climpact.outputs import product
from climpact.periods import periods
from climpact.products.tables import FREQS, dated_table, format_number, index_table
from climpact.rnumerics import r_cumsum, r_mean, r_sum
from climpact.station import StationRun
from climpact.thresholds import InsufficientBaseData, day_of_year

OPERATORS: dict[str, Callable] = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
}


# --- threshold counts -------------------------------------------------------------

# name -> (input variable, threshold in the variable's units (degC, mm/d), condition)
COUNTS: dict[str, tuple[str, float, str]] = {
    "fd": ("tasmin", 0.0, "<"),
    "tnlt2": ("tasmin", 2.0, "<"),
    "tnltm2": ("tasmin", -2.0, "<"),
    "tnltm20": ("tasmin", -20.0, "<"),
    "id": ("tasmax", 0.0, "<"),
    "su": ("tasmax", 25.0, ">"),
    "tr": ("tasmin", 20.0, ">"),
    "txge30": ("tasmax", 30.0, ">="),
    "txge35": ("tasmax", 35.0, ">="),
    "tmge5": ("tas", 5.0, ">="),
    "tmge10": ("tas", 10.0, ">="),
    "tmlt5": ("tas", 5.0, "<"),
    "tmlt10": ("tas", 10.0, "<"),
    "r10mm": ("pr", 10.0, ">="),
    "r20mm": ("pr", 20.0, ">="),
}


def count_days(da: xr.DataArray, threshold: float, condition: str, freq: str) -> xr.DataArray:
    """Number of days per period with ``da <condition> threshold`` (missing days do not
    count), masked by the climdex rules for ``da``.

    The same as xclim's ``tn_days_below``, ``tx_days_above``, ``wetdays`` and so on with
    ``check_missing="climdex"``, which compare in the data's units and count with
    ``resample(...).sum()``; done directly because xarray's resampling took most of a
    station run's time (``tests/test_index_helpers.py`` checks the two agree).
    """
    rule = FREQS[freq]
    with np.errstate(invalid="ignore"):
        hits = OPERATORS[condition](da.values, threshold)
    p = periods(da.time, rule)
    counts = p.wrap(p.count(hits).astype(float))
    return counts.where(valid_mask(da, freq=rule))


@product
def threshold_counts(run: StationRun) -> dict[str, pd.DataFrame]:
    p = run.params
    counts = dict(COUNTS)
    counts[f"r{format_number(p.rnnmm)}mm"] = ("pr", float(p.rnnmm), ">=")
    out = {}
    for name, (var, threshold, condition) in counts.items():
        for freq in FREQS:
            values = count_days(run.data[var], threshold, condition, freq)
            out[f"indices/{name}_{freq}"] = index_table(name, values, freq)
    return out


# --- user-defined threshold index -------------------------------------------------


@product
def custom_index(run: StationRun) -> dict[str, pd.DataFrame]:
    """User-defined count of days, e.g. TN > 0 (R ``calculate.custom.index``).

    The validity mask follows R: TM uses only the TN mask, and DTR uses TX and TN.
    """
    spec = run.params.custom
    if spec is None:
        return {}
    ds = run.data
    data, mask_vars = {
        "TX": (ds.tasmax, [ds.tasmax]),
        "TN": (ds.tasmin, [ds.tasmin]),
        "TM": (ds.tas, [ds.tasmin]),
        "PR": (ds.pr, [ds.pr]),
        "DTR": (ds.tasmax - ds.tasmin, [ds.tasmax, ds.tasmin]),
    }[spec.variable]
    hits = OPERATORS[spec.operator](data, spec.threshold) & data.notnull()

    out = {}
    for freq, rule in FREQS.items():
        p = periods(hits.time, rule)
        counts = p.wrap(p.count(hits.values).astype(float))
        values = counts.where(valid_mask(*mask_vars, freq=rule))
        out[f"indices/{spec.name}_{freq}"] = index_table(spec.name, values, freq)
    return out


# --- means and totals --------------------------------------------------------------


def period_stat(da: xr.DataArray, freq: str, stat: str, *mask_vars: xr.DataArray) -> xr.DataArray:
    """Mean, max or min per period, skipping missing days, masked by the climdex rules
    for ``mask_vars``.

    Used instead of xclim for temperature statistics: xclim converts temperatures to
    kelvin internally, and the round trip changes the last bits of most values, so
    extremes would no longer be identical to R.
    """
    rule = FREQS[freq]
    if stat == "mean":
        values = period_reduce(da, rule, r_mean)
    else:
        p = periods(da.time, rule)
        values = p.wrap(p.reduce(da.values, stat))
    return values.where(valid_mask(*mask_vars, freq=rule))


def period_reduce(da: xr.DataArray, rule: str, func: Callable) -> xr.DataArray:
    """Apply ``func`` to the non-missing values of each period (NaN if there are none).

    Used with the R-precision :func:`~climpact.rnumerics.r_mean` so that means are
    identical to R's, whose ``mean`` accumulates in extended precision.
    """
    p = periods(da.time, rule)
    return p.wrap(p.apply(da.values, func))


def precipitation_intensity(pr: np.ndarray) -> float:
    """climdex.pcic ``simple.precipitation.intensity``: wet-day total / wet days (0 if
    there are none), with R's extended-precision ``sum``."""
    wet = pr[pr >= 1]
    return r_sum(wet) / wet.size if wet.size else 0.0


def wet_day_total(pr: np.ndarray) -> float:
    """climdex.pcic ``total.precip.op.threshold(prec, 1, ">=")``: the total of days with at
    least 1 mm, with R's extended-precision ``sum`` (prcptot)."""
    return r_sum(pr[pr >= 1])


@product
def means_and_totals(run: StationRun) -> dict[str, pd.DataFrame]:
    ds = run.data
    out = {}
    for freq in FREQS:
        tables = {
            # climdex.dtr masks with the TM mask (a day is missing if TX or TN is missing),
            # which is stricter than masking TX and TN separately (#40).
            "dtr": period_stat(ds.tasmax - ds.tasmin, freq, "mean", ds.tas),
            "tmm": period_stat(ds.tas, freq, "mean", ds.tasmin, ds.tasmax),
            "txm": period_stat(ds.tasmax, freq, "mean", ds.tasmax),
            "tnm": period_stat(ds.tasmin, freq, "mean", ds.tasmin),
            "prcptot": period_reduce(ds.pr, FREQS[freq], wet_day_total).where(
                valid_mask(ds.pr, freq=FREQS[freq])
            ),
        }
        for name, values in tables.items():
            out[f"indices/{name}_{freq}"] = index_table(name, values, freq)

    sdii = period_reduce(ds.pr, "YS", precipitation_intensity).where(valid_mask(ds.pr, freq="YS"))
    out["indices/sdii_ANN"] = index_table("sdii", sdii, "ANN")
    return out


@product
def degree_days(run: StationRun) -> dict[str, pd.DataFrame]:
    ds, p = run.data, run.params
    # Climpact's climdex.hddheatn, cddcoldn, gddgrown: the annual sum of Tb - TM over days
    # with TM < Tb (heating), or of TM - Tb over days with TM > Tb, with R's
    # extended-precision sum, masked by the annual TM mask.
    specs = {
        f"hddheat{format_number(p.hdd_base)}": (p.hdd_base - ds.tas).where(ds.tas < p.hdd_base),
        f"cddcold{format_number(p.cdd_base)}": (ds.tas - p.cdd_base).where(ds.tas > p.cdd_base),
        f"gddgrow{format_number(p.gdd_base)}": (ds.tas - p.gdd_base).where(ds.tas > p.gdd_base),
    }
    mask = valid_mask(ds.tas, freq=FREQS["ANN"])
    out = {}
    for name, excess in specs.items():
        # A year whose days all fall outside the condition sums to 0 (sum(na.rm = TRUE)).
        values = period_reduce(excess.fillna(0).where(ds.tas.notnull()), FREQS["ANN"], r_sum)
        out[f"indices/{name}_ANN"] = index_table(name, values.where(mask), "ANN")
    return out


# --- extremes with the date they occurred -----------------------------------------


def first_extreme_dates(da: xr.DataArray, rule: str, stat: str) -> xr.DataArray:
    """Date of the first maximum/minimum in each period, skipping missing days
    (R ``which.max`` / ``which.min``).

    A period with no data gets no date (NaT). pandas' ``idxmax`` raises on an all-missing
    group, so missing days are filled with -inf (max) or +inf (min) first: they never win
    in a period that has data, and the first occurrence is unchanged.
    """
    s = da.to_series()
    fill = -np.inf if stat == "max" else np.inf
    grouped = s.fillna(fill).groupby(pd.Grouper(freq=rule))
    idx = grouped.idxmax() if stat == "max" else grouped.idxmin()
    empty = s.groupby(pd.Grouper(freq=rule)).count() == 0
    idx[empty] = pd.NaT
    return xr.DataArray(idx.values, dims="time", coords={"time": idx.index.values})


EXTREMES = {
    "txx": ("tasmax", "max"),
    "tnn": ("tasmin", "min"),
    "tnx": ("tasmin", "max"),
    "txn": ("tasmax", "min"),
    "rx1day": ("pr", "max"),
}


@product
def extremes(run: StationRun) -> dict[str, pd.DataFrame]:
    ds = run.data
    out = {}
    for name, (var, stat) in EXTREMES.items():
        for freq, rule in FREQS.items():
            values = period_stat(ds[var], freq, stat, ds[var])
            dates = first_extreme_dates(ds[var], rule, stat)
            out[f"indices/{name}_{freq}"] = dated_table(values, dates, freq)
    return out


# --- multi-day precipitation maxima (Rx3day, Rx5day) ------------------------------


def running_sum_centred(pr: np.ndarray, ndays: int) -> np.ndarray:
    """climdex.pcic ``running.mean(x, n) * n`` with missing days counted as zero.

    The window is centred (``n // 2`` days before), the series ends are padded with
    zero, and the arithmetic (first sum, then cumulative differences, accumulated in
    extended precision) follows R so that ties between windows resolve the same way.
    """
    x = np.where(np.isnan(pr), 0.0, pr)
    n = x.size
    left = ndays // 2
    right = ndays - left - 1
    increments = np.concatenate([[r_sum(x[:ndays])], x[ndays:] - x[:-ndays]])
    means = r_cumsum(increments) / ndays
    out = np.concatenate([np.zeros(left), means, np.zeros(right)])
    assert out.size == n
    return out


def rxnday(run: StationRun, ndays: int, freq: str) -> pd.DataFrame:
    ds = run.data
    rule = FREQS[freq]
    runsum = xr.DataArray(
        running_sum_centred(ds.pr.values, ndays), dims="time", coords={"time": ds.time}
    )
    p = periods(runsum.time, rule)
    values = p.wrap(p.reduce(runsum.values, "max")) * ndays
    values = values.where(valid_mask(ds.pr, freq=rule))
    dates = first_extreme_dates(runsum, rule, "max")
    return dated_table(values, dates, freq)


@product
def multi_day_precipitation(run: StationRun) -> dict[str, pd.DataFrame]:
    out = {}
    for ndays in sorted({5, run.params.rx_days}):
        for freq in FREQS:
            out[f"indices/rx{ndays}day_{freq}"] = rxnday(run, ndays, freq)
    return out


# --- dry and wet spells (CDD, CWD) -------------------------------------------------


def series_lengths_at_ends(flags: np.ndarray) -> np.ndarray:
    """climdex.pcic ``get.series.lengths.at.ends``: each run of True is replaced by its
    length at its last element, zeros elsewhere."""
    x = flags.astype(bool)
    out = np.zeros(x.size)
    if x.size == 0:
        return out
    prev = np.concatenate([[False], x[:-1]])
    nxt = np.concatenate([x[1:], [False]])
    starts = np.flatnonzero(x & ~prev)
    ends = np.flatnonzero(x & ~nxt)
    out[ends] = ends - starts + 1
    return out


def spell_length_max(run: StationRun, condition: str) -> pd.DataFrame:
    """Annual longest spell with dates (climdex.pcic ``spell.length.max`` with
    ``spells.can.span.years=TRUE`` and ``include.exact.dates=TRUE``).

    Spells crossing a year boundary count towards the year they end in; a year
    entirely inside an unfinished spell is missing. The start and end dates follow R:
    the end is the last day of the longest spell ending within the year, and the start
    is ``end - length`` days, so a spell that began in the previous year has a start
    date in that year.
    """
    ds = run.data
    pr = ds.pr.values
    flags = OPERATORS[condition](pr, 1.0)  # NaN compares False, as R's NA -> FALSE
    nan = np.isnan(pr)
    spells = series_lengths_at_ends(flags)
    years = ds.time.dt.year.values
    mask = valid_mask(ds.pr, freq="YS").values

    rows = []
    for i, year in enumerate(np.unique(years)):
        sel = years == year
        f, s = flags[sel], spells[sel]
        max_spell = float(s.max())
        # R: all(bools) is NA if the year has missing days but no False day
        all_true = bool(f.all()) if not nan[sel].any() else (None if f[~nan[sel]].all() else False)
        if max_spell == 0:
            if all_true is None or all_true:
                max_spell = np.nan
        end = int(np.argmax(series_lengths_at_ends(f))) + 1  # 1-based, first maximum
        duration = max_spell if mask[i] else np.nan
        if np.isnan(duration) or duration == 0:
            start_date = end_date = None
        else:
            origin = pd.Timestamp(year=int(year), month=1, day=1)
            start_date = (origin + pd.Timedelta(days=end - duration)).strftime("%Y-%m-%d")
            end_date = (origin + pd.Timedelta(days=end - 1)).strftime("%Y-%m-%d")
        rows.append((float(year), start_date, duration, end_date))

    df = pd.DataFrame(rows, columns=["time", "start", "duration", "end"])
    df["start"] = df["start"].astype(object)
    df["end"] = df["end"].astype(object)
    return df


@product
def spells(run: StationRun) -> dict[str, pd.DataFrame]:
    return {
        "indices/cdd_ANN": spell_length_max(run, "<"),
        "indices/cwd_ANN": spell_length_max(run, ">="),
    }


# --- precipitation percentile indices ---------------------------------------------


def annual_total_above(pr: xr.DataArray, threshold: float, condition: str) -> xr.DataArray:
    """Annual sum of the days where ``pr <condition> threshold``, skipping missing days
    (climdex.pcic ``total.precip.op.threshold``), with R's extended-precision ``sum``.

    Not masked: the caller applies the annual missing-data mask.
    """
    op = OPERATORS[condition]
    return period_reduce(pr, "YS", lambda x: r_sum(x[op(x, threshold)]))


@product
def precipitation_percentiles(run: StationRun) -> dict[str, pd.DataFrame]:
    """r95p, r99p, r95ptot and r99ptot (Climpact's ``climdex.r95p`` ... ``climdex.r99ptot``
    in ``climpact.etsci-functions.r``).

    rNNp is the annual total on days above the base-period wet-day (>= 1 mm) percentile;
    rNNptot is ``100 * rNNp / prcptot``, with prcptot recomputed in the same way, as R
    does. A year with no wet days gives 0 / 0, which R writes as missing.
    """
    try:
        quantiles = run.thresholds.precipitation
    except InsufficientBaseData:
        return {}
    pr = run.data.pr
    mask = valid_mask(pr, freq="YS")
    prcptot = annual_total_above(pr, 1.0, ">=").where(mask)
    out = {}
    for q in (0.95, 0.99):
        name = f"r{round(q * 100)}p"
        total = annual_total_above(pr, quantiles[q], ">").where(mask)
        with np.errstate(divide="ignore", invalid="ignore"):
            share = 100 * total / prcptot
        out[f"indices/{name}_ANN"] = index_table(name, total, "ANN")
        out[f"indices/{name}tot_ANN"] = index_table(f"{name}tot", share, "ANN")
    return out


# --- temperature percentile indices ------------------------------------------------

MAX_MISSING_DAYS = {"ANN": 15, "MON": 3}  # climdex.pcic max.missing.days


def days_op_threshold(run: StationRun, var: str, q: float, condition: str) -> xr.DataArray:
    """Daily share of thresholds exceeded: Climpact's ``percent.days.op.threshold``
    (``climpact.etsci-functions.r``, which replaces climdex.pcic's) before averaging.

    Outside the base period a day is 1 or 0: ``value <condition> threshold``, with the
    out-of-base threshold for its day of year. Inside the base period it is compared
    with each of the ``years - 1`` bootstrapped thresholds for its year and day, and
    the number of hits is divided by ``years - 1``, the number of comparisons, where
    ``years`` is the length of the base period. A missing threshold counts as not
    exceeded, as in R. A day is missing when every comparison is.

    R divides by ``byrs - 1`` instead, where ``byrs`` is the number of base-period
    years the series covers. That is the same when the series covers the whole base
    period, but gives percentages above 100 when it starts or ends inside it, so it
    is not copied (TECHNICAL.md, "R behaviour not copied").
    """
    th = run.thresholds
    da = run.data[var]
    x = da.values
    time = pd.DatetimeIndex(da.time.values)
    op = OPERATORS[condition]
    thr = th.daily(var, q, time).values
    with np.errstate(invalid="ignore"):
        dat = np.where(np.isnan(x) | np.isnan(thr), np.nan, op(x, thr).astype(float))

    inset = (time >= pd.Timestamp(f"{th.base_start}-01-01")) & (
        time <= pd.Timestamp(f"{th.base_end}-12-31")
    )
    years = time.year.to_numpy()[inset]
    # R skips the bootstrap for series shorter than two years. With one base year,
    # R fails (no years to replace with); the out-of-base thresholds are kept then.
    if inset.any() and time.size >= 360 * 2 and years.max() > years.min():
        doy = day_of_year(time[inset]) - 1
        base_thr = th.inbase(var, q)[doy, years - th.base_start, :]  # (days, years - 1)
        comparisons = base_thr.shape[1]
        xb = x[inset][:, None]
        valid = ~np.isnan(xb) & ~np.isnan(base_thr)
        with np.errstate(invalid="ignore"):
            hits = (op(xb, base_thr) & valid).sum(axis=1)
        dat[inset] = np.where(valid.any(axis=1), hits / comparisons, np.nan)
    return xr.DataArray(dat, dims="time", coords={"time": da.time.values})


def percent_days(dat: xr.DataArray, freq: str, mask: xr.DataArray) -> xr.DataArray:
    """Percentage of days per period: R ``tapply(dat, f, mean, na.rm = TRUE) * 100``,
    missing when more than ``max.missing.days`` days of ``dat`` are, then multiplied
    by the variable's climdex missing-data ``mask``."""
    rule = FREQS[freq]
    p = periods(dat.time, rule)
    n_missing = p.wrap(p.count(np.isnan(dat.values)))
    values = period_reduce(dat, rule, r_mean) * 100
    values = values.where(n_missing <= MAX_MISSING_DAYS[freq])
    return values.where(mask)


# name -> (variable, quantile, condition)
TEMPERATURE_PERCENTILES = {
    "tx90p": ("tasmax", 0.9, ">"),
    "tn90p": ("tasmin", 0.9, ">"),
    "tx10p": ("tasmax", 0.1, "<"),
    "tn10p": ("tasmin", 0.1, "<"),
    "txgt50p": ("tasmax", 0.5, ">"),
}


@product
def temperature_percentiles(run: StationRun) -> dict[str, pd.DataFrame]:
    """tx90p, tn90p, tx10p, tn10p and txgt50p: the percentage of days above (below) the
    base-period percentile for the day of year, bootstrapped inside the base period
    (Climpact's ``climdex.tx90p`` ... ``climdex.txgt50p``)."""
    try:
        run.thresholds  # noqa: B018 - raises when the base period has too little data
    except InsufficientBaseData:
        return {}
    masks = {
        (var, freq): valid_mask(run.data[var], freq=rule)
        for var in ("tasmax", "tasmin")
        for freq, rule in FREQS.items()
    }
    out = {}
    for name, (var, q, condition) in TEMPERATURE_PERCENTILES.items():
        dat = days_op_threshold(run, var, q, condition)
        for freq in FREQS:
            values = percent_days(dat, freq, masks[var, freq])
            out[f"indices/{name}_{freq}"] = index_table(name, values, freq)
    return out


# --- spell-duration indices (wsdi, csdi, wsdi{n}, csdi{n}, tx{n}tn{n}, txb{n}tnb{n}) -----


def r_compare(x: np.ndarray, thr: np.ndarray, condition: str) -> np.ndarray:
    """``x <condition> thr`` as an R logical held in floats: 1, 0, or NaN (R ``NA``)
    where either side is missing."""
    with np.errstate(invalid="ignore"):
        hit = OPERATORS[condition](x, thr).astype(float)
    hit[np.isnan(x) | np.isnan(thr)] = np.nan
    return hit


def r_and(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """R's ``&`` on logicals held as 1/0/NaN: FALSE wins over NA."""
    out = np.where((a == 1) & (b == 1), 1.0, np.nan)
    out[(a == 0) | (b == 0)] = 0.0
    return out


def select_blocks_gt_length(d: np.ndarray, n: int) -> np.ndarray:
    """climdex.pcic ``select.blocks.gt.length(d, n)``: runs of TRUE no longer than ``n``
    become FALSE; ``d`` holds an R logical as 1/0/NaN.

    R quirks kept: with ``n < 1``, ``d`` is returned unchanged, missing values (NA)
    included; with ``n >= length(d)``, everything is FALSE; otherwise NA counts as FALSE.
    """
    if n < 1:
        return d.copy()
    if n >= d.size:
        return np.zeros(d.size)
    flags = d == 1  # NaN -> False
    lengths = series_lengths_at_ends(flags)
    # Spread each run's length (stored at its last day) back over the run.
    run_id = np.cumsum(np.concatenate([[True], flags[1:] != flags[:-1]]))
    run_length = pd.Series(lengths).groupby(run_id).transform("max").to_numpy()
    return (flags & (run_length > n)).astype(float)


def threshold_exceedance_duration(
    x: np.ndarray, thr: np.ndarray, condition: str, min_length: int, years: np.ndarray
) -> np.ndarray:
    """climdex.pcic ``threshold.exceedance.duration.index`` with
    ``spells.can.span.years = FALSE``: per year, the number of days in runs of at least
    ``min_length`` days with ``x <condition> thr``. Spells are cut at year boundaries.

    With ``min_length = 1`` R does not replace missing comparisons with FALSE (see
    :func:`select_blocks_gt_length`), so any year with a missing day is missing.

    No missing-data mask is applied here: R's ``get.na.mask(is.na(x + thr), ...)`` calls
    ``is.na`` a second time on its already-logical input, so its mask is always 1. The
    caller applies the variable's climdex mask.
    """
    hit = r_compare(x, thr, condition)
    totals = [
        float(select_blocks_gt_length(hit[years == y], min_length - 1).sum())
        for y in np.unique(years)
    ]
    return np.asarray(totals)


def dual_threshold_duration(
    x1: np.ndarray,
    x2: np.ndarray,
    thr1: np.ndarray,
    thr2: np.ndarray,
    condition: str,
    n: int,
    years: np.ndarray,
) -> np.ndarray:
    """Climpact's ``dual.threshold.exceedance.duration.index``
    (``climpact.etsci-functions.r``, line 373): per year, the number of events where both
    ``x1 <condition> thr1`` and ``x2 <condition> thr2`` hold on **more than** ``n``
    consecutive days, events separated by 3 days or fewer counting as one.

    As in :func:`threshold_exceedance_duration`, R's own 15-day mask is always 1, so
    no mask is applied here; R then masks with the TX annual mask only.
    """
    both = r_and(r_compare(x1, thr1, condition), r_compare(x2, thr2, condition))
    counts = []
    for y in np.unique(years):
        periods = select_blocks_gt_length(both[years == y], n)
        # Gaps of k = 3 days or fewer (including at the ends of the year) are closed.
        gaps = select_blocks_gt_length(r_not(periods), 3)
        periods = r_not(gaps)
        true = periods == 1
        counts.append(float(np.count_nonzero(true & ~np.concatenate([[False], true[:-1]]))))
    return np.asarray(counts)


def r_not(d: np.ndarray) -> np.ndarray:
    """R's ``!`` on a logical held as 1/0/NaN."""
    return 1.0 - d


def annual_index(name: str, values: np.ndarray, years: np.ndarray, mask: xr.DataArray):
    """Annual index table from per-year ``values``, multiplied by a climdex ``mask``."""
    uniq = np.unique(years)
    time = pd.to_datetime([f"{y}-01-01" for y in uniq])
    da = xr.DataArray(values, dims="time", coords={"time": time})
    return index_table(name, da.where(mask.values), "ANN")


@product
def spell_durations(run: StationRun) -> dict[str, pd.DataFrame]:
    """wsdi, csdi, wsdi{n}, csdi{n} (Climpact's ``climdex.wsdid``/``csdid``,
    climdex.pcic's ``climdex.wsdi``/``csdi``), tx{n}tn{n} and txb{n}tnb{n}
    (``climdex.txdtnd``/``txbdtnbd``).

    All use the out-of-base thresholds only (no in-base bootstrap), and spells cannot
    span years. The dual-threshold indices are masked with the TX annual mask only, as
    in R.
    """
    try:
        th = run.thresholds
    except InsufficientBaseData:
        return {}
    ds, p = run.data, run.params
    time = pd.DatetimeIndex(ds.time.values)
    years = time.year.to_numpy()
    tx, tn = ds.tasmax.values, ds.tasmin.values
    thr = {
        (v, q): th.daily(v, q, time).values
        for v in ("tasmax", "tasmin")
        for q in (0.05, 0.1, 0.9, 0.95)
    }
    masks = {v: valid_mask(ds[v], freq="YS") for v in ("tasmax", "tasmin")}

    out = {}
    for prefix, var, x, q, condition in (
        ("wsdi", "tasmax", tx, 0.9, ">"),
        ("csdi", "tasmin", tn, 0.1, "<"),
    ):
        user_days = p.wsdi_days if prefix == "wsdi" else p.csdi_days
        for name, days in ((prefix, 6), (f"{prefix}{user_days}", user_days)):
            values = threshold_exceedance_duration(x, thr[var, q], condition, days, years)
            out[f"indices/{name}_ANN"] = annual_index(name, values, years, masks[var])

    d = p.txtn_days
    for name, q, condition in ((f"tx{d}tn{d}", 0.95, ">"), (f"txb{d}tnb{d}", 0.05, "<")):
        values = dual_threshold_duration(
            tx, tn, thr["tasmax", q], thr["tasmin", q], condition, d, years
        )
        out[f"indices/{name}_ANN"] = annual_index(name, values, years, masks["tasmax"])
    return out


# --- growing season length (GSL) ---------------------------------------------------

GSL_THRESHOLD = 5.0  # degC (growing.season.length t.thresh)
GSL_MIN_LENGTH = 6  # days (growing.season.length min.length)


def season_length(
    tas: np.ndarray, months: np.ndarray, transition_month: int
) -> tuple[int | None, float, int | None] | None:
    """climdex.pcic ``growing.season.length`` (``gsl.mode = "GSL"``) for one season.

    ``tas`` holds the season's daily mean temperatures in order (a calendar year in the
    north, July to June in the south) and ``months`` their months. Returns
    ``(start, length, end)`` as R computes them: ``start`` is the 1-based day of the
    first day of the first run of at least 6 days with TM > 5 before the first day of
    ``transition_month`` (the run must be at least 6 days long before that day);
    ``end`` is the 0-based day offset R uses for the end date (see
    :func:`growing_season_length`). Missing days count as neither warm nor cold. With
    no start the length is 0 and ``start`` and ``end`` are None. Returns None when the
    season has no day in ``transition_month`` (R's ``NA``).
    """
    mid = np.flatnonzero(months == transition_month)
    if mid.size == 0:
        return None
    ts_mid = int(mid[0]) + 1  # 1-based, as R's which()
    ts_len = tas.size
    n = GSL_MIN_LENGTH - 1
    thresh = np.full(ts_len, GSL_THRESHOLD)
    warm = select_blocks_gt_length(r_compare(tas, thresh, ">")[: ts_mid - 1], n)
    cold = select_blocks_gt_length(r_compare(tas, thresh, "<")[ts_mid - 1 :], n)
    begin = np.flatnonzero(warm == 1)
    finish = np.flatnonzero(cold == 1)
    if begin.size == 0:
        return None, 0.0, None
    start = int(begin[0]) + 1
    if finish.size == 0:
        # R: ``end <- ts.len - 1``, so the end date is the last day of the season.
        return start, float(ts_len - start + 1), ts_len - 1
    # R: ``gs.end`` is the cold run's first day (1-based, within the second half) minus
    # 1, and ``end <- gs.end + ts.mid - 1`` is the 1-based day before the cold run. Used
    # as a 0-based offset for the date, it gives the cold run's first day.
    end = int(finish[0]) + ts_mid - 1
    return start, float(end - start + 1), end


def southern_gsl_mask(tas: np.ndarray, season_years: np.ndarray, months: np.ndarray):
    """``climdex.gsl``'s missing-data mask for Southern Hemisphere seasons (July to
    June): one value, 1 or NaN, per season year in sorted order.

    R applies ``ci@max.missing.days["annual"]`` (15 days) both to the season and to each
    of its months, so a month with 4 to 15 missing days does not make the season
    missing, where the climdex monthly rule allows only 3. The last season is always
    missing.
    """
    missing = pd.Series(np.isnan(tas))
    by_season = missing.groupby(season_years).sum() > 15
    by_month = (missing.groupby([season_years, months]).sum() > 15).groupby(level=0).any()
    mask = np.where(by_season.to_numpy() | by_month.to_numpy(), np.nan, 1.0)
    mask[-1] = np.nan
    return mask


def growing_season_length(run: StationRun) -> pd.DataFrame:
    """Annual growing season length with dates: climdex.pcic ``climdex.gsl`` with
    ``gsl.mode = "GSL"`` and ``include.exact.dates = TRUE``, as Climpact calls it.

    Northern Hemisphere (``lat > 0``) seasons are calendar years; the season ends at the
    first run of 6 days with TM < 5 from 1 July, and is masked with the climdex annual
    TM mask. Southern Hemisphere seasons run from July of the labelled year to June of
    the next and end from 1 January; they are masked by :func:`southern_gsl_mask`.
    January to June of the first year are not used, and the last season is missing.

    Dates follow R: the start is the first day of the warm run, and the end is the
    first day of the cold run when one is found (so ``end - start = length``), or the
    last day of the season when none is (``end - start = length - 1``). A season with
    no start has length 0 and no dates.
    """
    ds = run.data
    tas = ds.tas.values
    dates = pd.DatetimeIndex(ds.time.values)
    years, months = dates.year.to_numpy(), dates.month.to_numpy()
    if run.metadata.northern_hemisphere:
        season_years, transition, origin_month = years, 7, 1
        mask = np.where(valid_mask(ds.tas, freq="YS").values, 1.0, np.nan)
    else:
        # R: years.gsl <- years - floor((12 - months) / 6), keeping years.gsl >= first year.
        season_years = years - (months <= 6)
        inset = season_years >= years[0]
        tas, season_years, months = tas[inset], season_years[inset], months[inset]
        transition, origin_month = 1, 7
        mask = southern_gsl_mask(tas, season_years, months)

    rows = []
    for i, year in enumerate(np.unique(season_years)):
        sel = season_years == year
        result = season_length(tas[sel], months[sel], transition)
        start_date = end_date = None
        if result is None:
            length = np.nan
        else:
            start, length, end = result
            length *= mask[i]
            if start is not None and not np.isnan(length):
                origin = pd.Timestamp(year=int(year), month=origin_month, day=1)
                start_date = (origin + pd.Timedelta(days=start - 1)).strftime("%Y-%m-%d")
                end_date = (origin + pd.Timedelta(days=end)).strftime("%Y-%m-%d")
        rows.append((float(year), start_date, length, end_date))

    df = pd.DataFrame(rows, columns=["time", "start", "sl", "end"])
    df["start"] = df["start"].astype(object)
    df["end"] = df["end"].astype(object)
    return df


@product
def growing_season(run: StationRun) -> dict[str, pd.DataFrame]:
    return {"indices/gsl_ANN": growing_season_length(run)}
