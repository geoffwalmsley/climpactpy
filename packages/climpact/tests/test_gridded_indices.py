"""Gridded indices: output names, the cells-at-once index functions, R's missing-value
quirks, memory bounds and the command line. Parity with R is in
tests/parity/test_gridded_indices.py."""

from __future__ import annotations

import tracemalloc

import netCDF4
import numpy as np
import pandas as pd
import pytest

from climpact.cli import main
from climpact.gridded import open_grid, write_grid_indices, write_grid_thresholds
from climpact.gridded.drought import (
    SCALES,
    monthly_inputs,
    pelgam,
    spei_package,
    spei_values,
    spi_values,
    tl_pwm,
)
from climpact.gridded.heatwaves import (
    EHF_FILE_THRESHOLDS,
    EHF_VARIABLES,
    hw_values,
    hwehf_values,
)
from climpact.gridded.indices import (
    THRESHOLD_FILE_VARIABLES,
    WRAPPER_PARAMS,
    cell_indices,
    index_files,
)
from climpact.gridded.thresholds import cell_thresholds
from climpact.missing import valid_mask, valid_periods
from climpact.periods import periods
from climpact.products import indices
from climpact.products.drought import pargam, pwm2lmom, pwm_ub
from climpact.products.indices import period_means
from climpact.rdist import pgamma, qnorm
from climpact.rnumerics import r_mean
from climpact.thresholds import bootstrap_quantiles

from .test_gridded import write_grid

# --- output names --------------------------------------------------------------------------


def test_index_files_follow_r_names_and_order():
    files = index_files()
    keys = [f.key for f in files]
    assert keys[:4] == ["su_MON", "su_ANN", "id_MON", "id_ANN"]  # get.climdex.variable.list
    for key in ("rx7day_MON", "r30mm_ANN", "wsdi5_ANN", "csdi5_ANN", "tx3tn3_ANN",
                "txb3tnb3_ANN", "hddheat18_ANN", "cddcold18_ANN", "gddgrow10_ANN",
                "tx95t_DAY"):  # fmt: skip
        assert key in keys
    assert len(files) == 88
    assert keys[-4:] == ["tmm_MON", "tmm_ANN", "hw_ANN", "hwEHF_ANN"]
    assert keys.index("spei_MON") + 1 == keys.index("spi_MON")
    rx = next(f for f in files if f.key == "rx7day_MON")
    assert rx.definition == "Maximum monthly 7-day precipitation total"
    assert rx.dated and not next(f for f in files if f.key == "cdd_ANN").dated
    # Monthly files get years only too (R looks for "_mon" in lower case).
    template = "var_daily_climpact.sample_historical_NA_1991-2010.nc"
    assert rx.filename(template) == "rx7day_MON_climpact.sample_historical_NA_1991-2010.nc"
    with pytest.raises(ValueError, match="CMIP5"):
        rx.filename("tas_1991-2010.nc")


# --- functions taking cells together -------------------------------------------------------


def test_periods_with_leading_dimensions_match_one_series():
    time = pd.date_range("2000-01-01", "2002-12-31")
    rng = np.random.default_rng(3)
    x = rng.normal(0, 1, (3, time.size)).round(1)
    x[rng.random(x.shape) < 0.2] = np.nan
    x[1, 31:59] = np.nan  # an empty month
    for rule in ("MS", "YS"):
        p = periods(time, rule)
        for i in range(3):
            assert np.array_equal(p.count(x > 0)[i], p.count(x[i] > 0))
            for stat in ("max", "min"):
                assert np.array_equal(p.reduce(x, stat)[i], p.reduce(x[i], stat), equal_nan=True)
                assert np.array_equal(p.first_extreme(x, stat)[i], p.first_extreme(x[i], stat))
            assert np.array_equal(p.apply(x, r_mean)[i], p.apply(x[i], r_mean), equal_nan=True)
            assert np.array_equal(
                valid_periods(~np.isnan(x), time, rule)[i],
                valid_mask(_da(x[i], time), freq=rule).values,
            )


def _da(values, time):
    import xarray as xr

    return xr.DataArray(values, dims="time", coords={"time": time})


def test_bootstrap_with_leading_dimensions_and_quantiles_together():
    rng = np.random.default_rng(5)
    base = rng.normal(10, 4, (2, 4, 365)).round(1)
    base[1, :, :50] = np.nan
    together = bootstrap_quantiles(base, 5, [0.1, 0.5, 0.9])
    for q in (0.1, 0.5, 0.9):
        for cell in range(2):
            alone = bootstrap_quantiles(base[cell], 5, [q])[q]
            assert np.array_equal(together[q][cell], alone, equal_nan=True)


def test_float32_means_round_like_r_mean(monkeypatch):
    """The vectorised means give R's mean rounded to float32, including near rounding
    boundaries (where they fall back to r_mean)."""
    time = pd.date_range("1990-01-01", "1999-12-31")
    rng = np.random.default_rng(11)
    x = (rng.normal(10, 8, (7, time.size)) + 273.15).astype(np.float32).astype(float) - 273.15
    x[1] = np.round(x[1], 1)
    x[2] = rng.integers(0, 2, time.size) / 29  # percentage-like shares
    # Means exactly on, or within 2**-45 of, the float32 midpoint 1 + 2**-24.
    x[3] = 1.0 + 2.0**-24 + np.where(np.arange(time.size) % 3 == 0, 2.0**-45, 0.0)
    x[4, :40] = np.nan
    x[5] = rng.normal(0, 1e-3, time.size) + 1e3 * np.sign(np.arange(time.size) % 2 - 0.5)
    x[6] = 1.0 + 2.0**-24
    calls = []
    monkeypatch.setattr(indices, "r_mean", lambda v: calls.append(1) or r_mean(v))
    for rule in ("MS", "YS"):
        p = periods(time, rule)
        for scale in (1.0, 100.0):
            exact = period_means(x, p, scale=scale).astype(np.float32)
            calls.clear()
            fast = period_means(x, p, float32=True, scale=scale).astype(np.float32)
            assert np.array_equal(exact, fast, equal_nan=True)
            # The fallback is used for the means near a boundary (rows 3 and 6), not all.
            assert 0 < len(calls) < np.count_nonzero(~np.isnan(exact))


def _cells(n_years=6, cells=3, seed=2):
    time = pd.date_range("1971-01-01", f"{1970 + n_years}-12-31")
    rng = np.random.default_rng(seed)
    doy = time.day_of_year.to_numpy()
    tx = 20 + 8 * np.cos(2 * np.pi * doy / 365.25) + rng.normal(0, 3, (cells, time.size))
    tx = tx.round(1)
    tn = (tx - 9 - np.abs(rng.normal(0, 2, tx.shape))).round(1)
    pr = np.maximum(rng.gamma(0.5, 8, tx.shape) - 1, 0).round(1)
    return time, tx, tn, pr


def _same(a, b) -> bool:
    return a is None and b is None or np.array_equal(a, b, equal_nan=True)


def test_cells_together_match_cells_alone():
    time, tx, tn, pr = _cells()
    lat = np.array([-10.0, 0.0, 45.0])
    together = cell_indices(tx, tn, pr, time, lat, 1972, 1975)
    for i in range(3):
        alone = cell_indices(
            tx[i : i + 1], tn[i : i + 1], pr[i : i + 1], time, lat[i : i + 1], 1972, 1975
        )
        for key, result in together.items():
            other = alone[key]
            assert _same(result.values[i : i + 1], other.values), key
            assert _same(None if result.nan is None else result.nan[i : i + 1], other.nan), key
            assert _same(None if result.day is None else result.day[i : i + 1], other.day), key


def test_r_missing_values():
    """An all-missing cell has no index; a year with no data has a NaN (not NA) mean;
    a year with no wet day has a NaN rNNptot."""
    time, tx, tn, pr = _cells()
    tx[0] = tn[0] = pr[0] = np.nan
    year = time.year == 1973
    tx[1, year] = np.nan
    pr[2, year] = 0.0
    out = cell_indices(tx, tn, pr, time, np.zeros(3), 1972, 1975)
    for key, result in out.items():
        assert np.isnan(result.values[0]).all(), key
        assert result.nan is None or not result.nan[0].any(), key
    txm = out["txm_ANN"]
    assert np.isnan(txm.values[1, 2]) and txm.nan[1, 2]
    assert not txm.nan[1, :2].any() and not txm.nan[1, 3:].any()
    assert out["txm_MON"].nan is None  # monthly: NaN times NA is NA
    r95ptot = out["r95ptot_ANN"]
    assert np.isnan(r95ptot.values[2, 2]) and r95ptot.nan[2, 2]
    assert out["prcptot_ANN"].values[2, 2] == 0


def test_hemisphere_of_the_equator_is_north():
    """gsl: R's gridded code takes latitude >= 0 as north (the station app > 0)."""
    time, tx, tn, pr = _cells(cells=1)
    north = cell_indices(tx, tn, pr, time, np.array([0.0]), 1972, 1975)["gsl_ANN"].values
    south = cell_indices(tx, tn, pr, time, np.array([-0.1]), 1972, 1975)["gsl_ANN"].values
    assert not np.array_equal(north, south, equal_nan=True)
    assert np.isnan(south[0, -1])  # the last southern season is always missing


def test_heatwave_hemisphere_per_cell():
    """hw: each cell's season follows its own latitude, with 0 as north (R's gridded
    ``lat >= 0``; the station app's ``> 0``)."""
    time, tx, tn, pr = _cells(n_years=8, cells=1)
    tx, tn, pr = (np.repeat(x, 2, axis=0) for x in (tx, tn, pr))
    lat = np.array([0.0, -0.1])
    hw = cell_indices(tx, tn, pr, time, lat, 1972, 1977, separate=["hw"])["hw_ANN"].values
    full = pd.DatetimeIndex(time)
    north = hw_values(tx[:1], tn[:1], full, np.array([True]), 1972, 1977)
    south = hw_values(tx[1:], tn[1:], full, np.array([False]), 1972, 1977)
    assert np.array_equal(hw[:1], north, equal_nan=True)
    assert np.array_equal(hw[1:], south, equal_nan=True)
    assert not np.array_equal(north, south, equal_nan=True)
    assert np.isnan(south[0, :, -1]).all()  # the last southern season is always missing
    assert not np.isnan(north[0, :, -1]).all()


def test_ehf_needs_half_of_the_base_period_unless_thresholds_are_given():
    """hwEHF: a cell with TAVG on less than half of the base period gets missing values
    (R stops); with thresholds from a file the check is not made."""
    time, tx, tn, pr = _cells(n_years=8, cells=2)
    in_base = (time.year >= 1972) & (time.year <= 1977)
    sparse = in_base & (np.arange(time.size) % 5 < 3)  # 60% of base days missing
    tx[1, sparse] = np.nan
    full = pd.DatetimeIndex(time)
    out = hwehf_values(tx, tn, full, 1972, 1977)
    assert np.isnan(out[1]).all()
    assert not np.isnan(out[0]).all()
    assert np.isnan(out[0, :, 0]).all()  # the first year is always missing
    thr = cell_thresholds(tx, tn, pr, time, 1972, 1977)
    given = hwehf_values(tx, tn, full, 1972, 1977, {k: thr[k] for k in EHF_FILE_THRESHOLDS})
    assert np.array_equal(given[0], out[0], equal_nan=True)  # the same thresholds
    assert not np.isnan(given[1]).all()
    # No positive base-period EHF in the sparse cell, so no EHF85: R's severities are
    # NA, giving HWPS -Inf (max with na.rm) and HWLS 0 in a year with heatwaves.
    assert np.isnan(thr["ehf85thresh"][1])
    hwn, hwps, hwls = (
        given[1, [k for k, v in enumerate(EHF_VARIABLES) if v[0] == n][0]]
        for n in ("EHF-HWN", "EHF-HWPS", "EHF-HWLS")
    )
    years = hwn > 0
    assert years.any() and np.isneginf(hwps[years]).all() and (hwls[years] == 0).all()


def test_heatwaves_and_drought_with_a_thresholds_file():
    """With a thresholds file, hw uses its 15-day thresholds and hwEHF its TAVG and EHF
    thresholds; SPI and SPEI fit the base-period data from the file followed by the data
    (``computefuture``), and the first ``scale - 1`` months are missing."""
    time, tx, tn, pr = _cells(n_years=12, cells=2, seed=5)
    lat = np.array([-20.0, 40.0])
    base, later = time.year <= 1976, time.year >= 1977
    thr = cell_thresholds(tx[:, base], tn[:, base], pr[:, base], time[base], 1971, 1976)
    future = pd.DatetimeIndex(time[later])
    file_values = {k: thr[k] for k in THRESHOLD_FILE_VARIABLES}
    out = cell_indices(
        tx[:, later], tn[:, later], pr[:, later], future, lat, 1971, 1976, thresholds=file_values
    )
    expected_hw = hw_values(
        tx[:, later], tn[:, later], future, lat >= 0, 1971, 1976,
        {"tasmax": thr["tx90thresh_15days"], "tasmin": thr["tn90thresh_15days"]},
    )  # fmt: skip
    assert np.array_equal(out["hw_ANN"].values, expected_hw, equal_nan=True)
    assert not np.isnan(expected_hw).all()
    expected_ehf = hwehf_values(
        tx[:, later], tn[:, later], future, 1971, 1976,
        {k: thr[k] for k in EHF_FILE_THRESHOLDS},
    )  # fmt: skip
    assert np.array_equal(out["hwEHF_ANN"].values, expected_ehf, equal_nan=True)

    # The data follow the base period here, so the series fitted is the whole series.
    n_future = 12 * 6
    whole_spi = spi_values(pr, pd.DatetimeIndex(time), 1971, 1976)[..., -n_future:]
    whole_spei = spei_values(tx, tn, pr, pd.DatetimeIndex(time), lat, 1971, 1976)
    whole_spei = whole_spei[..., -n_future:]
    for i, scale in enumerate(SCALES):
        for whole in (whole_spi, whole_spei):
            whole[:, i, : scale - 1] = np.nan
    assert np.array_equal(out["spi_MON"].values, whole_spi, equal_nan=True)
    assert np.array_equal(out["spei_MON"].values, whole_spei, equal_nan=True)
    assert np.isfinite(whole_spei[:, 0, 2:]).mean() > 0.9


def test_spi_and_spei_monthly_inputs_and_zero_accumulations():
    """climdex.spi sums a month with no data to 0 (``sum(na.rm = TRUE)``), climdex.spei
    makes it missing; SPI's Gamma is fitted to the non-zero values and an accumulated 0
    gets ``qnorm(0)``, which becomes missing."""
    time = pd.date_range("2000-01-01", "2000-03-31")
    pr = np.ones((1, time.size))
    pr[0, time.month == 2] = np.nan
    assert monthly_inputs(pr, time, "spi")[0].tolist() == [31.0, 0.0, 31.0]
    assert np.isnan(monthly_inputs(pr, time, "spei")[0, 1])

    rng = np.random.default_rng(4)
    monthly = rng.gamma(2.0, 20.0, 240)
    monthly[::12] = 0.0  # every January dry: nothing left to fit, all missing
    monthly[1::12][:5] = 0.0  # some dry Februaries
    values = spei_package(monthly, 1, slice(0, 240), "Gamma")
    assert np.isnan(values[::12]).all()
    assert np.isneginf(values[1::12][:5]).all()  # qnorm(cdfgam(0)) = qnorm(0) = -Inf
    assert np.isfinite(values[1::12][5:]).all()
    # The Gamma is fitted to the non-zero values only, and pze is not used.
    feb = monthly[1::12]
    lambdas, _ = pwm2lmom([tl_pwm(np.sort(feb[feb > 0]), r) for r in range(3)])
    alpha, beta = pelgam(lambdas[0], lambdas[1])
    expected = [qnorm(pgamma(v / beta, alpha)) for v in feb[5:]]
    assert np.array_equal(values[1::12][5:], expected)


def test_tl_pwm_and_pelgam_agree_with_lmomco():
    """TLMoments' PWMs and lmom's PELGAM differ from lmomco's ``pwm.ub`` and ``pargam``
    only in rounding (and PELGAM's 8-digit pi)."""
    x = np.sort(np.random.default_rng(1).gamma(2.0, 3.0, 30))
    lmomco = pwm_ub(x, nmom=3)
    tl = [tl_pwm(x, r) for r in range(3)]
    assert np.allclose(tl, lmomco, rtol=1e-13, atol=0)
    lambdas, _ = pwm2lmom(tl)
    assert np.allclose(pelgam(lambdas[0], lambdas[1]), pargam(lambdas), rtol=1e-6)
    assert pelgam(1.0, 1.0) is None


# --- writing ---------------------------------------------------------------------------------


def _all_values(directory):
    out = {}
    for path in sorted(directory.glob("*.nc")):
        with netCDF4.Dataset(path) as nc:
            for v in nc.variables:
                out[path.name, v] = nc[v][:]
    return out


def test_results_do_not_depend_on_blocks_batches_or_threads(tmp_path):
    path = write_grid(tmp_path / "g.nc", ny=3, nx=2, end="1976-12-31")
    write_grid_indices(open_grid([path]), tmp_path / "a", 1972, 1975)
    write_grid_indices(
        open_grid([path], max_values=1 * 3 * 2192),
        tmp_path / "b",
        1972,
        1975,
        workers=3,
        cells_per_batch=1,
    )
    a, b = _all_values(tmp_path / "a"), _all_values(tmp_path / "b")
    assert a.keys() == b.keys() and len(a) > 0
    for key in a:
        assert np.array_equal(np.ma.getmaskarray(a[key]), np.ma.getmaskarray(b[key])), key
        assert np.ma.allequal(a[key], b[key]), key


def test_thresholds_file_only_outside_the_base_period(tmp_path):
    path = write_grid(tmp_path / "g.nc", ny=2, nx=2, end="1976-12-31")
    thresholds = write_grid_thresholds(open_grid([path]), tmp_path / "t.nc", 1972, 1975)
    with pytest.raises(ValueError, match="outside the base period"):
        write_grid_indices(
            open_grid([path]), tmp_path / "out", 1972, 1975, thresholds_file=thresholds
        )
    future = write_grid(tmp_path / "f.nc", ny=2, nx=2, start="1977-01-01", end="1979-12-31")
    written = write_grid_indices(
        open_grid([future]), tmp_path / "out", 1972, 1975, thresholds_file=thresholds
    )
    assert len(written) == 88


# A representative subset (counts, means, extremes, Rx5day, spells, gsl and the
# percentile indices with their bootstrap): tracemalloc makes the full set slow.
MEMORY_INDICES = ("fd", "tmm", "txx", "rx5day", "cdd", "gsl", "tx90p", "wsdi", "r95p")


def _traced_peak(path, tmp_path, max_values):
    inp = open_grid([path], max_values=max_values)
    tracemalloc.start()
    try:
        write_grid_indices(
            inp, tmp_path / "out", 1972, 1974, cells_per_batch=2, indices=MEMORY_INDICES
        )
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def test_memory_is_bounded_by_the_block_not_the_grid(tmp_path):
    """The memory a run allocates depends on the block size, not on the grid size
    (numpy's allocations, traced with tracemalloc)."""
    ntime = 1826
    max_values = 4 * 3 * ntime  # 4 cells per block
    small = write_grid(tmp_path / "small.nc", ny=2, nx=2, end="1975-12-31")  # one block
    large = write_grid(tmp_path / "large.nc", ny=6, nx=6, end="1975-12-31", seed=1)  # 9
    peak_small = _traced_peak(small, tmp_path / "s", max_values)
    peak_large = _traced_peak(large, tmp_path / "l", max_values)
    peak_one_block = _traced_peak(large, tmp_path / "o", 36 * 3 * ntime)
    assert peak_large < 1.5 * peak_small
    assert peak_large < peak_one_block / 2


def test_command_line(tmp_path, capsys):
    path = write_grid(tmp_path / "g.nc", ny=1, nx=2, end="1976-12-31")
    out = tmp_path / "out"
    args = ["gridded-indices", str(path), "--out", str(out), "--base-start", "1972"]
    args += ["--base-end", "1975", "--indices", "fd", "rxdday", "hw", "--rx-days", "4"]
    assert main(args) == 0
    names = sorted(p.name for p in out.glob("*.nc"))
    assert names == [
        "fd_ANN_climpact_historical_NA_1971-1976.nc",
        "fd_MON_climpact_historical_NA_1971-1976.nc",
        "hw_ANN_climpact_historical_NA_1971-1976.nc",
        "rx4day_ANN_climpact_historical_NA_1971-1976.nc",
        "rx4day_MON_climpact_historical_NA_1971-1976.nc",
    ]
    with pytest.raises(SystemExit):
        main(["gridded-indices", str(path), "--out", str(out), "--indices", "nope"])


def test_wrapper_params():
    assert (WRAPPER_PARAMS.wsdi_days, WRAPPER_PARAMS.rx_days, WRAPPER_PARAMS.txtn_days) == (5, 7, 3)
