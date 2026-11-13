import numpy as np

from climpact.config import CustomIndex
from climpact.products.indices import running_sum_centred, series_lengths_at_ends
from climpact.products.tables import format_number, standardise


def test_series_lengths_at_ends():
    flags = np.array([True, True, True, False, True, False, True, True, True, True, False])
    assert series_lengths_at_ends(flags).tolist() == [0, 0, 3, 0, 1, 0, 0, 0, 0, 4, 0]


def test_running_sum_is_centred_and_zero_padded():
    pr = np.array([1.0, 2.0, np.nan, 4.0, 5.0, 6.0])
    # 3-day centred windows; missing day counts as 0; ends padded with 0
    expected = np.array([0.0, 3.0, 6.0, 9.0, 15.0, 0.0]) / 3
    assert np.allclose(running_sum_centred(pr, 3), expected)


def test_standardise_uses_sample_sd_and_handles_constants():
    out = standardise(np.array([1.0, 2.0, 3.0, np.nan]))
    assert np.allclose(out[:3], [-1.0, 0.0, 1.0])
    assert np.isnan(out[3])
    assert np.isnan(standardise(np.array([0.0, 0.0, 0.0]))).all()
    assert np.isnan(standardise(np.array([5.0]))).all()


def test_parameter_names_match_r():
    assert format_number(30.0) == "30"
    assert format_number(12.5) == "12.5"
    assert CustomIndex("TN", ">", 0).name == "TNgt0"
    assert CustomIndex("TX", "<=", -2.5).name == "TXle-2.5"


def test_dtr_uses_tm_mask_when_tx_and_tn_gaps_differ():
    """climdex.dtr masks with TM: 3 TX gaps + 3 TN gaps on other days = 6 missing days."""
    import pandas as pd

    from climpact.config import StationMetadata
    from climpact.io.station import station_dataset
    from climpact.products.indices import means_and_totals
    from climpact.station import StationRun

    dates = pd.date_range("2001-01-01", "2001-12-31", freq="D")
    df = pd.DataFrame({"date": dates, "prcp": 0.0, "tmax": 20.0, "tmin": 10.0})
    df.loc[[0, 1, 2], "tmax"] = np.nan  # 1-3 January: TX missing
    df.loc[[10, 11, 12], "tmin"] = np.nan  # 11-13 January: TN missing
    meta = StationMetadata(name="test")
    run = StationRun(data=station_dataset(df, meta), metadata=meta)

    dtr = means_and_totals(run)["indices/dtr_MON"]["dtr"]
    assert np.isnan(dtr.iloc[0])  # January: 6 days missing TX or TN
    assert dtr.iloc[1:].tolist() == [10.0] * 11


def test_extreme_dates_with_an_empty_month():
    """A month with no data gets no date; other months keep the first extreme."""
    import pandas as pd
    import xarray as xr

    from climpact.products.indices import first_extreme_dates

    time = pd.date_range("2001-01-01", "2001-03-31", freq="D")
    values = np.full(time.size, 5.0)
    values[time.month == 2] = np.nan  # February: no data at all
    values[[3, 7]] = 9.0  # January maximum on the 4th and 8th: the first wins
    values[time == "2001-03-10"] = np.nan
    values[time == "2001-03-20"] = 1.0
    da = xr.DataArray(values, dims="time", coords={"time": time})

    dmax = pd.DatetimeIndex(first_extreme_dates(da, "MS", "max").values)
    dmin = pd.DatetimeIndex(first_extreme_dates(da, "MS", "min").values)
    assert dmax[0] == pd.Timestamp("2001-01-04")
    assert pd.isna(dmax[1]) and pd.isna(dmin[1])
    assert dmax[2] == pd.Timestamp("2001-03-01")
    assert dmin[2] == pd.Timestamp("2001-03-20")


def _precip_run(prcp):
    import pandas as pd

    from climpact.config import StationMetadata
    from climpact.io.station import station_dataset
    from climpact.station import StationRun

    time = pd.date_range("1990-01-01", periods=len(prcp), freq="D")
    df = pd.DataFrame({"date": time, "prcp": prcp, "tmax": 20.0, "tmin": 10.0})
    meta = StationMetadata(name="test", base_start=1990, base_end=1991)
    return StationRun(station_dataset(df, meta), meta)


def test_precipitation_percentile_indices():
    """rNNp sums days strictly above the wet-day percentile; rNNptot divides by
    prcptot; a year with no wet days gives 0 / 0, written as missing."""
    from climpact.products.indices import precipitation_percentiles

    rng = np.random.default_rng(1)
    wet_years = np.round(rng.exponential(5, 730) * (rng.random(730) < 0.5), 1)
    run = _precip_run(np.concatenate([wet_years, np.zeros(365)]))  # 1990-1992
    q95 = run.thresholds.precipitation[0.95]
    out = precipitation_percentiles(run)

    pr = run.data.pr.sel(time="1990").values
    r95p = out["indices/r95p_ANN"]["r95p"].to_numpy()
    assert r95p[0] == pr[pr > q95].sum()
    assert r95p[2] == 0
    r95ptot = out["indices/r95ptot_ANN"]["r95ptot"].to_numpy()
    np.testing.assert_allclose(r95ptot[0], 100 * r95p[0] / pr[pr >= 1].sum())
    assert np.isnan(r95ptot[2])
    assert set(out) == {f"indices/{n}_ANN" for n in ("r95p", "r99p", "r95ptot", "r99ptot")}


def test_annual_total_above_is_strict():
    import pandas as pd
    import xarray as xr

    from climpact.products.indices import annual_total_above

    time = pd.date_range("2000-01-01", periods=4, freq="D")
    pr = xr.DataArray([5.0, 10.0, np.nan, 12.5], dims="time", coords={"time": time})
    assert annual_total_above(pr, 10.0, ">").item() == 12.5
    assert annual_total_above(pr, 10.0, ">=").item() == 22.5


def test_threshold_counts_match_xclim():
    """count_days gives the same counts and climdex mask as the xclim indicators."""
    import xclim
    from xclim.indicators import atmos

    from climpact.products.indices import COUNTS, count_days
    from climpact.products.tables import FREQS
    from climpact.station import load_station
    from tests.parity.catalogue import RUNS

    run = RUNS["sydney"]
    ds = load_station(run.input_path, run.metadata).data.copy(deep=True)
    for var in ("pr", "tasmax", "tasmin", "tas"):
        ds[var][100:105] = np.nan  # April 1936: the month and the year are missing
    indicators = {
        ("tasmin", "<"): atmos.tn_days_below,
        ("tasmin", ">"): atmos.tn_days_above,
        ("tasmax", "<"): atmos.tx_days_below,
        ("tasmax", ">"): atmos.tx_days_above,
        ("tasmax", ">="): atmos.tx_days_above,
        ("tas", ">="): atmos.tg_days_above,
        ("tas", "<"): atmos.tg_days_below,
        ("pr", ">="): atmos.wetdays,
    }
    units = {"pr": "mm/d"}
    for var, threshold, condition in [*COUNTS.values(), ("pr", 12.5, ">=")]:
        indicator = indicators[var, condition]
        for freq, rule in FREQS.items():
            with xclim.set_options(
                check_missing="climdex",
                as_dataset=False,
                cf_compliance="log",
                data_validation="log",
            ):
                expected = indicator(
                    **{var: ds[var]},
                    thresh=f"{threshold} {units.get(var, 'degC')}",
                    condition=condition,
                    freq=rule,
                )
            actual = count_days(ds[var], threshold, condition, freq)
            assert np.isnan(actual.values).any()
            np.testing.assert_array_equal(actual.values, expected.values.astype(float))
