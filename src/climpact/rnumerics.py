"""Reproduce R's floating-point accumulation where it decides results.

R's ``sum()`` and ``cumsum()`` accumulate doubles in a C ``long double``. On x86_64
(where the Climpact reference outputs were produced) that is the x87 80-bit extended
format with a 64-bit significand: each partial sum is rounded to 64 bits, and the
result is rounded to a double at the end (``sum``) or after every step (``cumsum``).

Usually the difference from numpy's double accumulation is around 1e-14 and does not
matter for the comparison tiers, but it changes the 15th significant digit that R writes
to its CSV files, so means and standardised anomalies use :func:`r_mean` and
:func:`r_var`. It also decides results in climdex.pcic's running sums (Rx3day, Rx5day): when two
windows have the same true total, R's rounding noise decides which date is reported.
numpy's ``longdouble`` only has this precision on x86, so the accumulation is emulated
exactly with integer arithmetic, giving the same answer on any platform.

Every finite double is an integer multiple of 2**-1074, so values are held as Python
integers in units of 2**-1074 and rounded explicitly (round half to even).

Rounding to 64 significant bits does not depend on the unit, so :func:`r_sum`,
:func:`r_cumsum` and :func:`r_mean` use the coarsest unit that holds every input value
exactly (2**-scale, see :func:`_scale`) instead, which keeps the integers small, and only
round when an accumulator reaches 2**64 units. When the absolute values add up to less
than 2**62 units no partial sum can need rounding, so :func:`r_sum` is the exact sum
rounded once, which is :func:`math.fsum`. The results are identical to the plain
emulation (``tests/rreference.py``), which ``tests/test_rnumerics.py`` checks.
"""

from __future__ import annotations

import math

import numpy as np

EXTENDED_BITS = 64  # x87 extended-precision significand
DOUBLE_BITS = 53
_UNIT_EXP = -1074  # every double is an integer multiple of 2**-1074


def _to_fixed(value: float) -> int:
    if not math.isfinite(value):
        raise ValueError("only finite values are supported")
    mantissa, exponent = math.frexp(value)  # value = mantissa * 2**exponent, 0.5 <= |m| < 1
    integer = int(mantissa * (1 << DOUBLE_BITS))  # exact: 53-bit integer
    shift = exponent - DOUBLE_BITS - _UNIT_EXP
    return integer << shift if shift >= 0 else integer >> -shift


def _round_bits(n: int, bits: int) -> int:
    """Round integer ``n`` to ``bits`` significant bits, ties to even."""
    a = abs(n)
    excess = a.bit_length() - bits
    if excess <= 0:
        return n
    q = a >> excess
    r = a - (q << excess)
    half = 1 << (excess - 1)
    if r > half or (r == half and q & 1):
        q += 1
    return (q << excess) if n > 0 else -(q << excess)


def _to_float(n: int) -> float:
    """Convert to the nearest double (ties to even)."""
    r = _round_bits(n, DOUBLE_BITS)
    excess = max(abs(r).bit_length() - DOUBLE_BITS, 0)  # trailing zero bits, exact shift
    magnitude = float(abs(r) >> excess)  # at most 53 bits: exact
    value = math.ldexp(magnitude, excess + _UNIT_EXP)
    return -value if r < 0 else value


_EXT_LIMIT = 1 << EXTENDED_BITS  # integers below this need no rounding to 64 bits
_FAST_SUM_BITS = 62  # margin below 2**64 units for the float estimate of sum(|x|)


def _finite(x: np.ndarray) -> np.ndarray:
    arr = np.asarray(x, dtype=float).ravel()
    if not np.isfinite(arr).all():
        raise ValueError("only finite values are supported")
    return arr


def _scale(arr: np.ndarray) -> int:
    """The smallest ``scale >= 0`` such that every value is an integer multiple of
    ``2**-scale``."""
    nonzero = arr[arr != 0]
    if nonzero.size == 0:
        return 0
    mantissa, exponent = np.frexp(nonzero)  # value = mantissa * 2**exponent
    significand = np.abs(mantissa * 2.0**DOUBLE_BITS).astype(np.int64)  # exact
    lowest_bit = significand & -significand
    trailing_zeros = np.frexp(lowest_bit.astype(float))[1] - 1  # exact: powers of two
    return max(int((DOUBLE_BITS - exponent - trailing_zeros).max()), 0)


def _scaled_ints(arr: np.ndarray, scale: int) -> list[int]:
    """The values as integers in units of ``2**-scale`` (exact)."""
    out = []
    for v in arr.tolist():
        n, d = v.as_integer_ratio()  # d is a power of two no larger than 2**scale
        out.append(n << (scale - d.bit_length() + 1))
    return out


def _scaled_float(n: int, scale: int) -> float:
    """``n * 2**-scale`` rounded to the nearest double (ties to even)."""
    if n.bit_length() <= 1000:
        return math.ldexp(float(n), -scale)  # int -> float rounds half to even
    r = abs(_round_bits(n, DOUBLE_BITS))
    excess = r.bit_length() - DOUBLE_BITS  # trailing zero bits, exact shift
    value = math.ldexp(float(r >> excess), excess - scale)
    return -value if n < 0 else value


def _ext_sum(values: list[int]) -> int:
    """Sum with every partial sum rounded to 64 significant bits."""
    acc = 0
    for v in values:
        acc += v
        if not -_EXT_LIMIT < acc < _EXT_LIMIT:
            acc = _round_bits(acc, EXTENDED_BITS)
    return acc


def r_cumsum(x: np.ndarray) -> np.ndarray:
    """R ``cumsum`` for doubles: extended-precision running sum, each output a double."""
    arr = _finite(x)
    scale = _scale(arr)
    out = np.empty(arr.size, dtype=float)
    acc = 0
    for i, v in enumerate(_scaled_ints(arr, scale)):
        acc += v
        if not -_EXT_LIMIT < acc < _EXT_LIMIT:
            acc = _round_bits(acc, EXTENDED_BITS)
        out[i] = _scaled_float(acc, scale)
    return out


def r_sum(x: np.ndarray) -> float:
    """R ``sum`` for doubles: extended-precision accumulation, rounded to a double."""
    arr = _finite(x)
    if arr.size == 0:
        return 0.0
    scale = _scale(arr)
    with np.errstate(over="ignore"):
        bound = np.abs(arr).sum()  # within a relative 1e-12 of the exact sum of |x|
    if scale <= 1000 and bound < math.ldexp(1.0, _FAST_SUM_BITS - scale):
        # No partial sum reaches 2**64 units, so none is rounded: R's result is the
        # exact sum rounded to a double (+ 0.0 turns fsum's -0.0 into R's 0).
        return math.fsum(arr.tolist()) + 0.0
    return _scaled_float(_ext_sum(_scaled_ints(arr, scale)), scale)


def _round_sticky(q: int, sticky: bool, bits: int) -> int:
    """Round non-negative ``q`` to ``bits`` significant bits, ties to even.

    ``sticky`` says whether ``q`` was truncated (a non-zero remainder below its last bit).
    """
    excess = q.bit_length() - bits
    if excess <= 0:
        return q
    low = q & ((1 << excess) - 1)
    q >>= excess
    half = 1 << (excess - 1)
    if low > half or (low == half and (sticky or q & 1)):
        q += 1
    return q << excess


def _div(a: int, n: int, bits: int = EXTENDED_BITS) -> int:
    """``a / n`` rounded to ``bits`` significant bits (``n`` a positive integer)."""
    q, r = divmod(abs(a), n)
    q = _round_sticky(q, r != 0, bits)
    return -q if a < 0 else q


def _mul(a: int, b: int, bits: int) -> int:
    """``a * b`` rounded to ``bits`` significant bits, in fixed units.

    Exact for results far above the subnormal range, which is all that is needed here.
    """
    p = _round_sticky(abs(a * b), False, bits) >> -_UNIT_EXP  # from units of 2**-2148
    return -p if (a < 0) != (b < 0) else p


def _ext(n: int) -> int:
    return _round_bits(n, EXTENDED_BITS)


def _mean_fixed(values: list[int]) -> int:
    """R's two-pass extended-precision mean (``summary.c`` ``rmean``, ``cov.c`` ``MEAN``)."""
    n = len(values)
    s = 0
    for v in values:
        s = _ext(s + v)
    s = _div(s, n)
    t = 0
    for v in values:
        t = _ext(t + _ext(v - s))
    return _ext(s + _div(t, n))


def _div_scaled(a: int, scale: int, n: int) -> tuple[int, int]:
    """``a * 2**-scale / n`` rounded to 64 significant bits, as ``(integer, scale)``.

    The numerator is shifted left until the quotient has more than 64 bits, so the
    rounding is correct, as it is in units of 2**-1074 for any value climate data has.
    """
    if a == 0:
        return 0, scale
    shift = max(EXTENDED_BITS + 2 + n.bit_length() - abs(a).bit_length(), 0)
    return _div(a << shift, n), scale + shift


def r_mean(x: np.ndarray) -> float:
    """R ``mean`` for doubles (no missing values): accumulated in extended precision,
    with R's second pass that adds the mean of the residuals."""
    arr = _finite(x)
    n = arr.size
    if n == 0:
        return math.nan
    scale = _scale(arr)
    values = _scaled_ints(arr, scale)
    s, s_scale = _div_scaled(_ext_sum(values), scale, n)
    shift = s_scale - scale
    t = 0
    for v in values:
        t = _ext(t + _ext((v << shift) - s))
    q, q_scale = _div_scaled(t, s_scale, n)
    return _scaled_float(_ext((s << (q_scale - s_scale)) + q), q_scale)


def r_var(x: np.ndarray) -> float:
    """R ``var`` for a vector without missing values (``cov.c``, Pearson).

    The mean is R's two-pass mean rounded to a double (``MEAN``); deviations from it,
    their squares and their sum are all formed in extended precision
    (``sum += (LDOUBLE)(xx[k] - xxm) * (xx[k] - xxm)`` with ``xxm`` a ``LDOUBLE``).
    """
    values = [_to_fixed(v) for v in np.asarray(x, dtype=float).tolist()]
    n = len(values)
    if n < 2:
        return math.nan
    mean = _to_fixed(_to_float(_mean_fixed(values)))
    total = 0
    for v in values:
        d = _ext(v - mean)
        total = _ext(total + _mul(d, d, EXTENDED_BITS))
    return _to_float(_div(total, n - 1))
