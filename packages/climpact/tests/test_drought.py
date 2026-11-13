"""SPI and SPEI against Climpact's cspei/cspi and SPEI's hargreaves (tests/data/r_drought.R).

The synthetic monthly series (1961-2010, base period 1971-2000) exercise what the
reference stations do not: a calendar month with no precipitation in any base year
(never fitted), one with fewer than five base values (never fitted), dry months mixed in
with the zero probability, missing months, a value whose probability is 1 (infinite
SPI/SPEI, written as missing), and polar latitudes in Hargreaves' radiation.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from climpact.config import IndexParams, StationMetadata
from climpact.io.output_files import write_outputs
from climpact.products import drought
from climpact.rdist import qnorm
from climpact.station import StationRun

from .libm import GLIBC_X86_64, LIBM_ATOL, LIBM_RTOL

DATA = Path(__file__).parent / "data"
BASE = slice(120, 480)  # 1971-01 .. 2000-12 of a series starting in 1961-01


def _parse(field: str) -> float:
    return math.nan if field == "NA" else float.fromhex(field)


def r_output() -> dict[str, np.ndarray]:
    out = {}
    for line in (DATA / "r_drought.txt").read_text().splitlines():
        name, *fields = line.split()
        if name in ("pet", "spi", "spei"):
            name = f"{name} {fields.pop(0)}"
        values = np.array([_parse(f) for f in fields])
        if name.startswith("sp"):
            values[np.isinf(values)] = np.nan  # Climpact turns Inf into NA after cspei
        out[name] = values
    return out


R = r_output()


def assert_matches_r(actual: np.ndarray, expected: np.ndarray) -> None:
    """Same missing values; values bit for bit on glibc x86_64, else within the libm tolerance."""
    assert actual.shape == expected.shape
    np.testing.assert_array_equal(np.isnan(actual), np.isnan(expected))
    ok = ~np.isnan(expected)
    if GLIBC_X86_64:
        np.testing.assert_array_equal(actual[ok], expected[ok])
    else:
        np.testing.assert_allclose(actual[ok], expected[ok], rtol=LIBM_RTOL, atol=LIBM_ATOL)


@pytest.mark.parametrize("lat", ["0", "-33.86", "62", "75", "-80"])
def test_hargreaves_matches_r(lat):
    pet = drought.hargreaves(R["tmin"], R["tmax"], float(lat), R["prec"])
    assert_matches_r(pet, R[f"pet {lat}"])


def test_hargreaves_quirks():
    pet = R["pet -33.86"]
    # The month with 1e5 mm: Tr - 0.0123 P < 0, so ET0 is 0 rather than missing.
    big = np.flatnonzero(R["prec"] == 1e5)[0]
    assert pet[big] == 0
    # A month with TX or TN missing (or precipitation missing) has missing PET.
    assert np.isnan(pet[[44, 45, 399]]).all()
    assert np.isnan(pet[np.isnan(R["prec"])]).all()
    # Polar night (sunset hour angle argument > 1): no radiation, so no PET.
    assert (R["pet 75"][0::12] == 0).all()


@pytest.mark.parametrize("scale", [1, 3, 24])
def test_spi_matches_r(scale):
    spi = drought.cspei(R["prec"], scale, BASE, "Gamma")
    assert_matches_r(spi, R[f"spi {scale}"])


@pytest.mark.parametrize("scale", [1, 3, 24])
def test_spei_matches_r(scale):
    balance = R["prec"] - R["pet -33.86"]
    spei = drought.cspei(balance, scale, BASE, "log-Logistic")
    assert_matches_r(spei, R[f"spei {scale}"])


def test_months_without_a_fit_are_missing():
    spi1 = R["spi 1"]
    # January: no precipitation in any base year (L2 = 0, invalid L-moments).
    assert np.isnan(spi1[0::12]).all()
    # April: 4 base-period values, so pwm.ub has a 0/0 moment and R skips the month.
    assert np.isnan(spi1[3::12]).all()
    # Every other calendar month is fitted.
    assert all(not np.isnan(spi1[m::12]).all() for m in (1, 2, 4, 5, 6, 7, 8, 9, 10, 11))


def test_zero_probability_mixed_in():
    """SPI of a dry month is qnorm(pze), the same value for every dry July."""
    july = R["prec"][6::12]
    spi = drought.cspei(R["prec"], 1, BASE, "Gamma")[6::12]
    dry = spi[july == 0]
    base_july = R["prec"][BASE][6::12]
    pze = np.count_nonzero(base_july == 0) / np.count_nonzero(~np.isnan(base_july))
    assert dry.size > 5 and np.all(dry == dry[0])
    assert dry[0] == qnorm(pze)


def test_infinite_values_are_missing():
    big = np.flatnonzero(R["prec"] == 1e5)[0]
    for scale in (1, 3):
        assert np.isnan(drought.cspei(R["prec"], scale, BASE, "Gamma")[big])


def test_accumulation_is_a_mean_newest_first():
    data = np.array([1.0, 2.0, 4.0, 8.0, np.nan, 3.0])
    acc = drought.accumulate(data, 3)
    np.testing.assert_array_equal(acc[:2], [np.nan, np.nan])
    # R: sum(c(4, 2, 1) * kern(3)) in extended precision is 0x1.2aaaaaaaaaaaap+1; adding
    # the three products in double precision would give 0x1.2aaaaaaaaaaabp+1.
    assert acc[2] == float.fromhex("0x1.2aaaaaaaaaaaap+1")
    assert acc[3] == pytest.approx(14 / 3)
    assert np.isnan(acc[4:]).all()  # any missing month in the window


# --- products ------------------------------------------------------------------------


def station(pr, tasmax, tasmin, start="1961-01-01", latitude=-33.86, params=None):
    time = pd.date_range(start, periods=len(pr), freq="D")
    ds = xr.Dataset(
        {
            "pr": ("time", pr),
            "tasmax": ("time", tasmax),
            "tasmin": ("time", tasmin),
            "tas": ("time", (tasmax + tasmin) / 2),
        },
        coords={"time": time},
    )
    meta = StationMetadata(name="synthetic", latitude=latitude)
    return StationRun(ds, meta, params or IndexParams())


@pytest.fixture(scope="module")
def daily():
    rng = np.random.default_rng(22)
    n = len(pd.date_range("1961-01-01", "2010-12-31"))
    pr = np.round(rng.gamma(0.5, 6.0, n), 1)
    tasmax = np.round(25 + rng.normal(0, 3, n), 1)
    tasmin = np.round(tasmax - 9 - np.abs(rng.normal(0, 2, n)), 1)
    return pr, tasmax, tasmin


def test_monthly_inputs_use_partial_months(daily):
    pr, tasmax, tasmin = (a.copy() for a in daily)
    pr[0:30] = np.nan  # 30 of January 1961's 31 days missing: still a total
    pr[31:59] = np.nan  # all of February 1961 missing
    tasmax[59:89] = np.nan  # 30 of March's 31 days
    m = drought.monthly_inputs(station(pr, tasmax, tasmin))
    assert m["time"][0] == "1961-01" and len(m) == 600
    assert m.loc[0, "prec"] == daily[0][30]
    assert np.isnan(m.loc[1, "prec"])
    assert m.loc[2, "tmax"] == daily[1][89]


def test_tables_and_files(daily, tmp_path):
    run = station(*daily, params=IndexParams(spei_months=18))
    tables = {**drought.spi(run), **drought.spei(run)}
    assert sorted(tables) == sorted(
        f"indices/{s}month_{i}_MON" for s in (3, 6, 12, 18) for i in ("spi", "spei")
    )
    t = tables["indices/18month_spi_MON"]
    assert list(t.columns) == ["time", "spi"]
    assert t["spi"][:17].isna().all() and not np.isnan(t["spi"][17])
    written = write_outputs(tables, run.metadata, run.params, tmp_path)
    lines = written["indices/3month_spei_MON"].read_text().splitlines()
    assert lines[0] == '"Description: ","Standardised Precipitation-Evapotranspiration Index"'
    assert lines[7] == "time, spei"
    assert lines[8] == "1961-01, -99.9"
    spi_lines = written["indices/18month_spi_MON"].read_text().splitlines()
    assert spi_lines[0] == '"Description: ","Standardised Precipitation Index"'


def test_scale_missing_throughout_is_still_written(daily, tmp_path):
    """write.precindex.csv writes all four files unless all four are missing."""
    run = station(*daily, params=IndexParams(spei_months=700))  # longer than the series
    tables = drought.spi(run)
    assert tables["indices/700month_spi_MON"]["spi"].isna().all()
    written = write_outputs(tables, run.metadata, run.params, tmp_path)
    assert "indices/700month_spi_MON" in written


def test_nothing_without_data(daily):
    pr, tasmax, tasmin = daily
    nan = np.full_like(pr, np.nan)
    assert drought.spi(station(nan, tasmax, tasmin)) == {}
    assert drought.spei(station(pr, nan, tasmin)) == {}
    assert drought.spei(station(pr, tasmax, nan)) == {}
    assert drought.spi(station(pr, nan, tasmin))  # SPI needs precipitation only
