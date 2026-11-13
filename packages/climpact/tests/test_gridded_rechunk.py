"""Rechunking gridded inputs chunked by time step (GriddedInput.block_reader, #67)."""

from __future__ import annotations

import os
import tracemalloc
from pathlib import Path

import netCDF4
import numpy as np
import pandas as pd
import pytest

from climpact.cli import main
from climpact.gridded import io, open_grid, write_grid_indices, write_grid_thresholds
from climpact.gridded.thresholds import THRESHOLD_VARIABLES

from .test_gridded import write_grid


def write_mixed_grid(tmp_path, ny=5, nx=7, time_chunk=7):
    """TX float32 in K with a fill value, TN packed int16 in degrees C with a
    missing_value, both chunked by ``time_chunk`` time steps over the whole grid; pr
    float64 in kg m-2 s-1 in a second file, stored (time, lon, lat), chunked by time step.
    """
    dates = pd.date_range("1971-01-01", "1980-12-31", freq="D")
    rng = np.random.default_rng(3)
    shape = (dates.size, ny, nx)

    def axes(nc, order):
        nc.createDimension("time", None)
        nc.createDimension("lat", ny)
        nc.createDimension("lon", nx)
        t = nc.createVariable("time", "f8", ("time",))
        t.units = "days since 1950-01-01"
        t.calendar = "standard"
        t[:] = netCDF4.date2num(dates.to_pydatetime(), t.units, "standard")
        nc.createVariable("lat", "f8", ("lat",))[:] = np.linspace(-40, 40, ny)
        nc["lat"].units = "degrees_north"
        nc.createVariable("lon", "f8", ("lon",))[:] = np.linspace(0, 90, nx)
        nc["lon"].units = "degrees_east"

    tas = tmp_path / "tas.nc"
    with netCDF4.Dataset(tas, "w") as nc:
        axes(nc, None)
        dims = ("time", "lat", "lon")
        tx = nc.createVariable(
            "tasmax", "f4", dims, fill_value=1e20, chunksizes=(time_chunk, ny, nx), zlib=True
        )
        tx.units = "K"
        values = 295 + rng.normal(0, 4, shape)
        values[rng.random(shape) < 0.02] = 1e20
        tx.set_auto_maskandscale(False)
        tx[:] = values.astype("f4")
        tn = nc.createVariable("tasmin", "i2", dims, chunksizes=(time_chunk, ny, nx))
        tn.units = "degrees_C"
        tn.missing_value = np.int16(-32767)
        tn.scale_factor = 0.01
        tn.add_offset = 5.0
        packed = np.round((12 + rng.normal(0, 4, shape) - 5.0) / 0.01).astype("i2")
        packed[rng.random(shape) < 0.02] = -32767
        tn.set_auto_maskandscale(False)
        tn[:] = packed
    pr = tmp_path / "pr.nc"
    with netCDF4.Dataset(pr, "w") as nc:
        axes(nc, None)
        p = nc.createVariable("pr", "f8", ("time", "lon", "lat"), chunksizes=(1, nx, ny))
        p.units = "kg m-2 s-1"
        p[:] = np.maximum(rng.gamma(0.5, 6, (dates.size, nx, ny)) - 1, 0) / 86400
    return [tas, pr]


def _values_per_block(inp, rechunked):
    out = {}
    with inp.block_reader() as reader:
        assert reader.rechunked is rechunked
        for block in inp.blocks():
            out[io._block_key(block)] = reader.load(block)
    return out


def test_read_amplification(tmp_path):
    by_step = write_grid(tmp_path / "steps.nc", ny=8, nx=8)  # chunks (1, 8, 8)
    inp = open_grid([by_step], max_values=8 * 3 * 3653)  # one row per block
    assert len(list(inp.blocks())) == 8
    assert inp.read_amplification() == 8
    assert inp.will_rechunk()
    one_block = open_grid([by_step])
    assert one_block.read_amplification() == 1
    assert not one_block.will_rechunk()
    by_cell = tmp_path / "cells.nc"
    with netCDF4.Dataset(by_step) as src, netCDF4.Dataset(by_cell, "w") as dst:
        for name, dim in src.dimensions.items():
            dst.createDimension(name, None if dim.isunlimited() else len(dim))
        for name, var in src.variables.items():
            chunks = (3653, 1, 1) if var.ndim == 3 else None
            fill = var.getncattr("_FillValue") if "_FillValue" in var.ncattrs() else None
            v = dst.createVariable(
                name, var.dtype, var.dimensions, fill_value=fill, chunksizes=chunks
            )
            v.setncatts({k: var.getncattr(k) for k in var.ncattrs() if k != "_FillValue"})
            v[:] = var[:]
    inp = open_grid([by_cell], max_values=8 * 3 * 3653)
    assert inp.read_amplification() == 1
    assert not inp.will_rechunk()


def test_rechunked_blocks_are_identical(tmp_path):
    files = write_mixed_grid(tmp_path)
    # Blocks of 3 cells (parts of rows); slabs of 938 days (134 time chunks of 7 days,
    # within max_values / 35 cells; not a divisor of the 3653 days).
    max_values = 3 * 3 * 3653
    direct = open_grid(files, max_values=max_values, rechunk=False)
    inp = open_grid(files, max_values=max_values, rechunk=True, tmp_dir=tmp_path)
    assert io._time_slabs(inp) == [(0, 938), (938, 1876), (1876, 2814), (2814, 3653)]
    a = _values_per_block(direct, False)
    b = _values_per_block(inp, True)
    assert a.keys() == b.keys() and len(a) == 15
    for block in a:
        for v in io.VARIABLES:
            assert a[block][v].dtype == b[block][v].dtype == np.float64
            np.testing.assert_array_equal(a[block][v], b[block][v])
    assert np.isnan(a[(0, 1, 0, 3)]["tasmin"]).any()


def test_progress_and_temporary_file(tmp_path, monkeypatch):
    files = write_mixed_grid(tmp_path)
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    made = []
    mkstemp = io.tempfile.mkstemp

    def recording_mkstemp(*args, **kwargs):
        made.append(mkstemp(*args, **kwargs))
        return made[-1]

    monkeypatch.setattr(io.tempfile, "mkstemp", recording_mkstemp)
    inp = open_grid(files, max_values=3 * 3 * 3653, rechunk=True, tmp_dir=tmp)
    calls = []
    blocks = list(inp.blocks())
    with inp.block_reader(lambda *c: calls.append(c), len(blocks)) as reader:
        assert len(made) == 1 and Path(made[0][1]).parent == tmp
        # Already removed from the directory (POSIX): freed even if the process is killed.
        assert not list(tmp.iterdir()) or os.name == "nt"
        for block in blocks:
            reader.load(block)
            reader.steps.done("indices")
    assert not list(tmp.iterdir())
    slabs = len(io._time_slabs(inp))
    total = slabs + len(blocks)
    assert calls == [("rechunk", i, total) for i in range(1, slabs + 1)] + [
        ("indices", i, total) for i in range(slabs + 1, total + 1)
    ]
    with pytest.raises(RuntimeError), inp.block_reader():
        raise RuntimeError("stop")
    assert not list(tmp.iterdir())


def test_not_rechunked_without_room(tmp_path, monkeypatch):
    files = write_mixed_grid(tmp_path)
    inp = open_grid(files, max_values=3 * 3 * 3653, tmp_dir=tmp_path)
    assert inp.will_rechunk()
    monkeypatch.setattr(io, "_free_bytes", lambda d: inp.rechunk_bytes())
    with pytest.warns(RuntimeWarning, match="not rechunking"):
        assert not inp.will_rechunk()
    forced = open_grid(files, max_values=3 * 3 * 3653, rechunk=True, tmp_dir=tmp_path)
    monkeypatch.setattr(io, "_free_bytes", lambda d: 0)
    with pytest.raises(OSError, match="GB free"), forced.block_reader():
        pass


def test_outputs_are_identical(tmp_path):
    path = write_grid(tmp_path / "g.nc", ny=3, nx=5)
    max_values = 2 * 3 * 3653
    files = {}
    for rechunk in (False, True):
        inp = open_grid([path], max_values=max_values, rechunk=rechunk)
        events: list[tuple] = []
        record = events.append
        files[rechunk] = (
            write_grid_thresholds(inp, tmp_path / f"t{rechunk}.nc", 1972, 1979),
            write_grid_indices(
                inp,
                tmp_path / f"i{rechunk}",
                1972,
                1979,
                indices=["txx", "r95p", "tx90p"],
                progress=lambda *e, record=record: record(e),
            ),
        )
        slabs = len(io._time_slabs(inp)) if rechunk else 0
        blocks = len(list(inp.blocks()))
        total = slabs + blocks
        assert events == [("rechunk", i, total) for i in range(1, slabs + 1)] + [
            ("indices", i, total) for i in range(slabs + 1, total + 1)
        ]
    with netCDF4.Dataset(files[False][0]) as x, netCDF4.Dataset(files[True][0]) as y:
        for v in THRESHOLD_VARIABLES:
            np.testing.assert_array_equal(x[v.name][:].filled(np.nan), y[v.name][:].filled(np.nan))
    assert len(files[False][1]) == 5
    for a, b in zip(files[False][1], files[True][1], strict=True):
        with netCDF4.Dataset(a) as x, netCDF4.Dataset(b) as y:
            for name in x.variables:
                np.testing.assert_array_equal(x[name][:], y[name][:])


def _traced_load_peak(path, max_values):
    inp = open_grid([path], max_values=max_values, rechunk=True)
    tracemalloc.start()
    try:
        with inp.block_reader() as reader:
            for block in inp.blocks():
                reader.load(block)
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def test_rechunking_memory_is_bounded(tmp_path):
    """Rechunking reads slabs of at most max_values values, so its memory, like the
    blocks', does not grow with the grid."""
    max_values = 16 * 3 * 3653  # 16 cells per block, slabs of 1 to 3 time steps
    small = write_grid(tmp_path / "small.nc", ny=8, nx=8)
    large = write_grid(tmp_path / "large.nc", ny=16, nx=16, seed=1)
    peak_small = _traced_load_peak(small, max_values)
    peak_large = _traced_load_peak(large, max_values)
    assert peak_large < 1.5 * peak_small
    assert peak_large < 256 * 3 * 3653 * 4  # the large grid's raw input


def test_command_line_rechunk(tmp_path, capsys):
    path = write_grid(tmp_path / "g.nc", ny=2, nx=3)
    out = tmp_path / "thresholds.nc"
    args = ["gridded-thresholds", str(path), "--out", str(out), "--base-start", "1972"]
    args += ["--base-end", "1979", "--max-values", "0.03", "--tmp-dir", str(tmp_path)]
    assert main([*args, "--rechunk", "yes"]) == 0
    text = capsys.readouterr().out
    assert "time slabs rechunked" in text and "blocks done" in text
    assert main([*args, "--rechunk", "no"]) == 0
    assert "rechunked" not in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main([*args[:-2], "--tmp-dir", str(tmp_path / "missing")])
    assert "not a directory" in capsys.readouterr().err
