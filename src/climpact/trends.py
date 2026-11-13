"""Sen's slope and its 95% confidence interval, as Climpact's trend file computes them.

Climpact 3.4.3 computes the trend of every plotted series with zyp 0.11-1:
``zyp.sen(y ~ x)`` for the slope (the median of the pairwise slopes) and
``confint.zyp(zsen, level = 0.95)`` for its bounds, and writes a trend only when
``min_trend_data`` passes (``services/plot_indices.R``). ``confint.zyp`` takes
``Var(S)`` from Kendall 2.2.2's ``Kendall(x, y)``, which calls the Fortran routine
``TAUK2`` with ``x`` and ``y`` converted to single precision and computes ``Var(S)`` in
single-precision arithmetic. All of this is ported exactly:

- :func:`sen_slope`: ``zyp.sen``'s pairwise slopes ``(y[j] - y[j + i]) / (x[j] - x[j + i])``
  and R's ``median`` (the mean of the two middle values in extended precision, R's
  ``mean``).
- :func:`kendall_var_s`: ``TAUK2``'s ``VARS`` in float32, including its quirk that a
  series is treated as untied only when it is constant (then ``VARS`` is never set and
  stays 0).
- :func:`confint_zyp`: the bounds ``slopes[round((n' -+ c) / 2)]`` with
  ``c = sqrt(Var(S)) * qnorm(0.975)`` (R's ``qnorm``, :func:`climpact.rdist.qnorm`) and
  ``round`` to even.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from climpact.rdist import qnorm
from climpact.rnumerics import r_mean

# server/global_variables.r
MIN_TREND = 10  # minimum number of valid values
MIN_TREND_PROPORTION = 0.7  # minimum fraction of the series that is valid

NA_TREND = (math.nan, math.nan, math.nan)


def min_trend_data(values: Sequence[float]) -> bool:
    """``min_trend_data``: at least 70% of the series and at least 10 values are valid."""
    values = np.asarray(values, dtype=float)
    valid = int(np.count_nonzero(~np.isnan(values)))
    return len(values) > 0 and valid / len(values) >= MIN_TREND_PROPORTION and valid >= MIN_TREND


def pairwise_slopes(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """``zyp.sen``'s slopes: for lag ``i = 1 .. n - 1``, ``(y[j] - y[j+i]) / (x[j] - x[j+i])``,
    concatenated in that order."""
    n = len(x)
    if n < 2:
        return np.array([], dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.concatenate([(y[: n - i] - y[i:]) / (x[: n - i] - x[i:]) for i in range(1, n)])


def r_median(values: np.ndarray) -> float:
    """R ``median`` of values without missing ones (NaN when empty)."""
    n = len(values)
    if n == 0:
        return math.nan
    half = (n + 1) // 2
    if n % 2:
        return float(np.partition(values, half - 1)[half - 1])
    s = np.partition(values, (half - 1, half))  # sort(x, partial = half + 0:1)
    return r_mean(s[half - 1 : half + 1])


def sen_slope(x: np.ndarray, y: np.ndarray) -> tuple[float, np.ndarray]:
    """``zyp.sen(y ~ x)``: the median of the finite pairwise slopes, and all the slopes."""
    slopes = pairwise_slopes(np.asarray(x, dtype=float), np.asarray(y, dtype=float))
    return r_median(slopes[np.isfinite(slopes)]), slopes


def kendall_var_s(x: np.ndarray, y: np.ndarray) -> float:
    """``Kendall(x, y)$varS`` (Kendall 2.2.2, Fortran ``TAUK2``), in single precision.

    ``x`` and ``y`` are passed to Fortran as ``REAL``, so ties are decided in float32,
    and every quantity is a float32 computed in the Fortran's order. ``TAUK2`` computes
    ``VARS`` only when neither series is constant (its ``SW`` flag is true when *all*
    values are equal, despite its comment); otherwise ``VARS`` keeps its input value, 0.
    Raises ``ValueError`` for fewer than 3 values, as ``Kendall`` stops then.
    """
    f = np.float32
    xs = np.asarray(x, dtype=float).astype(f)
    ys = np.asarray(y, dtype=float).astype(f)
    n = len(xs)
    if n != len(ys):
        raise ValueError("length of inputs muct be equal!")
    if n < 3:
        raise ValueError("length(x)<3")
    if (xs == xs[0]).all() or (ys == ys[0]).all():
        return 0.0

    def tie_sums(v: np.ndarray) -> tuple[np.float32, np.float32, np.float32]:
        # For each I, TMP = 1 + the later values equal to V(I) not yet counted, so a tie
        # group of t values adds t (t - 1) ... once, at its first value, and every other I
        # adds exactly 0. The sums are accumulated in float32 in order of first value.
        s, a1, a2 = f(0), f(0), f(0)
        one, two, five = f(1), f(2), f(5)
        _, first, counts = np.unique(v, return_index=True, return_counts=True)
        counts = counts[np.argsort(first)]
        for t in counts[counts > 1]:
            tmp = f(t)
            s = f(s + f(tmp * f(tmp - one)))
            a1 = f(a1 + f(f(tmp * f(tmp - one)) * f(two * tmp + five)))
            a2 = f(a2 + f(f(tmp * f(tmp - one)) * f(tmp - two)))
        return s, a1, a2

    sumt, suma1, suma2 = tie_sums(xs)
    sumu, sumb1, sumb2 = tie_sums(ys)
    cn = f(f(n) * f(n - 1))
    dn = f(f(0.5) * cn)
    # D1 = SQRT(DN - 0.5 * SUMT) <= 0 (a negative argument gives NaN, which passes).
    if f(dn - f(f(0.5) * sumt)) == 0 or f(dn - f(f(0.5) * sumu)) == 0:
        return 0.0  # IER = 30, VARS not set
    vars1 = f(f(f(f(cn * f(2 * n + 5)) - suma1) - sumb1) / f(18))
    vars2 = f(f(suma2 * sumb2) / f(f(f(9) * cn) * f(n - 2)))
    vars3 = f(f(sumt * sumu) / f(cn + cn))
    return float(f(f(vars1 + vars2) + vars3))


def confint_zyp(x: np.ndarray, y: np.ndarray, slopes: np.ndarray, level: float = 0.95):
    """Slope bounds of ``confint.zyp(zsen, level)``: ``(lower, upper)``.

    ``idx = round((n' - c) / 2), round((n' + c) / 2)`` with ``n'`` the number of
    pairwise slopes and ``c = sqrt(Var(S)) * qnorm(1 - (1 - level) / 2)``; the bounds are
    the sorted slopes at those (1-based) positions. Raises ``ValueError`` where R's
    ``confint.zyp`` stops with an error.
    """
    s = np.sort(slopes[~np.isnan(slopes)])  # R's sort drops NA and NaN
    zstat = qnorm(1 - (1 - level) / 2)
    c_alpha = math.sqrt(kendall_var_s(x, y)) * zstat
    n_prime = len(s)
    idx = [round((n_prime - c_alpha) / 2), round((n_prime + c_alpha) / 2)]

    def at(i: int) -> float:
        return float(s[i - 1]) if 1 <= i <= n_prime else math.nan

    picked = [at(i) for i in idx if i != 0]  # index 0 selects nothing
    if len(picked) == 1:  # res[2, ] <- one value: recycled to both bounds
        picked = picked * 2
    if len(picked) != 2:
        raise ValueError("replacement has length zero")
    return picked[0], picked[1]


def sen_trend(values: Sequence[float], x0: int = 0) -> tuple[float, float, float]:
    """``(lower bound, slope, upper bound)`` of a series, as ``plot.call`` computes them.

    ``x`` is ``x0, x0 + 1, ...`` with the missing values left out. All three are missing
    when ``min_trend_data`` fails or ``confint.zyp`` stops with an error.
    """
    y1 = np.asarray(values, dtype=float)
    keep = ~np.isnan(y1)
    x = (np.arange(len(y1)) + x0).astype(float)[keep]
    y = y1[keep]
    if not min_trend_data(y1):
        return NA_TREND
    slope, slopes = sen_slope(x, y)
    try:
        lower, upper = confint_zyp(x, y, slopes)
    except ValueError:
        return NA_TREND
    return lower, slope, upper
