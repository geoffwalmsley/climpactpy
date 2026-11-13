"""Heatwave aspects against values printed by R's get.hw.aspects (tests/data/r_hw_aspects.R).

The synthetic series exercise branches no reference station reaches: a heatwave cut 14
days after the season, ties in HWM, and missing flags and data inside a heatwave.

Two R behaviours are deliberately not copied (#51), so those values are worked out here
instead of taken from R: a heatwave covering the whole season (R: not counted) and a
series with no heatwave at all (R: HWN and HWF missing in every year).
"""

import numpy as np
import pandas as pd
import pytest

from climpact.products.heatwaves import heatwave_flags, hw_aspects, rle
from climpact.rnumerics import r_mean

NA = np.nan
DATES = pd.date_range("2001-01-01", "2003-12-31", freq="D")
YEARS = DATES.year.to_numpy()
MONTHS = DATES.month.to_numpy()
BASE = (200 + (np.arange(1, DATES.size + 1) * 37) % 101) / 10


def put(x, start, end, value):
    x[(DATES >= start) & (DATES <= end)] = value


def one_heatwave(start, end, data=BASE):
    """HWM, HWA, HWN, HWD, HWF of a season whose only heatwave covers start..end."""
    days = data[(DATES >= start) & (DATES <= end)]
    return [r_mean(days), days.max(), 1, days.size, days.size]


def north():
    f, d = np.zeros(DATES.size), BASE.copy()
    put(f, "2001-04-29", "2001-05-02", 1)
    put(f, "2001-06-10", "2001-06-12", 1)
    put(d, "2001-06-10", "2001-06-12", [30, 31, 32])
    put(f, "2001-07-01", "2001-07-03", 1)
    put(d, "2001-07-01", "2001-07-03", 31)
    put(f, "2001-09-20", "2001-10-31", 1)
    put(f, "2002-04-20", "2002-10-10", 1)
    put(f, "2003-04-28", "2003-05-01", 1)
    put(f, "2003-08-01", "2003-08-08", 1)
    put(f, "2003-08-04", "2003-08-04", NA)
    put(d, "2003-08-06", "2003-08-06", NA)
    return f, d


def south():
    f = np.zeros(DATES.size)
    put(f, "2001-12-29", "2002-01-03", 1)
    put(f, "2002-03-28", "2002-04-20", 1)
    put(f, "2002-11-05", "2002-11-07", 1)
    return f, BASE.copy()


# Rows HWM, HWA, HWN, HWD, HWF; columns 2001-2003 (R output in r_hw_aspects.R), except
# 2002, where the heatwave covers the whole season: R gives NA, NA, 0, NA, 0 (#51).
WHOLE_2002 = one_heatwave("2002-05-01", "2002-09-30")  # its in-season days
R_NORTH = [
    [27.955500000000001, WHOLE_2002[0], 25.966666666666669],
    [32.0, WHOLE_2002[1], 27.600000000000001],
    [4, 1, 3],
    [25, 153, 4],
    [33, 153, 8],
]
R_SOUTH = [
    [25.524999999999999, 26.166666666666668, NA],
    [29.899999999999999, 29.199999999999999, NA],
    [2, 1, NA],
    [18, 3, NA],
    [24, 3, NA],
]


@pytest.mark.parametrize(
    ("make", "northern", "namask", "expected"),
    [
        (north, True, 1.0, R_NORTH),
        (south, False, np.array([1, 1, NA]), R_SOUTH),
    ],
    ids=["north", "south"],
)
def test_hw_aspects_match_r(make, northern, namask, expected):
    flags, data = make()
    out = hw_aspects(flags, data, YEARS, MONTHS, northern, namask)
    np.testing.assert_array_equal(out, np.array(expected, dtype=float))


NO_HEATWAVE = [NA, NA, 0, NA, 0]


@pytest.mark.parametrize(
    ("northern", "start", "end", "year", "counted"),
    [
        # Under way before the season and still running after it: its in-season days.
        (True, "2002-04-20", "2002-10-10", 1, ("2002-05-01", "2002-09-30")),
        (False, "2001-10-20", "2002-04-30", 0, ("2001-11-01", "2002-03-31")),
        # Starting on the season's first day: cut 14 days after the season, as any
        # heatwave that begins in the season and runs past it.
        (True, "2002-05-01", "2002-11-30", 1, ("2002-05-01", "2002-10-14")),
        (False, "2001-11-01", "2002-05-31", 0, ("2001-11-01", "2002-04-14")),
    ],
    ids=["north-under-way", "south-under-way", "north-first-day", "south-first-day"],
)
def test_heatwave_covering_the_whole_season_counts(northern, start, end, year, counted):
    flags = np.zeros(DATES.size)
    put(flags, start, end, 1)
    out = hw_aspects(flags, BASE, YEARS, MONTHS, northern)
    expected = [NO_HEATWAVE] * 3
    expected[year] = one_heatwave(*counted)
    if not northern:
        expected[2] = [NA] * 5  # the last southern season is incomplete
    np.testing.assert_array_equal(out, np.array(expected, dtype=float).T)


@pytest.mark.parametrize("northern", [True, False], ids=["north", "south"])
def test_no_heatwave_at_all_gives_zero_heatwaves(northern):
    out = hw_aspects(np.zeros(DATES.size), BASE, YEARS, MONTHS, northern)
    expected = [NO_HEATWAVE, NO_HEATWAVE, NO_HEATWAVE if northern else [NA] * 5]
    np.testing.assert_array_equal(out, np.array(expected, dtype=float).T)


def test_season_without_usable_values_is_missing():
    data = BASE.copy()
    put(data, "2002-05-01", "2002-09-30", NA)  # e.g. no data or no threshold
    out = hw_aspects(np.zeros(DATES.size), data, YEARS, MONTHS, True)
    expected = [NO_HEATWAVE, [NA] * 5, NO_HEATWAVE]
    np.testing.assert_array_equal(out, np.array(expected, dtype=float).T)


def test_all_missing_data_gives_all_missing():
    out = hw_aspects(np.zeros(DATES.size), np.full(DATES.size, NA), YEARS, MONTHS, True)
    assert np.isnan(out).all()


def test_rle_keeps_each_missing_value_apart():
    lengths, values = rle(np.array([1, 1, NA, NA, 0, 0, 0, 1]))
    np.testing.assert_array_equal(lengths, [2, 1, 1, 3, 1])
    np.testing.assert_array_equal(values, [1, NA, NA, 0, 1])


def test_heatwave_flags_need_three_days_and_treat_missing_as_false():
    x = np.array([5, 5, 0, 5, 5, 5, NA, 5, 5, 5, 5])
    np.testing.assert_array_equal(
        heatwave_flags(x, np.ones(x.size)), [0, 0, 0, 1, 1, 1, 0, 1, 1, 1, 1]
    )
