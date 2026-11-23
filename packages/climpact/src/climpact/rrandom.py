"""R's random normal numbers: ``set.seed(seed); rnorm(n)`` with R's default generators.

The SNHT p-value of R's ``trend::snh.test`` comes from a Monte Carlo simulation drawn with
R's random number generator (:mod:`climpact.homogeneity.snht`). With the same seed and
the same numbers, the Python p-value is R's exactly instead of only to within Monte
Carlo error.

R's defaults (``RNGkind()``: "Mersenne-Twister", "Inversion"; ``src/main/RNG.c`` and
``src/nmath/snorm.c``, R 4.6.1):

- ``set.seed(seed)`` scrambles the seed with 50 steps of the congruential generator
  ``seed = 69069 * seed + 1`` (mod 2**32), then fills the 625 words of the Mersenne-Twister
  state with the next 625 steps. The first word is the position, which is then set to
  624, so the first draw regenerates the whole state.
- The generator is the standard MT19937 (numpy's :class:`numpy.random.MT19937`, given
  that state). A uniform is its 32-bit output times 2**-32, moved into (0, 1) if it is
  exactly 0 (``fixup``).
- A normal ("Inversion") takes two uniforms: ``u = floor(2**27 * u1) + u2``, then
  ``qnorm(u / 2**27)``. :func:`qnorm` is a vectorised copy of R's ``qnorm`` (AS 241),
  operation by operation, as in :func:`climpact.rdist.qnorm`.

``tests/test_rrandom.py`` checks the numbers against R's.
"""

from __future__ import annotations

import numpy as np

_BIG = 134217728.0  # 2**27
_TWO_M32 = 2.3283064365386963e-10  # 2**-32
_I2_32M1 = 2.328306437080797e-10  # 1 / (2**32 - 1), R's fixup value
_MT_WORDS = 624

# R's qnorm (AS 241) coefficients, highest power first.
_CENTRAL_NUM = (
    2509.0809287301226727,
    33430.575583588128105,
    67265.770927008700853,
    45921.953931549871457,
    13731.693765509461125,
    1971.5909503065514427,
    133.14166789178437745,
    3.387132872796366608,
)
_CENTRAL_DEN = (
    5226.495278852854561,
    28729.085735721942674,
    39307.89580009271061,
    21213.794301586595867,
    5394.1960214247511077,
    687.1870074920579083,
    42.313330701600911252,
    1.0,
)
_NEAR_NUM = (
    7.7454501427834140764e-4,
    0.0227238449892691845833,
    0.24178072517745061177,
    1.27045825245236838258,
    3.64784832476320460504,
    5.7694972214606914055,
    4.6303378461565452959,
    1.42343711074968357734,
)
_NEAR_DEN = (
    1.05075007164441684324e-9,
    5.475938084995344946e-4,
    0.0151986665636164571966,
    0.14810397642748007459,
    0.68976733498510000455,
    1.6763848301838038494,
    2.05319162663775882187,
    1.0,
)
_FAR_NUM = (
    2.01033439929228813265e-7,
    2.71155556874348757815e-5,
    0.0012426609473880784386,
    0.026532189526576123093,
    0.29656057182850489123,
    1.7848265399172913358,
    5.4637849111641143699,
    6.6579046435011037772,
)
_FAR_DEN = (
    2.04426310338993978564e-15,
    1.4215117583164458887e-7,
    1.8463183175100546818e-5,
    7.868691311456132591e-4,
    0.0148753612908506148525,
    0.13692988092273580531,
    0.59983220655588793769,
    1.0,
)


def _horner(r: np.ndarray, coeffs: tuple[float, ...]) -> np.ndarray:
    """``(...((r * c0 + c1) * r + c2) ... ) * r + cn``, in R's order of operations."""
    value = r * coeffs[0] + coeffs[1]
    for c in coeffs[2:]:
        value = value * r + c
    return value


def qnorm(p: np.ndarray) -> np.ndarray:
    """R ``qnorm(p)`` for an array of probabilities in (0, 1), with
    ``2**-59 <= min(p, 1 - p)`` (so R's extreme-tail series, for ``r > 27``, is never
    needed): the probabilities :class:`RNormal` makes."""
    p = np.asarray(p, dtype=float)
    q = p - 0.5
    out = np.empty_like(p)
    central = np.abs(q) <= 0.425
    if central.any():
        qc = q[central]
        r = 0.180625 - qc * qc
        out[central] = qc * _horner(r, _CENTRAL_NUM) / _horner(r, _CENTRAL_DEN)
    tail = ~central
    if tail.any():
        qt, pt = q[tail], p[tail]
        # R forms 1 - p as 0.5 - p + 0.5.
        r = np.sqrt(-np.log(np.where(qt > 0, 0.5 - pt + 0.5, pt)))
        if (r > 27).any():
            raise ValueError("qnorm: probability too close to 0 or 1")
        near = r <= 5.0
        val = np.empty_like(r)
        rn = r[near] + -1.6
        val[near] = _horner(rn, _NEAR_NUM) / _horner(rn, _NEAR_DEN)
        rf = r[~near] + -5.0
        val[~near] = _horner(rf, _FAR_NUM) / _horner(rf, _FAR_DEN)
        out[tail] = np.where(qt < 0.0, -val, val)
    return out


def _mt_state(seed: int) -> np.ndarray:
    """The Mersenne-Twister state words ``set.seed(seed)`` makes (``RNG_Init``)."""
    s = seed & 0xFFFFFFFF
    for _ in range(50):
        s = (69069 * s + 1) & 0xFFFFFFFF
    words = np.empty(_MT_WORDS + 1, dtype=np.uint32)
    for j in range(_MT_WORDS + 1):
        s = (69069 * s + 1) & 0xFFFFFFFF
        words[j] = s
    # words[0] is R's position word (dummy[0]), which FixupSeeds sets to 624.
    return words[1:]


class RNormal:
    """A stream of R's normal random numbers after ``set.seed(seed)``."""

    def __init__(self, seed: int) -> None:
        self._bits = np.random.MT19937()
        self._bits.state = {
            "bit_generator": "MT19937",
            "state": {"key": _mt_state(seed), "pos": _MT_WORDS},
        }

    def uniform(self, n: int) -> np.ndarray:
        """The next ``n`` of R's ``unif_rand()``."""
        u = self._bits.random_raw(n).astype(float) * _TWO_M32
        u[u <= 0.0] = 0.5 * _I2_32M1
        return u

    def normal(self, n: int) -> np.ndarray:
        """The next ``n`` of R's ``norm_rand()`` (``rnorm(n)``)."""
        u = self.uniform(2 * n)
        return qnorm((np.floor(_BIG * u[0::2]) + u[1::2]) / _BIG)


def rnorm(n: int, seed: int) -> np.ndarray:
    """R ``set.seed(seed); rnorm(n)``."""
    return RNormal(seed).normal(n)
