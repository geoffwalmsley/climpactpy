"""Read and write Climpact (R) output CSV files.

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

import math
import re
from dataclasses import dataclass, field
from fractions import Fraction
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


# --- writing ----------------------------------------------------------------------

# x87 long double significand, used by R's number formatting.
EXTENDED_BITS = 64

# Significant digits R's write.table and as.character use for doubles (DBL_DIG).
R_DIGITS = 15

METADATA_KEYS = (
    "Description",
    "Station",
    "Latitude",
    "Longitude",
    "Base_period",
    "Climpact_version",
    "Date_of_calculation",
)


def _round_extended(q: Fraction) -> Fraction:
    """Round a positive rational to the x87 extended format (64-bit significand)."""
    e = q.numerator.bit_length() - q.denominator.bit_length()
    if Fraction(2) ** e > q:
        e -= 1
    shift = EXTENDED_BITS - 1 - e  # scale so the significand is a 64-bit integer
    scaled = q * Fraction(2) ** shift
    n = round(scaled)  # Fraction rounding is half to even
    return Fraction(n) / Fraction(2) ** shift


def _r_scientific(r: float, digits: int) -> tuple[int, int, bool]:
    """R ``scientific()`` (``src/main/format.c``) for ``r > 0``: ``(kpower, nsig,
    roundingwidens)``.

    R scales ``r`` by a power of ten in long double, rounds to a ``digits``-digit
    integer and counts its trailing zeros. A value just below a rounding boundary can
    therefore be given fewer significant digits than correct rounding would, and is
    then printed rounded to that many digits.
    """
    kp = math.floor(math.log10(r)) - digits + 1
    r_prec = _round_extended(Fraction(r) / Fraction(10) ** kp)
    if r_prec < 10 ** (digits - 1):
        r_prec = _round_extended(r_prec * 10)
        kp -= 1
    alpha = round(r_prec)  # nearbyintl: half to even; at most 10**digits, exact as double
    nsig = digits
    for _ in range(digits):
        if alpha % 10:
            break
        alpha //= 10
        nsig -= 1
    if nsig == 0:
        nsig = 1
        kp += 1
    kpower = kp + digits - 1
    rgt = min(max(digits - kpower, 0), 27)
    fuzz = 0.5 / 10.0**rgt
    widens = 0 < kpower <= 27 and Fraction(r) < Fraction(10) ** kpower - Fraction(fuzz)
    return kpower, nsig, widens


def format_r_number(value: float, digits: int = R_DIGITS) -> str:
    """Format a double exactly as R's ``write.table`` and ``as.character`` do.

    Reproduces ``formatReal`` for a single value: the number of significant digits
    (at most ``digits``) comes from R's ``scientific()``, and fixed notation is used
    unless scientific notation is narrower (``scipen = 0``). Missing values are written
    as :data:`MISSING_TOKEN`.
    """
    x = float(value)
    if math.isnan(x):
        return MISSING_TOKEN
    if math.isinf(x):
        return "Inf" if x > 0 else "-Inf"
    if x == 0:
        return "0"
    neg = int(x < 0)
    kpower, nsig, widens = _r_scientific(abs(x), digits)
    left = kpower + 1 - widens
    rgt = max(nsig - left, 0)
    fixed_width = neg + max(left, 1) + rgt + (rgt != 0)
    exp_digits = 2 if (left > 100 or left <= -99) else 1
    sci_width = neg + (nsig > 1) + (nsig - 1) + 4 + exp_digits
    if fixed_width <= sci_width:
        return f"{x:.{rgt}f}"
    return f"{x:.{nsig - 1}e}"


def _format_value(value, na: str = MISSING_TOKEN) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return na
    if isinstance(value, str):
        return value
    if isinstance(value, bool | np.bool_):
        return "TRUE" if value else "FALSE"
    return format_r_number(value)


def _quote(text: str) -> str:
    """Quote a field as R ``write.table(quote = TRUE)`` does (``qmethod = "escape"``)."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def climpact_header(metadata: dict[str, str]) -> list[str]:
    """The quoted metadata lines R's ``write_header`` puts at the top of every file."""
    missing = [key for key in METADATA_KEYS if key not in metadata]
    if missing:
        raise ValueError(f"missing metadata: {', '.join(missing)}")
    return [f"{_quote(key + ': ')},{_quote(str(metadata[key]))}" for key in METADATA_KEYS]


def write_climpact_csv(
    path: str | Path,
    data: pd.DataFrame,
    metadata: dict[str, str] | None,
    sep: str = ", ",
    na: str = MISSING_TOKEN,
) -> Path:
    """Write a table as a Climpact output CSV, the inverse of :func:`read_climpact_csv`.

    ``metadata`` holds the header values (see :data:`METADATA_KEYS`). Numbers are
    formatted as R's ``write.table`` does (:func:`format_r_number`), missing values
    (NaN or None) as ``-99.9``, and the header row and data rows are unquoted and
    joined with ``sep``: ``", "`` for index files, ``","`` for ``nastatistics``.

    ``metadata=None`` writes no header block and ``na`` changes the missing-value token,
    for files R writes with a plain ``write.table`` (``thres.csv``: no header, ``NA``).
    """
    lines = climpact_header(metadata) if metadata is not None else []
    lines.append(sep.join(str(name) for name in data.columns))
    columns = [[_format_value(v, na) for v in data[name].tolist()] for name in data.columns]
    lines.extend(sep.join(row) for row in zip(*columns, strict=True))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return path
