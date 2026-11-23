"""R's random normal numbers (climpact.rrandom), checked against R."""

from pathlib import Path

import numpy as np
import pytest

from climpact import rdist
from climpact.rrandom import RNormal, qnorm, rnorm

REFERENCE = Path(__file__).parents[3] / "reference" / "homogeneity" / "output"


def test_rnorm_is_r_bit_for_bit():
    # set.seed(1); rnorm(10) from the R reference image (run_homogeneity.R)
    expected = np.loadtxt(REFERENCE / "potsdam" / "rnorm.csv", skiprows=1)
    assert rnorm(10, 1).tolist() == expected.tolist()


def test_the_stream_continues_across_calls():
    rng = RNormal(1)
    assert np.concatenate([rng.normal(3), rng.normal(7)]).tolist() == rnorm(10, 1).tolist()


@pytest.mark.parametrize("seed", [0, 42, -7, 2**31 - 1])
def test_other_seeds_give_uniforms_in_the_open_interval(seed):
    u = RNormal(seed).uniform(10_000)
    assert ((u > 0) & (u < 1)).all()
    assert abs(u.mean() - 0.5) < 0.02


def test_qnorm_matches_the_scalar_port():
    rng = np.random.default_rng(3)
    p = np.concatenate([rng.uniform(size=2000), 10.0 ** -rng.uniform(1, 17, size=500)])
    p = np.concatenate([p, 1 - p[p > 1e-15]])
    assert qnorm(p).tolist() == [rdist.qnorm(v) for v in p.tolist()]
