"""Alexandersson's standard normal homogeneity test, as R's ``trend::snh.test`` (trend
1.1.8), absolute (single-series) form.

With ``z = (x - mean(x)) / sd(x)``, ``T_k = k * mean(z[1:k])^2 + (n - k) *
mean(z[(k+1):n])^2`` for ``k = 1..n-1``; the statistic is ``T0 = max T_k`` and the change
point ``K`` the first ``k`` where it is reached (the last value before the break).

The p-value is from a Monte Carlo simulation, as R's (``mcsnht.f``): the share of
``m = 20000`` series of ``n`` standard normal values whose ``T0`` is greater than the
observed one. The simulated series are drawn with R's random numbers after ``set.seed(1)``
(:mod:`climpact.rrandom`), so the p-value is the one R gives after ``set.seed(1)``, not
one that differs by Monte Carlo error. As in R, the observed statistic standardises with
the sample standard deviation (``sd``, divisor ``n - 1``) but the simulation with the
population one (divisor ``n``); the Python port keeps this, so its p-values are R's.

The null distribution depends only on ``n``, so it is simulated once per length and
kept for the process.

Alexandersson, H. (1986): A homogeneity test applied to precipitation data. Journal of
Climatology 6, 661-675.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

from climpact.homogeneity.segmentation import SingleBreak
from climpact.rnumerics import r_mean, r_var
from climpact.rrandom import RNormal

SIMULATIONS = 20000  # trend::snh.test's default m
SEED = 1
_CHUNK = 2_000_000  # random values per batch of simulations


def _statistics(x: np.ndarray, sigma: np.ndarray | float) -> np.ndarray:
    """``T_k`` for ``k = 1..n-1`` of each row of ``x`` (already centred), standardised by
    ``sigma``."""
    n = x.shape[-1]
    z = x / sigma
    k = np.arange(1, n)
    head = np.cumsum(z, axis=-1)[..., :-1]
    tail = np.cumsum(z[..., ::-1], axis=-1)[..., -2::-1]
    return k * (head / k) ** 2 + (n - k) * (tail / (n - k)) ** 2


@lru_cache(maxsize=64)
def null_distribution(n: int, simulations: int = SIMULATIONS, seed: int = SEED) -> np.ndarray:
    """The simulated ``T0`` of ``simulations`` series of length ``n``, sorted (R's
    ``mcsnht`` after ``set.seed(seed)``)."""
    rng = RNormal(seed)
    out = np.empty(simulations)
    rows = max(1, _CHUNK // n)
    for start in range(0, simulations, rows):
        count = min(rows, simulations - start)
        x = rng.normal(count * n).reshape(count, n)
        centred = x - x.mean(axis=1, keepdims=True)
        sigma = np.sqrt((centred**2).sum(axis=1, keepdims=True) / n)
        out[start : start + count] = _statistics(centred, sigma).max(axis=1)
    out.sort()
    out.flags.writeable = False
    return out


def snht(x: np.ndarray, level: float) -> SingleBreak:
    """SNHT of ``x`` (no missing values, at least 3 of them); the critical value is the
    simulated ``T0`` that the statistic must reach for a p-value of at most ``1 - level``."""
    x = np.asarray(x, dtype=float)
    n = x.size
    mean = r_mean(x)
    sigma = math.sqrt(r_var(x))  # R's sd
    t = _statistics(x - mean, sigma)
    i = int(np.argmax(t))
    statistic = float(t[i])
    null = null_distribution(n)
    m = null.size
    p = (m - int(np.searchsorted(null, statistic, side="right"))) / m
    # p <= 1 - level exactly when at least round(level * m) simulated values are <= T0.
    critical = float(null[round(level * m) - 1])
    return SingleBreak(k=i + 1, statistic=statistic, p_value=p, critical_value=critical)
