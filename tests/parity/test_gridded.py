"""Gridded thresholds netCDF against R's (``climpact.ncdf.thresholds.wrapper.r``).

For each run of ``reference/gridded/runs.csv``, the thresholds file written by
:func:`climpact.gridded.write_grid_thresholds` must have every variable of R's file
with identical values (``EXACT``: R stores doubles, so no rounding is involved) and
the same missing values, and the same dimensions, variables and attributes, apart from
the differences listed in ``EXPECTED_ATTRIBUTE_DIFFERENCES``.
"""

from __future__ import annotations

import netCDF4
import numpy as np
import pytest

from climpact.gridded import open_grid, write_grid_thresholds

from .catalogue import GRID_RUNS

AUTHOR = {"institution": "climpactpy reference", "institution_id": "CPY"}  # as run_r_gridded.sh

# Attributes whose values depend on when and by what the file was written.
RUN_DEPENDENT = {"file_created", "file_created_by_userid", "history"}
# Global attributes only R writes, and only Python writes.
R_ONLY = {"R_version"}
PYTHON_ONLY = {"climpactpy_version"}


def _variables(run: str) -> list[str]:
    with netCDF4.Dataset(GRID_RUNS[run].thresholds_path) as nc:
        return list(nc.variables)


CASES = [(run, var) for run in GRID_RUNS for var in _variables(run)]


@pytest.fixture(scope="session")
def grid_thresholds_file(tmp_path_factory):
    """Factory returning the path of the thresholds file Python writes for a run."""
    cache = {}

    def get(run: str):
        if run not in cache:
            spec = GRID_RUNS[run]
            # Small blocks and batches, so that both and the threads are exercised.
            inp = open_grid(spec.input_paths, spec.names, max_values=5 * 3 * 14610)
            out = tmp_path_factory.mktemp(f"grid_{run}") / "thresholds.nc"
            cache[run] = write_grid_thresholds(
                inp,
                out,
                spec.base_start,
                spec.base_end,
                author=AUTHOR,
                workers=2,
                cells_per_batch=3,
            )
        return cache[run]

    return get


@pytest.mark.parity
@pytest.mark.parametrize(("run", "var"), CASES, ids=[f"{r}/{v}" for r, v in CASES])
def test_gridded(run, var, grid_thresholds_file):
    with (
        netCDF4.Dataset(GRID_RUNS[run].thresholds_path) as r,
        netCDF4.Dataset(grid_thresholds_file(run)) as py,
    ):
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
        differ = ev != av
        assert not differ.any(), (
            f"{np.count_nonzero(differ)} values differ, largest by "
            f"{np.max(np.abs(ev[differ] - av[differ]))}"
        )


def _attrs(obj) -> dict:
    return {k: obj.getncattr(k) for k in obj.ncattrs()}


def _same(a, b) -> bool:
    """Equal attribute values of the same type (a float attribute must stay float)."""
    if isinstance(a, str) or isinstance(b, str):
        return a == b
    a, b = np.asarray(a), np.asarray(b)
    return a.dtype == b.dtype and np.array_equal(a, b)


@pytest.mark.parity
@pytest.mark.parametrize("run", list(GRID_RUNS))
def test_gridded_layout(run, grid_thresholds_file):
    """Dimensions, variable order and attributes match R's file."""
    with (
        netCDF4.Dataset(GRID_RUNS[run].thresholds_path) as r,
        netCDF4.Dataset(grid_thresholds_file(run)) as py,
    ):
        assert py.data_model == r.data_model
        assert {n: (len(d), d.isunlimited()) for n, d in py.dimensions.items()} == {
            n: (len(d), d.isunlimited()) for n, d in r.dimensions.items()
        }
        assert list(py.dimensions) == list(r.dimensions)
        assert list(py.variables) == list(r.variables)

        r_global, py_global = _attrs(r), _attrs(py)
        assert set(r_global) - R_ONLY == set(py_global) - PYTHON_ONLY
        for key in set(r_global) - R_ONLY - RUN_DEPENDENT:
            assert _same(py_global[key], r_global[key]), key

        input_time_units = netCDF4.Dataset(GRID_RUNS[run].input_paths[0])["time"].units
        for name, r_var in r.variables.items():
            r_attrs, py_attrs = _attrs(r_var), _attrs(py.variables[name])
            assert set(py_attrs) == set(r_attrs), name
            for key in set(r_attrs) - RUN_DEPENDENT:
                if name == "time" and key == "units" and not input_time_units.startswith("days"):
                    # R copies the input's units (hours since ...) over its own, although
                    # the values are days; Python keeps days (see TECHNICAL.md).
                    assert py_attrs[key].startswith("days since ")
                    assert r_attrs[key] == input_time_units
                    continue
                assert _same(py_attrs[key], r_attrs[key]), f"{name}:{key}"
