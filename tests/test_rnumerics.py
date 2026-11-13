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


def bits(values) -> list[str]:
    return [float(v).hex() for v in np.atleast_1d(np.asarray(values, dtype=float))]


def random_series(rng, count):
    """Climate-like and adversarial series: decimals, mixed magnitudes, cancellation."""
    for _ in range(count):
        n = int(rng.choice([1, 2, 3, 30, 31, 365]))
        kind = rng.integers(0, 7)
        if kind == 0:
            yield np.round(rng.normal(15, 10, n), 1)
        elif kind == 1:
            yield np.round(rng.gamma(0.3, 8.0, n), 1)
        elif kind == 2:
            yield np.round(rng.normal(15, 6, n), 1) / 7
        elif kind == 3:
            yield rng.normal(0, 1, n) * 10.0 ** rng.integers(-20, 20, n)
        elif kind == 4:
            yield rng.choice([1.0, -1.0, 2.0**-60, 2.0**-70, 3.0, 1e16, -1e16, 0.1, -0.0], n)
        elif kind == 5:
            yield rng.integers(0, 30, n) / 29.0
        else:
            yield rng.uniform(-1, 1, n) * 2.0 ** rng.integers(-300, 300, n)


@pytest.mark.parametrize("name", ["r_sum", "r_cumsum", "r_mean"])
def test_matches_plain_emulation(name):
    """The scaled and fsum fast paths give the same bits as the plain emulation in units
    of 2**-1074 (tests/rreference.py, the original implementation)."""
    import climpact.rnumerics as fast

    from . import rreference

    rng = np.random.default_rng(42)
    for x in random_series(rng, 400):
        assert bits(getattr(fast, name)(x)) == bits(getattr(rreference, name)(x)), x


def test_sum_at_the_fast_path_limit():
    """Partial sums just below and above 2**64 units of the finest value."""
    from . import rreference

    unit = 2.0**-52
    for total in (2.0**11, 2.0**12, 2.0**13):
        x = np.array([total / 2, total / 2 - unit, unit, unit / 2, -unit / 4])
        assert bits(r_sum(x)) == bits(rreference.r_sum(x))
    assert bits(r_sum(np.array([-0.0]))) == bits(rreference.r_sum(np.array([-0.0])))
    with pytest.raises(ValueError):
        r_sum(np.array([1.0, np.inf]))


def test_window_sums_match_r_sum():
    """r_window_sums gives r_sum of every window, on both of its paths: values whose
    exact sum fits 62 bits (float data, kelvin conversions) and decimal doubles that
    need R's rounding emulation."""
    from climpact.rnumerics import r_window_sums

    rng = np.random.default_rng(0)
    cases = [
        np.round(rng.normal(10, 8, (3, 800)), 1) / 2,  # decimal doubles: some slow windows
        rng.normal(290, 10, (2, 800)).astype(np.float32).astype(float) - 273.15,
        rng.normal(0, 1e-3, (2, 300)),
        rng.normal(0, 1e5, (1, 300)) * rng.random((1, 300)),
    ]
    for x in cases:
        x[rng.random(x.shape) < 0.1] = np.nan
        x[0, 40:80] = np.nan  # an all-missing window sums to 0
        got = r_window_sums(x, 30)
        expected = [
            [r_sum(row[k : k + 30][~np.isnan(row[k : k + 30])]) for k in range(row.size - 29)]
            for row in x
        ]
        assert np.array_equal(got, np.array(expected))
    assert r_window_sums(np.ones((2, 10)), 30).shape == (2, 0)
