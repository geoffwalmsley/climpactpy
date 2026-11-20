"""A gridded variable split along time across several files (#291): joined in the order of
their first day, with the same results as the whole file, and clear errors naming the
files when they do not fit together."""

from __future__ import annotations

from pathlib import Path

import netCDF4
import numpy as np
import pytest

from climpact.cli import main
from climpact.gridded import io, open_grid, write_grid_indices, write_grid_thresholds
from climpact.gridded.thresholds import THRESHOLD_VARIABLES

from .test_gridded import write_grid
from .test_gridded_rechunk import _values_per_block, write_mixed_grid

SAMPLE = Path(__file__).parents[3] / "reference" / "gridded" / "input" / "grid_sample.nc"
SAMPLE_NAMES = {"tasmax": "tmax", "tasmin": "tmin", "pr": "precip"}


def split_file(src: Path, out_dir: Path, pieces=None, stem=None, time_units=None) -> list[Path]:
    """Copy ``src`` to one file per year (or per ``pieces``, a list of ``(first, last)``
    years), with the raw values, types, attributes and chunking of every variable. The
    files after the first may have other ``time_units``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = stem or src.stem
    paths = []
    with netCDF4.Dataset(src) as nc:
        tvar = nc["time"]
        dates = netCDF4.num2date(tvar[:], tvar.units, getattr(tvar, "calendar", "standard"))
        years = np.array([d.year for d in dates])
        if pieces is None:
            pieces = [(y, y) for y in np.unique(years)]
        for n, (first, last) in enumerate(pieces):
            index = np.flatnonzero((years >= first) & (years <= last))
            path = out_dir / f"{stem}_{first}-{last}.nc"
            with netCDF4.Dataset(path, "w") as out:
                out.setncatts({k: nc.getncattr(k) for k in nc.ncattrs()})
                for name, dim in nc.dimensions.items():
                    out.createDimension(name, None if dim.isunlimited() else len(dim))
                for name, var in nc.variables.items():
                    var.set_auto_maskandscale(False)
                    fill = var.getncattr("_FillValue") if "_FillValue" in var.ncattrs() else None
                    chunking = var.chunking()
                    chunks = None
                    if isinstance(chunking, list):
                        chunks = [
                            min(c, index.size) if d == "time" else c
                            for d, c in zip(var.dimensions, chunking, strict=True)
                        ]
                    v = out.createVariable(
                        name, var.dtype, var.dimensions, fill_value=fill, chunksizes=chunks
                    )
                    v.set_auto_maskandscale(False)
                    v.setncatts({k: var.getncattr(k) for k in var.ncattrs() if k != "_FillValue"})
                    if "time" in var.dimensions:
                        axis = var.dimensions.index("time")
                        v[:] = np.take(var[:], index, axis=axis)
                    else:
                        v[:] = var[:]
                if time_units and n > 0:
                    # The time and its bounds, in the other units.
                    calendar = getattr(tvar, "calendar", "standard")
                    for name in ("time", getattr(tvar, "bounds", None)):
                        if name in out.variables:
                            values = np.take(nc[name][:], index, axis=0)
                            dates_ = netCDF4.num2date(values, tvar.units, calendar)
                            out[name][:] = netCDF4.date2num(dates_, time_units, calendar)
                            if "units" in out[name].ncattrs():
                                out[name].units = time_units
            paths.append(path)
    return paths


def _whole_and_split(tmp_path, **grid):
    whole = write_grid(tmp_path / "g.nc", **grid)
    return whole, split_file(whole, tmp_path / "split", stem="g")


# --- reading ---------------------------------------------------------------------------


def test_split_files_read_as_the_whole_file(tmp_path):
    whole, split = _whole_and_split(tmp_path, ny=2, nx=3, end="1974-12-31")
    assert len(split) == 4
    # In any order: joined by their first day; other time units after the first file.
    shuffled = split_file(whole, tmp_path / "other", stem="g", time_units="hours since 1900-01-01")[
        ::-1
    ]
    a = open_grid([whole])
    for files in (split, shuffled):
        b = open_grid(files)
        assert b.time.equals(a.time)
        for v in io.VARIABLES:
            np.testing.assert_array_equal(a.data[v].values, b.data[v].values)
        assert [p.path.name for p in b.parts_of("pr")] == [p.name for p in sorted(files)]
        assert [(p.start, p.stop) for p in b.parts_of("pr")] == [
            (0, 365),
            (365, 731),
            (731, 1096),
            (1096, 1461),
        ]
        assert b.files["tasmax"] == b.parts_of("tasmax")[0].path == min(files)
        assert b.data.tasmax.chunks[0] == (1461,)
    assert a.parts_of("tasmax") == (io.FilePart(whole, 0, 1461),)


def test_each_file_is_decoded_with_its_own_attributes(tmp_path):
    """Packed files often have a scale factor and missing value of their own."""
    whole, split = _whole_and_split(tmp_path, ny=2, nx=2, end="1972-12-31")
    with netCDF4.Dataset(split[1], "a") as nc:
        tx = nc["tasmax"]
        tx.set_auto_maskandscale(False)
        values = tx[:]
        nc.renameVariable("tasmax", "old")
        new = nc.createVariable("tasmax", "i2", tx.dimensions)
        new.set_auto_maskandscale(False)
        new.units = "K"
        new.scale_factor = 0.01
        new.add_offset = 290.0
        new.missing_value = np.int16(-32767)
        packed = np.round((values.astype(float) - 290.0) / 0.01).astype("i2")
        packed[0, 0, 0] = -32767
        new[:] = packed
    inp = open_grid(split)
    tx = inp.data.tasmax.values
    expected = packed.astype(float) * 0.01 + 290.0 - 273.15
    expected[0, 0, 0] = np.nan
    np.testing.assert_array_equal(tx[365:], expected)
    with netCDF4.Dataset(whole) as nc:
        np.testing.assert_array_equal(tx[:365], nc["tasmax"][:365].astype(float) - 273.15)
    # The cell-first copy decodes each slab with its file's attributes too.
    direct = _values_per_block(open_grid(split, rechunk=False), False)
    copied = _values_per_block(open_grid(split, rechunk=True, tmp_dir=tmp_path), True)
    for block in direct:
        for v in io.VARIABLES:
            np.testing.assert_array_equal(direct[block][v], copied[block][v])


def test_a_file_may_hold_several_variables(tmp_path):
    """TX and TN split by year in files of their own; pr in one file."""
    tas, pr = write_mixed_grid(tmp_path)
    parts = split_file(tas, tmp_path / "tas", pieces=[(1971, 1975), (1976, 1980)])
    inp = open_grid([pr, *parts])
    whole = open_grid([tas, pr])
    for v in io.VARIABLES:
        np.testing.assert_array_equal(inp.data[v].values, whole.data[v].values)
    assert [p.path for p in inp.parts_of("tasmin")] == parts
    assert inp.parts_of("pr") == (io.FilePart(pr, 0, 3653),)
    assert inp.rechunk_bytes() == whole.rechunk_bytes()
    assert inp.read_amplification() == whole.read_amplification()


def test_time_slabs_stop_at_the_files(tmp_path):
    tas, pr = write_mixed_grid(tmp_path)
    parts = split_file(tas, tmp_path / "tas", pieces=[(1971, 1975), (1976, 1980)])
    inp = open_grid([pr, *parts], max_values=3 * 3 * 3653, rechunk=True, tmp_dir=tmp_path)
    slabs = io._time_slabs(inp)
    # 938-day slabs (as for the whole file), cut where the second file starts (1826).
    assert slabs == [(0, 938), (938, 1826), (1826, 2764), (2764, 3653)]
    whole = open_grid([tas, pr], max_values=3 * 3 * 3653, rechunk=False)
    direct = _values_per_block(whole, False)
    copied = _values_per_block(inp, True)
    for block in direct:
        for v in io.VARIABLES:
            np.testing.assert_array_equal(direct[block][v], copied[block][v])


# --- what does not fit -----------------------------------------------------------------


def test_files_that_do_not_fit_together(tmp_path):
    whole = write_grid(tmp_path / "g.nc", ny=2, nx=2, end="1973-12-31")
    a, b, c = split_file(whole, tmp_path / "s", stem="g")

    with pytest.raises(
        ValueError,
        match=r"tasmax: a gap between g_1971-1971\.nc, which ends on "
        r"1971-12-31, and g_1973-1973\.nc, which starts on 1973-01-01",
    ):
        open_grid([a, c])
    whole2 = write_grid(tmp_path / "h.nc", ny=2, nx=2, start="1972-07-01", end="1974-12-31")
    with pytest.raises(
        ValueError,
        match=r"g_1972-1972\.nc and h\.nc overlap: both have the "
        r"days from 1972-07-01 to 1972-12-31",
    ):
        open_grid([a, b, whole2])

    other_grid = write_grid(tmp_path / "x.nc", ny=3, nx=2, start="1972-01-01", end="1972-12-31")
    with pytest.raises(ValueError, match=r"x\.nc does not have the grid of g_1971-1971\.nc"):
        open_grid([a, other_grid])
    moved = write_grid(tmp_path / "m.nc", ny=2, nx=2, start="1972-01-01", end="1972-12-31")
    with netCDF4.Dataset(moved, "a") as nc:
        nc["lon"][:] = nc["lon"][:] + 0.5
    with pytest.raises(ValueError, match=r"m\.nc does not have the grid of g_1971-1971\.nc"):
        open_grid([a, moved])

    noleap = write_grid(
        tmp_path / "n.nc", ny=2, nx=2, start="1972-01-01", end="1972-12-31", calendar="noleap"
    )
    with pytest.raises(
        ValueError,
        match=r"g_1971-1971\.nc is in the standard calendar and "
        r"n\.nc in the noleap calendar",
    ):
        open_grid([a, noleap])

    celsius = tmp_path / "s" / "c.nc"
    celsius.write_bytes(b.read_bytes())
    with netCDF4.Dataset(celsius, "a") as nc:
        nc["tasmax"].units = "degrees_C"
    with pytest.raises(
        ValueError,
        match=r"tasmax: g_1971-1971\.nc is in 'K' and c\.nc in "
        r"'degrees_C'",
    ):
        open_grid([a, celsius])


def test_files_of_the_same_name_are_named_by_path(tmp_path):
    whole = write_grid(tmp_path / "g.nc", ny=1, nx=2, end="1972-12-31")
    a = split_file(whole, tmp_path / "one", pieces=[(1971, 1972)], stem="g")[0]
    b = split_file(whole, tmp_path / "two", pieces=[(1972, 1972)], stem="g")[0]
    b = b.rename(b.with_name(a.name))
    with pytest.raises(ValueError, match=f"{a} and {b} overlap"):
        open_grid([a, b])


def test_the_variables_must_share_the_joined_time_axis(tmp_path):
    tas, pr = write_mixed_grid(tmp_path)
    parts = split_file(tas, tmp_path / "tas", pieces=[(1971, 1975), (1976, 1979)])
    with pytest.raises(ValueError, match="same time axis"):
        open_grid([pr, *parts])


# --- the sample grid, split by year ----------------------------------------------------


def _all_values(directory: Path) -> dict:
    out = {}
    for path in sorted(directory.glob("*.nc")):
        with netCDF4.Dataset(path) as nc:
            for v in nc.variables:
                out[path.name, v] = nc[v][:]
    return out


def test_sample_grid_split_by_year_gives_the_same_files(tmp_path):
    """Every index file, and the thresholds file, of Climpact's sample grid (3 x 4 cells,
    1991-2010) split into 20 yearly files, read through the cell-first copy, has the same
    values as from the whole file."""
    split = split_file(SAMPLE, tmp_path / "input", time_units="days since 1991-01-01")
    assert len(split) == 20
    whole = open_grid([SAMPLE], SAMPLE_NAMES, max_values=4 * 3 * 7305)
    parts = open_grid(split, SAMPLE_NAMES, max_values=4 * 3 * 7305, rechunk=True)
    assert len(parts.parts_of("pr")) == 20
    thresholds = {}
    for key, inp in (("whole", whole), ("split", parts)):
        thresholds[key] = write_grid_thresholds(inp, tmp_path / f"t_{key}.nc", 1991, 2010)
        write_grid_indices(inp, tmp_path / key, 1991, 2010, workers=2)
    a, b = _all_values(tmp_path / "whole"), _all_values(tmp_path / "split")
    assert a.keys() == b.keys() and len(a) > 300
    for key in a:
        assert np.array_equal(np.ma.getmaskarray(a[key]), np.ma.getmaskarray(b[key])), key
        assert np.ma.allequal(a[key], b[key]), key
    with netCDF4.Dataset(thresholds["whole"]) as x, netCDF4.Dataset(thresholds["split"]) as y:
        for v in THRESHOLD_VARIABLES:
            np.testing.assert_array_equal(x[v.name][:].filled(np.nan), y[v.name][:].filled(np.nan))


# --- the command line ------------------------------------------------------------------


def test_command_line_takes_several_files_or_a_pattern(tmp_path, capsys):
    whole, split = _whole_and_split(tmp_path, ny=1, nx=2, end="1976-12-31")
    common = ["--base-start", "1972", "--base-end", "1975", "--indices", "fd", "txx", "--quiet"]
    assert main(["gridded-indices", str(whole), "--out", str(tmp_path / "a"), *common]) == 0
    pattern = str(tmp_path / "split" / "g_19*.nc")
    assert main(["gridded-indices", pattern, "--out", str(tmp_path / "b"), *common]) == 0
    files = [str(p) for p in split]
    assert main(["gridded-indices", *files, "--out", str(tmp_path / "c"), *common]) == 0
    a = _all_values(tmp_path / "a")
    for other in ("b", "c"):
        b = _all_values(tmp_path / other)
        assert a.keys() == b.keys() and len(a) > 0
        for key in a:
            assert np.ma.allequal(a[key], b[key]), key
    t = tmp_path / "t.nc"
    assert main(["gridded-thresholds", pattern, "--out", str(t), *common[:4], "--quiet"]) == 0
    assert t.is_file()
    with pytest.raises(SystemExit):
        main(["gridded-indices", str(tmp_path / "nothing_*.nc"), "--out", str(tmp_path / "d")])
    assert "no file matches" in capsys.readouterr().err
