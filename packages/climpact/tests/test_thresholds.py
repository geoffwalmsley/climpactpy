from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from climpact.config import StationMetadata
from climpact.io.station import station_dataset
from climpact.thresholds import (
    DAYS_PER_YEAR,
    InsufficientBaseData,
    base_period_matrix,
    climdex_quantile,
    compute_thresholds,
    day_of_year,
    quantile_name,
    r_quantile_type8,
    running_quantiles,
    window_values,
)

# --- quantile definitions ---------------------------------------------------------


DATA = Path(__file__).parent / "data"
QS = (0.05, 0.1, 0.5, 0.9, 0.95, 0.99)


def _r_cases():
    lines = [x for x in (DATA / "r_quantiles.txt").read_text().splitlines() if x[0] != "#"]
    for values, results in zip(lines[::2], lines[1::2], strict=True):
        r = [float(v) for v in results.split()]
        yield np.array([float(v) for v in values.split()]), r[:6], r[6:]


def test_quantiles_bit_identical_to_r():
    """Random, heavily tied and skewed samples, against values printed by R itself
    (climdex.quantile and quantile(type = 8) differ in the last bits for some)."""
    n_differ = 0
    for x, climdex_r, type8_r in _r_cases():
        assert [climdex_quantile(x, q) for q in QS] == climdex_r
        assert r_quantile_type8(x, QS).tolist() == type8_r
        n_differ += climdex_r != type8_r
    assert n_differ > 0  # the fixture includes cases where the two definitions differ


def test_climdex_quantile_known_values():
    # R: sprintf("%.17g", climdex.quantile(1:10, c(0.1, 0.5, 0.9))), same for type 8
    x = np.arange(1.0, 11.0)
    expected = [1.3666666666666665, 5.4999999999999991, 9.6333333333333329]
    assert [climdex_quantile(x, q) for q in (0.1, 0.5, 0.9)] == expected
    assert r_quantile_type8(x, [0.1, 0.5, 0.9]).tolist() == expected


def test_near_integer_position():
    # n = 135, q = 0.5: the position is just below an integer. climdex's C++ then
    # interpolates with h close to 1, while R's quantile() takes the upper value
    # (as for the 135-value case in r_quantiles.txt, where R gives 4.999999999999998
    # and 5).
    x = np.array([4.9] * 67 + [5.0] * 68)
    assert climdex_quantile(x, 0.5) == 4.999999999999998
    assert r_quantile_type8(x, [0.5])[0] == 5.0


def test_quantiles_clamp_at_the_ends():
    x = np.arange(1.0, 11.0)
    assert climdex_quantile(x, 0.0) == 1.0
    assert climdex_quantile(x, 1.0) == 10.0
    assert r_quantile_type8(x, [0.0, 0.99, 1.0]).tolist() == [1.0, 10.0, 10.0]


def test_quantiles_ignore_missing_values():
    x = np.array([np.nan, 3.0, 1.0, np.nan, 2.0])
    assert climdex_quantile(x, 0.5) == 2.0
    assert r_quantile_type8(x, [0.5])[0] == 2.0
    assert np.isnan(climdex_quantile([np.nan, np.nan], 0.5))
    assert np.isnan(r_quantile_type8([], [0.5])[0])
    assert climdex_quantile([7.3], 0.9) == 7.3  # one value: returned as is


def test_ties():
    tied = np.full(30, 21.7)
    for q in QS:
        assert climdex_quantile(tied, q) == 21.7
        assert r_quantile_type8(tied, [q])[0] == 21.7
    # ties at the threshold position: the tied value, not an interpolation
    x = np.array([1.0, 2.0, 2.0, 2.0, 2.0, 3.0])
    assert climdex_quantile(x, 0.5) == 2.0


# --- day of year and base period -------------------------------------------------------


def test_day_of_year_replaces_feb29():
    time = pd.date_range("2000-02-27", "2000-03-02", freq="D")
    assert day_of_year(time).tolist() == [58, 59, 59, 60, 61]
    assert day_of_year(pd.DatetimeIndex(["2000-12-31", "2001-12-31"])).tolist() == [365, 365]


def _daily(start, end, values=None):
    time = pd.date_range(start, end, freq="D")
    data = np.arange(time.size, dtype=float) if values is None else values
    return xr.DataArray(data, dims="time", coords={"time": time})


def test_base_period_matrix_drops_feb29_and_pads():
    da = _daily("1999-06-01", "2001-12-31")
    base = base_period_matrix(da, 1999, 2000)
    assert base.shape == (2, DAYS_PER_YEAR)
    assert np.isnan(base[0, :151]).all() and not np.isnan(base[0, 151:]).any()
    # 2000: 28 Feb is followed by 1 Mar
    feb28 = da.sel(time="2000-02-28").item()
    assert base[1, 58] == feb28 and base[1, 59] == da.sel(time="2000-03-01").item()


def test_window_wraps_within_the_same_year():
    base = np.zeros((2, DAYS_PER_YEAR))
    base[0, 364] = 100.0  # 31 December of the first year
    w = window_values(base, 5)
    assert w.shape == (DAYS_PER_YEAR, 2, 5)
    assert w[0, 0].tolist() == [0, 100, 0, 0, 0]  # 1 Jan, year 1, sees year 1's 31 Dec
    assert w[0, 1].max() == 0  # year 2's 1 Jan does not see year 1's 31 Dec


def test_running_quantiles_min_fraction():
    base = np.full((10, DAYS_PER_YEAR), np.nan)
    base[0, :] = 1.0  # one year of ten present: exactly 10% of each window
    q = running_quantiles(base, 5, [0.5])[0.5]
    assert (q == 1.0).all()
    base[0, 100] = np.nan  # days 98-102 now have 4/50 values present
    q = running_quantiles(base, 5, [0.5])[0.5]
    assert np.isnan(q[98:103]).all() and not np.isnan(q[97]) and not np.isnan(q[103])


def test_quantile_name():
    assert [quantile_name(q) for q in (0.05, 0.1, 0.5, 0.9, 0.95, 0.99)] == [
        "q5",
        "q10",
        "q50",
        "q90",
        "q95",
        "q99",
    ]


# --- station thresholds --------------------------------------------------------------


def _station(start, end, seed=0):
    time = pd.date_range(start, end, freq="D")
    rng = np.random.default_rng(seed)
    tmax = np.round(
        25 + 5 * np.sin(2 * np.pi * time.day_of_year / 365) + rng.normal(0, 3, time.size), 1
    )
    df = pd.DataFrame(
        {
            "date": time,
            "prcp": np.round(rng.exponential(3, time.size) * (rng.random(time.size) < 0.4), 1),
            "tmax": tmax,
            "tmin": tmax - 8,
        }
    )
    return station_dataset(df, StationMetadata(name="test"))


def test_compute_thresholds_and_daily_lookup():
    ds = _station("1990-01-01", "1995-12-31")
    t = compute_thresholds(ds, 1991, 1994)
    assert t.base["tasmax"].shape == (4, DAYS_PER_YEAR)
    q90 = t.outbase("tasmax", 0.9)
    assert q90.shape == (DAYS_PER_YEAR,)
    # tmin = tmax - 8 everywhere, so its thresholds are 8 lower (to rounding)
    np.testing.assert_allclose(t.outbase("tasmin", 0.9), q90 - 8, atol=1e-9)
    assert t.heatwave["tasmax"].shape == (DAYS_PER_YEAR,)

    daily = t.daily("tasmax", 0.9, ds.time)
    assert daily.sel(time="1992-02-29").item() == q90[58]
    assert daily.sel(time="1992-03-01").item() == q90[59]
    assert daily.sel(time="1993-12-31").item() == q90[364]

    years = ds.time.dt.year
    wet = ds.pr.values[((years >= 1991) & (years <= 1994) & (ds.pr >= 1)).values]
    assert t.precipitation[0.95] == r_quantile_type8(wet, [0.95])[0]


def test_insufficient_base_data():
    # climdex needs more than 359 days of the base period within the station's dates
    ds = _station("1990-01-07", "1991-12-31")
    with pytest.raises(InsufficientBaseData):
        compute_thresholds(ds, 1985, 1990)
    compute_thresholds(_station("1990-01-06", "1991-12-31"), 1985, 1990)


def test_row_quantiles_match_scalar_versions():
    """The batched quantiles (used for grids) agree with the per-series ones."""
    from climpact.thresholds import (
        r_quantile_type7,
        r_quantile_type7_rows,
        r_quantile_type8,
        r_quantile_type8_rows,
    )

    rng = np.random.default_rng(3)
    x = np.round(rng.gamma(0.6, 5, (40, 60)), 1)
    x[rng.random(x.shape) < 0.3] = np.nan
    x[0] = np.nan  # a row with no values
    x[1, 1:] = np.nan  # one value
    for q in (0.05, 0.5, 0.85, 0.95, 0.99):
        rows7, rows8 = r_quantile_type7_rows(x, q), r_quantile_type8_rows(x, q)
        for i, row in enumerate(x):
            row = row[~np.isnan(row)]
            if row.size == 0:
                assert np.isnan(rows7[i]) and np.isnan(rows8[i])
                continue
            assert rows7[i] == r_quantile_type7(row, q)
            assert rows8[i] == r_quantile_type8(row, [q])[0]


def test_running_quantiles_over_cells():
    """Leading dimensions (grid cells) give the same thresholds as one series at a time."""
    rng = np.random.default_rng(4)
    base = np.round(rng.normal(15, 6, (2, 3, 10, DAYS_PER_YEAR)), 1)
    base[rng.random(base.shape) < 0.5] = np.nan
    together = running_quantiles(base, 5, [0.1, 0.9])
    for i in range(2):
        for j in range(3):
            single = running_quantiles(base[i, j], 5, [0.1, 0.9])
            for q in (0.1, 0.9):
                assert np.array_equal(together[q][i, j], single[q], equal_nan=True)
