"""Gridded trends (trends.nc, #290): each cell's slope and interval are the station
trend's (climpact.trends.sen_trend) on that cell's values, missing cells stay missing,
the base-period and grid means, and the command line. R writes no gridded trends, so
there is no parity reference."""

from __future__ import annotations

from types import SimpleNamespace

import netCDF4
import numpy as np
import pytest

from climpact.cli import main
from climpact.gridded import open_grid, write_grid_indices
from climpact.gridded.trends import (
    MAX_VECTOR_YEARS,
    TRENDS_FILE,
    _mean_of_two,
    annual_series,
    base_means,
    cell_weights,
    grid_means,
    sen_trends,
    write_grid_trends,
)
from climpact.rnumerics import r_mean
from climpact.trends import sen_trend

from .test_gridded import write_grid


def _same(a, b) -> bool:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    return a.shape == b.shape and bool(((a == b) | (np.isnan(a) & np.isnan(b))).all())


def _station(values) -> np.ndarray:
    return np.array([sen_trend(row) for row in values]).reshape(-1, 3)


def _series(seed=0, cells=1200, n=60) -> np.ndarray:
    """Series with what changes the trend's arithmetic: ties (in float32 too), heavy
    ties, constant series, missing values (some too many for a trend), infinite values,
    and values of very different sizes."""
    rng = np.random.default_rng(seed)
    y = rng.normal(20, 5, (cells, n))
    y[:300] = np.round(y[:300])
    y[300:450] = rng.integers(0, 3, (150, n))
    y[450:480] = 3.0
    y[480:500] = 1 + rng.integers(0, 2, (20, n)) * 1e-9  # ties only in float32
    y[500:520, 5] = np.inf
    y[520:540, 7] = -np.inf
    y[540:560] = rng.normal(0, 1e-8, (20, n))
    y[540:560, ::2] *= 1e9
    missing = rng.random((cells, n)) < rng.random((cells, 1)) * 0.5
    y[missing] = np.nan
    y[560:570] = np.nan
    y[570:580, : n // 2] = np.nan  # too few values
    return y


@pytest.mark.parametrize("float32", [False, True])
def test_each_series_is_the_station_trend(float32):
    y = _series()
    if float32:  # the values as read from an index file
        y = y.astype(np.float32).astype(float)
    lower, slope, upper = sen_trends(y, cells_per_chunk=97)
    ref = _station(y)
    assert _same(lower, ref[:, 0]) and _same(slope, ref[:, 1]) and _same(upper, ref[:, 2])
    assert np.isfinite(slope).sum() > 600 and np.isnan(slope[560:580]).all()


def test_short_long_and_offset_series():
    rng = np.random.default_rng(3)
    for n in (9, 10, 11, 14, MAX_VECTOR_YEARS + 1):
        y = np.round(rng.normal(0, 2, (8, n)), 1)
        y[0, :3] = np.nan
        ref = np.array([sen_trend(row, 5) for row in y])
        assert _same(np.stack(sen_trends(y, x0=5), axis=1), ref), n
    assert all(v.size == 0 for v in sen_trends(np.empty((0, 12))))


def test_threads_do_not_change_the_result():
    from concurrent.futures import ThreadPoolExecutor

    y = _series(seed=5)
    with ThreadPoolExecutor(3) as pool:
        threaded = sen_trends(y, pool=pool, cells_per_chunk=33)
    assert all(_same(a, b) for a, b in zip(threaded, sen_trends(y), strict=True))


def test_mean_of_two_is_r_mean():
    rng = np.random.default_rng(1)
    a = rng.normal(0, 1, 4000) * 10.0 ** rng.integers(-30, 30, 4000)
    b = rng.normal(0, 1, 4000) * 10.0 ** rng.integers(-30, 30, 4000)
    a[:20], b[20:40] = 0.0, 0.0
    b[40:60] = -a[40:60]
    b[60:80] = np.nextafter(a[60:80], np.inf)
    expected = [r_mean(np.array([x, y])) for x, y in zip(a, b, strict=True)]
    assert _same(_mean_of_two(a, b), expected)


def test_base_and_grid_means():
    y = np.array([[1.0, 2.0, np.nan, 4.0], [np.nan, np.nan, 5.0, 7.0], [1.0, np.inf, 3, 4]])
    years = [1990, 1991, 1992, 1993]
    assert _same(base_means(y, years, 1990, 1992), [1.5, 5.0, 2.0])
    assert _same(base_means(y, years, 1980, 1985), [np.nan] * 3)
    weights = cell_weights(np.array([0.0, 60.0, 90.0]))
    assert np.allclose(weights, [1.0, 0.5, 0.0])
    means = grid_means(y.T, np.array([1.0, 0.5, 0.25]))
    assert _same(means, [(1 + 0.25) / 1.25, 2.0, (2.5 + 0.75) / 0.75, (4 + 3.5 + 1) / 1.75])
    assert _same(grid_means(np.full((2, 3), np.nan), np.ones(3)), [np.nan, np.nan])


# --- trends.nc ----------------------------------------------------------------------------


def _index_file(path, name, values, freq="yr", variables=None, lat=(-40.0, 0.0, 60.0)):
    """A file laid out as the gridded index files: ``values`` ``(time, y, x)`` (or a
    dict of them for several variables), annual from 1961, or monthly with three scales
    (``(scale, time, y, x)``) for four-dimensional values."""
    variables = variables or {name: values}
    first = next(iter(variables.values()))
    nt, ny, nx = first.shape[-3:]
    with netCDF4.Dataset(path, "w") as nc:
        nc.createDimension("bnds", 2)
        nc.createDimension("time", None)
        nc.createDimension("lon", nx)
        nc.createDimension("lat", ny)
        t = nc.createVariable("time", "f8", ("time",))
        t.units, t.calendar, t.bounds = "days since 1961-01-01", "standard", "time_bnds"
        step = 365.25 if freq == "yr" else 365.25 / 12
        t[:] = np.arange(nt) * step + step / 2
        nc.createVariable("time_bnds", "f8", ("time", "bnds"))[:] = np.stack(
            [np.arange(nt) * step, np.arange(nt) * step + step - 1], axis=1
        )
        lon = nc.createVariable("lon", "f8", ("lon",))
        lon.units = "degrees_east"
        lon[:] = np.arange(nx) * 10.0
        lt = nc.createVariable("lat", "f8", ("lat",))
        lt.units, lt.standard_name = "degrees_north", "latitude"
        lt[:] = lat[:ny]
        dims = ("time", "lat", "lon")
        if first.ndim == 4:
            nc.createDimension("scale", 3)
            nc.createVariable("scale", "i4", ("scale",))[:] = [1, 2, 3]
            dims = ("scale", *dims)
        for var, data in variables.items():
            v = nc.createVariable(var, "f4", dims, fill_value=np.float32(1e20))
            v.units, v.long_name = "days", f"{var} long name"
            v[:] = np.ma.masked_invalid(data)
        if "day_of" not in name and freq == "yr":
            nc.createVariable(f"day_of_{name}", "f4", dims, fill_value=np.float32(1e20))
        nc.index_calculation_frequency = freq
    return path


def _values(seed, nt=40, ny=3, nx=4):
    rng = np.random.default_rng(seed)
    v = np.round(rng.normal(10, 3, (nt, ny, nx)) + 0.1 * np.arange(nt)[:, None, None], 1)
    v[:, 0, 0] = np.nan  # a missing cell (ocean)
    v[rng.random(v.shape) < 0.1] = np.nan
    return v


def _read(path, name):
    with netCDF4.Dataset(path) as nc:
        var = nc.variables[name]
        attrs = SimpleNamespace(**{k: var.getncattr(k) for k in var.ncattrs()})
        return np.ma.filled(var[:].astype(float), np.nan), attrs


def test_trends_file_per_cell_equals_the_station_trend(tmp_path):
    fd = _values(1)
    hw = {"hwm_tx90": _values(2), "hwa_tx90": _values(3)}
    spi = np.stack(
        [np.round(np.random.default_rng(s).normal(0, 1, (480, 3, 4)), 2) for s in (4, 5, 6)]
    )
    paths = [
        _index_file(tmp_path / "fd_ANN_x.nc", "fd", fd),
        _index_file(tmp_path / "fd_MON_x.nc", "fd", np.zeros((480, 3, 4)), freq="mon"),
        _index_file(tmp_path / "hw_ANN_x.nc", "hw", None, variables=hw),
        _index_file(tmp_path / "spi_MON_x.nc", "spi", spi, freq="mon"),
    ]
    # The fd monthly file has no scale dimension: no series of its own.
    assert [s.name for s in annual_series(paths)] == ["fd", "hwm_tx90", "hwa_tx90", "spi"]
    out = write_grid_trends(paths, tmp_path / "out" / TRENDS_FILE, 1971, 1990, workers=2)
    years = np.arange(1961, 2001)
    weights = cell_weights(np.array([-40.0, 0.0, 60.0]))[:, None] * np.ones(4)
    for name, values in (("fd", fd), *hw.items(), ("spi", spi[2, 11::12])):
        cells = values.astype(np.float32).astype(float).reshape(len(years), -1).T
        ref = _station(cells) * 10
        for i, suffix in enumerate(("lower", "slope", "upper")):
            got, var = _read(out, f"{name}_{suffix}")
            assert got.shape == (3, 4) and _same(got.ravel(), ref[:, i]), (name, suffix)
            assert var.units == "days per decade"
        base, _ = _read(out, f"{name}_base_mean")
        assert _same(base.ravel(), base_means(cells, years, 1971, 1990))
        mean, var = _read(out, f"{name}_grid_mean")
        assert _same(mean, grid_means(cells.T, weights.ravel()))
        assert "cos(latitude)" in var.cell_methods
    slope, _ = _read(out, "fd_slope")
    assert np.isnan(slope[0, 0]) and np.isfinite(slope[1:]).all()  # the missing cell
    with netCDF4.Dataset(out) as nc:
        assert not any(v.startswith("day_of") for v in nc.variables)
        assert nc.base_period == "1971-1990" and nc.trend_period == "1961-2000"
        assert nc.variables["time"].shape == (40,) and nc.variables["time_bnds"].shape == (40, 2)
        assert nc.variables["fd_slope"].dimensions == ("lat", "lon")
        assert nc.variables["fd_slope"][0, 0] is np.ma.masked
    assert not list((tmp_path / "out").glob(".*tmp"))


def test_blocks_and_threads_do_not_change_the_file(tmp_path):
    paths = [
        _index_file(tmp_path / f"{n}_ANN_x.nc", n, _values(s)) for n, s in (("a", 1), ("b", 2))
    ]
    one = write_grid_trends(paths, tmp_path / "one.nc", 1971, 1990)
    many = write_grid_trends(
        paths, tmp_path / "many.nc", 1971, 1990, workers=3, max_cells=4, cells_per_chunk=2
    )
    with netCDF4.Dataset(one) as a, netCDF4.Dataset(many) as b:
        for name in ("a_slope", "a_lower", "b_upper", "b_base_mean"):
            assert _same(np.ma.filled(a[name][:], np.nan), np.ma.filled(b[name][:], np.nan))
        # The grid mean is summed by stripes of rows: equal up to rounding.
        assert np.allclose(a["a_grid_mean"][:], b["a_grid_mean"][:], rtol=1e-14)


def test_latitude_weights_and_mismatched_files(tmp_path):
    a = _index_file(tmp_path / "a_ANN_x.nc", "a", _values(1))
    out = write_grid_trends([a], tmp_path / "t.nc", 1971, 1990, latitude=np.zeros((3, 4)))
    mean, _ = _read(out, "a_grid_mean")
    cells = _values(1).astype(np.float32).astype(float).reshape(40, -1)
    assert _same(mean, grid_means(cells, np.ones(12)))
    short = _index_file(tmp_path / "b_ANN_x.nc", "b", _values(2, nt=30))
    with pytest.raises(ValueError, match="grid or years differ"):
        write_grid_trends([a, short], tmp_path / "t.nc", 1971, 1990)
    with pytest.raises(ValueError, match="latitude has shape"):
        write_grid_trends([a], tmp_path / "t.nc", 1971, 1990, latitude=np.zeros(3))
    tx95t = _index_file(tmp_path / "tx95t_DAY_x.nc", "tx95t", _values(1), freq="NA")
    assert write_grid_trends([tx95t], tmp_path / "none.nc", 1971, 1990) is None
    assert not (tmp_path / "none.nc").exists()


def test_from_the_indices_and_the_command_line(tmp_path, capsys):
    grid = write_grid(tmp_path / "g.nc", ny=2, nx=2, end="1982-12-31")
    out = tmp_path / "out"
    args = ["gridded-indices", str(grid), "--out", str(out), "--base-start", "1972"]
    args += ["--base-end", "1975", "--indices", "fd", "txx", "tx95t", "--trends", "--quiet"]
    assert main(args) == 0
    assert "Wrote " + str(out / TRENDS_FILE) in capsys.readouterr().out
    trends = out / TRENDS_FILE
    with netCDF4.Dataset(trends) as nc:
        names = {v for v in nc.variables if "_" in v and v != "time_bnds"}
    assert names == {f"{i}_{s}" for i in ("fd", "txx") for s in
                     ("slope", "lower", "upper", "base_mean", "grid_mean")}  # fmt: skip
    (fd_ann,) = out.glob("fd_ANN_*.nc")
    values, _ = _read(fd_ann, "fd")
    ref = _station(values.reshape(12, -1).T) * 10
    slope, _ = _read(trends, "fd_slope")
    assert _same(slope.ravel(), ref[:, 1]) and np.isfinite(slope).all()
    # The function the command line calls, with the input's latitudes.
    again = write_grid_trends(
        sorted(out.glob("*_ANN_*.nc")), tmp_path / "again.nc", 1972, 1975,
        latitude=open_grid([grid]).cell_latitude().values,
    )  # fmt: skip
    a, _ = _read(again, "txx_grid_mean")
    b, _ = _read(trends, "txx_grid_mean")
    assert _same(a, b)
    # Without --trends, no trends.nc.
    plain = [a for a in args if a != "--trends"]
    plain[plain.index("--out") + 1] = str(tmp_path / "o2")
    assert main(plain) == 0
    assert not (tmp_path / "o2" / TRENDS_FILE).exists()


def test_indices_alone_write_no_trends(tmp_path):
    grid = write_grid(tmp_path / "g.nc", ny=1, nx=1, end="1972-12-31")
    written = write_grid_indices(open_grid([grid]), tmp_path / "o", 1971, 1972, indices=["fd"])
    assert TRENDS_FILE not in {p.name for p in written}
