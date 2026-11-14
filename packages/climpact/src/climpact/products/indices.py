"""Climpact's day-count, mean, extreme, spell, percentile and growing-season indices.

Missing data follows the climdex.pcic rules (:func:`climpact.missing.valid_mask`).
Index definitions follow ``climpact.etsci-functions.r`` and climdex.pcic 1.2-0; where
the two differ, Climpact's definition is used because it is the one that runs.
Monthly and annual reductions use :mod:`climpact.periods`, not xarray's ``resample``,
for speed.

Each index is computed by an array function (``*_values``) taking daily values whose
last axis runs along a complete daily time axis ``time``, with any leading dimensions:
the station products below call them with one series, and the gridded indices
(:mod:`climpact.gridded.indices`) with the cells of a block. Steps that must follow R's
extended-precision arithmetic (means and sums) or that are sequential by nature
(spells, the growing season) loop over the leading dimensions inside these functions.
"""

from __future__ import annotations

import operator
from collections.abc import Callable

import numpy as np
import pandas as pd
import xarray as xr

from climpact.calendars import as_days
from climpact.missing import valid_mask, valid_periods
from climpact.outputs import product
from climpact.periods import Periods, periods
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


def valid_values(time, rule: str, *arrays: np.ndarray) -> np.ndarray:
    """The climdex validity of each period, ``(..., periods)``: valid for every array
    (``namask`` of each variable multiplied together)."""
    valid = None
    for x in arrays:
        v = valid_periods(~np.isnan(x), time, rule)
        valid = v if valid is None else valid & v
    return valid


def count_values(x: np.ndarray, threshold: float, condition: str, time, rule: str) -> np.ndarray:
    """:func:`count_days` of an array, ``(..., time) -> (..., periods)``."""
    with np.errstate(invalid="ignore"):
        hits = OPERATORS[condition](x, threshold)
    counts = periods(time, rule).count(hits).astype(float)
    return np.where(valid_values(time, rule, x), counts, np.nan)


def count_days(da: xr.DataArray, threshold: float, condition: str, freq: str) -> xr.DataArray:
    """Number of days per period with ``da <condition> threshold`` (missing days do not
    count), masked by the climdex rules for ``da``.

    The same as xclim's ``tn_days_below``, ``tx_days_above``, ``wetdays`` and so on with
    ``check_missing="climdex"``, which compare in the data's units and count with
    ``resample(...).sum()``; done directly because xarray's resampling took most of a
    station run's time (``tests/test_index_helpers.py`` checks the two agree).
    """
    rule = FREQS[freq]
    return periods(da.time, rule).wrap(count_values(da.values, threshold, condition, da.time, rule))


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


# Margin (relative to the mean and the largest value) within which a float32 rounding
# boundary makes :func:`period_means` use R's exact mean: see its docstring.
_FLOAT32_MARGIN = 2.0**-40


def period_means(
    x: np.ndarray, p: Periods, float32: bool = False, scale: float = 1.0
) -> np.ndarray:
    """R's ``mean`` of the non-missing values of each period, times ``scale``,
    ``(..., time) -> (..., periods)`` (NaN for a period with no values).

    With ``float32``, the result is only guaranteed to round to the same float32 as R's
    (the gridded outputs are float32): the mean is the double sum divided by the count,
    vectorised, and :func:`~climpact.rnumerics.r_mean` is used only for periods whose
    result lies within ``2**-40 * scale * (|mean| + max |x|)`` of a float32 rounding
    boundary (a midpoint between two float32 values). Both the double estimate (error
    below ``n * 2**-53 * max |x|``, n <= 366) and R's extended-precision mean (error
    well below ``2**-52 * (|mean| + max |x|)``) are much closer to the exact mean than
    that margin, so outside it both round to the same float32.
    """
    if not float32:
        return p.apply(x, r_mean) * scale
    x = np.asarray(x, dtype=float)
    present = ~np.isnan(x)
    n = p.count(present)
    order, bounds = p.grouping()
    filled = np.diff(bounds) > 0
    starts = bounds[:-1][filled]
    sums = np.zeros(n.shape)
    largest = np.zeros(n.shape)
    values = np.where(present, x, 0.0)[..., order]
    sums[..., filled] = np.add.reduceat(values, starts, axis=-1)
    largest[..., filled] = np.maximum.reduceat(np.abs(values), starts, axis=-1)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = sums / n * scale
    f = out.astype(np.float32)
    with np.errstate(over="ignore"):
        lower = (f.astype(float) + np.nextafter(f, np.float32(-np.inf)).astype(float)) / 2
        upper = (f.astype(float) + np.nextafter(f, np.float32(np.inf)).astype(float)) / 2
    distance = np.minimum(np.abs(out - lower), np.abs(out - upper))
    margin = _FLOAT32_MARGIN * scale * (np.abs(sums / np.maximum(n, 1)) + largest)
    near = (n > 0) & ~(distance > margin)
    if near.any():
        rows = x.reshape(-1, x.shape[-1])
        flat = out.reshape(-1, p.size)
        for r, i in zip(*np.nonzero(near.reshape(-1, p.size)), strict=True):
            period = rows[r, order[bounds[i] : bounds[i + 1]]]
            flat[r, i] = r_mean(period[~np.isnan(period)]) * scale
        out = flat.reshape(out.shape)
    return np.where(n > 0, out, np.nan)


def period_stat_values(
    x: np.ndarray, time, rule: str, stat: str, *masks: np.ndarray, float32: bool = False
) -> np.ndarray:
    """:func:`period_stat` of an array, ``(..., time) -> (..., periods)``; ``float32``:
    see :func:`period_means`."""
    p = periods(time, rule)
    values = period_means(x, p, float32) if stat == "mean" else p.reduce(x, stat)
    return np.where(valid_values(time, rule, *masks), values, np.nan)


def period_stat(da: xr.DataArray, freq: str, stat: str, *mask_vars: xr.DataArray) -> xr.DataArray:
    """Mean, max or min per period, skipping missing days, masked by the climdex rules
    for ``mask_vars``.

    Used instead of xclim for temperature statistics: xclim converts temperatures to
    kelvin internally, and the round trip changes the last bits of most values, so
    extremes would no longer be identical to R.
    """
    rule = FREQS[freq]
    masks = [m.values for m in mask_vars]
    return periods(da.time, rule).wrap(period_stat_values(da.values, da.time, rule, stat, *masks))


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


def means_and_totals_values(
    tasmax: np.ndarray,
    tasmin: np.ndarray,
    tas: np.ndarray,
    pr: np.ndarray,
    time,
    freq: str,
    float32: bool = False,
) -> dict[str, np.ndarray]:
    """dtr, tmm, txm, tnm and prcptot for ``freq`` (``"MON"`` or ``"ANN"``), and sdii for
    ``"ANN"``: ``{name: (..., periods)}``; ``float32``: see :func:`period_means`."""
    rule = FREQS[freq]
    f32 = {"float32": float32}
    out = {
        # climdex.dtr masks with the TM mask (a day is missing if TX or TN is missing),
        # which is stricter than masking TX and TN separately (#40).
        "dtr": period_stat_values(tasmax - tasmin, time, rule, "mean", tas, **f32),
        "tmm": period_stat_values(tas, time, rule, "mean", tasmin, tasmax, **f32),
        "txm": period_stat_values(tasmax, time, rule, "mean", tasmax, **f32),
        "tnm": period_stat_values(tasmin, time, rule, "mean", tasmin, **f32),
    }
    p = periods(time, rule)
    valid = valid_values(time, rule, pr)
    out["prcptot"] = np.where(valid, p.apply(pr, wet_day_total), np.nan)
    if freq == "ANN":
        out["sdii"] = np.where(valid, p.apply(pr, precipitation_intensity), np.nan)
    return out


@product
def means_and_totals(run: StationRun) -> dict[str, pd.DataFrame]:
    ds = run.data
    out = {}
    for freq, rule in FREQS.items():
        p = periods(ds.time, rule)
        values = means_and_totals_values(
            ds.tasmax.values, ds.tasmin.values, ds.tas.values, ds.pr.values, ds.time, freq
        )
        for name, v in values.items():
            out[f"indices/{name}_{freq}"] = index_table(name, p.wrap(v), freq)
    return out


def degree_day_values(tas: np.ndarray, time, params) -> dict[str, np.ndarray]:
    """hddheat, cddcold and gddgrow (named with their base temperatures):
    ``{name: (..., years)}``.

    Climpact's climdex.hddheatn, cddcoldn, gddgrown: the annual sum of Tb - TM over days
    with TM < Tb (heating), or of TM - Tb over days with TM > Tb, with R's
    extended-precision sum, masked by the annual TM mask.
    """
    p = params
    with np.errstate(invalid="ignore"):
        specs = {
            f"hddheat{format_number(p.hdd_base)}": np.where(
                tas < p.hdd_base, p.hdd_base - tas, 0.0
            ),
            f"cddcold{format_number(p.cdd_base)}": np.where(
                tas > p.cdd_base, tas - p.cdd_base, 0.0
            ),
            f"gddgrow{format_number(p.gdd_base)}": np.where(
                tas > p.gdd_base, tas - p.gdd_base, 0.0
            ),
        }
    years = periods(time, "YS")
    valid = valid_values(time, "YS", tas)
    out = {}
    for name, excess in specs.items():
        # A year whose days all fall outside the condition sums to 0 (sum(na.rm = TRUE)).
        excess = np.where(np.isnan(tas), np.nan, excess)
        out[name] = np.where(valid, years.apply(excess, r_sum), np.nan)
    return out


@product
def degree_days(run: StationRun) -> dict[str, pd.DataFrame]:
    ds = run.data
    years = periods(ds.time, "YS")
    return {
        f"indices/{name}_ANN": index_table(name, years.wrap(values), "ANN")
        for name, values in degree_day_values(ds.tas.values, ds.time, run.params).items()
    }


# --- extremes with the date they occurred -----------------------------------------


def first_extreme_dates(da: xr.DataArray, rule: str, stat: str) -> xr.DataArray:
    """Date of the first maximum/minimum in each period, skipping missing days
    (R ``which.max`` / ``which.min``). A period with no data gets no date (NaT)."""
    p = periods(da.time, rule)
    return p.wrap(_dates(da.time, p.first_extreme(da.values, stat)))


EXTREMES = {
    "txx": ("tasmax", "max"),
    "tnn": ("tasmin", "min"),
    "tnx": ("tasmin", "max"),
    "txn": ("tasmax", "min"),
    "rx1day": ("pr", "max"),
}


def extreme_values(x: np.ndarray, time, rule: str, stat: str) -> tuple[np.ndarray, np.ndarray]:
    """Maximum or minimum of each period, masked by the climdex rules for ``x``, and
    the position in ``time`` of its first occurrence (-1 if the period has no data):
    two ``(..., periods)`` arrays."""
    p = periods(time, rule)
    values = np.where(valid_values(time, rule, x), p.reduce(x, stat), np.nan)
    return values, p.first_extreme(x, stat)


def _dates(time, position: np.ndarray) -> np.ndarray:
    """The dates at ``position`` in ``time`` (NaT where it is -1)."""
    index = pd.DatetimeIndex(time.values if isinstance(time, xr.DataArray) else time)
    dates = np.array(index[np.maximum(position, 0)].to_numpy())
    dates[position < 0] = np.datetime64("NaT")
    return dates


@product
def extremes(run: StationRun) -> dict[str, pd.DataFrame]:
    ds = run.data
    time = pd.DatetimeIndex(ds.time.values)
    out = {}
    for name, (var, stat) in EXTREMES.items():
        for freq, rule in FREQS.items():
            p = periods(time, rule)
            values, position = extreme_values(ds[var].values, time, rule, stat)
            out[f"indices/{name}_{freq}"] = dated_table(
                p.wrap(values), p.wrap(_dates(time, position)), freq
            )
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


def running_sums(pr: np.ndarray, ndays: int) -> np.ndarray:
    """:func:`running_sum_centred` of every series (last axis)."""
    pr = np.asarray(pr, dtype=float)
    rows = pr.reshape(-1, pr.shape[-1])
    return np.stack([running_sum_centred(row, ndays) for row in rows]).reshape(pr.shape)


def rxnday_values(
    pr: np.ndarray, time, ndays: int, rule: str, runsum: np.ndarray | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Rx{n}day: the largest centred ``ndays``-day total of each period, masked by the
    climdex rules for ``pr``, and the position of its first occurrence: two
    ``(..., periods)`` arrays. The running sums (``runsum``, :func:`running_sums` if
    not given) follow R's arithmetic one series at a time."""
    if runsum is None:
        runsum = running_sums(pr, ndays)
    p = periods(time, rule)
    values = p.reduce(runsum, "max") * ndays
    values = np.where(valid_values(time, rule, pr), values, np.nan)
    return values, p.first_extreme(runsum, "max")


def rxnday(run: StationRun, ndays: int, freq: str) -> pd.DataFrame:
    ds = run.data
    rule = FREQS[freq]
    time = pd.DatetimeIndex(ds.time.values)
    p = periods(time, rule)
    values, position = rxnday_values(ds.pr.values, time, ndays, rule)
    return dated_table(p.wrap(values), p.wrap(_dates(time, position)), freq)


def rx_days(params) -> list[int]:
    """The Rx{n}day indices computed: Rx5day and the user's Rx{d}day."""
    return sorted({5, params.rx_days})


@product
def multi_day_precipitation(run: StationRun) -> dict[str, pd.DataFrame]:
    out = {}
    for ndays in rx_days(run.params):
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


def spell_length_values(pr: np.ndarray, time, condition: str) -> tuple[np.ndarray, np.ndarray]:
    """Annual longest spell of one series (climdex.pcic ``spell.length.max`` with
    ``spells.can.span.years=TRUE``): ``(durations, ends)`` per year, ``ends`` the 1-based
    day of the year of the spell's last day (see :func:`spell_length_max`)."""
    flags = OPERATORS[condition](pr, 1.0)  # NaN compares False, as R's NA -> FALSE
    nan = np.isnan(pr)
    spells = series_lengths_at_ends(flags)
    years = as_days(time).year.to_numpy()
    mask = valid_periods(~nan, time, "YS")
    durations, ends = [], []
    for i, year in enumerate(np.unique(years)):
        sel = years == year
        f, s = flags[sel], spells[sel]
        max_spell = float(s.max())
        # R: all(bools) is NA if the year has missing days but no False day
        all_true = bool(f.all()) if not nan[sel].any() else (None if f[~nan[sel]].all() else False)
        if max_spell == 0:
            if all_true is None or all_true:
                max_spell = np.nan
        ends.append(int(np.argmax(series_lengths_at_ends(f))) + 1)  # 1-based, first maximum
        durations.append(max_spell if mask[i] else np.nan)
    return np.asarray(durations), np.asarray(ends)


def spell_length_max_values(pr: np.ndarray, time, condition: str) -> np.ndarray:
    """Annual longest spell (cdd for ``"<"``, cwd for ``">="``) of every series,
    ``(..., time) -> (..., years)``."""
    rows = pr.reshape(-1, pr.shape[-1])
    out = np.stack([spell_length_values(row, time, condition)[0] for row in rows])
    return out.reshape(*pr.shape[:-1], out.shape[-1])


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
    time = pd.DatetimeIndex(ds.time.values)
    durations, ends = spell_length_values(ds.pr.values, time, condition)
    rows = []
    for year, duration, end in zip(np.unique(time.year), durations, ends, strict=True):
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
    p = periods(pr.time, "YS")
    return p.wrap(annual_total_values(pr.values, pr.time, threshold, condition))


def annual_total_values(pr: np.ndarray, time, threshold, condition: str) -> np.ndarray:
    """:func:`annual_total_above` of an array, ``(..., time) -> (..., years)``;
    ``threshold`` is a number or an array of the leading dimensions (one per series)."""
    op = OPERATORS[condition]
    years = periods(time, "YS")
    pr = np.asarray(pr, dtype=float)
    thresholds = np.broadcast_to(np.asarray(threshold, dtype=float), pr.shape[:-1]).reshape(-1)
    rows = pr.reshape(-1, pr.shape[-1])
    out = np.stack(
        [
            years.apply(row, lambda x, t=t: r_sum(x[op(x, t)]))
            for row, t in zip(rows, thresholds, strict=True)
        ]
    )
    return out.reshape(*pr.shape[:-1], years.size)


def precipitation_percentile_values(
    pr: np.ndarray, time, quantiles: dict[float, np.ndarray]
) -> dict[str, np.ndarray]:
    """r95p, r99p, r95ptot and r99ptot of every series, ``{name: (..., years)}``;
    ``quantiles[q]`` holds each series' base-period wet-day percentile (a missing
    percentile gives no days above it, so a total of 0)."""
    valid = valid_values(time, "YS", pr)
    prcptot = np.where(valid, annual_total_values(pr, time, 1.0, ">="), np.nan)
    out = {}
    for q in (0.95, 0.99):
        name = f"r{round(q * 100)}p"
        total = np.where(valid, annual_total_values(pr, time, quantiles[q], ">"), np.nan)
        with np.errstate(divide="ignore", invalid="ignore"):
            out[f"{name}tot"] = 100 * total / prcptot
        out[name] = total
    return out


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
    ds = run.data
    values = precipitation_percentile_values(ds.pr.values, ds.time, quantiles)
    p = periods(ds.time, "YS")
    return {
        f"indices/{name}_ANN": index_table(name, p.wrap(values[name]), "ANN")
        for name in ("r95p", "r95ptot", "r99p", "r99ptot")
    }


# --- temperature percentile indices ------------------------------------------------

MAX_MISSING_DAYS = {"ANN": 15, "MON": 3}  # climdex.pcic max.missing.days


def days_op_threshold(run: StationRun, var: str, q: float, condition: str) -> xr.DataArray:
    """Daily share of thresholds exceeded: Climpact's ``percent.days.op.threshold``
    (``climpact.etsci-functions.r``, which replaces climdex.pcic's) before averaging
    (see :func:`days_op_threshold_values`)."""
    th = run.thresholds
    da = run.data[var]
    dat = days_op_threshold_values(
        da.values,
        da.time,
        th.outbase(var, q),
        th.inbase(var, q) if _bootstraps(da.time, th.base_start, th.base_end) else None,
        th.base_start,
        th.base_end,
        condition,
    )
    return xr.DataArray(dat, dims="time", coords={"time": da.time.values})


def _base_days(time, base_start: int, base_end: int) -> np.ndarray:
    years = as_days(time).year.to_numpy()
    return (years >= base_start) & (years <= base_end)


def _bootstraps(time, base_start: int, base_end: int) -> bool:
    """Whether the in-base thresholds are used: R skips the bootstrap for series shorter
    than two years. With one base year, R fails (no years to replace with); the
    out-of-base thresholds are kept then."""
    inset = _base_days(time, base_start, base_end)
    years = as_days(time).year.to_numpy()[inset]
    return bool(inset.any() and len(time) >= 360 * 2 and years.max() > years.min())


def days_op_threshold_values(
    x: np.ndarray,
    time,
    outbase: np.ndarray,
    inbase: np.ndarray | None,
    base_start: int,
    base_end: int,
    condition: str,
) -> np.ndarray:
    """Daily share of thresholds exceeded, for every series: ``x`` is ``(..., time)``,
    ``outbase`` the ``(..., 365)`` out-of-base thresholds and ``inbase`` the
    ``(..., 365, years, years - 1)`` bootstrapped ones (None: not used).

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
    time = as_days(time)
    op = OPERATORS[condition]
    thr = np.asarray(outbase)[..., day_of_year(time) - 1]
    with np.errstate(invalid="ignore"):
        dat = np.where(np.isnan(x) | np.isnan(thr), np.nan, op(x, thr).astype(float))
    if inbase is None:
        return dat
    inset = _base_days(time, base_start, base_end)
    years = time.year.to_numpy()[inset]
    doy = day_of_year(time[inset]) - 1
    base_thr = inbase[..., doy, years - base_start, :]  # (..., days, years - 1)
    comparisons = base_thr.shape[-1]
    xb = x[..., inset][..., None]
    valid = ~np.isnan(xb) & ~np.isnan(base_thr)
    with np.errstate(invalid="ignore"):
        hits = (op(xb, base_thr) & valid).sum(axis=-1)
    dat[..., inset] = np.where(valid.any(axis=-1), hits / comparisons, np.nan)
    return dat


def percent_days(dat: xr.DataArray, freq: str, mask: xr.DataArray) -> xr.DataArray:
    """Percentage of days per period (see :func:`percent_days_values`)."""
    rule = FREQS[freq]
    values = percent_days_values(dat.values, dat.time, freq, mask.values)
    return periods(dat.time, rule).wrap(values)


def percent_days_values(
    dat: np.ndarray, time, freq: str, valid: np.ndarray, float32: bool = False
) -> np.ndarray:
    """Percentage of days per period: R ``tapply(dat, f, mean, na.rm = TRUE) * 100``,
    missing when more than ``max.missing.days`` days of ``dat`` are, then multiplied
    by the variable's climdex missing-data mask (``valid``, ``(..., periods)``);
    ``float32``: see :func:`period_means`."""
    p = periods(time, FREQS[freq])
    n_missing = p.count(np.isnan(dat))
    values = period_means(dat, p, float32, scale=100.0)
    values = np.where(n_missing <= MAX_MISSING_DAYS[freq], values, np.nan)
    return np.where(valid, values, np.nan)


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
    # The length of the run of equal flags each day belongs to.
    starts = np.flatnonzero(np.concatenate([[True], flags[1:] != flags[:-1]]))
    run_length = np.repeat(
        np.diff(np.append(starts, flags.size)), np.diff(np.append(starts, flags.size))
    )
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


def spell_duration_values(
    tasmax: np.ndarray,
    tasmin: np.ndarray,
    time,
    thresholds: dict[tuple[str, float], np.ndarray],
    params,
) -> dict[str, np.ndarray]:
    """wsdi, csdi, wsdi{n}, csdi{n}, tx{n}tn{n} and txb{n}tnb{n} of every series,
    ``{name: (..., years)}``; ``thresholds[var, q]`` holds the ``(..., 365)``
    out-of-base thresholds of TX and TN for q = 0.05, 0.1, 0.9, 0.95. The spells are
    found one series at a time."""
    time = as_days(time)
    years = time.year.to_numpy()
    doy = day_of_year(time) - 1
    masks = {v: valid_values(time, "YS", x) for v, x in (("tasmax", tasmax), ("tasmin", tasmin))}
    lead = tasmax.shape[:-1]
    tx, tn = tasmax.reshape(-1, time.size), tasmin.reshape(-1, time.size)
    thr = {k: np.asarray(v).reshape(-1, np.shape(v)[-1])[:, doy] for k, v in thresholds.items()}
    out = {}
    for prefix, var, x, q, condition in (
        ("wsdi", "tasmax", tx, 0.9, ">"),
        ("csdi", "tasmin", tn, 0.1, "<"),
    ):
        user_days = params.wsdi_days if prefix == "wsdi" else params.csdi_days
        for name, days in ((prefix, 6), (f"{prefix}{user_days}", user_days)):
            values = np.stack(
                [
                    threshold_exceedance_duration(x[i], thr[var, q][i], condition, days, years)
                    for i in range(x.shape[0])
                ]
            )
            out[name] = np.where(masks[var], values.reshape(*lead, -1), np.nan)
    d = params.txtn_days
    for name, q, condition in ((f"tx{d}tn{d}", 0.95, ">"), (f"txb{d}tnb{d}", 0.05, "<")):
        values = np.stack(
            [
                dual_threshold_duration(
                    tx[i], tn[i], thr["tasmax", q][i], thr["tasmin", q][i], condition, d, years
                )
                for i in range(tx.shape[0])
            ]
        )
        out[name] = np.where(masks["tasmax"], values.reshape(*lead, -1), np.nan)
    return out


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
    ds = run.data
    thresholds = {
        (v, q): th.outbase(v, q) for v in ("tasmax", "tasmin") for q in (0.05, 0.1, 0.9, 0.95)
    }
    values = spell_duration_values(
        ds.tasmax.values, ds.tasmin.values, ds.time, thresholds, run.params
    )
    p = periods(ds.time, "YS")
    return {
        f"indices/{name}_ANN": index_table(name, p.wrap(v), "ANN") for name, v in values.items()
    }


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
    rows = gsl_series(
        ds.tas.values, pd.DatetimeIndex(ds.time.values), run.metadata.northern_hemisphere
    )
    df = pd.DataFrame(rows, columns=["time", "start", "sl", "end"])
    df["start"] = df["start"].astype(object)
    df["end"] = df["end"].astype(object)
    return df


def gsl_series(tas: np.ndarray, dates: pd.DatetimeIndex, northern: bool) -> list[tuple]:
    """``(year, start date, length, end date)`` for each season of one series (see
    :func:`growing_season_length`)."""
    years, months = dates.year.to_numpy(), dates.month.to_numpy()
    if northern:
        season_years, transition, origin_month = years, 7, 1
        mask = np.where(valid_periods(~np.isnan(tas), dates, "YS"), 1.0, np.nan)
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
    return rows


def gsl_values(tas: np.ndarray, time, northern: np.ndarray) -> np.ndarray:
    """Growing season length of every series, ``(..., time) -> (..., years)``;
    ``northern`` (the leading dimensions) says which series use the Northern
    Hemisphere season."""
    dates = as_days(time)
    rows = tas.reshape(-1, dates.size)
    north = np.broadcast_to(np.asarray(northern, dtype=bool), tas.shape[:-1]).reshape(-1)
    out = np.stack(
        [
            np.array([r[2] for r in gsl_series(row, dates, bool(n))], dtype=float)
            for row, n in zip(rows, north, strict=True)
        ]
    )
    return out.reshape(*tas.shape[:-1], out.shape[-1])


@product
def growing_season(run: StationRun) -> dict[str, pd.DataFrame]:
    return {"indices/gsl_ANN": growing_season_length(run)}
