import math
from fractions import Fraction

import numpy as np
import pytest

from climpact.rnumerics import r_cumsum, r_mean, r_sum, r_var

HAS_X87 = np.finfo(np.longdouble).nmant == 63


def native_cumsum(x):
    acc = np.longdouble(0)
    out = []
    for v in x:
        acc += np.longdouble(v)
        out.append(float(acc))
    return np.array(out)


def test_simple_values():
    assert r_sum(np.array([0.1, 0.2, 0.3])) == pytest.approx(0.6)
    assert r_cumsum(np.array([1.0, 2.0, -3.0])).tolist() == [1.0, 3.0, 0.0]
    assert r_sum(np.array([])) == 0.0
    assert r_cumsum(np.array([-0.5, -0.25])).tolist() == [-0.5, -0.75]


def test_differs_from_double_accumulation():
    """Extended precision keeps bits that double accumulation loses."""
    x = np.array([1.0, 2.0**-60, -1.0])
    assert r_sum(x) == 2.0**-60
    assert np.cumsum(x)[-1] == 0.0


@pytest.mark.skipif(not HAS_X87, reason="numpy longdouble is not x87 80-bit on this platform")
def test_matches_native_x87_long_double():
    rng = np.random.default_rng(0)
    x = np.round(rng.gamma(0.3, 8.0, size=20000), 1)
    increments = np.concatenate([[x[:5].sum()], x[5:] - x[:-5]])
    assert np.array_equal(r_cumsum(increments), native_cumsum(increments))


def test_mean_and_var_close_to_numpy():
    rng = np.random.default_rng(2)
    x = rng.normal(20, 4, 500)
    assert r_mean(x) == pytest.approx(x.mean(), rel=1e-15)
    assert r_var(x) == pytest.approx(x.var(ddof=1), rel=1e-14)
    assert math.isnan(r_mean(np.array([])))
    assert math.isnan(r_var(np.array([1.0])))


def test_mean_uses_extended_precision_two_pass():
    """Values that cancel in double arithmetic keep their small part in R's mean."""
    x = np.array([1.0, 2.0**-60, -1.0, 0.0])
    assert r_mean(x) == 2.0**-62
    assert np.mean(x) == 0.0


def test_var_is_correctly_rounded_for_short_series():
    x = np.array([26.0, 40.0, 33.3])
    exact = sum((Fraction(v) - Fraction(r_mean(x))) ** 2 for v in x) / 2
    assert r_var(x) == float(exact)


def native_mean_var(x):
    """R's summary.c mean and cov.c var, written with numpy's x87 longdouble."""
    ld = np.longdouble
    n = len(x)
    s = ld(0)
    for v in x:
        s += ld(v)
    s /= n
    t = ld(0)
    for v in x:
        t += ld(v) - s
    mean = s + t / n
    xm = ld(float(mean))
    total = ld(0)
    for v in x:
        total += (ld(v) - xm) * (ld(v) - xm)
    return float(mean), float(total / (n - 1))


@pytest.mark.skipif(not HAS_X87, reason="numpy longdouble is not x87 80-bit on this platform")
def test_mean_var_match_native_x87_long_double():
    rng = np.random.default_rng(3)
    for _ in range(20):
        x = np.round(rng.normal(15, 6, 365), 1) / 7
        assert (r_mean(x), r_var(x)) == native_mean_var(x)
