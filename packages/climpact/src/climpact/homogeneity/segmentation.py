"""Binary segmentation: find several breaks with a single-break test (Pettitt, SNHT).

The test runs on the whole series. If it finds a significant break (p-value at most
``1 - level``) that leaves at least ``min_n`` values on each side, the series is split
there and each part is tested the same way, until no part has a significant break or
is too short to test (fewer than ``2 * min_n`` values). The breaks are the accepted
splits. ``reference/r/run_homogeneity.R`` does the same in R with ``trend``'s tests.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SingleBreak:
    """A single-break test: ``k`` values come before the break (R's change point ``K``,
    the position of the last value before it, counting from 1)."""

    k: int
    statistic: float
    p_value: float
    critical_value: float


SingleTest = Callable[[np.ndarray, float], SingleBreak]


@dataclass(frozen=True)
class SegmentTest:
    """One test of the segmentation: values ``start:end`` of the series were tested and
    the break falls before value ``split`` (``start + result.k``)."""

    start: int
    end: int
    split: int
    result: SingleBreak
    accepted: bool


def binary_segmentation(
    x: np.ndarray, test: SingleTest, level: float, min_n: int
) -> list[SegmentTest]:
    """Every test the segmentation of ``x`` (no missing values) runs, in R's order: a
    segment, then the part before its break, then the part after it."""
    alpha = 1 - level
    done: list[SegmentTest] = []

    def segment(start: int, end: int) -> None:
        n = end - start
        if n < 2 * min_n:
            return
        result = test(x[start:end], level)
        accepted = result.p_value <= alpha and min_n <= result.k <= n - min_n
        split = start + result.k
        done.append(SegmentTest(start, end, split, result, accepted))
        if accepted:
            segment(start, split)
            segment(split, end)

    segment(0, len(x))
    return done
