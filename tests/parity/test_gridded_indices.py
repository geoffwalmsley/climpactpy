"""Gridded index netCDF files against R's (``climpact.ncdf.wrapper.r``).

For each run of ``reference/gridded/runs.csv`` and each index file R wrote, the file
written by :func:`climpact.gridded.write_grid_indices` must have the same name, and
each index variable (and ``day_of_<index>``) identical values (``EXACT``: R stores
float32, so both are rounded to float32 the same way), the same missing values (the
fill value, and NaN where R stores NaN) and the same layout and attributes, apart from
the run-dependent ones. Files of indices not ported yet (``hw``, ``hwEHF``, ``spi``,
``spei``) are expected failures.
"""

from __future__ import annotations

from pathlib import Path

import netCDF4
import numpy as np
import pytest

from climpact.gridded import open_grid, write_grid_indices
from climpact.gridded.indices import NOT_PORTED

from .catalogue import GRID_RUNS
from .test_gridded import AUTHOR, PYTHON_ONLY, R_ONLY, RUN_DEPENDENT, _attrs, _same

COORDINATES = {"time", "time_bnds", "lat", "lon"}


def _index_of(path: Path) -> str:
    return path.name.split("_")[0]


def _cases():
    files, variables = [], []
    for run, spec in GRID_RUNS.items():
        for path in sorted(spec.indices_dir.glob("*.nc")):
            files.append((run, path.name))
            with netCDF4.Dataset(path) as nc:
                for var in nc.variables:
                    if var not in COORDINATES and len(nc.variables[var].dimensions) >= 3:
                        variables.append((run, path.name, var))
    return files, variables


FILES, VARIABLES = _cases()


def _key(name: str) -> str:
    """``fd_MON`` from ``fd_MON_climpactpy_historical_NA_1966-2005.nc``."""
    return "_".join(name.split("_")[:2])


def _expect_ported(name: str) -> None:
    if name.split("_")[0] in NOT_PORTED:
        pytest.xfail("not yet ported: heatwaves, EHF, SPI and SPEI on grids (#87)")


@pytest.fixture(scope="session")
def grid_indices_dir(tmp_path_factory):
    """Factory returning the directory of the index files Python writes for a run."""
    cache = {}

    def get(run: str) -> Path:
        if run not in cache:
            spec = GRID_RUNS[run]
            # Small blocks (one row) and batches, and two threads, so all are exercised.
            inp = open_grid(spec.input_paths, spec.names, max_values=4 * 3 * 14610)
            out = tmp_path_factory.mktemp(f"grid_indices_{run}")
            template = next(spec.indices_dir.glob("fd_ANN_*.nc")).name.replace(
                "fd_ANN", "var_daily"
            )
            write_grid_indices(
                inp,
                out,
                spec.base_start,
                spec.base_end,
                template=template,
                thresholds_file=spec.indices_thresholds_path,
                author=AUTHOR,
                workers=2,
                cells_per_batch=3,
            )
            cache[run] = out
        return cache[run]

    return get


@pytest.mark.parity
@pytest.mark.parametrize(
    ("run", "name", "var"), VARIABLES, ids=[f"{r}/{_key(n)}/{v}" for r, n, v in VARIABLES]
)
def test_gridded_indices(run, name, var, grid_indices_dir):
    _expect_ported(name)
    path = grid_indices_dir(run) / name
    assert path.exists(), f"{name} not written"
    with netCDF4.Dataset(GRID_RUNS[run].indices_dir / name) as r, netCDF4.Dataset(path) as py:
        assert var in py.variables, f"{var} not written"
        expected, actual = r.variables[var], py.variables[var]
        assert actual.dimensions == expected.dimensions
        assert actual.dtype == expected.dtype
        e, a = expected[:], actual[:]
        e_mask, a_mask = np.ma.getmaskarray(e), np.ma.getmaskarray(a)
        assert np.array_equal(e_mask, a_mask), (
            f"missing values differ in {np.count_nonzero(e_mask != a_mask)} places"
        )
        ev, av = np.ma.getdata(e)[~e_mask], np.ma.getdata(a)[~a_mask]
        e_nan, a_nan = np.isnan(ev), np.isnan(av)
        assert np.array_equal(e_nan, a_nan), (
            f"NaN differs in {np.count_nonzero(e_nan != a_nan)} places"
        )
        differ = ev[~e_nan] != av[~a_nan]
        assert not differ.any(), (
            f"{np.count_nonzero(differ)} values differ, largest by "
            f"{np.max(np.abs(ev[~e_nan][differ] - av[~a_nan][differ]))}"
        )


@pytest.mark.parity
@pytest.mark.parametrize(("run", "name"), FILES, ids=[f"{r}/{_key(n)}" for r, n in FILES])
def test_gridded_indices_layout(run, name, grid_indices_dir):
    """Dimensions, variables (order, types, values of the coordinates) and attributes
    match R's file."""
    _expect_ported(name)
    path = grid_indices_dir(run) / name
    assert path.exists(), f"{name} not written"
    with netCDF4.Dataset(GRID_RUNS[run].indices_dir / name) as r, netCDF4.Dataset(path) as py:
        assert py.data_model == r.data_model
        assert {n: (len(d), d.isunlimited()) for n, d in py.dimensions.items()} == {
            n: (len(d), d.isunlimited()) for n, d in r.dimensions.items()
        }
        assert list(py.variables) == list(r.variables)
        for var in COORDINATES & set(r.variables):
            assert py.variables[var].dtype == r.variables[var].dtype, var
            assert py.variables[var].dimensions == r.variables[var].dimensions, var
            assert np.array_equal(py.variables[var][:], r.variables[var][:]), var

        r_global, py_global = _attrs(r), _attrs(py)
        assert set(r_global) - R_ONLY == set(py_global) - PYTHON_ONLY
        for key in set(r_global) - R_ONLY - RUN_DEPENDENT:
            assert _same(py_global[key], r_global[key]), key
        for var, r_var in r.variables.items():
            r_attrs, py_attrs = _attrs(r_var), _attrs(py.variables[var])
            assert set(py_attrs) == set(r_attrs), var
            for key in r_attrs:
                assert _same(py_attrs[key], r_attrs[key]), f"{var}:{key}"
