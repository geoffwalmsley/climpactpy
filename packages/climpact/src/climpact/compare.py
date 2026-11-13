"""Compare Climpact output tables against a reference, using tolerance tiers.

The tiers are the ones proposed in the inception report:

- ``EXACT``: counts, extremes and dates. Values must be identical.
- ``CLOSE``: continuous values (means, sums, percentages, anomalies).
  ``|actual - expected| <= rtol * |expected| + atol`` with ``rtol=1e-6``.
- ``FITTED``: statistically fitted values (SPI, SPEI). At least 99% of values
  must be within an absolute difference of 0.01.

In every tier the pattern of missing values must be identical, and string columns
(dates) must match exactly.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum

import numpy as np
import pandas as pd


class Tier(Enum):
    EXACT = "exact"
    CLOSE = "close"
    FITTED = "fitted"


CLOSE_RTOL = 1e-6
CLOSE_ATOL = 1e-9
FITTED_ATOL = 0.01
FITTED_MIN_FRACTION = 0.99


@dataclass
class ColumnResult:
    column: str
    tier: Tier | None
    n_values: int
    n_missing_mismatch: int = 0
    n_value_mismatch: int = 0
    max_abs_diff: float = 0.0
    first_mismatch_row: int | None = None

    @property
    def ok(self) -> bool:
        if self.n_missing_mismatch:
            return False
        if self.tier is Tier.FITTED:
            compared = self.n_values - self.n_missing_mismatch
            return compared == 0 or (compared - self.n_value_mismatch) / compared >= (
                FITTED_MIN_FRACTION
            )
        return self.n_value_mismatch == 0


@dataclass
class Comparison:
    problems: list[str] = field(default_factory=list)
    columns: list[ColumnResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems and all(c.ok for c in self.columns)

    def summary(self) -> str:
        lines = list(self.problems)
        for c in self.columns:
            if c.ok:
                continue
            where = (
                f" (first at row {c.first_mismatch_row})"
                if c.first_mismatch_row is not None
                else ""
            )
            lines.append(
                f"{c.column!r} [{c.tier.value if c.tier else 'string'}]: "
                f"{c.n_missing_mismatch} missing-value mismatches, "
                f"{c.n_value_mismatch}/{c.n_values} values differ, "
                f"max |diff| = {c.max_abs_diff:.3g}{where}"
            )
        return "\n".join(lines) if lines else "tables match"


def _compare_strings(name: str, expected: pd.Series, actual: pd.Series) -> ColumnResult:
    exp = expected.astype(object).where(expected.notna(), None).to_numpy()
    act = actual.astype(object).where(actual.notna(), None).to_numpy()
    exp_missing = np.array([v is None for v in exp])
    act_missing = np.array([v is None for v in act])
    missing_mismatch = exp_missing != act_missing
    both = ~exp_missing & ~act_missing
    value_mismatch = both & np.array([str(a) != str(b) for a, b in zip(act, exp, strict=True)])
    bad = np.flatnonzero(missing_mismatch | value_mismatch)
    return ColumnResult(
        column=name,
        tier=None,
        n_values=len(exp),
        n_missing_mismatch=int(missing_mismatch.sum()),
        n_value_mismatch=int(value_mismatch.sum()),
        first_mismatch_row=int(bad[0]) if bad.size else None,
    )


def _compare_numbers(name: str, expected: pd.Series, actual: pd.Series, tier: Tier) -> ColumnResult:
    exp = expected.to_numpy(dtype=float)
    act = pd.to_numeric(actual, errors="coerce").to_numpy(dtype=float)
    exp_missing = np.isnan(exp)
    act_missing = np.isnan(act)
    missing_mismatch = exp_missing != act_missing
    both = ~exp_missing & ~act_missing
    diff = np.zeros_like(exp)
    diff[both] = np.abs(act[both] - exp[both])

    if tier is Tier.EXACT:
        value_mismatch = both & (diff != 0)
    elif tier is Tier.CLOSE:
        value_mismatch = both & (diff > CLOSE_RTOL * np.abs(exp) + CLOSE_ATOL)
    else:
        value_mismatch = both & (diff > FITTED_ATOL)

    bad = np.flatnonzero(missing_mismatch | value_mismatch)
    return ColumnResult(
        column=name,
        tier=tier,
        n_values=len(exp),
        n_missing_mismatch=int(missing_mismatch.sum()),
        n_value_mismatch=int(value_mismatch.sum()),
        max_abs_diff=float(diff.max()) if diff.size else 0.0,
        first_mismatch_row=int(bad[0]) if bad.size else None,
    )


def compare_tables(
    expected: pd.DataFrame,
    actual: pd.DataFrame,
    tier: Tier,
    column_tiers: Mapping[str, Tier] | None = None,
) -> Comparison:
    """Compare two tables column by column.

    ``tier`` applies to every numeric column unless overridden in ``column_tiers``.
    Columns of strings (dates) in ``expected`` are always compared exactly.
    """
    column_tiers = column_tiers or {}
    result = Comparison()

    if list(actual.columns) != list(expected.columns):
        result.problems.append(
            f"columns differ: expected {list(expected.columns)}, got {list(actual.columns)}"
        )
        return result
    if len(actual) != len(expected):
        result.problems.append(f"row count differs: expected {len(expected)}, got {len(actual)}")
        return result

    expected = expected.reset_index(drop=True)
    actual = actual.reset_index(drop=True)
    for name in expected.columns:
        if expected[name].dtype == object:
            result.columns.append(_compare_strings(name, expected[name], actual[name]))
        else:
            col_tier = column_tiers.get(name, tier)
            result.columns.append(_compare_numbers(name, expected[name], actual[name], col_tier))
    return result
