"""The original (slow, obviously exact) implementations of the R-precision sums and
R number formatting, kept as references for the faster versions in
``climpact.rnumerics`` and ``climpact.io.climpact_csv``: the tests check that both give
bit-identical results on many random and constructed inputs."""

from __future__ import annotations

import math
from fractions import Fraction

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


def r_cumsum(x: np.ndarray) -> np.ndarray:
    """R ``cumsum`` for doubles: extended-precision running sum, each output a double."""
    acc = 0
    values = np.asarray(x, dtype=float).tolist()
    out = np.empty(len(values), dtype=float)
    for i, v in enumerate(values):
        acc = _round_bits(acc + _to_fixed(v), EXTENDED_BITS)
        out[i] = _to_float(acc)
    return out


def r_sum(x: np.ndarray) -> float:
    """R ``sum`` for doubles: extended-precision accumulation, rounded to a double."""
    acc = 0
    for v in np.asarray(x, dtype=float).tolist():
        acc = _round_bits(acc + _to_fixed(v), EXTENDED_BITS)
    return _to_float(acc)


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


def r_mean(x: np.ndarray) -> float:
    """R ``mean`` for doubles (no missing values): accumulated in extended precision,
    with R's second pass that adds the mean of the residuals."""
    values = [_to_fixed(v) for v in np.asarray(x, dtype=float).tolist()]
    if not values:
        return math.nan
    return _to_float(_mean_fixed(values))


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


# --- R number formatting (climpact.io.climpact_csv) ---

MISSING_TOKEN = "-99.9"
R_DIGITS = 15


def _round_extended(q: Fraction) -> Fraction:
    """Round a positive rational to the x87 extended format (64-bit significand)."""
    e = q.numerator.bit_length() - q.denominator.bit_length()
    if Fraction(2) ** e > q:
        e -= 1
    shift = EXTENDED_BITS - 1 - e  # scale so the significand is a 64-bit integer
    scaled = q * Fraction(2) ** shift
    n = round(scaled)  # Fraction rounding is half to even
    return Fraction(n) / Fraction(2) ** shift


def _r_scientific(r: float, digits: int) -> tuple[int, int, bool]:
    """R ``scientific()`` (``src/main/format.c``) for ``r > 0``: ``(kpower, nsig,
    roundingwidens)``.

    R scales ``r`` by a power of ten in long double, rounds to a ``digits``-digit
    integer and counts its trailing zeros. A value just below a rounding boundary can
    therefore be given fewer significant digits than correct rounding would, and is
    then printed rounded to that many digits.
    """
    kp = math.floor(math.log10(r)) - digits + 1
    r_prec = _round_extended(Fraction(r) / Fraction(10) ** kp)
    if r_prec < 10 ** (digits - 1):
        r_prec = _round_extended(r_prec * 10)
        kp -= 1
    alpha = round(r_prec)  # nearbyintl: half to even; at most 10**digits, exact as double
    nsig = digits
    for _ in range(digits):
        if alpha % 10:
            break
        alpha //= 10
        nsig -= 1
    if nsig == 0:
        nsig = 1
        kp += 1
    kpower = kp + digits - 1
    rgt = min(max(digits - kpower, 0), 27)
    fuzz = 0.5 / 10.0**rgt
    widens = 0 < kpower <= 27 and Fraction(r) < Fraction(10) ** kpower - Fraction(fuzz)
    return kpower, nsig, widens


def format_r_number(value: float, digits: int = R_DIGITS) -> str:
    """Format a double exactly as R's ``write.table`` and ``as.character`` do.

    Reproduces ``formatReal`` for a single value: the number of significant digits
    (at most ``digits``) comes from R's ``scientific()``, and fixed notation is used
    unless scientific notation is narrower (``scipen = 0``). Missing values are written
    as :data:`MISSING_TOKEN`.
    """
    x = float(value)
    if math.isnan(x):
        return MISSING_TOKEN
    if math.isinf(x):
        return "Inf" if x > 0 else "-Inf"
    if x == 0:
        return "0"
    neg = int(x < 0)
    kpower, nsig, widens = _r_scientific(abs(x), digits)
    left = kpower + 1 - widens
    rgt = max(nsig - left, 0)
    fixed_width = neg + max(left, 1) + rgt + (rgt != 0)
    exp_digits = 2 if (left > 100 or left <= -99) else 1
    sci_width = neg + (nsig > 1) + (nsig - 1) + 4 + exp_digits
    if fixed_width <= sci_width:
        return f"{x:.{rgt}f}"
    return f"{x:.{nsig - 1}e}"
