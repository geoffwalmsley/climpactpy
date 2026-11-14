"""Climpact's SPI and SPEI for the cells of a grid (``spi_MON``, ``spei_MON``).

The gridded code does not run the station app's ``calculate.spi``/``calculate.spei``
and their ``cspei`` (:mod:`climpact.products.drought`). ``create.indices.from.files``
calls ``climdex.spi`` and ``climdex.spei`` (``climpact.etsci-functions.r``, lines 405
and 543), which call the SPEI package's own ``spi()`` and ``spei()`` (SPEI 1.8.1, the
version in the reference image). Ported here:

- Monthly inputs (:func:`monthly_inputs`): precipitation is the month's total of the
  days present (R ``sum(na.rm = TRUE)``), so a month with no precipitation at all is 0
  for SPI (``tapply.fast(..., sum, na.rm = TRUE)``) and missing for SPEI (its own
  function). TX and TN are the means of the days present. No missing-data rule.
- SPEI: ``P - PET`` with PET from ``hargreaves(Tmin, Tmax, lat, Pre)`` on plain vectors
  (non-leap years, :func:`climpact.products.drought.hargreaves`) at the cell's latitude.
- SPEI 1.8.1's ``spei()`` (:func:`spei_package`): the series is *summed* over ``scale``
  months (``rollapply`` with ``kern(scale) * scale``, all weights 1), and the reference
  window is cut from that accumulated series, so the first base-period months keep their
  accumulation from before the base period. Per calendar month a distribution is fitted
  to the reference values by unbiased PWMs (TLMoments ``PWM``, lmomco ``pwm2lmom``): a
  generalised logistic (lmom ``pelglo``) for SPEI; for SPI a two-parameter Gamma
  (lmom ``pelgam``) fitted to the non-zero values only. Values become ``qnorm`` of lmom's
  ``cdfglo``/``cdfgam``. The zero probability ``pze`` is computed but has no effect
  (``spei()`` overwrites the mixed value), so an accumulated 0 gives ``qnorm(0)``, which
  is infinite and becomes missing.
- With a thresholds file holding the base-period data (``txraw``, ``tnraw``,
  ``precraw``: ``computefuture``), the series fitted runs from January of the first base
  year to December of the last data year: the base-period data first, the cell's data
  last, missing in between. Only the cell's months are kept, and the first ``scale - 1``
  of them are made missing.

Scales 3, 6 and 12 only (no custom scale).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from climpact.periods import periods
from climpact.products.drought import _exp, are_lmom_valid, hargreaves, pwm2lmom
from climpact.rdist import pgamma, qnorm
from climpact.rnumerics import r_mean, r_sum

SCALES = (3, 6, 12)
GLO_SMALL = 1e-6  # lmom PELGLO: SMALL
PELGAM_PI = 3.1415927  # lmom PELGAM's single-precision-looking value of pi
_PELGAM_A = (-0.3080, -0.05812, 0.01765)
_PELGAM_B = (0.7213, -0.5947, -2.1817, 1.2113)


# --- the SPEI package's spei() ---------------------------------------------------------


def tl_pwm(sorted_x: np.ndarray, r: int) -> float:
    """TLMoments ``pwm_C``: the unbiased probability-weighted moment ``beta_r`` of the
    sorted values, accumulated in double precision as its C++ loop does."""
    n = sorted_x.size
    factor = 1.0
    for k in range(n, n - r - 1, -1):
        factor /= k
    total = 0.0
    for j, value in enumerate(sorted_x.tolist(), start=1):
        w = 1.0
        for i in range(1, r + 1):
            w *= j - i
        total += w * value
    return total * factor


def pelglo(l1: float, l2: float, t3: float) -> tuple[float, float, float] | None:
    """lmom's Fortran ``PELGLO``: generalised logistic ``(xi, alpha, k)``, None when the
    L-moments are invalid (``IFAIL = 7000``)."""
    g = -t3
    if l2 <= 0 or abs(g) >= 1:
        return None
    if abs(g) <= GLO_SMALL:
        return l1, l2, 0.0
    gg = g * math.pi / math.sin(g * math.pi)
    a = l2 / gg
    return l1 - a * (1 - gg) / g, a, g


def pelgam(l1: float, l2: float) -> tuple[float, float] | None:
    """lmom's Fortran ``PELGAM``: Gamma ``(alpha, beta)``, None when ``L1 <= L2`` or
    ``L2 <= 0``. Uses its constant ``PI = 3.1415927D0``."""
    if l1 <= l2 or l2 <= 0:
        return None
    a1, a2, a3 = _PELGAM_A
    b1, b2, b3, b4 = _PELGAM_B
    cv = l2 / l1
    if cv >= 0.5:
        t = 1 - cv
        alpha = t * (b1 + t * b2) / (1 + t * (b3 + t * b4))
    else:
        t = PELGAM_PI * cv * cv
        alpha = (1 + a1 * t) / (t * (1 + t * (a2 + t * a3)))
    return alpha, l1 / alpha


def cdfglo(x: float, xi: float, alpha: float, k: float) -> float:
    """lmom ``cdfglo`` (not lmomco's): ``-1 / k * log(pmax(0, 1 - k * (x - xi) / alpha))``."""
    if k == 0:
        y = (x - xi) / alpha
    else:
        arg = max(0.0, 1 - k * (x - xi) / alpha)
        y = -1 / k * (math.log(arg) if arg > 0 else -math.inf)
    return 1 / (1 + _exp(-y))


def cdfgam(x: float, alpha: float, beta: float) -> float:
    """lmom ``cdfgam``: ``pgamma(x / beta, alpha)``, 0 for ``x <= 0``."""
    return 0.0 if x <= 0 else pgamma(x / beta, alpha)


def accumulate_sum(data: np.ndarray, scale: int) -> np.ndarray:
    """``rollapply(acu, scale, function(x) sum(x * rev(wgt)), fill = NA, align = "right")``
    with ``wgt = kern(scale) * scale``: the sum of the last ``scale`` months (R's
    extended-precision ``sum`` of the weighted values), missing for the first ``scale - 1``
    months and for windows with a missing month."""
    weight = (1.0 / scale) * scale  # kern: rep(1, s) / sum(rep(1, s)), times scale
    out = np.full(len(data), np.nan)
    for t in range(scale - 1, len(data)):
        window = data[t - scale + 1 : t + 1] * weight
        if not np.isnan(window).any():
            out[t] = r_sum(window)
    return out


def _fit(values: np.ndarray, distribution: str):
    """The parameters ``spei()`` fits to one calendar month's reference values, or None
    when it skips the month (``next``)."""
    if values.size < 2 or np.all(values == values[0]):  # sd is NA or 0
        return None
    if values.size < 4:
        return None
    x = np.sort(values)
    lambdas, ratios = pwm2lmom([tl_pwm(x, r) for r in range(3)])
    padded = ratios + [math.nan, math.nan]
    if not are_lmom_valid(lambdas, padded) or any(math.isnan(v) for v in lambdas):
        return None
    l1, l2, t3 = lambdas[0], lambdas[1], ratios[2]
    if distribution == "log-Logistic":
        return pelglo(l1, l2, t3)  # never None: are.lmom.valid checked L2 and TAU3
    # PELGAM fails only when L1 <= L2, which non-zero precipitation sums cannot give; R
    # would then fall back to lmomco's pargam, return NULL and stop.
    return pelgam(l1, l2)


def spei_package(data: np.ndarray, scale: int, ref: slice, distribution: str) -> np.ndarray:
    """SPEI 1.8.1 ``spei()`` (``spi()`` with ``distribution = "Gamma"``) on a monthly
    series starting in January, with ``fit = "ub-pwm"``, ``na.rm = TRUE`` and the
    rectangular kernel; ``ref`` selects the reference months, also starting in January.
    Infinite values (probability 0 or 1) are returned as they are."""
    acu = accumulate_sum(np.asarray(data, dtype=float), scale)
    acu_ref = acu[ref]
    out = np.full(len(acu), np.nan)
    for c in range(12):
        fit_values = acu_ref[c::12]
        fit_values = fit_values[~np.isnan(fit_values)]
        positions = np.arange(c, len(acu), 12)
        positions = positions[~np.isnan(acu[positions])]
        if fit_values.size == 0:
            continue
        if distribution != "log-Logistic":
            fit_values = fit_values[fit_values > 0]
        params = _fit(fit_values, distribution)
        if params is None:
            continue
        if distribution == "log-Logistic":
            cdf = [cdfglo(v, *params) for v in acu[positions].tolist()]
        else:
            cdf = [cdfgam(v, *params) for v in acu[positions].tolist()]
        out[positions] = [qnorm(p) for p in cdf]
    return out


# --- climdex.spi and climdex.spei ------------------------------------------------------


def _months(dates: pd.DatetimeIndex) -> int:
    return (dates[-1].year - dates[0].year) * 12 + dates[-1].month - dates[0].month + 1


def monthly_inputs(values: np.ndarray, dates: pd.DatetimeIndex, kind: str) -> np.ndarray:
    """Monthly values of a daily ``(cells, time)`` array as ``climdex.spi``/``climdex.spei``
    compute them: ``"spi"`` precipitation (total of the days present, 0 when none),
    ``"spei"`` precipitation (missing when none) or ``"mean"`` (temperature)."""
    p = periods(dates, "MS")
    if kind == "mean":
        return p.apply(values, r_mean)
    totals = p.apply(values, r_sum)
    return np.where(np.isnan(totals), 0.0, totals) if kind == "spi" else totals


def _series(
    data: np.ndarray, full: pd.DatetimeIndex, raw: np.ndarray | None, base_start: int
) -> tuple[np.ndarray, pd.DatetimeIndex]:
    """The daily series ``climdex.spi``/``climdex.spei`` fit: the cell's data, or with
    base-period data from a thresholds file (``computefuture``) that data from 1 January
    of the first base year, the cell's data at the end and missing in between."""
    if raw is None:
        return data, full
    dates = pd.date_range(f"{base_start}-01-01", full[-1], freq="D")
    series = np.full((*data.shape[:-1], dates.size), np.nan)
    series[..., : raw.shape[-1]] = raw
    series[..., dates.size - full.size :] = data
    return series, dates


def _reference(dates: pd.DatetimeIndex, base_start: int, base_end: int) -> slice:
    first = dates[0].year
    n = _months(dates)
    return slice(
        min(max((base_start - first) * 12, 0), n), min(max((base_end - first + 1) * 12, 0), n)
    )


def _standardise(
    monthly: np.ndarray,
    dates: pd.DatetimeIndex,
    n_out: int,
    future: bool,
    base_start: int,
    base_end: int,
    distribution: str,
) -> np.ndarray:
    """``(cells, 3, months)``: the fitted values at the three scales, with R's handling
    of a thresholds file and non-finite values."""
    ref = _reference(dates, base_start, base_end)
    out = np.full((monthly.shape[0], len(SCALES), n_out), np.nan)
    for cell, series in enumerate(monthly):
        for i, scale in enumerate(SCALES):
            values = spei_package(series, scale, ref, distribution)[-n_out:]
            if future:
                values[: scale - 1] = np.nan
            out[cell, i] = values
    out[~np.isfinite(out)] = np.nan  # -Inf, Inf and NaN become NA
    return out


def spi_values(
    pr: np.ndarray,
    full: pd.DatetimeIndex,
    base_start: int,
    base_end: int,
    raw: np.ndarray | None = None,
) -> np.ndarray:
    """``climdex.spi`` for ``(cells, time)`` precipitation on the whole-year axis
    ``full``: ``(cells, 3, months)`` at 3, 6 and 12 months. ``raw`` is the cells'
    base-period precipitation from a thresholds file (``precraw``), or None."""
    series, dates = _series(pr, full, raw, base_start)
    monthly = monthly_inputs(series, dates, "spi")
    return _standardise(
        monthly, dates, _months(full), raw is not None, base_start, base_end, "Gamma"
    )


def spei_values(
    tx: np.ndarray,
    tn: np.ndarray,
    pr: np.ndarray,
    full: pd.DatetimeIndex,
    latitude: np.ndarray,
    base_start: int,
    base_end: int,
    raw: dict[str, np.ndarray] | None = None,
) -> np.ndarray:
    """``climdex.spei`` for ``(cells, time)`` TX, TN and precipitation on ``full``, with
    each cell's ``latitude``: ``(cells, 3, months)``. ``raw`` holds the cells'
    base-period ``tasmax``, ``tasmin`` and ``pr`` from a thresholds file, or None."""
    future = raw is not None
    tx, dates = _series(tx, full, raw["tasmax"] if future else None, base_start)
    tn, _ = _series(tn, full, raw["tasmin"] if future else None, base_start)
    pr, _ = _series(pr, full, raw["pr"] if future else None, base_start)
    tmax = monthly_inputs(tx, dates, "mean")
    tmin = monthly_inputs(tn, dates, "mean")
    prec = monthly_inputs(pr, dates, "spei")
    balance = (
        np.stack(
            [
                prec[c] - hargreaves(tmin[c], tmax[c], float(latitude[c]), prec[c])
                for c in range(prec.shape[0])
            ]
        )
        if prec.shape[0]
        else prec
    )
    return _standardise(balance, dates, _months(full), future, base_start, base_end, "log-Logistic")
