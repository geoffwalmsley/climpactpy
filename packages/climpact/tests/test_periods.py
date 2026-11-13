"""climpact.periods gives the same periods and results as xarray's resample."""

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from climpact.missing import climdex_missing
from climpact.periods import periods
from climpact.rnumerics import r_mean

SPANS = [
    ("1936-01-01", "2015-12-31"),  # whole years
    ("1961-03-05", "1999-07-09"),  # partial first and last years and months
    ("1899-12-31", "1901-01-01"),  # one day in the first and last years
    ("2000-02-10", "2000-02-20"),  # inside one month
]


def daily(start: str, end: str, seed: int = 0, gaps: float = 0.2) -> xr.DataArray:
    time = pd.date_range(start, end, freq="D")
    rng = np.random.default_rng(seed)
    values = np.round(rng.normal(15, 8, time.size), 1)
    values[rng.random(time.size) < gaps] = np.nan
    return xr.DataArray(values, dims="time", coords={"time": time})


@pytest.mark.parametrize("rule", ["MS", "YS"])
@pytest.mark.parametrize("span", SPANS)
def test_matches_xarray_resample(span, rule):
    da = daily(*span)
    p = periods(da.time, rule)
    resampled = da.resample(time=rule)
    expected = resampled.max()
    assert p.labels.equals(pd.DatetimeIndex(expected.time.values))
    assert p.labels.dtype == expected.time.dtype
    for stat in ("max", "min"):
        np.testing.assert_array_equal(p.reduce(da.values, stat), getattr(resampled, stat)().values)
    np.testing.assert_array_equal(p.count(da.notnull().values), resampled.count().values)
    np.testing.assert_array_equal(p.days(), da.fillna(0).resample(time=rule).count().values)


@pytest.mark.parametrize("rule", ["MS", "YS"])
def test_apply_matches_pandas_resample_apply(rule):
    da = daily("1990-01-01", "1995-12-31", gaps=0.5)
    da[40:80] = np.nan  # a month with no data
    expected = (
        da.to_series()
        .resample(rule)
        .apply(lambda g: r_mean(g.dropna().to_numpy()) if g.notna().any() else np.nan)
    )
    np.testing.assert_array_equal(periods(da.time, rule).apply(da.values, r_mean), expected)


def test_empty_periods_in_a_gappy_time_axis():
    time = pd.DatetimeIndex(["2001-01-05", "2001-04-02", "2001-04-03"])
    p = periods(time, "MS")
    assert p.labels.strftime("%Y-%m").tolist() == ["2001-01", "2001-02", "2001-03", "2001-04"]
    assert p.days().tolist() == [1, 0, 0, 2]
    assert np.isnan(p.reduce(np.array([1.0, 2.0, 3.0]), "max")[1])
    assert np.isnan(p.apply(np.array([1.0, 2.0, 3.0]), np.sum)[2])


def test_unsupported_rule():
    with pytest.raises(ValueError):
        periods(pd.date_range("2001-01-01", periods=3), "W")


@pytest.mark.parametrize("freq", ["MS", "YS"])
@pytest.mark.parametrize("seed", range(5))
def test_climdex_missing_single_series_matches_resample_version(freq, seed):
    """The 1-D fast path of climdex_missing gives the same mask as the xarray path used
    for arrays with more dimensions."""
    rng = np.random.default_rng(seed)
    da = daily("1961-01-01", "1990-12-31", seed=seed, gaps=0.0)
    # Runs of missing days of random length, so months have 0 to ~10 missing days.
    for start in rng.integers(0, da.size, 80):
        da[start : start + rng.integers(1, 6)] = np.nan
    fast = climdex_missing(da.notnull(), freq)
    generic = climdex_missing(da.notnull().expand_dims(station=1), freq).isel(station=0)
    assert fast.values.any() and not fast.values.all()
    np.testing.assert_array_equal(fast.values, generic.values)
    np.testing.assert_array_equal(fast.time.values, generic.time.values)
