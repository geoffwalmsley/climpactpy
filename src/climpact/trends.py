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
from dataclasses import dataclass

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
    s = slopes[~np.isnan(slopes)]  # R's sort drops NA and NaN
    zstat = qnorm(1 - (1 - level) / 2)
    c_alpha = math.sqrt(kendall_var_s(x, y)) * zstat
    n_prime = len(s)
    idx = [round((n_prime - c_alpha) / 2), round((n_prime + c_alpha) / 2)]
    # Only the two order statistics are needed: partition instead of sorting.
    positions = sorted({i - 1 for i in idx if 1 <= i <= n_prime})
    if positions:
        s = np.partition(s, positions)

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


def _alnorm(x: float, upper: bool) -> float:
    """Kendall's ``ALNORM`` (algorithm AS 66): the normal tail area below ``x``, or above
    it when ``upper``. Evaluated in double precision (the Fortran uses ``REAL``)."""
    if abs(x) >= 10.0:
        lower = 0.0 if x < 0 else 1.0
        return 1.0 - lower if upper else lower
    up, z = upper, x
    if z < 0:
        up, z = not up, -z
    if z <= 7.0 or (up and z <= 18.66):
        y = 0.5 * z * z
        if z > 1.28:
            p = (
                0.398942280385
                * math.exp(-y)
                / (
                    z
                    - 3.8052e-8
                    + 1.00000615302
                    / (
                        z
                        + 3.98064794e-4
                        + 1.98615381364
                        / (
                            z
                            - 0.151679116635
                            + 5.29330324926
                            / (
                                z
                                + 4.8385912808
                                - 15.1508972451
                                / (z + 0.742380924027 + 30.789933034 / (z + 3.99019417011))
                            )
                        )
                    )
                )
            )
        else:
            p = 0.5 - z * (
                0.398942280444
                - 0.399903438504
                * y
                / (
                    y
                    + 5.75885480458
                    - 29.8213557808 / (y + 2.62433121679 + 48.6959930692 / (y + 5.92885724438))
                )
            )
    else:
        p = 0.0
    return p if up else 1.0 - p


def mann_kendall_p(values: Sequence[float]) -> float:
    """Two-sided p-value of ``MannKendall(y)$sl`` (Kendall 2.2.2, Fortran ``TAUK2``).

    Missing values are dropped and ``x`` is ``1, 2, ...``. ``TAUK2``'s exact method is
    never reached (its flag for "no ties" is true only for a constant series, which
    returns before it), so the p-value is always the normal approximation with a
    continuity correction: ``z = (S -+ 1) / sqrt(Var(S))``, ``p = 2 min(Phi(z), 1 - Phi(z))``.
    A constant series, or one too short or too tied for ``Var(S)``, gives 1, as
    ``TAUK2`` leaves its p-value at 1 then. ``S`` and ``Var(S)`` are computed in single
    precision, as the Fortran does.
    """
    y = np.asarray(values, dtype=float)
    y = y[~np.isnan(y)].astype(np.float32)
    n = len(y)
    if n < 4 or (y == y[0]).all():
        return 1.0
    # S: +1 for each later value above, -1 for each below (x has no ties).
    diff = y[None, :] - y[:, None]
    s = int(np.sign(diff[np.triu_indices(n, 1)]).sum())
    var_s = kendall_var_s(np.arange(1, n + 1), y)
    if var_s <= 0:
        return 1.0
    score = s - 1 if s > 0 else s + 1 if s < 0 else 0
    z = float(np.float32(np.float32(score) / np.sqrt(np.float32(var_s))))
    prob = _alnorm(z, upper=False)
    return 2.0 * (1.0 - prob) if prob >= 0.5 else 2.0 * prob


@dataclass(frozen=True)
class PlotTrend:
    """The trend R draws and prints on an index plot (``plot.call``, ``plot.precindex``).

    ``slope``, ``lower`` and ``upper`` are those of the trend file (:func:`sen_trend`);
    ``intercept`` is ``zyp.sen``'s (the median of ``y - slope x``) with ``x`` counted from
    0 at the first value of the series; ``p_value`` is :func:`mann_kendall_p`.
    """

    lower: float
    slope: float
    upper: float
    intercept: float
    p_value: float

    @property
    def valid(self) -> bool:
        return not math.isnan(self.slope)


def plot_trend(values: Sequence[float]) -> PlotTrend:
    """Sen's slope, its bounds, intercept and Mann-Kendall p-value of a plotted series.

    All are missing when ``min_trend_data`` fails, as R prints "NO LINEAR TREND" then.
    """
    y1 = np.asarray(values, dtype=float)
    lower, slope, upper = sen_trend(y1)
    if math.isnan(slope):
        return PlotTrend(math.nan, math.nan, math.nan, math.nan, math.nan)
    keep = ~np.isnan(y1)
    x = np.arange(len(y1), dtype=float)[keep]
    intercept = r_median(y1[keep] - slope * x)
    return PlotTrend(lower, slope, upper, intercept, mann_kendall_p(y1))
