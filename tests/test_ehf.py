"""EHF heatwaves against values printed by Climpact's climdex.hwEHF (tests/data/r_ehf.R)
for tests/data/ehf_synthetic.txt (tests/data/make_ehf_synthetic.py), base period 2001-2003.

Scenarios, by year (T95 is exactly 25 degC):

2001  a heatwave; the first year is always missing
2002  two heatwaves 2 days apart (joined into one), two 3 days apart (kept apart), one whose
      two leading days have a missing EHF (7 May missing), 60 days with EHF exactly 0
2003  a heatwave crossing 31 December: its 2003 piece counts in 2003, the rest in 2004
2004  three days missing in November, inside the 30-day window of a December heatwave
      (R divides the sum of the remaining 27 days by 30); the two leading days of a
      heatwave whose first positive EHF is on 1 January 2005: a 2-day heatwave with no
      intensity or severity
2006  no heatwave: HWN and HWF 0, the other aspects missing
2007  missing: 4 days missing in June

With 28 December 2004 also missing, the 2004 piece has a missing EHF and no positive
one, and R stops (``if (all(...))`` on NA). Python counts the piece as R would without
the missing value (not copied from R; see TECHNICAL.md).
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from climpact.config import StationMetadata
from climpact.io.climpact_csv import read_climpact_csv
from climpact.io.output_files import write_outputs
from climpact.products.ehf import (
    ASPECTS,
    annual_aspects,
    ehf_heatwaves,
    excess_factors,
    heatwaves,
)
from climpact.station import StationRun, load_station
from climpact.thresholds import r_quantile_type7

DATA = Path(__file__).parent / "data"
YEARS = list(range(2001, 2008))
META = StationMetadata(name="ehf", latitude=-30, base_start=2001, base_end=2003)


def r_output() -> tuple[dict[str, np.ndarray], float, pd.DataFrame, str]:
    annual, days = {}, []
    ehf85 = error = None
    for line in (DATA / "r_ehf.txt").read_text().splitlines():
        if line.startswith("missing-lead-day:"):
            error = line.split(":", 1)[1].strip()
            continue
        key, *values = line.split()
        if key == "day":
            days.append((values[0], *[np.nan if v == "NA" else float(v) for v in values[1:]]))
            continue
        nums = [np.nan if v == "NA" else float(v) for v in values]
        if key == "ehf85":
            ehf85 = nums[0]
        else:
            annual[key.upper()] = np.array(nums)
    daily = pd.DataFrame(days, columns=["date", "ehf", "ecf"])
    return annual, ehf85, daily, error


R_ANNUAL, R_EHF85, R_DAILY, R_ERROR = r_output()


@pytest.fixture(scope="module")
def run():
    return load_station(DATA / "ehf_synthetic.txt", META)


@pytest.fixture(scope="module")
def tables(run):
    return ehf_heatwaves(run)


def same(a, b) -> bool:
    """Bit-identical, missing values in the same places."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    return a.shape == b.shape and bool(np.all((a == b) | (np.isnan(a) & np.isnan(b))))


@pytest.mark.parametrize("aspect", ASPECTS)
def test_annual_aspects_match_r(tables, aspect):
    values = tables[f"indices/EHF-{aspect}_ANN"][aspect].to_numpy()
    assert same(values, R_ANNUAL[aspect]), (values, R_ANNUAL[aspect])


def test_daily_values_match_r(tables):
    for name, column, r_col in (
        ("EHFdaily", "Excess Heat Factor", "ehf"),
        ("ECFdaily", "Excess Cold Factor", "ecf"),
    ):
        table = tables[f"indices/{name}"].set_index("date")
        assert same(table.loc[R_DAILY.date, column], R_DAILY[r_col]), name


def test_daily_series_include_29_february(tables):
    """R's description says 29 February is omitted, but it is in the series and the
    calculation."""
    table = tables["indices/EHFdaily"]
    assert table.date.iloc[0] == "2001-01-01"
    assert "2004-02-29" in set(table.date)
    assert table.shape[0] == pd.date_range("2001-01-01", "2007-12-31").size
    assert table["Excess Heat Factor"].iloc[:32].isna().all()
    assert not np.isnan(table["Excess Heat Factor"].iloc[32])


def test_ehf85(run):
    ds = run.data
    years = pd.DatetimeIndex(ds.time.values).year.to_numpy()
    tavg = ds.tas.values
    base = (years >= 2001) & (years <= 2003)
    t95 = r_quantile_type7(tavg[base], 0.95)
    assert t95 == 25.0
    ehf, _ = excess_factors(tavg, t95, r_quantile_type7(tavg[base], 0.05))
    assert r_quantile_type7(ehf[base][ehf[base] > 0], 0.85) == R_EHF85


def test_heatwave_pieces(run):
    """Joined, separate, split at 31 December, and the lead-days-only piece."""
    ds = run.data
    time = pd.DatetimeIndex(ds.time.values)
    tavg = ds.tas.values
    ehf, _ = excess_factors(tavg, 25.0, 0.0)
    pieces = [(str(time[s].date()), str(time[e].date())) for s, e in heatwaves(ehf, time.year)]
    assert ("2002-03-31", "2002-04-09") in pieces  # two heatwaves 2 days apart, joined
    assert ("2002-04-19", "2002-04-23") in pieces and ("2002-04-25", "2002-04-29") in pieces
    assert ("2002-05-08", "2002-05-11") in pieces  # starts with two missing EHF values
    # pieces of heatwaves crossing 31 December come last, as R appends them
    assert pieces[-4:] == [
        ("2003-12-28", "2003-12-31"),
        ("2004-01-01", "2004-01-04"),
        ("2004-12-30", "2004-12-31"),
        ("2005-01-01", "2005-01-04"),
    ]


def test_r_quantile_type7():
    x = np.array([3.0, 1.0, np.nan, 2.0, 10.0])
    assert r_quantile_type7(x, 0.5) == 2.5
    h = (1 + 3 * 0.95) - 3  # R: index - lo, with index = 1 + (n - 1) * prob
    assert r_quantile_type7(x, 0.95) == (1 - h) * 3.0 + h * 10.0
    assert r_quantile_type7(np.array([5.0, 5.0]), 0.3) == 5.0
    assert np.isnan(r_quantile_type7(np.array([np.nan]), 0.5))


def test_missing_lead_day_not_an_error(run):
    """R stops here; Python treats the 2004 piece (missing EHF, no positive one) as a
    piece without positive EHF: it counts in HWN, HWF and the durations only."""
    assert R_ERROR == "missing value where TRUE/FALSE needed"
    ds = run.data.copy(deep=True)
    day = np.flatnonzero(pd.DatetimeIndex(ds.time.values) == "2004-12-28")[0]
    for var in ("tasmax", "tasmin", "tas"):
        ds[var].values[day] = np.nan
    tables = ehf_heatwaves(StationRun(ds, META))
    ehf = tables["indices/EHFdaily"]["Excess Heat Factor"].to_numpy()
    assert np.isnan(ehf[day + 2])  # 30 December, the first day of the 2004 piece
    i = YEARS.index(2004)
    assert tables["indices/EHF-HWN_ANN"].HWN[i] == R_ANNUAL["HWN"][i]
    assert tables["indices/EHF-HWF_ANN"].HWF[i] == R_ANNUAL["HWF"][i]


def test_piece_without_positive_ehf_has_duration_only():
    years = np.array([2001] * 40 + [2002] * 5)
    ehf = np.full(45, -1.0)
    ehf[40:42] = 5.0  # first positive day 1 January: 2001 gets the two lead days
    out = annual_aspects(ehf, years, 10.0)
    assert out["HWN"].tolist() == [1, 1]
    assert out["HWF"].tolist() == [2, 2]
    assert out["HWD"].tolist() == [2, 2]
    assert np.isnan(out["HWPS"][0]) and np.isnan(out["HWLI"][0])
    assert out["HWLI"][1] == 10.0 and out["HWPS"][1] == 0.5


def test_insufficient_base_period_writes_nothing(run):
    ds = run.data.copy(deep=True)
    years = pd.DatetimeIndex(ds.time.values).year
    gone = (years == 2001) | (years == 2002)  # 365 of the 1094 days: under half
    for var in ("tasmax", "tasmin", "tas"):
        ds[var].values[gone] = np.nan
    assert ehf_heatwaves(StationRun(ds, META)) == {}


def test_written_files(tables, tmp_path):
    """All ten files are written, including aspects missing in every year, with R's
    layouts: ``time, <aspect>`` with ", ", and ``date,<factor>`` with ","."""
    paths = write_outputs(tables, META, StationRun(None, META).params, tmp_path)
    assert len(paths) == 10
    hwn = read_climpact_csv(paths["indices/EHF-HWN_ANN"])
    assert hwn.columns == ["time", "HWN"]
    assert hwn.metadata["Description"] == "Heatwave number (HWN): Number of EHF heatwaves."
    lines = paths["indices/EHFdaily"].read_text().splitlines()
    assert lines[7] == "date,Excess Heat Factor"
    assert lines[8] == "2001-01-01,-99.9"
    assert lines[0] == (
        '"Description: ","EHF daily values. Note that 29th February is omitted from this'
        ' calculation."'
    )
    assert paths["indices/ECFdaily"].read_text().splitlines()[7] == "date,Excess Cold Factor"

    all_missing = {k: v.assign(**{v.columns[1]: np.nan}) for k, v in tables.items()}
    all_missing["indices/EHF-HWF_ANN"] = tables["indices/EHF-HWF_ANN"]
    assert len(write_outputs(all_missing, META, StationRun(None, META).params, tmp_path)) == 10
