"""The thresholds file and tx95t, built from the base-period thresholds."""

from __future__ import annotations

import numpy as np
import pandas as pd

from climpact.outputs import product
from climpact.products.tables import STANDARDISED, standardise
from climpact.station import StationRun
from climpact.thresholds import (
    DAYS_PER_YEAR,
    HEATWAVE_QUANTILE,
    InsufficientBaseData,
    quantile_name,
)

# thres.csv column prefix for each variable, in R's column order
_THRES_VARIABLES = {"tasmax": "tmax", "tasmin": "tmin", "tas": "tavg"}
_HEATWAVE_COLUMNS = {"HW_TN90": "tasmin", "HW_TX90": "tasmax", "HW_TAVG90": "tas"}


@product
def thresholds_file(run: StationRun) -> dict[str, pd.DataFrame]:
    """``thres/thres``: one row per day of year (R ``quality_control_checks.R``).

    Precipitation thresholds are single numbers, repeated on every row as R's
    ``as.data.frame`` does.
    """
    try:
        t = run.thresholds
    except InsufficientBaseData:
        return {}
    columns: dict[str, np.ndarray] = {}
    for var, prefix in _THRES_VARIABLES.items():
        for q, values in t.temperature[var].items():
            columns[f"{prefix}_{quantile_name(q)}"] = values
    for q, value in t.precipitation.items():
        columns[f"prec_{quantile_name(q)}"] = np.full(DAYS_PER_YEAR, value)
    assert HEATWAVE_QUANTILE == 0.9  # the column names say 90
    for name, var in _HEATWAVE_COLUMNS.items():
        columns[name] = t.heatwave[var]
    return {"thres/thres": pd.DataFrame(columns)}


@product
def tx95t(run: StationRun) -> dict[str, pd.DataFrame]:
    """``indices/tx95t_DAY``: the base-period 95th percentile of TX for each day of year.

    R writes the row names of an unnamed vector as the ``time`` column, so every
    ``time`` is missing (``-99.9`` in the file); this is reproduced.
    """
    try:
        values = run.thresholds.outbase("tasmax", 0.95)
    except InsufficientBaseData:
        return {}
    return {
        "indices/tx95t_DAY": pd.DataFrame(
            {
                "time": np.full(DAYS_PER_YEAR, np.nan),
                "tx95t": values,
                STANDARDISED: standardise(values),
            }
        )
    }
