# climpactpy technical notes

Technical documentation for the Python port of [Climpact](https://github.com/ARCCSS-extremes/climpact).
It covers how the code is organised, how results are checked against the R version, and
every known difference between the Python and R implementations and how each is handled.

Reference version: **Climpact R v3.4.3** (commit `5ee0cfe`), with climdex.pcic 1.2-0.

## Status

The Python port reproduces **all 125** R reference files for Sydney (`lat0` and
`sydney`), and every file R wrote for all 13 GHCN stations and the synthetic QC station,
with none failing and none left to port (see [Reference outputs](#reference-outputs)).
Sector correlation (the app's step 4, `climpact sector-correlation`, #84) reproduces R's
ten files for Sydney with Climpact's sample wheat data, detrended and not (see
[Sector correlation](#sector-correlation)).
Gridded base-period thresholds (`climpact gridded-thresholds`, #29) reproduce every
variable of R's thresholds netCDF bit for bit on the six gridded reference grids that
have one, and the gridded indices (`climpact gridded-indices`, #30, #87) reproduce every
variable of all 88 index files R writes per grid, including the heatwave, EHF, SPI and
SPEI files, bit for bit on all eight reference grids, three of them in the `noleap` and
`360_day` calendars (#66; see [Gridded data](#gridded-data)).
Every file is also written text-identical to R's on all 16 runs, apart from the `Date_of_calculation` line (on platforms other than glibc
x86_64, the SPI and SPEI values agree to 1e-10 relative; see [SPI and SPEI](#spi-and-spei)):

| Area | Ported | Not yet ported |
| --- | --- | --- |
| Threshold counts | fd, tnlt2, tnltm2, tnltm20, id, su, tr, txge30, txge35, tmge5, tmge10, tmlt5, tmlt10, r10mm, r20mm, rNNmm, custom index | |
| Means and totals | dtr, tmm, txm, tnm, prcptot, sdii | |
| Extremes (with dates) | txx, tnn, tnx, txn, rx1day, rx3day (rxdday), rx5day | |
| Spells (with dates) | cdd, cwd, gsl | |
| Degree days | hddheat, cddcold, gddgrow | |
| Percentile indices | tx95t, r95p, r99p, r95ptot, r99ptot, tx90p, tx10p, tn90p, tn10p, txgt50p (with the in-base bootstrap) | |
| Spell durations | wsdi, csdi, wsdid, csdid (`wsdi1`, `csdi1`), txdtnd, txbdtnbd (`tx2tn2`, `txb2tnb2`) | |
| Heatwaves | Tx90/Tn90 (HWM, HWA, HWN, HWD, HWF each), EHF (HWN, HWF, HWD, HWMD, HWPI, HWLI, HWPS, HWLS), daily EHF and ECF | |
| Drought | SPI, SPEI (3, 6, 12 months and the custom scale `spei_months`) | |
| Quality control | qc/nastatistics, qc/tmaxmin, qc/toolarge, qc/duplicates, qc/tx_jumps, qc/tn_jumps, qc/tx_flatline, qc/tn_flatline, qc/outliers (see [Quality control](#quality-control)) | QC plots are out of scope (#9) |
| Other outputs | thresholds file (`thres/thres`), trend file (`trend/trend`), CSV files for all ported outputs, gridded thresholds netCDF, gridded index netCDF files, index plots (PNG) and the combined PDF, zip archive (see [Plots and zip archive](#plots-and-zip-archive)), sector correlation tables and plots (`corr/`, see [Sector correlation](#sector-correlation)) | web step 4 for sector correlation (#90) |
| Running | single station (`climpact run`), batch of stations from R's metadata file (`climpact batch`), gridded thresholds (`climpact gridded-thresholds`), gridded indices (`climpact gridded-indices`), sector correlation after a station run (`climpact sector-correlation`) | |
| Web app | Django + htmx skeleton (`climpact_web`): `climpact-web` starts it locally and offline, hosted mode reads its settings from the environment, health check; background jobs in a database-backed queue with a worker, progress pages, cancel, retry and retention; the design system (tokens, components, landing page, pattern library); single-station step 1, load data; batch processing of stations (see [Web front end](#web-front-end), [Background jobs](#background-jobs), [Single-station steps](#single-station-steps) and [Batch page](#batch-page)) | the screens: charts (#75), steps 2-4 (#77, #78, #90), downloads (#79), help (#81), gridded (#85) |
| Modules | QC, homogeneity and index module interfaces, third-party modules as plugins (see [Modules and plugins](#modules-and-plugins)); built-in homogeneity module `none` (pass-through) | homogeneity detection (#34) and adjustment (#35) |

Progress is printed at the end of every test run (see [Parity testing](#parity-testing)).

The Python port writes every ported output as a Climpact-format CSV file, text-identical
to R's apart from the `Date_of_calculation` line (see [Writing output files](#writing-output-files)).
With `--plots` it also draws R's index plots and combined PDF, under R's file names, and
with `--zip` zips the outputs as R's download does (see [Plots and zip archive](#plots-and-zip-archive)).

## Repository layout

The repository holds two Python packages, each with its own `pyproject.toml` (hatchling)
and tests, developed in one virtualenv with both installed editable (see
[Development](#development)). There is no uv workspace or lock file: a uv workspace could
be added later without moving files (#68).

```
packages/
  climpact/          the core package: distribution `climpactpy`, imported as `climpact`.
                     Its dependencies are the scientific stack only (xclim, xarray, numpy,
                     pandas, scipy, dask, netCDF4); extras `plots` and `dev`
  climpact-web/      the web front end, `climpact_web` (src/climpact_web, tests/): a Django
                     project, depends on the core (see [Web front end](#web-front-end))
reference/           the R reference outputs and the scripts that make them, shared at the root
ruff.toml            ruff settings for the whole repository (each package's pyproject.toml
                     extends it)
pytest.ini           `pytest` from the root runs both packages' tests; each package's
                     pyproject.toml has the same settings for running it alone
```

The core never imports `climpact_web`: `tests/test_layout.py` checks every Python file in
`packages/climpact`, and CI runs the core suite with only the core installed.

Paths in the rest of this document (`src/climpact/...`, `tests/...`) are relative to
`packages/climpact/`; `reference/...` is at the repository root.

```
src/climpact/
  cli.py             command line: `climpact run` (one station), `climpact batch` (many),
                     `climpact gridded-thresholds` and `climpact gridded-indices` (a netCDF
                     grid), `climpact modules` (list the modules available),
                     `climpact sector-correlation` (sector data against a station already run)
  modules.py         QCModule, HomogeneityModule, IndexModule; plugin discovery (entry
                     points); run_pipeline(): QC -> homogeneity -> indices
  batch.py           batch mode: R's batch metadata file, run_station(), run_batch() process pool
  plots.py           index plots (PNG), the combined PDF and the zip archives (matplotlib,
                     optional: the `plots` extra)
  progress.py        progress callbacks: Progress, BatchProgress, Steps (see Progress reporting)
  sector.py          sector correlation (R's step 4): sector_correlation(),
                     write_sector_correlation(), run_sector_correlation()
  config.py          StationMetadata, IndexParams, CustomIndex, QCParams (Climpact app defaults)
  station.py         StationRun (with cached base-period thresholds) and load_station()
  thresholds.py      base-period percentile thresholds; climdex and R type-7/8 quantiles,
                     vectorised over any leading dimensions (grid cells)
  calendars.py       CalendarDays: a daily axis in the noleap and 360_day calendars, for
                     gridded data (see Non-standard calendars)
  gridded/
    io.py            read CF netCDF tasmax/tasmin/pr as climdex.pcic.ncdf does (ncdf4
                     masking, udunits conversion); GriddedInput: dask blocks of cells,
                     load(), cell_latitude(), block_reader() (rechunks inputs chunked by
                     time step to a temporary file first, #67)
    thresholds.py    thresholds of every cell (cell_thresholds) and the thresholds netCDF
                     in R's layout (write_grid_thresholds)
    indices.py       indices of every cell (cell_indices, block_indices) and the index
                     netCDF files in R's names and layout (write_grid_indices)
    heatwaves.py     hw and hwEHF of every cell (hw_values, hwehf_values), with the
                     station heatwave and EHF code
    drought.py       SPI and SPEI of every cell (spi_values, spei_values): climdex.spi,
                     climdex.spei and the SPEI package's spei() (spei_package), with
                     TLMoments' PWMs and lmom's pelglo, pelgam, cdfglo, cdfgam
  qc.py              per-value QC checks (duplicates, tmaxmin, toolarge, jumps, flatline,
                     outliers with R's fivenum and boxplot.stats)
  data/
    climate.indices.csv  index definitions, copied unchanged from Climpact R (file headers)
  io/
    station.py       read Climpact/RClimDex station text files; build the xarray Dataset
    climpact_csv.py  read and write Climpact (R) output CSV files; R number formatting
    output_files.py  file names, folders and metadata headers; write_outputs()
  missing.py         climdex.pcic missing-data rules; registered with xclim as "climdex"
  outputs.py         registry of the index products; the built-in index module
                     (CLIMPACT_INDICES); build_all()
  periods.py         monthly and annual counts, max, min, first extremes and per-period
                     functions (fast resample), along the last axis of any array
  products/
    tables.py        shape results into Climpact's table layouts; standardised anomalies
    drought.py       SPI and SPEI (Climpact's cspei, lmomco fitting, SPEI's hargreaves)
    indices.py       index products, and the array functions (*_values) they and the
                     gridded indices share
    heatwaves.py     Tx90/Tn90 heatwave products; hw_aspects(), get.hw.aspects
    ehf.py           EHF heatwave products and the daily EHF/ECF series (climdex.hwEHF)
    thresholds.py    thresholds file and tx95t products
    qc.py            QC files: QC_REPORTS, the one list of QC files, qc/nastatistics and the
                     built-in QC module (CLIMPACT_QC)
    trends.py        trend file (trend/trend), built from the other products' tables
  compare.py         tiered comparison of tables against the R reference
  rnumerics.py       exact emulation of R's extended-precision sum, cumsum, mean and var,
                     the sums of moving windows (r_window_sums), and of R's round()
  rdist.py           exact ports of R's qnorm, pnorm, dnorm, pgamma (and glibc's lgamma)
  trends.py          Sen's slope and its 95% bounds (zyp.sen, confint.zyp, Kendall's Var(S)),
                     and the plots' trend: zyp.sen's intercept, Mann-Kendall p-value
tests/
  parity/            one test per R reference file and per gridded netCDF variable, plus
                     progress reporting
  libm.py            GLIBC_X86_64: whether the C maths library is the R reference's
  rreference.py      the original, plain R-precision and number-formatting code: the
                     reference the faster versions are tested against
  test_*.py          unit tests; test_layout.py: the core does not import climpact_web
  data/              unit-test fixtures (quantiles printed by R) and the R scripts that print them
  plugins/           climpact_example_plugin: an example third-party plugin package
reference/
  stations.csv       one row per R reference run: station, coordinates, period, input source
  fetch_ghcn.py      download GHCN-Daily stations and convert them to Climpact input files
  make_qc_stress.py  make the synthetic QC stress station from Potsdam
  input/             station input data used by the tests; input/sector/ Climpact's sample
                     sector file
  output/            R reference outputs, output/<run>/<station>/ (CSV only; plots are gitignored,
                     their names are in output/<run>/plot-files.txt); output/sydney/sector/
                     R's sector correlation files, detrended/ and raw/
  gridded/           gridded runs (runs.csv), make_grids.py, input grids and R's thresholds
                     and index netCDF files (output/<run>/thresholds.nc, output/<run>/indices/)
  r/, run_r_reference.sh, run_r_gridded.sh, run_r_sector.sh
                     Docker setup that produces reference/output (and its sydney/sector/) and
                     reference/gridded/output
                     (see reference/README.md)
```

## Data flow

```
station text file
  -> io.station.read_station_file   DataFrame(date, prcp, tmax, tmin), invalid dates dropped
  -> io.station.merged_rows         R's merged rows: first to last row's date, duplicates kept
  -> io.station.station_dataset     xarray Dataset on a full-year daily axis (last row of a date)
  -> StationRun(data, metadata, params, qc, qc_rows)
       run.thresholds               base-period thresholds, computed on first use and cached
       run.rows                     the merged rows the QC checks run on
  -> outputs.build_all(run)         modules.run_pipeline: {"indices/fd_ANN": DataFrame, ...}
       QC modules                   built-in "climpact": the qc/ files, on the input data
       homogeneity module           built-in "none": no tables, data unchanged
       index modules                built-in "climpact": the products below, then the
                                    derived products (the trend file), on the data
                                    the homogeneity module returned
  -> io.output_files.write_outputs  <out>/<station>/indices/<station>_fd_ANN.csv, ...
```

`climpact run` (`climpact.cli`) runs the whole chain for one station file
(`batch.run_station`). Station settings and every `IndexParams` value are options;
defaults are the Climpact app defaults, and the station name defaults to the file name
without its suffix. `climpact batch` runs the same chain for every station of an R batch
metadata file (see [Batch processing](#batch-processing)).
`climpact sector-correlation` then correlates annual sector data with a station already
run, reading the index files the run wrote (see [Sector correlation](#sector-correlation)).

### Station data model

`station_dataset` returns an `xarray.Dataset` with dimension `time` and variables:

| Variable | Units | Meaning |
| --- | --- | --- |
| `pr` | mm/d | daily precipitation |
| `tasmax` | degC | daily maximum temperature (TX) |
| `tasmin` | degC | daily minimum temperature (TN) |
| `tas` | degC | `(tasmax + tasmin) / 2` (TM) |

The rows of the file are first merged as R's `qualityControlCheck` does
(`io.station.merged_rows`): one row per day from the date of the file's first row to the
date of its last row, a date given more than once keeping all its rows in file order. The
time axis then runs from 1 January of the first year to 31 December of the last year,
as climdex.pcic's `climdexInput.raw` does, with the last row of each date. Days with no
data are NaN. Station metadata (name, latitude, longitude, base period) is kept in the
`StationRun` and copied into the Dataset attributes, together with `first_date` and
`last_date`, the first and last dates of the merged rows before padding (used for
climdex's base-period data check).

`StationRun.rows` is the merged rows (`date`, `prcp`, `tmax`, `tmin`), duplicates
included, which the QC checks run on. `load_station` stores them in `qc_rows`; a
`StationRun` built from a Dataset alone rebuilds them from the Dataset (one row per date).

The Dataset is one-dimensional in time. Batch runs do not add a `station` dimension: each
station is a separate `StationRun` in its own process, because stations have their own
time axes, coordinates and parameters. Gridded data have their own data path (see
[Gridded data](#gridded-data)); the threshold functions and the array functions of the
index products take any leading dimensions.

### Index parameters

`IndexParams` holds the user-set parameters with the Climpact app defaults:

| Parameter | Default | Used by |
| --- | --- | --- |
| `wsdi_days`, `csdi_days` | 1 | wsdid, csdid (outputs named `wsdi1`, `csdi1`) |
| `rx_days` | 3 | rxdday (output named `rx3day`) |
| `txtn_days` | 2 | txdtnd, txbdtnbd (outputs named `tx2tn2`, `txb2tnb2`) |
| `hdd_base`, `cdd_base`, `gdd_base` | 18, 18, 10 °C | hddheat, cddcold, gddgrow |
| `rnnmm` | 30 mm | rNNmm (output named `r30mm`) |
| `spei_months` | 24 | custom SPI/SPEI scale (outputs named `24month_spi_MON`, `24month_spei_MON`) |
| `custom` | TN > 0 | custom threshold index (output named `TNgt0`) |

Parameter values in output names are formatted as R's `paste` does (`30`, not `30.0`).

`QCParams` (`StationRun.qc`) holds the QC thresholds of `load_data_qc`, the values the
reference runs use (`reference/r/run_reference.R`):

| Parameter | Default | Used by |
| --- | --- | --- |
| `iqr_temp`, `iqr_prec` | 3, 5 | qc/outliers |
| `prec_max`, `temp_max` | 200 mm, 50 °C | qc/toolarge |
| `flatline_days` | 5 | qc/tx_flatline, qc/tn_flatline |
| `jump` | 20 °C | qc/tx_jumps, qc/tn_jumps |

The command line and batch mode use the defaults, as R's batch mode does.

### Output products

Every index, threshold and trend file is built by a *product*: a function registered with `@outputs.product`
that takes a `StationRun` and returns `{output key: DataFrame}`. A *derived* product
(`@outputs.derived`) takes the run and the tables of all other products and runs after
them; the trend file is the only one. Keys follow the R output
paths, for example `indices/fd_ANN` or `thres/thres`. Products return several tables
because names can depend on parameters (`r30mm`, `rx3day`, `hddheat18`). The registered
products make up the built-in index module, `CLIMPACT_INDICES`. The QC files are not
products: the built-in QC module, `CLIMPACT_QC` (`products/qc.py`), builds them from
`QC_REPORTS` and `na_statistics` (see [Modules and plugins](#modules-and-plugins)).

Table layouts follow R's `write.index.csv`:

| Kind | Columns |
| --- | --- |
| Standard index | `time`, `<index>`, `standardised values (using all years)` |
| Extreme with date | `time`, `val`, `ymd` |
| Spell with dates | `time`, `start`, `duration`, `end` |
| Thresholds (`thres/thres`) | 365 rows, one per day of year: `tmax_q5` ... `tavg_q95`, `prec_q5` ... `prec_q99`, `HW_TN90`, `HW_TX90`, `HW_TAVG90` |
| Day of year (`tx95t_DAY`) | `time` (always missing, see below), `tx95t`, standardised anomaly; 365 rows |
| Heatwave aspect (`TX90-HWM_ANN` ...) | `time`, `<aspect>` (`HWM`, `HWA`, `HWN`, `HWD` or `HWF`); no standardised column (`write.hw.csv`) |
| EHF heatwave aspect (`EHF-HWPS_ANN` ...) | `time`, `<aspect>` (`HWPS`, `HWPI`, `HWLS`, `HWLI`, `HWD`, `HWMD`, `HWN` or `HWF`); no standardised column (`write.hwEHF.csv`) |
| SPI, SPEI (`3month_spi_MON` ...) | `time` (`"YYYY-MM"`), `spi` or `spei`; no standardised column (`write.precindex.csv`) |
| Daily EHF/ECF (`EHFdaily`, `ECFdaily`) | `date` (`YYYY-MM-DD`, every day including 29 February), `Excess Heat Factor` or `Excess Cold Factor`; fields joined by `","` |
| QC lists (`qc/tmaxmin`, `qc/toolarge`) | `Date` (`1961-1-3`), `Prec`, `TX`, `TN` |
| QC duplicates (`qc/duplicates`) | `Dates_duplicated` |
| QC jumps (`qc/tx_jumps`, `qc/tn_jumps`) | `Date`, `TX` (the change) or `TN` (the value) |
| QC flatline (`qc/tx_flatline`, `qc/tn_flatline`) | `Date`, `TX` or `TN`, `Number of duplicates` |
| Trend file (`trend/trend`) | `Index`, `Frequency`, `StartYear`, `EndYear`, `Lower bound`, `Slope`, `Upper bound`; one row per trend R writes (see [Trend file](#trend-file)); fields joined by `","`, missing as `NA` |

`time` is the year (as a number) for annual tables and `"YYYY-MM"` for monthly tables.
The standardised column is `(x - mean) / sd` over all non-missing periods, using the sample
standard deviation; it is missing where the series is constant or has fewer than two values.
As in R, it is computed from the values rounded to 15 significant digits, with R's
extended-precision `mean` and `sd` (see [Numerical precision](#numerical-precision)).

### Writing output files

`climpact.io.output_files.write_outputs(tables, metadata, params, out_dir)` writes the
tables returned by `build_all` the way R does:

- **Paths:** `<out_dir>/<station>/<folder>/<station>_<name>.csv` for key `<folder>/<name>`,
  as in R's `models/outputFolders.R` (`indices/`, `qc/`, `thres/`, `trend/`).
- **Header:** the 7 quoted metadata lines of R's `write_header`
  (`server/climpact.GUI-functions.r`): Description, Station, Latitude, Longitude,
  Base_period, Climpact_version, Date_of_calculation. `Climpact_version` is `3.4.3`
  (`CLIMPACT_VERSION`), the R version whose files are reproduced. `Date_of_calculation` is
  the run date.
- **Descriptions:** index files use the `Definition` column of `climate.indices.csv`
  (copied unchanged into `src/climpact/data/`), and the parameterised definitions that
  `index.calc` builds (`services/calculate_indices.R`) for `r30mm`, `rx3day`, `hddheat18`,
  `wsdi1` and so on, all in `index_descriptions`. The custom index uses `TN > 0`, as in
  `calculate.custom.index`. Heatwave files use `write.hw.csv`'s
  `TX90 heatwave magnitude (HWM)` and so on; the EHF files use `write.hwEHF.csv`'s own
  descriptions (`_EHF_DESCRIPTIONS`). The SPI and SPEI files use the headers
  `calculate.spi` and `calculate.spei` pass, `Standardised Precipitation Index` and
  `Standardised Precipitation-Evapotranspiration Index` (`_PRECINDEX_DESCRIPTIONS`).
  `qc/nastatistics` has an empty description, and the trend file
  `Linear trend statistics` (`index.calc`).
- **Body:** a header row and data rows, unquoted, joined by `", "` (`write.index.csv`) or
  `","` (`write.NA.statistics`, the daily EHF/ECF files and the trend file). Missing values
  (NaN or None) are written as `-99.9`, except in the trend file (`NA`, from `paste`).
  Numbers are formatted by `format_r_number`, a port of R's `formatReal`/`scientific`
  (`src/main/format.c`) with 15 significant digits.
- **All-missing indices:** an index table whose values are missing in every period is not
  written, as in `write.index.csv` (`services/write_indices.R`, line 11). `climpact run`
  lists the files it skipped. The heatwave files are the exception: `write.hw.csv`
  (line 58) writes all ten `TX90-`/`TN90-` files unless every value of all ten is missing,
  so a file that is missing in every year is still written (`_HEATWAVE_FILE`). The
  heatwave product returns no tables in the all-missing case. `write.hwEHF.csv` does the
  same for the eight EHF files and the two daily files, unless HWF is missing in every
  year. `write.precindex.csv` writes all four SPI (or SPEI) files unless every value of
  all four is missing (`_PRECINDEX_FILE`); the drought products return no tables then.
- **`thres/thres`:** R writes it with a plain `write.table` in `quality_control_checks.R`,
  so it has no metadata header and writes missing values as `NA`. A `None` description in
  `_DESCRIPTIONS` means no header, and `_NA_TOKENS` holds the `NA` token.

- **Formats attached by products:** a product can attach a `FileFormat` (description or no
  header, separator, missing-value token, quoted column names, a message for an empty
  table, titled sections) to a table with `with_file_format`; `write_outputs` then uses it instead of the
  rules above. The QC files use it, because their descriptions depend on `QCParams`
  (see [Quality control](#quality-control)).

`write_climpact_csv` (in `climpact.io.climpact_csv`) writes one file and is the inverse of
`read_climpact_csv`, which unquotes quoted column names and returns a line that is a single
quoted string (`"NO DUPLICATE DATES FOUND"`, or a section title such as `"TX up"`) in
`ClimpactTable.messages`. `FileFormat.sections` (`(title, number of rows)` pairs) writes
each title as a quoted line before its rows, also when it has none, as `qc/outliers` does. An output key with
no description or file format is an error, so a new product must add its format in
`output_files.py`, or attach a `FileFormat`, before its files can be written. Tables from
third-party modules must attach a `FileFormat`; the pipeline checks this when the module
returns them.

## Modules and plugins

A run is a pipeline of modules (`climpact.modules`, #28):

```
input (StationRun) -> QC modules -> homogeneity module -> index modules -> write_outputs
```

| Kind | Interface | Built in | Entry point group |
| --- | --- | --- | --- |
| QC | `QCModule.build(run, tables) -> {key: table}` | `climpact`: R's `qc/` files | `climpact.qc` |
| Homogeneity | `HomogeneityModule.homogenise(run, tables) -> HomogeneityResult` | `none`: pass-through | `climpact.homogeneity` |
| Index | `IndexModule.build(run, tables) -> {key: table}` | `climpact`: R's `indices/`, `thres/` and `trend/` files | `climpact.indices` |

The interfaces are `typing.Protocol` classes: a module is any object with a `name` and
the method. `tables` holds the tables of the modules that ran before it, so a homogeneity
module can use the QC results and an index module the earlier indices.

- **QC modules** run on the input data, in the order selected, and must not change it.
- **One homogeneity module** runs. `HomogeneityResult` has `tables` (written like any
  output, for example `homogeneity/breaks` for #34) and `data`: `None`, or the adjusted
  series (#35), a copy of `run.data` with the same time axis and variables. The pipeline
  checks both, restores the station attributes (`first_date`, `last_date`, ...) if the
  module dropped them, and builds a new `StationRun` from the adjusted data, so the
  base-period thresholds are computed from it too. QC tables are never recomputed.
- **Index modules** run on the adjusted run when there is one, else on the input run.
- `run_pipeline` returns a `PipelineResult`: `tables`, `input_run` (the original data, for
  reporting next to adjusted results) and `indices_run`; `adjusted` says whether they
  differ. `build_all(run, modules)` returns the tables only.
- Output keys are `<folder>/<name>`, written to `<out>/<station>/<folder>/` (a module may
  use its own folder, for example `homogeneity/`). A key produced twice is an error.
  Tables from modules other than the built-in ones must carry a `FileFormat`.

**Discovery and selection.** Built-in modules are always available. Third-party modules
are installed packages that declare entry points in the three groups; an entry point
names a module object, or a class called with no arguments, and its name is the module
name. `climpact modules` lists what is available. A run uses the modules in a
`ModuleSelection` (names only, so batch workers can receive it and load the modules
themselves); the default is `qc=("climpact",)`, `homogeneity="none"`,
`indices=("climpact",)`, which writes exactly R's files. Installed plugins run only when
selected, with `--qc NAMES`, `--homogeneity NAME` and `--indices NAMES` on `climpact run`
and `climpact batch` (comma-separated, run in order; leaving out `climpact` drops the
built-in files). An unknown name, or a name installed twice, is an error before any
station runs.

**Example plugin.** `tests/plugins/climpact_example_plugin` is a separate package with its
own `pyproject.toml` and one module of each kind: `example_qc` (`qc/example_hot_days`),
`example_shift` (a break in TX in the middle year, `homogeneity/example_breaks`, and TX
before it raised by 1 °C) and `example_indices` (`indices/example_txmean_ANN`).
`tests/test_modules.py` installs it into a temporary folder on `sys.path` by writing its
`.dist-info` (entry points from its `pyproject.toml`; no build step or network), then
checks that it is discovered, runs through `run_pipeline`, the command line and a
two-process batch, that QC tables come from the original data and the built-in indices
from the adjusted data.

Not yet supported: module options (a module reads `run.params` and `run.qc` or its own
defaults), and trend rows for plugin indices (the trend file covers the built-in indices
only).

## Batch processing

`climpact batch <metadata file> <data dir> --out <dir>` ports Climpact's batch mode
(`climpact.batch.stations.r`, `server/batch_stations.R`). Options: `--base-start`,
`--base-end` (default 1971-2000, applied to every station, as R's command-line
arguments), `--workers` (processes; R's `cores_to_use`), `--custom VAR OP VALUE`, and
`--qc`, `--homogeneity`, `--indices` (see [Modules and plugins](#modules-and-plugins)),
`--plots` (each station's plots, as `climpact run --plots`) and `--zip` (the whole output
folder to `<out>.zip` once every station has finished; see
[Plots and zip archive](#plots-and-zip-archive)).

- **Metadata file** (`read_batch_metadata`): R's format, read unchanged, for example
  Climpact's `www/sample_data/climpact.sample.batch.metadata.txt` (copied to
  `tests/data/`). As R's `read.file.list.metadata` (`read.table(header = TRUE)`): a header
  row (its names are not checked), then one whitespace-separated row per station with 12
  fields: `station_file latitude longitude wsdin csdin Tb_HDD Tb_CDD Tb_GDD rxnday rnnmm
  txtn SPEI`. Blank lines and `#` comments are skipped. The columns map to `wsdi_days`,
  `csdi_days`, `hdd_base`, `cdd_base`, `gdd_base`, `rx_days`, `rnnmm`, `txtn_days` and
  `spei_months`. A row with the wrong number of fields or a non-numeric value stops the
  batch before any station runs, as `read.table` does.
- **Station name:** the file name without its last extension (`strip_file_extension`,
  as R's), so outputs go to `<out>/<station>/` exactly as `climpact run` writes them.
- **Custom index:** R's batch mode calls `climdexInputParams` with empty `var.choice` and
  `op.choice`, so `calculate.custom.index` writes nothing. Python calculates none either,
  unless `--custom` is given (then for every station).
- **Running:** `run_batch` runs each station in a `ProcessPoolExecutor` (spawn start
  method, one process per CPU by default, at most one per station; `--workers 1` runs in
  the main process). Each worker runs `run_station`, the same function as `climpact run`.
  Progress is printed as each station finishes; results are returned in metadata order.
  `--progress` also prints each stage of each station to standard error (see
  [Progress reporting](#progress-reporting)).
- **Failures:** any exception in a station (unreadable file, invalid parameters, a
  calculation error, a crashed worker) is caught and written to
  `<out>/<station>.errors.txt`, R's error log name, and the batch carries on. An error file
  left by an earlier run is removed first, as R does. The command ends with a summary of
  failed stations and their error files.

R behaviour not copied, and why:

| R behaviour | Python |
| --- | --- |
| Outputs go to a folder named after the metadata file without its extension | outputs go to `--out` |
| A station listed in the metadata but not in the data folder is skipped silently | reported as a failure (`station file not found`) with an error file |
| Parameters failing `validate_climdexInputParams` (e.g. `wsdin` outside 1-10) stop the whole batch: the check runs outside the `tryCatch` | the same checks (`validate_params`) fail only that station |
| An index calculation error leaves the files already written for that station | a station is built in full before anything is written, so a failed station has no output folder |
| Two rows with the same station name (e.g. `a.txt`, `a.csv`) both write to the same folder, the last overwriting | rejected when the metadata file is read, since parallel workers would write the same files |
| A file name without an extension gives an empty station name (`strip_file_extension`) | the whole file name is used |
| Exit status 0 even when stations fail | exit status 1 when any station fails |
| QC warnings go to `<station>.warnings.txt`; QC plots and text files are written | the QC files are written with the default `QCParams`; QC plots and warnings are not |
| Values are read with `colClasses` `integer` for `wsdin`, `csdin`, `rxnday`, `SPEI`, and `real` for `txtn` | `txtn` must also be a whole number (it is a day count; `IndexParams.txtn_days` is an `int`) |

**Parity.** `tests/parity/test_batch.py` runs a batch of `sydney`, `nairobi` and a
malformed file through a two-process pool, and checks that every file written for each
reference station is byte-identical to the file `write_outputs` writes for its single run
(same date), with the same set of files, and that the malformed file fails with an error
file while the others succeed. The single-run files are the ones `test_csv_text` checks
against R. `tests/test_batch.py` covers the metadata format, R's sample file, the error
cases and the command line.

## Progress reporting

Station, batch and gridded runs take an optional progress callback (`climpact.progress`,
#72), for the web app's progress pages (#11, #73) and the command line. The default is no
callback: no output changes, and the cost is a counter per stage.

A callback is `progress(stage, step, total)`, called as each step *finishes*: `stage`
names the step just done, `step` counts the steps done (1 to `total`), and `total` is known
before the first call. A run that succeeds ends with `step == total`; a run that fails
stops calling it.

| Function | Stages, in order |
| --- | --- |
| `modules.run_pipeline(run, modules, progress)`, `outputs.build_all(run, modules, progress)` | `qc:<module>` for each QC module, `homogeneity:<module>`, then `indices:<module>` for each index module. A module with a `progress_steps()` method reports its own steps instead (`<kind>:<module>:<step>`); the built-in index module reports each product (`indices:climpact:spi`, ..., `indices:climpact:trend_file`). `modules.pipeline_stages(modules)` lists them. The built-in modules give 20 stages. |
| `batch.run_station(..., progress=)` | `read` (`load_station`), the pipeline's stages, `write` (`write_outputs`): 22 for the built-in modules. With `plots=True`, then one stage per row of `climate.indices.csv` and per custom-index frequency (`plots:fd_ANN`, ..., `plots:hw`, `plots:spei`, ...; `plots.plot_steps(params)`, 90 for the defaults), and with `zip=True` a last `zip`: 113 in all |
| `batch.run_batch(..., progress=)` | a `BatchProgress`, `progress(station, stage, step, total)`: each station's `run_station` stages, with its name |
| `gridded.write_grid_thresholds(..., progress=)` | `rechunk` once per time slab if the input is rechunked first (see [Rechunking](#rechunking-inputs-chunked-by-time-step)), then `thresholds` once per block (this replaces the earlier `progress(done, total)`) |
| `gridded.write_grid_indices(..., progress=)` | `rechunk` once per time slab if rechunked, then `indices` once per block |
| `sector.run_sector_correlation(..., progress=)` | `read`, `correlate`, `write:tmin`, `write:tmax`, `write:t`, `write:above30`, `write:index-sector`, and with `zip=True` a last `zip` (`sector.sector_steps(zip)`): 7 or 8 |

**Batch with several workers.** Callbacks are called only in the process that passed
them, so they need not be picklable. Each worker process gets a `multiprocessing` queue
when it starts (the pool's `initializer`, since a queue cannot be sent with a task) and
puts `(station, stage, step, total)` tuples on it, then an end marker when the station is
done. The parent reads the queue every 0.1 s, in the thread that called `run_batch`, and
handles a finished station's result only after its end marker has arrived, so a station's
stages always reach the callback before its `on_result`; stages of different stations
interleave. Without a callback no queue is made. A station that fails before it is read
(missing file, invalid parameters) reports no stage.

**Cost.** Measured as in [Performance](#performance): the Sydney build (`build_all`, 5
runs each) took 2.50 s median without a callback and 2.46 s with one (20 calls), and
`climpact batch` on Climpact's two sample stations with `--workers 2` took 7.4 s with or
without `--progress` (3 runs each). A first version used a `multiprocessing` manager queue,
which added about 1.7 s to that batch: the manager is one more spawned process, which
imports the command line's modules again.

**Plugin modules** need not report progress: one stage per module. To report finer
steps, a module adds `progress_steps()` (the names of its steps) and accepts a keyword
argument `progress` in `build` (or `homogenise`), a callable it calls with each step's name
as it finishes. The pipeline passes it only when a callback was given.

**Command line.** `climpact run --progress` and `climpact batch --progress` print
`[step/total] stage` (prefixed by the station name in a batch) to standard error, so
standard output and the files written are unchanged, as does `climpact sector-correlation
--progress`. `climpact gridded-thresholds` and `climpact gridded-indices` print
`[done/total] time slabs rechunked` and `[done/total] blocks done`, unless `--quiet`.

`tests/test_progress.py` checks that every stage arrives once, in order, numbered 1 to
`total`, for the pipeline (built-in and plugin modules), a single station, a batch in one
process and in two worker processes (stages before each station's result), the gridded
thresholds and the command line, and that the files written with and without a callback
are byte-identical.

## Plots and zip archive

`climpact.plots` draws the plots R draws in `index.calc` (`services/calculate_indices.R`,
`plot.call` and `plot.hw` in `services/plot_indices.R`, `plot.precindex` in
`services/plot_prec_index.R`) and zips the outputs as `services/zipFiles.R`. matplotlib is
an optional dependency (`pip install climpactpy[plots]`; it is in `dev` too). It is imported
only when plots are drawn, on an Agg canvas without `pyplot`, so a caller's matplotlib
backend is never changed. `climpact run --plots --zip` and `climpact batch --plots --zip`
use it; `run_station(..., plots=True, zip=True)` and `run_batch(...)` take the same flags,
and `--plots` without matplotlib is a command-line error before the run starts.

**Files.** `write_plots(tables, metadata, params, out_dir)` writes, from a run's tables:

- `<out>/<station>/plots/<station>_<name>.png`, one per plotted series. `<name>` is the
  index file's (`fd_ANN`, `txx_MON`, `tx95t_DAY`, `TX90-HWM_ANN`, `EHF-HWLI_ANN`,
  `3month_spi_MON`, `TNgt0_ANN`, ...), or `day_of_<name>` for the calendar day of the
  indices with dates (`exact_date_indices`) other than cwd, cdd and gsl: day of the year
  for annual values, of the month for monthly ones, from the `ymd` column.
- `<out>/<station>/plots/<station>_all_plots.pdf`, every plot as a page, in R's order (the
  rows of `climate.indices.csv`, a series' `day_of_` plot after it, the custom index last).

A series is plotted when its table exists and the plotted column (`val`, `duration` or
`sl` for the indices with dates, otherwise the index; the trend file's `_value_column`) is
not missing throughout, as `plot.call` skips such a series. This gives exactly R's file
list: for `sydney` and `lat0`, the only reference runs whose plots are kept, R's 127
names (126 PNGs and the PDF) are committed in `reference/output/<run>/plot-files.txt`
(written by `run_r_reference.sh`), and `tests/parity/test_plots.py` checks the plots
Python draws, and the files `write_plots` writes for Sydney, against them. The other runs'
R plots are not kept locally, so their names are not checked. The plots are compared with
R's by eye, not pixel by pixel. `tests/test_plots.py` covers the p-value (`ALNORM` against
the normal distribution, ties, missing values, the cases `TAUK2` leaves at 1), the
intercept, which plots a set of tables gives, the text under a plot, the progress stages,
the zip layouts and the command-line flags.

**What each plot shows** is what R's show: the station name and coordinates, the index
definition (R's subtitle: `<name>: <definition>`, the heatwave and EHF descriptions of
`plot.hw` and `calculate.hwEHF`, `<scale>-month spi: <definition>`, `Number of days where
TN > 0` for the custom index), the units, the values, the missing periods, the Sen's slope
trend line, and the slope with its 95% bounds and the Mann-Kendall p-value, or R's "no
linear trend" message when `min_trend_data` fails. tx95t and the `day_of_` plots have no
trend, as R passes `opt = 0` or `calculate_trends = FALSE` for them. SPI and SPEI are bars,
blue above zero and orange below (R: blue and red); the others are lines with markers
(R's `type = "b"`).

**The trend** is `trends.plot_trend`: the slope and bounds are the trend file's
(`sen_trend`), so the plot and `trend/trend` agree. The intercept is `zyp.sen`'s, the
median of `y - slope x` over the values present, with `x` counted from 0 at the first
period. The p-value is `MannKendall(y)$sl` (Kendall 2.2.2), `trends.mann_kendall_p`: the
values present, `x = 1, 2, ...`, `S` and `Var(S)` in single precision as Fortran `TAUK2`,
and the normal approximation with a continuity correction, `z = (S -+ 1) / sqrt(Var(S))`,
`p = 2 min(Phi(z), 1 - Phi(z))`, with `Phi` from algorithm AS 66 (`ALNORM`) evaluated in
double precision. `TAUK2`'s exact method for small untied samples is never reached: its
"no ties" flag is true only for a constant series, which returns earlier with p = 1. The
Sydney plots show the p-values R prints (txx_ANN 0.819, txx_MON 0.282, 3-month SPEI
0.873).

**Zip archives.** `zip_station(out, station)` writes `<out>/<station>.zip` from the
station folder, as R's single-station download (`singleStationStep3.R`: the station folder
zipped into its parent as `<station>.zip`, leaving out `*.zip`): entries `indices/...`,
`plots/...`, `qc/...` relative to the station folder, with folder entries, as `zip -r`
writes them. `zip_batch(out)` writes `<out>.zip` next to the batch folder, with entries
`<station>/...` and the error files, as R's batch download (`batchStep1.R`). Entries are
sorted; CSV files are deflated at level 9 (R's `zip -9`), PNG and PDF files, compressed
already, are stored.

**Differences from R's plots** (deliberate; the information is the same):

| R | Python |
| --- | --- |
| 800 x 600 PNG; title `Station: <name> [-33.86°S, 151.21°E]`, the definition in small type | 1200 x 750 PNG (a 128-colour palette); the station line `<name>  ·  33.86°S, 151.21°E` (no minus sign before S or W), the definition as the bold title, wrapped |
| y label is the raw unit (`degrees_C`) | `°C`, `°C²`; `unitless` is left blank |
| Missing values: blue triangles at the bottom of the plot; the line is broken | a grey tick at the bottom of the axes per missing period, and a legend entry with the count; the line is broken |
| `Sen's slope = 0.001 lower bound = -0.001, upper bound = 0.002, p-value = 0.282`, rounded to 3 decimals (so small slopes print as 0) | `Sen's slope 0.001 °C per month (95% CI -0.001 to 0.002), Mann-Kendall p = 0.282`: the unit and time step, 3 decimals, or 3 significant digits below 0.0005 (`2.09e-5`), `p < 0.001` |
| The trend line is `abline(intercept, slope)` on axis positions that are not the fit's `x`: periods are at 1, 2, ... on the axis but 0, 1, ... in the fit, so the line is one period early; SPI/SPEI bars are centred at 0.5, 1.5, ... but fitted on 1, 2, ..., so half a period late | the line passes through `intercept + slope x` at each period's own position |
| When `min_trend_data` passes but `confint.zyp` fails, R prints `Sen's slope = NA ...` | the "no linear trend" message |
| No legend, no gridlines, a box around the plot | a legend (trend line, missing count, wet/dry for SPI/SPEI), light gridlines, no top or right axis line |
| PDF pages 11.5 x 8 in, with R's fonts embedded | 10 x 6.25 in pages (the PNG layout) in Helvetica, one of the standard PDF fonts, not embedded |
| A warning while plotting (`tryCatch(..., warning = ...)` in `index.calc`) skips the rest of that index's plots | every plot is drawn |
| `plot.precindex` loops over `c(3, 6, 12, custom)`, so a custom SPI/SPEI scale of 3, 6 or 12 months draws that PNG twice (the second overwrites the first) and adds a second PDF page | drawn once |

**Speed.** One figure is reused for every PNG and one for every PDF page: their artists
are created once and each plot only updates data and text. Measured on the Sydney tables
(Apple M-series): 126 PNGs and the 126-page PDF in 5.4-5.7 s, PNGs about 60% of it. A
figure per plot took 13 s. Unhinted text (PNG), the 128-colour PNG palette and the
standard PDF font (no embedding) each saved about 1 s. The PNGs total 6.8 MB (R's 13 MB),
the PDF 0.8 MB. Zipping the Sydney folder takes about 0.5 s. Plots are drawn in the
station's own process: a worker process would cost more than it saves, as importing
`climpact` imports xclim (about 2 s).

## Sector correlation

`climpact.sector` ports step 4 of the R app: `draw.correlation` and
`create.correlation.plots` in `server/sector_correlation.R`, called by
`modules/singleStationStep4.R` after the indices are calculated (#84; the web step is #90).
The user gives a CSV file of annual sector data, a header row and then `Year,<value>` per
year (Climpact's sample is `www/sample_data/wheat_yield_nsw_1922-1999.csv`, copied to
`reference/input/sector/`), a plot title (default: the station name), a y-axis label
(default: the file name up to its first `_` or `.`) and whether to detrend (default: yes).

| Function | Does |
| --- | --- |
| `read_sector_file(path)` | reads the file as `read.csv`: the header through `make.names` (`r_make_names`: `Wheat yield (t/ha)` becomes `Wheat.yield..t.ha.`), `-99.9`, `NA` and empty as missing. Returns a `SectorData` (`years`, `values`, `column`) |
| `sector_correlation(rows, index_tables, sector, station, detrend_sector)` | the calculation, in memory. `rows` are the station's daily rows as R's `read_user_file` reads them (`io.station.read_station_rows`), `index_tables` a run's tables keyed `indices/<name>_ANN` (from `build_all`, or read back by `read_index_tables`). Returns a `SectorCorrelation`: the four scatter tables with their regressions and the correlation table |
| `write_sector_correlation(result, folder, title, y_label, plots)` | writes the files below to `folder` (R's `corr/`), with `write_r_csv` (R's `write.csv`) |
| `run_sector_correlation(station_file, sector_file, out_dir, station, ..., index_tables=None, plots, zip, progress)` | the hook called after a run, by `climpact sector-correlation` and the web app: reads the station file and the index CSV files in `<out_dir>/<station>/indices/` (or uses `index_tables`, a run's tables in memory), writes to `<out_dir>/<station>/corr/` and, with `zip`, zips that folder to `<out_dir>/<station>_corr.zip`, as R's `zipFiles(corrdir, destinationFolder = baseFolder)` |

Files, with `<part>` the sector column name lower-cased and cut at its first `..`
(`wheat.yield`, or `detrended.wheat.yield` when detrended), as R's `sector.data.fileparts`:

| File | Content |
| --- | --- |
| `<station>_corr_{tmin,tmax,t,above30}_<part>.csv` | `"year"`, the temperature summary (`avg_tmin`, `avg_tmax`, `avg_t`, `above30`) and the sector series, per year the station and the sector data have in common |
| `<station>_index-sector_correlation_<part>.csv` | `"indice","cor","category"`: the correlation of the sector series with each index found, rounded to 2 decimals |
| the same names with `.png` | with `plots=True` (`--plots`): the four scatter plots with their regression line, equation and R², and the bar chart, drawn in the style of [Plots and zip archive](#plots-and-zip-archive) (R draws them with ggplot2; content the same, look different) |

R's behaviour reproduced (each covered by `tests/test_sector.py` where the reference run
does not show it):

- The temperature summaries come from the **raw station file**, not the QC'd data:
  `avg_tmax`, `avg_tmin` are yearly means of the values present, `avg_t` is the mean of
  every TX and TN value of the year pooled (`mean(c(tmax, tmin))`, not the mean of the
  two means), `above30` counts days with TX > 30. Means use R's `mean` (`r_mean`).
- At least 10 years in common between the station file and the sector data, counting
  years whose sector value is missing, or R's error "not able to make a correlation,
  since there is no data in common!" (`SectorCorrelationError`). The same error when an
  index has no year in common.
- **Detrending** (`detrend`, R's `calculateDeTrendValues`) is done on the whole sector
  file before it is cut to the station's years: each value minus the `lm` slope times its
  distance from the middle row, counted in **rows, not years**, from row `(n + 1) / 2`
  when `n` is odd and `(n + 2) / 2` when even. Rows with a missing value are left out of
  the slope and stay missing.
- The indices correlated are R's fixed list of 42 file names (`SECTOR_INDICES`), in its
  order, with its categories. A file R did not write (all missing) is skipped, and so is
  an index written under another name: with base temperatures other than 18/18/10 the
  degree-day indices (`hddheat18` ...), and `tx2tn2`/`txb2tnb2` with another `txtn_days`,
  are left out; `wsdi` and `csdi` are the plain ones, not `wsdi<d>`. The value column is
  `val`, `duration` or `sl` for the indices with dates (`exact_date_indices`).
- R reads the indices back from their CSV files, so the values are the 15-digit written
  ones and **a missing value is correlated as the number -99.9**. On Sydney this
  dominates many correlations (fd, which is 0 in every year it has, correlates at -0.25
  through its missing years). `_as_written` reproduces this for tables in memory.
- `cor` without `use =`: missing values give `NA`, as does an index with no variation.
  Which correlation is taken, and the `<part>` of the file names, depend on whether the
  column name contains `Detrended`, as R's `grepl("Detrended", sectorCol)`.

Differences from R are listed under [Sector correlation](#sector-correlation-1) in the
differences section.

## Missing data

climdex.pcic, and therefore Climpact, marks a period's index value as missing when:

- **monthly**: more than 3 days of the month are missing;
- **annual**: more than 15 days of the year are missing, **or** any month of the year is
  missing under the monthly rule.

None of xclim's built-in missing methods implement this, so `climpact.missing` provides it
and registers it with xclim as the `"climdex"` method. Any xclim indicator can use it:

```python
with xclim.set_options(check_missing="climdex"):
    fd = xclim.atmos.frost_days(tasmin=ds.tasmin, freq="YS")
```

`valid_mask(*arrays, freq=...)` combines several variables, like climdex's per-variable
`namask` multiplied together.

For a single series (a station) the rules are computed with `climpact.periods` (integer
period codes and `numpy.bincount`); DataArrays with more dimensions use xarray's
`resample`. `tests/test_periods.py` checks the two give the same mask.
`valid_periods(present, time, freq)` applies the rules to a numpy array with any leading
dimensions (the index functions and the gridded indices use it), also with
`climpact.periods`. The masks are cheap enough
(about 1 ms) that they are recomputed for each index rather than cached.

## Monthly and annual reductions

xarray's `resample` without the optional flox package reduces each period through its own
xarray objects, about 0.1 ms per month. With 960 months per station and hundreds of
reductions per run, this was most of a station run's time (see [Performance](#performance)).
`climpact.periods` groups a 1-D daily series by integer period codes instead
(`periods(time, "MS" | "YS")`), and gives the same periods and labels as
`resample(time=rule)`: every month or year from the first date's period to the last
date's, including empty ones. `Periods.count`, `Periods.days` and `Periods.reduce`
(`"max"`, `"min"`) give integer counts and exact extremes; `Periods.apply` calls a
function, usually `r_mean` or `r_sum`, on each period's non-missing values in date order.
No floating-point sums are done there, so results are identical to `resample`'s
(`tests/test_periods.py`). `Periods.first_extreme` gives the position of each period's
first maximum or minimum (R `which.max`), for the dates of the extremes. Every method
works along the last axis of an array with any leading dimensions (the cells of a grid
block); `Periods.apply` then calls the function once per period and leading index.
`missing.valid_periods` is the climdex validity of such an array
(`tests/test_gridded_indices.py` checks both against one series at a time).

## Base-period thresholds

`climpact.thresholds` computes every base-period threshold Climpact uses, once per
station. `StationRun.thresholds` computes them on first use and caches them
(`compute_thresholds`), so all percentile indices share one computation (about 20 ms).

| Threshold | R source | Python |
| --- | --- | --- |
| TX, TN, TM q5, q10, q50, q90, q95, 5-day window | climdex.pcic `get.outofbase.quantiles` / `zhang.running.qtile`, C++ `running_quantile_windowed` | `Thresholds.temperature[var][q]` (365 values) |
| TX, TN q10, q50, q90 inside the base period (Zhang et al. 2005 bootstrap) | climdex.pcic `zhang.running.qtile(get.bootstrap.data = TRUE)`, C++ `running_quantile_windowed_bootstrap` | `Thresholds.inbase(var, q)` (365 × years × (years − 1) values) |
| TX, TN, TM q90, 15-day window (`HW_TX90`, `HW_TN90`, `HW_TAVG90`) | Climpact `quality_control_checks.R`, `get.outofbase.quantiles(n = 15)` | `Thresholds.heatwave[var]` |
| TAVG q95 and q5 over all base-period days, and q85 of the positive base-period EHF (one number each, type 7) | Climpact `climdex.hwEHF`, R `quantile` | computed in `products/ehf.py` with `r_quantile_type7` (see [EHF heatwaves](#ehf-heatwaves-and-the-daily-ehfecf-series)) |
| Wet-day (≥ 1 mm) precipitation q5, q10, q50, q90, q95, q99 | climdex.pcic `get.prec.var.quantiles`, R `quantile(type = 8)` | `Thresholds.precipitation[q]` (a number) |

`var` is `tasmax`, `tasmin` or `tas`. For index code:

- `Thresholds.daily(var, q, time)` gives the threshold for each date of a series, using
  climdex's day-of-year mapping (`day_of_year`: 29 February takes 28 February's
  threshold, later days of a leap year shift back by one).
- `Thresholds.base[var]` is the `(years, 365)` base-period matrix the temperature
  thresholds came from, and `window_values` returns the `(365, years, window)` window
  values.
- `Thresholds.inbase(var, q)` gives the bootstrapped thresholds used inside the base
  period, a `(365, years, years - 1)` array, computed on first use and cached (see
  [In-base bootstrap](#in-base-bootstrap)). The quantiles a variable needs in the base
  period (`INBASE_QUANTILES`: TX q10, q50, q90; TN q10, q90) are computed together,
  since they share each day's sorting and weights (about 25% faster than one at a time,
  and identical). `bootstrap_quantiles` accepts leading dimensions (one cell at a time
  inside: the per-day work is already vectorised over the year pairs and limited by
  memory, so taking cells together was slower).
- `climdex_quantile_sorted` is climdex's C++ quantile, vectorised over the rows of a
  sorted matrix. `r_quantile_type8_rows` and `r_quantile_type7_rows` are R's
  `quantile(type = 8)` and `quantile()` along the last axis; the per-series
  `r_quantile_type8` and `r_quantile_type7` call them.
- `running_quantiles`, `window_values`, `base_period_array` and `wet_day_quantiles`
  accept any leading dimensions, so a block of grid cells is computed with the station
  code in one call (`tests/test_thresholds.py` checks cells together against one at a
  time).
- When the station's dates cover 359 days of the base period or fewer,
  `compute_thresholds` raises `InsufficientBaseData` (climdex.pcic refuses to compute
  thresholds in that case), and the threshold and percentile index products produce no
  tables.

Both quantile functions are checked bit for bit against values printed by R 4.6.1 and
climdex.pcic (`tests/data/r_quantiles.txt`, made with the `reference/r` Docker image).

## Gridded data

`climpact gridded-thresholds <files> --out <file>` ports Climpact's
`climpact.ncdf.thresholds.wrapper.r`, which calls `create.thresholds.from.file` in
Climpact's own modified climdex.pcic.ncdf 0.5-4 (`server/pcic_packages/climdex.pcic.ncdf/R/ncdf.R`).
Options follow the wrapper's settings: input files (one to three), `--tmax`, `--tmin`,
`--prec` (variable names, default `tasmax`, `tasmin`, `pr`), `--base-start`, `--base-end`,
`--institution`, `--institution-id` (R's `author.data`), `--workers` (R's `cores`),
`--max-values` (R's `max.vals.millions`, default 5), and `--rechunk` (`auto`, `yes`,
`no`) and `--tmp-dir`, which R does not have (see
[Rechunking](#rechunking-inputs-chunked-by-time-step)). R's wrapper always uses
`fclimdex.compatible = FALSE`, which only affects the in-base bootstrap, not used here.

```
netCDF files
  -> gridded.io.open_grid          GriddedInput: tasmax, tasmin (degrees C), pr (kg m-2 d-1),
                                   float64 dask arrays (time, y, x), chunked in blocks of cells
  -> gridded.thresholds.write_grid_thresholds
       create_thresholds_file      dimensions, coordinates, attributes (create.thresholds.file)
       per block: GriddedInput.load(block)          one read per block, in the main thread
                  block_thresholds -> cell_thresholds   batches of cells, on worker threads
                  _write_block                      written before the next block is read
```

**Reading** (`gridded/io.py`), as `create.file.metadata` and `get.data`:

- Each variable must be in exactly one file and have time, Y and X dimensions (found
  from `axis`, `standard_name` or the dimension name); the files must share their time axis
  (truncated to days). The standard, `noleap` (`365_day`) and `360_day` calendars are
  supported (see [Non-standard calendars](#non-standard-calendars)); others (`all_leap`,
  `julian`) raise `NotImplementedError`, as PCICt does not know them.
- Missing values as ncdf4's `ncvar_get`: the `missing_value` attribute, else `_FillValue`,
  else 1e30 for float types; float values within `1e-5 * |missing value|` of it are missing
  (`1e-10` when it is 0), integers only when equal. Then `value * scale_factor + add_offset`
  (`decode_ncdf4`).
- Units as udunits2's `ud.convert`, which checked in the image computes exactly `value -
  273.15` for K to degrees C and `value * 86400` for kg m-2 s-1 to kg m-2 d-1
  (`unit_conversion`). Every value is converted to float64 first, as R reads doubles.
- Blocks are whole Y rows (or parts of a row) with at most `max_values` values of the
  three variables, like R's stripes (`axis.to.split.on = "Y"`). They are the dask chunks of
  `GriddedInput.data`, opened with those chunks so that a block reads only its cells.
- Files chunked by time step over the whole grid are rechunked to a temporary file first
  (see [Rechunking](#rechunking-inputs-chunked-by-time-step)); `--rechunk` and
  `--tmp-dir` control it.
- `GriddedInput.cell_latitude()` gives each cell's latitude, from the Y coordinate or a
  two-dimensional latitude variable, for the hemisphere rules of the gridded indices (see
  [Gridded indices](#gridded-indices)).

**Thresholds** (`cell_thresholds`), as `get.quantiles.for.stripe`, for a block of cells
at once: each series is padded to whole years (`create.filled.series`), TAVG is
`(TX + TN) / 2`, and

| Variable | Dimensions | Computed with |
| --- | --- | --- |
| `tx05thresh` ... `tx95thresh`, `tn05thresh` ... `tn95thresh` | time (365, or `dpy`), lat, lon | `running_quantiles`, 5-day window (the station `thres/thres` columns) |
| `tx90thresh_15days`, `tn90thresh_15days`, `tavg90thresh_15days` | time, lat, lon | `running_quantiles`, 15-day window (`HW_TX90`, `HW_TN90`, `HW_TAVG90`) |
| `tavg05thresh`, `tavg95thresh` | lat, lon | `r_quantile_type7_rows` over every base-period day (the station EHF's T05, T95) |
| `ehf85thresh` | lat, lon | `excess_factors` (`calculate_EHF` is the station EHF formula), then the type-7 85th percentile of the positive base-period EHF |
| `r95thresh`, `r99thresh` | lat, lon | `wet_day_quantiles` (`get.prec.var.quantiles`) |
| `txraw`, `tnraw`, `precraw` | base_time, lat, lon | the base-period data, 29 February included, for the gridded SPI and SPEI |

`calculate_EHF` has no 50% base-period check, unlike the station EHF, so every cell gets
an `ehf85thresh` unless it has no positive base-period EHF. With 359 days of the base
period or fewer in the time axis, R stops; Python raises `InsufficientBaseData` and writes
nothing.

**Writing** (`create_thresholds_file`): the 21 variables above in R's order, as float64 with
`_FillValue` 1e20 and `units`, `long_name`, `history`, `base_period`; dimensions `bnds`,
`time` (unlimited, 365 days (`dpy` in other calendars) of the middle base year, `floor(mean(base))`), the X and Y
dimensions of the input, and `base_time` (unlimited, every base-period day); `time` with
the input time's attributes and `time_bnds` (first and last base year, named by the input
time's `bounds` attribute); X and Y as float64 with the input's attributes; the exemplar
file's (the TX file's) global attributes plus R's `put.ETCCDI.atts`. The file is netCDF4,
compressed, chunked by blocks, and renamed into place when complete.

**Memory and speed.** One block is read (default 5 million values, 40 MB as float64), its
cells are computed in batches of 8 (`cells_per_batch`, about 10 MB of working memory per
cell for 60 years) by `--workers` threads, and the results are written before the next
block is read. The output variables get a 1 MB HDF5 chunk cache each (`OUTPUT_CHUNK_CACHE`):
with HDF5's default of 64 MB each, written chunks of the 21 variables would stay cached.
`tests/test_gridded.py` checks that the memory numpy allocates (tracemalloc) for a grid 16
times larger, with the same block size, stays within 1.5 times that of the small grid. The
input files' read cache is netCDF-C's default (64 MB per variable). See
[Performance](#performance) for timings.

### Gridded indices

`climpact gridded-indices <files> --out <dir>` ports Climpact's `climpact.ncdf.wrapper.r`,
which calls `create.indices.from.files` in the same modified climdex.pcic.ncdf. Options
follow the wrapper's settings: input files and variable names as for the thresholds,
`--template` (R's `file.template`, the CMIP5-style name the outputs follow; default
`var_daily_climpactpy_historical_NA_<first year>-<last year>.nc`), `--base-start`,
`--base-end`, `--indices` (R's `indices`, by short name: `fd`, `rxdday`, `wsdid`, ...),
`--thresholds` (R's `thresholds.files`, a file from `climpact gridded-thresholds`),
`--institution`, `--institution-id`, `--workers` (`cores`), `--max-values`
(`maxvals`), `--rechunk`, `--tmp-dir` (as for the thresholds) and the wrapper's
"esoteric" index parameters with its values
(`WRAPPER_PARAMS`: `--wsdi-days`, `--csdi-days` 5, `--rx-days` 7, `--txtn-days` 3,
`--hdd-base`, `--cdd-base` 18, `--gdd-base` 10, `--rnnmm` 30). `EHF_DEF` is always
`NF13`, the only definition `climdex.hwEHF` accepts.

R computes every cell as a station: `climdexInput.raw` and the index functions of
`climpact.etsci-functions.r`. So `gridded/indices.py` computes them with the station code:
the index products' array functions (`count_values`, `means_and_totals_values`,
`extreme_values`, `rxnday_values`, `spell_length_max_values`,
`precipitation_percentile_values`, `days_op_threshold_values`, `percent_days_values`,
`spell_duration_values`, `gsl_values`, `degree_day_values`) take `(cells, time)` arrays,
and the station products call the same functions with one series. The heatwaves call the
station's `heatwave_flags`, `hw_aspects`, `excess_factors` and `annual_aspects` one cell at
a time (`gridded/heatwaves.py`), so the Tx90/Tn90 behaviour not copied from R (#51, see
[Heatwaves](#heatwaves-tx90-tn90)) applies to grids too; no cell of the reference grids is
affected; SPI and SPEI have their own port (`gridded/drought.py`,
see [Gridded SPI and SPEI](#gridded-spi-and-spei)), because R's gridded code does not run
the station app's `cspei`. `cell_indices` computes the heatwave, SPI and SPEI files only
when they are requested (`SEPARATE`); the other 84 are always computed. Counts, masks, extremes
and their dates, and the daily comparisons with the thresholds are vectorised over the
cells; R's extended-precision sums, the running sums of Rx{n}day, spells and the growing
season are computed one series at a time inside those functions. The thresholds of a block
are computed as for a station (`compute_block_thresholds`: `running_quantiles`,
`wet_day_quantiles` and the in-base bootstrap), or read from the thresholds file.

```
netCDF files
  -> gridded.io.open_grid           as for the thresholds; the exemplar is the precipitation
                                    file (the wrapper's variable map lists prec first)
  -> gridded.indices.write_grid_indices
       create_index_file            one file per index and frequency (create.ncdf.output.files)
       per block: GriddedInput.load(block), thresholds file block if given
                  block_indices -> cell_indices   batches of cells, on worker threads
                  _write_block                    every file, before the next block is read
```

**What R writes.** For TX, TN and precipitation, `get.climdex.variable.list` gives 88
files, in its order (`index_files`): one per index and frequency, `MON` and `ANN`, `ANN`
only for the spell, degree-day, rNNp, gsl, wsdi/csdi, tx{n}tn{n} indices, sdii, cdd and
cwd, `MON` only for SPI and SPEI, and `DAY` for tx95t. Parameterised indices are named
with their values (`rx7day`, `r30mm`, `wsdi5`, `csdi5`, `tx3tn3`, `txb3tnb3`, `hddheat18`,
`cddcold18`, `gddgrow10`) and their `definition` attribute is rewritten as R does. All 88
are ported. Station outputs the gridded code does not have: the custom index, Rx3day (the
wrapper's `rxnday_n` is 7), the thresholds and trend files, the daily EHF/ECF series, the
SPI/SPEI custom scale, the QC files and plots.

**Per cell, as R:**

| Rule | R source | Python |
| --- | --- | --- |
| Northern Hemisphere when the cell's latitude is >= 0 (the station app: > 0); gsl and the Tx90/Tn90 heatwave season depend on it | `get.northern.hemisphere.booleans` (`y.subset.vals >= 0`) | `cell_indices(latitude)`, `gsl_values(northern)`, `hw_values(northern)` |
| SPEI's PET uses the cell's latitude (the Y coordinate, or the 2-D latitude) | `compute.indices.for.stripe` (`lat = y.subset.vals[x]`), `spei.opts$lat` | `spei_values(latitude)` |
| A cell whose TX, TN and precipitation are all missing gets no index (every value missing, also counts) | `compute.indices.for.stripe`'s fast path | `cell_indices` |
| Thresholds from a file: the out-of-base thresholds for every year, no in-base bootstrap; only for data with no day in the base period, else R stops (`check.quantile.validity`: "Temperature in-base quantiles must contain 10th and 90th percentiles") | `get.thresholds.chunk`, `get.quantiles.object`, `climdexInput.raw` | `thresholds_from_file`, `check_thresholds_file` (raises `ValueError`) |
| With a thresholds file, `hw` uses its `tx90thresh_15days`/`tn90thresh_15days` (`q90_15days`) instead of recomputing them; `hwEHF` its `tavg95thresh`, `tavg05thresh` and `ehf85thresh`, and then skips the 50% base-period check; SPI and SPEI fit `precraw` (and `txraw`, `tnraw`) followed by the data (`computefuture`) | `climdex.hw`, `climdex.hwEHF`, `climdex.spi`, `climdex.spei` | `hw_values`, `hwehf_values`, `spi_values(raw)`, `spei_values(raw)` |
| A cell with TAVG on less than half of the base period (and no thresholds file) gets no EHF heatwaves. R prints "NOT CALCULATING EHF HEATWAVES ..." and `climdex.hwEHF` returns `NULL`, after which `write.climdex.results` stops (see [Gridded data](#gridded-data-1)) | `climdex.hwEHF` | `hwehf_values` (missing values) |
| Values are stored as float32 | `ncvar_def` (default `prec = "float"`) | `create_index_file` |
| R's `NaN` is stored as NaN, its `NA` as the fill value 1e20. `NaN` occurs where a mean has no values and its mask is the annual climdex mask: tmm, txm, tnm `ANN` for a year with no data (`NaN * NA` is `NaN` with that mask, which `prod` builds; with the monthly mask it is `NA`), and r95ptot, r99ptot for a year with no wet day (`0 / 0`) | `climdex.tmm` ..., `climdex.r95ptot` | `IndexResult.nan`, `_write_block` |
| The extremes (txx, tnn, tnx, txn, rx1day, rx5day, rx{n}day) also get `day_of_<index>`: the day of the month (`MON`) or of the year (`ANN`) of the first extreme, missing with the value; cdd, cwd and gsl get no dates | `write.climdex.results` (`exact_date_indices`) | `IndexResult.day` |
| The heatwave, SPI and SPEI values have no `NaN`: R's `NaN` and infinite values become `NA` (fill value), except EHF-HWPS, which is `-Inf` in a year with heatwaves when the cell has no EHF85 (the severities are all `NA` and `max(na.rm = TRUE)` is `-Inf`; EHF-HWLS is then 0) | `get.hw.aspects`, `climdex.hwEHF`, `climdex.spi`/`climdex.spei` | `annual_aspects`, `_write_block` |

**Writing** (`create_index_file`), as `create.ncdf.output.files`: dimensions `bnds` (or the
input time bounds' own dimension, `nb2` in Climpact's sample), `time` (unlimited), X and Y;
variables `time` (the middle of each month or year, in `days since <origin>` with the
origin's date only, and the input time's attributes), its bounds (first and last day of
each period, named by the input time's `bounds` attribute), X and Y (float64, the input's
attributes) and the index (float32, fill value 1e20) with `units`, `long_name`, the
attributes of the input precipitation variable that R does not exclude, `definition` and
`expert_team`. Three files differ (`IndexFile.variables`, `IndexFile.scaled`): `hw_ANN`
holds ten variables, `hwm_tx90`, `hwm_tn90`, `hwa_tx90`, ... `hwf_tn90` (`HW_VARIABLES`),
and `hwEHF_ANN` eight, `EHF-HWMD`, `EHF-HWD`, `EHF-HWPS`, `EHF-HWPI`, `EHF-HWLS`,
`EHF-HWLI`, `EHF-HWN`, `EHF-HWF` (`EHF_VARIABLES`), each with its own `units` and
`long_name`, `expert_team` `ETSCI`, and no `definition` or copied input attributes;
`spi_MON` and `spei_MON` have a fourth dimension `scale` (length 3, an int coordinate
variable 1-3 with `units` `3,6,12 months`), and their variable is `(scale, time, Y, X)`. tx95t has a fixed `time` dimension of 365 calendar days (360 in the `360_day`
calendar; int32, values 1 to 365 or 360, no bounds variable although the copied `bounds` attribute names one). Global
attributes: the precipitation file's, with `title`, `frequency`, `creation_date` and
`tracking_id` renamed `input_*`, then `put.ETCCDI.atts` (`index_calculation_frequency` is
`mon`, `yr` or `NA` for tx95t). The files are netCDF4, compressed, chunked by block,
written under temporary names and renamed when all are complete.

**Memory and speed.** As for the thresholds: one block is read and its cells computed in
batches of 8 (`DEFAULT_CELLS_PER_BATCH`) by `--workers` threads, and every file is written
before the next block is read. Each of the 88 open files' variables has a 1 MB HDF5 chunk
cache. `tests/test_gridded_indices.py` checks that the memory numpy allocates for a grid 16
times larger, with the same block size, stays within 1.5 times that of the small grid.
The means of the gridded indices (tmm, txm, tnm, dtr and the percentage indices) use a
vectorised mean that is only guaranteed to round to the same float32 as R's
extended-precision mean (`period_means(float32=True)`), falling back to `r_mean` near a
float32 rounding boundary (see [Numerical precision](#numerical-precision)). See
[Performance](#performance) for timings.

### Gridded SPI and SPEI

R's gridded code computes SPI and SPEI with `climdex.spi` and `climdex.spei`
(`climpact.etsci-functions.r`, lines 405 and 543), which call the SPEI package's own
`spi()`/`spei()` (SPEI 1.8.1, in the reference image), not the station app's `cspei` (see
[SPI and SPEI](#spi-and-spei)). The two give different values. Ported in
`gridded/drought.py`, scales 3, 6 and 12 only:

| Step | Station (`cspei`, `products/drought.py`) | Gridded (`spei()`, `gridded/drought.py`) |
| --- | --- | --- |
| Monthly precipitation with no data | missing | SPI: 0 (`tapply.fast(..., sum, na.rm = TRUE)`); SPEI: missing (`monthly_inputs`) |
| Accumulation | mean of the last `scale` months | sum (`rollapply` with `kern(scale) * scale`, all weights 1; `accumulate_sum`) |
| Reference window | accumulated again inside the window | cut from the accumulated series, so the first base months keep the accumulation from before the base period |
| PWMs and fit | lmomco `pwm.ub`, `parglo`; SPI `pargam(lmom.ub)` on all values | TLMoments `PWM` (`tl_pwm`, its C++ loop), lmomco `pwm2lmom`/`are.lmom.valid`, lmom's Fortran `PELGLO`/`PELGAM` (`pelglo`, `pelgam`, with PELGAM's `PI = 3.1415927D0`) |
| Months skipped | fewer than 2 values, invalid L-moments | no value, `sd` NA or 0, fewer than 4 values, invalid or NA L-moments |
| SPI zeros | fitted, then mixed with the zero probability `pze` | left out of the fit; `pze` is computed but the mixed value is overwritten, so an accumulated 0 is `qnorm(cdfgam(0))` = `-Inf` and becomes missing |
| CDF | lmomco `cdfglo`, `cdfgam` | lmom `cdfglo` (`-1 / k * log(pmax(0, 1 - k * (x - xi) / alpha))`), `cdfgam` (`pgamma(x / beta, alpha)`) |
| PET | `hargreaves` on plain vectors at the station latitude | the same, at the cell's latitude |

With a thresholds file, `computefuture`: the daily series fitted runs from 1 January of
the first base year to the last data year, the file's `precraw` (and `txraw`, `tnraw`)
first, the cell's data last and missing in between (SPI's missing months there are 0).
Only the cell's months are kept, and their first `scale - 1` are made missing (R's comment
calls it a kludge for a SPEI bug). Infinite and NaN results become `NA`. `spei_package`
keeps R's order of operations and its extended-precision `sum` (`r_sum`) in the
accumulation, and uses `climpact.rdist`'s `qnorm` and `pgamma`; every SPI and SPEI value
of the five reference grids is identical to R's after rounding to float32. Not reachable
with precipitation sums, and not reproduced: when `PELGAM` fails (`L1 <= L2`) R falls back
to lmomco's `pargam`, gets `NULL` and stops; Python leaves the month missing.

### Rechunking inputs chunked by time step

A block needs every day of its cells, so it reads every netCDF chunk its cells are in.
Model output is usually chunked by one time step (or a few) over the whole grid; then
every block decompresses the whole file, and reading grows with the square of the grid
size (R's stripes read the same way). `GriddedInput.block_reader()`, which both
`write_grid_thresholds` and `write_grid_indices` read their blocks through, first copies
such an input to a temporary file laid out by block, and reads the blocks from it:

- **When.** `open_grid(..., rechunk=None)` (the default, `--rechunk auto`) rechunks when
  `GriddedInput.read_amplification()` is at least `RECHUNK_AMPLIFICATION` (4): the area
  of the files' chunks the blocks touch, summed over the blocks, divided by the grid's
  area, for the worst of the three variables. Files chunked by time step give the number
  of blocks; files chunked by cell or by block give 1, as do contiguous and netCDF-3
  variables (not rechunked automatically; `--rechunk yes` forces it). A single block is
  never worth it. `rechunk=True` / `False` (`--rechunk yes` / `no`) force it on or off.
- **Where.** `tmp_dir` (`--tmp-dir`, default the system's temporary directory). The copy
  is the raw values of the three variables in their file types, uncompressed
  (`GriddedInput.rechunk_bytes()`; 2.7 GB for 60 years of float32 on a 2.5-degree global
  grid). In automatic mode it is skipped, with a warning, when it would take more than
  90% of the free space; forced, too little space raises `OSError`. The file is deleted
  when the run ends, also on error or interrupt.
- **How.** One pass over the input in time slabs of the whole grid, each holding at most
  `max_values` values of one variable and a whole number of the files' time chunks
  (so each chunk is decompressed once). Each slab of each variable is written as one
  tile per block, sequentially; a block is then read back with one read per slab and
  variable (`_TileFile`). The raw values are decoded and converted exactly as
  `GriddedInput.load` does (`_to_climpact_units`, the same `decode_ncdf4` and unit
  conversion), so the values of every block, and every output, are identical.
- **Progress.** The run's `total` counts the slabs and the blocks; each slab reports
  `rechunk` (see [Progress reporting](#progress-reporting)).
- **Memory.** A slab holds at most `max_values` values in the file's type (20 MB for the
  default and float32), less than a block as float64. netCDF-C's read cache (up to 64 MB
  per variable, as for reading blocks directly) adds to the resident memory; it cannot be
  reduced for the copy, because `open_grid`'s open handles share HDF5's per-variable
  cache.

`tests/test_gridded_rechunk.py` checks every block of a grid with float32 data with a
fill value, packed int16 data with a `missing_value` and float64 precipitation stored
`(time, lon, lat)` in a second file is identical rechunked and read directly; that the
thresholds and index files are identical; the automatic decision, the progress stages,
that the temporary file is in `tmp_dir` and deleted (also on error), and that the memory
numpy allocates while rechunking does not grow with the grid. See
[Performance](#performance) for timings.

### Non-standard calendars

Model output often uses the `noleap` (`365_day`) or `360_day` calendar (#66). R reads them
as PCICt dates, and climdex.pcic then works with `dpy` days per year (`attr(ts, "dpy")`):
365 or 360 day-of-year thresholds (`create.thresholds.file`'s `num.thresholds`), years that
end on the calendar's last day of December (`get.last.monthday.of.year`, 30 December for
`360_day`), day numbers `1..dpy` (`get.jdays`), and no day dropped from the base period
(`get.bootstrap.set` drops 29 February only when it exists and `dpy != 360`).

`open_grid` reads such a time axis (xarray decodes it to cftime dates) into a
`CalendarDays` (`src/climpact/calendars.py`), held as `GriddedInput.calendar_days`.
`CalendarDays` has the parts of the `pandas.DatetimeIndex` interface the index code uses
(`year`, `month`, `day`, `day_of_year`, indexing, `get_indexer`), so the station index
functions run on it unchanged; standard-calendar data keep a `DatetimeIndex` and take
exactly the code paths they took before. The functions that build or compare dates go
through `climpact.calendars` (`as_days`, `whole_years`, `year_range`, `days_per_year`):
`filled_dates`, `take_dates`, `base_period_array` (`(years, dpy)`), `running_quantiles`,
`bootstrap_quantiles` (`dpy` from the array), `day_of_year`, `periods` (months and years of
the calendar; labels are the first days as standard dates), the base-period masks of the
percentile indices (by year), SPI/SPEI's `computefuture` series, and the output time axes
(`_days_since`, `_period_bounds`).

What R does in these calendars, reproduced (all checked by the reference runs
`grid_filled_noleap`, `grid_filled_360day` and `grid_sample_360day`):

- The thresholds file's `time` has `dpy` values and `base_time` every base-period day;
  `base_time`'s `calendar` attribute is PCICt's name, `365` or `360` (`pcict_calendar`),
  while `time` takes the input time's attributes, so it says `noleap` or `360_day`.
- `create.thresholds.file` makes the `time` and `time_bnds` dates with
  `as.PCICt(paste(year, 1:dpy), format = "%Y-%j")`. In `noleap`, PCICt reads `%j` as a day
  of the standard calendar and places its month and day in the 365-day year, so in a leap
  year day 60 (29 February) becomes 1 March, and so does day 61: 1 March appears twice and
  31 December not at all (`_year_days`). `grid_filled_noleap`'s `time_bnds` (base end 2000)
  has this. In `360_day` `%j` is read in the calendar.
- `climdex.hw` drops 29 February only in the standard calendar, and looks up each day's
  threshold with `tx90p[match(fact2, fact)]`, the position of its `"%m-%d"` among the days
  of 2001 (`hw_threshold_days`). In `noleap` that is the day of the year. In `360_day` it is
  not: from 1 February each day takes the threshold of a later day (1 February day 32's,
  1 March day 60's), 29 and 30 February get none, and neither do 27-30 December (positions
  past 360). Such days have no usable value (#51). Without this, 56 to 89 of
  `grid_filled_360day`'s `hw` values differ from R's.
- `climdex.hwEHF`'s 50% check divides by the days from 1 January of the first base year to
  the calendar's last day of the last (`base_data_sufficient(..., calendar)`).
- `write.climdex.results` turns the date of each extreme into a day number with `as.Date`,
  in the standard calendar (`_day_numbers`): in `noleap`, a day after February of a leap
  year gets its standard day of the year (1 March 2000 is 61); in `360_day`, the annual
  day numbers reach 364 and 29 and 30 February (and 29 February outside leap years) are
  missing. `day_of_txx` of the 360-day runs has such values.
- The index files' `time_bnds` and `time` (the midpoints) are the first and last days of
  each month or year of the calendar, in days since the origin of the calendar.

A thresholds file whose `time` length is not the input calendar's `dpy` is refused
(`check_thresholds_file`); R would index past its thresholds. Station files stay
standard-calendar: Climpact's station input has no calendar.

## Use of xclim

xclim 1.0 was meant to be used where its result is identical to R's or within tolerance,
but no station index uses it now. Threshold counts were the last: they used xclim's
`tn_days_below`, `tx_days_above`, `tg_days_*` and `wetdays` with
`check_missing="climdex"` until #23, and are now counted directly (`count_days`) for
speed. xclim compares in the data's units and counts with xarray's `resample(...).sum()`,
which took most of a station run's time, and its missing-value check builds a second
resample per call. `count_days` makes the same comparison and counts with
`climpact.periods`; `tests/test_index_helpers.py` checks it gives the same values and
mask as the xclim indicators on the Sydney station with a gap added. xclim remains a
dependency: `climpact.missing` registers the climdex rules as an xclim missing method
(see [Missing data](#missing-data)), so that xclim indicators can be used with
Climpact's rules. The gridded indices do not use xclim either: they are the station
index functions taking many cells (`count_values` and the other `*_values` functions,
with the climdex masks of `missing.valid_periods`).

| Uses xclim | Computed directly, and why |
| --- | --- |
| | Threshold counts (fd, su, tr, r10mm, ...): xclim's comparison and count are reproduced exactly, without xarray's per-period resampling (see above) |
| | Temperature max/min/mean (txx, tnn, tnx, txn, tmm, txm, tnm): xclim's kelvin round trip changes values (see below) |
| | dtr, sdii, and the means tmm/txm/tnm: R's extended-precision `mean`/`sum` is needed for the 15th digit written to the CSV files (see below) |
| | prcptot, hddheat, cddcold, gddgrow: xclim's sums (`wet_precip_accumulation`, `heating_degree_days`, ...) give the same 15 digits in the CSV files but differ from R's extended-precision `sum` in the last bits, which changes the trend file's slopes (see [Trend file](#trend-file)) |
| | rx1day: computed with the other extremes so the date of occurrence comes from the same data |
| | rx3day/rx5day: xclim's window is trailing, R's is centred (see below) |
| | cdd/cwd: R's handling of spells across years and its start/end dates have no xclim equivalent |
| | gsl: xclim's `growing_season_length` ends the season on TM ≤ 5 °C when it starts on TM > 5 °C (or starts on ≥ 5 °C when it ends on < 5 °C), where R uses > 5 and < 5; it returns no dates, and its Southern Hemisphere mask differs (see [Growing season length](#growing-season-length-gsl)) |
| | r95p, r99p, r95ptot, r99ptot: one threshold per station, not per day of year, and R's extended-precision `sum` is needed for the 15th digit (see below) |
| | Custom index: R's mask choice per variable differs from xclim's (see below) |
| | tx90p, tn90p, tx10p, tn10p, txgt50p: xclim's bootstrapping (`xclim.core.bootstrapping`) recomputes `percentile_doy`, which already differs from climdex's thresholds (see below), so it cannot match R exactly; the bootstrap and R's in-base averaging are ported directly |
| | wsdi, csdi, wsdid, csdid: xclim's `warm_spell_duration_index`/`cold_spell_duration_index` would need its own thresholds (`percentile_doy`, see below) and does not reproduce R's missing-value handling (`wsdi1` missing for any year with a missing day); txdtnd, txbdtnbd have no xclim equivalent. Both are ported directly (see below) |
| | Base-period thresholds: xclim's `percentile_doy` gives different values (see below) |
| | EHF heatwaves, EHF and ECF: xclim has no Excess Heat Factor; Climpact's definition (single base-period quantiles, joining and splitting heatwaves) is ported directly |
| | SPI, SPEI: xclim 1.0's `standardized_precipitation_index` and `..._evapotranspiration_index` do not implement `method="PWM"` for the gamma or fisk distributions (`NotImplementedError`), fit only the non-zero values, and its `fisk` is a 2-parameter log-logistic, not lmomco's generalised logistic. With `method="ML"` on `lat0` and `sydney` only 6-23% of values are within 0.01 of R's (largest difference 6.9), far from even the `FITTED` tier. Climpact's `cspei` is ported directly (see [SPI and SPEI](#spi-and-spei)) |
| | Tx90/Tn90 heatwaves: xclim's `heat_wave_index`/`hot_spell_*` use fixed thresholds or `percentile_doy`, calendar-year periods and no extended summer; Climpact's season and run rules are ported directly (see below) |

## Parity testing

### Reference outputs

`reference/output/<run>/<station>/` holds the R outputs of Climpact v3.4.3, produced by the
Docker setup in `reference/` (see `reference/README.md`). Each row of `reference/stations.csv`
is one run. `tests/parity/catalogue.py` reads it to build `RUNS`, so adding a row (with its input
file and R outputs) adds a run to the parity suite. Every run uses the Climpact app defaults
(base period 1971-2000) at the coordinates in `stations.csv`.

| Run | Station | Input | Parity (of R files) |
| --- | --- | --- | --- |
| `lat0` | Sydney Observatory Hill 1936-2015 at latitude 0, longitude 0. Reproduces the stored reference in the original repo's `tests/output_compare` exactly | Climpact's sample file | 125/125 |
| `sydney` | The same file at its real coordinates (-33.86, 151.21) | Climpact's sample file | 125/125, and 10/10 sector correlation files |
| `minneapolis`, `phoenix`, `alice_springs`, `darwin`, `perth`, `madrid`, `potsdam` | NH and SH continental, arid, tropical and Mediterranean climates, 1961-2020 | GHCN-Daily | 125/125 each |
| `oxford`, `dublin` | Maritime; TX and TN often missing on different days | GHCN-Daily | 123/123 and 125/125 |
| `yakutsk`, `beijing` | Extreme cold; missing-data rules (months with no data) | GHCN-Daily | 125/125 each |
| `new_delhi`, `nairobi` | Patchy base periods; R writes fewer files | GHCN-Daily | 91/91 and 68/68 |
| `qc_stress` | Synthetic: Potsdam with planted QC faults (see below). Only its `qc/` files are compared | `reference/make_qc_stress.py` | 9/9 |

**Gridded runs.** `reference/gridded/runs.csv` lists the gridded reference runs, made by
`reference/run_r_gridded.sh` with the same image (see `reference/README.md`); the catalogue
reads it into `GRID_RUNS`. Each run has R's thresholds file (`output/<run>/thresholds.nc`,
unless its `thresholds` column is `no`) and R's index files (`output/<run>/indices/`,
`climpact.ncdf.wrapper.r` with its fixed settings):

| Run | Grid | Thresholds (of R's variables) | Indices (of R's index variables) |
| --- | --- | --- | --- |
| `grid_stations` | Synthetic 3 x 4 grid, latitudes 52.5, 0 and -33.75, one station input per cell, 1966-2005, base 1971-2000, with an all-missing cell, a sparse base period, a dry cell and missing years; TX in K (float, `missing_value`), TN in degrees C (double), precipitation in kg m-2 s-1 in a second file | 26/26 | 100/100 (86 files; R's run leaves out `hw` and `hwEHF`, see [Gridded data](#gridded-data-1)) |
| `grid_sample` | 3 x 4 cut of Climpact's sample grid, 1991-2010, base 1991-2010; K, kg m-2 d-1, time in hours since 1800 | 26/26 | 118/118 (88 files) |
| `grid_future` | The cells of `grid_stations` for 2001-2020, after the base period; indices only, with `grid_stations`' thresholds file (R accepts one only for data with no base-period day) | none | 100/100 (86 files; no `hw`, `hwEHF`) |
| `grid_filled` | `grid_stations` with Beijing's series in the all-missing cell, and the sparse cell missing 20 June-20 July of every base year instead (its 15-day thresholds are missing for part of the northern season, but it has EHF), so R can write `hw` and `hwEHF`; only `hw`, `hwEHF`, `spi`, `spei` (`indices` column) | 26/26 | 20/20 (4 files) |
| `grid_filled_future` | The cells of `grid_filled` for 2001-2020, with `grid_filled`'s thresholds file: the thresholds-file paths of `hw`, `hwEHF`, SPI and SPEI | none | 20/20 (4 files) |
| `grid_filled_noleap` | `grid_filled` relabelled to the `noleap` calendar (29 February dropped); all indices | 26/26 | 118/118 (88 files) |
| `grid_filled_360day` | `grid_filled` relabelled to `360_day` (the first 360 days of each year as twelve 30-day months); all indices | 26/26 | 118/118 (88 files) |
| `grid_sample_360day` | `grid_sample` relabelled to `360_day` the same way, keeping its storage (hours since 1800, `time_bnds`); all indices | 26/26 | 118/118 (88 files) |

`runs.csv`'s `indices_exclude` column lists the indices R's run leaves out, and its
`indices` column the only ones it computes (passed to `run_gridded_indices.R` as
`--exclude` and `--indices`); the Python side computes the same.

`tests/parity/test_gridded.py` writes each run's thresholds file with small blocks, batches
and two threads, and requires every variable (the 21 thresholds and the coordinates) to have
R's dimensions, type, missing values and values exactly (`EXACT`: R stores doubles, so
unlike the CSV files no rounding is involved). `test_gridded_layout` checks the dimensions
(sizes and unlimited), the order of the dimensions and variables, and every attribute, apart
from `history`, `file_created` and `file_created_by_userid`, R's `R_version` and Python's
`climpactpy_version`, and the time units of `grid_sample` (see
[Gridded data](#gridded-data-1)).

`tests/parity/test_gridded_indices.py` writes each run's index files (one-row blocks,
batches of 3 cells, two threads, the thresholds file for `grid_future` and
`grid_filled_future`, only the run's `indices` if set) and compares every
index variable of every file R wrote, `day_of_<index>` included: same name, dimensions,
type (float32), fill-value positions, NaN positions and values (`EXACT`: both sides round
the same doubles to float32). `test_gridded_indices_layout` checks each file's dimensions,
variable order, coordinate values and types, and every attribute, with the same
exceptions as the thresholds file.

**Sector correlation.** `reference/run_r_sector.sh` runs R's step 4
(`reference/r/run_sector_correlation.R`, which calls `draw.correlation` as
`singleStationStep4.R` does) on the `sydney` run's committed index files and its raw input
file, with Climpact's sample `wheat_yield_nsw_1922-1999.csv`, detrended and not; the files
are in `reference/output/sydney/sector/{detrended,raw}/` (CSV committed, PNG gitignored).
The image installs ggplot2 from the same snapshot, in a layer after the others.
`tests/parity/test_sector.py` builds the correlation from the Python `sydney` run's tables
in memory and requires each file to equal R's line for line, apart from the detrended
sector column, compared at `CLOSE` (see [Sector correlation](#sector-correlation-1)): 6 of
the 10 files are text-identical, and the four detrended scatter files differ in one value
(1994) in the 15th significant digit.

`qc_stress` (`source` `synthetic` in `stations.csv`) exists because none of the real stations
has a duplicated date and several QC checks fire at only a few of them.
`reference/make_qc_stress.py` takes Potsdam 1961-2020 and plants duplicate dates (an
identical repeat, a repeat with other values, a date given three times, an out-of-order
repeat, an all-missing repeat), a removed day, an invalid date, TN >= TX, values at and
beyond the too-large limits, jumps at and below 20 °C (including two-decimal values whose
change depends on R's `round`), and flat runs of 5, 6 and more values, one broken by a
missing value. The catalogue (`Run.qc_only`) compares only its `qc/` files, and
`test_only_reference_files_written` checks only those. Its committed index, threshold and
trend files were compared by hand when the run was added: all 110 that do not depend on
the C maths library are text-identical to R's, and the SPI/SPEI files and rows differ on
macOS only in the last digits, as on the other runs. This confirms that R's index
calculations use the last row of a duplicated date, as Python does.

GHCN inputs are converted by `reference/fetch_ghcn.py`: values divided by 10, `-99.9` for
missing, and values with a GHCN QC flag set to missing. Sydney keeps Climpact's own sample
file. A GHCN conversion of the same station (ASN00066062) has every shared value identical,
but GHCN has 89 more temperature days and QC-flags 96 values Climpact's file keeps, so it
would not reproduce the stored reference (details in `reference/README.md`).

Climpact writes no CSV for an index that is missing in every period, so stations with patchy
data have fewer reference files (`oxford` 112 index files, `new_delhi` 80, `nairobi` 57,
against 114). The catalogue lists only the files R wrote. The heatwave files are an
exception (see [Writing output files](#writing-output-files)): `new_delhi`'s five
`TN90-` files are written although every value is missing, and `nairobi` has no heatwave
files because no TX or TN year passes the climdex annual rule, so every value is missing.
Neither station has EHF files: R writes none when HWF is missing in every year, which the
TX and TN annual masks cause on both.

If building a run's outputs raises, the `station_outputs` fixture caches the error, so every
test of that run fails at once instead of rebuilding the station for each file.

### Tolerance tiers

`climpact.compare.compare_tables` compares tables column by column:

| Tier | Applies to | Pass condition |
| --- | --- | --- |
| `EXACT` | counts, extremes, event lengths, all QC files | identical values |
| `CLOSE` | means, sums, percentages, degree days, standardised anomalies, trend slopes and bounds | `abs(py - r) <= 1e-6 * abs(r) + 1e-9` |
| `FITTED` | fitted distributions (no file uses it: SPI and SPEI pass at `CLOSE`) | at least 99% of values within 0.01 |

In every tier the pattern of missing values must be identical, and string columns (dates)
must match exactly. Metadata header lines (including `Date_of_calculation`) are not compared.
Tiers are assigned by file name in `tests/parity/catalogue.py`; the standardised column of
an `EXACT` file uses `CLOSE`. The sector correlation files (`tests/parity/test_sector.py`)
are compared as text, apart from the detrended sector column at `CLOSE`. Every variable of
the gridded thresholds and index netCDF files is compared at `EXACT`.

**These tiers are the project's acceptance criteria** (decided 2026-11-13, #31). WMO could
not be consulted, so the project set them itself. A file may be moved to a looser tier only
with an entry under "Differences between Python and R" explaining why. `FITTED` is reserved
for fitted distributions.

### Running

```sh
.venv/bin/pytest                                   # everything (both packages)
.venv/bin/pytest packages/climpact                 # the core only
.venv/bin/pytest packages/climpact/tests/parity    # parity only
```

Files that no product builds are reported as `xfail` ("not yet ported"); there are none
now. A summary is printed at the end:

```
=================================== R parity ===================================
alice_springs: 125/125 reference files reproduced, 0 failing, 0 not yet ported
beijing: 125/125 reference files reproduced, 0 failing, 0 not yet ported
darwin: 125/125 reference files reproduced, 0 failing, 0 not yet ported
dublin: 125/125 reference files reproduced, 0 failing, 0 not yet ported
lat0: 125/125 reference files reproduced, 0 failing, 0 not yet ported
madrid: 125/125 reference files reproduced, 0 failing, 0 not yet ported
minneapolis: 125/125 reference files reproduced, 0 failing, 0 not yet ported
nairobi: 68/68 reference files reproduced, 0 failing, 0 not yet ported
new_delhi: 91/91 reference files reproduced, 0 failing, 0 not yet ported
oxford: 123/123 reference files reproduced, 0 failing, 0 not yet ported
perth: 125/125 reference files reproduced, 0 failing, 0 not yet ported
phoenix: 125/125 reference files reproduced, 0 failing, 0 not yet ported
potsdam: 125/125 reference files reproduced, 0 failing, 0 not yet ported
qc_stress: 9/9 reference files reproduced, 0 failing, 0 not yet ported
sydney: 125/125 reference files reproduced, 0 failing, 0 not yet ported
yakutsk: 125/125 reference files reproduced, 0 failing, 0 not yet ported
alice_springs: 125/125 written CSV files text-identical to R, 0 differing
beijing: 125/125 written CSV files text-identical to R, 0 differing
darwin: 125/125 written CSV files text-identical to R, 0 differing
dublin: 125/125 written CSV files text-identical to R, 0 differing
lat0: 125/125 written CSV files text-identical to R, 0 differing
madrid: 125/125 written CSV files text-identical to R, 0 differing
minneapolis: 125/125 written CSV files text-identical to R, 0 differing
nairobi: 68/68 written CSV files text-identical to R, 0 differing
new_delhi: 91/91 written CSV files text-identical to R, 0 differing
oxford: 123/123 written CSV files text-identical to R, 0 differing
perth: 125/125 written CSV files text-identical to R, 0 differing
phoenix: 125/125 written CSV files text-identical to R, 0 differing
potsdam: 125/125 written CSV files text-identical to R, 0 differing
qc_stress: 9/9 written CSV files text-identical to R, 0 differing
sydney: 125/125 written CSV files text-identical to R, 0 differing
yakutsk: 125/125 written CSV files text-identical to R, 0 differing
grid_filled: 26/26 thresholds netCDF variables identical to R, 0 differing
grid_filled_360day: 26/26 thresholds netCDF variables identical to R, 0 differing
grid_filled_noleap: 26/26 thresholds netCDF variables identical to R, 0 differing
grid_sample: 26/26 thresholds netCDF variables identical to R, 0 differing
grid_sample_360day: 26/26 thresholds netCDF variables identical to R, 0 differing
grid_stations: 26/26 thresholds netCDF variables identical to R, 0 differing
grid_filled: 20/20 index netCDF variables identical to R, 0 differing, 0 not yet ported
grid_filled_360day: 118/118 index netCDF variables identical to R, 0 differing, 0 not yet ported
grid_filled_future: 20/20 index netCDF variables identical to R, 0 differing, 0 not yet ported
grid_filled_noleap: 118/118 index netCDF variables identical to R, 0 differing, 0 not yet ported
grid_future: 100/100 index netCDF variables identical to R, 0 differing, 0 not yet ported
grid_sample: 118/118 index netCDF variables identical to R, 0 differing, 0 not yet ported
grid_sample_360day: 118/118 index netCDF variables identical to R, 0 differing, 0 not yet ported
grid_stations: 100/100 index netCDF variables identical to R, 0 differing, 0 not yet ported
sydney: 10/10 sector correlation CSV files matching R, 0 differing
```

The "reference files reproduced" lines come from `tests/parity/test_parity.py`, which
compares tables with the tolerance tiers. The "text-identical" lines come from
`tests/parity/test_csv_text.py`, which writes every built table with `write_outputs` and
requires the file to equal R's line for line, ignoring only the `Date_of_calculation` line.
The SPI and SPEI files, and the SPI and SPEI rows of the trend file (`spi3,FEB,...`),
are compared as text only on glibc x86_64; on other platforms their numeric fields may
differ within 1e-10 relative (see [SPI and SPEI](#spi-and-spei) and
[Trend file](#trend-file)), so a macOS run also prints "text-identical" for them.
It also checks that no file is written that R does not write: on `oxford`, `new_delhi` and
`nairobi` this exercises the rule that all-missing index tables are skipped, on
`new_delhi` the exception for heatwave files, and on both that no EHF file is written
when HWF is missing in every year.

Files that fail because of a filed bug are listed in `KNOWN_BUGS` in
`tests/parity/catalogue.py` (a pattern on the test id and the ticket). They are strict xfails
in both tests, counted as "known bugs" in the summary: when the bug is fixed the test passes,
which fails the run, so the entry has to be removed. If a whole run's build fails, every file
of that run counts as a known bug, including files not yet ported. The list is currently empty.

A failure reports, per column, the number of missing-value and value mismatches, the
largest difference and the first mismatching row.

### Adding an index

1. Read the R definition. Climpact's own version in `server/climpact.etsci-functions.r`
   takes precedence over climdex.pcic's, because Climpact sources its file after loading
   the package.
2. Add or extend a product in `src/climpact/products/` returning the table under the key
   matching the R file name. (An index that R does not have can instead be a separate
   index module; see [Modules and plugins](#modules-and-plugins).)
3. Run `pytest packages/climpact/tests/parity -k <name>`. Fix mismatches, or, if the difference comes from
   R behaviour that should not be copied, record it in the differences section below.

## Differences between Python and R, and how they are handled

Each entry states the R behaviour, what Python does, and the effect on results.

### Numerical precision

**R accumulates sums in 80-bit extended precision.** R's `sum()`, `cumsum()` and `mean()`
accumulate in a C `long double`, which on x86_64 is the x87 80-bit format (64-bit
significand). numpy accumulates in 64-bit doubles (pairwise summation).

- *Effect:* differences of about 1e-14 in sums and means. These are within the `CLOSE`
  tier, but R writes 15 significant digits, so they change the last digit of some values
  in the CSV files (see below).
- *Exception, Rx3day/Rx5day dates:* when two windows have the same true precipitation
  total, R's rounding noise decides which window's date is reported (3 of 1,920 monthly
  dates differed with plain numpy). `climpact.rnumerics` emulates R's extended-precision
  `sum` and `cumsum` exactly using integer arithmetic, so ties resolve as in R on every
  platform. numpy's `longdouble` is not used because it is only 80-bit on x86 (on Apple
  Silicon it is a plain double). `tests/test_rnumerics.py` checks the emulation against
  native x87 `longdouble` on the x86 CI runners.
- *Means and the standardised column:* with numpy, 19 of the 65 written files of the `lat0` run
  differed from R's in the last digit (mostly the standardised column, plus a few values
  of dtr, tmm, txm, tnm and sdii). `rnumerics.r_mean` emulates R's two-pass mean
  (`summary.c`: extended-precision sum, divide, then add the mean of the residuals) and
  `rnumerics.r_var` emulates `var` (`cov.c`: the same mean rounded to a double, then
  squared deviations summed in extended precision). They are used for tmm, txm, tnm, dtr
  (`period_stat`) and the standardised column (`standardise`); sdii, prcptot, the degree
  days and the r95p, r99p, r95ptot and r99ptot totals use `r_sum` (prcptot and the
  degree days only for the trend file: xclim's sums gave the same 15 digits). All written files are then text-identical to
  R's. With numpy sums, 34 of the 3,752 r95p/r99p/r95ptot/r99ptot values of the 15 runs
  would be written with a different last digit.
- The emulation is only used where it changes a result. It should be considered for
  other index calculations if new tie-related or last-digit mismatches appear.
- *Speed:* rounding to 64 significant bits does not depend on the unit, so `r_sum`,
  `r_cumsum` and `r_mean` hold the values as integers in the coarsest power-of-two unit that
  holds them all exactly, not in units of 2**-1074, and only round when an accumulator
  reaches 2**64 units. When the absolute values add up to less than 2**62 of those units,
  no partial sum is ever rounded, so R's `sum` is the exact sum rounded once, which is
  `math.fsum` (most monthly and 30-day temperature sums). `r_mean`'s two divisions are
  done with enough extra bits that their 64-bit rounding is exact, as it is in units of
  2**-1074. `tests/test_rnumerics.py` checks all three against the original
  implementation (`tests/rreference.py`) bit for bit on random and adversarial series.
- *Moving sums:* the EHF's 30-day `sum(..., na.rm = TRUE)` is needed for every day of every
  series (and grid cell). `r_window_sums` computes all windows at once: where a window
  meets `r_sum`'s fast-path condition, the exact sum is formed in 64-bit integers (values
  scaled by the window's finest power of two) and rounded once to a double; other windows
  go through `r_sum`. Data stored as float, or converted from kelvin (multiples of
  2**-44), always take the fast path; decimal doubles near 0 °C do not. `excess_factors`
  uses it for stations too; every station EHF file is unchanged, and
  `tests/test_rnumerics.py` checks it against `r_sum` on both paths.
- *Means stored as float32 (gridded indices):* R's gridded index files store float32, so
  only R's mean rounded to float32 matters. `period_means(float32=True)` divides the double
  sum of each period by its count, for all periods and cells at once, and uses `r_mean`
  only where the result lies within `2**-40 * scale * (|mean| + max |x|)` of a float32
  rounding boundary (a midpoint between two float32 values; `scale` is 100 for the
  percentage indices, applied before rounding as R does). The double estimate is within
  `n * 2**-53 * max |x|` of the exact mean (n <= 366) and R's two-pass extended mean
  within about `2**-52 * (|mean| + max |x|)`, both far inside the margin, so outside it
  both round to the same float32. Station outputs keep `r_mean` (they print 15 digits).
  `tests/test_gridded_indices.py` checks the float32 results against `r_mean`, including
  means exactly on and next to a boundary, which take the fallback. It made the gridded
  means about 20 times faster (they were half of a cell's time).

**R's `write.index.csv` standardises the text, not the values.** It prepends the column
name to the index vector, which turns the numbers into strings (`as.character`, 15
significant digits), and then computes the mean and sd of `as.numeric` of those strings.

- *Handling:* `standardise` rounds the values through `format_r_number` and back before
  computing the anomalies. Without this, standardised values of means differ in the last
  digit.

**R's choice of significant digits is not correct rounding.** `formatReal` decides how many
significant digits to print by scaling the value by a power of ten in long double,
rounding to a 15-digit integer and dropping trailing zeros; the digits are then printed by
`sprintf`. A value just below a rounding boundary can round up to a trailing zero in
long double and then be printed with 14 digits: R writes `-0.8707237491215295` as
`-0.87072374912153`, where correct rounding to 15 digits gives `-0.870723749121529`.

- *Handling:* `format_r_number` ports `scientific()` with exact long-double rounding, and
  R's choice between fixed and scientific notation (`1e+05`, not `100000`). Tested in
  `tests/test_climpact_csv.py`; the reference files have this case in `r10mm_ANN`. The
  long-double steps are done on integer ratios (each value is `n / 2**shift`), and results
  are cached (`functools.lru_cache`), since index files repeat many values; the test checks
  the result against the original `Fraction` version (`tests/rreference.py`) on values
  next to decimal rounding boundaries.

**xclim converts temperatures to kelvin internally.** Indicators such as `tx_max` and
`tg_mean` return kelvin, and converting °C → K → °C changes the last bits of about 84% of
values.

- *Handling:* temperature maxima, minima and means are computed directly (`period_stat`):
  maxima and minima with xarray, means with `r_mean`, the same arithmetic as R's `tapply`
  with `mean`. Results are identical to R.
- Threshold counts would be unaffected: xclim converts the threshold into the data's
  units, so comparisons are made on the original values. They are counted directly anyway,
  for speed (see [Use of xclim](#use-of-xclim)).

**The R reference depends on CPU architecture.** On arm64, climdex.pcic's C++ percentile
code (used for the bootstrapped in-base percentiles) rounds differently from x86, which
flips threshold ties and changes tx10p, tn10p, tx90p and csdi in some base-period years.

- *Handling:* the R reference is always generated as `linux/amd64` (emulated on Apple
  Silicon). This matches the original repo's stored reference exactly.
- *Implication for the port:* percentile indices are sensitive to exact ties between data
  (0.1 °C resolution) and thresholds. Across the 14 distinct stations, 178,283 of the
  21.4 million in-base comparisons of tx90p, tn90p, tx10p, tn10p and txgt50p are exact
  ties, as are 5,319 out-of-base days. The thresholds are therefore computed bit for bit
  as climdex's C++ does (`climdex_quantile_sorted`, `bootstrap_quantiles`), with no fused
  multiply-add, which matches the amd64 reference.

### Index definitions

**Rx3day/Rx5day use a centred window.** climdex.pcic's `running.mean` centres the window
(`n %/% 2` days before), replaces missing days with 0, pads the ends with 0, and reports the
centre day as the date. xclim's `max_n_day_precipitation_amount` uses a trailing window.

- *Handling:* the R algorithm is ported directly (`running_sum_centred`), including its
  arithmetic order (first sum, then cumulative differences).

**CDD/CWD spells across years and their dates.** With `spells.can.span.years = TRUE`, a
spell counts towards the year it ends in, and a year entirely inside an unfinished spell is
missing. The reported end date is the last day of the longest spell *ending within* the
year, and the start date is `end - duration` days, so it can fall in the previous year.
CDD/CWD use the annual precipitation mask.

- *Handling:* ported directly (`spell_length_max`), including R's treatment of `all()` with
  missing values when deciding whether a year is inside an unfinished spell.

**Date of occurrence.** R reports the first day on which the maximum/minimum occurs,
skipping missing days (`which.max`/`which.min`), and no date when the value is missing.

- *Handling:* same rule via pandas `idxmax`/`idxmin`, which also return the first occurrence.
  Missing days are filled with -inf/+inf first, so a period with no data at all does not
  raise an error (its date is dropped because its value is missing).

**Custom index masks.** In R's `calculate.custom.index`, TM uses only the TN missing mask
(not TX), and DTR uses both TX and TN masks.

- *Handling:* replicated. A TM custom index can therefore have a value in a month where TX
  has more than 3 missing days; this matches R.

**tmm and dtr masks.** R masks tmm with the TN and TX masks (each variable's climdex rule
applied separately, then combined), which is what Python does. climdex.pcic's `climdex.dtr`
masks dtr with the TM mask, where a day is missing if either TX or TN is missing, so a month
with 3 missing TX days and 3 missing TN days on different dates is missing.

- *Handling:* dtr is the mean of TX − TN (`period_stat`, with `r_mean`) masked with
  `valid_mask(ds.tas)`, the TM mask, exactly R's mask. Sydney's gaps
  coincide, so only `oxford` and `dublin` exercise this (#40).

**Dates of extremes in empty periods.** R's `which.max`/`which.min` return no index for a
period with no data, and Climpact writes `-99.9`.

- *Handling:* pandas `idxmax`/`idxmin` raise on an all-missing group, so
  `first_extreme_dates` fills missing days with -inf (max) or +inf (min), which never win in a
  period with data, and sets the date to NaT for periods with no data. Exercised by
  `yakutsk`, `beijing`, `nairobi` and `new_delhi` (#39).

**r95p, r99p, r95ptot, r99ptot.** climdex.pcic's `climdex.r95ptot` returns the total
precipitation above the percentile, which is r95p in Donat et al. (2013). Climpact
redefines all four in `climpact.etsci-functions.r`: `climdex.r95p` and `climdex.r99p` are
the annual totals on days with precipitation **>** the base-period wet-day (≥ 1 mm)
95th/99th percentile, and `climdex.r95ptot` and `climdex.r99ptot` are `100 * rNNp /
prcptot`, with prcptot recomputed as the annual total on days ≥ 1 mm. All four use the
annual precipitation mask. A year with no wet days gives `0 / 0`; R's `write.index.csv`
turns the resulting `NaN` into `-99.9` and leaves it out of the standardised column.

- *Handling:* Climpact's definitions are ported (`precipitation_percentiles`,
  `annual_total_above` in `products/indices.py`), using `Thresholds.precipitation` and
  `r_sum`. The `0 / 0` year is `NaN`, so it is missing in the table and the file, as in R.
  All four files are text-identical to R's on all 15 runs. No reference run has a valid
  year without wet days; `tests/test_index_helpers.py` covers it.

**SU threshold.** Climpact's code counts TX **>** 25 °C, although a code comment says
`>=`. Python follows the code.

### Base-period thresholds

**Window wraps around within the same year.** In climdex.pcic's C++
`running_quantile_windowed`, the window day index is `(day + dpy) % dpy` within the same
year's block, so the 5-day window for 1 January takes 30-31 December of the *same* year,
not the previous one (the 15-day heatwave window likewise for its first and last 7 days).

- *Handling:* reproduced (`window_values`). Needed for parity on the first and last days
  of the year.

**29 February is left out of the base period.** climdex.pcic `get.bootstrap.set` drops
29 February, so the base period is 30 × 365 days and there are 365 thresholds. In a
series, 29 February uses 28 February's threshold (`get.jdays.replaced.feb29`).

- *Handling:* reproduced (`base_period_matrix`, `day_of_year`). Precipitation thresholds
  keep 29 February, as `get.prec.var.quantiles` does.

**Two quantile definitions.** Temperature thresholds use climdex's C++ `c_quantile`;
precipitation thresholds use R's `quantile(type = 8)`. Both are "type 8", but they are
not bit-identical: the C++ works in 0-based positions with `floor(nppm + fuzz)` and always
interpolates, while R 4.6.1 uses `floor(nppm * (1 + fuzz))` and takes the lower value
without interpolating when both neighbours are equal. They differ in the last bits for
some inputs (in 46 of 2,400 R test cases, for example `n = 135, q = 0.5`, where climdex
gives 4.999999999999998 and R gives 5).

- *Handling:* both are ported exactly (`climdex_quantile_sorted`, `r_quantile_type8`) and
  match R bit for bit on all 2,400 cases. numpy's `method="median_unbiased"` is the
  same definition but differs from climdex in the last bits on 209 of 365 tx95t days, so
  it is not used. These last-bit differences matter for percentile indices, where data at
  0.1 °C resolution can tie with a threshold.

**xclim's `percentile_doy` is not used.** It groups by a 366-day day of year, uses windows
that cross year boundaries, and then interpolates the 365-day result onto 366 days across
the whole year. For Sydney's TX, over 1 January to 28 February alone (where the two
day-of-year grids line up), it differs from climdex on 54 of 59 days for q95 (by up to
0.25 °C) and on 45 of 59 days for q50 (by up to 0.1 °C). The thresholds are computed
directly instead.

**Minimum data per window.** A day's temperature threshold is missing when fewer than 10%
of the window's values are present (`min.base.data.fraction.present = 0.1`). Climpact
passes this value to `get.outofbase.quantiles` for the heatwave thresholds, but that
function does not forward it, so the default 0.1 always applies. Python uses 0.1
(`MIN_BASE_FRACTION`); the effect is identical.

**Not enough base-period data.** climdex.pcic computes no thresholds (or stops) when 359
days or fewer of the base period lie between the station's first and last dates; this
counts dates, not valid values. Python applies the same rule using the `first_date` and
`last_date` Dataset attributes and raises `InsufficientBaseData`. What Climpact then
writes for the percentile indices has not been checked; Python writes no threshold
tables and none of the percentile indices (tx95t, r95p, r99p, r95ptot, r99ptot, tx90p,
tn90p, tx10p, tn10p, txgt50p, wsdi, csdi, wsdid, csdid, txdtnd, txbdtnbd).

**Result.** `thres/thres` and `indices/tx95t_DAY` pass at `CLOSE` for both runs. Every
threshold value is identical to R's file after formatting to the 15 significant digits R
writes; `EXACT` cannot be used because the file holds rounded values. The tx95t
standardised column differs by up to 1.4e-13 relative (mean and standard deviation
arithmetic).

### In-base bootstrap

**Zhang et al. (2005) in-base thresholds.** Inside the base period climdex.pcic does not
compare a day with the plain threshold, which would be biased because the day's own year
helped set it. For each calendar day and base year `rm`, it builds `years - 1` samples:
the 5-day window values of all base years, with year `rm` replaced by a second copy of
another year `dup`, and takes the quantile of each (`zhang.running.qtile` with
`get.bootstrap.data = TRUE`, C++ `running_quantile_windowed_bootstrap`). A sample with
fewer than 10% of the `years * 5` window values present gives a missing threshold.

- *Handling:* `bootstrap_quantiles` in `thresholds.py`, used through `Thresholds.inbase`.
  The C++ sorts the window values once and drops or duplicates elements in place, so the
  replaced sample is the sorted values with weights 0, 1 or 2. Python finds the values at
  the two quantile positions from the cumulative weights, without building each sample,
  and applies `c_quantile`'s arithmetic (shared with `climdex_quantile_sorted`). Results
  are bit-identical to building every sample (`tests/test_temperature_percentiles.py`).
  Only the quantiles the indices use are computed: TX q10, q50, q90 and TN q10, q90
  (R computes all five for TX, TN; the others are unused).

**Averaging in-base comparisons.** Climpact replaces climdex.pcic's
`percent.days.op.threshold` (`climpact.etsci-functions.r`, line 259) with a version that
returns a missing day only when all comparisons are missing. Outside the base period a
day scores 1 if `value > threshold` (`<` for tx10p, tn10p), else 0. Inside it, the day is
compared with each of the `years - 1` bootstrapped thresholds for its year and day of
year, and scores `hits / (byrs - 1)` (line 284). Comparisons with a missing threshold
count as no hit. The period value is `mean(scores, na.rm = TRUE) * 100`, missing if more than 3
(monthly) or 15 (annual) days' scores are missing, then multiplied by the variable's
climdex mask. The in-base part is skipped for series shorter than 720 days.

- *Handling:* ported in `days_op_threshold` and `percent_days` (`products/indices.py`),
  except the denominator: Python divides by `years - 1`, the number of comparisons
  (see the next entry). The comparisons are strict, as in R. The mean uses `r_mean`: with numpy's mean, 269 of
  the 54,207 values of the 14 stations would be written with a different last digit.

**`byrs` counts the years of the series, not of the base period.** In R, `byrs` is the
number of base-period years between the series' first and last dates, while the
bootstrap always has `base_end - base_start + 1` years. For a station that starts or
ends inside the base period, the hits are divided by fewer than the number of
comparisons, so a value can exceed 100%. For a station starting in 2002 with base period
2001-2003, R gives 200% for 2003 (checked in R itself: `tests/data/r_percent_days.R`).

- *Handling:* not copied (decided 2026-11-13, #47). `days_op_threshold` divides each
  in-base day's hits by `years - 1`, the number of bootstrapped thresholds it is
  compared with, so a score is at most 1 and a percentage at most 100%. In the example,
  Python gives 100% for 2003. Missing thresholds still count as no hit, as in R.
- *Why this denominator:* when the series covers the whole base period, `years - 1`
  equals R's `byrs - 1`, so the result is identical to R by construction, on any station.
  The other candidate, the number of non-missing comparisons for each day, would also
  stay at or below 100%. But it would differ from R on a station that covers the whole
  base period whenever some, but not all, of a day's bootstrapped thresholds are
  missing. On the 15 reference runs both candidates give the same results, because no
  run has a partly missing set of bootstrapped thresholds. That includes the stress
  stations: new_delhi (1,545 TX and 2,920 TN values missing in the base period) and
  nairobi (3,501 and 3,797) have no missing bootstrapped threshold at all.
- *Effect:* none on any reference run. Every run starts before 1971 and ends after 2000,
  so `byrs` = 30 = `years`, and parity and text identity are unchanged on all 15 runs.
  Only series that partly cover the base period differ from R. They are covered by
  `test_station_starting_inside_the_base_period`,
  `test_station_ending_inside_the_base_period` and `test_percentages_never_exceed_100`
  in `tests/test_temperature_percentiles.py`. No other index ported so far uses
  `byrs`: in R only tx90p, tn90p, tx10p, tn10p and txgt50p call
  `percent.days.op.threshold`, and the spell-duration indices use the out-of-base
  thresholds only.
- *Not reproduced:* with exactly one base year in the series (and at least 720 days),
  R stops with an error (`byrs - 1 = 0`). Python uses the out-of-base thresholds for that
  year instead.

**Result.** All 10 files (`tx90p`, `tn90p`, `tx10p`, `tn10p`, `txgt50p`, ANN and MON)
pass at `CLOSE` on all 15 runs (8 files for `new_delhi` and 5 for `nairobi`, where R wrote
fewer), and are text-identical to R's.

### Spell-duration indices

**Thresholds and year boundaries.** wsdi and csdi (climdex.pcic `climdex.wsdi`/`csdi`),
Climpact's `climdex.wsdid`/`csdid` (`climpact.etsci-functions.r`, lines 47-62) and
`climdex.txdtnd`/`txbdtnbd` (lines 330-347) all compare with the out-of-base thresholds
(`ci@quantiles$...$outbase`) only, on every day including the base period: there is no
in-base bootstrap. Climpact calls them without `spells.can.span.years`, so the default
`FALSE` applies (unlike cdd/cwd): each year is split off before runs are found, and a spell
crossing 31 December counts as two separate runs.

- *Handling:* `spell_durations` in `products/indices.py` uses `Thresholds.daily` with
  q90 (wsdi), q10 (csdi), q95 (tx{n}tn{n}) and q5 (txb{n}tnb{n}), year by year.

**Run selection** (`threshold_exceedance_duration`, `select_blocks_gt_length`). wsdi/csdi
count the days in runs of at least `min.length` days (6, or `wsdi_days`/`csdi_days`) via
climdex.pcic `select.blocks.gt.length(d, min.length - 1)`, which keeps runs **longer than**
its `n`. Missing comparisons count as FALSE, except that with `n < 1` the function returns
its input unchanged, NA included.

- *Effect, reproduced:* `wsdi1` and `csdi1` (`min.length = 1`) are missing in every year
  with a single missing TX (TN) day or threshold, because the year's `sum` is NA. This is
  why R wrote no `wsdi1`/`csdi1` for `oxford` and `new_delhi`.

**Dual-threshold events** (`dual_threshold_duration`). Climpact's
`dual.threshold.exceedance.duration.index` (line 373) combines the two comparisons with R's
`&` (FALSE wins over NA), keeps runs with `select.blocks.gt.length(both, n)`, so events need
**more than** `n` days: `tx2tn2` counts events of at least 3 days, although its description
says "2 consecutive days". Runs of 3 or fewer non-event days are then filled in (including
at the ends of the year), and the result is the number of remaining events.

- *Handling:* reproduced, including the "more than `n`" rule.

**Missing-data masks.** Both R functions compute an annual mask with
`get.na.mask(is.na(x + thresholds[jdays]), f, 15)`, but `get.na.mask` applies `is.na` again
to its already-logical input, so the mask is always 1 (checked in R on `oxford`, where TN
has 16 and 30 missing days in 1981 and 2018). The only mask applied is the variable's
climdex annual mask (`namasks$annual`): TX for wsdi, wsdid, txdtnd and txbdtnbd, TN for csdi
and csdid. The dual-threshold indices are therefore not masked for missing TN.

- *Handling:* reproduced (no 15-day mask; TX mask for the dual-threshold indices). Masking
  for TN as well would make 1981 and 2018 missing in `oxford`'s `tx2tn2` and `txb2tnb2`.

**Result.** All 6 files (`wsdi`, `csdi`, `wsdi1`, `csdi1`, `tx2tn2`, `txb2tnb2`) pass at
`EXACT` on every run where R wrote them (4 for `oxford`, 3 for `new_delhi`, none for
`nairobi`), and are text-identical to R's. `tests/test_spell_durations.py` checks the
helpers against values printed by R (`tests/data/r_spell_durations.R`), covering the
`n < 1`, `n >= length` and gap-merging cases.

### Heatwaves (Tx90, Tn90)

Climpact's `climdex.hw` and `get.hw.aspects` (`climpact.etsci-functions.r`, lines 674 and
773; Perkins and Alexander 2013), driven by `services/calculate/calculate_hw.R` and written by
`write.hw.csv`. Ported in `products/heatwaves.py`: `tx90_tn90_heatwaves` builds the daily
flags, and `hw_aspects` / `season_aspects` turn flags into the five annual aspects.
`hw_aspects` takes any daily flags (1/0/NaN) and values. Climpact's EHF heatwaves do not
use `get.hw.aspects` (see [EHF heatwaves](#ehf-heatwaves-and-the-daily-ehfecf-series)).

**Thresholds.** `climdex.hw` finds no `q90_15days` in the climdex object, so it recomputes
the 15-day-window q90 with `get.outofbase.quantiles(n = 15)`. These are the same values as
`HW_TX90`/`HW_TN90` in `thres.csv`; Python uses `Thresholds.heatwave[var]`. `calculate.hw`
calls `climdex.hw(cio)` without `min.base.data.fraction.present`, which is harmless because
`get.outofbase.quantiles` never uses it (see [Base-period thresholds](#base-period-thresholds-1)).

**Daily flags** (`heatwave_flags`). 29 February is dropped from the data, the dates and the
thresholds. A day is flagged when `value > threshold`; `select.blocks.gt.length(flags, 2)`
then keeps runs of at least 3 days over the whole series, with missing days counting as
FALSE. A missing day therefore ends a heatwave.

**Season** (`summer_days`). Year Y's season is May-September of Y in the Northern
Hemisphere and November Y to March Y+1 in the Southern Hemisphere (latitude 0 is southern,
`lat > 0`). R looks at the season plus the following 90 days; days past the end of the
series are missing.

**Which heatwaves count** (`season_aspects`):

- A run that ends inside the season counts, including the in-season part of one that began
  before the season. If only 1 or 2 days of such a run fall in the season, R adds them by a
  separate test, so a heatwave can count with a duration of 1 or 2 days (reproduced; see
  below).
- The first run that ends after the season counts if it began inside it, cut so that it
  ends at most 14 days after the season. The cut applies to HWM, HWA, HWD and HWF
  (reproduced).
- A run that is under way on the first day of the season and ends after the season. R does
  not count it at all: `extvals[1] > 1` (`climpact.etsci-functions.r`, line 827) excludes
  the first run of the extended season, so the season gets HWN 0. **Not copied** (decided
  2026-11-13, #51): Python counts it as one heatwave. If it was already under way the day
  before the season (`flags[start - 1] == 1`) only its in-season days count, as for any
  heatwave that began before the season, so HWD = HWF = the season length (153 days in the
  north, 151 in the south). If it began on the season's first day, it began inside the
  season and the 14-day cut applies. No season of any reference run has such a heatwave,
  so no reference file changes.

**Aspects.** HWN is the number of heatwaves; HWF the sum of their lengths; HWD the longest;
HWM the mean of the heatwave means (R's extended-precision `mean`, `r_mean`); HWA the peak
of the heatwave with the highest mean (the first on ties, `which.max`), as defined by
Perkins and Alexander. With no heatwave in a season, HWN and HWF are 0 and HWM, HWA and
HWD are missing.

**Missing data.**

- R (`get.hw.aspects`, after the season loop) makes HWN and HWF missing in every year when
  HWM is missing in every year. It does this for stations without thresholds, but it also
  catches a station with no heatwave in any year, which gets missing instead of 0. **Not
  copied** (decided 2026-11-13, #51). Python drops the rule. Instead, `hw_aspects` makes a
  season missing when none of its days has a usable value, and `tx90_tn90_heatwaves`
  treats a day without a threshold as having no usable value (thresholds are only read on
  heatwave days, so nothing else changes). A station without base-period thresholds
  writes no heatwave files at all (`InsufficientBaseData`), in R as in Python. On all 15
  reference runs every Tx90 and Tn90 series has a heatwave in at least one year and no
  threshold is missing, so R's rule never fires and no reference file changes.
- In the Southern Hemisphere the last year is always missing (its season is incomplete).
- Each year is multiplied by the variable's climdex annual mask (`namasks$annual$tmax` for
  TX90, `tmin` for TN90). Missing days within the season are not otherwise checked (R's
  25-day rule is commented out). A southern season is masked by its first year only, so
  January-March data missing in Y+1 do not affect year Y. **Kept deliberately for R parity**
  (decided 2026-11-13, #51): see below.
- All-missing files are still written (see [Writing output files](#writing-output-files)).
  On `new_delhi`, no TN year passes the climdex annual rule, so all five `TN90-` files are
  `-99.9` throughout, in R as in Python.

**Result.** All 10 files pass on all 14 runs where R wrote them (none for `nairobi`) and
are text-identical to R's: `HWN`, `HWF` and `HWD` at `EXACT`, `HWM` and `HWA` at `CLOSE`.
The reference runs exercise the pre-season and post-season branches but not the 14-day cut,
the whole-season run, HWM ties, a station without heatwaves, or missing flags and values
inside a heatwave. `tests/test_heatwaves.py` checks the reproduced
branches against `get.hw.aspects` output printed by R (`tests/data/r_hw_aspects.R`) for
both hemispheres; for the two behaviours not copied it checks the corrected values
instead (the whole-season heatwave in both hemispheres, under way before the season and
starting on its first day; a series without heatwaves; a season without usable values).

**R behaviour kept deliberately for R parity** (decided 2026-11-13, #51). These look like
R bugs but are reproduced so that the files match R's:

1. **Southern season masked by its first year only.** `get.hw.aspects` multiplies year Y's
   aspects by `namask[Y]` (`calculate.hw`, `namasks$annual$tmax`/`tmin`), but a southern
   season runs from November Y to March Y+1. Missing data in January-March Y+1 never mask
   year Y, and year Y+1's mask applies to a season that is mostly in Y+1's November and
   December. `hw_aspects` multiplies by the same per-year mask. A season can therefore
   have a value although up to three of its months fail the climdex monthly rule.
2. **Pre-season heatwave with 1 or 2 days in the season.** The two tests after `truevals`
   in `get.hw.aspects` (`extended_boolean[1:2] == TRUE, extended_boolean[3] == FALSE` and
   `extended_boolean[1] == TRUE, extended_boolean[2] == FALSE`, each with the days before
   the season TRUE) add the first run of the season even when only 1 or 2 of its days are
   in the season. `season_aspects` does the same, so a season can have HWD 1 or 2, below
   the 3-day minimum, and those days count in HWN, HWF, HWM and HWA.

R behaviour not copied (also #51) is described above: the whole-season heatwave and the
all-missing HWN/HWF; both are listed under
[R behaviour not to be copied](#r-behaviour-not-to-be-copied).

### EHF heatwaves and the daily EHF/ECF series

Climpact's `climdex.hwEHF` (`climpact.etsci-functions.r`, line 936; Nairn and Fawcett
2015), driven by `services/calculate/calculate_hwEHF.R` and written by `write.hwEHF.csv`.
Ported directly in `products/ehf.py` (`ehf_heatwaves`, `excess_factors`, `heatwaves`,
`annual_aspects`).

**Not the Tx90/Tn90 machinery.** In Climpact 3.4.3, `climdex.hwEHF` does not call
`get.hw.aspects` and does not use the `HW_TAVG90` thresholds. It has no extended summer:
heatwaves are counted in calendar years, in both hemispheres. Its aspects are HWN, HWF,
HWD, HWMD (mean duration), HWPI and HWLI (peak and load intensity) and HWPS and HWLS
(peak and load severity). None of `hw_aspects`, `season_aspects` or `summer_days` applies,
so neither the #51 changes nor the Tx90/Tn90 quirks kept for parity affect EHF. R's EHF
code already gives HWN and HWF 0 in a year without heatwaves.

**Thresholds.** TAVG is `(TX + TN) / 2` on every day, 29 February included. `T95` and
`T05` are single numbers: R `quantile(type = 7)` of TAVG over every day of the base-period
years (`r_quantile_type7` in `thresholds.py`, a port of `quantile.default`).
`ci@quantiles$tavg$q95` is never set in station mode, so R always computes them here.
`EHF85` is the type-7 85th percentile of the positive base-period EHF values. R computes
nothing (no files) when TAVG is present on fewer than half of the days counted by
`difftime(base end, base start)` (10,956 days for 1971-2000, one fewer than the period
has).

**Daily values** (`excess_factors`). From the 33rd day of the series, with `T3` the mean of
TAVG on the day and the two before it, and `T30` the sum of TAVG on the 30 days before
those:

```
EHF = max(1, T3 - T30 / 30) * (T3 - T95)
ECF = min(-1, T3 - T30 / 30) * -(T3 - T05)
```

The first 32 days are missing. `T3` is missing if any of its days is missing. `T30` is
`sum(..., na.rm = TRUE)`, so missing days are dropped but the sum is still divided by 30
(reproduced; see below). The arithmetic follows R exactly: the three-day sum is
`sum(a, b, c)` of three arguments, which R adds in double precision; the 30-day sum is
one vector `sum`, accumulated in extended precision (`r_sum`). With a long-double
three-day sum, 1,896 written values of `lat0` would differ in the last digit; with a
numpy 30-day sum, 4,024.

**Heatwaves** (`heatwaves`). A heatwave is a run of days with EHF > 0 plus the two days
before it (Nairn and Fawcett's three-day period), so the shortest is 3 days. A heatwave
starting no later than the day after the previous one ends is joined to it, so heatwaves
up to two days apart become one. A heatwave crossing 31 December is split into one piece
per calendar year, and each piece counts in its own year (HWN in both). R keeps the
heatwaves within one year in place and appends the pieces to the end of its list; the
order decides the last digit of means and sums, and is reproduced. A missing EHF ends a
run of positive days, and a missing TAVG makes three days of EHF missing, so two runs can
never be joined across a missing day. Only a heatwave's two leading days can have a
missing EHF; they count in its duration.

**Aspects** (`annual_aspects`). Per heatwave (piece): duration = number of days; peak
intensity = largest EHF; load intensity = sum of the positive EHF values; severity =
EHF / `EHF85`, its peak and sum over the positive days. Per year: HWN the number of
heatwaves, HWF the sum of durations, HWD the longest, HWMD the mean duration, HWPI and
HWPS the mean of the peaks, HWLI and HWLS the sum of the loads (R's extended-precision
`mean` and `sum`). In a year without heatwaves HWN and HWF are 0 and the others missing.

**Missing data.** Every aspect is multiplied by the product of the TX and TN climdex
annual masks, and the first year is always missing (`namask[1] = NA`, because its first
32 days have no EHF). No other check is made: missing days in the 30-day window or the
leading days are not counted. R writes no file when HWF is missing in every year (it is
then missing for `new_delhi`, where no TN year passes, and `nairobi`); otherwise it
writes all ten files, even an aspect that is missing in every year (`_HEATWAVE_FILE`).

**Result.** All ten files pass on all 13 runs where R wrote them and are text-identical to
R's: `EHF-HWN`, `EHF-HWF` and `EHF-HWD` at `EXACT`, the other six aspects and the two
daily files at `CLOSE`. No file needs a looser tier. The reference runs exercise joined
heatwaves (7 to 33 per run), heatwaves split at 31 December (`lat0`/`sydney` 9,
`alice_springs` 14, `darwin` 5, `perth` 10), the lead-days-only pieces below and missing
days in the 30-day window. `tests/test_ehf.py` checks every aspect, `EHF85` and two
months of daily EHF and ECF bit for bit against `climdex.hwEHF` itself, run by
`tests/data/r_ehf.R` on a synthetic station (`tests/data/ehf_synthetic.txt`, made by
`tests/data/make_ehf_synthetic.py`) with each of these cases, missing leading days, a
year without heatwaves, a masked year, and the R error below.

**R quirks reproduced for parity that look like bugs (decision pending).**

1. **`T30` divided by 30 whatever the number of missing days.** Missing days in the
   window lower the acclimatisation term instead of being left out. Dividing by the
   number of days present would change 380 annual values (HWPS, HWPI, HWLS, HWLI) on 7
   runs (`lat0` and `sydney` 186 each, `darwin` 126, `alice_springs` 28, `oxford` and
   `dublin` 12 each, `madrid` 4) and daily values on all 13 runs (`oxford` 5,883,
   `dublin` 2,733, `lat0` 1,144, ...).
2. **A heatwave whose first positive EHF day is 1 or 2 January gives the previous year a
   1- or 2-day heatwave** made of its leading days only: it counts in HWN, HWF, HWD and
   HWMD but has no intensity or severity (`if (all(heatwave_values <= 0))`). Dropping
   such pieces would change 60 values: `lat0` and `sydney` 21 each (7 pieces),
   `alice_springs` 18 (6), `perth` 12 (5), `darwin` 9 (3).
3. **29 February is in the calculation**, although both daily files say "Note that 29th
   February is omitted from this calculation." The description is reproduced. Dropping
   29 February (as `climdex.hw` does) would remove 15 to 20 rows from every daily file and
   change the annual values of `perth` (255), `darwin` (124), `lat0` and `sydney` (42
   each), because `T95` and the windows change.

**R behaviour not copied.** When the leading days of a heatwave piece include a missing
EHF and no positive one (a heatwave whose first positive day is 1 or 2 January, with TAVG
missing on 28 or 29 December), `all(heatwave_values <= 0)` is `NA` and R stops with
"missing value where TRUE/FALSE needed", so no EHF file is written (and in the app the
rest of the run stops). Python treats the piece as one without positive EHF (duration
only). No reference run has such a piece; `tests/test_ehf.py` checks R's error message.

### Growing season length (gsl)

climdex.pcic's `climdex.gsl` and `growing.season.length` (`R/threshold_indices.R`), which
Climpact does not override. `index.calc` calls it with the default `gsl.mode = "GSL"` and
`include.exact.dates = TRUE` (gsl is in `exact_date_indices`, `server/global_variables.r`),
so the file has the columns `time, start, sl, end` and no standardised column. TM is
`(TX + TN) / 2`, computed by `climdexInput.raw`. Ported directly in `products/indices.py`
(`growing_season_length`, `season_length`, `southern_gsl_mask`).

**Season.** In the Northern Hemisphere (`lat > 0`) a season is a calendar year. The start
is the first day of the first run of at least 6 days with TM **>** 5 °C that lies before
1 July; the end is the first run of at least 6 days with TM **<** 5 °C from 1 July. In the
Southern Hemisphere (latitude 0 included) the season runs from 1 July of the labelled year
to 30 June of the next (`years.gsl <- years - floor((12 - months) / 6)`), the start is
searched in July-December and the end from 1 January. January-June of the first year are
not used. Reproduced, including:

- runs are found within each half separately (`select.blocks.gt.length` on the two halves),
  so a warm run crossing the transition date needs 6 days before it, and a cold run 6 days
  after it;
- a missing day breaks a run (NA counts as FALSE);
- a day of exactly 5 °C is neither warm nor cold;
- with no start the length is 0 and the dates are missing; with a start but no end the
  season ends on its last day;
- a season without a day in the transition month is missing; in the south this is always
  the last season (July-December only), so the last year is missing.

**Dates.** The start date is the first day of the warm run. The end date is computed from
`end`, a 1-based day number, as `origin + end` days, so it is one day later than the day
`end` numbers. When a cold run is found, `end` is the day before the cold run and the
reported end date is the **first day of the cold run** (`end - start = sl`); when none is
found, `end <- ts.len - 1` and the end date is the season's last day (`end - start = sl - 1`).
Reproduced (see the quirks below).

**Missing data.** The north uses the climdex annual TM mask (`namasks$annual$tavg`, our
`valid_mask(ds.tas, freq="YS")`). The south builds its own mask for July-June seasons, with
`max.missing.days["annual"]` (15 days) applied both to the season and to each of its
months, and the last season set missing. A month with 4-15 missing days therefore does not
make a southern season missing, where it makes a northern year missing. Reproduced. Where
the length is missing, so are both dates; as for cdd/cwd, the file is written unless every
value is missing (R wrote none for `new_delhi` and `nairobi`, nor does Python).

**Not using xclim.** xclim's `growing_season_length` (`xclim.compute`) uses a start
condition and its complement for the end: with `op=">"` the season ends on TM ≤ 5 °C.
It differs from R in 8 of 60 years on `minneapolis` (2 on `potsdam` and `madrid`, 4 on
`yakutsk`, 1 on `beijing`). These are all days of exactly 5.0 °C: with the end test changed
to ≤ 5, the port agrees with xclim in every year where both have a value. xclim also
returns no dates, and in the south (`freq="YS-JUL"`) adds a partial first season starting
in the July before the data and applies the climdex mask, not `climdex.gsl`'s.

**Result.** `gsl_ANN` passes at `EXACT` and is text-identical to R on all 13 runs where R
wrote it, 8 of them northern (`minneapolis`, `yakutsk`, `phoenix`, `madrid`, `potsdam`,
`oxford`, `dublin`, `beijing`). No reference run has a season with length 0, a southern
season ending in a cold run, or a cold run starting on the transition day.
`tests/test_gsl.py` covers these and the other rules above with values printed by R
(`tests/data/r_gsl.R` on `tests/data/gsl_synthetic.txt`) at latitudes 45, 0 and -30.

**R quirks that look like bugs, reproduced for parity (decision pending).**

1. **End date is the first day of the cold run.** When a cold run ends the season, the
   reported end date is one day after the season's last growing day, while a season with
   no cold run reports its last day. Correcting it (end = start + sl - 1 in both cases)
   would change the `end` column of 295 rows across the 7 northern runs with a cold-run
   end (`minneapolis` 60, `potsdam` 60, `yakutsk` 57, `beijing` 52, `dublin` 27, `oxford`
   23, `madrid` 16); `sl` would not change, and no southern reference row is affected.
2. **Southern months checked with the annual 15-day limit.** `climdex.gsl` passes
   `max.missing.days["annual"]` to the monthly `get.na.mask` of a southern season. With the
   climdex monthly limit of 3 days, season 1996 of `lat0` and `sydney` would become missing;
   no other reference row changes.

### SPI and SPEI

**Which R code runs.** Climpact 3.4.3 computes SPI and SPEI in `calculate.spi` and
`calculate.spei` (`services/calculate/calculate_spi.R`, `calculate_spei.R`) with its own
copy of the SPEI package's old fitting function, `cspei` (`services/calculate/custom_cspei.R`;
`cspi` in `custom_cspi.R` is `cspei` with a Gamma distribution). `climdex.spi` and
`climdex.spei` in `climpact.etsci-functions.r` are never called, and neither is the SPEI
package's current `spei()`. `cspei` uses lmomco 2.5.7 (`pwm.ub`, `pwm2lmom`,
`are.lmom.valid`, `parglo`, `cdfglo`, `lmom.ub`, `pargam`, `cdfgam`) and SPEI 1.8.1's
`hargreaves` and `kern`, the versions in the reference image. Ported directly in
`products/drought.py` (`monthly_inputs`, `hargreaves`, `accumulate`, `cspei`,
`standardise_month` and one function per lmomco function); the scales are 3, 6, 12 and
`IndexParams.spei_months`.

**R behaviour reproduced:**

- **Monthly inputs ignore the missing-data rules.** Precipitation is the total of the
  days present (`sum(na.rm = TRUE)`), missing only when every day of the month is
  missing; TX and TN are the means of the days present. R's extended-precision `sum` and
  `mean` are used (`r_sum`, `r_mean`).
- **PET** (SPEI only) is `hargreaves(Tmin, Tmax, lat = latitude, Pre = prec)`: the
  Droogers and Allen (2002) form `0.0013 * 0.408 * Ra * (Tmean + 17) * (Tr - 0.0123 P)^0.76`
  times the days in the month, with extraterrestrial radiation `Ra` from the station
  latitude. This is why `lat0` and `sydney` have different SPEI files (their SPI files are
  identical). ET0 is 0 when `Tr - 0.0123 P` is negative (wet months) and missing when TX,
  TN or precipitation is. The inputs are plain vectors, so `hargreaves` assumes every year
  is a non-leap year: February always has 28 days and the mid-month day of year is fixed.
  At polar latitudes the sunset hour angle is 0 (polar night) or the series maximum
  (`omegas[sset < -1] <- max(omegas)`), as in SPEI.
- **Accumulation** (`accumulate`): `sum(data[t:(t - scale + 1)] * kern(scale))` with
  rectangular weights `1 / scale`, so the accumulated value is the *mean* of the last
  `scale` months, multiplied first and summed newest month first in extended precision.
  Any missing month in the window makes it missing; the first `scale - 1` months are
  missing.
- **Fit window.** The fit uses `window(data, base start, base end)` and accumulates again
  inside that window, so the first `scale - 1` months of the base period have no
  accumulated value and are left out of the fit (one or two of the 30 base years per
  calendar month, at 24 months).
- **Per calendar month** a distribution is fitted by unbiased probability-weighted
  moments: `parglo` (generalised logistic) for SPEI; for SPI, `pargam` of `lmom.ub` (a
  two-parameter Gamma, from lmomco's direct L-moment formula rather than the PWMs) fitted
  to **all** base values, zeros included. Each value then becomes `qnorm(cdfglo(x))`, or
  `qnorm(pze + (1 - pze) * pnorm(qnorm(cdfgam(x))))` for SPI, where `pze` is the fraction
  of zeros among the base values.
- **Months without a fit.** A calendar month with fewer than two base values, invalid
  L-moments (for example all values equal, `L2 = 0`) or a NaN L-moment (fewer than five
  values: `pwm.ub` divides 0 by 0) is skipped (`next`), so all its values are missing.
- **Infinite values are missing.** A value outside the fitted distribution's support or
  with probability 0 or 1 gives `qnorm` of 0 or 1, which `calculate.spi`/`calculate.spei`
  turn into `NA`.
- **Files** (`write.precindex.csv`): `time, spi` (or `spei`), no standardised column,
  written unless every value of all four scales is missing, so a scale missing throughout
  is still written. Nothing is calculated when all precipitation (SPI) or all of TX, TN
  or precipitation (SPEI) is missing. A custom scale of 3, 6 or 12 writes the same file
  twice in R; Python builds it once.

**Exact arithmetic.** R's distribution functions differ from scipy's in the last bits
(scipy's `ndtri`, `ndtr` and `gammainc` disagree with R on 469 of 706, 275 of 706 and 261
of 400 test values), which changes the 15th significant digit of about 40% of SPI values.
`climpact.rdist` ports R 4.6.1's `qnorm` (AS 241), `pnorm` (Cody), `dnorm` and `pgamma`
(Welinder's algorithm, with `dpois_raw`, `ebd0`, `stirlerr`, `lgamma1p`, `log1pmx` and
`lgammafn`). R's `stirlerr` calls the C library's `lgamma`, and CPython's `math.lgamma` is
its own implementation, so glibc's `lgamma` (fdlibm `e_lgamma_r.c`) is ported too
(`libm_lgamma`). The lmomco and SPEI functions follow R's operation order, including
`pi * LCV^2` and `5 * TAU3^2` (squared first). On Linux x86_64 with glibc, all 1,812 R
test values (`tests/data/r_rdist.R`) are reproduced bit for bit.

**The C maths library.** The remaining operations call the C library's `exp`, `log`,
`log1p`, `expm1`, `pow`, `sin`, `cos`, `tan` and `acos`, as R does. Python's `math`
calls the same functions, so on glibc x86_64 (R's platform for the reference, and CI)
every SPI and SPEI value is identical to R's. macOS's library differs from glibc in the
last bit for some inputs (for example `sin`, `cos`, `tan` and `acos` on 5-35% of
inputs), which changes the 15th significant digit of up to about 60% of the values of a
file; the largest relative difference on the 15 runs is 2.7e-11. Correctly rounded
replacements were tried and rejected: glibc is not exactly correctly rounded either (about
0.1% of `exp`, `log` and `sin` inputs differ by one ulp), so they left 551 differing
values on macOS. `test_csv_text` therefore requires text identity for these files only on
glibc x86_64 (`tests/libm.py`); elsewhere their numeric fields must agree to 1e-10
relative plus 1e-12, with identical missing values. `test_drought.py` and `test_rdist.py`
are bit-exact on glibc x86_64 and use the same tolerance elsewhere.

**Result.** All 8 files (`3month_spi_MON`, `6month_spi_MON`, `12month_spi_MON`,
`24month_spi_MON` and the same for `spei`) pass at `CLOSE` on all 15 runs (120 files),
with identical missing values. On glibc x86_64 every file is text-identical to R's; on
macOS the largest difference is 2.4e-12 absolute and 2.7e-11 relative (`perth` and
`sydney` SPEI), all well inside `CLOSE`. No file needs the `FITTED` tier. The runs
exercise dry months mixed in with the zero probability (`phoenix`, `alice_springs`,
`darwin`, `madrid`, `new_delhi`), partial months and long gaps (`oxford`, `dublin`,
`new_delhi`, `nairobi`) and latitudes from 33.9 S to 62 N. `tests/test_drought.py` checks
`cspei` (scales 1, 3, 24) and `hargreaves` (latitudes 0, -33.86, 62, 75, -80) against R
(`tests/data/r_drought.R`) on a synthetic series with a calendar month never fitted
because all base values are 0, one with only four base values, dry months, missing months,
an infinite value and polar night.

**R quirks reproduced for parity that look like bugs (decision pending).** Numbers are
the values (rows of the 8 files) that would change on the 15 runs.

1. **No missing-data rule for the monthly inputs.** A month with one day of
   precipitation gets that day as its total, which biases SPI low. Applying the climdex
   monthly rule (more than 3 missing days) would change 2,603 values on each of `lat0`
   and `sydney`, 2,415 on `dublin`, 2,189 on `oxford`, 262 on `beijing`, 176 on `yakutsk`,
   121 on `alice_springs` and 53 on `darwin`, and every value of `new_delhi` and `nairobi`,
   whose SPEI files would no longer be written; none on `minneapolis`, `phoenix`, `perth`,
   `madrid` or `potsdam`.
2. **The first `scale - 1` base-period months are left out of the fit.** Accumulating
   over the whole series before taking the base-period window would change about 60% of
   all values on every run except `new_delhi` (3,155 to 4,718 values per run; `nairobi`
   1,483).
3. **The Gamma distribution is fitted to the zeros as well** and then mixed with the zero
   probability, so zeros count twice; the usual method (and later SPEI versions) fits
   the non-zero values. Fitting the non-zero values would change SPI in calendar months
   with zero accumulations: `phoenix` 346 values, `new_delhi` 190, `alice_springs` 171,
   `darwin` 148, `madrid` 59, none elsewhere.
4. **Leap years are ignored in PET.** Passing a monthly `ts` (as SPEI expects) would give
   leap Februaries 29 days and SPEI's own mid-month days, changing almost every SPEI value
   on every run (3,799 values on `lat0`, about 2,800 on the 60-year runs).
5. **`std[f] <- NA`** in `cspei` (for a month with no base values) indexes the output with
   positions in the base-period window rather than the series. Because the series and
   the window both start in January it only touches values of the same calendar month,
   which are still missing at that point: no effect on any output.

**R behaviour not copied** (none is reachable on the reference runs): when `pargam`
returns no parameters (`L1 <= L2`) or `are.parglo.valid` fails, R stops with an error
(`cdfgam` on `NULL`, or a zero-length replacement), ending the SPI/SPEI calculation;
Python leaves that calendar month missing. When the base period lies wholly outside the
series, R's `window` stops with an error; Python writes no SPI/SPEI files.

### Trend file

**Which R code runs.** R writes `trend/<station>_trend.csv` as a side effect of plotting.
`index.calc` (`services/calculate_indices.R`, lines 25-28) writes the header block
(`Linear trend statistics`) and the column row; `plot.call` (`services/plot_indices.R`)
computes the trend of each plotted series into the global `mktrend` (and `DJFtrend` ...
`SONtrend` for monthly series), and `index.calc` appends a row per index when `mktrend`
exists, then removes it. `plot.precindex` (`services/plot_prec_index.R`) writes the SPI and
SPEI rows itself, and `calculate.custom.index` the custom-index rows. The trend is zyp
0.11-1's `zyp.sen(y ~ x)` (slope) and `confint.zyp(zsen, level = 0.95)` (bounds), which
calls Kendall 2.2.2's `Kendall(x, y)` for `Var(S)` (the versions in
`r-package-versions.csv`). Ported directly: the algorithms in `climpact.trends`
(`sen_slope`, `kendall_var_s`, `confint_zyp`, `min_trend_data`, `sen_trend`), and R's
row sequence, globals included, in `products/trends.py` (`trend_file`, a derived product
built from the other products' tables).

**The calculation.**

- `x` is `0, 1, 2, ...` over the whole series (years, months, or days of year for
  `tx95t`), with the missing values and their `x` left out, so the slope is per year for
  annual series and per month for monthly ones.
- **Slope:** the median of the pairwise slopes `(y[j] - y[j+i]) / (x[j] - x[j+i])`; R's
  `median` of an even count is R's extended-precision `mean` of the two middle values
  (`r_mean`).
- **Bounds:** `c = sqrt(Var(S)) * qnorm(0.975)` (R's `qnorm`, `climpact.rdist.qnorm`),
  and the bounds are the sorted slopes at positions `round((n' - c) / 2)` and
  `round((n' + c) / 2)` (1-based, round half to even), `n'` the number of slopes.
- **`Var(S)`** comes from Kendall's Fortran `TAUK2`, which receives `x` and `y` as
  single-precision `REAL`s and computes `Var(S) = (n(n-1)(2n+5) - sum t(t-1)(2t+5)) / 18 + ...`
  in float32. Ties are therefore decided in float32 (values equal as floats tie), and
  for a monthly series (`n = 960`) `n(n-1)(2n+5)` is about 1.8e9, above float32's exact
  integer range, so `Var(S)` is rounded. `kendall_var_s` reproduces this with numpy
  float32 in the Fortran's order. `TAUK2` computes `Var(S)` only when neither series is
  constant (its `SW` flag is true when every value is equal, though its comment says
  "has no ties"); for a constant series `Var(S)` stays 0 and both bounds equal the
  median slope (0), as R prints (`IFAULT = 12`).
- **`min_trend_data`:** a trend needs at least 10 values and at least 70% of the series
  (`min_trend`, `min_trend_proportion`, `server/global_variables.r`); otherwise the row
  is written with `NA` bounds and slope.
- Numbers are written by `paste`, which formats them as `as.character` (15 significant
  digits, `format_r_number`); missing ones as `NA`.

**Which rows R writes, in order** (all reproduced):

- One row per index file of `climate.indices.csv`, in its order, with frequency `annual`
  or `monthly`; `tx95t` has frequency `NA` (its `Annual.flag` is empty) and is a "trend"
  over the 365 days of the year. There is no row when the plotted series is missing
  throughout (`plot.call` returns before `mktrend` is set): this matches the index files
  R does not write. The series is the index column, or `val`, `duration` or `sl` for the
  indices with dates (`exact_date_indices`).
- After the row of a monthly index, `DJF`, `MAM`, `JJA` and `SON` rows. `plot.call` builds
  the seasons with zoo: each month is shifted forward one month (`as.yearqtr(yearmon +
  1/12)`), the last month of the series is dropped, and months are grouped by quarter, so
  **December counts towards the next year's DJF** and DJF of year Y is December Y-1,
  January Y and February Y. A season needs all three months; the first DJF (no previous
  December) is therefore always missing, and the final December is in no season. A
  season's value is `max` for `txx`, `tnx`, `rx1day`, `rx5day`, `min` for `tnn`, `txn`,
  `sum` (`r_sum`) for `su`, `tr`, `txge30`, `txge35`, `r10mm`, `r20mm`, `prcptot`, and
  `mean` (`r_mean`) for every other index (`seasonal_series`, `season_function`). Each
  season has its own `min_trend_data` check.
- Tx90/Tn90 heatwaves: none (`plot.hw`'s trend line is commented out).
- EHF heatwaves: none (`calculate.hwEHF` calls `plot.call` but writes no row).
- SPEI, then SPI (`plot.precindex`): no row for the whole series. For each scale that is
  not missing throughout: for 3 months, the February, May, August and November values
  labelled `FEB`, `MAY`, `AUG`, `NOV`; for 6 months, the August and October values
  labelled `APR` and `OCT`; for 12 months, the January and December values labelled
  `JUN` and `DEC` (January first). The index is `spi3`, `spei12` and so on. The custom
  scale (`spei_months`, 24) writes no rows.
- The custom index, `annual` then `monthly` with its seasons, as an index.
- `StartYear` and `EndYear` are the first and last years of the series.

**R quirks reproduced that look like bugs.** Numbers are the rows of the 15 reference
trend files that fixing each would change.

1. **SPI/SPEI season labels.** The 6-month rows labelled `APR` hold the August values,
   and the 12-month rows labelled `JUN` hold the January values. Fixing the labels (or the
   months) would change the 4 rows `spi6`/`spei6` `APR` and `spi12`/`spei12` `JUN` on
   every run: 60 rows.
2. **The seasonal function is chosen by output name.** `plot.call` tests for `rxnday` and
   `rnnmm`, but the names it is given are `rx3day` and `r30mm`, so their seasons are
   means rather than a maximum and a sum. Fixing it would change 63
   rows: rx3day's seasons on the 13 runs with rx3day files, and r30mm's on `lat0`,
   `sydney`, `minneapolis`, `darwin` and `beijing` (elsewhere its seasonal slopes and
   bounds are 0 or `NA` either way).
3. **Counts are summed or averaged inconsistently.** `su`, `tr`, `txge30`, `txge35`,
   `r10mm`, `r20mm` seasons are sums, but `fd`, `id`, `tnlt2`, `tnltm2`, `tnltm20`,
   `tmge5`, `tmlt5`, `tmge10`, `tmlt10` and the custom index are averaged, which divides
   their seasonal slopes by 3. Summing them would change
   177 rows on 12 runs (none on `darwin`, `new_delhi` and `nairobi`, where these seasonal
   trends are 0 or `NA`).
4. **The custom SPI/SPEI scale.** Only the scales 3, 6 and 12 have rows, so the custom
   scale has none, and a custom scale of 3, 6 or 12 repeats that scale's rows. No
   reference output changes (all use 24), unless the custom scale got its own rows
   (then 8 more rows per run with SPI and SPEI).
5. **`mktrend` left behind by the EHF heatwaves.** `calculate.hwEHF` never removes
   `mktrend`, so the trend of the last EHF aspect with a value stays in the global. It is
   removed by the first SPEI or SPI scale with a value; if there is none and `tmm` is
   missing in every year, `index.calc` writes the EHF trend as `tmm`'s annual row.
   Reproduced; no reference run reaches it (unit test `test_ehf_trend_left_in_mktrend`).
6. **`tx95t` gets a trend** across the days of the year of a threshold climatology,
   which is not a trend in time. Dropping it would remove 1 row per run (15 rows).

**R behaviour not reproduced** (none is reachable on the reference runs or with a
successful R run):

- `plot.call` runs inside `tryCatch(..., warning = ...)` in `index.calc`. A warning or
  error after `mktrend` is set and before the seasons are computed would leave the
  previous monthly index's `DJFtrend` ... `SONtrend` to be written with this index's
  row. Python computes every season. No warning or error occurs on any reference run
  (the trend files match), and none is expected for valid series.
- `plot.precindex` builds its seasonal table from the global `monthsGLOB`/`yearsGLOB`
  set by the last monthly `plot.call`; if no monthly index had a value, R stops with an
  error and writes no SPI/SPEI rows or later rows. Python takes the months from the
  SPI/SPEI table.

**Exact inputs.** The trend of a series depends on every bit of its values, not just the
15 digits written to the index files. prcptot and the degree days (hddheat, cddcold,
gddgrow) were computed with xclim, whose sums gave text-identical index files but
differed from R's extended-precision `sum` in the last bits, which changed 6 rows of the
`lat0` trend file (for example `prcptot,DJF` slope `0.02` against R's
`0.0199999999999989`). They are now summed with `r_sum` like sdii (`wet_day_total`,
`degree_days` in `products/indices.py`), and every index file stays text-identical.

**Result.** `trend/trend` passes at `CLOSE` and is text-identical to R's on all 15 runs
(on glibc x86_64; see below). `tests/test_trends.py` checks `sen_slope`,
`kendall_var_s` and `confint_zyp` bit for bit against zyp and Kendall on synthetic series
(`tests/data/r_trends.R`: few values, many ties, a 960-value tied series where float32
rounding matters, a constant series, values tied only in float32, missing values, and
three values, where `confint.zyp`'s lower index is 0 and R recycles the upper bound into
both bounds), `seasonal_series` against `plot.call`'s zoo code, hand-computed slopes,
and the row rules no reference run exercises.

**Platform.** The SPI and SPEI rows are computed from the SPI and SPEI values, which on
platforms other than glibc x86_64 differ from R's in the last bits (see
[SPI and SPEI](#spi-and-spei)). On macOS, 0 to 8 SPEI rows per run differ from R's in the
last one or two digits (relative differences below 1e-13); SPI rows and all other
rows are identical. `test_csv_text` therefore applies the libm tolerance (1e-10 relative)
to the lines of the trend file that start with `spi` or `spei`
(`LIBM_SENSITIVE_LINES`), and only on those platforms; on glibc x86_64 (CI) the whole
file must be text-identical.

### Station input

| R behaviour | Python |
| --- | --- |
| Commas are treated as separators; a header row is skipped when the first field is not an integer | same |
| Values equal to `-99.9` are missing | same |
| Rows with an invalid date (e.g. 29 February in a non-leap year) are dropped | same |
| `qualityControlCheck` merges the rows onto the dates from the first row's date to the last row's date (`merge(dffull, user_data, by = "dates", all.x = TRUE)`): rows dated outside that range are dropped, which only happens when the file is not in date order | same (`io.station.merged_rows`, used by `station_dataset` and the QC checks). A file whose last row is dated before its first row is an error, as R's `seq` fails |
| A date that appears more than once keeps all its rows, in file order, through both merges; `create.filled.series` then keeps the last, even when it is missing. The QC step lists the repeats (`qc/duplicates`) | same: the indices use the last row of each date in file order, the QC checks see every row. Checked on the `qc_stress` run, whose index files match R's (see [Reference outputs](#reference-outputs)) |
| The time axis is padded to whole years; padded days count as missing | same |
| `northern.hemisphere = latitude > 0`, so latitude 0 is treated as Southern Hemisphere | same (`StationMetadata.northern_hemisphere`); matters for gsl and heatwaves |
| `qualityControlCheck` stops with "Years are not in ascending order" when they are not | the check runs after the merge, which sorts the rows, so it never fires; Python has no such check either |
| `read_user_file` reads the columns with `read.table`, whose default `na.strings = "NA"` makes an `NA` value missing | `read_station_rows` raises `ValueError` on `NA` (numpy cannot convert it); the web app's step 1 refuses the file and asks for -99.9 at the line (#76); reading `NA` as missing is #99. Files written as Climpact documents them (-99.9) are unaffected |
| A UTF-8 byte-order mark is kept by `readLines`, so the first row's first field is not an integer and the first data row is skipped as a header | same in the core; the web app stores uploads without the BOM, so it keeps that row |

### Output files

| R behaviour | Python |
| --- | --- |
| Values are written with 15 significant digits and `-99.9` for missing | same, including R's digit-count quirk (`format_r_number`); tables in memory hold full-precision floats |
| No file is written when an index is missing for every period (`write.index.csv`; heatwave files differ, below) | same (`write_outputs`); `build_all` still returns the all-missing table. Exercised by `oxford`, `new_delhi` and `nairobi` |
| A 7-line metadata header (version, date of calculation, ...) | same; `Climpact_version` is `3.4.3`. Ignored by the table comparison; only `Date_of_calculation` is ignored by the text comparison |
| `tx95t_DAY`: `write.index.csv` writes the row names of an unnamed vector as `time`, so every `time` is `-99.9` | reproduced: `time` is missing on every row |
| `thres.csv` is written by a plain `write.table`: no metadata header, missing values as `NA` (not `-99.9`), and each precipitation threshold repeated on all 365 rows (`as.data.frame` recycling) | reproduced; `write_outputs` writes it with no header and `NA` (`_DESCRIPTIONS`/`_NA_TOKENS` in `io/output_files.py`) |
| `write.hwEHF.csv` writes the eight EHF files and `EHFdaily`/`ECFdaily` unless HWF is missing in every year; the daily files are joined by `","`, and their description says 29 February is omitted, though it is not | reproduced (`_HEATWAVE_FILE`, `_SEPARATORS`, `_EHF_DESCRIPTIONS`) |
| `write.hw.csv` writes the ten Tx90/Tn90 heatwave files with `time, <aspect>` columns (no standardised column) and writes them even when one is missing in every year | reproduced (`_HEATWAVE_FILE` in `io/output_files.py`). Exercised by `new_delhi` |
| `write.precindex.csv` writes the four SPI (SPEI) files with `time, spi` columns and no standardised column, all four unless every value is missing | reproduced (`_PRECINDEX_FILE`, `_PRECINDEX_DESCRIPTIONS`) |
| The trend file is written with `cat(paste(..., sep = ","))`: no spaces after commas, `NA` for missing, numbers as `as.character` | reproduced (`_SEPARATORS`, `_NA_TOKENS`); the reader treats `NA` as missing in numeric columns |
| `index.calc` writes a PNG per plotted series and `<station>_all_plots.pdf`; the app zips the station folder | written with `--plots` and `--zip`, under R's names; drawn differently (see [Plots and zip archive](#plots-and-zip-archive)) |

### Sector correlation

| R behaviour | Python | Effect |
| --- | --- | --- |
| `calculateDeTrendValues` takes the slope from `lm`, whose QR decomposition runs in the image's OpenBLAS (`dnrm2`, `ddot` in SIMD order) | `detrend` uses the exact least-squares slope, rounded once to a double (`fractions`), the same on every platform | R's slope for the sample wheat file is 1 ulp above the exact one (0.016154604888782106 against ...103). One detrended value of 64 (1994) differs in the 15th significant digit; the detrended column is compared at `CLOSE`. Correlations, rounded to 2 decimals, are identical |
| `cbind` pairs the station's years (sorted) with the sector rows **by position**, so a sector file not in year order, or with a year twice, silently pairs values with the wrong years (or stops on a row-count mismatch) | `SectorData` refuses years that do not increase from row to row (`SectorCorrelationError`) | an error instead of wrong numbers; files in year order, as the sample, are unaffected |
| With more than two columns, R's detrended column is the file's third column and the file names take its name (`[2:3]`) | `read_sector_file` refuses a file without exactly two columns | an error instead of wrong numbers |
| `Year` must be the first column's name (`filter(Year %in% ...)` fails otherwise, with an R error) | same requirement, with a clear message | none |
| When an index has no year in common with the sector data, R stops after writing the four scatter files | the error is raised before anything is written | no partial `corr/` folder |
| The plots are drawn with ggplot2 (red points, black line, equation in the plot) | drawn with matplotlib in the style of the index plots, under R's file names; the equation and R² (rounded to 2 decimals, as R) under the plot | look only |

### Gridded data

The gridded thresholds match R's file exactly on all six reference grids that have one,
and every gridded index file matches R's exactly on all eight reference grids (see
[Reference outputs](#reference-outputs)); the per-cell rules R follows are in
[Gridded indices](#gridded-indices). Differences in behaviour (the reference grids
exercise only those said to be):

| R behaviour | Python |
| --- | --- |
| `create.thresholds.file` copies every attribute of the input time variable onto the output `time`, including `units`; with input units in hours (Climpact's own sample, `hours since 1800-01-01 00:00:00`) or seconds, the output says hours although its values are days | the input's units are kept when they are in days, as R; otherwise `time` keeps `days since <origin>`. The values are identical; `grid_sample` exercises this |
| `get.quantiles.for.stripe` takes the base-period TAVG, EHF and raw data by position in the full-year date series (`date.series`) but indexes the file's series with it, and `base_time` holds the file's base-period dates: if the file does not start on 1 January or skips days, the positions shift and `txraw` and `base_time` differ in length | Python pads every series to whole years by date first (as `create.filled.series` does for the percentiles), so the positions are right and missing days are missing. Identical for files starting on 1 January with every day, as all reference grids |
| `calculate_EHF` on a series that does not start on 1 January has its first 32 values missing; with the padding, the first EHF values of such a file use the padded (missing) days | as above: only files not starting on 1 January differ |
| Bounds variables of X and Y (`lat_bnds`, ...) are copied (Climpact's README says inputs must not have them) | not copied; `time_bnds` uses a dimension `bnds` |
| Non-standard calendars: PCICt supports `365_day`/`noleap` and `360_day` (and stops on others) | supported the same way (#66), including R's `%Y-%j` threshold dates in `noleap` leap years, `climdex.hw`'s threshold lookup by month and day of 2001, and `day_of_<index>` numbers read as standard dates (see [Non-standard calendars](#non-standard-calendars)); `all_leap` and `julian` raise `NotImplementedError`. Identical on `grid_filled_noleap`, `grid_filled_360day` and `grid_sample_360day` |
| Units udunits cannot convert to kg m-2 d-1 (`mm/day`) stop the run | `mm/day`, `mm d-1`, `mm day-1` and `mm` are accepted as kg m-2 d-1 |
| `put.ETCCDI.atts` writes `R_version` and `climdex.pcic_version` (1.2.0); `history` says `Created by climdex.pcic 1.2.0 on <date>` | no `R_version`; `climpactpy_version` instead; `climdex.pcic_version` is 1.2.0 (the version reproduced, as `Climpact_version` 3.4.3); `history` says `Created by climpactpy <version> on <date>` |
| Only TX, TN or precipitation alone: `get.thresholds.metadata` still lists all 21 variables and writing stops | all three variables are required, checked when the files are opened |
| R writes an uncompressed file with one chunk per day | compressed (zlib), chunked by block; the content is the same |
| R reads each stripe straight from the input files, however they are chunked: with files chunked by time step, every stripe decompresses the whole file | inputs chunked by time step are copied once to a temporary file laid out by block (`GriddedInput.block_reader`, see [Rechunking](#rechunking-inputs-chunked-by-time-step)); the values read are identical |
| Gridded indices: R stops in `write.climdex.results` on the `hw` and `hwEHF` files of any grid with an all-missing cell (`climdex.results[[i]][[ind]][[2]]` of the cell's `NA`), after writing part of the files | **Not copied** (decided 2026-11-14, #87): Python writes every file, with missing values (the fill value) for the all-missing cell, as for every other index. The `grid_stations` and `grid_future` R references leave `hw` and `hwEHF` out for this reason; `grid_filled` has no all-missing cell. `test_r_missing_values` checks the all-missing cell |
| Gridded indices: for a cell with TAVG on less than half of the base period, `climdex.hwEHF` prints "NOT CALCULATING EHF HEATWAVES, LESS THAN 50% OF BASE PERIOD DATA AVAILABLE..." and returns `NULL`; `write.climdex.results` then stops on `hwEHF` ("subscript out of bounds": it turns the `NULL` into a one-element list and takes its second element). The first `grid_filled` run hit this on its sparse cell, which is why that cell was changed | **Not copied** (#87, same decision): the cell's eight EHF variables are missing (`hwehf_values`), as the station product writes no EHF files then. With a thresholds file R makes no such check, and neither does Python. `test_ehf_needs_half_of_the_base_period_unless_thresholds_are_given` |
| Gridded indices: EHF85 missing from a thresholds file (a cell without positive base-period EHF) makes every severity `NA`; R's `max(na.rm = TRUE)` and `sum(na.rm = TRUE)` then give EHF-HWPS `-Inf` and EHF-HWLS 0 in years with heatwaves, written as such | reproduced (`annual_aspects` drops missing severities; `_write_block` keeps infinite values). The station product had raised an error in this case (possible only with no positive base-period EHF); it now gives R's values too. No reference grid has such a cell; the unit test above checks it |
| Gridded indices: bounds variables of X and Y, a `grid_mapping` variable and two-dimensional coordinate variables named in `coordinates` are copied to every index file | not copied, as for the thresholds; X and Y are float64 |
| Gridded indices: `create.climdex.cmip5.filenames` names monthly files with years only (it looks for `_mon` in lower case) and needs a six-part template; `rxnday_n = 5` writes `rx5day` twice | the same names; a template with fewer parts is refused; `rx5day` is written once |
| Gridded indices: `create.ncdf.output.files` gives tx95t's `time` a `calendar` of `365_day`, replaced by the input time's calendar when it has one; its `bounds` attribute names a variable that does not exist | the same |

### Quality control

The per-value QC checks are in `climpact.qc`, one function per R check
(`services/check/*.R`), and every QC file is declared once in `QC_REPORTS`
(`climpact.products.qc`): its name, its check, its description (from `QCParams`), whether R
writes a "NO ... FOUND" line and whether it quotes the column names. All of R's
behaviour is reproduced, and every QC file is text-identical to R's on all 16 runs.

| R behaviour (`services/check/`) | Python |
| --- | --- |
| `allqc` runs on a temporary file of the merged rows written with `na = "-99.9"` and read back with `na.strings = "-99.9"`. Since `-99.9` already means missing in the input, the checks see the same values and missing values as the indices | the checks run on `StationRun.rows` (`io.station.merged_rows`) |
| QC only reports: `allqc` writes files and plots, and the climdex input object the indices use is built before it and never changed | same: the QC products read the rows and change nothing |
| `duplivals` lists every repeat of a date (`duplicated` on year, month, day), so a date given three times is listed twice | `duplicate_dates` |
| `tmaxmin` lists `tx - tn <= 0`: TN >= TX, not only TN > TX as its description says. Rows with TX or TN missing are left out; a missing precipitation is written `NA` | `tmax_le_tmin` |
| `humongous` lists precipitation above `prec_threshold` or below 0, or TX or TN above `temp_threshold` or below its negative. A missing value does not hide the others (`NA \| TRUE` is `TRUE`) | `too_large` |
| `jumps_tx`, `jumps_tn`: `abs(round(diff(x), 1))`, run-length encoded (`rle`), runs `>= temp_change_threshold` kept, although the description says `>`. A run of equal changes is reported once, on the date of its last change, which is the first of the two days compared. A missing value breaks runs | `jumps`, with R's `round` (`rnumerics.r_round`) and `rle` (`_runs`) |
| `jumps_tx` writes the rounded change in its `TX` column; `jumps_tn` writes the TN value of the date (they select different columns after the merge) | reproduced |
| `flatline_tx`, `flatline_tn`: runs of at least `no_variability_threshold` zero rounded changes (more than that many equal values), reported on the second-last day of the run with the value and the number of equal values | `flatline` |
| `flatline_tn`'s description says "TX" | reproduced |
| `duplivals`, `jumps_*` and `flatline_*` write a quoted "NO ... FOUND" line when nothing is found; `tmaxmin` and `humongous` test `length(data.frame) == 0`, which counts columns, so they never do | reproduced (`QCReport.empty_message`) |
| `flatline_*` quote their column names (`write.table` default); the others do not. Missing values are written `NA` and numbers with `as.character` | reproduced (`QCReport.quote_header`, `FileFormat.na`); `format_r_number` gives the same text as `as.character` |
| `fourboxes` (`qc/outliers`) draws one box per calendar month with `boxplot`, whose `boxplot.stats` uses Tukey's hinges (`fivenum`: medians of the lower and upper halves, each including the median when n is odd), not the quartiles `numpy.percentile` gives | `qc.fivenum`, `qc.boxplot_stats`, checked against values printed by R (`tests/data/r_boxplot.R`), n = 0 to 12 and longer samples, ties, IQR 0, missing values and values on a fence |
| Boxes are drawn from non-zero precipitation (whiskers at `iqr_threshold_prec` IQRs) and from TX, TN and DTR = TX - TN (`iqr_threshold_temp`). The file lists the days above each month's upper whisker (`up`) and, for the temperatures, below its lower one (`low`), so values beyond the fences `hinge ± coef × IQR`, compared in doubles: a value on a fence is listed or not depending on its last bit | `qc.outliers`, with the same arithmetic |
| Sections in the order `Prec up`, `TX up`, `TX low`, `TN up`, `TN low`, `DTR up`, `DTR low`, each a quoted title line followed by its rows month by month (merged-row order within a month), each row with all four values. A section is written even when empty; a variable missing throughout (for precipitation, with no non-zero value) has no sections. A month without values has no box and lists nothing | reproduced (`FileFormat.sections`, from the categorical `Section` column `qc.outliers` returns) |
| The rows are `cbind`ed with the dates, so the values go through `as.character` (15 significant digits): DTR is written as, say, `8.2` although `tx - tn` is 8.200000000000001 | the table holds the values as written, so `qc/outliers` passes the `EXACT` tier as well as the text comparison |

R's `round(x, 1)` (`nmath/fround.c`, R >= 4.0.0) is not Python's: it picks the nearer of
`floor(x * 10) / 10` and `ceil(x * 10) / 10` computed in doubles (ties to even), so
`round(0.45, 1)` is 0.4 in R and 0.5 in Python. `r_round` ports it; on 813 changes printed
by R (`tests/data/r_round.R`), numpy's `round` differs from R's on 11 and `r_round` on none.
On the reference stations, whose values have one decimal, the two agree; on `qc_stress`,
30.05 - 10.1 (19.950000000000003) rounds to 20 and is reported as a jump.

The outlier edges no reference run has (a month with no TX, a month with no rain, a
station with no rain and no TN, TX values on the fences, an IQR of 0, non-default
thresholds) are checked against R's own `fourboxes` run on synthetic stations
(`tests/data/make_fourboxes_synthetic.py`, `tests/data/r_fourboxes.R`): the files are
text-identical.

### R behaviour not to be copied

These are known R bugs or limitations, found while reviewing the R code. They are not
reproduced; where they affect an output, the difference will be documented when that
output is ported.

- `percent.days.op.threshold` divides the in-base hits by `byrs - 1`, the base years the
  series covers minus one, not by the number of comparisons, so tx90p, tn90p, tx10p,
  tn10p and txgt50p can exceed 100% for a series that starts or ends inside the base
  period. Python divides by `years - 1`. No reference run is affected (see
  [In-base bootstrap](#in-base-bootstrap)).
- `percent.days.op.threshold` stops with an error when the series has exactly one
  base-period year and at least 720 days (`byrs - 1 = 0`). Python uses the out-of-base
  thresholds for that year (see [In-base bootstrap](#in-base-bootstrap)).
- `get.hw.aspects` does not count a heatwave that is under way on the first day of the
  extended season and ends after it (`extvals[1] > 1`), so the season gets HWN 0. Python
  counts it (decided 2026-11-13, #51). No reference run is affected (see
  [Heatwaves](#heatwaves-tx90-tn90)).
- `get.hw.aspects` makes HWN and HWF missing in every year when HWM is missing in every
  year, so a station without any heatwave gets missing instead of 0. Python gives 0 and
  makes a season missing only when it has no usable value (decided 2026-11-13, #51). No
  reference run is affected (see [Heatwaves](#heatwaves-tx90-tn90)).
- `climdex.hwEHF` stops with an error ("missing value where TRUE/FALSE needed") when the
  leading days of a heatwave piece have a missing EHF and no positive one. Python counts
  the piece with its duration only. No reference run is affected (see
  [EHF heatwaves](#ehf-heatwaves-and-the-daily-ehfecf-series)).

- Gridded `hw`/`hwEHF`: R stops on a grid with an all-missing cell, and on `hwEHF` when
  a cell has less than half of the base period. Python writes missing values for those
  cells (decided 2026-11-14, #87; see [Gridded data](#gridded-data-1)).
- `cspei` stops with an error when `pargam` returns no parameters or the generalised
  logistic parameters are invalid, and `window` stops when the base period is outside the
  series. Python leaves the calendar month missing, or writes no SPI/SPEI files. No
  reference run is affected (see [SPI and SPEI](#spi-and-spei)).
- A warning or error inside `plot.call` (caught by `index.calc`) can leave the previous
  index's seasonal trends to be written, and `plot.precindex` stops when no monthly index
  had a value (`monthsGLOB` unset). Python computes every season and takes the SPI/SPEI
  months from their own table. No reference run is affected (see
  [Trend file](#trend-file)).

## Performance

Measured on an Apple M-series laptop (one process), before and after #23:

| | Before #23 | After #23 |
| --- | --- | --- |
| Build, 80-year station (`lat0`, `sydney`) | 13.4 s | 2.6-2.7 s |
| Build, 60-year GHCN station | 10.3-10.5 s | 2.1-2.3 s |
| Build, patchy stations (`new_delhi`, `nairobi`) | 9.2-9.5 s | 1.5-1.7 s |
| Write the CSV files | 1.0-1.3 s | 0.1-0.2 s |
| `climpact run` for Sydney (including about 2 s of imports) | 16.6 s | 5.2 s |
| `climpact batch`, Climpact's two sample stations, `--workers 2` | 19.1 s | 8-9 s |
| Full test suite (15 runs, text comparison, batch test) | 202 s | 55 s |

The build is `build_all`, after `load_station`. Profiling (cProfile) on Sydney before #23
showed three causes, fixed without changing any output (all 1,662 files written for the 15
runs are byte-identical before and after, as well as text-identical to R):

- **xarray's `resample`** reduced each of the 960 months separately through xarray
  objects (flox is not installed), about 70% of the build. Most of it was the climdex
  missing-data mask, recomputed 75 times per station, including inside every xclim call.
  Masks, counts, maxima and minima now use `climpact.periods` (see
  [Monthly and annual reductions](#monthly-and-annual-reductions)), and threshold counts
  no longer go through xclim (see [Use of xclim](#use-of-xclim)). Once a mask takes about
  1 ms, caching it per variable on the `StationRun` was not worth it.
- **The R-precision emulation** worked on integers in units of 2**-1074 (about 1,100
  bits). It now uses the values' own unit and skips rounding that cannot happen, with an
  exact `math.fsum` path (see [Numerical precision](#numerical-precision)).
- **R number formatting** used `fractions.Fraction`, for every value written and for the
  standardised column. It now uses integer ratios and a cache.

The trend file also reads its two confidence-bound order statistics with `np.partition`
instead of sorting all the pairwise slopes.

What is left of the Sydney build (about 2.4 s for the products):

| Product | Time |
| --- | --- |
| Temperature percentile indices (tx90p, tn90p, tx10p, tn10p, txgt50p) | 1.0 s: bootstrap 0.74 s (5 variable/quantile pairs), indices 0.26 s |
| Trend file | 0.47 s, mostly the 460,000 pairwise slopes of each monthly series |
| EHF heatwaves | 0.31 s, mostly the extended-precision 30-day sums (one `r_sum` per day) |
| Means and totals (tmm, txm, tnm, dtr, prcptot, sdii) | 0.24 s, mostly `r_mean` per month |
| SPI and SPEI (8 files) | 0.22 s, the extended-precision accumulations and the scalar R ports |
| Everything else | under 0.12 s each |

GHCN stations take 0.9 s for the percentile indices and 0.3 s for the trend file. The
bootstrap loops over the 365 days and handles all 870 (rm, dup) year pairs of a day at
once with numpy, so it takes about 0.15 s per variable and quantile, against 317,550
quantiles. A batch runs one station per process, and each spawned worker also imports
xclim (about 2 s).

### Gridded thresholds

Apple M-series laptop, a synthetic grid of float32 data in K, 1961-2020 (21,915 days),
base 1971-2000, default block (5 million values) and batch (8 cells):

| Grid | Python, 1 thread | Python, 4 threads | R (`climpact.ncdf.thresholds.wrapper.r`, `parallel = FALSE`, Docker amd64 under emulation) |
| --- | --- | --- | --- |
| 16 x 16 (256 cells) | 5.8 s (23 ms per cell) | 3.2 s | 40 s |
| 32 x 32 (1,024 cells) | 24 s | 13 s | not run |

Both 256-cell results are identical. Peak resident memory with 1 thread was 0.69 GB on the
256-cell grid and 1.2 GB on the 1,024-cell grid (about 330 MB of it imports). The memory
numpy allocates depends only on the block (see [Gridded data](#gridded-data)); the rest is
netCDF-C's read cache, which holds more of the larger grid's bigger file chunks (up to
64 MB per variable), and memory the allocator keeps: with a 4 MB read cache
(`netCDF4.set_chunk_cache`) the 1,024-cell grid peaked at 0.78 GB. The
two reference grids take under 0.5 s each. Decimal doubles in degrees C are slower in the
EHF, where some 30-day sums need R's rounding emulation one window at a time (see
[Numerical precision](#numerical-precision)).

Input files chunked by time step over the whole grid (common in model output) are
rechunked first; see [Rechunked inputs](#rechunked-inputs).

### Rechunked inputs

Apple M-series laptop, a synthetic 2.5-degree global grid (72 x 144 = 10,368 cells),
1961-2020 (21,915 days), float32 in K, chunked by one time step over the whole grid and
compressed (zlib level 1, shuffle; 1.7 GB, 2.7 GB of raw values), default block (5 million
values: 144 blocks of 76 cells) and slabs (482 days, 46 slabs):

| | Read directly (`--rechunk no`, as before #67) | Rechunked (`--rechunk auto`) |
| --- | --- | --- |
| Reading every block (`load`), no computing | about 22 min (9 s per block: each decompresses the whole file) | 22 s (rechunk 10-11 s, then 11.5 s for the 144 blocks) |
| `climpact gridded-thresholds`, base 1991-2000, `--workers 4` | 1,377 s, 1.54 GB peak resident memory | 80 s, 1.16 GB |

All 26 variables of the two thresholds files are identical, as are the SHA-1 hashes of
every block's three arrays. The numpy allocations of the rechunk are 40 MB
(tracemalloc); the rest of its resident memory is netCDF-C's read cache, as for reading
blocks directly (see [Rechunking](#rechunking-inputs-chunked-by-time-step)). Read
directly, the time grows with the square of the grid: a 1-degree global grid has 900
blocks, each decompressing four times as much, so about 9 hours of reading against
about 3 minutes of rechunking. The indices compute for much longer per cell than the
thresholds (see below), so the gain is relatively smaller there, but the hours of reading
saved are the same.

### Gridded indices

The same kind of synthetic grid (float32 in K, 1961-2020, base 1971-2000), the 84 files
other than `hw`, `hwEHF`, `spi` and `spei` (R run with those four left out, so both compute
the same indices), default block and batch (timed for #30):

| Grid | Python, 1 thread | Python, 4 threads | R (`climpact.ncdf.wrapper.r`, `cores = FALSE`, Docker amd64 under emulation) |
| --- | --- | --- | --- |
| 8 x 8 (64 cells) | 46 s (0.7 s per cell), 0.82 GB | 37 s, 1.23 GB | 196 s (3.1 s per cell) |
| 16 x 16 (256 cells) | 172 s (0.67 s per cell), 0.95 GB | 123 s, 1.31 GB | not timed (over 30 minutes on a loaded machine) |

On the 64-cell grid all 196 index variables of R's 84 files were identical to Python's,
with 1 and 4 threads. A cell's time is mostly the in-base bootstrap (about 0.28 s per
variable, TX and TN), then R's exact running sums for Rx{n}day, the spell indices and
the exact sums, which run in Python one series at a time and hold the GIL; so threads
help less than for the thresholds. Before the float32 means (see
[Numerical precision](#numerical-precision)) a 60-year cell took 1.76 s, half of it in
`r_mean`. The batched bootstrap was tried (all cells of a batch per day) and was slower
than one cell at a time; computing a variable's in-base quantiles together is kept.

**The heatwave, EHF, SPI and SPEI files** (#87), on the same 64-cell grid, measured on the
same kind of machine. `cell_indices` always computes the other 84 outputs (`--indices` only
limits what is written), and these four only when asked for:

| Run | Python, 1 thread | Python, 4 threads | R (the four only, `cores = FALSE`, Docker amd64 under emulation) |
| --- | --- | --- | --- |
| `--indices fd` (the 84 computed, one written) | 47.4 s, 0.76 GB | | |
| `--indices hw` / `hwEHF` / `spi` / `spei` | 48.1 / 48.1 / 51.3 / 51.8 s | | |
| `--indices hw hwEHF spi spei` | 53.8 s, 0.83 GB | 52.0 s, 1.32 GB | 103 s (1.6 s per cell) |
| all 88 files | 59.2 s (0.92 s per cell), 0.95 GB | 50.9 s, 1.33 GB | |

So the four add about 0.1 s per cell (hw and hwEHF about 0.01 s each, SPI and SPEI about
0.06 s each, mostly the per-value `qnorm`, `pgamma` and exact sums in pure Python), and
threads do not help them (they hold the GIL). All 20 variables of R's four files were
identical to Python's with 1 and 4 threads (644,232 values).

## Web front end

The web app (epic #11) replaces the R Shiny app (`climpact/ui`, `climpact/modules`). It is
**Django + htmx**, server-rendered with Django templates (decided in #11). The
`climpact-web` package depends on the core and calls it as a library; the core never
imports `climpact_web`. This section describes the skeleton (#69) and the design system
(#71); the screens follow in #73 (jobs, described in [Background jobs](#background-jobs)), #75 (charts), #76-#78 and #90 (steps 1-4; step 1 is described in [Single-station steps](#single-station-steps)), #79
(downloads), #80 (batch, described in [Batch page](#batch-page)), #81 (help), #85 (gridded), #82 (size budget) and #83
(accessibility).

### Layout

```
packages/climpact-web/src/climpact_web/
  settings.py        the one settings module; every value from environment variables
                     (local or hosted mode, see below); reading it has no side effects
  urls.py            root URLs: i18n/ (set_language), jobs/, station/, batch/ and the core app;
                     later apps add their own include here
  wsgi.py            WSGI application, for waitress and hosted servers
  middleware.py      UploadSizeLimitMiddleware: 413 for request bodies over MAX_UPLOAD_MB
  cli.py, __main__.py  the `climpact-web` command (also `python -m climpact_web`); starts
                     the background worker as a child process in local mode
  core/              the UI shell app (label `core`): landing page, /patterns/, /healthz,
                     the context processor `site`
    navigation.py    the app's destinations (header links, landing page) and the
                     single-station and batch steps (`station_steps`, `batch_steps`) for
                     the step indicator
    tokens.py        reads the design tokens back from the CSS; writes chart-palette.json
    forms.py         PatternDemoForm, the example form on the pattern library
    templatetags/ui.py  `{% icon %}` and the `times` filter
    management/commands/design_snapshots.py  static HTML copies of the pages for review
    templates/       base.html (the page shell), 404.html, 413.html, 500.html,
                     core/home.html (landing), core/patterns.html (pattern library),
                     core/language_switcher.html, components/*.html (the components)
    static/climpact_web/
      css/main.css   tokens (light), base styles, layout and every component
      css/theme-dark.css  dark values of the colour tokens
      css/patterns.css    pattern library page only
      css/stations.css    the single-station pages (and the batch pages)
      css/batch.css       the batch pages only
      js/ui.js       progressive enhancement: theme toggle, tabs, drop zone, dialogs, toasts
      icons/icons.svg     the icon sprite (drawn for this project); favicon.svg
      chart-palette.json  chart colours for both themes, generated from the tokens
      vendor/htmx/   htmx 2.0.11, vendored; README.md records its source URL and SHA-256
  jobs/              background jobs (label `jobs`, see [Background jobs](#background-jobs))
    models.py        Job (the queue and its progress), Worker (running workers)
    registry.py      runner registry, JobContext, JobError, JobCancelled, JobInterrupted
    runners.py       the built-in runners: station, batch, sector, gridded-thresholds,
                     gridded-indices (thin wrappers of the core functions)
    worker.py        claiming, progress writes, heartbeats, dead-worker detection, the
                     worker loop (JobWorker)
    retention.py     purge_expired: old jobs and their folders
    storage.py       LocalJobStorage: the per-job folders (the S3 hook for #12)
    stages.py        readable names of the core's progress stages
    views.py, urls.py  /jobs/: list, job page, progress fragment, cancel, retry, file
                     downloads
    forms.py         STATION_NAME and safe_station_name (the station name rules)
    context_processors.py  `job_retention_days` for every template
    management/commands/  runworker, purgejobs
    templates/jobs/  job_list.html, job_detail.html, _progress.html, _status.html
  stations/          the single-station steps (label `stations`, see
                     [Single-station steps](#single-station-steps))
    models.py        StationAnalysis: one station going through the steps
    station_file.py  checks an uploaded file (plain-language problems at file lines,
                     warnings) and summarises its data
    forms.py         UploadForm, MetadataForm (step 1), RunAllForm (step 2 placeholder)
    preview.py       the static monthly preview (inline SVG) until the charts of #75
    retention.py     purge_expired_analyses, registered with the jobs app's purge
    views.py, urls.py  /station/: upload, sample, load, field validation, replace file,
                     daily CSV, delete, the step 2 placeholder
    sample_data/     sydney_observatory_hill_1936-2015.txt.gz, R's sample (173 KB)
    templates/stations/  upload.html, load.html, qc.html, _unit.html (a field group
                     validated by htmx), _summary.html, _problems.html, _retention.html
  batch/             batch processing of stations (label `batch`, see [Batch page](#batch-page))
    models.py        BatchRun: one batch's files, check result, options and job
    check.py         the pre-flight check: metadata file, each station, zip unpacking
    forms.py         UploadForm, AddFilesForm, OptionsForm
    retention.py     purge_expired_batches, registered with the jobs app's purge
    views.py, urls.py  /batch/: start, sample, check, add files, options (htmx), run,
                     results, progress fragment, open a station, delete
    sample_data/     climpact.sample.batch.metadata.txt, R's sample metadata file
    templates/batch/  start.html, check.html, results.html, _options.html,
                     _progress.html, _retention.html
  locale/en/LC_MESSAGES/django.po   the message catalogue (English, from makemessages)
packages/climpact-web/tests/
  web_test_settings.py  test settings: local mode, data folder in a temporary folder
  test_*.py          settings, views and security, i18n, static files, the command, jobs
                     (test_jobs.py), the worker as a real process (test_worker_process.py),
                     step 1 (test_stations.py) and the batch page (test_batch.py)
```

Apps, one per area, each added by the ticket that needs it: `jobs` (the job model,
worker and progress pages, #73), `stations` (single-station steps, #76; steps 2-4
follow in #77-#79, #90), `batch` (#80) and planned `gridded` (#85). `core` keeps what every page shares.

Templates and static files live inside the package, so the wheel carries them (hatchling
includes every file under `src/climpact_web`; checked by building the wheel). There is no
build step and no Node: the user decided against Tailwind on 2026-11-14 (#69), so the
design system (#71) is hand-written CSS with custom-property tokens.

### Modes

`CLIMPACT_WEB_MODE` selects one of two modes; the same settings module serves both.

| | `local` (default) | `hosted` |
| --- | --- | --- |
| Started by | `climpact-web` (waitress on 127.0.0.1) | a WSGI server chosen in #12, on `climpact_web.wsgi:application` |
| Database | SQLite, `<data dir>/db.sqlite3` (WAL journal, 20 s busy timeout, `IMMEDIATE` transactions, as the server and the worker both write), migrated on every start | `DATABASE_URL` (Postgres; the `postgres` extra installs psycopg); migrations run by the deployment |
| Secret key | `CLIMPACT_WEB_SECRET_KEY`, else `<data dir>/secret_key` (written on first start, mode 0600) | `CLIMPACT_WEB_SECRET_KEY`, required |
| Allowed hosts | localhost, 127.0.0.1, [::1] (`*` when started with a non-loopback `--host`) | `CLIMPACT_WEB_ALLOWED_HOSTS`, required |
| Static files | WhiteNoise serves them straight from the package (`WHITENOISE_USE_FINDERS`), no `collectstatic` | `collectstatic` into `CLIMPACT_WEB_STATIC_ROOT` (required), WhiteNoise's compressed, hashed storage |
| HTTPS | none (localhost) | secure session and CSRF cookies, redirect to HTTPS, `X-Forwarded-Proto` from the proxy trusted; `/healthz` exempt from the redirect |
| Uploads and results | `<data dir>/media`; job folders under `media/runs` | `CLIMPACT_WEB_MEDIA_ROOT`, a filesystem every worker and web process shares (S3: a documented hook, see [Background jobs](#background-jobs), for #12) |
| Background worker | started by `climpact-web` as a child process, restarted if it crashes | one or more `climpact-web manage runworker` processes, run by the deployment (#12) |

The data folder is `CLIMPACT_WEB_DATA_DIR` or `--data-dir`, else the user data folder from
platformdirs (`~/Library/Application Support/climpact-web` on macOS,
`~/.local/share/climpact-web` on Linux, `%LOCALAPPDATA%\climpact-web` on Windows).
Missing required settings in hosted mode stop the app with `ImproperlyConfigured` naming
the variable.

### Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `CLIMPACT_WEB_MODE` | `local` | `local` or `hosted` |
| `CLIMPACT_WEB_DATA_DIR` | user data folder | database, secret key, media (local mode) |
| `CLIMPACT_WEB_SECRET_KEY` | see Modes | Django `SECRET_KEY` |
| `CLIMPACT_WEB_ALLOWED_HOSTS` | see Modes | comma-separated host names |
| `CLIMPACT_WEB_CSRF_TRUSTED_ORIGINS` | none | comma-separated origins, e.g. `https://climpact.example.org` |
| `DATABASE_URL` | SQLite in the data folder | any URL dj-database-url reads, e.g. `postgres://user:pw@host:5432/db`; required in hosted mode |
| `CLIMPACT_WEB_DEBUG` | `false` | Django `DEBUG` |
| `CLIMPACT_WEB_PATTERN_LIBRARY` | same as `DEBUG` | serve the pattern library at `/patterns/` (404 otherwise) |
| `CLIMPACT_WEB_STATIC_ROOT` | none | `collectstatic` target; required in hosted mode |
| `CLIMPACT_WEB_MEDIA_ROOT` | `<data dir>/media` | uploads and job folders (`RUNS_DIR` is `media/runs`) |
| `CLIMPACT_WEB_RETENTION_DAYS` | `7` | days a finished job and its files are kept (`JOB_RETENTION_DAYS`) |
| `CLIMPACT_WEB_JOB_HEARTBEAT_SECONDS` | `10` | seconds between worker heartbeats |
| `CLIMPACT_WEB_JOB_STALE_SECONDS` | `60` | seconds without a heartbeat before a running job counts as dead |
| `CLIMPACT_WEB_JOB_POLL_SECONDS` | `1` | seconds between a worker's checks for queued jobs |
| `CLIMPACT_WEB_JOB_STORAGE` | `climpact_web.jobs.storage.LocalJobStorage` | class that manages job folders |
| `CLIMPACT_WEB_MAX_UPLOAD_MB` | `50` | largest request body, uploads included |
| `CLIMPACT_WEB_SSL_REDIRECT` | `true` | hosted mode: redirect HTTP to HTTPS |
| `CLIMPACT_WEB_HSTS_SECONDS` | `0` | hosted mode: `Strict-Transport-Security` max-age; set once the domain is final (#12) |
| `CLIMPACT_WEB_LOG_LEVEL` | `INFO` | level for the `climpact_web` and `climpact` loggers; other libraries log warnings and errors |

Both modes also set `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: same-origin`,
`Cross-Origin-Opener-Policy: same-origin`, HttpOnly SameSite=Lax session cookies and
Django's CSRF protection; htmx requests send the CSRF token from the `hx-headers` on
`<body>`. Server errors are logged to the console by `django.request`. pint's warnings
about xclim redefining its units are silenced (`pint.util` at ERROR).

**Upload limit.** Django limits only in-memory form data, not file uploads, so
`UploadSizeLimitMiddleware` answers 413 (with `413.html`) when `Content-Length` exceeds
`MAX_UPLOAD_MB`, before the body is read; waitress gets the same limit
(`max_request_body_size`) for bodies without a length. The default, 50 MB, covers any
station file; gridded runs read netCDF files from disk in local mode (#85). Uploads over
2.5 MB go to a temporary file, not memory (Django's default).

### Running the web app

```sh
.venv/bin/climpact-web                      # local mode: migrate, serve on 127.0.0.1:8000, open the browser
.venv/bin/climpact-web --no-browser --port 9000 --data-dir /tmp/cw
.venv/bin/climpact-web manage <command>     # any Django management command with these settings
```

Options: `--host` (default 127.0.0.1; 0.0.0.0 serves the network, with a warning),
`--port` (default 8000, or a free port if 8000 is taken), `--no-browser`, `--data-dir`,
`--threads` (default 4), `--no-worker` (do not start the background worker). Ctrl+C or
SIGTERM stops the server and the worker cleanly (exit status 0). The command prints the
address and the data folder.

A hosted deployment runs `climpact-web manage migrate` and
`climpact-web manage collectstatic --no-input` with the hosted variables set, then serves
`climpact_web.wsgi:application`; the server, containers and AWS set-up are #12. Load
balancers check **`/healthz`**: 200 and `{"status": "ok", "database": "ok", "version":
..., "core_version": ...}` when the database answers, 503 otherwise; never cached.

### Design system

The visual language and shared components (#71). The R Shiny app (`climpact/ui`,
`climpact/www/styles.css`: shinydashboard boxes, a sidebar menu, tabs as steps) is the
baseline it replaces.

**Look.** Calm and plain: neutral surfaces, one blue accent (`--color-accent`), strong
type hierarchy, generous spacing. System fonts only (`--font-sans`, `--font-mono`): no
web fonts are downloaded, for bandwidth and offline use, and every script the operating
system supports displays. Icons are a sprite drawn for this project
(`icons/icons.svg`, same licence as the package, 2px strokes on a 24px grid), inserted
with `{% icon "name" %}` (decorative, `aria-hidden`) or `{% icon "name" "Label" %}`
(announced as an image).

**Tokens.** CSS custom properties on `:root` in `css/main.css`: colours (`--color-*`),
chart colours (`--chart-*`), type scale (`--text-*`), spacing (`--space-*`), radii,
control heights and widths. Components use only tokens: a test fails on a hex colour
outside the token block. `css/theme-dark.css` holds the dark values and nothing else;
`base.html` loads it with `media="(prefers-color-scheme: dark)"`. The theme toggle in the
header (system, light, dark) sets that `media` to `all` or `not all` and stores the
choice in `localStorage` (`climpact-theme`); a two-line inline script in `<head>` applies
the stored choice before the page paints. Without JavaScript the system setting applies
and the toggle stays hidden. The toggle sets `data-theme` on `<html>` and fires
`climpact:themechange` on `document`, so charts can redraw.

**Contrast.** `tests/test_design_tokens.py` reads the token values from both stylesheets
and computes WCAG 2.1 contrast ratios for every pairing the components use, in both
themes: text, muted text, links and status text on each surface and on each tinted alert
background (4.5:1), button labels on their fills (4.5:1), and input borders, focus rings,
status icons and chart line roles against their backgrounds (3:1, WCAG 1.4.11). All pass;
the closest are light success text on the sunken surface (4.99:1, needs 4.5) and light
input borders on the sunken surface (3.43:1, needs 3).

**Chart palette.** For #75 (and the static plots of #74, #79):

| Tokens | Use |
| --- | --- |
| `--chart-1` ... `--chart-8` | categorical series, assigned in this order and never cycled |
| `--chart-tmax`, `--chart-tmin`, `--chart-prcp` | the variables: red, blue, teal |
| `--chart-trend`, `--chart-trend-band` | trend line (ink, dashed) and its confidence band |
| `--chart-flag` | QC flags: hollow ring markers in ink, told apart from series by shape |
| `--chart-grid`, `--chart-axis` | gridlines and axes |
| `--chart-seq-1` ... `-5` | sequential (one hue, blue), e.g. maps (#85) |
| `--chart-div-1` ... `-7` | diverging, blue to red through grey, e.g. anomalies |

The categorical order was checked with a colour-vision-deficiency validator (OKLab
distance under protan, deutan and tritan simulation) against the light surface
(`#ffffff`) and the dark surface (`#151c24`): worst adjacent pair ΔE 9.1 light, 8.4 dark
(target 8), normal-vision floor 19.6 and 19.3 (floor 15). `tmax`, `tmin` and `prcp`
were checked as a set with every pair compared: they pass in light; in dark the
`prcp`-`tmax` pair is ΔE 6.5, inside the band that is acceptable with labels, and the two
rarely share a chart. In the light theme categorical slots 3, 4 and 5 are below 3:1 on
white (2.2-2.8:1), so charts that use them must label series directly or offer the table
view, which every chart frame has. The validator is not part of the test suite (it is
JavaScript); re-run it when the palette changes. `chart-palette.json` carries the same
colours for both themes, for code that cannot read CSS; it is generated with
`.venv/bin/python -m climpact_web.core.tokens` and a test fails when it is out of date.
In the browser `Climpact.chartPalette()` returns the live values for the current theme.

**Components.** Template includes in `core/templates/components/`; each file starts with
a comment listing its parameters. Labels are passed in already translated
(`{% translate "Start" as label %}{% include "components/button.html" with label=label %}`).

| Component | Notes |
| --- | --- |
| `button` | primary, secondary, ghost, danger; `lg`, `sm`, icon only, `full_width`, `busy` (spinner, `aria-busy`), link when `href` is given; disabled links render as disabled buttons |
| `field`, `field_errors`, `form_errors` | label, hint, inline error with an icon, unit suffix; radio groups as a fieldset; the error summary links to each field and takes focus. Hint and error ids are Django's (`<id>_helptext`, `<id>_error`), which Django 5.2 puts in the widget's `aria-describedby` with `aria-invalid` |
| `dropzone` | a label around a real, visible file input; `ui.js` hides the input visually, adds drag and drop and shows the file name |
| `alert`, `messages`, `toasts` | info, success, warning, error, each with its own icon; dismissible; Django messages render as alerts; toasts via `Climpact.toast()` or an `HX-Trigger: {"toast": {...}}` response header; error toasts stay until dismissed |
| `card`, `badge`, `stat`, `summary_list` | cards can be one link (the title's link covers the card); badges always carry text |
| `table` | caption, numeric columns right-aligned with tabular figures, sticky header, a focusable scrolling region for wide tables, empty text |
| `tabs` | links to panels without JS (all panels show); `ui.js` makes an ARIA tablist (arrow keys mirrored for right-to-left, Home, End) |
| `steps` | the single-station step indicator: Load data, Check quality, Calculate indices, Results and downloads, Compare with sector data (optional); from `navigation.station_steps(current, urls)`; completed steps link back; `aria-current="step"`; below 40rem only the current step's label shows |
| `progress`, `stages` | native `<progress>` (indeterminate when no value), a politely announced note, and the list of job stages (done, current, pending, failed) for #73 |
| `skeleton`, `empty_state`, `disclosure` | loading placeholder (`aria-busy`), empty state with an action, help that opens in place (`<details>`) for #81 |
| `dialog` | native `<dialog>` opened by `data-dialog-open`; cancel and close use `method="dialog"` |
| `chart_frame` | title, text summary, legend, plot area with a skeleton until a chart draws into `[data-chart-plot]`, CSV link and table view, for #75 |
| `theme_toggle` | see Tokens |

**Navigation before the screens exist.** `core/navigation.py` lists the destinations
(single station, sample data, batch, gridded, help, and the job list from #73) with the
URL name each later ticket will add (`gridded:start`, `help:index`; `stations:upload`,
`stations:sample` (#76), `batch:start` (#80) and `jobs:list` exist). Until a URL exists, the landing page shows that action disabled or
"Available soon" and the header leaves it out. Gridded is offered only in local mode, as
in R. The step URLs (`stations:qc` and so on) are named in `STATION_STEPS` for the same
reason. "Try with sample data" is a one-button POST form, since it creates the session's
analysis.

**Pages.** The landing page (`/`) says what Climpact does, has the start and "try with
sample data" buttons, the four steps, the other ways to run Climpact (batch, gridded in
local mode, help, the command line) and a note on where data is kept (local or hosted).
The pattern library (`/patterns/`, with `PATTERN_LIBRARY`) shows every component, the
palette and the icons, and is what the user review and the accessibility audit (#83) use.

**Responsive and right-to-left.** Layouts use flex and grid with `auto-fill` columns, so
they reflow down to 320px wide and at 200% zoom without horizontal scrolling (checked on
the landing page, pattern library, station step 1 pages and batch pages in a 320px frame with headless Chrome); wide tables
scroll inside their own region. Only logical properties are used: a test fails on
`left`, `right`, `top`, `bottom`, `width` or `height` properties in any stylesheet.
Motion is reduced under `prefers-reduced-motion`; borders are drawn in system colours
under `forced-colors`.

**Size.** `main.css` and `theme-dark.css` together are about 36 KB (7.6 KB gzipped);
`ui.js` is about 10.6 KB. Tests hold them under 36 KB (8.5 KB gzipped) and 12 KB. The
issue aimed for under 30 KB of CSS; the full component set, both token sets and the
comments put it above that. Whole-page budgets are set in #82.

**Review snapshots.** `climpact-web manage design_snapshots <folder>` saves the landing
page, pattern library, 404 page, the job pages (a running, a finished and a failed
job and the job list), the single-station step 1 pages (upload, upload with file
problems, the sample loaded, metadata errors, the step 2 placeholder) and the batch pages
(start, a check with every station status, a running batch, finished results), rendered from
unsaved example jobs and analyses, so no database is needed, each in light and dark copies, with the static files beside them
and the icon sprite inlined, so they open from disk without a server.

### Translations

`LocaleMiddleware` picks the language from the request (`Accept-Language`, or the
`django_language` cookie set by `set_language` at `/i18n/setlang/`). Only English is in
`LANGUAGES` for now; the language switcher in the header appears once a second language
is added. `<html>` carries `lang` and `dir` (`rtl` for right-to-left languages), and the
stylesheet uses logical properties only, so layouts mirror. Every template string is in
`{% translate %}` or `{% blocktranslate %}`: `tests/test_i18n.py` strips those,
`{% comment %}` blocks, tags and `<code>` from each template and fails on any text left. It
also fails on plain-text `aria-label`, `title`, `placeholder`, `alt` and `data-message`
attributes, since screen readers and tooltips read those. To refresh the catalogue (needs
GNU gettext's `xgettext`), run from `packages/climpact-web/src/climpact_web`:
`../../../../.venv/bin/climpact-web manage makemessages -l en --no-obsolete`. To add a
language, add it to `LANGUAGES` in `settings.py`, run `makemessages -l <code>`, translate
the `.po` file and run `compilemessages`.

### Tests

pytest-django with `web_test_settings` (set in `pytest.ini` and the package's
`pyproject.toml`; the tests folder is put on the path by `pythonpath`). The settings clear
every `CLIMPACT_WEB_*` variable and `DATABASE_URL`, and point the data folder at a
temporary folder, so tests never touch the user's data; the database is SQLite in memory.
`test_settings.py` loads `settings.py` afresh under different environments (local
defaults, hosted with a Postgres `DATABASE_URL`, each required hosted variable missing).
`test_cli.py::test_serves_local_mode` starts `python -m climpact_web --no-browser --port 0`
on a fresh data folder, fetches `/healthz`, `/` and a static file, and stops it with
SIGTERM. Postgres is not installed on the development machine; CI's `web-postgres` job
runs hosted mode against a Postgres 16 service container: `check --deploy`, `migrate`,
`collectstatic` and `/healthz`, then queues a station job (Madrid) and runs it with
`runworker --once`, which claims it with `SELECT ... FOR UPDATE SKIP LOCKED`.
`test_worker_process.py` runs the worker as a real process on a SQLite file: killed with
SIGKILL in the middle of a station run, the job is failed by `purgejobs` once the heartbeat
is stale, and after a retry a new worker runs it to the end; stopped with SIGTERM, the job
is queued again. `test_cli.py` checks that `climpact-web` starts a worker and stops it.

### Background jobs

Calculations never run in a web request: a view queues a **job** and a **worker** process
runs it, reporting progress through the core's callbacks (#72, see
[Progress reporting](#progress-reporting)).

**Choice of backend (#73).** The queue is the database: a `Job` table and a worker that
polls it (`climpact-web manage runworker`). The development machine may not install
system services, and the local install should not need any, so Redis (RQ, Celery) was
ruled out (issue comment of 2026-11-14). Django's tasks framework is not in Django 5.2
(it arrives in Django 6.0, which needs Python 3.12, and ships no production backend). The
`django-tasks` package's database backend was considered, but the progress pages need
stage progress, heartbeats and cancel requests on the job row anyway, so it would add a
dependency without removing much code; the worker is about 400 lines in `jobs/worker.py`.
It works the same on SQLite (local) and Postgres (hosted).

**The `Job` model** (`jobs/models.py`): a UUID primary key (unguessable URLs); `kind` (the
runner); `owner` (a random token kept in the browser session, `jobs_owner`: only that
session sees the job; a token rather than the session key, so rotating the session key
does not orphan jobs); `params` (JSON); `title`; `status` (`queued`, `running`,
`succeeded`, `failed`, `cancelled`); `stage`, `step`, `total` (the last progress callback;
`percent` from them); `created_at`, `started_at`, `finished_at`, `heartbeat_at`; `worker`;
`attempts`; `cancel_requested`; `error` (the message for the user); `log` (the operator
log: one timestamped line per attempt, the outcome, the run time, and the traceback of a
failure); `result` (JSON from the runner: files written, zip). The job's folder is
`<RUNS_DIR>/<id>/` with `input/` (uploads) and `output/` (what the core writes). The
`Worker` table lists running workers (`name`, `started_at`, `seen_at`).

**Runners** (`jobs/registry.py`, `jobs/runners.py`). `@register("kind")` maps a kind to a
function `runner(ctx: JobContext) -> dict`. The context has the params, the folders, the
progress callback and `input_file(name)` (which refuses names outside `input/`). The
built-in runners call the same core functions as the command line, so the files are the
same: `station` (`run_station`, with plots and zip), `batch` (`run_batch`; one progress
count for the whole batch, the sum of each station's last step over the sum of their
`pipeline_stages` + `plot_steps` totals; a failed station counts as done; `workers`
defaults to 1; each station's own progress goes to `output/stations.json`, see
[Batch page](#batch-page)), `sector` (`run_sector_correlation` on the station file and index tables
of a finished `station` job), `gridded-thresholds` and `gridded-indices`
(`write_grid_thresholds`, `write_grid_indices`; input files are read in place from the
paths given, local mode). The parameters of each are in the module docstring. The
batch page (#80) creates batch jobs; the sector and gridded runners are complete and
tested but no screen creates them yet (#90, #85). The core is imported inside each runner, so the web server never imports
xclim.

**The worker** (`jobs/worker.py`, `JobWorker`) runs one job at a time:

- *Claiming* is atomic. Where the database has `SELECT ... FOR UPDATE SKIP LOCKED`
  (Postgres), the oldest unlocked queued row is locked and marked running in one
  transaction. Elsewhere (SQLite) a conditional `UPDATE ... SET status='running' WHERE
  id=? AND status='queued'` takes a candidate; a worker whose update changes no row tries
  the next. Each claim increments `attempts`.
- *Progress* from the core is kept in memory and written at most every
  `JOB_PROGRESS_INTERVAL` (0.5 s) and at the last step, with
  `UPDATE ... WHERE status='running' AND cancel_requested=false`: a station run with plots
  has 113 stages in a few seconds, which costs a handful of writes. The update changing no
  row means the job was cancelled.
- *Heartbeat*: a thread updates the running job's `heartbeat_at` and the worker's
  `seen_at` every `JOB_HEARTBEAT_SECONDS` (10), and picks up a cancel request, so it is
  noticed even during a long stage.
- *Dead workers*: a running job whose heartbeat is older than `JOB_STALE_SECONDS` (60) is
  marked failed ("The calculation stopped unexpectedly ... You can try again."), with a
  retry offered. Any worker checks every heartbeat interval (`reap_stale`), and so does the
  progress fragment when it is asked about a running job, so an open page never waits for
  ever, even with no worker left. In local mode `climpact-web` knows at once when its
  worker child exits unexpectedly: it fails that worker's running job and starts a new
  worker after 2 s (at most 5 restarts a minute).
- *Cancel*: a queued job is cancelled at once; a running one at its next progress step,
  where the callback raises `JobCancelled`. `JobCancelled` and `JobInterrupted` derive from
  `BaseException`, like `KeyboardInterrupt`, because `run_batch` catches `Exception` per
  station and would otherwise carry on with the next one. With batch `workers` > 1, the
  stations already handed to the pool still finish before the cancel takes effect.
- *Stopping*: SIGTERM or Ctrl+C (CTRL_BREAK on Windows) sets a flag that raises
  `JobInterrupted` at the next step; the job is queued again (not failed) and runs on the
  next start. `climpact-web` waits 15 s for its worker to stop, then kills it and queues
  its job again itself.
- *Failures*: `JobError` and `ValueError` (the core's validation errors, e.g.
  `validate_params`, `BatchMetadataError`, `SectorCorrelationError`) are shown to the user
  as their message, with the job folder's path removed; `FileNotFoundError` names only the
  file; `MemoryError` says so; anything else shows a generic message naming the job id,
  and the traceback goes to the operator log and the `climpact_web.jobs` logger. A
  traceback is never shown in the browser. The stage where a failed run stopped is kept.
  Messages are stored in English at the time of failure (the core's messages are English
  too); translating them is left to the translation work.
- *Retry* (`Job.retry`) queues a failed or cancelled job again with the same inputs and
  parameters, at the back of the queue; its output folder is emptied when it starts.

In local mode `climpact-web` starts the worker as a **child process**
(`python -m climpact_web manage runworker --name <host>:<pid>/worker-<n>`) rather than a
thread: a crash or an out-of-memory error in a calculation does not take the web server
down, and the worker's imports (xclim, matplotlib) stay out of the server process.
Hosted mode runs `runworker` processes alongside the web servers (#12); more workers
claim different jobs. `runworker --once` runs the jobs waiting now and exits.

**Pages** (`/jobs/`). `jobs/` lists the session's jobs. Station runs are started from
the single-station steps (see [Single-station steps](#single-station-steps)), which
replaced #73's minimal form at `jobs/station/new`; the station file is copied into the
job as `input/station.txt`, never under a name from the browser.
`jobs/<id>/` is the job page; `jobs/<id>/progress` the progress fragment;
`jobs/<id>/cancel` and `jobs/<id>/retry` (POST); `jobs/<id>/files/<path>` downloads an
output file of a finished job (paths outside `output/` give 404). Any other session gets
404, as for a job that does not exist. The templates use the design system's components
(see [Design system](#design-system)): a status badge (`jobs/_status.html`), the progress
bar and note, alerts for failure, cancellation and a missing worker, the zip download
button and the file list in a disclosure; the list is a table with an empty state, and
the station form uses the field and drop zone components with an error summary. The
header links to the list as "Your calculations".

**Polling.** The fragment replaces itself (`hx-swap="outerHTML"`) after a delay the
server chooses: `hx-trigger="load delay:<n>s, visibilitychange[!document.hidden] from:document"`
with `hx-vals='js:{hidden: document.hidden}'`. The delay is 1 s for the first 10 s of a
run, 2 s up to a minute and 5 s after; 30 s while the tab is hidden, and a poll at once
when it is shown again. A finished job's fragment has no `hx-get`, so polling stops. It
shows the status, the readable stage (`jobs/stages.py`: `indices:climpact:spi` is
"Calculating indices (spi)"), step *n* of *total* with the percentage, the time so far and
a linear estimate of the time left (from the second step and 2 s on), for a queued job a
warning when no worker has been seen for `JOB_STALE_SECONDS`, and the cancel, retry and download controls.
Each GET is a plain request, so polling works through proxies and survives a dropped
connection (the next poll carries on).

**Retention** (`jobs/retention.py`). A finished job and its folder are deleted
`JOB_RETENTION_DAYS` (default 7, `CLIMPACT_WEB_RETENTION_DAYS`) after it finished; a queued
job that never ran, that long after it was created. Running jobs are never deleted. Folders
under `RUNS_DIR` named like a job id but belonging to none (an interrupted upload) are
deleted once older than the period. The worker purges at start and every hour
(`JOB_CLEANUP_INTERVAL`); `climpact-web manage purgejobs` does it on demand (and fails
stale jobs), for cron in a deployment. Every template gets `job_retention_days` (context
processor `climpact_web.jobs.context_processors.jobs`), for the upload page (#76) to state
the period; the job page shows the deletion date. Other apps register their own clean-up
with `register_purger(func)`; each purge calls `func(now, days)` (the stations app deletes
its analyses this way, so the jobs app knows nothing of them).

**Storage** (`jobs/storage.py`). `LocalJobStorage` creates the folders, saves uploads
(`save_input(job, name, file, folder="")`: the name is reduced to a file name, and a
folder, one plain word chosen by the code, puts it in `input/<folder>/`; `create_job` takes
such files as `"<folder>/<name>"` keys),
empties `output/` before a run, resolves download paths and deletes a job's folder. The
core reads and writes ordinary files, so a worker always works on a local folder. For AWS
(#12) the job folders can live on shared storage (EFS) with this class unchanged, or a
subclass can copy `input/` down from S3 before a run and `output/` up after it and serve
downloads from S3; `CLIMPACT_WEB_JOB_STORAGE` names the class.

The design system has no browser tests (no browser is installed for them; the axe checks
are #83). Instead `test_components.py` renders every component with sample parameters and
checks the accessibility hooks in the markup (labels, `aria-describedby`, `aria-invalid`,
`aria-current`, roles, the no-JS fallbacks), that the pattern library includes every
component, that every icon used exists in the sprite, the landing page with and without
the later screens' URLs (a stub URLconf), and the snapshot command.
`test_design_tokens.py` checks contrast, the chart palette export and the size budgets;
`test_static.py` checks logical properties in every stylesheet and that `ui.js` has no
imports or network requests.

### Single-station steps

The single-station flow (#76-#79, #90) replaces the R app's tabs
(`climpact/modules/singleStationStep1UI.R` to `singleStationStep4UI.R`). Step 1 (#76) is
built; the later steps add pages to the same object.

**Data model (#76).** A `StationAnalysis` (`stations/models.py`) is one station going
through the steps: a UUID primary key; `owner` (the session's job owner token, so a
session sees its analyses and its jobs, and any other session gets 404); `source`
(`upload` or `sample`); `file_name` (as uploaded, display only); `summary` (JSON from
`station_file.summarise`: first and last dates, days, per variable the days present and
missing, days with data per year, monthly means for the preview); `warnings` (about the
file); the metadata `station_name`, `latitude`, `longitude` (null until given),
`base_start`, `base_end` (R's defaults, 1971 and 2000); `step`, the furthest step reached
(`upload`, `qc`, `indices`, `results`, `sector`, the keys of `STATION_STEPS`); and
`qc_job`, `indices_job`, `sector_job`, links to the `Job` rows of the later steps (null on
delete). The file is kept in the analysis's own folder, `<MEDIA_ROOT>/stations/<id>/station.txt`
(not under `RUNS_DIR`, whose stray folders the jobs app deletes); a job copies it into
its own `input/` when queued, so analyses and jobs expire independently. Changing the
file or any metadata value clears the job links and sets `step` back (`reset_later_steps`),
so the later steps run again. `step_urls()` gives the step indicator a link for each step
reached whose URL exists; #77-#79 and #90 add `stations:indices`, `stations:results` and
`stations:sector` (all `/station/<id>/...`) and set the job links.

**URLs.** `/station/` upload page (`stations:upload`); `/station/sample` (POST) loads the
sample; `/station/sample.txt` downloads it (R links to the sample file too);
`/station/<id>/load` step 1 (`stations:load`); `.../load/validate` (htmx, POST);
`.../file` (POST) loads a different file into the analysis; `.../series.csv` the daily
series; `.../delete` (POST); `.../quality` step 2 (`stations:qc`) and
`.../quality/run-all` (POST).

**Step 1: the file.** The upload page has a drop zone around a real file input (a plain
multipart form, so it works without JavaScript; `ui.js` adds drag and drop), the sample
card, the retention note, the file format in a disclosure and the session's recent
analyses. `station_file.inspect_station_bytes` checks the file before anything is saved:

- *Problems* stop the file: empty, not text (a zip or Excel workbook, or NUL bytes), no
  data rows, a line without six values, a value that is not a number ("NA" and similar
  get "write missing values as -99.9"; a comma inside a number gets a note that commas
  separate values), no valid date, the last row dated before the first. Each names the
  **line of the file** (blank and header lines counted) and shows the line; at most 10
  are listed, with a count of the rest. The lines are walked with the core reader's rules
  (commas are separators, blank lines skipped, a first row whose first field is not an
  integer is a header), then the core itself (`read_station_file`, `merged_rows`) reads the
  file; its remaining errors are translated (`core_error_message`). A test checks that
  every `ValueError` the core reader raises has its own message.
- *Warnings* do not stop it, for what R accepts silently: dates that do not exist
  (dropped), rows dated outside the first row's and last row's dates (dropped), rows out
  of order (sorted), repeated dates (the indices use the last row), a variable with no
  values.
- The accepted file is stored as UTF-8 without a byte-order mark: the core reads with
  Python's default encoding, and a BOM would make the first data row a header (as it does
  in R). A header in Latin-1 is decoded as such.

**Step 1: the summary.** The load page shows the period, years and days (from the first
row's date to the last, as R's quality control), a table of days with data, days missing
and the share missing per variable (one value per date, the last row of a repeated date,
as the indices use), a static preview, the days with data in each year (in a
disclosure), a CSV download of the daily series and a form to load a different file
(the metadata is kept; the station name follows the new file name only if it was still
the default). The preview (`preview.py`) is two small inline SVG charts of monthly means
(maximum and minimum temperature, monthly total precipitation; months with fewer than 20
days are gaps), drawn on the server in the chart tokens. It is a placeholder: a
`CHART HOOK` comment in `stations/_summary.html` marks where the interactive chart of #75
replaces it, fed by `stations:series`.

**Step 1: the metadata.** The fields are exactly those of the R app: station name,
latitude, longitude, base period first and last year (`MetadataForm`). The name defaults
to the file name without its extension (as the command line does), reduced to letters,
digits, spaces and `.()-_` (it becomes folder and file names). Rules and messages:

| Field | R app | Python |
| --- | --- | --- |
| Station name | required ("Please enter a station name") | required; the characters above, not starting with a dot |
| Latitude, longitude | default 0, 0; must lie in -90..90 and -180..180 | start empty and are required (a forgotten 0 would put the station in the Southern Hemisphere); same ranges; latitude 0 gets a warning that it counts as Southern Hemisphere |
| Base period | default 1971-2000; years >= 0; the help says it "must be within the limits of the dates in the station data", but nothing checks it before the run | same defaults; the last year must not be before the first; a base period with no year inside the data is an error; partial coverage is a warning naming the years covered; 359 days or fewer of the base period inside the data (`MIN_BASE_DAYS`, the core's rule) is a warning that the percentile indices cannot be calculated, as the run would go ahead in R too |
| Sample | a link to the file; the user uploads it and types the metadata | one click: the analysis is created with the name, latitude -33.86 and longitude 151.21 (as in `reference/stations.csv`) filled in |

**htmx.** The form is split into groups (`MetadataForm.UNITS`: name, latitude, longitude,
base period). Each group is a `<div>` with `hx-post` to `.../load/validate`,
`hx-trigger="change"`, `hx-include="closest form"` and `hx-vals` naming the group; the
server validates the whole form and returns only that group, re-rendered with its
errors and warnings, which replaces the old one (`outerHTML`). Without JavaScript the
whole form is posted and the page shows every error with the error summary.
"Continue to quality checks" saves the metadata, moves `step` to `qc` and redirects to
step 2.

**Step 2 placeholder.** Until #77, `stations:qc` shows what was loaded and offers the
whole calculation with the default parameters (the `station` runner: QC files, every
index, plots and zip, each of the last two a checkbox), recorded as `indices_job`; this
is what #73's minimal form did. #77 replaces the page with the quality-check screen and
its own job.

**Retention.** An analysis is deleted, with its folder, `JOB_RETENTION_DAYS` after it was
last changed (`updated_at`), unless one of its jobs is queued or running
(`stations/retention.py`, run with every purge of expired jobs); folders under
`stations/` that belong to no analysis are deleted once older than the period. The pages
state the period and the date the analysis will be deleted, and "Delete this data now"
deletes it at once.

### Batch page

The batch page (#80) replaces the R app's batch screen (`climpact/modules/batchStep1UI.R`
and `batchStep1.R`): many stations from R's batch metadata file, run as one job.

**Flow** (`batch:start`, `batch:check`, `batch:results`; the step indicator's three steps,
`navigation.batch_steps`):

1. `/batch/`: two drop zones, the metadata file and the station files (several at once,
   or a zip; a zip may also hold the metadata file, found by its first line, 12 column
   names starting `station_file`, and may sit in the metadata box). "Use the sample batch"
   loads R's sample in one click: R's `climpact.sample.batch.metadata.txt` (bundled
   unchanged in `batch/sample_data/`) with two copies of the Sydney file under the two
   names it lists; R ships the same file twice, the package keeps the one gzipped copy of
   step 1. The sample metadata file downloads as a template (R links to it). The format,
   each column's meaning and the retention note are on the page.
2. `/batch/<id>/`: every station listed as **ready**, **file missing** or **has problems**,
   with the reasons, before anything runs; counts; files uploaded but not listed; each
   station's index parameters in a table; a form to add or replace station files or the
   metadata file (checked again at once); the options; and "Calculate *N* stations". A
   batch with some stations not ready can start: those are left out and reported.
3. `/batch/<id>/results`: one `batch` job for the ready stations. A fragment polled by
   htmx (`batch:progress`, the job page's delays) shows the whole batch's progress and
   each station (waiting, calculating with its own bar and stage, finished, failed, left
   out). When it has finished: a summary, "Download everything (zip)", and for each
   station its zip and "Open as a single station", or its error and error file;
   failures are listed first. The cancel and retry controls are the job's.

**Data model.** A `BatchRun` (`batch/models.py`): UUID; `owner` (the job owner token: any
other session gets 404); `source` (`upload`, `sample`); `metadata_name` (as uploaded); the
check result as JSON (`report`, `check.BatchCheck.to_json()`); the options `base_start`,
`base_end`, `workers`, `plots`; `job` (null on delete). Files live in
`<MEDIA_ROOT>/batches/<id>/`: `metadata.txt` and `files/<name>`, each station file under
its own name without folders (hidden names are ignored). Every change checks the whole
batch again. Retention as for analyses: `JOB_RETENTION_DAYS` after the last change unless
its job is queued or running (`batch/retention.py`, registered with `register_purger`);
"Delete these files now" deletes it at once.

**The check** (`batch/check.py`). The metadata file is walked with
`read_batch_metadata`'s rules (whitespace-separated fields, `#` comments and blank lines
skipped, the first line the header) and every problem is reported in plain language with
its line and the line's text, as step 1 does for station files: empty or not text, no
stations, a line without 12 values (with a note when commas are used), a value that is not
a number, a whole-number column (`wsdin`, `csdin`, `rxnday`, `txtn`, `SPEI`) with a
fraction, two lines giving the same station name. A test checks that the core reads what
the check accepts to the same stations. Any of these makes the metadata file unusable, as
`read.table` stops R's whole batch. A first line that looks like a station (12 fields, a
number second) is a warning: R and the core read it as the header, so that station is
left out. Then each station:

- *has problems* when its station file name is a path, its station name (the file name
  without its extension) breaks the station name rules (`jobs.forms.STATION_NAME`; it
  becomes a folder), its latitude or longitude is out of range, a parameter fails R's
  `validate_climdexInputParams` rules (the same as `climpact.batch.validate_params`,
  checked against it by a test), or its file fails step 1's checks
  (`inspect_station_bytes`: the same messages with file lines);
- *file missing* when no file of that name was uploaded, with a hint when a file of the
  same name in other capitals, or with another extension, was;
- *ready* otherwise, with step 1's warnings (dates R drops, repeated dates, latitude 0).

**Options.** The R screen's base period (here 1971-2000 by default) and, in the local
install only, the number of cores ("Stations to calculate at the same time", 1 to the
number of cores, R's messages for both limits), plus a "Draw the plots" checkbox (on).
An htmx fragment (`batch:options`) re-checks them as they change: the base period's order,
ready stations whose data cover 359 days or fewer of it (`MIN_BASE_DAYS`: their
percentile indices cannot be calculated) and a rough time estimate (10 s a station with
plots, 4 s without, divided by the stations at a time; R's modal says about a minute a
station per core).

**The job.** `batch:run` writes a metadata file in R's format with only the ready
stations (`check.metadata_text`, numbers written so they read back the same) and copies
their files as UTF-8 to `input/stations/`, then queues a `batch` job with `zip`,
`station_zips`, `folder` (the metadata file's name without its extension, as R names the
batch folder and zip) and `skipped` (the other stations and why). The runner writes each
skipped station's reason to `<folder>/<station>.errors.txt`, so the zip lists it like a
failed station; runs `run_batch` (a failing station fails alone, its error in R's error
file); zips each finished station to `output/stations/<station>.zip` (as R's
single-station zip) and the whole batch folder to `output/<folder>.zip`. During the run
`BatchStatus` writes each station's state to `output/stations.json` (atomically, when a
station starts or ends and at most every 0.5 s), which the progress fragment reads; at the
end the job's `result` lists each station with its files, error, error file and zip. A
station's error is shown without the exception's class name or the job folder's path.

**Per-station dashboards (#78).** Each finished station can be opened as a
single-station analysis ("Open as a single station", `batch:open_station`, POST): a
`StationAnalysis` with `source` `batch`, the station file, its name, location and the
batch's base period, at step 2 (the metadata is complete), and
`origin = {"batch", "job", "station", "params", "outputs"}`: the batch, its job, the
station, the `IndexParams` fields of its metadata line and its folder in the job's
`output/`. The indices step (#78) can start from those parameters and show the batch's
results; opening the station again returns to the same analysis. This keeps one
dashboard implementation (the single-station steps) rather than a second one for batches.

R behaviour not copied, and why:

| R batch screen | Python |
| --- | --- |
| Base period defaults to 1970-2010 | 1971-2000, as R's single-station screen, the command line and WMO's reference period |
| Number of cores defaults to 1 | up to 4, one core left free and no more than the stations; 1 when hosted (where the option is hidden, as in R) |
| A station listed but not uploaded is skipped silently; problems appear only after the run, in error files | the check lists every station's status and reasons before the run; stations not ready are left out with an error file saying why |
| A bad parameter or malformed metadata line stops the whole batch | a malformed metadata file is reported line by line before the run; a bad parameter leaves out only its station |
| Plots are always drawn | a checkbox, on by default (plots are about two thirds of the run time) |
| One zip of the batch folder | the same zip, and each station's own zip |
| Station files only as separate uploads | separate files or zips, with the metadata file in the zip if wanted |

## Development

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e "packages/climpact[dev]" -e "packages/climpact-web[dev]"
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest
```

- One venv holds both packages, installed editable with pip (no uv). New T3 worktrees get
  it from the project's "Set up venv" script, which runs the commands above.
- CI has three jobs. `core` and `web` run on Python 3.11, 3.12 and 3.13: `core` installs only
  `packages/climpact[dev]`, runs ruff, checks that `climpact_web` is neither installed nor
  imported in `packages/climpact`, and runs `pytest packages/climpact` (the full core
  suite, parity included); `web` installs both packages, runs
  `pytest packages/climpact-web`, `climpact-web manage check` and
  `makemigrations --check`. `web-postgres` runs hosted mode against a Postgres 16 service
  container, including a station job through the worker (see [Tests](#tests)).
- Start the web app with `.venv/bin/climpact-web` (see [Running the web app](#running-the-web-app)).

- Compute gridded thresholds with
  `.venv/bin/climpact gridded-thresholds <netCDF files> --out <file> [--tmax ... --base-start ...]`.
- Compute gridded indices with
  `.venv/bin/climpact gridded-indices <netCDF files> --out <dir> [--thresholds <file> --indices ... --workers N]`.
- Correlate sector data with a station already run with
  `.venv/bin/climpact sector-correlation <station file> <sector CSV> --out <dir> [--no-detrend] [--plots] [--zip]`.
- Run a station from the command line with
  `.venv/bin/climpact run <station file> --out <dir> [--lat ... --lon ...] [--plots] [--zip]`
  (`climpact run --help` lists the options), or a batch with
  `.venv/bin/climpact batch <metadata file> <data dir> --out <dir> [--workers N]`.
- Python 3.11+, xclim 1.0.x, netCDF4 and dask (gridded data); matplotlib 3.8+ for the
  plots (the optional `plots` extra, also in `dev`). CI runs on Python 3.11, 3.12 and 3.13 on **Ubuntu 24.04**
  (x86_64, glibc 2.39), pinned rather than `ubuntu-latest`. Its glibc is the C maths library
  the R reference was made with, so CI checks the SPI and SPEI files for text identity; on
  macOS they are checked to 1e-10 relative (`tests/libm.py`). Newer glibc releases differ:
  Ubuntu 26.04's `lgamma` differs from glibc 2.39 in the last bit on some inputs, so
  `test_libm_lgamma_matches_glibc_2_39` checks against fixed values printed in the R image.
- Always work inside `.venv`.
- To regenerate the R reference outputs, station, sector correlation or gridded, see `reference/README.md`. Re-running changes the
  `Date_of_calculation` line in every CSV, so only commit a re-run when the numbers are
  meant to change.
- Work is tracked as GitHub issues on the
  [climpactpy Kanban](https://github.com/users/geoffwalmsley/projects/2), grouped under
  epics (#8 station parity, #9 QC, #10 gridded, #11 web, #12 deployment). Branches are
  named `<issue>-<slug>` and PRs say `Closes #N`. Each ticket names the reference files it
  should make pass. The full workflow is in `.claude/skills/ticket/SKILL.md`.
