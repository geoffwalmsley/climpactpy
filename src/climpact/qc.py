"""Climpact's per-value quality-control checks (``allqc`` in
``services/quality_control_checks.R``, the checks in ``services/check/``).

Each check takes the rows R's QC step works on (:func:`climpact.io.station.merged_rows`:
one row per day from the first to the last row of the file, every row of a duplicated
date kept, in file order) and returns the table R writes, with R's columns. The checks
only report: nothing here changes the data the indices are calculated from.

R writes the rows to a temporary file with missing values as ``-99.9`` and each check
reads it back with ``na.strings = "-99.9"``; since ``-99.9`` already means missing in
the input, the checks see the same missing values as the indices.

R quirks reproduced:

- ``tmaxmin`` lists TN >= TX, not only TN > TX (``tx - tn <= 0``).
- ``jumps_tx``/``jumps_tn`` and ``flatline_tx``/``flatline_tn`` work on the absolute
  day-to-day change rounded to one decimal with R's ``round`` (:func:`r_round`), run-length
  encoded (``rle``). A run of equal changes is reported once, on the date of the run's
  last change: the first of the two days it compares. A missing value breaks a run.
- ``jumps_tx`` reports the rounded change in its ``TX`` column, while ``jumps_tn``
  reports the TN value of the date (column-selection slips in R).
- ``jumps_*`` keep changes ``>=`` the threshold, though the description says ``>``;
  ``flatline_*`` keep runs of at least ``flatline_days`` zero changes, i.e. more than
  ``flatline_days`` equal values, reported with that number of values.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from climpact.config import QCParams
from climpact.rnumerics import r_round


def r_dates(dates: pd.Series) -> pd.Series:
    """Dates as R's ``paste(year, month, day, sep = "-")``: ``1961-1-3``."""
    d = pd.DatetimeIndex(dates)
    return pd.Series(
        [f"{y}-{m}-{dd}" for y, m, dd in zip(d.year, d.month, d.day, strict=True)],
        dtype=object,
    )


def _runs(values: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """R ``rle`` on doubles, without the runs of missing values.

    Returns the index of the last element of each run, its length and its value. Each
    missing value is a run of its own (``NA != x`` is ``NA``), so it breaks runs.
    """
    n = len(values)
    if n == 0:
        empty = np.array([], dtype=int)
        return empty, empty, np.array([], dtype=float)
    same = values[1:] == values[:-1]  # False where either is missing
    ends = np.append(np.flatnonzero(~same), n - 1)
    lengths = np.diff(np.concatenate([[-1], ends]))
    run_values = values[ends]
    keep = ~np.isnan(run_values)
    return ends[keep], lengths[keep], run_values[keep]


def _changes(values: pd.Series) -> np.ndarray:
    """``abs(round(diff(x), digits = 1))``."""
    return np.abs(r_round(np.diff(values.to_numpy(dtype=float)), 1))


def duplicate_dates(rows: pd.DataFrame) -> pd.DataFrame:
    """``duplivals``: each repeat of a date (a date given three times is listed twice)."""
    repeats = rows.loc[rows["date"].duplicated(), "date"]
    return pd.DataFrame({"Dates_duplicated": r_dates(repeats)})


def _rows_table(rows: pd.DataFrame, mask: np.ndarray) -> pd.DataFrame:
    hits = rows[mask]
    return pd.DataFrame(
        {
            "Date": r_dates(hits["date"]),
            "Prec": hits["prcp"].to_numpy(dtype=float),
            "TX": hits["tmax"].to_numpy(dtype=float),
            "TN": hits["tmin"].to_numpy(dtype=float),
        }
    )


def tmax_le_tmin(rows: pd.DataFrame) -> pd.DataFrame:
    """``tmaxmin``: days with TX - TN <= 0 (both present)."""
    with np.errstate(invalid="ignore"):
        mask = (rows["tmax"] - rows["tmin"]).to_numpy() <= 0
    return _rows_table(rows, mask)


def too_large(rows: pd.DataFrame, params: QCParams) -> pd.DataFrame:
    """``humongous``: precipitation above ``prec_max`` or below 0, or a temperature with
    absolute value above ``temp_max``. A missing value does not hide the others."""
    tx, tn, pc = (rows[c].to_numpy(dtype=float) for c in ("tmax", "tmin", "prcp"))
    t = params.temp_max
    with np.errstate(invalid="ignore"):
        mask = (tx > t) | (tx < -t) | (tn > t) | (tn < -t) | (pc > params.prec_max) | (pc < 0)
    return _rows_table(rows, mask)


def jumps(rows: pd.DataFrame, variable: str, params: QCParams) -> pd.DataFrame:
    """``jumps_tx`` (``variable="tmax"``) and ``jumps_tn`` (``"tmin"``): rounded
    day-to-day changes of at least ``params.jump`` degrees.

    TX reports the change and TN the value on the date (see the module docstring)."""
    values = rows[variable]
    ends, _, change = _runs(_changes(values))
    keep = change >= params.jump
    at = ends[keep]
    label = "TX" if variable == "tmax" else "TN"
    reported = change[keep] if variable == "tmax" else values.to_numpy(dtype=float)[at]
    return pd.DataFrame({"Date": r_dates(rows["date"].iloc[at]), label: reported})


def flatline(rows: pd.DataFrame, variable: str, params: QCParams) -> pd.DataFrame:
    """``flatline_tx`` and ``flatline_tn``: runs of at least ``params.flatline_days``
    zero (rounded) day-to-day changes, reported on the second-last day of the run with
    the value and the number of equal values."""
    values = rows[variable]
    ends, lengths, change = _runs(_changes(values))
    keep = (change == 0) & (lengths >= params.flatline_days)
    at = ends[keep]
    label = "TX" if variable == "tmax" else "TN"
    return pd.DataFrame(
        {
            "Date": r_dates(rows["date"].iloc[at]),
            label: values.to_numpy(dtype=float)[at],
            "Number of duplicates": (lengths[keep] + 1).astype(float),
        }
    )
