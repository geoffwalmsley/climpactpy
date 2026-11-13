"""Read station data in the Climpact / RClimDex text format.

The format has six whitespace- or comma-separated columns::

    year  month  day  prcp  tmax  tmin

with ``-99.9`` marking missing values and an optional header row. The behaviour
follows the R code path used by Climpact v3.4.3:

- ``read_user_file``: commas are treated as separators, a header row is skipped when
  the first field is not an integer, and values equal to ``-99.9`` become missing.
- ``create_user_data_ts``: rows whose year/month/day is not a valid date are dropped.
- ``qualityControlCheck``: the rows are merged onto the daily dates from the date of the
  **first row** to the date of the **last row** of the file (:func:`merged_rows`). Rows
  outside that range are dropped (only possible when the file is not in date order),
  days without a row are added as missing, and a date that appears more than once keeps
  every row, in file order. The QC checks run on these rows.
- ``climdexInput.raw``: the merged series is placed on a daily axis running from 1 January
  of the first year to 31 December of the last year; days without data are missing. If a
  date appears more than once, the last row wins.
- ``tavg`` (``tas``) is ``(tmax + tmin) / 2``.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from climpact.config import StationMetadata

MISSING_VALUE = -99.9
COLUMNS = ["year", "month", "day", "prcp", "tmax", "tmin"]

_INTEGER = re.compile(r"^[+-]?\d+$")


def read_station_file(path: str | Path) -> pd.DataFrame:
    """Read a station text file into a DataFrame with a ``date`` column.

    Returns columns ``date``, ``prcp``, ``tmax``, ``tmin`` (floats, NaN for missing),
    in file order, with invalid dates removed.
    """
    lines = [line.replace(",", "\t") for line in Path(path).read_text().splitlines()]
    lines = [line for line in lines if line.strip()]
    if lines and not _INTEGER.match(lines[0].split()[0]):
        lines = lines[1:]

    rows = [line.split() for line in lines]
    for number, row in enumerate(rows, start=1):
        if len(row) != len(COLUMNS):
            raise ValueError(f"{path}: data row {number} has {len(row)} fields, expected 6")

    df = pd.DataFrame(np.array(rows, dtype=float), columns=COLUMNS)
    for column in ("prcp", "tmax", "tmin"):
        df.loc[df[column] == MISSING_VALUE, column] = np.nan

    dates = pd.to_datetime(
        {"year": df["year"], "month": df["month"], "day": df["day"]}, errors="coerce"
    )
    df = df.assign(date=dates).dropna(subset=["date"])
    return df[["date", "prcp", "tmax", "tmin"]].reset_index(drop=True)


def merged_rows(df: pd.DataFrame) -> pd.DataFrame:
    """The rows R's ``qualityControlCheck`` makes from the file (``merge(dffull,
    user_data, by = "dates", all.x = TRUE)``).

    Every date from the first row's date to the last row's date, in date order. A date
    missing from the file gets one row of missing values; a duplicated date keeps all
    its rows, in file order. Rows dated before the first row or after the last row are
    dropped. Returns the columns of :func:`read_station_file`.
    """
    if df.empty:
        raise ValueError("station file contains no valid dates")
    first, last = df["date"].iloc[0], df["date"].iloc[-1]
    if last < first:
        # R's seq(first.date, last.date, "day") fails ("wrong sign in 'by' argument").
        raise ValueError(
            f"the last row of the station file ({last.date()}) is dated before the first "
            f"({first.date()})"
        )
    rows = df[(df["date"] >= first) & (df["date"] <= last)]
    days = pd.date_range(first, last, freq="D")
    absent = days[~days.isin(rows["date"])]
    filler = pd.DataFrame({"date": absent}).reindex(columns=rows.columns)
    merged = pd.concat([rows, filler], ignore_index=True) if len(absent) else rows
    return merged.sort_values("date", kind="stable").reset_index(drop=True)


def station_dataset(df: pd.DataFrame, metadata: StationMetadata) -> xr.Dataset:
    """Place station data on a full-year daily time axis as an xarray Dataset.

    ``df`` is the file's rows (:func:`read_station_file`); they are first merged as R
    does (:func:`merged_rows`). Variables use CF-style names: ``pr`` (mm/d), ``tasmax``,
    ``tasmin`` and ``tas`` (degC), where ``tas = (tasmax + tasmin) / 2``.
    """
    df = merged_rows(df)
    first = df["date"].min().year
    last = df["date"].max().year
    time = pd.date_range(f"{first}-01-01", f"{last}-12-31", freq="D")

    deduplicated = df.drop_duplicates(subset="date", keep="last").set_index("date")
    filled = deduplicated.reindex(time)

    pr = filled["prcp"].to_numpy()
    tasmax = filled["tmax"].to_numpy()
    tasmin = filled["tmin"].to_numpy()
    tas = (tasmax + tasmin) / 2

    def var(values, units, standard_name):
        return xr.DataArray(
            values, dims="time", attrs={"units": units, "standard_name": standard_name}
        )

    return xr.Dataset(
        {
            "pr": var(pr, "mm/d", "precipitation_flux"),
            "tasmax": var(tasmax, "degC", "air_temperature"),
            "tasmin": var(tasmin, "degC", "air_temperature"),
            "tas": var(tas, "degC", "air_temperature"),
        },
        coords={"time": time},
        attrs={
            "station_name": metadata.name,
            "latitude": metadata.latitude,
            "longitude": metadata.longitude,
            "base_period": f"{metadata.base_start}-{metadata.base_end}",
            # First and last dates of the merged series (before padding to whole years); climdex
            # uses them to decide whether the base period has enough data.
            "first_date": str(df["date"].min().date()),
            "last_date": str(df["date"].max().date()),
        },
    )
