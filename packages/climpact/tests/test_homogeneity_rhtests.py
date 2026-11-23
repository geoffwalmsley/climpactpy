"""The port of RHtestsV4's PMFred and PMTred detection (climpact.homogeneity.rhtests, #34).

The parity tests run :func:`pmf` and :func:`pmt` on the series in
``reference/homogeneity/series/`` and compare them with RHtests' own results for the same
series (``reference/homogeneity/output/<run>/rhtests.csv``, parsed from its ``_1Cs.txt``
and ``_Ustat.txt`` files by ``reference/r/run_homogeneity.R``): the changepoints' dates,
labels and Nseg exactly, the numbers to the 4 decimals RHtests prints. A series RHtests
refused (``rhtests_series.csv`` has its error) must raise :class:`RHtestsError`.

The penalties and critical values were printed by R from the same RHtests file
(``source("/opt/rhtests/RHtestsV4_20190301.r")`` in the reference image).
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import numpy as np
import pytest

from climpact.homogeneity import rhtests
from climpact.homogeneity.rhtests import RHtestsError, pk_pmft, pk_pmt, pmf, pmt

REFERENCE = Path(__file__).parents[3] / "reference" / "homogeneity"
RUNS = sorted(
    p.name for p in (REFERENCE / "output").iterdir() if (p / "rhtests_series.csv").is_file()
)
# RHtests prints these to 4 decimals (sprintf("%10.4f") or round(x, 4)).
PRINTED = ("statistic", "cv", "cv_low", "cv_high", "prob", "prob_low", "prob_high", "step")
PRINTED_TOLERANCE = 5e-5 + 1e-9


def _read_csv(path: Path) -> list[dict[str, str]]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _series(run: str) -> dict[tuple[str, str], tuple[np.ndarray, np.ndarray, np.ndarray]]:
    rows = defaultdict(list)
    for row in _read_csv(REFERENCE / "series" / f"{run}.csv"):
        rows[(row["variable"], row["series"])].append(row)
    return {
        key: (
            np.array([int(r["year"]) for r in group]),
            np.array([int(r["month"]) for r in group]),
            np.array([float(r["value"]) if r["value"] else np.nan for r in group]),
        )
        for key, group in rows.items()
    }


def _cases() -> list:
    cases = []
    for run in RUNS:
        for row in _read_csv(REFERENCE / "output" / run / "rhtests_series.csv"):
            key = (run, row["variable"], row["series"], row["method"])
            cases.append(pytest.param(*key, id="-".join(key)))
    return cases


@pytest.mark.parametrize(("run", "variable", "series", "method"), _cases())
def test_matches_rhtests(run, variable, series, method):
    years, months, values = _series(run)[(variable, series)]
    summary = {
        (r["variable"], r["series"], r["method"]): r
        for r in _read_csv(REFERENCE / "output" / run / "rhtests_series.csv")
    }[(variable, series, method)]
    detect = {"pmf": pmf, "pmt": pmt}[method]
    if summary["error"]:
        with pytest.raises(RHtestsError):
            detect(years, months, values)
        return
    expected = [
        r
        for r in _read_csv(REFERENCE / "output" / run / "rhtests.csv")
        if (r["variable"], r["series"], r["method"]) == (variable, series, method)
    ]
    assert len(expected) == int(summary["breaks"])
    result = detect(years, months, values)
    assert result.method == method
    got = [
        {
            "date": str(years[c.position] * 10000 + months[c.position] * 100),
            "label": c.label,
            "nseg": str(c.nseg),
            **{name: getattr(c, name) for name in PRINTED},
        }
        for c in result.changepoints
    ]
    assert [g["date"] for g in got] == [e["date"] for e in expected]
    for g, e in zip(got, expected, strict=True):
        assert (g["label"], g["nseg"]) == (e["label"], e["nseg"]), e["date"]
        for name in PRINTED:
            assert abs(g[name] - float(e[name])) <= PRINTED_TOLERANCE, (e["date"], name)


def test_every_reference_run_is_compared():
    runs = {p.stem for p in (REFERENCE / "series").glob("*.csv")}
    assert set(RUNS) == runs


# ---- penalties and critical values, as R computes them --------------------------------

# Pk.PMT(N) and Pk.PMFT(N) at positions 1, 2, 5, floor(N/2) and N-1 (R's 1-based k).
PK_PMT = {
    10: [0.98621371195685892, 0.999035376414113, 1.01984288066111, 1.01984288066111,
         0.98621371195685892],
    25: [0.94797584241388799, 0.96426887447862708, 1.0071871253236444, 1.040129125537484,
         0.94797584241388799],
    60: [0.90715421759658599, 0.92171444809340841, 0.96539513958387546, 1.0559278253950994,
         0.90715421759658599],
    150: [0.88259503797764471, 0.89469082371819653, 0.92494185144120655, 1.0690840060288331,
          0.88259503797764505],
    700: [0.80805844911171154, 0.81473262220685827, 0.83359490848196727, 1.0868649663674101,
          0.80805844911171154],
}  # fmt: skip
PK_PMFT = {
    20: [0.98908200590583073, 1.0071437449753045, 1.0334294842470877, 0.98119999999999996,
         0.98908200590583073],
    45: [0.92766864856723485, 0.95501987247262943, 1.0075150717927652, 0.98516604165609389,
         0.92766864856723485],
    60: [0.90804386988481745, 0.93206056850662733, 0.99245154116307532, 0.98360000000000003,
         0.90804386988481745],
    150: [0.856691779770404, 0.87608671344386047, 0.92459258886414553, 0.98899999999999999,
          0.85669177977040412],
    720: [0.71248471122300583, 0.72408359242179166, 0.75697400276360338, 1.0,
          0.71248471122300583],
}  # fmt: skip


def _positions(n: int) -> list[int]:
    return [0, 1, 4, n // 2 - 1, n - 2]


@pytest.mark.parametrize("n", PK_PMT)
def test_pk_pmt(n):
    np.testing.assert_allclose(pk_pmt(n)[_positions(n)], PK_PMT[n], rtol=1e-13)
    assert len(pk_pmt(n)) == n - 1


@pytest.mark.parametrize("n", PK_PMFT)
def test_pk_pmft(n):
    np.testing.assert_allclose(pk_pmft(n)[_positions(n)], PK_PMFT[n], rtol=1e-13)
    assert len(pk_pmft(n)) == n - 1


# getPTx95 after readPTtable(1500, pkth): pkth, N, then the values at cor -0.5, 0, 0.3123
# and 0.99. N = 7 is below the table (interpolated from 0), 1300 above it (extrapolated).
PT_CRITICAL = [
    (1, 7, [0.50666666666666693, 0.84000000000000008, 1.1364000000000001, 2.3333333333333335]),
    (1, 33, [1.3879999999999997, 2.214, 2.95444, 9.0399999999999991]),
    (1, 1300, [1.4733333333333347, 2.6066666666666669, 3.5516866666666669, 20.223333333333333]),
    (4, 10, [1.4299999999999999, 2.3500000000000001, 3.1593600000000004, 5.7999999999999998]),
    (4, 59, [1.8699999999999997, 3.1080000000000001, 4.2021200000000007, 16.347999999999999]),
    (4, 1300, [1.8650000000000029, 3.2849999999999997, 4.5107066666666666, 27.838333333333335]),
    (6, 33, [3.3440000000000025, 5.6079999999999997, 7.771128, 21.059999999999999]),
    (6, 1300, [2.9466666666666677, 5.1183333333333341, 7.0392200000000003, 49.004999999999995]),
]
# getPFx95 after readPFtable(1500, pkth), at cor -0.5, 0.0123, 0.3123 and 0.99.
PF_CRITICAL = [
    (1, 15, [0.42000000000000082, 1.042336842105263, 1.6205810526315791, 3.0652631578947371]),
    (1, 59, [2.0419999999999989, 6.1893479999999998, 10.636364, 74.876999999999995]),
    (4, 20, [1.8500000000000023, 4.4487199999999998, 6.8730000000000002, 12.69]),
    (4, 33, [3.3260000000000032, 9.4288959999999999, 15.935, 54.335999999999999]),
    (4, 1300, [2.8566666666666736, 11.838666666666667, 21.654846666666668, 781.54166666666663]),
    (6, 59, [8.6380000000000088, 28.175884, 50.904540000000004, 279.39500000000004]),
    (6, 1300, [6.1783333333333363, 26.137353333333333, 48.273933333333339, 2085.6366666666668]),
]


@pytest.mark.parametrize(("pkth", "n", "values"), PT_CRITICAL)
def test_pt_critical_values(pkth, n, values):
    phi, table = rhtests._critical_table(rhtests._PT_TABLE, pkth, 1500)
    got = [rhtests._critical_value(phi, table, cor, n) for cor in (-0.5, 0.0, 0.3123, 0.99)]
    np.testing.assert_allclose(got, values, rtol=1e-12)


@pytest.mark.parametrize(("pkth", "n", "values"), PF_CRITICAL)
def test_pf_critical_values(pkth, n, values):
    phi, table = rhtests._critical_table(rhtests._PF_TABLE, pkth, 1500)
    got = [rhtests._critical_value(phi, table, cor, n) for cor in (-0.5, 0.0123, 0.3123, 0.99)]
    np.testing.assert_allclose(got, values, rtol=1e-12)


def test_critical_value_on_a_grid_value():
    # getPFx95 fails in R for a cor exactly on an interior grid value; the port gives the
    # tabulated value there, as getPTx95 does.
    phi, table = rhtests._critical_table(rhtests._PF_TABLE, 4, 60)
    assert phi[5] == 0.0
    assert rhtests._critical_value(phi, table, 0.0, 60) == table[60, 5]


def test_tables_have_every_level():
    for name, levels in ((rhtests._PF_TABLE, 18), (rhtests._PT_TABLE, 28)):
        rows = rhtests._table_rows(name)
        assert rows.shape == (44 * levels, 8)
        assert rows[-1, 0] == 1200


# ---- arguments and the series RHtests refuses ------------------------------------------


def _annual(values) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    values = np.asarray(values, dtype=float)
    return np.arange(1961, 1961 + len(values)), np.zeros(len(values), dtype=int), values


def _noise(n: int, seed: int = 1) -> np.ndarray:
    return np.random.default_rng(seed).normal(0, 0.5, n)


@pytest.mark.parametrize("detect", [pmf, pmt])
def test_level_must_have_critical_values(detect):
    with pytest.raises(ValueError, match="level must be one of"):
        detect(*_annual(_noise(60)), level=0.85)


@pytest.mark.parametrize("detect", [pmf, pmt])
def test_arrays_must_match(detect):
    years, months, values = _annual(_noise(60))
    with pytest.raises(ValueError, match="1-D arrays of one length"):
        detect(years, months[:-1], values)


@pytest.mark.parametrize("detect", [pmf, pmt])
def test_series_with_no_values(detect):
    with pytest.raises(RHtestsError, match="no values"):
        detect(*_annual(np.full(60, np.nan)))


def test_pmf_needs_consecutive_values():
    values = _noise(60)
    values[1::2] = np.nan  # 30 values, no two consecutive
    with pytest.raises(RHtestsError, match="Too many missing values"):
        pmf(*_annual(values))


def test_pmf_needs_twenty_values():
    with pytest.raises(RHtestsError, match="at least 20 values"):
        pmf(*_annual(_noise(19)))
    assert pmf(*_annual(_noise(20))).method == "pmf"


def test_pmf_series_must_be_in_order():
    years, months, values = _annual(_noise(60))
    with pytest.raises(RHtestsError, match="not continuous"):
        pmf(years[::-1], months, values)


def test_pmt_needs_eleven_values():
    values = np.full(60, np.nan)
    values[:10] = _noise(10)
    with pytest.raises(RHtestsError, match="too few for autocorrelation"):
        pmt(*_annual(values))
    values[:11] = _noise(11)
    assert pmt(*_annual(values)).method == "pmt"


def test_pmt_needs_five_values_in_every_month():
    # Read.wRef asks for 10, but counts two matrix elements per value.
    years = np.repeat(np.arange(1961, 1991), 12)
    months = np.tile(np.arange(1, 13), 30)
    values = _noise(len(years))
    march = np.flatnonzero(months == 3)
    values[march[5:]] = np.nan  # 5 values in March
    assert pmt(years, months, values).method == "pmt"
    values[march[4]] = np.nan  # 4
    with pytest.raises(RHtestsError, match="input data too few at: 300"):
        pmt(years, months, values)


# ---- a shift is found ------------------------------------------------------------------

# RHtests' _1Cs.txt for the series below (FindU, and FindU.wRef with a zero reference): the
# year before each shift, its label, PFmax or PTmax and the two critical values. The noise
# has a dip from 1977, which both find as well as the inserted shift.
SHIFTED = {
    pmf: [(1976, "Yes", 10.0059, 3.6120, 9.2028), (1990, "Yes", 71.1400, 3.7135, 10.1471)],
    pmt: [
        (1976, "Yes", 4.0273, 2.0387, 3.2916),
        (1981, "?", 2.0329, 1.9163, 3.0627),
        (1990, "Yes", 13.2517, 2.1155, 3.3536),
    ],
}


@pytest.mark.parametrize("detect", [pmf, pmt])
def test_finds_an_inserted_shift(detect):
    values = _noise(60, seed=7)
    values[30:] += 2.0  # from 1991
    years, months, values = _annual(values)
    result = detect(years, months, values)
    got = [
        (years[c.position], c.label, c.statistic, c.cv_low, c.cv_high) for c in result.changepoints
    ]
    assert [g[:2] for g in got] == [e[:2] for e in SHIFTED[detect]]
    np.testing.assert_allclose(
        [g[2:] for g in got], [e[2:] for e in SHIFTED[detect]], atol=PRINTED_TOLERANCE
    )
    assert result.changepoints[-1].step == pytest.approx(2.0, abs=0.3)
