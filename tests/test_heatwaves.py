"""Heatwave aspects against values printed by R's get.hw.aspects (tests/data/r_hw_aspects.R).

The synthetic series exercise branches no reference station reaches: a heatwave cut 14
days after the season, one covering the whole season (not counted), ties in HWM, missing
flags and data inside a heatwave, and a run with no heatwave at all.
"""

import numpy as np
import pandas as pd
import pytest

from climpact.products.heatwaves import heatwave_flags, hw_aspects, rle

NA = np.nan
DATES = pd.date_range("2001-01-01", "2003-12-31", freq="D")
YEARS = DATES.year.to_numpy()
MONTHS = DATES.month.to_numpy()
BASE = (200 + (np.arange(1, DATES.size + 1) * 37) % 101) / 10


def put(x, start, end, value):
    x[(DATES >= start) & (DATES <= end)] = value


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


# Rows HWM, HWA, HWN, HWD, HWF; columns 2001-2003 (R output in r_hw_aspects.R).
R_NORTH = [
    [27.955500000000001, NA, 25.966666666666669],
    [32.0, NA, 27.600000000000001],
    [4, 0, 3],
    [25, NA, 4],
    [33, 0, 8],
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
        (lambda: (np.zeros(DATES.size), BASE), True, 1.0, [[NA] * 3] * 5),
    ],
    ids=["north", "south", "none"],
)
def test_hw_aspects_match_r(make, northern, namask, expected):
    flags, data = make()
    out = hw_aspects(flags, data, YEARS, MONTHS, northern, namask)
    np.testing.assert_array_equal(out, np.array(expected, dtype=float))


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
