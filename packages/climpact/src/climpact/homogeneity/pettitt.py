"""Pettitt's test for a single change point, as R's ``trend::pettitt.test`` (trend 1.1.8).

A non-parametric (rank) test for a shift in the median. With ``r`` the ranks of the
series (ties get their average rank, as R's ``rank``), ``U_k = 2 * sum(r[1:k]) - k * (n +
1)`` for ``k = 1..n``; the statistic is ``U* = max |U_k|`` and the change point ``K`` the
first ``k`` where it is reached (the last value before the break). The p-value is
Pettitt's approximation ``min(1, 2 * exp(-6 * U*^2 / (n^3 + n^2)))``.

Pettitt, A. N. (1979): A non-parametric approach to the change-point problem. Applied
Statistics 28, 126-135.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.stats import rankdata

from climpact.homogeneity.segmentation import SingleBreak


def pettitt(x: np.ndarray, level: float) -> SingleBreak:
    """Pettitt's test of ``x`` (no missing values); the critical value is the ``U*`` at
    which the approximate p-value is ``1 - level``."""
    x = np.asarray(x, dtype=float)
    n = x.size
    ranks = rankdata(x)  # exact multiples of 0.5, so the sums below are exact
    k = np.arange(1, n + 1)
    u = np.abs(2 * np.cumsum(ranks) - k * (n + 1))
    i = int(np.argmax(u))
    statistic = float(u[i])
    p = min(1.0, 2.0 * math.exp((-6.0 * statistic**2) / (n**3 + n**2)))
    alpha = 1 - level
    critical = math.sqrt(-math.log(alpha / 2) * (n**3 + n**2) / 6)
    return SingleBreak(k=i + 1, statistic=statistic, p_value=p, critical_value=critical)
