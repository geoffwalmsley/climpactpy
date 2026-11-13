"""Spell-duration helpers against values printed by R (tests/data/r_spell_durations.R)."""

import numpy as np
import pytest

from climpact.products.indices import (
    dual_threshold_duration,
    select_blocks_gt_length,
    threshold_exceedance_duration,
)

NA = np.nan
YEARS = np.repeat([2001, 2002], 20)
ZERO = np.zeros(40)


def same(a, b):
    np.testing.assert_array_equal(np.asarray(a, dtype=float), np.asarray(b, dtype=float))


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (0, [1, 1, 0, 1, 1, 1, 0, NA, 1, 1]),  # n < 1: returned unchanged, NA kept
        (1, [1, 1, 0, 1, 1, 1, 0, 0, 1, 1]),
        (2, [0, 0, 0, 1, 1, 1, 0, 0, 0, 0]),
        (10, [0] * 10),  # n >= length: all FALSE
    ],
)
def test_select_blocks_gt_length_matches_r(n, expected):
    d = np.array([1, 1, 0, 1, 1, 1, 0, NA, 1, 1], dtype=float)
    same(select_blocks_gt_length(d, n), expected)


X = np.array(
    [1, 1, 1, -1, 1, 1, NA, 1, 1, 1, 1, 1, 1, -1, -1, 1, 1, 1, 1, 1] + [-1] * 17 + [1, 1, 1],
    dtype=float,
)


@pytest.mark.parametrize(("min_length", "expected"), [(1, [NA, 3]), (2, [16, 3]), (3, [14, 3])])
def test_threshold_exceedance_duration_matches_r(min_length, expected):
    same(threshold_exceedance_duration(X, ZERO, ">", min_length, YEARS), expected)


def test_threshold_exceedance_duration_has_no_15_day_mask():
    # R's get.na.mask(is.na(...)) is always 1, so 16 missing days do not mask the year.
    x = np.array([NA] * 16 + [1] * 24)
    same(threshold_exceedance_duration(x, ZERO, ">", 2, YEARS), [4, 20])


T1 = np.array(
    [1, 1, -1, -1, -1, 1, 1, 1, -1, -1, -1, 1, 1, 1, -1, -1, -1, -1, -1, -1]
    + [1, 1, 1, -1, -1, -1, -1, 1, 1, 1, -1, -1, -1, -1, -1, 1, NA, 1, 1, 1],
    dtype=float,
)


@pytest.mark.parametrize(("n", "expected"), [(1, [1, 3]), (2, [1, 3]), (3, [0, 0])])
def test_dual_threshold_duration_matches_r(n, expected):
    # Events need more than n days; events 3 days apart or less count as one.
    same(dual_threshold_duration(T1, np.ones(40), ZERO, ZERO, ">", n, YEARS), expected)


def test_dual_threshold_duration_missing_second_variable():
    t2 = np.array([NA] * 20 + [1] * 20)
    same(dual_threshold_duration(T1, t2, ZERO, ZERO, ">", 2, YEARS), [0, 3])
