"""Gridded data in the noleap (365_day) and 360_day calendars (#66): the CalendarDays axis,
the R behaviour reproduced for those calendars, and the whole pipeline on such grids.

The values are checked against R by the gridded parity runs ``grid_filled_noleap``,
``grid_filled_360day`` and ``grid_sample_360day``.
"""

from __future__ import annotations

import netCDF4
import numpy as np
import pandas as pd
import pytest

from climpact.calendars import CalendarDays, canonical_calendar, days_per_year, whole_years
from climpact.gridded import cell_thresholds, open_grid, write_grid_indices, write_grid_thresholds
from climpact.gridded.heatwaves import hw_threshold_days
from climpact.gridded.indices import _day_numbers, _period_bounds
from climpact.gridded.thresholds import _days_since, _year_days, pcict_calendar
from climpact.periods import periods
from climpact.products.ehf import base_data_sufficient
from climpact.thresholds import base_period_array, day_of_year, take_dates

from .test_gridded import write_grid


def test_canonical_calendar():
    assert canonical_calendar(None) is None
    assert canonical_calendar("standard") is None
    assert canonical_calendar("Gregorian") is None
    assert canonical_calendar("365_day") == canonical_calendar("NoLeap") == "noleap"
    assert canonical_calendar("360_day") == "360_day"
    for name in ("all_leap", "366_day", "julian", "none"):
        with pytest.raises(NotImplementedError):
            canonical_calendar(name)
    assert days_per_year(None) == days_per_year("noleap") == 365
    assert days_per_year("360_day") == 360


@pytest.mark.parametrize(("calendar", "dpy"), [("noleap", 365), ("360_day", 360)])
def test_whole_years(calendar, dpy):
    days = CalendarDays.whole_years(calendar, 2000, 2002)
    assert days.size == 3 * dpy
    assert days.day_of_year.tolist() == list(range(1, dpy + 1)) * 3
    assert np.array_equal(np.diff(days.ordinal), np.ones(3 * dpy - 1))
    last = days[dpy - 1]
    assert (last.year, last.month, last.day) == (2000, 12, 31 if dpy == 365 else 30)
    lengths = np.bincount(days.month.to_numpy())[1:] // 3
    assert lengths.tolist() == (
        [30] * 12 if dpy == 360 else [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    )
    # Slices, masks and indexing keep the calendar.
    sub = days[days.year == 2001]
    assert isinstance(sub, CalendarDays) and sub.size == dpy and sub[0].year == 2001
    assert whole_years(sub[10:20]).equals(sub)


def test_360_day_months():
    days = CalendarDays.whole_years("360_day", 1999, 1999)
    feb = days[days.month == 2]
    assert feb.day.tolist() == list(range(1, 31))
    assert day_of_year(days).tolist() == list(range(1, 361))


def test_get_indexer_and_take_dates():
    time = CalendarDays.whole_years("360_day", 1971, 1972)
    keep = np.ones(time.size, dtype=bool)
    keep[[5, 400]] = False
    data = time[keep]
    values = np.arange(data.size, dtype=float)
    full = whole_years(data)
    out = take_dates(values, data, full)
    assert np.isnan(out[[5, 400]]).all()
    assert np.array_equal(out[keep], values)
    assert time.get_indexer(CalendarDays("360_day", [1972], [2], [30])).tolist() == [419]
    assert time.get_indexer(CalendarDays("360_day", [1973], [1], [1])).tolist() == [-1]


def test_periods_of_calendar_days():
    days = CalendarDays.whole_years("360_day", 1980, 1981)
    months = periods(days, "MS")
    assert months.size == 24 and months.days().tolist() == [30] * 24
    assert months.labels[1] == pd.Timestamp("1980-02-01")
    years = periods(days, "YS")
    assert years.days().tolist() == [360, 360]
    assert years.labels.tolist() == [pd.Timestamp("1980-01-01"), pd.Timestamp("1981-01-01")]
    noleap = periods(CalendarDays.whole_years("noleap", 1980, 1980), "MS")
    assert noleap.days()[1] == 28  # no 29 February in a leap year


def test_base_period_array_keeps_every_day():
    """noleap and 360_day base periods are dpy days a year, nothing dropped."""
    for calendar, dpy in (("noleap", 365), ("360_day", 360)):
        time = CalendarDays.whole_years(calendar, 1970, 1975)
        values = np.arange(time.size, dtype=float)[None, :]
        base = base_period_array(values, time, 1971, 1973)
        assert base.shape == (1, 3, dpy)
        assert base[0, 0, 0] == dpy and base[0, -1, -1] == 4 * dpy - 1


def test_noleap_thresholds_equal_standard_without_29_february(tmp_path):
    """The day-of-year thresholds drop 29 February in the standard calendar, so the same
    values relabelled to noleap give the same thresholds; the wet-day percentiles keep
    29 February in the standard calendar, so they can differ."""
    rng = np.random.default_rng(3)
    dates = pd.date_range("1970-01-01", "1979-12-31", freq="D")
    keep = ~((dates.month == 2) & (dates.day == 29))
    season = 8 * np.sin(2 * np.pi * dates.day_of_year.to_numpy() / 365)
    tx = 20 + season + rng.normal(0, 3, (2, dates.size))
    tn = tx - 10
    pr = np.maximum(rng.gamma(0.5, 6, (2, dates.size)) - 1, 0)
    noleap = CalendarDays("noleap", dates.year[keep], dates.month[keep], dates.day[keep])
    standard = cell_thresholds(tx, tn, pr, dates, 1971, 1978)
    other = cell_thresholds(tx[:, keep], tn[:, keep], pr[:, keep], noleap, 1971, 1978)
    for name in ("tx10thresh", "tn90thresh", "tx90thresh_15days", "tavg90thresh_15days"):
        assert np.array_equal(standard[name], other[name], equal_nan=True), name
    assert other["txraw"].shape == (2, 8 * 365)


def test_threshold_time_noleap_reads_day_of_year_as_standard():
    """create.thresholds.file's ``%Y-%j`` in noleap: in a leap year day 60 is 1 March, and
    so is day 61; 31 December is never reached."""
    days = _year_days("noleap", 2000)
    offsets = _days_since(days, "2000-01-01")
    assert offsets[58:62].tolist() == [58, 59, 59, 60]
    assert offsets[-1] == 363
    assert _days_since(_year_days("noleap", 2001), "2001-01-01").tolist() == list(range(365))
    assert _days_since(_year_days("360_day", 2000), "2000-01-01").tolist() == list(range(360))
    assert _days_since(CalendarDays("360_day", [1951], [3], [1]), "1950-01-01").tolist() == [420]
    assert [pcict_calendar(c) for c in (None, "noleap", "360_day")] == [
        "proleptic_gregorian",
        "365",
        "360",
    ]


def test_hw_threshold_days():
    """climdex.hw matches each day's month and day with the days of 2001."""
    noleap = CalendarDays.whole_years("noleap", 2000, 2000)
    assert hw_threshold_days(noleap, 365).tolist() == list(range(365))
    d360 = CalendarDays.whole_years("360_day", 2000, 2000)
    j = hw_threshold_days(d360, 360)
    assert j[:30].tolist() == list(range(30))  # January 1-30
    assert j[30] == 31  # 1 February takes day 32's threshold
    assert j[57] == 58 and j[58] == j[59] == -1  # 28 February; 29 and 30 February have none
    assert j[60] == 59  # 1 March
    assert j[-5:].tolist() == [359, -1, -1, -1, -1]  # 26 December, then past day 360


def test_day_numbers_read_as_standard_dates():
    """write.climdex.results reads the extreme's date with as.Date."""
    d360 = CalendarDays.whole_years("360_day", 2001, 2001)
    pos = np.array([30, 58, 359])  # 1 February, 29 February, 30 December
    assert _day_numbers(d360, pos, "ANN").tolist()[:1] == [32.0]
    assert np.isnan(_day_numbers(d360, pos, "ANN")[1])
    assert _day_numbers(d360, pos, "ANN")[2] == 364
    assert _day_numbers(d360, pos, "MON")[[0, 2]].tolist() == [1.0, 30.0]
    leap = CalendarDays.whole_years("noleap", 2000, 2000)
    assert _day_numbers(leap, np.array([59, -1]), "ANN")[0] == 61  # 1 March 2000
    assert np.isnan(_day_numbers(leap, np.array([59, -1]), "ANN")[1])


def test_ehf_base_days_in_calendar():
    """hwEHF's 50% check divides by the days from 1 January to the calendar's last day."""
    assert base_data_sufficient(np.ones(360), 1971, 1972, "360_day")  # 360 of 719
    assert not base_data_sufficient(np.ones(359), 1971, 1972, "360_day")
    assert base_data_sufficient(np.ones(547), 1971, 1973, "noleap")  # 547 of 1094
    assert not base_data_sufficient(np.ones(547), 1971, 1973)  # 547 of 1095


def test_period_bounds_360_day():
    time = CalendarDays.whole_years("360_day", 1951, 1952)
    bounds, mid = _period_bounds(time, "ANN", "1950-01-01")
    assert bounds.tolist() == [[360, 719], [720, 1079]]
    assert mid.tolist() == [539.5, 899.5]
    bounds, _ = _period_bounds(time, "MON", "1950-01-01")
    assert bounds[:2].tolist() == [[360, 389], [390, 419]]


@pytest.mark.parametrize(("calendar", "dpy"), [("noleap", 365), ("360_day", 360)])
def test_grid_files_in_calendar(tmp_path, calendar, dpy):
    """Thresholds and index files of a grid in the calendar, identical rechunked or not,
    with dpy days of thresholds and of tx95t."""
    path = write_grid(tmp_path / "g.nc", calendar=calendar, start="1971-01-01", end="1976-12-31")
    files = {}
    for rechunk in (False, True):
        inp = open_grid([path], max_values=2 * 3 * 2200, rechunk=rechunk)
        out = tmp_path / f"r{rechunk}"
        out.mkdir()
        thr = write_grid_thresholds(inp, out / "thr.nc", 1971, 1975)
        write_grid_indices(inp, out, 1971, 1975, indices=["txx", "tx95t", "hw", "spi"])
        files[rechunk] = sorted(out.glob("*.nc"))
        with netCDF4.Dataset(thr) as nc:
            assert nc["tx90thresh"].shape == (dpy, 2, 3)
            assert nc["time"].calendar == calendar
            assert nc["base_time"].calendar == pcict_calendar(canonical_calendar(calendar))
            assert nc["base_time"].shape == (5 * dpy,)
    names = [p.name for p in files[False]]
    assert names == [p.name for p in files[True]]
    for a, b in zip(files[False], files[True], strict=True):
        with netCDF4.Dataset(a) as x, netCDF4.Dataset(b) as y:
            for var in x.variables:
                assert np.array_equal(x[var][:], y[var][:], equal_nan=True), (a.name, var)
    tx95t = next(p for p in files[False] if p.name.startswith("tx95t"))
    with netCDF4.Dataset(tx95t) as nc:
        assert nc["time"][:].tolist() == list(range(1, dpy + 1))
    txx = next(p for p in files[False] if p.name.startswith("txx_ANN"))
    with netCDF4.Dataset(txx) as nc:
        assert nc["time"].shape == (6,)
        assert np.ma.count(nc["txx"][:]) > 0


def test_thresholds_file_of_another_calendar(tmp_path):
    """A thresholds file with 365 days cannot be used for 360_day data."""
    past = write_grid(tmp_path / "p.nc", start="1971-01-01", end="1975-12-31")
    thr = write_grid_thresholds(open_grid([past]), tmp_path / "thr.nc", 1971, 1975)
    future = write_grid(tmp_path / "f.nc", calendar="360_day", start="1981-01-01", end="1982-12-31")
    with pytest.raises(ValueError, match="365 days of thresholds"):
        write_grid_indices(
            open_grid([future]), tmp_path / "out", 1971, 1975, thresholds_file=thr, indices=["fd"]
        )
