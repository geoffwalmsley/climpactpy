# R reference

Runs the original Climpact v3.4.3 (R) in Docker, so no local R install is needed.

```sh
./reference/run_r_reference.sh                 # build image, run every station in stations.csv
./reference/run_r_reference.sh lat0 sydney     # only the named runs
```

Expects the original repo at `../climpact` (override with `CLIMPACT_DIR`). It is mounted read-only.

Each row of [`stations.csv`](stations.csv) is one run:

| Column | Meaning |
| --- | --- |
| `run` | Run name. Outputs go to `output/<run>/<name>_<start>-<end>/` |
| `id` | GHCN-Daily station id |
| `name`, `start`, `end` | The input file is `input/<name>_<start>-<end>.txt` |
| `lat`, `lon` | Coordinates passed to Climpact (the station's GHCN coordinates rounded to 2 dp), so the hemisphere rules and Hargreaves PET follow the real station |
| `source` | `ghcn`: converted from GHCN-Daily by `fetch_ghcn.py`; `climpact`: Climpact's own sample file; `synthetic`: made by a script here (only its `qc/` files are compared) |

Each run writes indices, thres, trend, qc and plots, plus `r-package-versions.csv` and
`climpact-commit.txt`. The `lat0` run also runs Climpact's own CSV test
(`climpact/tests/output_compare`) and writes `comparison_summary.csv`.

The CSV outputs are committed so tests can use them without Docker; plots (PNG/PDF) are gitignored.
The plot file names are committed in `output/<run>/plot-files.txt` (written by
`run_r_reference.sh` when the run has plots), for the plot file-list test.
Re-running changes the `Date_of_calculation` header line in every CSV, so only commit a re-run when the
numbers are meant to change.

Climpact does not write an index's CSV when every value of it is missing ("NO DATA FOR tmm. NOT
WRITING .csv FILE."), so stations with patchy data have fewer files (see the table below).

## Runs

All runs use base period 1971-2000 and the Shiny UI defaults (WSDI/CSDI d=1, Rx3day, TX2TN2,
R30mm, SPEI 24, custom TN > 0).

| Run | Station (GHCN id) | Lat | Period | Covers | Index files |
| --- | --- | --- | --- | --- | --- |
| `lat0` | Sydney Observatory Hill (ASN00066062) | 0 | 1936-2015 | Reproduces `climpact/tests/output_compare` and runs its `test_output.R` | 114 |
| `sydney` | Sydney Observatory Hill (ASN00066062) | -33.86 | 1936-2015 | Same file at its real coordinates; only SPEI differs from `lat0` | 114 |
| `minneapolis` | Minneapolis-St Paul (USW00014922) | 44.89 | 1961-2020 | NH cold continental: frost/ice days, csdi, NH gsl | 114 |
| `yakutsk` | Yakutsk (RSM00024959) | 62.02 | 1961-2020 | Extreme cold: tnltm20, short growing season | 114 |
| `phoenix` | Phoenix (USW00023183) | 33.43 | 1961-2020 | NH hot arid: txge35, long cdd, zero-rain months | 114 |
| `alice_springs` | Alice Springs (ASN00015590) | -23.80 | 1961-2020 | SH arid | 114 |
| `darwin` | Darwin (ASN00014015) | -12.42 | 1961-2020 | Tropical monsoon, no frost | 114 |
| `perth` | Perth Airport (ASN00009021) | -31.93 | 1961-2020 | SH Mediterranean | 114 |
| `madrid` | Madrid Retiro (SP000003195) | 40.41 | 1961-2020 | NH Mediterranean, 667 m | 114 |
| `oxford` | Oxford (UK000056225) | 51.77 | 1961-2020 | Maritime, mild winters | 112 (no wsdi1, csdi1) |
| `potsdam` | Potsdam (GM000003342) | 52.38 | 1961-2020 | Central European | 114 |
| `beijing` | Beijing (CHM00054511) | 39.93 | 1961-2020 | Monsoon continental; 8 years fail the annual missing-data rule | 114 |
| `dublin` | Dublin Phoenix Park (EI000003969) | 53.36 | 1961-2020 | Missing-data rules (8 bad years) | 114 |
| `new_delhi` | New Delhi Safdarjung (IN022021900) | 28.58 | 1961-2020 | Stress: patchy base period (71-86 %) | 80 |
| `nairobi` | Nairobi JKIA (KE000063740) | -1.32 | 1961-2020 | Stress: near-equator SH, patchy temperature base (65-68 %), 1,624 m | 57 |
| `qc_stress` | Synthetic, from Potsdam (GM000003342) | 52.38 | 1961-2020 | QC checks: planted duplicate dates, TN >= TX, too-large values, jumps, flat lines, missing values (see below) | 114 (not compared) |

## Gridded reference

Climpact's gridded thresholds (`climpact.ncdf.thresholds.wrapper.r`, which calls
`create.thresholds.from.file` in Climpact's own modified `climdex.pcic.ncdf`) and gridded
indices (`climpact.ncdf.wrapper.r`, `create.indices.from.files`) are run on three small test
grids by

```sh
.venv/bin/python reference/gridded/make_grids.py   # make the input grids (deterministic)
./reference/run_r_gridded.sh                        # build the image, run every grid
./reference/run_r_gridded.sh grid_sample            # only the named runs
```

`make_grids.py` needs the original repo for the sample grid (`--climpact`, or `CLIMPACT_DIR`,
default `../climpact`). Each row of [`gridded/runs.csv`](gridded/runs.csv) is one run: its
input files in `gridded/input/` (`;`-separated), the netCDF names of TX, TN and precipitation,
the base period, whether to compute a thresholds file (`thresholds`), the run whose
thresholds file the indices use (`indices_thresholds`; empty: R computes the thresholds
itself) and the indices left out of R's index run (`indices_exclude`, `;`-separated). A run
that uses another's thresholds file comes after it.

The R outputs go to `gridded/output/<run>/`: `thresholds.nc`, `indices/<index>_<FREQ>_climpactpy_historical_NA_<years>.nc`
(R's names from the default template `var_daily_climpactpy_historical_NA_<first>-<last year>.nc`),
`r-package-versions.csv` and `climpact-commit.txt`. The wrappers are scripts with hard-coded
settings, so `r/run_gridded_thresholds.R` and `r/run_gridded_indices.R` make their calls with
the run's files, names, base period (and thresholds file) and the wrappers' fixed settings
(`fclimdex.compatible = FALSE`, no cluster; for the indices `EHF_DEF = "NF13"`, `maxvals = 10`,
`wsdin_n = csdin_n = 5`, `rxnday_n = 7`, `ntxntn_n = ntxbntnb_n = 3`, `hddheatn_n =
cddcoldn_n = 18`, `gddgrown_n = 10`, `rnnmm_n = 30`, `project.lat2d.coords = TRUE` and the
wrapper's `thresholds.name.map`), and author data `climpactpy reference` / `CPY`.

| Run | Grid | Period, base | Covers |
| --- | --- | --- | --- |
| `grid_stations` | 3 lat (52.5, 0, -33.75) x 4 lon, one committed station input per cell | 1966-2005, base 1971-2000 | Both hemispheres and the equator; an all-missing cell; a sparse base period (about 10% of values kept, so some windows have too few values); a dry cell (no wet day in the base period); missing years of TX and TN; TX in K as float with `missing_value`, TN in degrees C as double, precipitation in kg m-2 s-1 in a second file |
| `grid_sample` | 3 x 4 cut of Climpact's `www/sample_data/climpact.sampledata.gridded.1991-2010.nc` (south-east Australia) | 1991-2010, base 1991-2010 (the wrapper's defaults) | A real CF file: K, kg m-2 d-1, time in hours since 1800 with `time_bnds` |
| `grid_future` | The cells of `grid_stations` for 2001-2020, stored the same way | 2001-2020; indices only, with `grid_stations`' thresholds file (base 1971-2000) | R's thresholds-file path, which it accepts only for data with no day in the base period (otherwise `check.quantile.validity` stops: "Temperature in-base quantiles must contain 10th and 90th percentiles") |

R stops in `write.climdex.results` on the `hw` and `hwEHF` files of any grid with an
all-missing cell, so `grid_stations` and `grid_future` leave those two indices out (86 index
files each; `grid_sample` has all 88).

The inputs (2.2 MB) and outputs (2.1 MB of thresholds, 9.2 MB of index files) are committed.
R writes uncompressed files with one chunk per time step; `run_r_gridded.sh` repacks them with
`nccopy -d 9 -s` and larger chunks, which changes neither the variables, values nor attributes.
Re-running changes the `file_created` and `history` attributes, so only commit a re-run when
the numbers are meant to change (the thresholds files of #29 were re-run for #30 and were
identical apart from those, so the committed ones were kept).

The image's netCDF support (ncdf4, abind, snow, udunits2, functional, proj4 from the same CRAN
snapshot, and Climpact's `ncdf4.helpers` 0.3-3 and modified `climdex.pcic.ncdf` 0.5-4 fetched
from the pinned Climpact commit) is installed in layers after the station packages, which are
unchanged: the rebuilt image reproduces the committed `sydney` outputs (every CSV identical apart
from `Date_of_calculation`).

## Sector correlation reference

Climpact's step 4, sector correlation (`server/sector_correlation.R`), is run on the
committed `sydney` outputs by

```sh
./reference/run_r_sector.sh
```

`r/run_sector_correlation.R` calls `draw.correlation` as the app's
`modules/singleStationStep4.R` does, with the app's defaults: title the station name, y-axis
label `wheat` (the file name up to its first `_` or `.`). Inputs: the raw station file
`input/sydney_observatory_hill_1936-2015.txt` (R re-reads it at this step), the index CSVs in
`output/sydney/<station>/indices/`, and `input/sector/wheat_yield_nsw_1922-1999.csv`, a copy
of Climpact's `www/sample_data` file. It runs twice, detrended (the app's default) and not,
into `output/sydney/sector/detrended/` and `output/sydney/sector/raw/` (R's `corr/` folder),
with `r-package-versions.csv` and `climpact-commit.txt`. The CSVs are committed; the PNGs are
gitignored. The R files carry no date, so a re-run with the same inputs reproduces them.

The scatter plots need ggplot2, which the image installs from the same CRAN snapshot in a
layer after the station and gridded packages, so those are unchanged.

## Synthetic QC station

`qc_stress_1961-2020.txt` is Potsdam's input with faults planted for every per-value QC
check, made by

```sh
.venv/bin/python reference/make_qc_stress.py
```

None of the real stations has a duplicated date, and several checks fire at only a few of
them. The script's docstring lists the faults. The parity tests compare only this run's
`qc/` files; its index, threshold and trend files are committed but not compared.

## Station data: GHCN-Daily

The input files other than Sydney's come from NOAA NCEI's Global Historical Climatology Network -
Daily (Menne et al. 2012, GHCN-Daily v3, doi:10.7289/V5D21VHZ), one CSV per station:
`https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/<ID>.csv`.

```sh
.venv/bin/python reference/fetch_ghcn.py            # every source=ghcn row of stations.csv
.venv/bin/python reference/fetch_ghcn.py phoenix    # one station
```

Downloads are cached in `reference/.ghcn-cache/` (gitignored); `--refresh` downloads again.

Conversion rules:

- one row per calendar day from 1 January of `start` to 31 December of `end`, tab-separated
  `year month day prcp tmax tmin`, as in Climpact's sample file;
- GHCN values are tenths of mm / degC, so they are divided by 10;
- **a value with a non-blank QFLAG (it failed GHCN quality control) is written as missing.** Climpact
  runs its own QC, but it does not remove values, and a value GHCN has already rejected should not
  reach the indices. Oxford (848 values, flag `I`) and Dublin (264, flag `I`) are the most affected;
  `fetch_ghcn.py` prints the count per station;
- missing (blank or flagged) is written as `-99.9`.

The window is 1961-2020 for every new station (the Australian GHCN copies end in 2020).

### Sydney: Climpact's file, not the GHCN conversion

`lat0` and `sydney` keep Climpact's own sample file (`source=climpact`), because that is what the
stored Climpact outputs were made from. Converting GHCN ASN00066062 for 1936-2015 with the rules
above does **not** give the same file, although every value present in both is identical (so the
units, dates and format of the conversion are right):

| Difference | Days |
| --- | --- |
| Value in GHCN, missing in Climpact's file | 45 TMAX, 44 TMIN |
| Value in Climpact's file, QC-flagged in GHCN (set missing) | 91 TMIN (flag `D`, mostly Dec 1936), 3 TMAX (`O`), 1 TMAX (`S`), 1 PRCP (`L`) |
| Value in Climpact's file, no longer in GHCN | 1 TMAX, 1 TMIN, 1 PRCP |

Run through the R reference, the GHCN conversion matches the stored `sydney` outputs in 24 of 116 index, threshold and trend
files (ignoring the standardised-anomaly column); the rest differ in the years touched above (and SPEI,
EHF and the thresholds, which use the whole series). The pipeline check for this ticket was instead:
the stations.csv-driven runner reproduces the committed `lat0` and `sydney` outputs byte for byte
(apart from `Date_of_calculation`) and Climpact's own `test_output.R` passes (114/0).

### Licence

NOAA/NCEI data are free to use. The GHCN-Daily `readme.txt` and NCEI's dataset record
(gov.noaa.ncdc:C00861) carry only warranty and liability disclaimers. Older NCEI documentation says that
some non-US GHCN-Daily data are subject to WMO Resolution 40 (since replaced by the WMO Unified Data
Policy, Resolution 1 (Cg-Ext 2021)): they may be used freely for research, education and other
non-commercial purposes, but not re-exported for commercial services. Committing the converted files
here, with attribution, to test the port is non-commercial use. Anyone redistributing these inputs
commercially should check the national source's terms.

## Pinned environment

- `rocker/r-ver:4.6.1`, CRAN from the Posit snapshot of 2026-09-18
- PCICt 0.5-4.4 from the CRAN archive; climdex.pcic 1.2-0 from GitHub commit `011cb78`
- For sector correlation: ggplot2 from the same snapshot (`r-package-versions.csv` in
  `output/sydney/sector/` lists the version)
- For gridded runs: ncdf4 1.24, udunits2 0.13.2.2 and the other CRAN packages from the same
  snapshot; ncdf4.helpers 0.3-3 and climdex.pcic.ncdf 0.5-4 (Climpact's modified version) from
  Climpact's `server/pcic_packages` at commit `5ee0cfe` (checked by SHA-256)
- Runs as `linux/amd64` (emulated on Apple Silicon). On native arm64, climdex.pcic's bootstrapped
  in-base percentiles round differently and tx10p, tn10p, tx90p and csdi change in some base-period
  years. Use `PLATFORM=linux/arm64` to run natively anyway.
