"""In-base bootstrap and the temperature percentile indices (tx90p ... txgt50p)."""

import numpy as np
import pandas as pd
import pytest

from climpact.config import StationMetadata
from climpact.io.station import station_dataset
from climpact.products.indices import temperature_percentiles
from climpact.station import StationRun
from climpact.thresholds import (
    DAYS_PER_YEAR,
    bootstrap_quantiles,
    climdex_quantile,
    window_values,
)


def _replaced_sample_quantiles(base, window, quantiles, min_fraction):
    """Direct port of the C++ bootstrap: build each replaced sample and take its quantile."""
    nyears = base.shape[0]
    windows = window_values(base, window)
    out = {q: np.full((DAYS_PER_YEAR, nyears, nyears - 1), np.nan) for q in quantiles}
    for day in range(DAYS_PER_YEAR):
        for rm in range(nyears):
            others = [y for y in range(nyears) if y != rm]
            for k, dup in enumerate(others):
                sample = np.concatenate([windows[day, y] for y in others] + [windows[day, dup]])
                sample = sample[~np.isnan(sample)]
                if sample.size / (window * nyears) < min_fraction:
                    continue
                for q in quantiles:
                    out[q][day, rm, k] = climdex_quantile(sample, q)
    return out


def test_bootstrap_known_values():
    """Three years, each constant: replacing year rm by a second copy of year dup."""
    base = np.repeat([[1.0], [2.0], [3.0]], DAYS_PER_YEAR, axis=1)
    result = bootstrap_quantiles(base, 1, [0.5])[0.5]
    assert result.shape == (DAYS_PER_YEAR, 3, 2)
    # rm=0: {2,2,3} -> 2, {2,3,3} -> 3; rm=1: {1,1,3} -> 1, {1,3,3} -> 3; rm=2: 1, 2
    expected = [[2.0, 3.0], [1.0, 3.0], [1.0, 2.0]]
    assert (result == np.array(expected)).all()


@pytest.mark.parametrize("seed", [0, 1])
def test_bootstrap_matches_replaced_samples(seed):
    """Bit-identical to building every replaced sample, with heavy ties and gaps."""
    rng = np.random.default_rng(seed)
    base = np.round(rng.normal(20, 3, (5, DAYS_PER_YEAR)), 0)
    base[rng.random(base.shape) < 0.3] = np.nan
    base[2, :200] = np.nan  # a year with no data for most of its days
    base[:, 100:110] = np.nan  # no data at all: every threshold missing
    base[1:, 150:160] = np.nan  # one year left: below the minimum fraction
    qs = [0.1, 0.5, 0.9]
    result = bootstrap_quantiles(base, 5, qs)
    expected = _replaced_sample_quantiles(base, 5, qs, 0.1)
    for q in qs:
        np.testing.assert_array_equal(result[q], expected[q])
    assert np.isnan(result[0.9][102]).all()


def _run(start: int, tmax_by_year: dict[int, float], end: int = 2004) -> StationRun:
    dates = pd.date_range(f"{start}-01-01", f"{end}-12-31", freq="D")
    tmax = dates.year.map(tmax_by_year).to_numpy(dtype=float)
    df = pd.DataFrame({"date": dates, "prcp": 0.0, "tmax": tmax, "tmin": tmax - 5})
    meta = StationMetadata(name="test", base_start=2001, base_end=2003)
    return StationRun(data=station_dataset(df, meta), metadata=meta)


def test_txgt50p_matches_r():
    """Values printed by R (tests/data/r_percent_days.R).

    Out of base (2004) the threshold is 2 and every day exceeds it. In base, each year
    is compared with the thresholds of the samples where it is replaced by another year:
    2001 (1) exceeds neither, 2002 (2) exceeds one of two, 2003 (3) exceeds both.
    """
    out = temperature_percentiles(_run(2001, {2001: 1, 2002: 2, 2003: 3, 2004: 2.5}))
    assert out["indices/txgt50p_ANN"]["txgt50p"].tolist() == [0.0, 50.0, 100.0, 100.0]


def test_station_starting_inside_the_base_period():
    """In-base hits are divided by the number of bootstrapped thresholds (2), so 2003,
    which exceeds both, gets 100%. R divides by the base years the series covers minus
    one (1) and gives 200% (tests/data/r_percent_days.R): deliberately not copied."""
    out = temperature_percentiles(_run(2002, {2002: 2, 2003: 3, 2004: 2.5}))
    assert out["indices/txgt50p_ANN"]["txgt50p"].tolist() == [0.0, 100.0, 100.0]


def test_station_ending_inside_the_base_period():
    """The base period is 2001-2003 and the series ends in 2002. 2002 (2) is compared
    with the thresholds of the samples where it is replaced by 2001 ({1, 1}) or by the
    missing 2003 ({1}): both exceeded, 100% (R: 200%). 2001 (1) exceeds neither."""
    out = temperature_percentiles(_run(2000, {2000: 1.5, 2001: 1, 2002: 2}, end=2002))
    assert out["indices/txgt50p_ANN"]["txgt50p"].tolist()[1:] == [0.0, 100.0]


@pytest.mark.parametrize(("start", "end"), [(2002, 2005), (2003, 2005), (1999, 2002)])
def test_percentages_never_exceed_100(start, end):
    """Random data on series that start or end inside the base period."""
    rng = np.random.default_rng(start + end)
    years = range(start, end + 1)
    run = _run(start, dict.fromkeys(years, 0.0), end=end)
    tasmax = run.data.tasmax.copy()
    tasmax[:] = np.round(rng.normal(20, 3, tasmax.size), 1)
    run.data["tasmax"] = tasmax
    run.data["tasmin"] = tasmax - 5
    out = temperature_percentiles(run)
    for name in ("tx90p", "tn90p", "tx10p", "tn10p", "txgt50p"):
        for freq in ("ANN", "MON"):
            values = out[f"indices/{name}_{freq}"][name].to_numpy(dtype=float)
            assert np.nanmax(values) <= 100.0, (name, freq)
            assert not np.isnan(values).all()


def test_strict_comparison_at_ties():
    """A value equal to its threshold does not count, out of base (2004 equals the
    threshold, 2) and against each bootstrapped threshold in base."""
    run = _run(2001, {2001: 1, 2002: 2, 2003: 2, 2004: 2})
    out = temperature_percentiles(run)
    # 2002 (rm=1): {1,1,2} -> 1 (exceeded), {1,2,2} -> 2 (tied: not exceeded)
    # 2003 (rm=2): {1,1,2} -> 1 (exceeded), {1,2,2} -> 2 (tied: not exceeded)
    assert out["indices/txgt50p_ANN"]["txgt50p"].tolist() == [0.0, 50.0, 50.0, 0.0]


def test_missing_days_and_months():
    """More than 3 missing days in a month, or 15 in a year, make the period missing."""
    run = _run(2001, {2001: 1, 2002: 2, 2003: 3, 2004: 2.5})
    tasmax = run.data.tasmax.copy()
    tasmax.loc["2004-01-01":"2004-01-04"] = np.nan  # 4 days in January 2004
    run.data["tasmax"] = tasmax
    out = temperature_percentiles(run)
    mon = out["indices/txgt50p_MON"].set_index("time")["txgt50p"]
    assert np.isnan(mon["2004-01"])
    assert mon["2004-02"] == 100.0
    assert np.isnan(out["indices/txgt50p_ANN"]["txgt50p"].iloc[3])
