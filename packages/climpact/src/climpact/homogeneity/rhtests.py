"""RHtestsV4's changepoint detection: the PMFred and PMTred tests.

A port of the detection in RHtestsV4 (``RHtestsV4_20190301.r`` from
https://github.com/ECCC-CDAS/RHtests, commit 827b2b2254da41f3a3c57cb61390d9f57a22e07f):

- :func:`pmf` is ``FindU``: the penalised maximal F test (PMFred, Wang 2008b), which needs
  no reference series. It fits a two-phase regression with a common linear trend, so a
  trend is not mistaken for a shift. Monthly series have their annual cycle removed first.
- :func:`pmt` is ``FindU.wRef``, the penalised maximal t test (PMTred, Wang et al. 2007),
  called with a reference series of zeros: the series tested is then the base series minus
  the mean of each calendar month (of the whole series for an annual one). PMT assumes the
  tested series has no trend (RHtests uses it on base-minus-reference differences), so a
  trend in an absolute series can show up as changepoints.

Both embed the test in RHtests' recursive search for multiple changepoints (Wang 2008a)
and account for lag-1 autocorrelation empirically: each changepoint is reported with the
critical value at the autocorrelation estimate and at the ends of its 95% confidence
interval, and labelled as RHtests labels it in its ``_1Cs.txt`` file: ``"Yes"``
(significant even at the upper critical value), ``"?"`` (significant at the lower one
only: RHtests keeps it only if station metadata support it) or ``"No"``. Only the
detection is ported: no mean or quantile-matching adjustment, plots or files.

The code follows R's statement order, including its quirks, which are marked "R quirk"
below. Positions are kept as R's 1-based indices where they come from R (``Ips``: the
last value of each segment, the last one being N), so ``y[i0:i2]`` here is R's
``Y[(I0+1):I2]``. Least-squares fits use the normal equations, as R's
``solve(t(D)%*%D)%*%t(D)%*%X`` does; ``pt`` and ``pf`` are scipy's t and F distributions.
The scans for the most likely changepoint of a segment (``PMFT``, ``PTK``) are vectorised
with cumulative sums; where two positions come within 1e-9 of each other, those positions
are recomputed as R computes them before the first maximum is taken, as R's loops do.

R refuses some series; :class:`RHtestsError` is raised for them with RHtests' message:
fewer than 10 pairs of consecutive values (PMF: ``Read``, "too many missing values ... to
estimate autocorrelation"); a calendar month with fewer than 5 values, or fewer than 11
values in all (PMT: ``Read.wRef``, "input data too few"). It is also raised for a series
with no values (R fails with an unrelated error) and, for PMF, for fewer than 20 values:
R runs then, but its scan for the first changepoint goes from position 10 *down* to N - 10
and its critical values are interpolated towards 0 below the table's smallest N (20), so
its result means nothing.

RHtests is (c) Environment and Climate Change Canada (Xiaolan L. Wang and Yang Feng),
licensed under the GNU Lesser General Public License 2.1. The critical values are its
tables of empirical percentiles of PFmax and PTmax (``data/``, extracted from the R code by
``reference/homogeneity/extract_rhtests_tables.py``).

References:

- Wang, X. L., Q. H. Wen and Y. Wu, 2007: Penalized maximal t test for detecting
  undocumented mean change in climate data series. J. Appl. Meteor. Climatol., 46, 916-931.
- Wang, X. L., 2008a: Accounting for autocorrelation in detecting mean shifts in climate
  data series using the penalized maximal t or F test. J. Appl. Meteor. Climatol., 47,
  2423-2444.
- Wang, X. L., 2008b: Penalized maximal F test for detecting undocumented mean shift
  without trend change. J. Atmos. Oceanic Technol., 25, 368-384.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import cache
from importlib import resources

import numpy as np
from scipy import stats

LEVELS = (0.75, 0.8, 0.9, 0.95, 0.99, 0.9999)
"""The confidence levels RHtests has critical values for (``p.lev``)."""

_PF_TABLE = "pfmax31red_nmin10.csv"
_PT_TABLE = "ptmaxred_nmin5.csv"
_PMF_NMIN = 10  # FindU's Nmin: the shortest segment
_PMT_NMIN = 5  # FindU.wRef's Nmin
_TIE = 1e-9  # relative distance below which scan values are recomputed as R does


class RHtestsError(ValueError):
    """RHtests cannot test the series (too few values, or too few consecutive ones)."""


@dataclass(frozen=True)
class Changepoint:
    """A changepoint as RHtests reports it (``_1Cs.txt`` and ``_Ustat.txt``).

    ``position`` is the index, in the input arrays, of the last period before the shift
    (RHtests' ``IY0[Ic]``). ``statistic`` is PFmax or PTmax; ``cv`` its critical value at
    the series' lag-1 autocorrelation, ``cv_low`` and ``cv_high`` at the ends of the
    autocorrelation's 95% confidence interval, which decide ``label`` (``"Yes"``, ``"?"``
    or ``"No"``). ``prob`` is the nominal confidence of the unpenalised test on the
    prewhitened series, and ``prob_low``/``prob_high`` its range. ``nseg`` is the length of
    the two segments either side (RHtests' ``Nseg``), and ``step`` the size of the shift
    (the mean after minus the mean before; PMF: with the common trend removed).
    """

    position: int
    label: str
    statistic: float
    cv: float
    cv_low: float
    cv_high: float
    prob: float
    prob_low: float
    prob_high: float
    nseg: int
    step: float


@dataclass(frozen=True)
class Result:
    """The changepoints of one series by one method (``"pmf"`` or ``"pmt"``), in date
    order, and the lag-1 autocorrelation of the final fit's residuals."""

    method: str
    changepoints: tuple[Changepoint, ...]
    cor: float


# ---- critical-value tables -------------------------------------------------------------


def _pkth(level: float) -> int:
    for i, allowed in enumerate(LEVELS, start=1):
        if level == allowed:
            return i
    raise ValueError(f"level must be one of {', '.join(map(str, LEVELS))}, got {level!r}")


@cache
def _table_rows(name: str) -> np.ndarray:
    with resources.files("climpact.homogeneity").joinpath("data", name).open() as f:
        rows = list(csv.reader(f))[1:]
    return np.array(rows, dtype=float)


def _seq_length(start: float, end: float, n: int) -> np.ndarray:
    """R's ``seq(start, end, length = n)``."""
    if n <= 2:
        return np.array([start, end])[:n]
    if start == end:
        return np.full(n, start)
    n1 = n - 1
    return np.concatenate(([start], start + np.arange(1, n1) * ((end - start) / n1), [end]))


@cache
def _base_table(name: str, pkth: int) -> tuple[np.ndarray, np.ndarray]:
    """``readPTtable``/``readPFtable`` up to the table's largest N: the autocorrelations
    ``phi`` (45) and the critical values, ``table[n, j]`` for series length ``n``."""
    rows = _table_rows(name)
    levels = list(dict.fromkeys(rows[:, 0].astype(int)))
    phi = np.concatenate(([-0.975], rows[:44, 7]))
    table = np.zeros((levels[-1] + 1, 45))
    for i in range(len(levels)):
        for j in range(44):
            if i == 0:
                # Linear from 0 at N = 1 to the first level.
                start, end, ind1, ind2 = 0.0, rows[j, pkth], 1, levels[0]
            else:
                start = rows[(i - 1) * 44 + j, pkth]
                end = rows[i * 44 + j, pkth]
                ind1, ind2 = levels[i - 1], levels[i]
            table[ind1 : ind2 + 1, j + 1] = _seq_length(start, end, ind2 - ind1 + 1)
        # Column 1 (phi = -0.975) is extrapolated from the columns for -0.2 and -0.15.
        block = table[ind1 : ind2 + 1]
        block[:, 0] = block[:, 1] - (phi[1] - phi[0]) * (block[:, 2] - block[:, 1]) / (
            phi[2] - phi[1]
        )
    return phi, table


@cache
def _critical_table(name: str, pkth: int, nx: int) -> tuple[np.ndarray, np.ndarray]:
    """The table R builds for a series of length ``nx``: above the largest N it is
    extrapolated linearly from the last two levels."""
    phi, base = _base_table(name, pkth)
    nmax = base.shape[0] - 1
    if nx <= nmax:
        return phi, base
    rows = _table_rows(name)
    levels = list(dict.fromkeys(rows[:, 0].astype(int)))
    table = np.zeros((nx + 1, 45))
    table[: nmax + 1] = base
    for j in range(45):
        delta = (base[levels[-1], j] - base[levels[-2], j]) / (levels[-1] - levels[-2])
        table[nmax : nx + 1, j] = base[levels[-1], j] + np.arange(nx - nmax + 1) * delta
    return phi, table


def _critical_value(phi: np.ndarray, table: np.ndarray, cor: float, n: int) -> float:
    """``getPTx95`` and ``getPFx95``: the critical value for length ``n`` at
    autocorrelation ``cor``, interpolated linearly in ``phi``.

    R quirk: ``getPFx95`` looks for ``phi[i] < cor < phi[i+1]``, so a ``cor`` exactly on
    an interior grid value finds no interval and R stops (or uses a stale global ``Kr1``).
    Here both look for ``phi[i] <= cor < phi[i+1]``, as ``getPTx95`` does, which gives the
    grid value.
    """
    if np.isnan(cor):
        raise RHtestsError("the lag-1 autocorrelation of the series cannot be estimated")
    row = table[n]
    if cor <= phi[0]:
        return float(row[0])
    if cor >= phi[-1]:
        return float(row[-1])
    i = int(np.searchsorted(phi, cor, side="right")) - 1
    return float(row[i] + (row[i + 1] - row[i]) * (cor - phi[i]) / (phi[i + 1] - phi[i]))


# ---- penalty functions ----------------------------------------------------------------


def _pow(x, y):
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.power(x, y)


@cache
def pk_pmft(n: int) -> np.ndarray:
    """``Pk.PMFT(N)``: the PMF penalty for a changepoint after position k = 1 ... N-1."""
    big_n = n
    k = np.arange(1, big_n, dtype=float)
    m = (big_n - 1) // 2
    if (big_n - 1) % 2 == 0:
        kmin = np.concatenate((np.arange(1, m + 1), np.arange(m, 0, -1)))
    else:
        kmin = np.concatenate((np.arange(1, m + 2), np.arange(m, 0, -1)))
    kmin = kmin.astype(float)
    w = int(np.floor(11 * big_n / 50 if big_n <= 500 else 21 * big_n / 100))
    a = np.abs(1 - 2 * k / big_n)
    b = np.log(big_n)
    c = np.log(b)
    d = np.log(np.log(big_n + 150))
    half = big_n // 2
    q = np.concatenate(
        (
            np.abs(1 - 50 * k[:half] / (big_n * 11)),
            np.abs(1 - (50 * k[half:] - 28 * big_n) / (big_n * 11)),
        )
    )
    tmp1 = 11 / b**3
    with np.errstate(divide="ignore"):  # Kmin = 100 gives Inf, replaced below as in R
        tmp2 = np.abs(2 * c**4 / (900 - 9 * kmin))
    s = np.where(tmp1 < tmp2, tmp1, tmp2)
    s[kmin == 100] = tmp1
    e = b * (3 - c) / 6
    f1 = 1 - _pow(q, e)
    f2 = 1 + _pow(a, e)
    f = np.concatenate((f1[:w], f2[w : big_n - w - 1], f1[big_n - w - 1 :]))
    v1 = (11.7 - s) * b**0.01 - 11.8
    v2 = ((c + 353) * big_n**0.01 - 340) / 200
    v = np.concatenate((v1[:w], np.full(big_n - 2 * w - 1, v2), v1[big_n - w - 1 :]))
    fv = _pow(f, v)
    p1 = ((64 * big_n ** (1 / 40) + 35 - c) * fv) / 100
    p2 = min(1.0, (98000 + 6 * big_n) / 100000) * fv
    p0 = np.concatenate((p1[:w], p2[w : big_n - w - 1], p1[big_n - w - 1 :]))
    p = p0.copy()
    if big_n >= 40:
        ell = int(np.floor(1 + (317 * big_n**0.75 - 2867) / 1000))
        if big_n <= 100:
            delta = np.full(big_n - 1, d ** (1 / 3) * (p0[ell] - p0[ell - 1]) + c**3 / (big_n * 5))
        else:
            delta = np.full(big_n - 1, np.nan)
            denominator = ell + b - 2 * c - 1
            delta[:ell] = (p0[ell - 1] - p0[0]) * _pow(a[:ell], c**3) / denominator
            delta[big_n - ell - 1 :] = (
                (p0[big_n - ell - 1] - p0[big_n - 2])
                * _pow(a[big_n - ell - 1 :], c**3)
                / denominator
            )
        lo = np.arange(1, ell + 1)
        p[:ell] = p0[ell - 1] - (ell - lo) * delta[:ell]
        hi = np.arange(big_n - ell, big_n)
        p[big_n - ell - 1 :] = p0[big_n - ell - 1] - (hi - big_n + ell) * delta[big_n - ell - 1 :]
    p.setflags(write=False)
    return p


@cache
def pk_pmt(n: int) -> np.ndarray:
    """``Pk.PMT(N)``: the PMT penalty for a changepoint after position k = 1 ... N-1."""
    big_n = n
    k = np.arange(1, big_n, dtype=float)
    a = np.abs(1 - 2 * k / big_n)
    b = np.log(big_n)
    c = np.log(b)
    d = np.log(np.log(big_n + 150))
    if big_n <= 100:
        f = 1 - _pow(a, (7 * b - 2 * b * c) / 10)
        v = (15 * c**0.5 - 11) / 100
    else:
        f = 1 - _pow(a, 11 * b * c / 50)
        v = (2 * c**2 + 2 * c - 1) / 100
    po = (11 * c ** (9 / 8) + 195) * _pow(f, v) / 200
    k1 = int(np.sum(po[: big_n // 2] < 1)) + 1
    ell = k1 // 2 + 2 if 10 < big_n < 50 else k1 // 2 + 1
    if big_n <= 10:
        delta = np.full(big_n - 1, d**0.5 * (po[ell] - po[ell - 1]))
    elif big_n <= 100:
        step = d ** (1 / 3) * (po[ell] - po[ell - 1]) + 3 / (10 * big_n ** (4 / 3))
        delta = np.full(big_n - 1, step)
    else:
        delta = np.zeros(big_n - 1)
        delta[:ell] = (po[ell - 1] - po[0]) * _pow(a[:ell], c**3) / (2 * ell - 4)
        delta[big_n - ell - 1 :] = (
            (po[big_n - ell - 1] - po[big_n - 2]) * _pow(a[big_n - ell - 1 :], c**3) / (2 * ell - 4)
        )
    p = po.copy()
    # In R's order: the second assignment reads P after the first one changed it.
    p[:ell] = p[ell - 1] - delta[:ell] * (ell - np.arange(1, ell + 1))
    p[big_n - ell - 1 :] = p[big_n - ell - 1] - delta[big_n - ell - 1 :] * (
        np.arange(big_n - ell, big_n) - big_n + ell
    )
    p.setflags(write=False)
    return p


# ---- shared pieces ----------------------------------------------------------------------


def _solve(design: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.linalg.solve(design.T @ design, design.T @ y)


def _ls_matrix(y: np.ndarray, t: np.ndarray, ic: int | None) -> tuple[np.ndarray, float]:
    """``LSmatrix``: fit intercept, trend and (``ic``) a step after position ``ic``;
    returns the residuals and the SSE."""
    columns = [np.ones(len(y)), t - t.mean()]
    if ic is not None:
        step = np.zeros(len(y))
        step[ic:] = 1
        columns.append(step)
    design = np.column_stack(columns)
    resi = y - design @ _solve(design, y)
    return resi, float(np.sum(resi**2))


def _ls_multiple(y: np.ndarray, t: np.ndarray, ips: list[int]) -> tuple[np.ndarray, np.ndarray]:
    """``LSmultiple``: intercept, trend and a step for every segment after the first;
    returns the coefficients and the residuals."""
    n = len(y)
    columns = [np.ones(n), t - t.mean()]
    for i in range(len(ips) - 1):
        step = np.zeros(n)
        step[ips[i] : ips[i + 1]] = 1
        columns.append(step)
    design = np.column_stack(columns)
    sig = _solve(design, y)
    return sig, y - design @ sig


def _autocor(y: np.ndarray, flg: np.ndarray) -> tuple[float, float, float]:
    """``autocorlh``: lag-1 autocorrelation of ``y`` over consecutive pairs (``flg``), and
    the 95% interval from Fisher's z."""
    n = len(y)
    d = y - y.mean()
    s1 = np.sum((d**2 * flg)[: n - 1])
    s2 = np.sum((d * (np.append(y[1:], 0) - y.mean()) * flg)[: n - 1])
    with np.errstate(invalid="ignore", divide="ignore"):
        cor = s2 / s1
        z = 0.5 * np.log((1 + cor) / (1 - cor))
        df = np.sum(flg[: n - 1])
        cl = np.tanh(z - 1.96 / np.sqrt(df - 3))
        ch = np.tanh(z + 1.96 / np.sqrt(df - 3))
    return float(cor), float(min(cl, ch)), float(max(cl, ch))


def _segments(ips: list[int]):
    """(start, end) slices of the segments ending at ``ips`` (R's ``I1:I2``)."""
    start = 0
    for end in ips:
        yield start, end
        start = end


def _rphi(y0: np.ndarray, ips: list[int], flg: np.ndarray):
    """``Rphi``: autocorrelation of ``y0`` about its segment means, and ``y0``
    prewhitened with it and with the ends of its interval (W, WL, WU).

    R quirk: ``W[i]`` is the prewhitened value when ``IY0flg[i]`` is 1, which says whether
    values i and i+1 are consecutive, not i-1 and i as the prewhitening needs (unlike
    ``LSmultipleRed``).
    """
    y = y0.copy()
    means = []
    for i1, i2 in _segments(ips):
        mu = y0[i1:i2].mean()
        means.append(mu)
        y[i1:i2] = y0[i1:i2] - mu
    cor, corl, corh = _autocor(y, flg)
    out = []
    for r in (cor, corl, corh):
        w = y.copy()
        w[1:] = y[1:] - y[:-1] * r
        w = np.where(flg == 1, w, y)
        for (i1, i2), mu in zip(_segments(ips), means, strict=True):
            w[i1:i2] += mu
        out.append(w)
    return cor, corl, corh, out[0], out[1], out[2]


def _first_max(values: np.ndarray, exact) -> int:
    """Index of the first maximum of ``values``, as R's loop ``if (x > best)`` finds it.
    Values within a relative 1e-9 of the maximum are recomputed with ``exact(i)``."""
    best = int(np.argmax(values))
    top = values[best]
    close = np.flatnonzero(values >= top - _TIE * abs(top))
    if len(close) == 1:
        return best
    recomputed = [exact(int(i)) for i in close]
    return int(close[int(np.argmax(recomputed))])


# ---- PMF (FindU) ------------------------------------------------------------------------


@dataclass
class _Series:
    """What RHtests' ``Read`` (or ``Read.wRef``) leaves in its global variables."""

    rows: np.ndarray  # input row of each non-missing value (IY0)
    y0: np.ndarray  # the non-missing values (Y0)
    ti: np.ndarray  # time index (Ti)
    flg: np.ndarray  # IY0flg: 1 where the next value is the next period
    imd: np.ndarray  # cycle category of each value (Imd)
    icy: np.ndarray  # the cycle categories (Icy)


def _arrays(years, months, values) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    years = np.asarray(years, dtype=int)
    months = np.asarray(months, dtype=int)
    values = np.asarray(values, dtype=float)
    if not (years.shape == months.shape == values.shape) or years.ndim != 1:
        raise ValueError("years, months and values must be 1-D arrays of one length")
    if not np.any(~np.isnan(values)):
        raise RHtestsError("the series has no values")
    return years, months, values


def _time_index(years, cats, icy, year0) -> np.ndarray:
    nt = len(icy)
    return ((years - year0) * nt + np.searchsorted(icy, cats) + 1).astype(float)


def _consecutive(ti: np.ndarray) -> np.ndarray:
    flg = np.zeros(len(ti))
    flg[:-1] = np.diff(ti) == 1
    return flg


def _read(years, months, values) -> _Series:
    """``Read``: the non-missing values and their time index; the cycle categories come
    from the non-missing values."""
    valid = ~np.isnan(values)
    cats = months * 100  # month * 100 + day, with day 0
    icy = np.unique(cats[valid])
    first, last = cats[0], cats[-1]
    expected = [years[0] * 10000 + c for c in icy if c >= first]
    expected += [y * 10000 + c for y in range(years[0] + 1, years[-1]) for c in icy]
    expected += [years[-1] * 10000 + c for c in icy if c <= last]
    dates = years[valid] * 10000 + cats[valid]
    if not np.isin(dates, expected).all() or np.any(np.diff(dates) < 0):
        raise RHtestsError("Input data series not continuous")
    ti = _time_index(years[valid], cats[valid], icy, years[0])
    flg = _consecutive(ti)
    if flg.sum() < 10:
        raise RHtestsError("Too many missing values to estimate autocorrelation")
    rows = np.flatnonzero(valid)
    return _Series(rows, values[valid], ti, flg, cats[valid], icy)


def _remove_cycle(y: np.ndarray, imd: np.ndarray, icy: np.ndarray):
    """``rmCycle``: subtract each category's mean; returns the means (EB) and the rest."""
    out = y.copy()
    eb = np.zeros(len(icy))
    for i, cat in enumerate(icy):
        rows = imd == cat
        eb[i] = y[rows].mean()
        out[rows] = y[rows] - eb[i]
    return eb, out


def _pmft(y: np.ndarray, t: np.ndarray, pk0: np.ndarray, nmin: int) -> tuple[int, float]:
    """``PMFT``: the position k (``Nmin`` ... ``N - Nmin``) with the largest penalised F of a
    step after k on top of a trend; returns k and its F."""
    n = len(y)
    resi, sse0 = _ls_matrix(y, t, None)
    tc = t - t.mean()
    k = np.arange(nmin, n - nmin + 1)
    after = n - k
    tail_t = np.cumsum(tc[::-1])[::-1]  # sum of tc[j] for j >= index
    tail_r = np.cumsum(resi[::-1])[::-1]
    st = tail_t[k]
    zz = after - after**2 / n - st**2 / np.sum(tc**2)
    gain = tail_r[k] ** 2 / zz
    fc = gain * (n - 3) / (sse0 - gain)
    pfc = fc * pk0[k - 1]

    def exact(i: int) -> float:
        _, sse = _ls_matrix(y, t, int(k[i]))
        return (sse0 - sse) * (n - 3) / sse * pk0[k[i] - 1]

    best = _first_max(pfc, exact)
    _, sse = _ls_matrix(y, t, int(k[best]))
    return int(k[best]), (sse0 - sse) * (n - 3) / sse


def _pmf_search(y, t, i0: int, i2: int) -> tuple[int, float]:
    """``PMFxKxI0I2``: the most likely changepoint of ``y[i0:i2]`` and its confidence
    (``pf``), or ``(i0, -1)`` for a segment shorter than ``2 * Nmin``."""
    nseg = i2 - i0
    if nseg < 2 * _PMF_NMIN:
        return i0, -1.0
    kpx, fx = _pmft(y[i0:i2], t[i0:i2], pk_pmft(nseg), _PMF_NMIN)
    return i0 + kpx, float(stats.f.cdf(fx, 1, nseg - 3))


def _pmf_at(y, t, i0: int, i2: int, ic: int) -> tuple[float, float]:
    """``PMFxKc``: the penalised F and the confidence of a step after ``ic`` in
    ``y[i0:i2]``."""
    if ic <= i0:
        return 0.0, 0.0
    nseg = i2 - i0
    _, sse0 = _ls_matrix(y[i0:i2], t[i0:i2], None)
    _, sse1 = _ls_matrix(y[i0:i2], t[i0:i2], ic - i0)
    fc = (sse0 - sse1) * (nseg - 3) / sse1
    return fc * pk_pmft(nseg)[ic - i0 - 1], float(stats.f.cdf(fc, 1, nseg - 3))


def _pmf_iseg(y, t, flg, ips: list[int], iseg: int, crit) -> tuple[float, float]:
    """``PMFxIseg``, the two values FindU uses: PFmax of changepoint ``iseg`` (1-based)
    against the segments either side, and its lower critical value (at the lower end of
    the autocorrelation interval of the fit with every changepoint)."""
    i0 = 0 if iseg == 1 else ips[iseg - 2]
    i3 = ips[iseg]
    ic = ips[iseg - 1]
    nseg = i3 - i0
    _, resi = _ls_multiple(y, t, ips)
    _, corl, _ = _autocor(resi, flg)
    pfx95l = crit(corl, nseg)
    ssef = np.sum(resi[i0:i3] ** 2)
    _, resi0 = _ls_multiple(y, t, ips[: iseg - 1] + ips[iseg:])
    sse0 = np.sum(resi0[i0:i3] ** 2)
    fx = (sse0 - ssef) * (nseg - 3) / ssef
    return fx * pk_pmft(nseg)[ic - i0 - 1], pfx95l


def _ls_multiple_red(y0, ti, ips, flg):
    """``LSmultipleRed``: the trend of the prewhitened series, the segment means about it,
    and the series prewhitened with the autocorrelation and its interval (W, WL, WU)."""
    n = len(y0)
    sig, resi = _ls_multiple(y0, ti, ips)
    beta = sig[1]
    cor, corl, corh = _autocor(resi, flg)
    resi = resi + beta * ti
    w1 = resi / (1 - cor)
    w2 = np.concatenate(([w1[0]], (resi[1:] - cor * resi[:-1]) / (1 - cor)))
    prev = np.concatenate(([1.0], flg[:-1]))
    w = np.where(prev == 1, w2, w1)
    # LSmatrix(W, Ti, NA)'s slope: the trend of the prewhitened series.
    beta = _solve(np.column_stack((np.ones(n), ti - ti.mean())), w)[1]
    detrended = y0 - beta * ti
    mu = []
    resi = np.empty(n)
    for i1, i2 in _segments(ips):
        mu.append(detrended[i1:i2].mean())
        resi[i1:i2] = y0[i1:i2] - (mu[-1] + beta * ti[i1:i2])
    out = []
    for r in (cor, corl, corh):
        w = np.where(prev == 1, np.concatenate(([resi[0]], resi[1:] - r * resi[:-1])), resi)
        for (i1, i2), m in zip(_segments(ips), mu, strict=True):
            w[i1:i2] += m + beta * ti[i1:i2]
        out.append(w)
    return cor, corl, corh, np.array(mu), out[0], out[1], out[2]


def _ls_multi_red_cycle(y0, s: _Series, ips: list[int], eb: np.ndarray, iseg_adj: int):
    """``LSmultiRedCycle``: ``LSmultipleRed``, re-estimating the annual cycle of a
    monthly series until it settles (at most 20 times)."""
    y0 = y0.copy()
    nt = len(s.icy)
    eb1 = eb.copy()
    cats = np.searchsorted(s.icy, s.imd)
    niter = 0
    while True:
        niter += 1
        eb0 = eb1.copy()
        cor, corl, corh, mu, w, wl, wu = _ls_multiple_red(y0, s.ti, ips, s.flg)
        if nt <= 1:
            break
        segments = list(_segments(ips))
        full = eb0[cats]
        for i, (i1, i2) in enumerate(segments):
            delta = mu[i] - mu[iseg_adj - 1]
            y0[i1:i2] = y0[i1:i2] + full[i1:i2] - delta
        for i in range(nt):
            eb1[i] = y0[s.imd == s.icy[i]].mean()
        veb = np.sqrt(np.var(eb1, ddof=1))
        if np.isnan(veb):
            break
        full = eb1[cats]
        for i, (i1, i2) in enumerate(segments):
            delta = mu[i] - mu[iseg_adj - 1]
            y0[i1:i2] = y0[i1:i2] - full[i1:i2] + delta
        if not (np.max(np.abs(eb1 - eb0)) > veb / 1000 and niter < 20):
            break
    return y0, cor, corl, corh, mu, w, wl, wu


def pmf(years, months, values, level: float = 0.95) -> Result:
    """RHtests' ``FindU``: changepoints of a series by the PMFred test.

    ``years``, ``months`` and ``values`` hold one row per period, consecutive, as in an
    RHtests input file: ``months`` is 1-12 for a monthly series and 0 for an annual one,
    ``values`` NaN where missing. ``level`` is the nominal confidence, one of
    :data:`LEVELS`. Raises :class:`RHtestsError` for a series RHtests cannot test.
    """
    pkth = _pkth(level)
    years, months, values = _arrays(years, months, values)
    s = _read(years, months, values)
    n = len(s.y0)
    if n < 2 * _PMF_NMIN:
        raise RHtestsError(f"PMF needs at least {2 * _PMF_NMIN} values, the series has {n}")
    phi, table = _critical_table(_PF_TABLE, pkth, n)

    def crit(cor: float, nseg: int) -> float:
        return _critical_value(phi, table, cor, nseg)

    eb, y1 = _remove_cycle(s.y0, s.imd, s.icy)
    ti, flg = s.ti, s.flg

    # The first changepoint: the PMFT maximum, refined in the segments either side.
    i2, _ = _pmft(y1, ti, pk_pmft(n), _PMF_NMIN)
    i1, _ = _pmf_search(y1, ti, 0, i2)
    i3, _ = _pmf_search(y1, ti, i2, n)
    i2, _ = _pmf_search(y1, ti, i1, i3)
    candidates = []
    for ic in (i1, i2, i3):
        if ic > 0:
            # FindU also computes the prewhitened series' confidence here, but uses only
            # PFmax and the lower end of the autocorrelation interval.
            _, resi = _ls_multiple(y1, ti, [ic, n])
            _, corl, _, _, _, _ = _rphi(resi, [ic, n], flg)
            pfx, _ = _pmf_at(y1, ti, 0, n, ic)
            candidates.append((pfx, ic, corl))
        else:
            candidates.append((0.0, ic, 0.0))
    # sort(decreasing = TRUE) is stable: the first of equal PFmax values wins.
    best = max(range(3), key=lambda i: (candidates[i][0], -i))
    pfx_mx, imx, cor_mx = candidates[best]

    if pfx_mx < crit(cor_mx, n):
        ips = [n]
    else:
        ips = [imx, n]
        ips = _pmf_insert(y1, ti, flg, ips, crit)
        ips = _pmf_delete(y1, ti, flg, ips, crit)

    ns = len(ips) - 1
    y1, cor, corl, corh, mu, w, wl, wu = _ls_multi_red_cycle(y1, s, ips, eb, ns + 1)
    changepoints = []
    if ns > 0:
        _, resi = _ls_multiple(y1, ti, ips)
        _, resi_w = _ls_multiple(w, ti, ips)
        _, resi_wl = _ls_multiple(wl, ti, ips)
        _, resi_wu = _ls_multiple(wu, ti, ips)
        for i in range(ns):
            i0 = 0 if i == 0 else ips[i - 1]
            ic, i3 = ips[i], ips[i + 1]
            nseg = i3 - i0
            others = ips[:i] + ips[i + 1 :]
            fx = _segment_f(y1, ti, resi, others, i0, i3)
            pfx = fx * pk_pmft(nseg)[ic - i0 - 1]
            fx = _segment_f(w, ti, resi_w, others, i0, i3)
            if fx > 0:
                prob = float(stats.f.cdf(fx, 1, nseg - 3))
            else:
                fx = prob = pfx = 0.0
            # R quirk: probL and probU are pf() of the W-based Fx, not of FxL and FxU;
            # only the signs of FxL and FxU are used.
            fx_low = _segment_f(wl, ti, resi_wl, others, i0, i3)
            fx_high = _segment_f(wu, ti, resi_wu, others, i0, i3)
            prob_low = float(stats.f.cdf(fx, 1, nseg - 3)) if fx_low > 0 else 0.0
            prob_high = float(stats.f.cdf(fx, 1, nseg - 3)) if fx_high > 0 else 0.0
            cv_low, cv_high = crit(corl, nseg), crit(corh, nseg)
            changepoints.append(
                Changepoint(
                    position=int(s.rows[ic - 1]),
                    label=_label(pfx, cv_low, cv_high),
                    statistic=float(pfx),
                    cv=crit(cor, nseg),
                    cv_low=cv_low,
                    cv_high=cv_high,
                    prob=prob,
                    prob_low=prob_low,
                    prob_high=prob_high,
                    nseg=nseg,
                    step=float(mu[i + 1] - mu[i]),
                )
            )
    return Result("pmf", tuple(changepoints), cor)


def _segment_f(y, t, resi_full, others: list[int], i0: int, i3: int) -> float:
    """F of the changepoint between the other changepoints ``others``, from the SSE of
    ``y[i0:i3]`` with it (``resi_full``) and without it."""
    _, resi0 = _ls_multiple(y, t, others)
    ssef = np.sum(resi_full[i0:i3] ** 2)
    return float((np.sum(resi0[i0:i3] ** 2) - ssef) * (i3 - i0 - 3) / ssef)


def _label(statistic: float, cv_low: float, cv_high: float) -> str:
    if statistic < cv_low:
        return "No"
    if statistic < cv_high:
        return "?"
    return "Yes"


def _pmf_insert(y, t, flg, ips: list[int], crit) -> list[int]:
    """FindU's search for more changepoints: the most likely one of each segment, the
    most significant of those that pass inserted, repeated until none passes."""
    more = True
    while more:
        more = False
        candidates: list[int] = []
        for i0, i2 in _segments(ips):
            ic, prob = _pmf_search(y, t, i0, i2)
            if prob > 0:
                candidates = sorted([*candidates, ic])
        while candidates:
            best, best_pfx, best_cv = 0, -9999.0, 0.0
            for i, ic in enumerate(candidates):
                trial = sorted([*ips, ic])
                pfx, pfx95l = _pmf_iseg(y, t, flg, trial, trial.index(ic) + 1, crit)
                if pfx < pfx95l:
                    candidates[i] = 0
                elif pfx > best_pfx:
                    best, best_pfx, best_cv = ic, pfx, pfx95l
            if best_pfx >= best_cv:
                ips = sorted([*ips, best])
                candidates = [c for c in candidates if c != best]
                more = True
                candidates = [c for c in candidates if c != 0]
            else:
                break
    return ips


def _pmf_delete(y, t, flg, ips: list[int], crit) -> list[int]:
    """FindU's removal of the least significant changepoint while it is not significant."""
    while len(ips) > 1:
        worst, worst_pfx, worst_cv = 0, 99999.0, 99999.0
        for i in range(1, len(ips)):
            pfx, pfx95l = _pmf_iseg(y, t, flg, ips, i, crit)
            if pfx < worst_pfx:
                worst, worst_pfx, worst_cv = i, pfx, pfx95l
        if worst > 0 and worst_pfx < worst_cv:
            ips = ips[: worst - 1] + ips[worst:]
        else:
            break
    return ips


# ---- PMT (FindU.wRef with a zero reference) -------------------------------------------


def _read_wref(years, months, values) -> _Series:
    """``Read.wRef`` with a reference of zeros: the non-missing values minus the mean of
    their cycle category. The categories come from every row, missing or not."""
    valid = ~np.isnan(values)
    cats = months * 100
    icy = np.unique(cats)
    y = values[valid]
    imd = cats[valid]
    for cat in icy:
        # R quirk: the count is of the matrix elements of the category's rows, two per
        # value (its category and its value), so it asks for 5 values, not 10.
        if 2 * np.sum(imd == cat) < 10:
            raise RHtestsError(f"input data too few at: {cat}")
    # R counts adjacent rows of the non-missing values, not consecutive periods.
    if len(y) - 1 < 10:
        raise RHtestsError("input data too few for autocorrelation calculating")
    ti = _time_index(years[valid], imd, icy, years[0])
    eb, _ = _remove_cycle(y, imd, np.unique(imd))
    y0 = y - eb[np.searchsorted(icy, imd)]
    return _Series(np.flatnonzero(valid), y0, ti, _consecutive(ti), imd, icy)


def _t_stat(y: np.ndarray, ic: int) -> float:
    """The two-sample t of a step after position ``ic`` (1-based), as ``PTK``/``PTKIc``."""
    n = len(y)
    m1, m2 = y[:ic].mean(), y[ic:].mean()
    var = np.sum((y[:ic] - m1) ** 2) + np.sum((y[ic:] - m2) ** 2)
    return float(np.sqrt(ic * (n - ic) / n) * abs(m1 - m2) / np.sqrt(var / (n - 2)))


def _ptk(y: np.ndarray, pk: np.ndarray) -> tuple[int, float]:
    """``PTK``: the position k (``Nmin`` ... ``N - Nmin``) with the largest penalised t;
    returns k and its t."""
    n = len(y)
    yc = y - y.mean()
    k = np.arange(_PMT_NMIN, n - _PMT_NMIN + 1)
    c1, c2 = np.cumsum(yc), np.cumsum(yc**2)
    s1, q1 = c1[k - 1], c2[k - 1]
    s2, q2 = c1[-1] - s1, c2[-1] - q1
    var = (q1 - s1**2 / k) + (q2 - s2**2 / (n - k))
    tk = np.sqrt(k * (n - k) / n) * np.abs(s1 / k - s2 / (n - k)) / np.sqrt(var / (n - 2))
    ptk = tk * pk[k - 1]
    best = _first_max(ptk, lambda i: _t_stat(y, int(k[i])) * pk[k[i] - 1])
    return int(k[best]), _t_stat(y, int(k[best]))


def _pmt_search(y0, i0: int, i2: int) -> tuple[int, float]:
    """``PTKI0I2``: the most likely changepoint of ``y0[i0:i2]`` and its confidence
    (``pt``), or ``(i0, -1)`` for a segment shorter than ``2 * Nmin``."""
    y = y0[i0:i2]
    if len(y) < 2 * _PMT_NMIN:
        return i0, -1.0
    kpx, tx = _ptk(y, pk_pmt(len(y)))
    return i0 + kpx, float(stats.t.cdf(tx, len(y) - 2))


def _pmt_at(y: np.ndarray, pk: np.ndarray, ic: int) -> tuple[float, float]:
    """``PTKIc``: the penalised t and the confidence of a step after ``ic`` (1-based)."""
    if ic <= 0:
        return 0.0, 0.0
    tk = _t_stat(y, ic)
    return tk * pk[ic - 1], float(stats.t.cdf(tk, len(y) - 2))


def pmt(years, months, values, level: float = 0.95) -> Result:
    """RHtests' ``FindU.wRef`` with a reference series of zeros: changepoints of the
    series' anomalies by the PMTred test. Arguments as for :func:`pmf`."""
    pkth = _pkth(level)
    years, months, values = _arrays(years, months, values)
    s = _read_wref(years, months, values)
    y0, flg = s.y0, s.flg
    n = len(y0)
    phi, table = _critical_table(_PT_TABLE, pkth, n)

    def crit(cor: float, nseg: int) -> float:
        return _critical_value(phi, table, cor, nseg)

    pk0 = pk_pmt(n)
    i2, _ = _ptk(y0, pk0)
    i1, _ = _pmt_search(y0, 0, i2)
    i3, _ = _pmt_search(y0, i2, n)
    i02, _ = _pmt_search(y0, i1, i3)

    _, prob = _pmt_at(y0, pk0, i02)
    if i02 > 0 and prob >= level:
        ips = _pmt_search_zero_cor(y0, [i02, n], level, crit)
    else:
        ips = [n]
    ns_initial = len(ips) - 1
    _, cor_low, _, _, _, _ = _rphi(y0, ips, flg)

    ptk, _ = _pmt_at(y0, pk0, i02)
    if ptk < crit(cor_low, n - 1):
        ips = [n]
        cor, corl, corh, w, wl, wu = _rphi(y0, ips, flg)
    else:
        ips = _pmt_insert(y0, [i02, n], cor_low, crit)
        while True:
            ips = _pmt_delete(y0, ips, cor_low, crit)
            cor, corl, corh, w, wl, wu = _rphi(y0, ips, flg)
            if ns_initial > len(ips) - 1:
                ns_initial = len(ips) - 1
                cor_low = corl
            else:
                break

    ns = len(ips) - 1
    changepoints = []
    means = [y0[i1:i2].mean() for i1, i2 in _segments(ips)]
    for i in range(ns):
        i0 = 0 if i == 0 else ips[i - 1]
        ic, i3 = ips[i], ips[i + 1]
        nseg = i3 - i0
        pk = pk_pmt(nseg)
        # R quirk: these use the critical values for Nseg, the search those for Nseg - 1.
        cv_low, cv_high = crit(corl, nseg), crit(corh, nseg)
        _, prob_w = _pmt_at(w[i0:i3], pk, ic - i0)
        _, prob_l = _pmt_at(wl[i0:i3], pk, ic - i0)
        _, prob_u = _pmt_at(wu[i0:i3], pk, ic - i0)
        ptk, _ = _pmt_at(y0[i0:i3], pk, ic - i0)
        changepoints.append(
            Changepoint(
                position=int(s.rows[ic - 1]),
                label=_label(ptk, cv_low, cv_high),
                statistic=ptk,
                cv=crit(cor, nseg),
                cv_low=cv_low,
                cv_high=cv_high,
                prob=prob_w,
                prob_low=min(prob_l, prob_u),
                prob_high=max(prob_l, prob_u),
                nseg=nseg,
                step=float(means[i + 1] - means[i]),
            )
        )
    cor, _, _, _, _, _ = _rphi(y0, ips, flg)
    return Result("pmt", tuple(changepoints), cor)


def _pmt_search_zero_cor(y0, ips: list[int], level: float, crit) -> list[int]:
    """FindU.wRef's first search, with no autocorrelation: changepoints whose t passes
    ``level``, the one with the largest PTmax relative to its critical value first."""
    more = True
    while more:
        more = False
        candidates: list[int] = []
        for i0, i2 in _segments(ips):
            ic, prob = _pmt_search(y0, i0, i2)
            if prob > 0:
                candidates = sorted([*candidates, ic])
        while candidates:
            best_ratio, best_prob, best_i = -9999 / 0.001, 0.0, -1
            for i, ic in enumerate(candidates):
                trial = sorted([*ips, ic])
                pos = trial.index(ic)
                # R quirk: the segment starts at the value after the previous changepoint
                # (I0 = Ips1[id-1] + 1), but Nseg = I2 - I0 is one less than its length,
                # so the penalty is for Nseg and the critical value for Nseg - 1.
                start = 1 if pos == 0 else trial[pos - 1] + 1
                end = trial[pos + 1]
                nseg = end - start
                cv = crit(0.0, nseg - 1)
                ptk, prob = _pmt_at(y0[start - 1 : end], pk_pmt(nseg), ic - start + 1)
                if prob < level:
                    candidates[i] = 0
                elif ptk / cv > best_ratio:
                    best_ratio, best_prob, best_i = ptk / cv, prob, i
            if best_prob >= level:
                ips = sorted([*ips, candidates[best_i]])
                del candidates[best_i]
                more = True
                candidates = [c for c in candidates if c != 0]
            else:
                break
    return ips


def _pmt_insert(y0, ips: list[int], cor_low: float, crit) -> list[int]:
    """FindU.wRef's main search: changepoints whose PTmax passes the critical value at the
    lower end of the autocorrelation interval, the largest relative to it first."""
    more = True
    while more:
        more = False
        candidates: list[int] = []
        for i0, i2 in _segments(ips):
            ic, prob = _pmt_search(y0, i0, i2)
            if prob > 0:
                candidates = sorted([*candidates, ic])
        while candidates:
            best_ptk, best_cv, best_i = -9999.0, 0.001, -1
            for i, ic in enumerate(candidates):
                trial = sorted([*ips, ic])
                pos = trial.index(ic)
                i0 = 0 if pos == 0 else trial[pos - 1]
                i2 = trial[pos + 1]
                nseg = i2 - i0
                cv = crit(cor_low, nseg - 1)
                ptk, _ = _pmt_at(y0[i0:i2], pk_pmt(nseg), ic - i0)
                if ptk < cv:
                    candidates[i] = 0
                elif ptk / cv > best_ptk / best_cv:
                    best_ptk, best_cv, best_i = ptk, cv, i
            if best_ptk >= best_cv:
                ips = sorted([*ips, candidates[best_i]])
                del candidates[best_i]
                more = True
                candidates = [c for c in candidates if c != 0]
            else:
                break
    return ips


def _pmt_delete(y0, ips: list[int], cor_low: float, crit) -> list[int]:
    """FindU.wRef's removal of the changepoint with the smallest PTmax relative to its
    critical value while it is below it."""
    while len(ips) > 1:
        worst_ptk, worst_cv, worst = 9999.9, 9999.9, 0
        for i in range(1, len(ips)):
            i1 = 0 if i == 1 else ips[i - 2]
            i3, ic = ips[i], ips[i - 1]
            nseg = i3 - i1
            cv = crit(cor_low, nseg - 1)
            ptk, _ = _pmt_at(y0[i1:i3], pk_pmt(nseg), ic - i1)
            if ptk / cv < worst_ptk / worst_cv:
                worst_ptk, worst_cv, worst = ptk, cv, i
        if worst > 0 and worst_ptk < worst_cv:
            ips = ips[: worst - 1] + ips[worst:]
        else:
            break
    return ips
