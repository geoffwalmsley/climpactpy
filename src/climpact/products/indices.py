"""Climpact indices that map directly onto xclim, plus the date-of-occurrence and
spell indices whose R definitions need a direct port.

Missing data follows the climdex.pcic rules (``check_missing="climdex"``, see
:mod:`climpact.missing`). Index definitions follow ``climpact.etsci-functions.r``
and climdex.pcic 1.2-0; where the two differ, Climpact's definition is used because
it is the one that runs.
"""

from __future__ import annotations

import operator
from collections.abc import Callable

import numpy as np
import pandas as pd
import xarray as xr
import xclim
from xclim.indicators import atmos

from climpact.missing import valid_mask
from climpact.outputs import product
from climpact.products.tables import FREQS, dated_table, format_number, index_table
from climpact.rnumerics import r_cumsum, r_mean, r_sum
from climpact.station import StationRun

OPERATORS: dict[str, Callable] = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
}


def run_xclim(indicator, freq: str, **kwargs) -> xr.DataArray:
    """Run an xclim indicator with the climdex missing-data rules."""
    with xclim.set_options(
        check_missing="climdex",
        as_dataset=False,
        cf_compliance="log",
        data_validation="log",
    ):
        return indicator(freq=FREQS[freq], **kwargs)


# --- threshold counts -------------------------------------------------------------

# name -> (xclim indicator, input variable, threshold, condition)
COUNTS: dict[str, tuple] = {
    "fd": (atmos.tn_days_below, "tasmin", "0 degC", "<"),
    "tnlt2": (atmos.tn_days_below, "tasmin", "2 degC", "<"),
    "tnltm2": (atmos.tn_days_below, "tasmin", "-2 degC", "<"),
    "tnltm20": (atmos.tn_days_below, "tasmin", "-20 degC", "<"),
    "id": (atmos.tx_days_below, "tasmax", "0 degC", "<"),
    "su": (atmos.tx_days_above, "tasmax", "25 degC", ">"),
    "tr": (atmos.tn_days_above, "tasmin", "20 degC", ">"),
    "txge30": (atmos.tx_days_above, "tasmax", "30 degC", ">="),
    "txge35": (atmos.tx_days_above, "tasmax", "35 degC", ">="),
    "tmge5": (atmos.tg_days_above, "tas", "5 degC", ">="),
    "tmge10": (atmos.tg_days_above, "tas", "10 degC", ">="),
    "tmlt5": (atmos.tg_days_below, "tas", "5 degC", "<"),
    "tmlt10": (atmos.tg_days_below, "tas", "10 degC", "<"),
    "r10mm": (atmos.wetdays, "pr", "10 mm/d", ">="),
    "r20mm": (atmos.wetdays, "pr", "20 mm/d", ">="),
}


def count_days(run: StationRun, indicator, var: str, thresh: str, condition: str, freq: str):
    ds = run.data
    return run_xclim(indicator, freq, **{var: ds[var]}, thresh=thresh, condition=condition)


@product
def threshold_counts(run: StationRun) -> dict[str, pd.DataFrame]:
    p = run.params
    counts = dict(COUNTS)
    counts[f"r{format_number(p.rnnmm)}mm"] = (atmos.wetdays, "pr", f"{p.rnnmm} mm/d", ">=")
    out = {}
    for name, (indicator, var, thresh, condition) in counts.items():
        for freq in FREQS:
            values = count_days(run, indicator, var, thresh, condition, freq)
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
        counts = hits.resample(time=rule).sum().astype(float)
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
        values = getattr(da.resample(time=rule), stat)(skipna=True)
    return values.where(valid_mask(*mask_vars, freq=rule))


def period_reduce(da: xr.DataArray, rule: str, func: Callable) -> xr.DataArray:
    """Apply ``func`` to the non-missing values of each period (NaN if there are none).

    Used with the R-precision :func:`~climpact.rnumerics.r_mean` so that means are
    identical to R's, whose ``mean`` accumulates in extended precision.
    """
    series = (
        da.to_series()
        .resample(rule)
        .apply(lambda g: func(g.dropna().to_numpy()) if g.notna().any() else np.nan)
    )
    return xr.DataArray(series.to_numpy(dtype=float), dims="time", coords={"time": series.index})


def precipitation_intensity(pr: np.ndarray) -> float:
    """climdex.pcic ``simple.precipitation.intensity``: wet-day total / wet days (0 if
    there are none), with R's extended-precision ``sum``."""
    wet = pr[pr >= 1]
    return r_sum(wet) / wet.size if wet.size else 0.0


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
            "prcptot": run_xclim(atmos.wet_precip_accumulation, freq, pr=ds.pr, thresh="1 mm/d"),
        }
        for name, values in tables.items():
            out[f"indices/{name}_{freq}"] = index_table(name, values, freq)

    sdii = period_reduce(ds.pr, "YS", precipitation_intensity).where(valid_mask(ds.pr, freq="YS"))
    out["indices/sdii_ANN"] = index_table("sdii", sdii, "ANN")
    return out


@product
def degree_days(run: StationRun) -> dict[str, pd.DataFrame]:
    ds, p = run.data, run.params
    specs = {
        f"hddheat{format_number(p.hdd_base)}": (atmos.heating_degree_days, p.hdd_base),
        f"cddcold{format_number(p.cdd_base)}": (atmos.cooling_degree_days, p.cdd_base),
        f"gddgrow{format_number(p.gdd_base)}": (atmos.growing_degree_days, p.gdd_base),
    }
    out = {}
    for name, (indicator, base) in specs.items():
        values = run_xclim(indicator, "ANN", tas=ds.tas, thresh=f"{base} degC")
        out[f"indices/{name}_ANN"] = index_table(name, values, "ANN")
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
    values = runsum.resample(time=rule).max() * ndays
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
