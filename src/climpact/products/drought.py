"""Climpact's SPI and SPEI: standardised precipitation (-evapotranspiration) indices.

A port of the code Climpact 3.4.3 actually runs: ``calculate.spi`` and
``calculate.spei`` (``services/calculate/calculate_spi.R``, ``calculate_spei.R``), which
call Climpact's own copy of the SPEI package's old fitting function, ``cspei``
(``services/calculate/custom_cspei.R``; ``cspi`` is ``cspei`` with a Gamma
distribution). ``climdex.spi`` and ``climdex.spei`` in ``climpact.etsci-functions.r``
are not used. The fit uses lmomco 2.5.7 and the PET SPEI 1.8.1's ``hargreaves``, the
versions in the reference image (``reference/r``).

For each scale (3, 6, 12 months and ``IndexParams.spei_months``):

1. Monthly inputs. Precipitation is the month's total of the days present (missing only
   when every day is missing); TX and TN are the month's means of the days present
   (R's extended-precision ``sum`` and ``mean``). There is no missing-data rule.
2. SPEI only: the climatic water balance ``P - PET``, with PET from Hargreaves'
   equation as modified by Droogers and Allen (2002), which uses precipitation, and
   extraterrestrial radiation from the station latitude (:func:`hargreaves`).
3. The series is accumulated over ``scale`` months with a rectangular kernel, so each
   value is the *mean* of the last ``scale`` months (:func:`accumulate`); any missing
   month makes it missing.
4. For each calendar month a distribution is fitted by unbiased probability-weighted
   moments to the accumulated values of the base period (whose first ``scale - 1``
   months have no value, because the window does not look before the base period):
   a generalised logistic (``parglo``) for SPEI, a two-parameter Gamma (``pargam`` of
   ``lmom.ub``, fitted to all values including zeros) for SPI.
5. Every accumulated value of that calendar month is turned into a standard normal
   deviate: ``qnorm(cdfglo(x))`` for SPEI; ``qnorm(pze + (1 - pze) * pnorm(qnorm(
   cdfgam(x))))`` for SPI, with ``pze`` the fraction of zeros among the fitted values.
   Infinite values become missing.

A calendar month whose base-period values have fewer than five values (or invalid
L-moments) gets no fit, and all its values are missing.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
import pandas as pd

from climpact.outputs import product
from climpact.rdist import pgamma, pnorm, qnorm
from climpact.rnumerics import r_mean, r_sum
from climpact.station import StationRun

SCALES = (3, 6, 12)
# Days in each month and the day of year of mid-month that ``hargreaves`` uses when its
# input is a plain vector: always a non-leap year (``msum <- cumsum(mlen) - mlen + 15``).
_MONTH_LENGTHS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
_MID_MONTH_DAYS = tuple(
    total - length + 15
    for total, length in zip(np.cumsum(_MONTH_LENGTHS).tolist(), _MONTH_LENGTHS, strict=True)
)


# --- monthly inputs ------------------------------------------------------------------


def monthly_inputs(run: StationRun) -> pd.DataFrame:
    """Monthly precipitation totals and TX, TN means, as ``calculate.spei`` computes them.

    Precipitation is ``sum(x, na.rm = TRUE)``, missing only when the whole month is
    missing; temperatures are ``mean(x, na.rm = TRUE)`` (``NaN``, then ``NA``, for a
    month with no data).
    """
    ds = run.data
    time = pd.DatetimeIndex(ds.time.values)
    month_index = (time.year - time.year[0]) * 12 + time.month - 1
    starts = np.flatnonzero(np.r_[True, np.diff(month_index) != 0])
    ends = np.r_[starts[1:], len(time)]

    def per_month(values: np.ndarray, func: Callable[[np.ndarray], float]) -> np.ndarray:
        out = np.full(len(starts), np.nan)
        for i, (a, b) in enumerate(zip(starts, ends, strict=True)):
            v = values[a:b]
            v = v[~np.isnan(v)]
            if v.size:
                out[i] = func(v)
        return out

    return pd.DataFrame(
        {
            "time": time[starts].strftime("%Y-%m"),
            "prec": per_month(ds.pr.values, r_sum),
            "tmax": per_month(ds.tasmax.values, r_mean),
            "tmin": per_month(ds.tasmin.values, r_mean),
        }
    )


def _r_pow(x: float, y: float) -> float:
    """R's ``x ^ y`` for a non-integer ``y``: C ``pow``, NaN for a negative base."""
    if math.isnan(x):
        return x
    if x < 0:
        return math.nan
    return math.pow(x, y)


def hargreaves(tmin: np.ndarray, tmax: np.ndarray, lat: float, pre: np.ndarray) -> np.ndarray:
    """Monthly reference evapotranspiration (mm), SPEI 1.8.1 ``hargreaves(..., Pre =)``.

    The inputs are plain vectors starting in January, so every year is treated as a
    non-leap year. Extraterrestrial radiation ``Ra`` comes from ``lat``; with
    precipitation the Droogers and Allen (2002) form is used::

        ET0 = 0.0013 * 0.408 * Ra * (Tmean + 17) * (Tr - 0.0123 * P) ^ 0.76

    which is 0 where ``Tr - 0.0123 * P`` is negative, and missing where an input is.
    """
    n = len(tmin)
    month = np.arange(n) % 12
    latr = lat / 57.2957795
    ra_month = []
    omegas, ssets, deltas, drs = [], [], [], []
    for j in _MID_MONTH_DAYS:
        delta = 0.409 * math.sin(0.0172 * j - 1.39)
        dr = 1 + 0.033 * math.cos(0.0172 * j)
        sset = -math.tan(latr) * math.tan(delta)
        omegas.append(math.acos(sset) if abs(sset) <= 1 else 0.0)
        ssets.append(sset)
        deltas.append(delta)
        drs.append(dr)
    # omegas[sset < -1] <- max(omegas): the maximum over the whole series, which repeats
    # the twelve months (all twelve occur once the series has a full year).
    largest = max(omegas[m] for m in set(month.tolist()))
    for m in range(12):
        omega = largest if ssets[m] < -1 else omegas[m]
        ra = (
            37.6
            * drs[m]
            * (
                omega * math.sin(latr) * math.sin(deltas[m])
                + math.cos(latr) * math.cos(deltas[m]) * math.sin(omega)
            )
        )
        ra_month.append(0.0 if ra < 0 else ra)
    ra = np.array(ra_month)[month]
    tmean = (tmin + tmax) / 2
    tr = tmax - tmin
    tr = np.where(tr < 0, 0.0, tr)  # pmax(0, Tr), NA kept
    ab = tr - 0.0123 * pre
    powered = np.array([_r_pow(v, 0.76) for v in ab.tolist()])
    et0 = 0.0013 * 0.408 * ra * (tmean + 17) * powered
    et0[~np.isnan(ab) & np.isnan(powered)] = 0.0  # ET0[is.nan(ab^0.76)] <- 0
    et0 = np.where(et0 < 0, 0.0, et0)
    return et0 * np.array(_MONTH_LENGTHS, dtype=float)[month]


# --- accumulation and fitting --------------------------------------------------------


def accumulate(data: np.ndarray, scale: int) -> np.ndarray:
    """``cspei``'s accumulated series: ``sum(data[t:(t - scale + 1)] * wgt)``.

    ``wgt`` is SPEI's rectangular ``kern(scale)``, ``1 / scale`` for every month, so the
    value is the mean of the last ``scale`` months. R multiplies first (in double) and
    then sums the products, newest month first, in extended precision. The first
    ``scale - 1`` values, and any window with a missing month, are missing.
    """
    weight = 1.0 / scale
    out = np.full(len(data), np.nan)
    for t in range(scale - 1, len(data)):
        window = data[t - scale + 1 : t + 1][::-1] * weight
        if not np.isnan(window).any():
            out[t] = r_sum(window)
    return out


def _choose(n: int, k: int) -> float:
    """R ``choose`` for whole numbers (exact while the result fits in a double)."""
    return float(math.comb(n, k)) if 0 <= k <= n else 0.0


def pwm_ub(x: np.ndarray, nmom: int = 5) -> list[float]:
    """lmomco ``pwm.ub``/``pwm``: unbiased probability-weighted moments of sorted ``x``.

    ``0 / 0`` (fewer values than moments) gives NaN, as in R.
    """
    values = sorted(x.tolist())
    n = len(values)
    betas = []
    for r in range(nmom):
        total = 0.0
        for j, v in enumerate(values, start=1):
            total = total + _choose(j - 1, r) * v
        denominator = n * _choose(n - 1, r)
        betas.append(total / denominator if denominator else math.nan)
    return betas


def pwm2lmom(betas: list[float]) -> tuple[list[float], list[float]]:
    """lmomco ``pwm2lmom`` for a ``betas`` vector: L-moments ``lambdas`` and ``ratios``."""
    nmom = len(betas)
    lambdas = []
    for r in range(nmom):
        total = 0.0
        for k in range(r + 1):
            weight = (-1) ** (r - k) * _choose(r, k) * _choose(r + k, k)
            total = total + weight * betas[k]
        lambdas.append(total)
    ratios = [math.nan] * nmom
    if nmom >= 2:
        ratios[1] = _div(lambdas[1], lambdas[0])
    for r in range(2, nmom):
        ratios[r] = _div(lambdas[r], lambdas[1])
    return lambdas, ratios


def _div(a: float, b: float) -> float:
    """IEEE division, as in R (``x / 0`` is infinite or NaN rather than an error)."""
    if b == 0:
        if math.isnan(a) or a == 0:
            return math.nan
        return math.copysign(math.inf, a) * math.copysign(1.0, b)
    return a / b


def lmom_ub(x: np.ndarray) -> tuple[list[float], list[float]]:
    """lmomco ``lmom.ub``: unbiased sample L-moments by its own direct formula.

    Returned as ``(lambdas, ratios)``, as ``lmorph`` turns them into for ``pargam``.
    Only called with at least five values that are not all equal (``cspei`` checks the
    ``pwm.ub`` L-moments first), so ``lmom.ub``'s errors cannot occur.
    """
    values = sorted(x.tolist())
    n = len(values)
    l1 = l2 = l3 = l4 = l5 = 0.0
    for i, v in enumerate(values, start=1):
        cl1 = i - 1
        cl2 = cl1 * (i - 1 - 1) / 2
        cl3 = cl2 * (i - 1 - 2) / 3
        cl4 = cl3 * (i - 1 - 3) / 4
        cr1 = n - i
        cr2 = cr1 * (n - i - 1) / 2
        cr3 = cr2 * (n - i - 2) / 3
        cr4 = cr3 * (n - i - 3) / 4
        l1 = l1 + v
        l2 = l2 + v * (cl1 - cr1)
        l3 = l3 + v * (cl2 - 2 * cl1 * cr1 + cr2)
        l4 = l4 + v * (cl3 - 3 * cl2 * cr1 + 3 * cl1 * cr2 - cr3)
        l5 = l5 + v * (cl4 - 4 * cl3 * cr1 + 6 * cl2 * cr2 - 4 * cl1 * cr3 + cr4)
    c1 = n
    c2 = c1 * (n - 1) / 2
    c3 = c2 * (n - 2) / 3
    c4 = c3 * (n - 3) / 4
    c5 = c4 * (n - 4) / 5
    l1 = l1 / c1
    l2 = l2 / c2 / 2
    l3 = l3 / c3 / 3
    l4 = l4 / c4 / 4
    l5 = l5 / c5 / 5
    return [l1, l2, l3, l4, l5], [math.nan, l2 / l1, l3 / l2, l4 / l2, l5 / l2]


def are_lmom_valid(lambdas: list[float], ratios: list[float]) -> bool:
    """lmomco ``are.lmom.valid`` (with ``checkt3t4``) on ``lmorph``'d L-moments."""
    l1, l2 = lambdas[0], lambdas[1]
    t3, t4, t5 = ratios[2], ratios[3], ratios[4]
    if not math.isfinite(l1):
        return False
    if math.isnan(l2):
        return True
    if not math.isfinite(l2) or l2 <= 0:
        return False
    if math.isnan(t3):
        return True
    if abs(t3) >= 1:
        return False
    if math.isnan(t4):
        return True
    if t4 >= 1:
        return False
    if t4 < (5 * (t3 * t3) - 1) / 4:  # TAU4 < (5 * TAU3^2 - 1) / 4
        return False
    if math.isnan(t5):
        return True
    return not abs(t5) >= 1


def parglo(lambdas: list[float], ratios: list[float]) -> tuple[float, float, float]:
    """lmomco ``parglo``: generalised logistic ``(xi, alpha, kappa)`` from L-moments."""
    k = -ratios[2]
    if abs(k) <= 1e-6:
        return lambdas[0], lambdas[1], 0.0
    kk = k * math.pi / math.sin(k * math.pi)
    a = lambdas[1] / kk
    return lambdas[0] - a * (1 - kk) / k, a, k


def _exp(x: float) -> float:
    try:
        return math.exp(x)
    except OverflowError:
        return math.inf


def cdfglo(x: float, xi: float, alpha: float, kappa: float) -> float:
    """lmomco ``cdfglo``. Non-finite results become 0 (``kappa < 0``) or 1 (``> 0``)."""
    y = (x - xi) / alpha
    if kappa == 0:
        f = 1 / (1 + _exp(-y))
    else:
        arg = 1 - kappa * y
        if arg < 0 or math.isnan(arg):
            f = math.nan
        else:
            y = -(math.log(arg) if arg > 0 else -math.inf) / kappa
            f = 1 / (1 + _exp(-y))
    if not math.isfinite(f):
        if kappa < 0:
            return 0.0
        if kappa > 0:
            return 1.0
    return f


def pargam(lambdas: list[float]) -> tuple[float, float] | None:
    """lmomco ``pargam`` (two parameters): ``(alpha, beta)``, or None when invalid."""
    a1, a2, a3 = -0.308, -0.05812, 0.01765
    b1, b2, b3, b4 = 0.7213, -0.5947, -2.1817, 1.2113
    l1 = lambdas[0]
    lcv = lambdas[1] / l1
    if lcv >= 0.5:
        tt = 1 - lcv
        alpha = tt * (b1 + tt * b2) / (1 + tt * (b3 + tt * b4))
    else:
        tt = math.pi * (lcv * lcv)  # pi * LCV^2
        alpha = (1 + a1 * tt) / (tt * (1 + tt * (a2 + tt * a3)))
    beta = l1 / alpha
    if not alpha > 0 or not beta > 0:
        return None
    return alpha, beta


def standardise_month(
    fit_values: np.ndarray, values: np.ndarray, distribution: str
) -> np.ndarray | None:
    """Standard normal deviates of ``values`` from a fit to ``fit_values``.

    One calendar month of ``cspei``'s loop. Returns None when R skips the month
    (``next``), leaving its values missing.
    """
    month = np.sort(fit_values)
    if month.size < 2:  # length(month) == 0 | is.na(sd(month))
        return None
    lambdas, ratios = pwm2lmom(pwm_ub(month))
    if not are_lmom_valid(lambdas, ratios) or math.isnan(sum(lambdas)):
        return None
    if distribution == "log-Logistic":
        xi, alpha, kappa = parglo(lambdas, ratios)
        return np.array([qnorm(cdfglo(v, xi, alpha, kappa)) for v in values.tolist()])
    # Gamma: fitted to all values, zeros included, then mixed with the zero probability.
    ub_lambdas, ub_ratios = lmom_ub(month)
    if not are_lmom_valid(ub_lambdas, ub_ratios):
        return None  # R: pargam returns NULL and cdfgam stops (not reproduced)
    params = pargam(ub_lambdas)
    if params is None:
        return None  # R: pargam returns NULL and cdfgam stops (not reproduced)
    shape, scale = params
    pze = float(np.count_nonzero(month == 0)) / month.size
    out = []
    for v in values.tolist():
        g = 0.0 if v <= 0 else pgamma(v / scale, shape)
        out.append(qnorm(pze + (1 - pze) * pnorm(qnorm(g))))
    return np.array(out)


def cspei(data: np.ndarray, scale: int, ref: slice, distribution: str) -> np.ndarray:
    """Climpact's ``cspei`` on a monthly series starting in January.

    ``ref`` selects the base-period months (``window(data, ref.start, ref.end)``),
    which also start in January.
    """
    acu_pred = accumulate(data, scale)
    acu = acu_pred[ref].copy()
    acu[: scale - 1] = np.nan  # the window's own accumulation starts within the window
    std = np.full(len(data), np.nan)
    for c in range(12):
        fit = acu[c::12]
        fit = fit[~np.isnan(fit)]
        positions = np.arange(c, len(data), 12)
        positions = positions[~np.isnan(acu_pred[positions])]
        values = standardise_month(fit, acu_pred[positions], distribution)
        if values is not None:
            std[positions] = values
    std[~np.isfinite(std)] = np.nan  # Inf, -Inf and NaN become NA
    return std


# --- products ------------------------------------------------------------------------


def _scales(run: StationRun) -> tuple[int, ...]:
    return (*SCALES, run.params.spei_months)


def _reference_months(run: StationRun, months: pd.Series) -> slice:
    first_year = int(months.iloc[0][:4])
    start = (run.metadata.base_start - first_year) * 12
    stop = (run.metadata.base_end - first_year + 1) * 12
    return slice(max(start, 0), min(max(stop, 0), len(months)))


def drought_tables(
    run: StationRun, index: str, series: np.ndarray, months: pd.Series, distribution: str
) -> dict[str, pd.DataFrame]:
    """The four ``<scale>month_<index>_MON`` tables (``write.precindex.csv``).

    No tables when every value of all four is missing, as ``write.precindex.csv``
    writes nothing then; otherwise all four, even one that is missing throughout.
    """
    ref = _reference_months(run, months)
    tables = {}
    for scale in _scales(run):
        values = cspei(series, scale, ref, distribution)
        tables[f"indices/{scale}month_{index}_MON"] = pd.DataFrame(
            {"time": months.astype(object), index: values}
        )
    if all(t[index].isna().all() for t in tables.values()):
        return {}
    return tables


@product
def spi(run: StationRun) -> dict[str, pd.DataFrame]:
    """SPI at 3, 6, 12 and ``spei_months`` months (``calculate.spi``)."""
    monthly = monthly_inputs(run)
    if monthly["prec"].isna().all():
        return {}
    return drought_tables(run, "spi", monthly["prec"].to_numpy(), monthly["time"], "Gamma")


@product
def spei(run: StationRun) -> dict[str, pd.DataFrame]:
    """SPEI at 3, 6, 12 and ``spei_months`` months (``calculate.spei``)."""
    monthly = monthly_inputs(run)
    if monthly[["prec", "tmax", "tmin"]].isna().all().any():
        return {}
    pet = hargreaves(
        monthly["tmin"].to_numpy(),
        monthly["tmax"].to_numpy(),
        run.metadata.latitude,
        monthly["prec"].to_numpy(),
    )
    balance = monthly["prec"].to_numpy() - pet
    return drought_tables(run, "spei", balance, monthly["time"], "log-Logistic")
