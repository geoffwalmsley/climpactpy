"""climdex.pcic missing-data rules.

climdex.pcic (and so Climpact) treats a period's index value as missing when:

- **monthly**: more than 3 days in the month are missing;
- **annual**: more than 15 days in the year are missing, **or** any month of the
  year is missing under the monthly rule.

None of xclim's built-in missing methods implement this, so this module provides it
as plain functions and registers it with xclim as the ``"climdex"`` missing method.
"""

from __future__ import annotations

import numpy as np
import xarray as xr
from xclim.core.missing import MissingBase
from xclim.core.options import register_missing_method

from climpact.periods import RULES, periods

MAX_MISSING_DAYS = {"monthly": 3, "annual": 15}

_FREQ_ALIASES = {
    "MS": "monthly",
    "M": "monthly",
    "ME": "monthly",
    "YS": "annual",
    "YS-JAN": "annual",
    "Y": "annual",
    "YE": "annual",
    "AS": "annual",
    "AS-JAN": "annual",
}


def _period(freq: str) -> str:
    try:
        return _FREQ_ALIASES[freq]
    except KeyError:
        raise ValueError(
            f"climdex missing rules support monthly or annual frequency, got {freq!r}"
        ) from None


def missing_days(valid: xr.DataArray, resample_freq: str) -> xr.DataArray:
    """Number of days without valid data in each period."""
    if valid.ndim == 1 and resample_freq in RULES:
        p = periods(valid.time, resample_freq)
        return p.wrap(p.days() - p.count(valid.values))
    grouped = valid.resample(time=resample_freq)
    return grouped.count() - grouped.sum()


def climdex_missing(valid: xr.DataArray, freq: str) -> xr.DataArray:
    """Boolean mask, True where the period is missing under the climdex rules.

    ``valid`` is a daily boolean array (True where the day has data) on a complete
    daily time axis. ``freq`` is ``"MS"`` (monthly) or ``"YS"`` (annual).
    """
    period = _period(freq)
    if valid.ndim == 1:
        return _climdex_missing_1d(valid, period)
    monthly = missing_days(valid, "MS") > MAX_MISSING_DAYS["monthly"]
    if period == "monthly":
        return monthly
    annual = missing_days(valid, "YS") > MAX_MISSING_DAYS["annual"]
    any_month = monthly.resample(time="YS").any()
    return annual | any_month


def _climdex_missing_1d(valid: xr.DataArray, period: str) -> xr.DataArray:
    """:func:`climdex_missing` for a single series, with :mod:`climpact.periods`."""
    flags = np.asarray(valid.values, dtype=bool)
    months = periods(valid.time, "MS")
    monthly = months.days() - months.count(flags) > MAX_MISSING_DAYS["monthly"]
    if period == "monthly":
        return months.wrap(monthly)
    years = periods(valid.time, "YS")
    annual = years.days() - years.count(flags) > MAX_MISSING_DAYS["annual"]
    # Each month's year is that of its first day, so group the months by their labels.
    any_month = periods(months.labels, "YS").count(monthly) > 0
    return years.wrap(annual | any_month)


def valid_mask(*arrays: xr.DataArray, freq: str) -> xr.DataArray:
    """True for periods that are valid for every input array (climdex ``namask``)."""
    missing = None
    for da in arrays:
        m = climdex_missing(da.notnull(), freq)
        missing = m if missing is None else (missing | m)
    return ~missing


@register_missing_method("climdex")
class MissingClimdex(MissingBase):
    """climdex.pcic rules: month missing if >3 days missing; year missing if >15 days
    missing or any month missing."""

    def __init__(self) -> None:
        super().__init__()

    def is_missing(
        self, valid: xr.DataArray, count: xr.DataArray, freq: str | None
    ) -> xr.DataArray:
        if freq is None:
            raise ValueError("the climdex missing method needs a resampling frequency")
        return climdex_missing(valid, freq)
