"""Reproduce R's floating-point accumulation where it decides results.

R's ``sum()`` and ``cumsum()`` accumulate doubles in a C ``long double``. On x86_64
(where the Climpact reference outputs were produced) that is the x87 80-bit extended
format with a 64-bit significand: each partial sum is rounded to 64 bits, and the
result is rounded to a double at the end (``sum``) or after every step (``cumsum``).

Usually the difference from numpy's double accumulation is around 1e-14 and does not
matter. It does matter for climdex.pcic's running sums (Rx3day, Rx5day): when two
windows have the same true total, R's rounding noise decides which date is reported.
numpy's ``longdouble`` only has this precision on x86, so the accumulation is emulated
exactly with integer arithmetic, giving the same answer on any platform.

Every finite double is an integer multiple of 2**-1074, so values are held as Python
integers in units of 2**-1074 and rounded explicitly (round half to even).
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
