"""Shape index results into Climpact's output table layouts."""

from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

STANDARDISED = "standardised values (using all years)"

# Climpact output frequency suffix -> pandas resampling frequency.
FREQS = {"ANN": "YS", "MON": "MS"}


def period_labels(time: xr.DataArray | pd.DatetimeIndex, freq: str) -> pd.Series:
    """Climpact ``time`` column values: year as a float for ANN, ``"YYYY-MM"`` for MON."""
    index = pd.DatetimeIndex(time.values if isinstance(time, xr.DataArray) else time)
    if freq == "ANN":
        return pd.Series(index.year.astype(float))
    return pd.Series(index.strftime("%Y-%m"), dtype=object)


def standardise(values: np.ndarray) -> np.ndarray:
    """``(x - mean) / sd`` over all non-missing periods, as R ``write.index.csv`` does.

    Uses the sample standard deviation (``ddof=1``). Constant or single-value series
    give missing values, like R's ``0/0``.
    """
    values = np.asarray(values, dtype=float)
    valid = values[~np.isnan(values)]
    if valid.size < 2:
        return np.full(values.shape, np.nan)
    sd = valid.std(ddof=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = (values - valid.mean()) / sd
    out[~np.isfinite(out)] = np.nan
    return out


def index_table(name: str, values: xr.DataArray, freq: str) -> pd.DataFrame:
    """Standard index table: ``time``, ``<name>``, standardised anomaly."""
    v = values.values.astype(float)
    return pd.DataFrame(
        {"time": period_labels(values.time, freq), name: v, STANDARDISED: standardise(v)}
    )


def dated_table(values: xr.DataArray, dates: xr.DataArray, freq: str) -> pd.DataFrame:
    """Index table with the date of occurrence: ``time``, ``val``, ``ymd``."""
    v = values.values.astype(float)
    ymd = pd.Series(pd.DatetimeIndex(dates.values).strftime("%Y-%m-%d"), dtype=object)
    ymd[np.isnan(v)] = None
    return pd.DataFrame({"time": period_labels(values.time, freq), "val": v, "ymd": ymd})


def format_number(value: float) -> str:
    """Format a user parameter as R's ``paste`` would (``30`` not ``30.0``)."""
    return str(int(value)) if float(value).is_integer() else str(value)
