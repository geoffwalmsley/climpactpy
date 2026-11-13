"""Gridded input reading, threshold blocks, memory bounds and the command line."""

from __future__ import annotations

import tracemalloc

import netCDF4
import numpy as np
import pandas as pd
import pytest
import xarray as xr

from climpact.cli import main
from climpact.gridded import cell_thresholds, open_grid, write_grid_thresholds
from climpact.gridded.io import decode_ncdf4, unit_conversion
from climpact.gridded.thresholds import THRESHOLD_VARIABLES
from climpact.thresholds import InsufficientBaseData, compute_thresholds


def write_grid(
    path,
    ny=2,
    nx=3,
    start="1971-01-01",
    end="1980-12-31",
    calendar="standard",
    seed=0,
    names=("tasmax", "tasmin", "pr"),
):
    """A small grid: TX and TN in K (float), pr in kg m-2 s-1 (float)."""
    dates = pd.date_range(start, end, freq="D")
    rng = np.random.default_rng(seed)
    with netCDF4.Dataset(path, "w") as nc:
        nc.createDimension("time", None)
        nc.createDimension("lat", ny)
        nc.createDimension("lon", nx)
        t = nc.createVariable("time", "f8", ("time",))
        t.units = "days since 1950-01-01"
        t.calendar = calendar
        t[:] = netCDF4.date2num(dates.to_pydatetime(), t.units, "standard")
        lat = nc.createVariable("lat", "f8", ("lat",))
        lat.units = "degrees_north"
        lat[:] = np.linspace(-30, 30, ny)
        lon = nc.createVariable("lon", "f8", ("lon",))
        lon.units = "degrees_east"
        lon[:] = np.linspace(0, 90, nx)
        season = 8 * np.cos(2 * np.pi * dates.day_of_year.to_numpy() / 365.25)[:, None, None]
        shape = (dates.size, ny, nx)
        for name, units, values in (
            (names[0], "K", 295 + season + rng.normal(0, 3, shape)),
            (names[1], "K", 283 + season + rng.normal(0, 3, shape)),
            (names[2], "kg m-2 s-1", np.maximum(rng.gamma(0.5, 6, shape) - 1, 0) / 86400),
        ):
            v = nc.createVariable(name, "f4", ("time", "lat", "lon"), fill_value=1e20)
            v.units = units
            v[:] = values.astype("f4")
    return path


# --- reading ---------------------------------------------------------------------------


def _raw(values, dtype="f4", **attrs):
    return xr.DataArray(np.array(values, dtype=dtype), dims="x", attrs=attrs)


def test_decode_missing_value_before_fill_value():
    """ncdf4 uses missing_value when both attributes are present."""
    x = decode_ncdf4(_raw([1.0, -999.0, 1e20], missing_value=-999.0, _FillValue=1e20))
    assert np.isnan(x.values[1]) and x.values[2] == np.float32(1e20)


def test_decode_tolerance_and_default():
    """Floats within 1e-5 relative of the missing value are missing; without an
    attribute the missing value is 1e30, not the netCDF default fill value."""
    x = decode_ncdf4(_raw([1.0, -99.9, -99.9005, -99.8], _FillValue=-99.9))
    assert np.isnan(x.values).tolist() == [False, True, True, False]
    y = decode_ncdf4(_raw([1.0, 1e30, 9.969209968386869e36]))
    assert np.isnan(y.values).tolist() == [False, True, False]
    z = decode_ncdf4(_raw([0.0, 1e-11, 1e-9], _FillValue=0.0))
    assert np.isnan(z.values).tolist() == [True, True, False]


def test_decode_packed_integers():
    x = decode_ncdf4(
        _raw([10, -32767, 20], dtype="i2", _FillValue=-32767, scale_factor=0.1, add_offset=273.15)
    )
    assert x.dtype == np.float64
    assert x.values[0] == 10 * 0.1 + 273.15 and np.isnan(x.values[1])
    assert decode_ncdf4(_raw([5, -1], dtype="i4")).values.tolist() == [5.0, -1.0]


def test_unit_conversion():
    assert unit_conversion("tasmax", "K") == (1.0, -273.15)
    assert unit_conversion("tasmin", "degrees_C") == (1.0, 0.0)
    assert unit_conversion("tasmin", "degC") == (1.0, 0.0)
    assert unit_conversion("pr", "kg m-2 s-1") == (86400.0, 0.0)
    assert unit_conversion("pr", "kg m-2 d-1") == (1.0, 0.0)
    assert unit_conversion("pr", "mm/day") == (1.0, 0.0)
    for var, units in (("tasmax", "degF"), ("pr", "m s-1"), ("pr", None)):
        with pytest.raises(ValueError):
            unit_conversion(var, units)


def test_open_grid_converts_like_udunits(tmp_path):
    path = write_grid(tmp_path / "g.nc")
    inp = open_grid([path])
    with netCDF4.Dataset(path) as nc:
        tx = nc["tasmax"][:].astype(float)
        pr = nc["pr"][:].astype(float)
    assert np.array_equal(inp.data.tasmax.values, tx - 273.15)
    assert np.array_equal(inp.data.pr.values, pr * 86400)
    assert inp.data.tasmax.dtype == np.float64
    assert (inp.time_dim, inp.y_dim, inp.x_dim) == ("time", "lat", "lon")
    lat = inp.cell_latitude()
    assert lat.dims == ("lat", "lon") and lat.values[:, 0].tolist() == [-30.0, 30.0]


def test_open_grid_variables_across_files(tmp_path):
    a = write_grid(tmp_path / "a.nc", names=("tx", "tn", "rain"))
    inp = open_grid([a], {"tasmax": "tx", "tasmin": "tn", "pr": "rain"})
    assert inp.names == {"tasmax": "tx", "tasmin": "tn", "pr": "rain"}
    with pytest.raises(ValueError, match="not found"):
        open_grid([a])
    b = write_grid(tmp_path / "b.nc", names=("tx", "x2", "x3"))
    with pytest.raises(ValueError, match="more than one input file"):
        open_grid([a, b], {"tasmax": "tx", "tasmin": "tn", "pr": "rain"})
    c = write_grid(tmp_path / "c.nc", names=("y1", "y2", "rain2"), end="1979-12-31")
    with pytest.raises(ValueError, match="same time axis"):
        open_grid([a, c], {"tasmax": "tx", "tasmin": "tn", "pr": "rain2"})


def test_open_grid_refuses_other_calendars(tmp_path):
    path = write_grid(tmp_path / "g.nc", calendar="360_day", end="1972-12-30")
    with pytest.raises(NotImplementedError, match="calendar"):
        open_grid([path])


def test_blocks_are_bounded_by_max_values(tmp_path):
    """Blocks are whole rows, or parts of a row, with at most max_values values."""
    path = write_grid(tmp_path / "g.nc", ny=5, nx=4)
    ntime = 3653 * 3
    inp = open_grid([path], max_values=8 * ntime)
    assert inp.data.tasmax.chunks == ((3653,), (2, 2, 1), (4,))
    assert list(inp.blocks())[-1] == (slice(4, 5), slice(0, 4))
    inp = open_grid([path], max_values=3 * ntime)
    assert inp.data.tasmax.chunks[1:] == ((1,) * 5, (3, 1))
    assert len(list(inp.blocks())) == 10


# --- thresholds ------------------------------------------------------------------------


def test_cell_thresholds_match_station_thresholds(tmp_path):
    """Each cell's thresholds are the station thresholds of its series."""
    inp = open_grid([write_grid(tmp_path / "g.nc")])
    data = inp.load((slice(0, 2), slice(0, 3)))
    out = cell_thresholds(data["tasmax"], data["tasmin"], data["pr"], inp.time, 1972, 1979)
    for i in range(2):
        for j in range(3):
            ds = xr.Dataset(
                {v: ("time", data[v][i, j]) for v in ("tasmax", "tasmin", "pr")},
                coords={"time": inp.time},
            )
            ds["tas"] = (ds.tasmax + ds.tasmin) / 2
            t = compute_thresholds(ds, 1972, 1979)
            assert np.array_equal(out["tx90thresh"][i, j], t.temperature["tasmax"][0.9])
            assert np.array_equal(out["tn05thresh"][i, j], t.temperature["tasmin"][0.05])
            assert np.array_equal(out["tavg90thresh_15days"][i, j], t.heatwave["tas"])
            assert out["r95thresh"][i, j] == t.precipitation[0.95]
    assert set(out) == {v.name for v in THRESHOLD_VARIABLES}
    assert out["txraw"].shape == (2, 3, 8 * 365 + 2)  # 29 February kept


def test_insufficient_base_period(tmp_path):
    inp = open_grid([write_grid(tmp_path / "g.nc", end="1971-12-25")])
    with pytest.raises(InsufficientBaseData):
        write_grid_thresholds(inp, tmp_path / "t.nc", 1971, 2000)
    assert not (tmp_path / "t.nc").exists()


def test_results_do_not_depend_on_blocks_batches_or_threads(tmp_path):
    path = write_grid(tmp_path / "g.nc", ny=3, nx=5)
    a = write_grid_thresholds(open_grid([path]), tmp_path / "a.nc", 1972, 1979)
    b = write_grid_thresholds(
        open_grid([path], max_values=2 * 3 * 3653),
        tmp_path / "b.nc",
        1972,
        1979,
        workers=3,
        cells_per_batch=1,
    )
    with netCDF4.Dataset(a) as x, netCDF4.Dataset(b) as y:
        for v in THRESHOLD_VARIABLES:
            assert np.ma.allequal(x[v.name][:], y[v.name][:])
            assert np.array_equal(
                np.ma.getmaskarray(x[v.name][:]), np.ma.getmaskarray(y[v.name][:])
            )


def _traced_peak(path, tmp_path, max_values):
    inp = open_grid([path], max_values=max_values)
    tracemalloc.start()
    try:
        write_grid_thresholds(inp, tmp_path / "t.nc", 1972, 1979, cells_per_batch=4)
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def test_memory_is_bounded_by_the_block_not_the_grid(tmp_path):
    """The memory a run allocates depends on the block size, not on the grid size.

    numpy's allocations are traced (tracemalloc); the HDF5 caches outside Python are
    bounded separately (OUTPUT_CHUNK_CACHE per output variable).
    """
    ntime = 3653
    max_values = 16 * 3 * ntime  # 16 cells per block
    small = write_grid(tmp_path / "small.nc", ny=4, nx=4)  # one block
    large = write_grid(tmp_path / "large.nc", ny=16, nx=16, seed=1)  # 16 blocks
    peak_small = _traced_peak(small, tmp_path, max_values)
    peak_large = _traced_peak(large, tmp_path, max_values)
    whole_grid = 256 * 3 * ntime * 8  # the large grid's input as float64
    assert peak_large < 1.5 * peak_small
    assert peak_large < whole_grid


# --- command line ------------------------------------------------------------------------


def test_command_line(tmp_path, capsys):
    path = write_grid(tmp_path / "g.nc")
    out = tmp_path / "thresholds.nc"
    args = ["gridded-thresholds", str(path), "--out", str(out), "--base-start", "1972"]
    assert main([*args, "--base-end", "1979", "--institution", "Uni", "--workers", "2"]) == 0
    assert "Wrote" in capsys.readouterr().out
    with netCDF4.Dataset(out) as nc:
        assert nc.base_period == "1972-1979"
        assert nc.author_institution == "Uni"
        assert nc["tx90thresh"].dimensions == ("time", "lat", "lon")
        assert nc.dimensions["base_time"].isunlimited()
    with pytest.raises(SystemExit):
        main(["gridded-thresholds", str(path), "--out", str(out), "--tmax", "nope"])
    assert "not found" in capsys.readouterr().err
