"""Read Climpact (R) output CSV files.

Climpact writes its index, threshold and trend outputs as CSV files with a block of
quoted metadata lines followed by a header row and data rows, for example::

    "Description: ","Annual number of days when TN < 0 degrees_C"
    "Station: ","sydney_observatory_hill_1936-2015"
    "Latitude: ","0"
    "Longitude: ","0"
    "Base_period: ","1971-2000"
    "Climpact_version: ","3.4.3"
    "Date_of_calculation: ","2026-11-12"
    time, fd, standardised values (using all years)
    1936, 0, -99.9

Missing values are written as ``-99.9``. Columns holding dates (``ymd``, ``start``,
``end``, ``date``) are kept as strings; all other columns are parsed as floats.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

MISSING_VALUE = -99.9
MISSING_TOKEN = "-99.9"

_METADATA_LINE = re.compile(r'^"(?P<key>[A-Za-z_]+): ","(?P<value>.*)"$')


@dataclass
class ClimpactTable:
    """Contents of one Climpact output CSV file."""

    data: pd.DataFrame
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def columns(self) -> list[str]:
        return list(self.data.columns)


def _parse_column(values: list[str]) -> pd.Series:
    """Parse a column as floats if every entry is numeric, otherwise as strings."""
    try:
        numbers = np.array([float(v) for v in values], dtype=float)
    except ValueError:
        return pd.Series([None if v == MISSING_TOKEN else v for v in values], dtype=object)
    numbers[numbers == MISSING_VALUE] = np.nan
    return pd.Series(numbers, dtype=float)


def read_climpact_csv(path: str | Path) -> ClimpactTable:
    """Read a Climpact output CSV (indices, thresholds or trends).

    Metadata lines are returned separately from the data. Leading and trailing
    whitespace around fields is stripped, so both ``", "`` and ``","`` separators work.
    """
    lines = Path(path).read_text().splitlines()

    metadata: dict[str, str] = {}
    start = 0
    while start < len(lines) and (match := _METADATA_LINE.match(lines[start])):
        metadata[match["key"]] = match["value"]
        start += 1

    header = [name.strip() for name in lines[start].split(",")]
    rows = [[v.strip() for v in line.split(",")] for line in lines[start + 1 :] if line.strip()]
    for number, row in enumerate(rows, start=start + 2):
        if len(row) != len(header):
            raise ValueError(f"{path}:{number}: expected {len(header)} fields, got {len(row)}")

    columns = {name: _parse_column([row[i] for row in rows]) for i, name in enumerate(header)}
    return ClimpactTable(data=pd.DataFrame(columns), metadata=metadata)
