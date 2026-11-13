"""Make the small gridded inputs used for the gridded R reference runs.

Three runs (``reference/gridded/runs.csv``):

``grid_stations``
    A synthetic 3 lat x 4 lon grid cut from the committed station inputs, 1966-2005
    (base period 1971-2000). Latitudes 52.5, 0 and -33.75 (both hemispheres and the
    equator, which R counts as northern). Each cell holds one station's series, so the
    values are real weather; four cells are made to exercise missing data:

    - an all-missing cell (as over the ocean in a land-only grid);
    - a sparse base period: about 10% of the base-period values kept (seeded), so some
      5- and 15-day windows have fewer than 10% of their values and their thresholds
      are missing;
    - a dry cell: precipitation below 1 mm on every day of the base period, so the
      wet-day percentiles are missing;
    - a cell with three base-period years of TX missing and a year of TN missing.

    Storage is chosen to exercise R's reading and unit conversion: TX in K as float
    with a ``missing_value`` attribute, TN in degrees C as double with ``_FillValue``,
    both in ``grid_stations_tas.nc``; precipitation in kg m-2 s-1 as float in a second
    file, ``grid_stations_pr.nc``.

``grid_future``
    The cells of ``grid_stations`` for 2001-2020, after its base period, stored the
    same way (``grid_future_tas.nc``, ``grid_future_pr.nc``), with no cell degraded
    apart from the all-missing one (Sydney's series ends in 2015). Only indices are
    computed for it, with ``grid_stations``' thresholds file: R's
    ``create.indices.from.files`` accepts a thresholds file only for data with no day
    in the base period.

``grid_sample``
    A 3 x 4 cut of Climpact's own sample, ``www/sample_data/
    climpact.sampledata.gridded.1991-2010.nc`` (south-eastern Australia), with its
    variables, types and attributes unchanged (stored as compressed netCDF4 classic):
    ``tmax``/``tmin`` in K, ``precip`` in kg m-2 d-1, time in hours since 1800 with
    ``time_bnds``. Run with base period 1991-2010, the defaults of
    ``climpact.ncdf.thresholds.wrapper.r``.

    .venv/bin/python reference/gridded/make_grids.py [--climpact ../climpact]

The output is deterministic.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import netCDF4
import numpy as np
import pandas as pd

from climpact.io.station import read_station_file

HERE = Path(__file__).parent
STATIONS = HERE.parent / "input"
OUT = HERE / "input"

START, END = 1966, 2005
BASE = (1971, 2000)
LATS = [52.5, 0.0, -33.75]
LONS = [-93.25, 13.0, 77.25, 151.25]
# Station input per cell, rows north to south; None for the all-missing cell.
CELLS = [
    ["minneapolis_st_paul_1961-2020", "potsdam_1961-2020", "yakutsk_1961-2020", None],
    [
        "nairobi_jkia_1961-2020",
        "madrid_retiro_1961-2020",
        "new_delhi_safdarjung_1961-2020",
        "darwin_1961-2020",
    ],
    [
        "alice_springs_1961-2020",
        "perth_airport_1961-2020",
        "oxford_1961-2020",
        "sydney_observatory_hill_1936-2015",
    ],
]
SPARSE = (0, 2)  # yakutsk: about 10% of base-period values kept
DRY = (2, 0)  # alice springs: no wet day in the base period
GAPS = (2, 2)  # oxford: TX missing 1980-1982, TN missing 1990
TIME_UNITS = "days since 1950-01-01 00:00:00"
SAMPLE = "www/sample_data/climpact.sampledata.gridded.1991-2010.nc"
SAMPLE_LAT = slice(10, 13)
SAMPLE_LON = slice(18, 22)


FUTURE = (2001, 2020)


def station_cube(
    start: int = START, end: int = END, degrade: bool = True
) -> tuple[pd.DatetimeIndex, dict[str, np.ndarray]]:
    dates = pd.date_range(f"{start}-01-01", f"{end}-12-31", freq="D")
    shape = (dates.size, len(LATS), len(LONS))
    cube = {k: np.full(shape, np.nan) for k in ("prcp", "tmax", "tmin")}
    for i, row in enumerate(CELLS):
        for j, name in enumerate(row):
            if name is None:
                continue
            df = read_station_file(STATIONS / f"{name}.txt").drop_duplicates("date", keep="last")
            df = df.set_index("date").reindex(dates)
            for k in cube:
                cube[k][:, i, j] = df[k].to_numpy()
    if not degrade:
        return dates, cube

    in_base = (dates.year >= BASE[0]) & (dates.year <= BASE[1])
    rng = np.random.default_rng(29)
    drop = in_base & (rng.random(dates.size) > 0.1)
    for k in cube:
        cube[k][drop, SPARSE[0], SPARSE[1]] = np.nan
    wet = cube["prcp"][:, DRY[0], DRY[1]]
    cube["prcp"][in_base, DRY[0], DRY[1]] = np.minimum(wet[in_base], 0.9)
    cube["tmax"][(dates.year >= 1980) & (dates.year <= 1982), GAPS[0], GAPS[1]] = np.nan
    cube["tmin"][dates.year == 1990, GAPS[0], GAPS[1]] = np.nan
    return dates, cube


def _coords(nc: netCDF4.Dataset, dates: pd.DatetimeIndex) -> None:
    nc.createDimension("time", None)
    nc.createDimension("lat", len(LATS))
    nc.createDimension("lon", len(LONS))
    t = nc.createVariable("time", "f8", ("time",))
    t.setncatts(
        {
            "standard_name": "time",
            "long_name": "time",
            "units": TIME_UNITS,
            "calendar": "standard",
            "axis": "T",
        }
    )
    t[:] = netCDF4.date2num(dates.to_pydatetime(), TIME_UNITS, "standard")
    lat = nc.createVariable("lat", "f8", ("lat",))
    lat.setncatts(
        {
            "standard_name": "latitude",
            "long_name": "latitude",
            "units": "degrees_north",
            "axis": "Y",
        }
    )
    lat[:] = LATS
    lon = nc.createVariable("lon", "f8", ("lon",))
    lon.setncatts(
        {
            "standard_name": "longitude",
            "long_name": "longitude",
            "units": "degrees_east",
            "axis": "X",
        }
    )
    lon[:] = LONS
    nc.setncatts(
        {
            "title": "climpactpy gridded test grid",
            "Conventions": "CF-1.6",
            "source": "GHCN-Daily and Climpact sample stations (reference/input), "
            "one station per cell; see reference/gridded/make_grids.py",
        }
    )


def write_station_grid(name: str = "grid_stations", future: bool = False) -> None:
    dates, cube = station_cube(*FUTURE, degrade=False) if future else station_cube()
    CHUNKS = (dates.size, 1, 1)  # noqa: N806 - one time series per chunk compresses best
    dims = ("time", "lat", "lon")
    with netCDF4.Dataset(OUT / f"{name}_tas.nc", "w", format="NETCDF4") as nc:
        _coords(nc, dates)
        tx = nc.createVariable(
            "tasmax", "f4", dims, zlib=True, complevel=9, fill_value=False, chunksizes=CHUNKS
        )
        tx.setncatts(
            {
                "standard_name": "air_temperature",
                "long_name": "daily maximum temperature",
                "units": "K",
                "missing_value": np.float32(-999.0),
            }
        )
        tx.set_auto_maskandscale(False)
        tx[:] = np.where(np.isnan(cube["tmax"]), -999.0, cube["tmax"] + 273.15).astype("f4")
        tn = nc.createVariable(
            "tasmin", "f8", dims, zlib=True, complevel=9, fill_value=1e20, chunksizes=CHUNKS
        )
        tn.setncatts(
            {
                "standard_name": "air_temperature",
                "long_name": "daily minimum temperature",
                "units": "degrees_C",
            }
        )
        tn[:] = np.ma.masked_invalid(cube["tmin"])
    with netCDF4.Dataset(OUT / f"{name}_pr.nc", "w", format="NETCDF4") as nc:
        _coords(nc, dates)
        pr = nc.createVariable(
            "pr", "f4", dims, zlib=True, complevel=9, fill_value=1e20, chunksizes=CHUNKS
        )
        pr.setncatts(
            {
                "standard_name": "precipitation_flux",
                "long_name": "precipitation",
                "units": "kg m-2 s-1",
            }
        )
        pr[:] = np.ma.masked_invalid((cube["prcp"] / 86400.0).astype("f4"))


def write_sample_grid(climpact: Path) -> None:
    with (
        netCDF4.Dataset(climpact / SAMPLE) as src,
        netCDF4.Dataset(OUT / "grid_sample.nc", "w", format="NETCDF4_CLASSIC") as dst,
    ):
        dst.setncatts({k: src.getncattr(k) for k in src.ncattrs()})
        sub = {"lat": SAMPLE_LAT, "lon": SAMPLE_LON}
        for name, dim in src.dimensions.items():
            size = (
                None
                if dim.isunlimited()
                else len(range(*sub[name].indices(len(dim))))
                if name in sub
                else len(dim)
            )
            dst.createDimension(name, size)
        for name, var in src.variables.items():
            chunks = [
                len(dst.dimensions[d]) if d != "time" else len(src.dimensions[d])
                for d in var.dimensions
            ]
            if "lat" in var.dimensions:
                chunks = [
                    c if d == "time" else 1 for c, d in zip(chunks, var.dimensions, strict=True)
                ]
            out = dst.createVariable(
                name, var.dtype, var.dimensions, zlib=True, complevel=9, chunksizes=chunks
            )
            out.setncatts({k: var.getncattr(k) for k in var.ncattrs()})
            var.set_auto_maskandscale(False)
            out.set_auto_maskandscale(False)
            index = tuple(sub.get(d, slice(None)) for d in var.dimensions)
            out[:] = var[index]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--climpact",
        type=Path,
        default=Path(os.environ.get("CLIMPACT_DIR", HERE.parents[2] / "climpact")),
        help="the original Climpact repository (default: ../climpact)",
    )
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    write_station_grid()
    write_station_grid("grid_future", future=True)
    write_sample_grid(args.climpact)
    for path in sorted(OUT.glob("*.nc")):
        print(f"{path.relative_to(HERE.parent.parent)}: {path.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
