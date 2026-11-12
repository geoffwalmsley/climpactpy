import numpy as np
import pytest

from climpact.rnumerics import r_cumsum, r_sum

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
