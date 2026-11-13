"""R's qnorm, pnorm and pgamma against values printed by R 4.6.1 (tests/data/r_rdist.R)."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from climpact.rdist import lgamma1p, libm_lgamma, pgamma, pnorm, qnorm

from .libm import GLIBC_X86_64, LIBM_ATOL, LIBM_RTOL

DATA = Path(__file__).parent / "data"


def r_values() -> dict[str, list[list[float]]]:
    out: dict[str, list[list[float]]] = {}
    for line in (DATA / "r_rdist.txt").read_text().splitlines():
        name, *fields = line.split()
        out.setdefault(name, []).append([float.fromhex(f) for f in fields])
    return out


R = r_values()


def mismatches(pairs: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Pairs that differ: bit for bit on glibc x86_64, otherwise beyond the libm tolerance."""
    if GLIBC_X86_64:
        return [(a, b) for a, b in pairs if a != b]
    return [(a, b) for a, b in pairs if not math.isclose(a, b, rel_tol=LIBM_RTOL, abs_tol=0)]


def test_qnorm():
    pairs = [(qnorm(p), expected) for p, expected in R["qnorm"]]
    assert len(pairs) == 706
    assert not mismatches(pairs)


def test_pnorm():
    pairs = [(pnorm(x), expected) for x, expected in R["pnorm"]]
    assert len(pairs) == 706
    assert not mismatches(pairs)


def test_pgamma():
    pairs = [(pgamma(q, shape), expected) for q, shape, expected in R["pgamma"]]
    assert len(pairs) == 400
    assert not mismatches(pairs)


def test_qnorm_is_exact_without_libm():
    """The central region of qnorm is plain arithmetic: identical to R on any platform."""
    central = [(qnorm(p), e) for p, e in R["qnorm"] if abs(p - 0.5) <= 0.425]
    assert len(central) > 300
    assert all(a == b for a, b in central)


@pytest.mark.parametrize(
    ("p", "expected"), [(0.0, -math.inf), (1.0, math.inf), (math.nan, math.nan), (-0.1, math.nan)]
)
def test_qnorm_boundaries(p, expected):
    got = qnorm(p)
    assert (math.isnan(got) and math.isnan(expected)) or got == expected


def test_pnorm_tails_and_scales():
    assert pnorm(math.inf) == 1.0 and pnorm(-math.inf) == 0.0
    assert pnorm(-40.0) == 0.0  # below R's underflow limit (-38.4674)
    assert pnorm(1.5, lower_tail=False) == pytest.approx(1 - pnorm(1.5), rel=1e-15)
    assert pnorm(-3.0, log_p=True) == pytest.approx(math.log(pnorm(-3.0)), rel=1e-15)


def test_pgamma_edge_cases():
    assert pgamma(0.0, 2.0) == 0.0
    assert pgamma(-1.0, 2.0) == 0.0
    assert pgamma(math.inf, 2.0) == 1.0
    assert pgamma(1.0, 0.0) == 1.0
    assert math.isnan(pgamma(1.0, -1.0))
    assert pgamma(6.0, 2.0, scale=3.0) == pgamma(2.0, 2.0)  # q / scale first, as in R
    # A probability below DBL_MIN / DBL_EPSILON is recomputed on the log scale (R values).
    assert pgamma(1.0, 170.0) == float.fromhex("0x1.2550f77e9521ap-1021")
    assert pgamma(3.0, 200.0) == float.fromhex("0x1.3c66273a72bdap-933")


# glibc 2.39's lgamma, the C library of the R reference image (rocker/r-ver:4.6.1 on Ubuntu
# 24.04), printed there with `printf("%a", lgamma(x))`. Newer glibc releases differ in the last
# bit for some inputs (e.g. Ubuntu 26.04), so the port is checked against these fixed values
# rather than against whatever libm the test machine has.
GLIBC_2_39_LGAMMA = {
    0.3: "0x1.188637a6c4196p+0",
    0.7: "0x1.0b20c891cde74p-2",
    0.95: "0x1.fb648aaf97604p-6",
    1.1: "-0x1.988e1705d89eap-5",
    1.5: "-0x1.eeb95b094c191p-4",
    1.9: "-0x1.3f5bf3c4bb75ap-5",
    2.5: "0x1.2383e809a67e8p-2",
    3.3: "0x1.f964fc1bf8d4p-1",
    5.0: "0x1.96ca77c922cf9p+1",
    7.99: "0x1.10290e198803cp+3",
    8.5: "0x1.319398ed5be28p+3",
    42.0: "0x1.c8230869ca105p+6",
    1e20: "0x1.e873977d7ba97p+71",
}


def test_libm_lgamma_matches_glibc_2_39():
    """glibc's lgamma, as R's stirlerr calls it (CPython's math.lgamma differs).

    Exact on glibc x86_64, where the port's own exp/log calls match R's platform; within
    the documented libm tolerance elsewhere.
    """
    xs = list(GLIBC_2_39_LGAMMA)
    ours = [libm_lgamma(x) for x in xs]
    expected = [float.fromhex(h) for h in GLIBC_2_39_LGAMMA.values()]
    assert ours == pytest.approx(expected, rel=1e-14, abs=LIBM_ATOL)
    if GLIBC_X86_64:
        assert ours == expected


def test_lgamma1p_small_argument():
    assert lgamma1p(1e-8) == pytest.approx(math.lgamma(1 + 1e-8), rel=1e-12)
    assert lgamma1p(0.7) == pytest.approx(math.lgamma(1.7), rel=1e-14)
