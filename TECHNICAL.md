# climpactpy technical notes

Technical documentation for the Python port of [Climpact](https://github.com/ARCCSS-extremes/climpact).
It covers how the code is organised, how results are checked against the R version, and
every known difference between the Python and R implementations and how each is handled.

Reference version: **Climpact R v3.4.3** (commit `5ee0cfe`), with climdex.pcic 1.2-0.

## Status

The Python port reproduces **all 125** R reference files for Sydney (`lat0` and
`sydney`), and every file R wrote for all 13 GHCN stations and the synthetic QC station,
with none failing and none left to port (see [Reference outputs](#reference-outputs)).
Sector correlation (the R app's step 4, `climpact sector-correlation`, #84) reproduces R's
ten files for Sydney with Climpact's sample wheat data, detrended and not (see
[Sector correlation](#sector-correlation)).
Gridded base-period thresholds (`climpact gridded-thresholds`, #29) reproduce every
variable of R's thresholds netCDF bit for bit on the six gridded reference grids that
have one, and the gridded indices (`climpact gridded-indices`, #30, #87) reproduce every
variable of all 88 index files R writes per grid, including the heatwave, EHF, SPI and
SPEI files, bit for bit on all eight reference grids, three of them in the `noleap` and
`360_day` calendars (#66; see [Gridded data](#gridded-data)). With `--trends` (and always
in the web app) a gridded run also writes `trends.nc`, each cell's Sen's slope per decade,
its 95% interval and base-period mean, and the grid mean, of every annual index (#290).
R's gridded code has no counterpart; each cell's trend equals the station trend file's
calculation on that cell's values (see [Gridded trends](#gridded-trends)).
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
| Quality control | qc/nastatistics, qc/tmaxmin, qc/toolarge, qc/duplicates, qc/tx_jumps, qc/tn_jumps, qc/tx_flatline, qc/tn_flatline, qc/outliers (see [Quality control](#quality-control)) | QC plots are not written as files (#9); the web QC screen draws the same plots (#77, see [A station's pages](#a-stations-pages)) |
| Other outputs | thresholds file (`thres/thres`), trend file (`trend/trend`), CSV files for all ported outputs, gridded thresholds netCDF, gridded index netCDF files, gridded trends (`trends.nc`, not in R; see [Gridded trends](#gridded-trends)), index plots (PNG) and the combined PDF, zip archive (see [Plots and zip archive](#plots-and-zip-archive)), a PDF report of a station run (not in R; see [PDF report](#pdf-report)), sector correlation tables and plots (`corr/`, see [Sector correlation](#sector-correlation)) | |
| Running | single station (`climpact run`), batch of stations from R's metadata file (`climpact batch`), gridded thresholds (`climpact gridded-thresholds`), gridded indices (`climpact gridded-indices`), sector correlation after a station run (`climpact sector-correlation`) | |
| Web app | Django + htmx skeleton (`climpact_web`): `climpact-web` starts it locally and offline, hosted mode reads its settings from the environment, health check; background jobs in a database-backed queue with a worker, progress pages, cancel, retry and retention; the design system (tokens, components, landing page, pattern library); Add stations (#233: one way into a workspace, for one file or many, reviewed in one table, see [Add stations](#add-stations)); the single-station workspace (#179, #198, #199, #201: a New station page with the file and the details and one button that checks and calculates (replaced by Add stations; its page stays as a station's setup page), then Quality, Indices (Results until #236) and Files as tabs beside the Inputs panel ("Your inputs") whose Edit opens a side sheet for each input, the quality thresholds and index settings included, with results kept and marked out of date after a change; the sector comparison as an action on Indices) with the PDF report (#79); the workspace overview (#234: a workspace of several stations, its run status line and Stations table, live as they calculate, Rename and Workspace settings, see [Workspace overview](#workspace-overview)); the workspace's Files (#239: Everything, the trends and indices of all stations as CSV, each station's R files and `climpact_run.json` in every zip, see [Workspace files](#workspace-files)); trends across stations (#238: the trend grid and the selected index's interval plot on the overview and Compare an index; #276: Overlay the series, an index's series at every station on a page of its own, see [Trends across stations](#trends-across-stations)); Copy to workspace… (#241: a station copied to another workspace or a new one, recalculated with its settings, see [Copy to workspace](#copy-to-workspace)); the landing page, Get started and Workspaces (#242: real output and the parity suite's facts on the landing page, every workspace of the browser in one table, Delete, see [Landing page and Workspaces](#landing-page-and-workspaces)); the workspace file (#240: Save file and Open a workspace file rebuild a workspace anywhere, see [Workspace file](#workspace-file)); interactive charts; batch processing of stations; gridded runs (#289: Gridded lists the runs, and a run has its context bar and Map, Files and Set-up tabs; #293: set-up is one page of sections beside a summary panel that is the check, and starting a finished run again keeps its results until the new ones are ready; #294: while a run calculates, or after it failed, its Map tab shows its stages and what to change, and starting again keeps the finished stages, see [Gridded pages](#gridded-pages)); in-app help: guide pages, contextual help topics, search and a first-run tour (see [Web front end](#web-front-end), [Background jobs](#background-jobs), [A station's pages](#a-stations-pages), [Batch page](#batch-page), [Gridded pages](#gridded-pages), [Help](#help) and [Charts](#charts)) | |
| Modules | QC, homogeneity and index module interfaces, third-party modules as plugins, module options (see [Modules and plugins](#modules-and-plugins)); built-in homogeneity module `none` (pass-through) | homogeneity detection (#34) and adjustment (#35) |

Progress is printed at the end of every test run (see [Parity testing](#parity-testing)).

The Python port writes every ported output as a Climpact-format CSV file, text-identical
to R's apart from the `Date_of_calculation` line (see [Writing output files](#writing-output-files)).
With `--plots` it also draws R's index plots and combined PDF, under R's file names, and
with `--zip` zips the outputs as R's download does (see [Plots and zip archive](#plots-and-zip-archive)).
With `--report` it writes a PDF report of each station beside the zip (see [PDF report](#pdf-report)).

## Repository layout

The repository holds two Python packages, each with its own `pyproject.toml` (hatchling)
and tests. They are the members of a uv workspace with one lock file, developed in one
virtualenv with both installed editable (see [Development](#development); #68, #116).

```
packages/
  climpact/          the core package: distribution `climpact` (`climpactpy` until #131),
                     imported as `climpact`.
                     Its dependencies are the scientific stack only (xclim, xarray, numpy,
                     pandas, scipy, dask, netCDF4); extra `plots`, dependency group `dev`
  climpact-web/      the web front end, `climpact_web` (src/climpact_web, tests/): a Django
                     project, depends on the core with its `plots` extra (matplotlib, for
                     the plots and the PDF report; see [Web front end](#web-front-end))
pyproject.toml       the uv workspace (members: both packages) and the development `dev`
                     dependency group; not a package itself
uv.lock              the locked versions for every supported Python (`uv lock`)
.python-version      the Python used for development (3.12)
reference/           the R reference outputs and the scripts that make them, shared at the root
ruff.toml            ruff settings for the whole repository (each package's pyproject.toml
                     extends it)
pytest.ini           `pytest` from the root runs both packages' tests, in parallel
                     (pytest-xdist); each package's pyproject.toml has the same settings for
                     running it alone
LICENSE              the GNU GPL v3 text; each package has a copy (hatch's `license-files`
                     cannot reach outside the package; a test checks they match)
RELEASING.md         how a release is made, and the one-time PyPI/GitHub setup (#131)
CHANGELOG.md         one entry per release of both packages
scripts/             build-css.sh, fetch-tailwind.sh, image.sh; set_version.py,
                     check_dists.py, smoke_dists.sh, fetch_published.py (the releases)
Dockerfile           the production image of the web app (#120; see [Deployment](#deployment))
docker/              its entrypoint (`entrypoint.sh`, the roles) and `healthcheck.py`
.dockerignore        keeps everything but the two packages' sources, the pyproject files
                     and uv.lock out of the image's build context
deploy/              the hosted stack on one Droplet (#121): `compose.yaml` and
                     `.env.example` (see [Compose stack](#compose-stack)); the Droplet's
                     `cloud-init.yaml` and the runbook `README.md` (#123; see
                     [Hosting: Droplet and tunnel](#hosting-droplet-and-tunnel)); the
                     Cloudflare rule expressions `cloudflare/*.txt` and `check-edge.sh`
                     (#124; see [Cloudflare edge](#cloudflare-edge)); `update.sh`,
                     `deploy-hook.py` and `call-hook.sh`, which deploy a release (#126;
                     see [Deploy on release](#deploy-on-release))
scripts/image.sh     builds, smoke-tests, scans, tags and pushes the image, for CI and
                     releases (#122; see [Image in CI and on ghcr.io](#image-in-ci-and-on-ghcrio))
.github/workflows/   `ci.yml` (every pull request and main), `image.yml` (the image job
                     both use) and `release.yml` (a published GitHub Release)
```

The core never imports `climpact_web`: `tests/test_layout.py` checks every Python file in
`packages/climpact`, and CI runs the core suite with only the core installed.

Paths in the rest of this document (`src/climpact/...`, `tests/...`) are relative to
`packages/climpact/`; `reference/...` is at the repository root.

```
src/climpact/
  cli.py             command line: `climpact run` (one station), `climpact batch` (many),
                     `climpact gridded-thresholds` and `climpact gridded-indices` (a netCDF
                     grid; `--trends` also writes trends.nc), `climpact modules` (list the modules available
                     and their options),
                     `climpact sector-correlation` (sector data against a station already run)
  modules.py         QCModule, HomogeneityModule, IndexModule; plugin discovery (entry
                     points); module options (Option); run_pipeline(): QC ->
                     homogeneity -> indices
  batch.py           batch mode: R's batch metadata file, run_station(), run_batch() process pool
  plots.py           index plots (PNG), the combined PDF and the zip archives (matplotlib,
                     optional: the `plots` extra)
  report.py          the PDF report of a station run: write_report(), report_file() (#79)
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
    trends.py        trends.nc (#290, not in R): sen_trends() (climpact.trends.sen_trend
                     vectorised over cells), base_means(), grid_means(), write_grid_trends()
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
  conftest.py        running in parallel: thread limits per worker, xdist groups of the
                     modules with module-scoped fixtures, and the R parity summary hook
  parity/            one test per R reference file and per gridded netCDF variable, plus
                     progress reporting; conftest.py: the cached builds and their xdist
                     groups; summary.py: the R parity summary and .parity-summary.txt
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

**Module options** (#63). A module declares the options it accepts in an `options`
attribute, a sequence of `Option(name, type, default, help, choices, required)`; `type`
is `str`, `int`, `float` or `bool`. A module that declares options gets them as the
keyword argument `options` of `build` or `homogenise`: a dict with a value for every
declared option (the user's, else the default). Modules without an `options` attribute
are called as before; the built-in modules take none.

- **Choosing them.** `ModuleSelection.options` is `{kind: {module name: {option:
  value}}}`, plain values, so batch workers receive it with the names. On the command
  line, `climpact run` and `climpact batch` take `--module-option [KIND:]NAME.OPTION=VALUE`
  (repeatable; `KIND` is needed only when two selected modules of different kinds share a
  name, as the built-in QC and index modules `climpact` do) and `--module-options FILE`, a
  TOML file of `[KIND.NAME]` tables; `--module-option` overrides the file.
- **Checking them.** `resolve()` checks every option (`option_values`) and raises
  `ModuleOptionError` for options of a kind or module not selected, an option the module
  does not declare, a missing `required` option, a value of the wrong type or not among
  `choices`. Strings (from the command line) are parsed to the option's type (`bool`:
  true/false, yes/no, on/off, 1/0); other values must have the type already (an int is
  accepted for a float). The command line reports the error before any station runs, and
  `run_batch` calls `resolve()` before starting the stations, so a bad option fails the
  batch rather than each station. The checked values are kept in `Modules.options`, keyed
  by `(kind, name)`.
- **Listing them.** `climpact modules` loads each module and prints its options under
  it (type, default, choices and help); a plugin that fails to load is reported and the
  listing goes on.

**Example plugin.** `tests/plugins/climpact_example_plugin` is a separate package with its
own `pyproject.toml` and one module of each kind: `example_qc` (`qc/example_hot_days`),
`example_shift` (a break in TX in the middle year, `homogeneity/example_breaks`, and TX
before it raised by 1 °C; options `adjustment` and `variable`) and `example_indices`
(`indices/example_txmean_ANN`).
`tests/test_modules.py` installs it into a temporary folder on `sys.path` by writing its
`.dist-info` (entry points from its `pyproject.toml`; no build step or network), then
checks that it is discovered, runs through `run_pipeline`, the command line and a
two-process batch, that QC tables come from the original data and the built-in indices
from the adjusted data, and that module options reach the module from `run_pipeline`,
`climpact run`, `climpact batch` and a two-process `run_batch`, with bad options rejected
before any station runs.

Not yet supported: trend rows for plugin indices (the trend file covers the built-in
indices only).

## Batch processing

`climpact batch <metadata file> <data dir> --out <dir>` ports Climpact's batch mode
(`climpact.batch.stations.r`, `server/batch_stations.R`). Options: `--base-start`,
`--base-end` (default 1971-2000, applied to every station, as R's command-line
arguments), `--workers` (processes; R's `cores_to_use`), `--custom VAR OP VALUE`, and
`--qc`, `--homogeneity`, `--indices`, `--module-option`, `--module-options` (see
[Modules and plugins](#modules-and-plugins)),
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
| `batch.run_station(..., progress=)` | `read` (`load_station`), the pipeline's stages, `write` (`write_outputs`): 22 for the built-in modules (5 with no index modules, `ModuleSelection(indices=())`, as the web app's QC job runs it: `read`, `qc:climpact`, `homogeneity:none`, `write`, `zip`). With `plots=True`, then one stage per row of `climate.indices.csv` and per custom-index frequency (`plots:fd_ANN`, ..., `plots:hw`, `plots:spei`, ...; `plots.plot_steps(params)`, 90 for the defaults), with `report=True` a `report` (`climpact.report`), and with `zip=True` a last `zip`: 113 in all (114 with the report) |
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
`[done/total] time slabs rechunked` and `[done/total] blocks done`, and `climpact
gridded-indices --trends` then `[done/total] trends` (one step per annual series), unless
`--quiet`.

`tests/test_progress.py` checks that every stage arrives once, in order, numbered 1 to
`total`, for the pipeline (built-in and plugin modules), a single station, a batch in one
process and in two worker processes (stages before each station's result), the gridded
thresholds and the command line, and that the files written with and without a callback
are byte-identical.

## Plots and zip archive

`climpact.plots` draws the plots R draws in `index.calc` (`services/calculate_indices.R`,
`plot.call` and `plot.hw` in `services/plot_indices.R`, `plot.precindex` in
`services/plot_prec_index.R`) and zips the outputs as `services/zipFiles.R`. matplotlib is
an optional dependency (`pip install 'climpact[plots]'`; it is in the `dev` dependency groups too). It is imported
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

**What each plot shows** is what R's show: the station name and coordinates (or the plot
title given to `write_plots(..., title=...)` and `run_station(..., plot_title=...)`, R's
"Plot title" of step 3, which replaces `title.station` in R too), the index
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

### PDF report

Climpact for R has no report: its downloads are the zip and `<station>_all_plots.pdf`.
`climpact.report.write_report(out_dir, metadata, params, path=None, qc=None, title=None,
date=None, progress=None)` (#79) writes one, read back from the files a run wrote to
`<out>/<station>/`, so it can also be made later for any run whose folder is kept:

1. a cover: station, coordinates, period of the data (from `qc/nastatistics`), base
   period, date, software versions, every `IndexParams` value and the `QCParams`
   thresholds (`qc`, default R's; the report states them, it cannot read them back);
2. the contents, two columns per page, each entry a link to its page;
3. the quality-control summary (`qc_summary`): the rows each `qc/` file lists, with what
   the check looks for, and the years with missing days (up to four columns of them, the
   rest referred to `qc/nastatistics`);
4. a page per index, in R's order: the plotted series of `plots.index_plots` grouped by
   `index_key` (`day_of_txx_MON` -> `txx`, `3month_spi_MON` -> `3month_spi`, as the web
   dashboard's cards). The first series is drawn by the same `plots._Canvas` as the PNGs,
   into a `SubFigure` of the page (`_Canvas` takes an optional `figure`); below it a table
   of Sen's slope, 95% interval and Mann-Kendall p of each series with a trend, then the
   index's DJF, MAM, JJA and SON rows of the trend file (which have no p-value).
   "Significant" means the interval excludes zero, as in the trends guide and the web app;
5. "Plots not drawn": the plot stages with no values, if any.

Pages are A4 landscape in Helvetica, one of the standard PDF fonts (no font embedded),
so the text is English and Latin-1 only, as the plots are. `run_station(..., report=True)`
writes it to `<out>/<station>_report.pdf` (`report_file`; `report_path` to choose), after
the plots and before the zip, with a `report` progress stage; it is **beside** the station
folder, so `zip_station` keeps R's file list. `run_batch(..., report_dir=...)` writes
`<report_dir>/<station>_report.pdf` from each worker process; `report_dir` should be
outside the batch folder, which `zip_batch` zips. `climpact run --report` writes
`OUT/NAME_report.pdf`, `climpact batch --report` writes `OUT_reports/NAME_report.pdf`.
`--report` without matplotlib is a command-line error, as `--plots` is.

**Accessibility.** matplotlib cannot write a tagged PDF (no structure tree), so the report
is not PDF/UA. It has what can be added without another library: the document title,
author, subject and keywords; `/Lang (en)`; `DisplayDocTitle`; bookmarks for the cover,
contents, quality control and every index (`PageMode /UseOutlines`); link annotations
from the contents; and real text, which can be searched, copied and read aloud.
matplotlib writes neither bookmarks nor internal links, so `_add_navigation` uses
`PdfPages`' private `PdfFile` (checked on matplotlib 3.11): it appends link annotations
to the pages' annotation lists, which matplotlib writes when the file is closed, and
writes the catalogue object a second time, later in the file, with the outline and the
language (the cross-reference table records the last offset). If those internals change,
the report is written without bookmarks and links and a warning is logged.
`tests/test_report.py` checks the cross-reference table, the outline in the last
catalogue, the links and the metadata; the Sydney report also opens in macOS PDFKit with
its 82 pages, 4 top-level bookmarks (78 index bookmarks under "Indices") and working
contents links.

**Tagged PDF (PDF/UA): not planned, left to WMO (#110).** Neither the report nor
`<station>_all_plots.pdf` is a tagged PDF. Both also use the standard Helvetica font
without embedding it (`_RC_PDF`, `pdf.use14corefonts`), which PDF/UA does not allow.
The same information is accessible on the web app's results pages (headings, tables, a
table view for every chart) and in the CSV files, and the accessibility statement
(`/help/accessibility/`, "Known limitations") says so. On 2026-11-15 the user decided not
to make the PDFs PDF/UA: whether a tagged PDF is required depends on the accessibility
policy of whoever hosts the tool, so it is WMO's decision if they adopt it. #110 records
the options compared:
- Typst (the `typst` package, Apache-2.0, native wheels with no Python dependencies,
  about 79 MB installed) writes a full structure tree and refuses to compile a PDF/UA-1
  document that breaks a rule it checks, such as a plot with no alternative text. It is
  the recommended route if a tagged PDF is needed.
- fpdf2 tags only images, ReportLab's open-source edition writes no tags, and WeasyPrint
  needs system libraries.
- Adding tags to matplotlib's PDF afterwards would be fragile.

veraPDF (`--flavour ua1`) is the suggested checker.

**Size and speed.** The Sydney run: 82 pages (cover, 2 contents pages, quality control, 78
indices), 440-460 KB, written in 2.6 s (Apple M-series). `tests/parity/test_plots.py`
checks that the Sydney zip, made after the report, unpacks to exactly R's file list (the
reference output folder and `plot-files.txt`).

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
| `regression(x, y)` | `lm(y ~ x)` on the years with both values, rounded to 2 decimals as R annotates the scatter plots (a `Regression`, or `None` with fewer than two such years); public for the web app's `sector` runner (#90) |
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
Options follow the wrapper's settings: input files (several per variable when it is split
along time, or patterns such as `'tasmax_day_*.nc'`, expanded in name order by the command
when the shell has not; see below), `--tmax`, `--tmin`,
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

- Each variable has time, Y and X dimensions (found from `axis`, `standard_name` or the
  dimension name), in one file or split along time across several (below); the three
  variables must share their time axis (truncated to days). The standard, `noleap` (`365_day`) and `360_day` calendars are
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
- **A variable split along time** (#291). Datasets such as AGCD, ERA5 and CMIP6 come as a
  file per year or decade. `open_grid` reads every file's header and coordinates once,
  then joins the files holding each variable in the order of their first day
  (`_check_parts`), and refuses, with a `ValueError` naming the two files: a different
  grid (sizes, or Y or X coordinates differing by more than a relative 1e-6), calendar or
  units (compared after normalising case and spaces), an overlap ("`a.nc` and `b.nc`
  overlap: both have the days from ... to ..."), or a gap ("a gap between `a.nc`, which
  ends on ..., and `b.nc`, which starts on ..."). Files are named by name, or by path when
  two share a name. A file may hold one variable or several; TX may be split by year while
  precipitation is one file. Each file is decoded with its own attributes (packed files
  often have a scale factor of their own) and the pieces are joined with `xr.concat`,
  then chunked again with the whole time series per block. `GriddedInput.parts` (and
  `parts_of(variable)`) gives each variable's `FilePart`s, the path and the time steps of
  the joined axis it holds; `files[v]` is the first, so the exemplar file whose time
  units, coordinates and attributes the outputs copy is the first TX file (the first
  precipitation file for the index files), and the output times are the same whatever the
  later files' time units. `tests/test_gridded_split.py` checks that the sample grid split
  into 20 yearly files (the later ones with other time units), read through the rechunked
  copy, gives every index file and the thresholds file with the same values as the whole
  file; that files given in any order are joined by date; per-file packing; and each
  refusal's message.
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
`var_daily_climpact_historical_NA_<first year>-<last year>.nc`), `--base-start`,
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
wrapper's `rxnday_n` is 7), the thresholds and trend files (`trends.nc`, written on
request, is not in R; see [Gridded trends](#gridded-trends)), the daily EHF/ECF series, the
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

### Gridded trends

R's gridded code writes no trends: `climpact.ncdf.wrapper.r` writes the index files only.
The gridded map's Base mean, Anomaly and Trend views and its grid mean (#296) need them, so
`gridded/trends.py` (#290) applies the station trend (`climpact.trends`, see
[Trend file](#trend-file)) to every cell of the annual index files a run writes.
`climpact gridded-indices --trends` writes `<out>/trends.nc` after the index files; the
web app's `gridded-indices` job does so by default (its stage `trends`, "Trends and the
map", see [Background jobs](#background-jobs)).

```
index files of one run
  -> gridded.trends.write_grid_trends
       annual_series        the annual series of the files
       per series, per stripe of rows (max_cells, default 100,000 cells):
                  sen_trends -> slope, lower, upper   batches of 512 cells on worker threads
                  base_means, and the weighted sums of the grid mean
       trends.nc            written under a temporary name, renamed when complete
```

**Which series.** Every index variable of each annual (`ANN`) file: one per file, ten in
`hw_ANN` (`hwm_tx90` ... `hwf_tn90`) and eight in `hwEHF_ANN` (`EHF-HWMD` ...), each with
its own variables; the `day_of_<index>` variables are dates and have none. Monthly files
of indices that also have an annual file give no series of their own (the annual file is
their annual series, as the station trend file's `annual` row uses the annual values).
SPI and SPEI have only monthly files: their series is the 12-month scale's December value
(the calendar year), which the station trend file also has as its `spi12`/`spei12` `DEC`
row. `tx95t` (a day-of-year climatology) has none. All series must share the grid and the
years (`ValueError` otherwise); with no annual series nothing is written (`None`).

**Per cell**, for each series `<name>`:

| Variable | Dimensions | What |
| --- | --- | --- |
| `<name>_slope` | Y, X | Sen's slope per decade: `sen_trend`'s slope (per year, `x` counting years) times 10 |
| `<name>_lower`, `<name>_upper` | Y, X | its 95% interval (`confint.zyp`), per decade |
| `<name>_base_mean` | Y, X | the mean of the base-period years that have a value, as the station index page's base-period mean (`index_page.base_mean`); missing when none has |
| `<name>_grid_mean` | time | the mean over the cells with a value, weighted by the cosine of the cell's latitude (`cell_weights`; the input's `cell_latitude()`, or the files' Y coordinate) |

The trend rules are the station's: missing unless at least 10 values and 70% of the years
have one (`min_trend_data`). Missing cells (the fill value in the index file) stay missing.
An infinite value (EHF-HWPS `-Inf`, see [Gridded indices](#gridded-indices)) counts as a
value for the trend, as in the station code, but not for the means.

**Equal to the station trend.** `sen_trends` computes `sen_trend` for a batch of series
with the same arithmetic. The pairwise slopes of the valid values are the same numbers in
another order (a pair with a missing value is NaN and sorts last). `x` is whole years, so
it has no ties, and Kendall's float32 `Var(S)` reduces to `(n (n - 1) (2n + 5) -
sum t (t - 1) (2t + 5)) / 18` over the float32 tie groups of `y`; its integer sums are
exact in float32, whatever the order TAUK2 adds them in, for up to 200 values
(`MAX_VECTOR_YEARS`). The bound positions are rounded half to even (`np.rint`, as Python's
`round`), and only the four order statistics needed are found, with `np.partition` on the
rows that need the same positions. R's median of an even count is R's extended-precision
mean of the two middle values; for two doubles whose sum is exact in 64 bits (exponents at
most 10 apart, or a zero) that is `(a + b) / 2` in double precision, and any other pair goes
to `r_mean` (`_mean_of_two`). A series with an infinite value, more than 200 values, or
bound positions outside the slopes (`confint.zyp`'s edge cases) goes to `sen_trend` itself.
`tests/test_gridded_trends.py` checks that each cell's slope and bounds equal `sen_trend`
bit for bit (series with ties, ties only in float32, heavy ties, constant series, missing
values, too few values, infinite values, values of very different sizes; with and without
threads), that `_mean_of_two` is `r_mean`, and that the file holds, per cell, the station
trend of the values in the index file, with missing cells missing.

**Writing.** Dimensions `time` (the years of the annual files, with their `time` values,
attributes and bounds; the December values' for SPI and SPEI alone), Y and X (the index
files' coordinates and attributes), `bnds`. Variables are float64 with fill value 1e20,
compressed; each has `units` (the index's, `<units> per decade` for the slope and its
bounds), `long_name`, `index_file`, and `cell_methods` for the means. Global attributes:
`title`, `base_period`, `trend_period`, `trend_method`, `source`,
`climpact_python_version`, `file_created`. See [Performance](#gridded-trends-1) for
timings.

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
  (so each chunk is decompressed once); no slab crosses from one file of a variable split
  along time to the next. Each slab of each variable is written as one
  tile per block, sequentially; a block is then read back with one read per slab and
  variable (`_TileFile`). The raw values of each slab are decoded and converted with its
  file's type and attributes exactly as `GriddedInput.load` does (`_to_climpact_units`,
  the same `decode_ncdf4` and unit conversion), so the values of every block, and every
  output, are identical.
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
`climpact_python_version`, and the time units of `grid_sample` (see
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
uv run pytest                                   # everything (both packages) but the browser checks
uv run pytest -m browser                        # the browser accessibility checks only
uv run pytest packages/climpact                 # the core only
uv run pytest packages/climpact/tests/parity    # parity only
uv run pytest -n 0 ...                          # in one process (for --pdb, print debugging)
```

#### Running the tests in parallel

The tests run in parallel with [pytest-xdist](https://pytest-xdist.readthedocs.io/) (#181):
the default options (`pytest.ini` and both packages' `[tool.pytest.ini_options]`) include
`-n auto --dist loadgroup`, one worker process per core. `-n 0` runs everything in the
pytest process, as before; `--pdb` does that by itself. Measured on a 12-core Apple M-series
Mac (2026-11-16), the default run (both packages, without the browser checks) went from
8 min 17 s in one process to 1 min 17 s, for about 40% more CPU time (each worker imports
the scientific stack, and the cores are shared).

- **Groups.** Many tests share a build cached in a session- or module-scoped fixture, which
  each worker would otherwise make again. With `--dist loadgroup`, tests with the same
  `xdist_group` mark run in one worker, and the marks are added at collection
  (`pytest_collection_modifyitems`, not in the test modules). The parity tests
  (`tests/parity/conftest.py`) are grouped by the build they use: `station-<run>`
  (`station_outputs`, `station_run`, and the fixtures built on them: `written_files`,
  `sector_files`), `grid-thresholds-<run>` and `grid-indices-<run>`. Tests not
  parametrised by run (sector, batch, the plot files) use `sydney`, so the `sydney` build
  is made once; `test_batch.py` also builds `nairobi`, a second time. Whole modules are
  grouped where their module-scoped fixtures are shared: `test_drought.py` and
  `test_ehf.py` (`tests/conftest.py`), `test_page_budget.py` and `test_accessibility.py`
  (`packages/climpact-web/tests/conftest.py`). Every other test is handed to whichever
  worker is free. A group's name is appended to the test id (`...[sydney/indices/fd_ANN]@station-sydney`).
- **pytest version.** pytest-xdist 3.8.0 adds the group to the test id by setting
  `item._nodeid`, which pytest 9.2 no longer reads: with 9.2, `--dist loadgroup` silently
  ignores every `xdist_group` and each worker rebuilds every station and grid it gets a test
  of (the default run then took almost five times the serial run's CPU time, and was only
  2.3 times faster).
  This is pytest-xdist#1386, fixed on its master branch after 3.8.0, so the dev groups pin
  `pytest<9.2`; remove the pin with the first pytest-xdist release that has the fix, and
  check that the ids still carry the groups or that each group still runs in one worker.
- **Threads.** The main process sets `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`,
  `MKL_NUM_THREADS`, `VECLIB_MAXIMUM_THREADS`, `NUMEXPR_NUM_THREADS` and `DASK_NUM_WORKERS`
  to 1 before it starts the workers, which inherit them (`pytest_configure` in both
  conftest files; a value already set is kept): the workers already use every core. Tests
  that choose their own threads or processes (`workers=2`, the batch process pool) are not
  affected.
- **Summaries.** The workers send every test report to the main process, which prints the
  summaries. The R parity summary is therefore a hook of `tests/conftest.py` (calling
  `tests/parity/summary.py`), not of `tests/parity/conftest.py`: that file is loaded only
  where tests are collected, which under xdist is the workers, and a worker sees only its
  own tests. The hook does nothing in a worker, so a worker never overwrites
  `.parity-summary.txt`. The page sizes of `test_page_budget.py` travel the same way, as a
  `user_properties` entry (`page_sizes`) on each report.
- **Isolation.** Each worker has its own pytest temporary folder, its own test database
  (pytest-django) and its own data folder (`web_test_settings.py` makes one per process).
  Tests that start servers use `--port 0` and a folder of their own, and
  `test_queue_postgres.py` makes a database with a unique name. Warnings are counted once
  per worker, so the total in the last line is larger than in a serial run.

Files that no product builds are reported as `xfail` ("not yet ported"); there are none
now. A summary is printed at the end. The same lines, with a header giving the time, the
pytest command, the Python version and the test totals, are written to
`.parity-summary.txt` at the repository root (git-ignored;
`packages/climpact/tests/parity/conftest.py`). The section is longer than a `tail` of the
output shows, so read the file rather than running the suite again:

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
| `read_user_file` reads the columns with `read.table(colClasses = rep("real", 6))`, whose default `na.strings = "NA"` makes the field `NA` (exactly; `na`, `N/A`, `+NA` stop R with "scan() expected 'a real'") missing in any column. `NaN` in any case is read as a missing number too, and `Inf`/`infinity` (any case) as infinite numbers. An `NA` in the year, month or day makes the date invalid, so the row is dropped (and in the first row's first field it makes the row a header). Checked with the R image in `reference/r` | same (`io.station.read_station_rows` reads `NA` as NaN, `NA_STRING`; Python's `float` already reads `NaN` and `Inf` as R does and refuses `na`). The web app's station file check (`stations/station_file.py`, used by a station's setup page and Add stations' review) accepts `NA` as missing too; it still refuses `Inf` and offers "-99.9 (or NA, in capitals)" for `na`, `N/A`, `NULL`, `-` and `.` (#99). The help guides keep -99.9 as the recommended code |
| `scan` reads hexadecimal numbers (`0x10` is 16) and refuses digit separators (`1_0`) | Python's `float` does the opposite: `0x10` is an error and `1_0` is 10. Neither appears in a real station file; not changed |
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
| No report | `--report` (and the web app, by default) also writes `<station>_report.pdf` (`climpact.report`, #79), beside the station folder, so the zip's file list is still R's (checked for Sydney by `tests/parity/test_plots.py`); see [PDF report](#pdf-report) |

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
| `create.file.metadata` and `get.data` (climdex.pcic.ncdf) read each variable from one file; R's gridded screens and wrapper scripts take one file per variable | a variable may be split along time across several files, joined in the order of their first day after checking grid, calendar, units, overlaps and gaps (#291, see [Gridded data](#gridded-data)). The results are those of the joined file: the sample grid split into 20 yearly files gives identical index and thresholds files (`tests/test_gridded_split.py`) |
| `calculate_EHF` on a series that does not start on 1 January has its first 32 values missing; with the padding, the first EHF values of such a file use the padded (missing) days | as above: only files not starting on 1 January differ |
| Bounds variables of X and Y (`lat_bnds`, ...) are copied (Climpact's README says inputs must not have them) | not copied; `time_bnds` uses a dimension `bnds` |
| Non-standard calendars: PCICt supports `365_day`/`noleap` and `360_day` (and stops on others) | supported the same way (#66), including R's `%Y-%j` threshold dates in `noleap` leap years, `climdex.hw`'s threshold lookup by month and day of 2001, and `day_of_<index>` numbers read as standard dates (see [Non-standard calendars](#non-standard-calendars)); `all_leap` and `julian` raise `NotImplementedError`. Identical on `grid_filled_noleap`, `grid_filled_360day` and `grid_sample_360day` |
| Units udunits cannot convert to kg m-2 d-1 (`mm/day`) stop the run | `mm/day`, `mm d-1`, `mm day-1` and `mm` are accepted as kg m-2 d-1 |
| `put.ETCCDI.atts` writes `R_version` and `climdex.pcic_version` (1.2.0); `history` says `Created by climdex.pcic 1.2.0 on <date>` | no `R_version`; `climpact_python_version` instead; `climdex.pcic_version` is 1.2.0 (the version reproduced, as `Climpact_version` 3.4.3); `history` says `Created by Climpact for Python <version> on <date>` |
| Only TX, TN or precipitation alone: `get.thresholds.metadata` still lists all 21 variables and writing stops | all three variables are required, checked when the files are opened |
| R writes an uncompressed file with one chunk per day | compressed (zlib), chunked by block; the content is the same |
| R reads each stripe straight from the input files, however they are chunked: with files chunked by time step, every stripe decompresses the whole file | inputs chunked by time step are copied once to a temporary file laid out by block (`GriddedInput.block_reader`, see [Rechunking](#rechunking-inputs-chunked-by-time-step)); the values read are identical |
| Gridded indices: R stops in `write.climdex.results` on the `hw` and `hwEHF` files of any grid with an all-missing cell (`climdex.results[[i]][[ind]][[2]]` of the cell's `NA`), after writing part of the files | **Not copied** (decided 2026-11-14, #87): Python writes every file, with missing values (the fill value) for the all-missing cell, as for every other index. The `grid_stations` and `grid_future` R references leave `hw` and `hwEHF` out for this reason; `grid_filled` has no all-missing cell. `test_r_missing_values` checks the all-missing cell |
| Gridded indices: for a cell with TAVG on less than half of the base period, `climdex.hwEHF` prints "NOT CALCULATING EHF HEATWAVES, LESS THAN 50% OF BASE PERIOD DATA AVAILABLE..." and returns `NULL`; `write.climdex.results` then stops on `hwEHF` ("subscript out of bounds": it turns the `NULL` into a one-element list and takes its second element). The first `grid_filled` run hit this on its sparse cell, which is why that cell was changed | **Not copied** (#87, same decision): the cell's eight EHF variables are missing (`hwehf_values`), as the station product writes no EHF files then. With a thresholds file R makes no such check, and neither does Python. `test_ehf_needs_half_of_the_base_period_unless_thresholds_are_given` |
| Gridded indices: EHF85 missing from a thresholds file (a cell without positive base-period EHF) makes every severity `NA`; R's `max(na.rm = TRUE)` and `sum(na.rm = TRUE)` then give EHF-HWPS `-Inf` and EHF-HWLS 0 in years with heatwaves, written as such | reproduced (`annual_aspects` drops missing severities; `_write_block` keeps infinite values). The station product had raised an error in this case (possible only with no positive base-period EHF); it now gives R's values too. No reference grid has such a cell; the unit test above checks it |
| Gridded indices: bounds variables of X and Y, a `grid_mapping` variable and two-dimensional coordinate variables named in `coordinates` are copied to every index file | not copied, as for the thresholds; X and Y are float64 |
| Gridded indices: `create.climdex.cmip5.filenames` names monthly files with years only (it looks for `_mon` in lower case) and needs a six-part template; `rxnday_n = 5` writes `rx5day` twice | the same names; a template with fewer parts is refused; `rx5day` is written once |
| Gridded indices: `create.ncdf.output.files` gives tx95t's `time` a `calendar` of `365_day`, replaced by the input time's calendar when it has one; its `bounds` attribute names a variable that does not exist | the same |
| R's gridded code (`climpact.ncdf.wrapper.r`) writes no trends, base-period means or grid means | **Not in R** (#290): `trends.nc` (`gridded/trends.py`, `climpact gridded-indices --trends`, on by default in the web app): each cell's Sen's slope per decade and 95% interval, computed as the station trend file does and equal to `climpact.trends.sen_trend` on the cell's values bit for bit; the base-period mean; the cos-latitude weighted grid mean. The index files are unchanged. No R reference; see [Gridded trends](#gridded-trends) |

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

**QC plots and the app's Quality tab (#77).** R's quality-control step also draws plots
(`createPlots`/`pplotts`: daily series and the precipitation histogram;
`fourboxes`, `roundcheck`, `boxseries` in `services/check/`) as PNG and PDF files, combined
into `<station>_QC_PLOTS.pdf`. The core does not write them (the QC CSV files are what the
parity suite compares); the web app's Quality tab shows the same plots on screen instead
(interactive daily charts per variable, and `stations/qc_plots.py` for the box plots,
decimals and histogram, see [A station's pages](#a-stations-pages)), so a station
run from the web or the command line has no QC plot files. R's step 2 writes the
thresholds file as well (`thres/`); the web QC job writes only `qc/`, and the thresholds
file comes with the indices (the station run). R's per-station QC zip holds the `qc` folder; the
web QC job's `<station>.zip` holds `<station>/qc/`, the same files.

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
- Climpact R's `climate.indices.csv` gives `tmge10` the long name "TX of at least 10
  degrees_C", though it counts days with TM >= 10 °C (its definition says so). The core's
  copy (`climpact/data/climate.indices.csv`) keeps R's text, because it is the
  `long_name` attribute of the gridded `tmge10` netCDF files, which
  `tests/parity/test_gridded_indices.py` compares with R's; no station output uses the
  long name. The web app uses "TM of at least 10 °C" (`LONG_NAME_FIXES` in
  `climpact_web/help/indices.py`, #217) wherever it shows R's long name: the index page's
  "Name in Climpact for R" line, the help and the gridded index list. Elsewhere the web app
  names an index by its code and short name (#218), "TMge10 Days TM ≥ 10 °C". Station and gridded results are identical to R's.

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

### Gridded trends

`write_grid_trends` (#290) on synthetic annual index files, 55 indices of 60 years
(1961-2020; half integer day counts, heavily tied, half to one decimal), every cell with
values, Apple M-series laptop with other work running:

| Grid | 1 thread | 4 threads | `trends.nc` |
| --- | --- | --- | --- |
| 38 x 50 (1,900 cells) | 3.8 s | 1.4 s | 3 MB |
| 145 x 192 (27,840 cells, the ACCESS grid) | 47 s | 16 s | 33 MB |

`sen_trend` called cell by cell takes about 0.17 ms per series, about 260 s for the ACCESS
grid's 1.5 million series. Most of the time left is `np.partition` (the four order
statistics of 1,770 slopes per series); reading and writing take under 10%.

## Web front end

The web app (epic #11) replaces the R Shiny app (`climpact/ui`, `climpact/modules`). It is
**Django + htmx**, server-rendered with Django templates (decided in #11). The
`climpact-web` package depends on the core and calls it as a library; the core never
imports `climpact_web`. This section describes the skeleton (#69) and the design system
(#71); the screens follow in #73 (jobs, described in [Background jobs](#background-jobs)), #75 (charts, described in [Charts](#charts)), #76-#78 and #90 (a station's pages, described in [A station's pages](#a-stations-pages)), #79
(downloads, described there too), #80 (batch, described in [Batch page](#batch-page)), #81 (help, described in [Help](#help)), #85 (gridded, described in [Gridded pages](#gridded-pages)), #82 (size budget, described in [Size budget](#size-budget)) and #83
(accessibility, described in [Accessibility](#accessibility)).

### Layout

```
packages/climpact-web/src/climpact_web/
  settings.py        the one settings module; every value from environment variables
                     (local or hosted mode, see below); reading it has no side effects
  urls.py            root URLs: i18n/ (set_language), jobs/, station/, batch/, gridded/, help/, charts/ and the core app;
                     later apps add their own include here
  wsgi.py            WSGI application, for waitress and hosted servers
  middleware.py      ContentSecurityPolicyMiddleware (Django's, with a nonce on every
                     HTML page, #164); UploadSizeLimitMiddleware: 413 for request bodies over MAX_UPLOAD_MB
                     (GRIDDED_MAX_UPLOAD_MB under /gridded/); StaticFilesMiddleware
                     (WhiteNoise); CompressionMiddleware (gzip for text answers, #82);
                     PrivateCacheMiddleware; RefusalMiddleware (the page and log line for
                     a request the hosted limits refuse, #125)
  cli.py, __main__.py  the `climpact-web` command (also `python -m climpact_web`); starts
                     the background worker as a child process in local mode
  core/              the UI shell app (label `core`): landing page, /patterns/, /healthz,
                     the context processor `site`
    landing.py       the landing page's preview of the Sydney sample's real output, its
                     facts (the parity suite's counts) and the miniatures' values (#242)
    navigation.py    the app's destinations (header links, landing page); no page has a
                     step indicator since #289 (station tabs since #179, the batch none
                     since #234, a gridded run's tabs since #289)
    tokens.py        reads the design tokens back from the Tailwind source; writes
                     chart-palette.json
    numbers.py       the number rules (#226): minus, places, units, coordinates
    tailwind/        the stylesheet's source (#118): climpact.css (the entry: layers,
                     sources, the dark variant, custom utilities), theme.css (the tokens,
                     @theme), base.css (dark token values, element styles),
                     components/*.css (the repeated pieces, @layer components)
    storage.py       the static files storage: hashed names, gzip and Brotli copies,
                     minified CSS (StaticFilesStorage, LocalStaticFilesStorage; #82)
    forms.py         PatternDemoForm, the example form on the pattern library
    limits.py        the hosted site's abuse limits (#125): client_ip, Turnstile
                     (verify_turnstile, human_required), the quotas (check_job_quotas),
                     the disk guard (check_disk, disk_required), Refused
    templatetags/ui.py  `{% icon %}`, `{% turnstile %}`, the `times` and `token_name` filters
    management/commands/design_snapshots.py  static HTML copies of the pages for review
    templates/       base.html (the page shell), 404.html, 413.html, 500.html, refused.html,
                     core/home.html (landing), core/patterns.html (pattern library),
                     core/language_switcher.html, components/*.html (the components)
    static/climpact_web/
      css/climpact.css  the one stylesheet, built from tailwind/ by the Tailwind CLI and
                     committed (#118): tokens, both themes, base styles, every component,
                     uPlot's stylesheet and the utilities the templates use
      js/ui.js       progressive enhancement: theme toggle, tabs, drop zone, dialogs, toasts,
                     the announcer and focus kept across htmx swaps (#83), the progress
                     polls' tab visibility (#137)
      js/drawer.js   the help drawer (#177): opens a section's help beside the content
      js/site-header.js  keeps --site-header-measured to the sticky site header's height
                     (#284), which everything that sticks under it and the scroll
                     padding use
      js/help-toc.js  the help frame's On this page (#325): marks the section in view
      js/setup.js    a station's setup page (New station, #201): Replace on the file card
                     reads the chosen file at once, focus on the card after reading
      js/add-stations.js  Add stations (#233): files sent as soon as they are chosen or
                     dropped, the table checked as it is typed, a pasted column filled
                     down, Enter moving down a row
      js/context-bar.js  keeps the page's scroll padding to the height of the sticky
                     context bar (#227; the workspace header's js/workspace.js, #197; on
                     phones the part that stays, #203), and closes the phone's ⋯ page
                     menu and the workspace's Export ▾ (#239) on Escape or a click
                     elsewhere (#203), loaded by components/context_bar.html
      js/copy.js     Files' "Copy methods text" (#239): the text's disclosure becomes a
                     button that copies it
      js/index-page.js  an index's page (#237): Values / Anomaly in place, Copy citation
      js/trends.js   the trend grid (#238): a column's interval plot in place
      js/sheet.js    opens an Inputs panel's side sheet, a modal dialog (#198), the
                     sheet an old address asks for as the page loads (#199), and the
                     phone's Inputs sheet from the Inputs bar (#203), loaded by
                     stations/_inputs.html
      js/theme.js    applies the stored theme before the page paints (blocking, #137)
      js/turnstile.js  holds a form with a Turnstile widget until its token comes (#163),
                     loaded with the widget only
      js/tour.js     the first-run tour of the landing page (#81), loaded there only
      js/gridded.js  the gridded set-up page: All, None and "Without the slow ones" for
                     the indices, a file's header in a dialog, Copy beside a CDO command,
                     and Browse's listing (#320) filling its field in place
      js/gridded-map.js  the gridded Map (#295): the rail's Find, the map and pane swapped in
                     place, the cell under the pointer read out (by view, #296), the arrow keys
      js/charts.js   the interactive charts (#75): hydrates chart frames with uPlot
      js/qc.js       Quality: the checks' rail and the check's detail, its values in place (#202, #235, #264), linked to the daily charts (#77, #174)
      js/results.js  the Indices: the rail's filters (#78), column sorting (#200) and the detail pane (#236), that page only
      js/sector.js   the sector comparison (#90): fills the y-axis label from the chosen file's name
      icons/icons.svg     the icon sprite (drawn for this project); favicon.svg
      chart-palette.json  chart colours for both themes, generated from the tokens
      vendor/htmx/   htmx 2.0.11, vendored; README.md records its source URL and SHA-256
      vendor/uplot/  uPlot 1.6.32 (JS, CSS, MIT LICENSE), vendored; README.md records the
                     source URLs and SHA-256s
  jobs/              background jobs (label `jobs`, see [Background jobs](#background-jobs))
    models.py        Job (the queue and its progress), JobStart (the daily quota's
                     records, #125), Worker (running workers)
    registry.py      runner registry, JobContext, JobError, JobCancelled, JobTimedOut,
                     JobInterrupted
    runners.py       the built-in runners: station, qc, batch, sector, gridded-thresholds,
                     gridded-indices (thin wrappers of the core functions)
    worker.py        claiming, progress writes, heartbeats, dead-worker detection, the
                     worker loop (JobWorker)
    retention.py     purge_expired: old jobs and their folders
    storage.py       LocalJobStorage: the per-job folders (the S3 hook for #12)
    stages.py        readable names of the core's progress stages, in words only (#226)
    views.py, urls.py  /jobs/: list, job page, progress fragment, cancel, retry, file
                     downloads
    forms.py         STATION_NAME and safe_station_name (the station name rules)
    context_processors.py  `job_retention_days` for every template
    management/commands/  runworker, purgejobs
    templates/jobs/  job_list.html, job_detail.html, _progress.html, _status.html
  stations/          the single-station workspace (label `stations`, see
                     [A station's pages](#a-stations-pages))
    models.py        Workspace (stations and their shared settings, #231, #254), Station
                     (one station of a workspace, with its slug); slug_for, file_digest
    workspace.py     the sections each job shows, a station's settings (the workspace's
                     with its own values, station_settings), staleness from the jobs'
                     recorded inputs, settle, undo_available, the tabs' states (#179),
                     the Inputs panel, its sheets and what each updates (#198, #199)
    calculation.py   queueing the checks and the run, speculative runs, recalculate,
                     bring_up_to_date after a change (#178, #179), change_settings and
                     undo for the workspace's settings (#254)
    station_file.py  checks an uploaded file (plain-language problems at file lines,
                     warnings) and summarises its data
    forms.py         UploadForm, MetadataForm (the details) and its parts for the Station
                     and Base period sheets (StationForm, BasePeriodForm, #198),
                     QCParamsForm and QC_DEFAULTS (the thresholds)
    qc_review.py     Quality's results: reads the qc job's files back, adds context from the
                     station rows, missing data per year, the verdict and its limits, the
                     checks as a rail (wrong_groups, worth_groups, Item, Review.items,
                     #174, #202, #264), each check's values table (value_columns, sorted
                     largest first), its When and By calendar month charts and its
                     selected value with the days around it (build_finding), the coverage
                     strip and the flagged values as CSV (flagged_rows, #235, #264)
    qc_plots.py      Quality's distribution plots (R's QC plots) as inline SVG with tables
    forms_indices.py IndexParamsForm (the Index settings sheet, #78, #178, #199): every
                     IndexParams field, checked by the core's validate_params
    calculation.py   queueing the station run (#178): the speculative run with the
                     workspace's settings (speculate, commit), a recalculation
                     (queue_station_run), the form's starting settings (previous_params,
                     settings_form)
    preview.py       the static monthly preview (inline SVG), the daily chart's no-JavaScript
                     fallback
    retention.py     purge_expired_workspaces and kept_jobs, registered with the jobs
                     app's purge
    results.py       the Indices' model: one card per index table,
                     sparklines, trends, tables not written and why; cached
    index_detail.py  the Indices' detail pane (#236): each index's chart drawn on the server
                     (axes, base period, Sen's slope), its read-out data (#283), its text
                     alternative and statistics
    index_page.py    one index's page (#237): its chart drawn on the server (values or
                     anomalies, running mean, Sen's slope and interval, values left out)
                     and the same as data for charts.js (payload, #283), the statistics,
                     why values were left out, the table and the citation
    themes.py        the Indices' themes (#175): the index-to-theme mapping (Heat, Cold,
                     Rain, Drought, "Also measured") the rail filters by, and their hues
    add_stations.py  Add stations (#233): each file read once (read_files), the review
                     table with every problem in one pass (review), tidy_name
    views_add.py     /add/, /w/<id>/add/ and the files waiting at /w/<id>/add/<files>/
                     (#233): staging, the review form, its live check, the sample and the
                     sample batch, adding one station (add_one) or several (add_many, which
                     queues them with queue_batch, #271)
    views.py, urls.py  /w/<id>/<station>/ (#256): a station's setup page (new_station: a new
                     file and the details, the New station page of #201), field
                     validation, the old /station/, /station/new, /station/sample (upload,
                     #271) and Load addresses' redirects, daily CSV,
                     delete; Quality: the checks, progress, table pages, continue; the
                     Inputs panel's sheets (edit_input: file, station, base period,
                     thresholds, index settings) and their runs' progress; the old
                     /station/<id>/ redirects; `filled` records a finished batch's run on
                     a station opened before its workspace's overview
    overview.py      the workspace overview's model (#234): the Stations table's rows
                     (`rows`) and the run status line (`status_line`)
    copy_station.py  Copy to workspace… (#241): the workspaces a station can go to
                     (`targets`), the form (`CopyForm`) and the copy (`copy_to`)
    views_copy.py    /w/<id>/<station>/copy (#241): the Copy to workspace page
    workspace_file.py  the workspace file (#240): climpact_workspace.zip written (`write`:
                     workspace.json, the station files, metadata.txt, climpact_run.json),
                     read and checked as untrusted (`read`, `NotAWorkspaceFile`) and
                     rebuilt through Add stations' routes (`open_into`)
    views_workspace_file.py  /w/<id>/workspace.zip (Save file) and /w/open/ (Open a
                     workspace file, #240)
    workspace_list.py  Workspaces (#242): each workspace's row (`entry`, `entries`):
                     its hint, station count, status summary, dates; `latest` for the
                     landing page's "Welcome back"
    workspace_files.py  the workspace's Files (#239): each station's results as Files
                     sees them (`entries`), the all-station trends and indices CSVs,
                     climpact_run.json (`provenance`) and its methods sentence, the zips,
                     made once per `fingerprint` under <MEDIA_ROOT>/stations/<workspace>/files/
                     (`build`), and the By station table (`table`)
    trend_grid.py    trends across stations (#238): the trend grid of the stations'
                     results (`grid`: columns, cells on the trend scale, every column's
                     interval plot, `interval_plot`) and its CSV (`grid_csv`)
    overlay.py       Overlay the series (#276): an index's series at every station on
                     shared axes (`overlay`, `for_index`), drawn on the server (`chart`)
                     and for charts.js (`payload`, kind `overlay`), its summary, table
                     and CSV (`index_csv`)
    views_files.py   /w/<id>/files/ (#239): the Files page, its three downloads and a
                     station's zip with its provenance file (`station_zip`)
    views_workspace.py  /w/<id>/ (#234): the workspace's address (`workspace_page`: one
                     station opens it, several the overview), the overview's polled
                     fragment (`workspace_progress`), Compare an index (`compare_page`,
                     /w/<id>/compare/, and the grid's CSV, `compare_csv`, #238), Overlay
                     the series (`overlay_page`, /w/<id>/compare/<code>/overlay, and its
                     CSV, `overlay_csv`, #276), Rename,
                     Workspace settings (a page and one page a setting) and Undo
    views_indices.py Indices: progress, the table and detail pane (with a recalculation's progress
                     above it), the settings sheet's htmx field checks, "Recalculate", the
                     old Calculate address, each index's page, anomalies JSON
    sector_file.py   the sector comparison (#90): checks a sector file (plain-language problems at file
                     lines, years in common with the station); SectorForm
    sector_plots.py  the sector comparison's results: a sector job's files read back; the bar chart and
                     scatter plots as inline SVG
    downloads.py     the Files page's model (#79, #176): the zip, report, plots PDF, summary
                     files, the quality check's files, the sector comparison's files, each
                     index's tables and PNGs and any other file of the run, with their sizes
    views_downloads.py  the Files page (#79, #176)
    views_sector.py  the sector comparison: the form, the sector job, its progress and results, the sample
    sample_data/     sydney_observatory_hill_1936-2015.txt.gz, R's sample (173 KB);
                     wheat_yield_nsw_1922-1999.csv, R's sample sector file (795 bytes)
    templates/stations/  add.html (Add stations and starting a workspace, #233), new.html
                     (a station's setup page, New station until #233) and _file_card.html (its file card
                     and days-with-data strip), qc.html (and its _qc_*.html parts),
                     _unit.html (a field group validated by htmx), _summary.html,
                     _problems.html, _retention.html; the Inputs panel (_inputs.html,
                     _input_sheets.html, _input_form.html, input_edit.html,
                     _settings_fields.html and _indices_unit.html: the Index settings
                     sheet, #199; _open_sheet.html), results_progress.html,
                     _results_progress.html, results.html, _indices.html and
                     _index_detail.html (Indices, #236), result.html and its
                     _index_title.html, _index_lead.html, _index_actions.html and
                     _index_chart.html (one index, #237),
                     downloads.html (Files, #79, #176),
                     sector.html, _sector_progress.html,
                     _sector_results.html (the sector comparison); workspace.html, _overview.html
                     (the run status line and Stations table), _space_bar.html and its
                     _space_*.html parts (the workspace's context bar; _space_actions.html
                     has Export ▾, #239), workspace_files.html (the workspace's Files),
                     _trends.html and workspace_compare.html (trends across stations,
                     #238),
                     workspace_settings.html, workspace_setting.html,
                     workspace_rename.html (#234); _station_links.html (the end of a
                     station's provenance line)
  batch/             batch processing of stations (label `batch`, see [Batch page](#batch-page))
    models.py        BatchRun: one batch's files, check result, run options and job; it
                     fills a workspace (#231, #255)
    check.py         the pre-flight check: metadata file, each station, zip unpacking
    fill.py          add_stations, fill_workspace, run_states, run_progress: every station of
                     a batch is the workspace's, with its run state (#255)
    forms.py         OptionsForm (Add stations' settings), MultipleFileField (gridded)
    retention.py     purge_stray_batch_folders, registered with the jobs app's purge
    views.py, urls.py  the sample batch's files, R's sample metadata file to download, and
                     the old addresses (#271): /batch/ and /batch/sample lead to /add/,
                     /w/<id>/batch/ to the files waiting on Add stations or the workspace,
                     `results` to the workspace's overview at /w/<id>/ (#234); the old
                     /batch/<id>/ redirects
    sample_data/     climpact.sample.batch.metadata.txt, R's sample metadata file
  gridded/           gridded runs (label `gridded`, see [Gridded pages](#gridded-pages))
    models.py        GriddedRun: one set of netCDF files, its name (#289), their
                     inspection, the variable names, the parameters, the thresholds
                     and indices jobs, and those of a new start waiting beside them
                     (#293, settle)
    runs.py          a run as a place of its own (#289): its default name, its row on
                     Gridded, its provenance line, its Files tab's groups and its record
                     (run.json, climpact.log)
    inspection.py    reads the files' metadata (variables, units, calendar, grid, dates),
                     guesses the variables, checks them as the core reader does, and
                     `preflight` (the core's `open_grid`) before a run
    forms.py         PathsForm, UploadForm (New gridded run), RenameForm, SetupForm
    listing.py       New gridded run's folder listing (#292): each netCDF file's daily
                     variables and dates from its header (cached by path, size and
                     modification time), and what the files chosen so far hold; the
                     set-up's Browse listings (#320, `picking`: a thresholds file, or
                     folders only)
    setup_page.py    the set-up page (#293): the Variables rows (units, how they are
                     read, a unit Climpact cannot read with a CDO command), the
                     Together line, the base period's timeline and coverage, the
                     indices by variable, the estimates, the summary panel, a file's
                     header as ncdump -h prints it
    maps.py          output files; a layer (one index variable of one file), its values
                     (read whole and kept, `variable_values`; a monthly file's month,
                     `month_values`), a cell's series; the
                     colour scale by the index's kind and its fixed breaks; the map's
                     frame (north up, west left, the cells' aspect, axes, coastline)
    map_page.py      the Map tab (#295): the rail's entries, the state from the query
                     string, the toolbar, the map, the legend and the cell pane
    map_views.py     the map's Base mean, Anomaly and Trend views and the grid mean
                     (#296): trends.nc read and kept, a monthly file's month computed
                     (#348, `month_trends`), each view's field, breaks and
                     scale, the diverging palettes, the dots on Trend
    stages.py        the Map tab while a run calculates (#294): each job's stages from
                     its stages.json, the stages table, the status line, what to change
                     when it fails, what is being calculated
    map_image.py     the map's PNG, one pixel per cell (zlib); the report figure (matplotlib)
    outline.py       the coastline and places for a box of the grid, from data/outline.npz
    data/outline.npz Natural Earth 1:50m coastline and populated places (public domain,
                     scripts/build-map-outline.py)
    retention.py     purge_expired_gridded and kept_jobs (#301), registered with the
                     jobs app's purge and keepers
    views.py, urls.py  /gridded/: the runs (start), new/ (folder listing, paths, patterns),
                     upload, sample; a run's Map (<run>/), files/, setup/ (with Browse,
                     `setup_browse`) and its checks (htmx), a file's header (setup/header/<n>/), rename/, progress (the
                     stages, polled), cancel, map.png, map.f32 (the values), map and
                     series CSV,
                     zips (every output, a group), a file (session or key), links.txt,
                     run.json, climpact.log, delete (Forget); results redirects to Map
    sample_data/     climpact.sampledata.gridded.3x4.1991-2010.nc (525 KB), the
                     reference grid `grid_sample`: a 3 x 4 cut of R's sample grid
    templates/gridded/  start.html, new.html, setup.html (with _summary.html, the summary
                     panel, and the parts htmx swaps out of band), header.html, run.html,
                     files.html, _listing.html (New run's chooser and set-up's Browse),
                     _browse_field.html, _chosen.html, _stages.html and
                     _stages_table.html (the stages, #294), _run_finished.html and
                     _run_bar_update.html (the poll's answer once the run finishes),
                     _run_result.html, _map.html, _cell_pane.html, _run_bar.html,
                     _retention.html
  help/              in-app help (label `help`, see [Help](#help))
    topics.py        the contextual help topics, keyed by id; get_topic, index_topic_for_output
    sections.py      section help (#177): the topics and notes behind each section's Help
                     button (#197; an ⓘ before)
    indices.py       the index catalogue from the core's climate.indices.csv (display names,
                     short names, groups, parameters); writes index_messages.py
    index_messages.py  generated: the index names and definitions for makemessages
    guides.py        guide pages from Markdown (language folders, English fallback), the
                     generated index catalogue, link resolution, search
    contents.py      the help frame's contents (#325: the groups, the current page, the
                     Reference pages of #319 by URL name) and the help home's lists
    tour.py          the landing page's tour steps
    views.py, urls.py  /help/: index, search, topics (A to Z), /help/sections/<id>/,
                     /help/<guide>/
    templatetags/help.py  `{% help_contents as contents %}`, `{% section_help "id" %}`,
                     `{% help_topic "id" %}`
    guides/en/*.md   the guides, in English (accessibility.md: the accessibility
                     statement, #83, linked from every page's footer)
    templates/help/  frame.html (the help frame every help page extends, #325),
                     _contents.html, _toc.html, _action.html, index.html, guide.html,
                     topics.html, search.html, section.html,
                     _results.html, _search_form.html, _section_help.html,
                     _section_body.html, _topic.html, _tour.html, sections/ (help that
                     needs markup: the station file format)
  charts/            chart data for the interactive charts (label `charts`, see [Charts](#charts))
    data.py          the payloads: daily series with QC flags, index series with trend, summaries
    views.py, urls.py  /charts/: a station analysis's daily series, a finished job's index
                     series and their list, the pattern library's examples; ETag caching
    templatetags/charts.py  `{% chart_scripts %}`: the chart assets and text for a page
    sample_outputs/sydney/  index tables (TXx, SU, TR, TN10p, PRCPTOT annual; TXx and SPI
                     monthly) and the trend rows of the Sydney sample's run, for the chart
                     demos and the landing page's preview (#242)
                     (pattern library examples and tests)
  locale/en/LC_MESSAGES/django.po   the message catalogue (English, from makemessages)
packages/climpact-web/docs/accessibility-audit.md  the accessibility audit (#83): what was
                     checked, what was fixed, the screen reader checklist done by hand
packages/climpact-web/tests/
  web_test_settings.py  test settings: local mode, data folder in a temporary folder
  turnstile_test_settings.py  the browser test's app with Turnstile on (test keys, #137)
  browser.py         headless Chrome over the DevTools protocol (#83)
  made.py            stations and batches made at model level (#271): a station on its
                     setup page with its details not done, a batch checked against its
                     metadata file (missing and unreadable stations too) and queued
  assets/axe-core/   axe-core 4.14.0, vendored for the accessibility tests (README: source,
                     SHA-256, MPL-2.0 licence)
  conftest.py        prints the page sizes measured by test_page_budget.py (from the
                     test reports); thread limits and xdist groups, as the core's
  test_*.py          settings, views and security, i18n, the message catalogue is current
                     (test_catalogue.py, #205), static files, the command, jobs
                     (test_jobs.py), the worker as a real process (test_worker_process.py),
                     several workers on Postgres (test_queue_postgres.py, #119),
                     a station's setup page (test_stations.py, #201), Add stations
                     (test_add_stations.py, #233), Quality (test_qc_review.py; out of date,
                     test_stale_quality.py, #308), the
                     workspace, staleness and the Inputs panel's edits (test_workspace.py,
                     #179, #198), the workspace overview (test_workspace_overview.py,
                     #234), the workspace's Files (test_workspace_files.py, #239), the landing page,
                     Get started and Workspaces (test_workspaces_list.py, #242), trends across stations
                     (test_trend_grid.py, #238; Overlay the series, test_overlay.py, #276), the batch page (test_batch.py), the
                     gridded pages (test_gridded_web.py), the help (test_help.py),
                     the size budget (test_page_budget.py), the charts (test_charts.py),
                     the index settings and the Indices (test_indices_results.py), the sector comparison (test_sector_web.py),
                     the Files page and the PDF report jobs (test_downloads.py),
                     accessibility in a browser (test_accessibility.py, #83), the
                     Content Security Policy (test_csp.py, #137)
```

Apps, one per area, each added by the ticket that needs it: `jobs` (the job model,
worker and progress pages, #73), `stations` (a station's pages, #76-#78, the downloads
page, #79, and the sector comparison, #90), `batch` (#80), `gridded` (#85), `help` (#81) and `charts` (#75). `core` keeps what every page shares.

Templates and static files live inside the package, so the wheel carries them (hatchling
includes every file under `src/climpact_web`; checked by building the wheel). The
stylesheet is built with the standalone Tailwind CLI (#118; Tailwind was first dropped in
#69 because nothing could be installed, and installed with the user on 2026-11-14), but
the built file is committed, so installing or running the app needs no build step, no
Node and no Tailwind (see [Stylesheet and Tailwind](#stylesheet-and-tailwind)).

### Modes

`CLIMPACT_WEB_MODE` selects one of two modes; the same settings module serves both.

| | `local` (default) | `hosted` |
| --- | --- | --- |
| Started by | `climpact-web` (waitress on 127.0.0.1) | the image's `web` role: `climpact-web --host 0.0.0.0` (waitress), behind a TLS-terminating proxy (see [Deployment](#deployment)) |
| Database | SQLite, `<data dir>/db.sqlite3` (WAL journal, 20 s busy timeout, `IMMEDIATE` transactions, as the server and the worker both write), migrated on every start | `DATABASE_URL` (Postgres; the `postgres` extra installs psycopg); migrations run by the deployment |
| Secret key | `CLIMPACT_WEB_SECRET_KEY`, else `<data dir>/secret_key` (written on first start, mode 0600) | `CLIMPACT_WEB_SECRET_KEY`, required |
| Allowed hosts | localhost, 127.0.0.1, [::1] (`*` when started with a non-loopback `--host`) | `CLIMPACT_WEB_ALLOWED_HOSTS`, required |
| Static files | `climpact-web` runs `collectstatic` into `<data dir>/static` on every start (hashed, compressed copies, `LocalStaticFilesStorage`); WhiteNoise serves them, and its finders serve any file not collected straight from the package. With `DEBUG`, nothing is collected | `collectstatic` into `CLIMPACT_WEB_STATIC_ROOT` (required) at deployment, `StaticFilesStorage`; see [Size budget](#size-budget) |
| HTTPS | none (localhost) | secure session and CSRF cookies, redirect to HTTPS, `X-Forwarded-Proto` from the proxy trusted; `/healthz` exempt from the redirect |
| Uploads and results | `<data dir>/media`; job folders under `media/runs` | `CLIMPACT_WEB_MEDIA_ROOT`, a filesystem every worker and web process shares (in the image, a Docker volume mounted by both containers) |
| Background worker | started by `climpact-web` as a child process, restarted if it crashes | one or more `climpact-web manage runworker` processes (the image's `worker` role) |

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
| `CLIMPACT_WEB_STATIC_ROOT` | `<data dir>/static` (local) | `collectstatic` target; required in hosted mode |
| `CLIMPACT_WEB_MEDIA_ROOT` | `<data dir>/media` | uploads and job folders (`RUNS_DIR` is `media/runs`) |
| `CLIMPACT_WEB_RETENTION_DAYS` | `7` | days a finished job and its files are kept (`JOB_RETENTION_DAYS`) |
| `CLIMPACT_WEB_WORKSPACE_EXPIRY` | on when hosted, off locally | whether workspaces and gridded runs expire `JOB_RETENTION_DAYS` after their last change (`WORKSPACE_EXPIRY`, #231, #301); off, a workspace or gridded run and the jobs it shows stay until deleted |
| `CLIMPACT_WEB_JOB_HEARTBEAT_SECONDS` | `10` | seconds between worker heartbeats |
| `CLIMPACT_WEB_JOB_STALE_SECONDS` | `60` | seconds without a heartbeat before a running job counts as dead |
| `CLIMPACT_WEB_JOB_POLL_SECONDS` | `1` | seconds between a worker's checks for queued jobs |
| `CLIMPACT_WEB_JOB_STORAGE` | `climpact_web.jobs.storage.LocalJobStorage` | class that manages job folders |
| `CLIMPACT_WEB_MAX_UPLOAD_MB` | `50` | largest request body, uploads included |
| `CLIMPACT_WEB_GRIDDED_HOSTED` | `false` | hosted mode: offer gridded runs (`GRIDDED_ENABLED`; always on in local mode) |
| `CLIMPACT_WEB_GRIDDED_MAX_UPLOAD_MB` | `200` | largest request body under `/gridded/` (netCDF uploads), when gridded runs are offered |
| `CLIMPACT_WEB_SSL_REDIRECT` | `true` | hosted mode: redirect HTTP to HTTPS |
| `CLIMPACT_WEB_HSTS_SECONDS` | `0` | hosted mode: `Strict-Transport-Security` max-age, sent with `includeSubDomains` when above 0; `deploy/.env.example` sets `31536000` (#124) |
| `CLIMPACT_WEB_CSP_REPORT_ONLY` | `false` | send the Content Security Policy as `Content-Security-Policy-Report-Only` (violations are reported in the browser console, nothing is blocked) instead of enforcing it; for a first deployment (#137) |
| `CLIMPACT_WEB_CF_WEB_ANALYTICS` | `true` | hosted mode: the Content Security Policy allows Cloudflare Web Analytics' beacon (`WEB_ANALYTICS`); ignored in local mode (#164) |
| `CLIMPACT_WEB_LOG_LEVEL` | `INFO` | level for the `climpact_web` and `climpact` loggers; other libraries log warnings and errors |
| `CLIMPACT_WEB_TURNSTILE_SITE_KEY` | none | hosted mode: Cloudflare Turnstile's site key; Turnstile is on only when both keys are set, and one without the other is an error (#125) |
| `CLIMPACT_WEB_TURNSTILE_SECRET_KEY` | none | hosted mode: Turnstile's secret key, for the siteverify check |
| `CLIMPACT_WEB_MAX_ACTIVE_JOBS_PER_IP` | `2` | hosted mode: jobs one client may have waiting or running at once; `0` is no limit |
| `CLIMPACT_WEB_MAX_DAILY_JOBS_PER_IP` | `50` | hosted mode: jobs (and retries) one client may start in 24 hours, the jobs of one change counting once (#254); `0` is no limit |
| `CLIMPACT_WEB_MAX_QUEUED_JOBS` | `20` | hosted mode: no new job while this many wait; `0` is no limit |
| `CLIMPACT_WEB_SPECULATIVE_MAX_QUEUED` | `3` | hosted mode: no speculative station run (#178) while this many jobs wait; `0` turns speculative runs off |
| `CLIMPACT_WEB_MIN_FREE_DISK_GB` | `2` | hosted mode: no upload and no new job while `MEDIA_ROOT`'s disk has less free space; `0` turns it off |
| `CLIMPACT_WEB_JOB_TIME_LIMIT_MINUTES` | `60` | hosted mode: wall-clock limit on one job; `0` is none (see [Background jobs](#background-jobs)) |
| `CLIMPACT_WEB_TRUSTED_PROXY` | none (`*` in the image) | the `climpact-web` server (waitress) trusts `X-Forwarded-Proto` and `X-Forwarded-For` from this address (`*`: any peer) and takes the request's scheme and client address from them; read by `cli.proxy_options`, not by the settings |

Both modes also send a strict Content Security Policy (see
[Content Security Policy](#content-security-policy)), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: same-origin`,
`Cross-Origin-Opener-Policy: same-origin`, HttpOnly SameSite=Lax session cookies and
Django's CSRF protection. `PrivateCacheMiddleware` (below WhiteNoise, so static files keep
their one-year cache) adds `Cache-Control: private` to every answer that sets no
`Cache-Control` of its own: Cloudflare caches answers by extension (`.csv`, `.png`, `.pdf`,
`.zip`) when the origin says nothing, whatever the cookies, and the job downloads belong
to one session (#124); htmx requests send the CSRF token from the `hx-headers` on
`<body>`. Server errors are logged to the console by `django.request`. pint's warnings
about xclim redefining its units are silenced (`pint.util` at ERROR).

See [Security of the hosted site](#security-of-the-hosted-site) for the limits.

#### Content Security Policy

`climpact_web.middleware.ContentSecurityPolicyMiddleware` (Django 6's
`django.middleware.csp` one, right after `SecurityMiddleware`) adds the policy from
`SECURE_CSP` to every answer, in both modes, so a violation shows in development as it
would on the hosted site (#137). `settings.py` builds it with
`content_security_policy(turnstile, analytics)`:

```
default-src 'self'; script-src 'self' 'nonce-<per page>'; style-src 'self' 'sha256-<500 page>';
img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-src 'none';
object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'
```

`frame-ancestors 'none'` does what `X-Frame-Options: DENY` does; the latter stays for old
browsers. `CLIMPACT_WEB_CSP_REPORT_ONLY=true` sends the same policy as
`Content-Security-Policy-Report-Only` instead (`SECURE_CSP_REPORT_ONLY`). There is no
reporting endpoint (`report-to`): violations appear only in the browser's console.

**No inline code.** Every page loads one same-origin stylesheet and same-origin scripts
only, so the policy needs no `'unsafe-inline'` or `'unsafe-eval'`, and no template uses
the nonce (the `csp` context processor is not used):

| What was inline | Now |
| --- | --- |
| the theme script in `<head>` | `js/theme.js`, loaded without `defer` after the stylesheet, so the stored theme still applies before the first paint |
| the chart frame's `<noscript><style>` hiding the skeleton | `@media (scripting: none) { [data-chart-src] .skeleton { display: none } }` in `charts.css` (browsers without the media feature, from before 2023, show the skeleton above the no-JS fallback) |
| `style="--swatch: var(--chart-…)"` on legend, summary, sector and pattern-library swatches | a class per `--chart-*` token, `swatch-chart-…` (`charts.css`), written with the `token_name` filter (`swatch-{{ token\|token_name }}`); `charts.js` still sets `--swatch` from script, which CSP allows (the CSSOM is not restricted) |
| `style="--chart-height: …"` and `--skeleton-height` | a class per height the templates use, `chart-height-14rem` etc. (`charts.css`) |
| the gridded map's `style="--gmap-width: …"` | the SVG's `viewBox` sets the map's aspect (#295); the tooltip is placed from script (`element.style`, the CSSOM) |
| the sparkline bars' `style="stroke-width: …"` | the SVG `stroke-width` attribute |
| the server-drawn SVG plots' `style="--plot-colour: …"` (`stations/qc_plots.py`) and `style="fill: …"` (`stations/sector_plots.py`) | the same `swatch-chart-…` classes; `.qc-plot` and `.sector-plot__bar` read `--swatch` |
| `hx-trigger="… visibilitychange[!document.hidden] …"` and `hx-vals='js:{hidden: document.hidden}'` on the progress polls (both eval'd by htmx) | `hx-trigger="… climpact:visible from:document"` and `data-poll-hidden`: `ui.js` fires `climpact:visible` when the tab is shown and adds `hidden` to the poll's parameters in `htmx:configRequest` |
| htmx's injected indicator `<style>` | `.htmx-indicator` rules in `feedback.css`; `<meta name="htmx-config">` in `base.html` turns off `includeIndicatorStyles`, `allowEval` and `allowScriptTags` (no fragment relies on a script in it) |

The one exception is the 500 page, which renders without the page shell or context
processors and keeps its small inline `<style>`; the policy allows it by its SHA-256
(`ERROR_PAGE_STYLE_HASH`), which `test_csp.py` recomputes from the template. uPlot styles
its elements through the CSSOM, which CSP does not restrict, and `charts.js` fetches chart
data from the same origin.

**Turnstile.** With Turnstile on (hosted mode and both keys set, as in
`core/limits.py`), `content_security_policy(turnstile=True)` adds
`https://challenges.cloudflare.com` to `script-src` (its `api.js`) and makes it the only
`frame-src` (the challenge frame); nothing else is needed, since the frame makes its own
requests. Without the keys the policy stays as above.

**Scripts Cloudflare adds at the edge (#164).** Cloudflare inserts two scripts into every
page it proxies, which the app's templates never contain:

- *JavaScript detections* (bot management; cannot be turned off on the free plan): an
  inline `<script>` before `</body>` that adds a hidden 1×1 `about:blank` iframe, writes
  an inline script into it (`window.__CF$cv$params=…`), and that script loads
  `/cdn-cgi/challenge-platform/scripts/jsd/main.js` from this origin.
  [Cloudflare's docs](https://developers.cloudflare.com/cloudflare-challenges/challenge-types/javascript-detections/)
  say that when the `Content-Security-Policy` *header* has a nonce in `script-src`, it
  adds that nonce to the scripts it injects (nonces in a `<meta>` policy are not read),
  and that `/cdn-cgi/challenge-platform/` must be allowed, which `'self'` does. So
  `script-src` always has `CSP.NONCE`. Django makes the nonce lazily and leaves it out of
  the header unless something read it, so the middleware subclass reads it for every
  `text/html` answer; other answers (static files, downloads, JSON) get no nonce. The
  nonce is fresh per response and no HTML is cached anywhere (`Cache-Control: private`
  from `PrivateCacheMiddleware`, or `never_cache`; Cloudflare reports them `DYNAMIC`), so
  no page is served with an old one. The policy has no `'strict-dynamic'`, so the nonce
  allows only scripts that carry it. Local mode sends the same nonce: one policy in both
  modes, so development sees what production enforces, and it grants nothing there.
  The `about:blank` iframe inherits the page's policy, nonce included. Its inner script
  is made with `createElement` and `innerHTML`, so it runs only if Cloudflare's
  nonce-aware snippet also sets that element's nonce; Cloudflare's docs don't mention the
  iframe, and the snippet served without a nonce (checked on climpact.app, 2026-11-16)
  shows no `nonce` handling. The owner's check after deploying (report-only on) settles
  it: if one violation remains for that inner script, it costs only Cloudflare's bot
  signals (`main.js` doesn't load), never the site, and is a case for Cloudflare.
- *Web Analytics* (the zone's automatic setup): `<script type="module"
  src="https://static.cloudflareinsights.com/beacon.min.js/v…" integrity=…>`. With the
  `version` Cloudflare puts in its `data-cf-beacon`, the beacon reports to `/cdn-cgi/rum`
  on this origin (`connect-src 'self'`); without one it reports to
  `https://cloudflareinsights.com/cdn-cgi/rum`. In hosted mode with
  `CLIMPACT_WEB_CF_WEB_ANALYTICS` on (the default), `content_security_policy(...,
  analytics=True)` adds `https://static.cloudflareinsights.com` to `script-src` and
  `https://cloudflareinsights.com` to `connect-src` (host sources: Cloudflare's suggested
  `…/beacon.min.js` path would not match the versioned path the beacon is served from).
  Never in local mode, where no Cloudflare edge adds it.

One console message is expected and is not the app's: `Fetch API cannot load data:,`
from inside Turnstile's own frame (its URL ends `flexible?lang=en`). The frame is
Cloudflare's document with its own policy; nothing in this site's policy affects it.

**Extending it.** Add a source to `content_security_policy` only for something that
cannot be served from this site, and say why in a comment. Prefer moving code to a static
file and a class over a nonce; if a template ever needs the nonce, add
`django.template.context_processors.csp` and write `nonce="{{ csp_nonce }}"`. Never add
`'unsafe-inline'` or `'unsafe-eval'`.

**Tests.** `test_csp.py`: the header on pages and the 404 page (strict directives, no
`'unsafe-*'`, `X-Frame-Options` kept), a nonce on every HTML page and the report-only
header, different on each request and absent from non-HTML answers, the Turnstile and Web
Analytics policies, the settings in both modes and with the report-only switch, Turnstile
keys and `CLIMPACT_WEB_CF_WEB_ANALYTICS`, the 500 page's hash, no inline
script, inline style, style or event handler attribute or htmx eval in any template, no
style attribute in markup built in Python or the scripts, and a class for every chart token
and chart height. In the browser (`test_accessibility.py`,
CI's `web-accessibility` job), `browser.py` records every `securitypolicyviolation`
event (through a DevTools binding, on every document) and every console message about the
policy for the whole module, so the run through the station steps, the progress polls,
the results filters, the charts, the sector comparison, the batch, the grid, help, the
jobs and the error pages must leave none (`test_no_content_security_policy_violations`).
`test_turnstile_widget_within_the_policy` starts a second app with
`turnstile_test_settings.py` (Turnstile on with Cloudflare's published test keys, which
always pass on any host, and the Turnstile policy) and waits for the widget's token on
Add stations with no violation; `test_turnstile_holds_a_form_until_its_token`
presses "Check and calculate" on a station's setup page as soon as the page is parsed,
before the token, and expects the quality checks, not "Not accepted" (#163). The setup page
is reached as a user reaches it since #271: Add stations' sample, then a new file from the
File sheet that the base period does not fit (`setup_page`), so the sheet needs a token
too. Both skip when Cloudflare cannot be reached.

**Upload limit.** Django limits only in-memory form data, not file uploads, so
`UploadSizeLimitMiddleware` answers 413 (with `413.html`) when `Content-Length` exceeds
`MAX_UPLOAD_MB`, before the body is read (`GRIDDED_MAX_UPLOAD_MB`, default 200 MB, for
requests under `/gridded/` when gridded runs are offered); waitress gets the larger of the
two (`max_request_body_size`) for bodies without a length. The default, 50 MB, covers any
station file; gridded runs read netCDF files in place from paths in local mode, so only
uploads need the larger limit (#85). Uploads over
2.5 MB go to a temporary file, not memory (Django's default).

### Running the web app

```sh
uv run climpact-web                      # local mode: migrate, serve on 127.0.0.1:8000, open the browser
uv run climpact-web --no-browser --port 9000 --data-dir /tmp/cw
uv run climpact-web manage <command>     # any Django management command with these settings
```

Changing a template's classes or the stylesheet source needs the stylesheet rebuilt (see
[Stylesheet and Tailwind](#stylesheet-and-tailwind)):

```sh
scripts/fetch-tailwind.sh                # once: the pinned Tailwind CLI into bin/ (checksum checked)
scripts/build-css.sh --watch             # rebuild css/climpact.css on every change
CLIMPACT_WEB_DEBUG=true uv run climpact-web   # in another terminal: edits show on reload
scripts/build-css.sh                     # one build, before committing (CI checks it is current)
```

A pull request that changes how the app looks carries one or two screenshots of the new
design in its body. `scripts/pr-screenshots.sh <pr-number> <image>...` pushes them to the
orphan branch `pr-screenshots`, under `pr-<number>/`, and prints the Markdown image links.
GitHub has no API for attaching images, and the orphan branch keeps them out of `main`'s
history.

Options: `--host` (default 127.0.0.1; 0.0.0.0 serves the network, with a warning),
`--port` (default 8000, or a free port if 8000 is taken), `--no-browser`, `--data-dir`,
`--threads` (default 4), `--no-worker` (do not start the background worker). Ctrl+C or
SIGTERM stops the server and the worker cleanly (exit status 0). The command prints the
address and the data folder.

A hosted deployment runs `climpact-web manage migrate` and
`climpact-web manage collectstatic --no-input` with the hosted variables set, then serves
`climpact_web.wsgi:application`; the production image does all three (see
[Deployment](#deployment)). Load balancers and the image's `HEALTHCHECK` check **`/healthz`**: 200 and `{"status": "ok", "database": "ok", "version":
..., "core_version": ...}` when the database answers, 503 otherwise; never cached.

### Deployment

The hosted app runs from one container image (#120), built by the root `Dockerfile` for
`linux/amd64` (DigitalOcean Droplets are amd64):

```sh
docker buildx build --platform linux/amd64 -t climpact-web --load .
```

**Build.** Two stages on `python:3.12-slim` (trixie), pinned by tag and digest, with uv
copied from `ghcr.io/astral-sh/uv` (pinned the same way, the version CI uses). The builder
runs `uv sync --frozen --package climpact-web --extra postgres --no-default-groups
--no-editable` into `/opt/venv`, first with `--no-install-workspace` from the pyproject
files and `uv.lock` alone (a layer reused until the lock changes), then again with the two
packages' sources, which installs them as ordinary wheels; no dev group and no tests go in.
Byte code is compiled at install (`UV_COMPILE_BYTECODE`), as the image runs with
`PYTHONDONTWRITEBYTECODE` and a read-only root. The third-party packages' own `tests`
folders (about 150 MB, never imported) are deleted. The builder then runs `collectstatic`
into `/opt/climpact/static` (dummy hosted settings for that one step; the image is
self-contained) and builds matplotlib's font cache into `/opt/climpact/mplconfig`. The
runtime stage copies only `/opt/venv` and `/opt/climpact`: the wheels bundle their native
libraries (matplotlib's FreeType, netCDF4/h5py's HDF5, psycopg's libpq, OpenBLAS), so no
system packages are installed. `.dockerignore` admits only the pyproject files, `uv.lock`,
`docker/` and the packages' `src` folders and READMEs.

**Roles.** `docker/entrypoint.sh` takes the role as its first argument and `exec`s it, so
the Python process is PID 1 and gets `docker stop`'s SIGTERM (the web server and the worker
both stop cleanly on it, exit status 0):

| Role | Runs |
| --- | --- |
| `web` (default) | `climpact-web --host 0.0.0.0 --port 8000 --threads 4 --no-browser`: waitress in hosted mode (no migrate, collectstatic or worker); `CLIMPACT_WEB_PORT` and `CLIMPACT_WEB_THREADS` change the port and threads |
| `worker [args]` | `climpact-web manage runworker [args]` |
| `migrate` | `climpact-web manage migrate --no-input` |
| `purge` | `climpact-web manage purgejobs` (for a daily run) |
| `manage <command> ...` | any management command |
| anything else | run as a command (e.g. `sh`) |

waitress, not gunicorn: it is already a dependency (the local server), it is one process
with threads, which suits a small Droplet, and `climpact-web` already passes it the upload
limit. Behind Cloudflare's tunnel the TLS is terminated by `cloudflared`, which sends
`X-Forwarded-Proto: https`; waitress drops forwarded headers from peers it does not trust,
so without `CLIMPACT_WEB_TRUSTED_PROXY` hosted mode would redirect every request to HTTPS
again. The image sets it to `*` because only the tunnel can reach port 8000 (it is never
published on the host); set it to the proxy's address where other hosts can reach the
container.

**Environment.** The image sets `CLIMPACT_WEB_MODE=hosted`,
`CLIMPACT_WEB_STATIC_ROOT=/opt/climpact/static`, `CLIMPACT_WEB_DATA_DIR=/var/lib/climpact`,
`CLIMPACT_WEB_MEDIA_ROOT=/var/lib/climpact/media`, `CLIMPACT_WEB_TRUSTED_PROXY=*`,
`MPLBACKEND=Agg`, `MPLCONFIGDIR=/tmp/matplotlib`, `HOME=/tmp`,
`XDG_CACHE_HOME=/tmp/.cache`, `PYTHONDONTWRITEBYTECODE=1` and `PYTHONUNBUFFERED=1`. The
deployment must set `CLIMPACT_WEB_SECRET_KEY`, `CLIMPACT_WEB_ALLOWED_HOSTS` and
`DATABASE_URL`, and in practice `CLIMPACT_WEB_CSRF_TRUSTED_ORIGINS` (the origin behind the
proxy, `https://climpact.app`) and `CLIMPACT_WEB_HSTS_SECONDS`; gridded runs stay off
(`CLIMPACT_WEB_GRIDDED_HOSTED` unset). Every variable is in [Settings](#settings).

**Filesystem.** The processes run as `climpact` (uid and gid 10001), and the image works
with a read-only root filesystem (`--read-only`). Two paths must be writable: a volume at
`/var/lib/climpact/media` shared by the web and worker containers (a new named volume
takes the folder's `climpact` ownership from the image), and a tmpfs at `/tmp`, for
uploads over 2.5 MB and matplotlib's cache: the entrypoint copies the font cache built into
the image to `MPLCONFIGDIR` when that folder does not exist, because matplotlib needs it
writable and would otherwise rebuild it on every start.

**Health check.** The image's `HEALTHCHECK` runs `docker/healthcheck.py` every 30 s: for
the web role it fetches `/healthz` on 127.0.0.1 with the first name in
`CLIMPACT_WEB_ALLOWED_HOSTS` as the `Host` header (Django refuses other hosts); the worker
and one-off roles (PID 1 runs `manage`) always count as healthy.

**Size and memory** (measured 2026-11-15, image of #120, on an arm64 Mac with Docker
Desktop 29). The amd64 image is 312 MB compressed (`docker save | gzip`; 297 MiB), under
the free tier of most registries (it is published on ghcr.io as a public package, whose
storage and pulls are free). The largest parts are pyarrow and llvmlite
(about 170 MB each uncompressed, from xclim's dependencies), scipy and pandas. Memory of the
web and worker processes (`VmRSS`/`VmHWM` of PID 1, and the container's peak `docker
stats` usage) for the Sydney sample (80 years) driven through the web pages: quality
checks, then the station run with plots, the PDF report and the zip, then the results,
downloads and sector pages and the downloads; Postgres 16 peaked at 59 MiB:

| | idle RSS | peak RSS | peak container |
| --- | --- | --- | --- |
| web, amd64 under Rosetta | 510 MiB | 563 MiB | 467 MiB |
| worker, amd64 under Rosetta | 504 MiB | 671 MiB | 524 MiB |
| web, arm64 native | 363 MiB | 407 MiB | 254 MiB |
| worker, arm64 native | 364 MiB | 516 MiB | 423 MiB |

The amd64 image runs under Rosetta on the Mac, whose translations count in the process's
memory (`/run/rosetta` is mapped into it); the same Dockerfile built for arm64 and run
natively shows the overhead, so a Droplet's amd64 numbers should be close to the arm64
rows. The run took 26 s under Rosetta and 15 s natively. The web process idles as high as
the worker because loading the URLconf imports the core (xclim, pandas, matplotlib,
numba). With Postgres, `cloudflared` and the OS, the stack peaks around 1.2–1.3 GB (about
1.5 GB with the Rosetta figures), so the 2 GB Droplet chosen in #12, with swap, is
comfortable for one worker, and 1 GB is not.

#### Compose stack

`deploy/compose.yaml` (#121) runs the whole hosted app on the Droplet with Docker Compose
(project name `climpact`); `deploy/.env.example` lists its settings.

```sh
cd deploy && cp .env.example .env && chmod 600 .env   # fill in the image and the secrets
docker compose --profile tunnel up -d --wait          # on the Droplet
docker compose up -d --wait                           # without the tunnel, e.g. locally
```

| Service | Runs | Memory limit |
| --- | --- | --- |
| `db` | `postgres:16-alpine`, data in the `pgdata` volume, health check `pg_isready` | 192 MB |
| `migrate` | the image's `migrate` role once, after `db` is healthy; exits 0 | 512 MB |
| `web` | the `web` role; the image's `/healthz` health check | 768 MB |
| `worker` | the `worker` role (one `runworker`); 120 s to stop, so the running job is queued again (see [Deploy on release](#deploy-on-release)) | 1 GB |
| `purge` | a shell loop: the `purge` role (`purgejobs`) at start and then every 24 h | 512 MB |
| `deploy-hook` | `deploy/deploy-hook.py` (bind-mounted, read-only) on the app Dockerfile's `python:3.12-slim` base image, as uid 10001; drops deploy requests into `./hook` (#126, [Deploy on release](#deploy-on-release)) | 64 MB |
| `cloudflared` | `cloudflare/cloudflared` `tunnel --no-autoupdate run`, only with the `tunnel` profile; starts once `web` is healthy | 128 MB |

`web` and `worker` start only after `migrate` has succeeded
(`service_completed_successfully`). Every long-running service has
`restart: unless-stopped` and `json-file` logs rotated at 10 MB × 3. The limits follow the
measurements above (the worker peaked at 423 MiB natively, 524 MiB under Rosetta; web at
254/467 MiB; Postgres at 59 MiB) with room for larger stations and for `/tmp` uploads,
which count against the container's memory. They add up to more than 2 GB, but they are
caps, not reservations: they stop one runaway job from taking Postgres and the web server
with it, and the Droplet's swap covers short peaks. Measured with the stack idle after a
Sydney run (arm64): web 283 MiB, worker 375 MiB, Postgres 41 MiB, `purge` 7 MiB.

**Images.** Postgres, cloudflared and the deploy hook's Python are pinned by tag and digest
in `compose.yaml` (update both together; the hook's is the `Dockerfile`'s `PYTHON_IMAGE`,
and a test checks they match, so its layers are already on the Droplet). The app image
comes from `CLIMPACT_IMAGE` in `.env`: `ghcr.io/geoffwalmsley/climpact-web` with a
release's version tag, pinned by `update.sh` (see [Deploy on release](#deploy-on-release)
and [Image in CI and on ghcr.io](#image-in-ci-and-on-ghcrio)). The package
is public, so the Droplet pulls it without credentials. Compose never builds it.

**Networks and ports.** No service publishes a port on the host. The app containers and
`db` share `backend`, an `internal` network with no route out. Two services are also on
`egress`: `cloudflared`, to dial out to Cloudflare, and `web`, to check Turnstile tokens
with `challenges.cloudflare.com` (#125). The worker, `migrate`, `purge`, `deploy-hook`
and `db` have no route out. The tunnel's public hostname (`climpact.app`) is
routed to `http://web:8000` in the tunnel's configuration at Cloudflare (#123), and its
path `_deploy` to `http://deploy-hook:9000` (#126), so the Droplet needs no inbound
traffic at all.

**Hardening.** The app containers and `db` run with a read-only root filesystem; the app
gets a 256 MB tmpfs at `/tmp` and the `media` volume (job folders, shared by `web`,
`worker` and `purge`, so `LocalJobStorage` works unchanged), `db` gets tmpfs at
`/var/run/postgresql` and `/tmp`. The app containers and `cloudflared` drop all
capabilities and set `no-new-privileges`.

**Environment.** Compose reads `deploy/.env` (mode 0600, only on the Droplet, never
committed; `.gitignore` lists it) and passes each service only what it needs: the app
gets `CLIMPACT_WEB_SECRET_KEY`, `CLIMPACT_WEB_ALLOWED_HOSTS` (default `climpact.app`),
`CLIMPACT_WEB_CSRF_TRUSTED_ORIGINS` (default `https://climpact.app`),
`CLIMPACT_WEB_HSTS_SECONDS` (default `31536000`), `CLIMPACT_WEB_MAX_UPLOAD_MB`,
`CLIMPACT_WEB_RETENTION_DAYS`, `CLIMPACT_WEB_LOG_LEVEL` and `DATABASE_URL`; `db` gets `POSTGRES_PASSWORD`; `cloudflared`
gets `TUNNEL_TOKEN`; `deploy-hook` gets `DEPLOY_WEBHOOK_SECRET` (#126). `DATABASE_URL` defaults to
`postgres://climpact:${POSTGRES_PASSWORD}@db:5432/climpact`, so the password is set once
and must be URL-safe (`openssl rand -hex 32`). `CLIMPACT_IMAGE`, the secret key and the
password are required (Compose stops with a message); `TUNNEL_TOKEN` is not, because
Compose reads the whole file even when the `tunnel` profile is off.
`CLIMPACT_WEB_GRIDDED_HOSTED` is not passed, so gridded runs stay off (#12).

**Purge.** The worker already purges at start and every hour; the `purge` service keeps a
daily `purgejobs` (expired jobs, and jobs whose worker died) running when no worker is.
A shell loop in a container was simpler than a host systemd timer: nothing to install on
the Droplet, and it starts and stops with the stack. Its Python process exists only while
purging. The image's health check would look for the web server, so the service's health
check is `true`, which lets `up --wait` finish.

**Behind the tunnel.** `cloudflared` sends `X-Forwarded-Proto: https`, which waitress
trusts (`CLIMPACT_WEB_TRUSTED_PROXY=*` in the image), so hosted mode's HTTPS redirect,
secure session and CSRF cookies and CSRF origin checks work; plain HTTP gets a 301 to
`https://climpact.app/`. For the client address, waitress takes the last entry of
`X-Forwarded-For` (`trusted_proxy_count` 1). Cloudflare's edge appends the visitor's
address there, the same address as in `CF-Connecting-IP`, so a value the visitor sends in
the header is ignored: with `X-Forwarded-For: 203.0.113.9, 198.51.100.7`, `REMOTE_ADDR`
is `198.51.100.7`. Nothing in the app reads the client address yet (#125 will). Check on
the real tunnel (#123) that `cloudflared` adds no entry of its own.

**Tested locally** (2026-11-15, arm64 build of the image, Docker Desktop 29 with Compose
2.40, the tunnel profile off, a scratch override publishing `web` on loopback): the Sydney
sample through the web pages (QC, then the station run with plots, PDF report and zip in
15 s, then the results, downloads and sector pages and the downloads); `docker compose
restart` (migrate runs again with nothing to apply, every service healthy, results kept);
`docker compose kill worker` during a station run, then `up -d worker`: the new worker
marked the job failed 66 s after its last heartbeat (`JOB_STALE_SECONDS` 60), with the
retry offered. Without the override `docker compose ps` lists no published ports and the
web container cannot reach the internet. With a dummy token `cloudflared` starts
(read-only) and refuses the token.

#### Hosting: Droplet and tunnel

**Decision (user, 2026-11-14): DigitalOcean, not AWS** (#12). The original specification
asked for AWS. The user changed it to DigitalOcean, deployed from GitHub, with Cloudflare
in front to block abuse and spam. Very few people will use the app, so the cheapest setup
that works was chosen: one DigitalOcean Droplet (Basic Regular, 1 vCPU / 2 GB / 50 GB, $12/mo) running
the [Compose stack](#compose-stack), with Cloudflare's free plan in front (WAF, rate
limiting, bot protection; see [Cloudflare edge](#cloudflare-edge)) and a Cloudflare Tunnel as the only way in. The expected
cost is about $12/mo plus the domain (`climpact.app`, about $10/yr); no paid backups (see
[Operations](#operations-alerts-backups-credentials)). Rejected: DigitalOcean App Platform (about $30+/mo for two 1 GB
containers, a dev database and Spaces, and no shared disk, so job files would need an S3
storage class); a managed database ($15/mo); Redis (#119, the database queue stays);
Terraform/OpenTofu (not worth it for one Droplet and one tunnel;
revisit if WMO wants infrastructure as code). GitHub Releases drive deployment (#122,
#126); merges to `main` deploy nothing.

**Provisioning (#123).** `deploy/cloud-init.yaml` is the Droplet's user data (Ubuntu 24.04
LTS) and `deploy/README.md` is the runbook, written to be repeated by hand, for example in
WMO's accounts. Nothing account-side is automated. DigitalOcean accepts user data only when
a Droplet is created: a rebuild keeps the original user data, so a Droplet made without it
is destroyed and created again. The user data holds no secrets, because it can be read from
the metadata service and is stored by DigitalOcean. cloud-init:

| Part | Does |
| --- | --- |
| `deploy` user | sudo without password (it has no password), `docker` group; gets the SSH keys chosen at creation, copied from root by `climpact-bootstrap` (`disable_root: false`, so they are copied without cloud-init's prefix) |
| SSH | `sshd_config.d/10-climpact.conf`: no root login, keys only, `AllowUsers deploy`; read before cloud-init's `50-cloud-init.conf`, and sshd keeps the first value |
| Docker | Docker's apt repository; `climpact-bootstrap` downloads the signing key and stops unless the file holds exactly one primary key with fingerprint `9DC8 5822 9FC7 DD38 854A E2D8 8D81 803C 0EBF CD88`; then `docker-ce`, `containerd.io`, `docker-compose-plugin`. `daemon.json`: `live-restore`, `json-file` logs rotated at 10 MB × 3 |
| Swap | 2 GB `/swapfile`, `vm.swappiness = 10` |
| Updates | `unattended-upgrades` daily for Ubuntu's security pocket and Docker's repository (`origin=Docker,label=Docker CE`), reboot at 03:30 UTC when needed; `live-restore` keeps the containers up while Docker upgrades |
| `/opt/climpact` | owned by `deploy`, 0750; `update.sh` fetched from `main` at first boot, which then fetches `compose.yaml`, `.env.example` and `deploy-hook.py` from `main` (`update.sh --fetch main`) |
| `update.sh --install-hook` | the deploy hook's drop folder `/opt/climpact/hook` (uid 10001, group `deploy`, 2770) and the systemd units `climpact-deploy.path` and `climpact-deploy.service` (#126; see [Deploy on release](#deploy-on-release)) |
| `update.sh X.Y.Z` | deploys release `vX.Y.Z`: its Compose files and image, migrations, health check, rollback (#126). It replaced #123's `climpact-use vX.Y.Z`, which only fetched the files and pinned the image |
| `climpact-init-env` | makes `.env` (0600, `deploy`) from `.env.example` and fills only empty values: a new secret key (`secrets.token_urlsafe(50)`), Postgres password (`openssl rand -hex 32`), `COMPOSE_PROFILES=tunnel` (so a plain `docker compose up` includes `cloudflared`), and the tunnel token at a hidden prompt; prints which values are set, never the values |
| `climpact-image-prune.timer` | weekly `docker image prune --all --filter until=720h` |

The ticket's "purge timer" is the Compose `purge` service (see [Compose stack](#compose-stack)),
and app updates are releases, which the release workflow pushes to the Droplet's deploy
hook (#126), so cloud-init installs no timer for either. No host
firewall (ufw): the DigitalOcean Cloud Firewall has no inbound rules (one SSH rule for the
admin's IP only while it is needed), applied by the tag `climpact`, so a new Droplet is
covered from its first boot. Nothing publishes a port, and the tunnel is outbound. The
tunnel's public hostname `climpact.app` routes to `http://web:8000`, and Cloudflare creates
its proxied CNAME. No DNS record may point at the Droplet's IP. Break-glass access: the SSH
rule for the admin's IP; DigitalOcean's Droplet Console, which needs port 22 open to all
because its source addresses are not published; or the Recovery Console after a root
password reset, which root can use because root is refused only over SSH.

**Tested locally** (2026-11-15, without the DigitalOcean or Cloudflare accounts):
`cloud-init schema` (cloud-init 26.2 in `ubuntu:24.04`) reports the file valid, and
shellcheck finds nothing in the three scripts. A full cloud-init run in a privileged
`ubuntu:24.04` container (arm64) with a NoCloud seed and a test SSH key, with swap and
`package_upgrade` left out and `CLIMPACT_BOOTSTRAP_NO_SYSTEMD=1` (no systemd in the
container), created `deploy` with the key, Docker 29.9 and Compose 5.7 from the verified
repository, `/opt/climpact` with the files from `main`, and the apt settings; `sshd -T`
gives `permitrootlogin no`, `passwordauthentication no`, `allowusers deploy`. The only
cloud-init error was `set_passwords`, which needs systemd. This test found that Docker's
key file holds a subkey with its own `fpr` line, and the check compares only the primary
key. `climpact-init-env` filled the secrets, kept the Postgres password on a second run,
and left `.env` at 0600. `climpact-use v0.1.0` (since replaced by `update.sh`, #126)
stopped with a clear message, because the release did not exist yet; with `curl` and
`docker` stubbed it pinned `CLIMPACT_IMAGE` and replaced the pin on the next version. `docker compose config --services` lists
`cloudflared` once `COMPOSE_PROFILES=tunnel` is in `.env`. Not yet tested on a real
Droplet: swap, the services, unattended upgrades, the tunnel and the closed IP. Those are
the runbook's steps 3, 7 and 8, done once v0.1.0 (#131) has published the first image.

#### Cloudflare edge

The zone's settings (#124) are applied by hand in the Cloudflare dashboard (free plan),
from `deploy/README.md` › *Cloudflare edge settings*; nothing account-side is automated.
The rule expressions are files in `deploy/cloudflare/` (plain ASCII, pasted into the
expression editor), and `deploy/check-edge.sh` checks the result from outside with curl.

| Setting | Value |
| --- | --- |
| TLS | Always Use HTTPS; minimum TLS 1.2; Cloudflare's HSTS off (the app sends `max-age=31536000; includeSubDomains`) |
| `www` | proxied `AAAA www → 100::` placeholder and a 301 redirect rule `http*://www.climpact.app/*` → `https://climpact.app/${2}`, query string kept |
| WAF | Cloudflare Free Managed Ruleset; custom rules: skip `waf-skip-deploy.txt` (`POST /_deploy`, first: skips the other custom rules, the managed rules, rate limiting, Browser Integrity Check and Security Level; #126); skip `waf-skip-healthz.txt` (`GET`/`HEAD /healthz`, second, the same skips: DigitalOcean's Uptime check comes from cloud addresses; #127), block `waf-block.txt` (`*.php` and similar, WordPress paths, `/cgi-bin/`, dot segments except `/.well-known/`), managed challenge `waf-challenge.txt` (`/admin*`, `/patterns/`) |
| Rate limit | the one free rule: `rate-limit.txt`, 10 requests per 10 s per IP, then block (429) for 10 s |
| Bots | Bot Fight Mode **off** since the first automatic deploy, which it challenged (#126); no rule can exempt a request from it. Turning it back on needs deploys that don't call in from outside, and a check that the uptime check still passes |
| Cache | `/static/*` eligible for cache, edge TTL from `Cache-Control`; everything else bypasses the cache |
| Turnstile | a Managed widget for `climpact.app`; its keys go in `.env` (see [Security of the hosted site](#security-of-the-hosted-site)) |

The free plan's rate-limiting rule can match the path, but **not the method**, so a rule on
"POSTs to `/w/`" would also count the htmx polls (`.../progress`, about once a second
while a job runs) and the htmx validation POSTs. `rate-limit.txt` therefore lists the
exact paths that take an upload or start a job. `test_deploy_files.py` reads the seven
expression files with a small evaluator (`wildcard`: whole value, case-insensitive;
`contains`; `eq` on the path or the method; `and`/`or`/`not`), runs them against a sample path for every URL pattern of
the app, and checks that the rate limit counts exactly the job-starting views, that the
WAF rules match no page except `/patterns/`, that only `/static/` is cached, and that the
deploy hook's `POST /_deploy` is matched by the skip rule and by no block, challenge or
rate-limit rule (and the skip rule by nothing the app serves), and that `/healthz` (GET and
HEAD) is matched by its own skip rule and the cache bypass, by no block, challenge,
rate-limit or static-cache rule, and its skip rule by nothing else. The Inputs panel's
sheets start jobs when applied, so the rule counts `/w/*/inputs/<key>` for each of
the five keys, but not `/w/*/inputs/progress` (#199; `quality/run` left the rule
with its form). Since #201 it counts `/w/*/setup` (a station's setup page), instead of
the upload page, the old Load page and its "Use a different file" (`/station/`,
`.../load`, `.../file`), which now only redirect or are gone. Since #256 the station paths
are under `/w/` (`*` matches any number of path segments, so `/w/*/setup` is
`/w/<id>/<station>/setup`) and "Recalculate" is `/w/*/recalculate`; the old
`/station/<id>/…` and `/batch/<id>/…` addresses only redirect a GET, so they are not
counted. The old New station and batch forms (`/station/new`, `/station/sample`,
`/batch/`, `/batch/sample`, `/w/*/batch/files`, `/w/*/batch/run`) left the rule with #271:
their addresses only redirect to Add stations. Since #310 the rule counts Add stations'
own paths, which take the files dropped or add the stations and queue their jobs: `/add/`,
`/add/sample`, `/add/sample-batch`, `/w/*/add/` and `/w/*/add/*/` (the review form), but
not `/w/*/add/*/check`, the table's check as it is typed (`add` is a reserved station slug,
so neither pattern matches a station's pages). A normal Add stations flow makes at most
about 5 counted requests in any 10 s (the page, the drop and its redirect, a second drop and
its redirect), and 6 to 8 counted requests in all. A new job-starting URL therefore fails the test until it is added to `rate-limit.txt`. Bot Fight
Mode can't be exempted by any rule. htmx swaps in only 2xx answers, so a challenged poll
would freeze a progress bar until the page is reloaded; the runbook says how to watch for
this. Bot Fight Mode is off (see the table). The same test checks
that `.env.example` and the `compose.yaml` default send HSTS for a year, and keep
`CLIMPACT_WEB_MAX_UPLOAD_MB` at or under the free plan's 100 MB request bodies.

#### Deploy on release

Publishing a final GitHub Release deploys it to climpact.app with no manual step (#126;
user decisions: merges to `main` never deploy, 2026-11-14; the release workflow calls a
webhook through the existing tunnel rather than the Droplet polling, 2026-11-15). The
Droplet still accepts no inbound connections: the call comes in through the Cloudflare
Tunnel like every other request.

```
release.yml deploy ──POST /_deploy (signed)──▶ Cloudflare ──tunnel──▶ deploy-hook (container)
                                                                     │ writes hook/request
     ◀──polls /healthz until it reports X.Y.Z──                      ▼
                                            climpact-deploy.path ─▶ update.sh --hook (host)
```

| Piece | Where | Does |
| --- | --- | --- |
| `deploy` job | `.github/workflows/release.yml` | last job; `deploy/call-hook.sh post X.Y.Z`, then `call-hook.sh wait X.Y.Z` |
| `deploy-hook` | Compose service running `deploy/deploy-hook.py` | checks the signature and the version, writes the version to `hook/request`, answers 202 |
| `climpact-deploy.path` / `.service` | systemd units on the host, written by `update.sh --install-hook` | `PathExists=/opt/climpact/hook/request` starts the oneshot service, as `deploy`: `update.sh --hook` |
| `update.sh` | `/opt/climpact/update.sh`, from `deploy/update.sh` | fetch, pull, migrate, start, check, roll back, prune |

**Why the hook only drops a file.** The listener is the one piece the internet can reach,
so it holds no privilege: it runs as uid 10001 on a read-only root, drops all
capabilities, sits only on the `backend` network (no route out) and has no Docker socket.
All it can do is write a validated `X.Y.Z` into the folder `/opt/climpact/hook`
(owner 10001, group `deploy`, mode 2770, so the host's `deploy` user can read and delete
the file). The host's path unit does the deploy. Rejected: a listener on the host, which
would put an HTTP parser that the internet reaches in a process that can run Docker (the
`docker` group is root-equivalent), and needs the tunnel to reach the host's bridge
address; a listener container with the Docker socket mounted, for the same reason;
`adnanh/webhook`, one more image and configuration language for what 150 lines of
standard-library Python do.

**The request.** `POST /_deploy` with the body `{"version": "X.Y.Z"}`, the header
`X-Climpact-Timestamp: <unix seconds>` and `X-Climpact-Signature: sha256=<hex>`, an
HMAC-SHA256 of `<timestamp>.<body>` keyed with `DEPLOY_WEBHOOK_SECRET` (the GitHub secret
and the Droplet's `.env` hold the same value). The hook answers, always as JSON with
`"hook": "climpact-deploy"` (so `call-hook.sh` can tell it from the app or the edge),
`Cache-Control: no-store` and `Content-Security-Policy: default-src 'none';
frame-ancestors 'none'` (the app's policy, [Content Security Policy](#content-security-policy),
comes from Django, which the hook doesn't run):

| Answer | When |
| --- | --- |
| 202 | valid: the version is in `hook/request` (a newer request replaces one not yet picked up) |
| 401 | no or wrong signature, or a timestamp more than 300 s from the hook's clock (so a captured request can't be replayed later to roll the site back); nothing is written |
| 400 | signed, but the body is not a JSON object whose `version` matches `[0-9]+\.[0-9]+\.[0-9]+` (ASCII digits only, whole string) |
| 503 | `DEPLOY_WEBHOOK_SECRET` is empty or shorter than 32 characters on the Droplet |
| 404, 405, 411, 413 | another path; another method than POST; no `Content-Length`; a body over 1 KB |

The signature is checked with `hmac.compare_digest` before the body is parsed. Nothing in
the body but `version` is read, and nothing but `update.sh <version>` can be triggered.
`update.sh --hook` reads at most 64 bytes of the request, deletes it and checks the
version again before using it. The hook handles SIGTERM itself (it is PID 1).

**One at a time.** systemd never starts a unit that is already running; a request that
arrives during a deploy stays in `hook/request`, and when the service finishes the path
unit sees it and starts the next run. `update.sh` also takes an `flock` on
`/opt/climpact/.deploy.lock`, so a deploy started by hand waits for one started by the
hook and the other way round (up to an hour).

**`update.sh X.Y.Z`** (as `deploy`; `vX.Y.Z` also works; the same steps for the hook, by
hand, or a rollback to an older release):

1. Fetch `compose.yaml`, `.env.example`, `deploy-hook.py` and `update.sh` from tag
   `vX.Y.Z` on `raw.githubusercontent.com` into a staging folder, and `docker pull
   ghcr.io/geoffwalmsley/climpact-web:X.Y.Z` (a public package: no credential on the
   Droplet, unlike the read-only registry token the ticket planned for a DigitalOcean
   registry). A failure here changes nothing. Releases before `deploy-hook.py` and
   `update.sh` existed (0.1.1 and older) lack those two: the current copies are kept.
2. Copy the current files and `CLIMPACT_IMAGE` to `.previous/`; move the new files in (by
   rename, so the running script keeps reading its own copy) and pin `CLIMPACT_IMAGE` in
   `.env`.
3. `docker compose run --rm -T migrate`, then `docker compose up -d --wait` (Compose
   recreates only what changed; the `migrate` dependency runs again with nothing to do).
   If `deploy-hook.py` changed, `docker compose restart deploy-hook` (a file bind mount
   keeps the old inode until the container restarts).
4. `docker compose exec web python` fetches `http://127.0.0.1:8000/healthz` (with the
   first allowed host as `Host`) until it reports `X.Y.Z`, for up to 180 s.
5. If step 3 or 4 fails: restore `.previous/`, `up -d --wait`, check that `/healthz`
   answers with the old version, and log `ROLLED BACK to ...` (or `ROLLBACK ... FAILED
   TOO`); exit 1. On the very first deploy there is nothing to roll back to.
6. On success, remove the `climpact-web` images other than the new and the previous one,
   and dangling images.

It logs to stderr and one line per step to `/opt/climpact/deploy.log`; run by the
service, stderr is in the journal (`journalctl -u climpact-deploy`), and run by hand it
also logs with `logger` (`journalctl -t climpact-deploy`). Other modes:
`--fetch vX.Y.Z|main` (files only; cloud-init uses `--fetch main`) and, as root,
`--install-hook`. It replaced `climpact-use` (#123), so there is one way to change what
runs.

**Migrations are not reversed.** A rollback restores the previous image and Compose files
but keeps the database as the new release's migrations left it (reversing them would need
each migration's target, and data migrations may not reverse). So a release's migrations
must keep working with the previous release's code (add columns and tables; drop or rename
them a release later), or its release notes must say that a rollback needs a database
restore. Django runs each migration in a transaction on Postgres, so a migration that
fails leaves nothing half-applied.

**The worker on SIGTERM.** `runworker` sets the worker's stop flag; the running job
raises `JobInterrupted` at its next progress step and is queued again, and the new worker
runs it from the start. A stage that reports no progress can't be interrupted, so the
worker's `stop_grace_period` went from 30 s to 120 s; if Docker still has to kill it, the
job stays `running` until the new worker's `reap_stale` marks it failed (no heartbeat for
`JOB_STALE_SECONDS`, 60 s) with a retry offered. The worker is recreated only when its
image or settings change, which is every release.

**The `deploy` job.** It needs `version` and `publish` and runs only when the event is a
release, the release is not a pre-release (checked both on the event and on the version),
and `publish` succeeded; a merge to `main` doesn't start `release.yml` at all, and a pull
request that changes it skips the job. Its environment is `production` (URL
https://climpact.app), which the owner limits to `v*` tags and which holds
`DEPLOY_WEBHOOK_SECRET` as an environment secret. Permissions `contents: read` only (a
sparse checkout of `deploy/call-hook.sh`), concurrency group `deploy-production`, never
cancelled, 20 minutes at most. `call-hook.sh` needs only `sh`, `curl` and `openssl`:
`post` signs with `openssl dgst -sha256 -hmac` and POSTs (retrying network errors and
5xx), succeeding only on 202, and otherwise says which side failed: a Cloudflare challenge
(`cf-mitigated: challenge`), an answer that isn't the hook's (no tunnel route, or an edge
rule), a tunnel error (502/530: the service isn't running), a refused signature, or no
secret on the Droplet. `wait` polls `https://climpact.app/healthz` every 10 s for up to
10 minutes; the job is green only once it reports the new version. A rolled-back deploy
keeps reporting the old version, so the job fails at the timeout. Re-running the job
deploys the same release again.

**Cloudflare.** The tunnel's published application route for `climpact.app` with path
`_deploy` sends the call to `http://deploy-hook:9000`; it must come before the catch-all
route to `web`. The path is an unanchored regular expression, so it would also match any
other path containing `_deploy`: the app has none, and the hook answers 404 to anything
but `/_deploy`. No existing custom rule, rate limit or cache rule matches `POST /_deploy`
(tested), and `cache-bypass.txt` covers it, but the runner's addresses are a cloud
provider's, so the zone's Security Level or the managed rules could still challenge it:
`waf-skip-deploy.txt` is a Skip rule for `POST /_deploy` only, placed first. **Bot Fight
Mode can't be skipped** by any rule on the free plan, and it may class `curl` from a
GitHub-hosted runner as a bot, for the POST and for the `/healthz` polls. If it does,
`call-hook.sh` fails at once with that diagnosis, and the fix is to turn Bot Fight Mode
off (the runbook already allows that, #124); the signature, the rate limit and Turnstile
still guard the site. That happened on the first automatic deploy, and Bot Fight Mode has
been off since.

**Tests.** `test_deploy_hook.py` runs the hook on loopback: 202 and the request file for
a signed request (and the latest request wins); 401 and no file for a missing signature,
a wrong secret, a changed body, a timestamp too old or in the future and a malformed one;
400 for versions such as `1.2`, `1.2.3rc1`, `v1.2.3`, `1.2.3\n`, Arabic-Indic digits or a
number, and for signed bodies without a version; 404, 405 and 413; 503 without a secret;
`no-store` on every answer. `call-hook.sh post` against that hook checks that openssl's
signature is what the hook expects, and that a wrong secret is reported as such; `wait`
runs against a stand-in `/healthz` whose version changes after a few polls, and times
out when it never does. `update.sh` runs in a temporary folder with stub `docker`, `curl`
and `logger` on `PATH`: a deploy (file contents, `.previous/`, the order pull → migrate
→ up → restart hook → health check, the pruning), a tag name, a failed pull and a
missing release (nothing changed, no Compose call), a failed health check and a failed
migration (files and image rolled back, the old version checked), a failed rollback,
an older release without the hook files, invalid versions and arguments (no Docker call),
`--hook` with a good, a malicious and no request, and `--install-hook` refusing to run
without root. With util-linux `flock` (Linux, so CI), a second deploy started during a
first one waits for the lock and runs after it. `test_deploy_files.py` checks the
Cloudflare skip rule, that the hook service is locked down (`backend` only, read-only, no
capabilities, uid 10001, the only service with the secret, no Docker socket and no
published port anywhere, the `Dockerfile`'s Python image), the worker's grace period, and
`release.yml`'s `deploy` job (last, final releases only, `production`, `contents: read`).

**Tested locally** (2026-11-16, Docker Desktop 29): the `update.sh` tests, including the
lock test, in `python:3.12-slim` (Debian, so `sh` is dash and `flock` is util-linux); the
hook in that image as Compose runs it (read-only, uid 10001, all capabilities dropped) with
a setgid drop folder: an unsigned POST got 401, `call-hook.sh post 0.1.2` got 202 and the
folder held `request` (mode 0640) with `0.1.2`, and `docker stop` took 0.2 s;
`docker compose config` accepts the new `compose.yaml`; shellcheck finds nothing in
`update.sh`, `call-hook.sh` and cloud-init's two scripts; actionlint passes `release.yml`.
Not tested here: systemd's path unit, the tunnel route, the edge rules and Bot Fight Mode
against a GitHub runner, which need the Droplet and the Cloudflare account; the first
release after this change is their test (see the runbook).

#### Operations: alerts, backups, credentials

Set by hand in the DigitalOcean control panel from `deploy/README.md` › *Alerts* (#127);
nothing account-side is automated, and everything used is free except the Droplet.

| What | Setting |
| --- | --- |
| Uptime | a DigitalOcean Uptime check on `https://climpact.app/healthz` from two or three regions: downtime alert after 5 minutes (long enough to ignore the 03:30 UTC reboots and deploys), latency over 5 s for 10 minutes, certificate expiry 7 days ahead. It goes through Cloudflare, so it also catches a broken tunnel or edge rule; `waf-skip-healthz.txt` keeps the WAF off it, the cache rules bypass it and the view is `never_cache` (tested), and `check-edge.sh` checks it from outside |
| Droplet | DigitalOcean Monitoring resource alerts, applied by the tag `climpact` so a new Droplet is covered: memory over 90 % for 10 minutes, disk over 80 % for 5 minutes, CPU over 90 % for 30 minutes (not the ticket's 15: one job keeps the single CPU near 100 % for 10 minutes or more) |
| Spend | a DigitalOcean billing alert at $15/mo (the expected bill is $12) |
| Deploys | GitHub's e-mail for a failed `deploy` job; a failed deploy has rolled back or changed nothing |

**Backups (decision, #127): none.** No DigitalOcean Backups or Snapshots and no scheduled
`pg_dump`. The database and the `media` volume hold only jobs, which expire after 7 days
and belong to one browser session; there are no accounts. A dump on the Droplet would not
survive the Droplet's loss, a dump elsewhere needs paid storage and another credential,
and a dump without `media` restores jobs whose files are gone. A lost Droplet is created
again from the runbook (*Operating the server* › *Rebuild from nothing*), losing only open
jobs. The runbook gives a by-hand `pg_dump`/`pg_restore` for a release whose migrations
the previous release can't work with, since a rollback doesn't undo migrations.

**Credentials.** The runbook's *Credentials* table lists each secret, where it lives, its
expiry and how to rotate it: the Django secret key and Postgres password (`.env` only,
made on the server), the tunnel token and Turnstile keys (`.env` and Cloudflare), the
deploy hook secret (`.env`, the GitHub `production` environment and the owner's password
manager), the `deploy` user's SSH key, and the account logins with two-factor
authentication. No registry or API token exists: the image is a public ghcr.io package
pushed with the workflow's `GITHUB_TOKEN`, PyPI uses Trusted Publishing, and nothing calls
the DigitalOcean or Cloudflare APIs. Rotating the Django key also ends visitors' access to
their open jobs, because a job belongs to the session that made it.

### Security of the hosted site

The hosted site has no accounts, so the edge (Cloudflare, above) stops floods, and the app
limits what one visitor can make the single worker do (#125). Everything in
`core/limits.py` is off in local mode (`IS_HOSTED` false), so the offline install and
the tests are unchanged; the settings are in [Settings](#settings).

**The client address.** `client_ip` reads Cloudflare's `CF-Connecting-IP` in hosted mode
only. The header can be trusted there because the origin is reachable only through the
Cloudflare Tunnel (no published port, [Compose stack](#compose-stack)), and Cloudflare
sets it. Anywhere else it is ignored, since anyone could send it, and `REMOTE_ADDR` is
used. A header that is not an IP address is ignored too. The quotas count by
`client_key`: the IPv4 address, or the /64 network of an IPv6 address, because one
connection usually gets a whole /64.

**Turnstile.** On when hosted and both `CLIMPACT_WEB_TURNSTILE_SITE_KEY` and
`_SECRET_KEY` are set. `{% turnstile %}` (`core/templatetags/ui.py`) renders the widget
(`<div class="cf-turnstile" data-size="flexible">`, in the page's language) above the submit
button, with a `<noscript>` note that the check needs JavaScript, and adds `js/turnstile.js` and Cloudflare's
`api.js` once per page (`<script src>`, no inline code), so pages without such a form
load neither. **Waiting for the token (#163).** The widget takes a second or two to get
its token, out of sight when the form's widget is below the fold, and a form sent before
then was refused (`turnstile-missing`): on the live site, the sample's top button on
the old step 1 page ("Details look right", outside the details form with
`form="station-details"`; #173 removed it, and a station's setup page has since taken the
page's place, #198, #201).
`turnstile.js` catches every submit in the capture phase (the form's own buttons, a button
outside it, Enter) of a form holding a `.cf-turnstile`; with no token in that form's
widget (or `turnstile.isExpired`), it stops the submit, marks the form's submit buttons
`aria-busy` and `aria-disabled`, puts a `role="status"` line beside the button pressed,
and sends the form with `requestSubmit(submitter)` (the button's name and value kept)
when the token comes: the widget's `data-callback`/`data-error-callback` name its global
functions, and a 250 ms poll covers a callback that ran before the file did. After 6 s
the line asks the user to answer the check, if it asks something, and scrolls the widget
into view; on a widget error or after 60 s it says the form was not sent, with a "Try
again" button (`turnstile.reset`). A token that comes later still sends the form. Its
texts come translated in the widget's `data-wait`, `data-slow`, `data-failed` and
`data-retry`. Each form reads only its own widget's field, so the widgets of one page keep
their tokens apart: a station page carries one in each of the Inputs panel's sheets
(`stations/_input_form.html`) and one in a form of its own where it has one (the sector
form; Results' "Recalculate" when out of date, `stations/_recalculate_form.html`),
while Add stations (`stations/add.html`, a widget in its drop form or in its review
form, never both) and a station's setup page (`stations/new.html`) have one each.
Widgets that arrive in an htmx swap are rendered with `turnstile.render` on `htmx:load`
(implicit rendering only scans the page when `api.js`
loads), never twice; since htmx runs script tags off, that needs a page that already
loaded the scripts with a widget of its own. None of today's swaps carries one. The
views whose POST uploads a file or starts a job are wrapped in `human_required`: the New
station page (its file, and its details, which queue the checks; #201), the Inputs
panel's sheets (the file, the details, the thresholds and the settings), the indices and the sector run; batch upload, add files and
run; gridded upload and set-up. The decorator posts the widget's `cf-turnstile-response`
to `https://challenges.cloudflare.com/turnstile/v0/siteverify` (form-encoded, with
`remoteip`, 10 s timeout) once per request. A missing or rejected token gets a 400; no
answer from Cloudflare gets a 503 (fail closed, logged as an error). The sample-data buttons
(`disk_required`) and job retry need no token: the samples copy a bundled file and start
nothing, and a retry uploads nothing, while the disk guard and the quotas still apply. The
Content Security Policy allows the script and its frame from
`https://challenges.cloudflare.com` only when Turnstile is on, and the Web Analytics beacon
in hosted mode (see
[Content Security Policy](#content-security-policy)); `Referrer-Policy: same-origin`, `COOP: same-origin` and `X-Frame-Options: DENY` don't
affect the widget (they govern this site's pages, not Cloudflare's frame). Managed mode
usually passes without a question. Cloudflare states the widget meets WCAG AA (its docs
have said 2.1 AA and, more recently, 2.2), a claim made by Cloudflare itself, not checked
by this project's audit (#83), which runs with Turnstile off. Nothing else on the pages
changes.

**Quotas and guards.** `create_job` calls `check_job_quotas` before it writes anything, and
the retry view calls it before re-queuing. In order:

| Check | Refused when | Answer |
| --- | --- | --- |
| disk (`check_disk`, also every `human_required` and `disk_required` POST) | `MEDIA_ROOT`'s disk (or its nearest existing parent) has under `MIN_FREE_DISK_GB` free | 503, "busy, try again in a few minutes", `Retry-After: 600` |
| queue | `MAX_QUEUED_JOBS` or more jobs wait (not cancelled) | 503, the same message, `Retry-After: 300` |
| active jobs | the client has `MAX_ACTIVE_JOBS_PER_IP` or more jobs waiting or running (not cancelled) | 429, how many, and to wait or cancel one |
| daily jobs | the client has started `MAX_DAILY_JOBS_PER_IP` or more jobs in 24 hours (`JobStart` rows) | 429, try tomorrow or install Climpact locally |

The jobs of one change (`params["change"]`, #254: a workspace's recalculation of all its
stations, a station's checks and run after a change to its details, a new station's checks
and speculative run) count as one job in the queue, active-jobs and daily counts
(`jobs.models.change_groups`), whatever the number of stations. The change is checked with
its first job; its other jobs are let through (`limits.change_admitted`), and
`record_job_start` records one `JobStart` per change (`JobStart.change`), also when a
speculative run of it is promoted. So the daily quota counts what the user did, not the
stations it touched: 50 by default (30 before #254, when a new station took two starts, its
checks and its run), room for a day of, say, 10 new stations and 40 changes to settings.

The queue and active-jobs counts leave out speculative runs (#178, `jobs.models.ordinary_q`),
and a speculative run records no `JobStart`: see "Speculative calculation" in [A station's pages](#a-stations-pages).
A speculative run has its own check, `check_speculative_quotas`: the disk as above, fewer
than `SPECULATIVE_MAX_QUEUED` (default 3) jobs of any kind waiting, and fewer than
`MAX_ACTIVE_JOBS_PER_IP` jobs of the client's (speculative or not) waiting or running,
each change counted once and the run's own change, already the client's through the checks
queued with it, left out (#254). Its
refusal is silent (logged at INFO to `climpact_web.stations`); the run is then queued as an
ordinary job at "See results", under the checks above.

Refusals come before the job is created, so no job fails halfway. The checks are counts,
not locks: two requests at the same moment can both pass, so a quota can be overrun by a
job or two. A refusal raises `Refused` (reason, message, status, `Retry-After`);
`RefusalMiddleware` renders `refused.html` (the message in a warning alert, and links to
the jobs and the home page) and logs a warning to `climpact_web.limits`: `Refused POST
/w/<id>/<station>/setup from 203.0.113.7: active-quota:2`. The reasons are
`turnstile-missing`, `turnstile-failed:<codes>`, `turnstile-unavailable`,
`active-quota:<n>`, `daily-quota:<n>`, `queue-full:<n>` and `disk-low:<MB>`, and
`deploy/README.md` says how to use them to tune the Cloudflare rules. A refused token
saves nothing, as the view does not run. A station's setup page refused by a quota saves
none of the station's details (the base period of a workspace that is the station's own
is saved first, `set_base_period`), so going back and sending the form again saves them
and queues the checks. On Add stations a quota refusal makes nothing, with one station or
several, and the review stays with its files and what was typed (`keep_typed` saves the
table first), to be sent again: several stations are refused when their batch job is
created, before any station is made (`queue_batch`), and one station by
`check_job_quotas` at the top of `add_one` (#351; until then the station was made first
and kept without its checks or run, and the files waiting were gone). Should the
station's checks be refused after all (two requests at once), `add_one` deletes the
station and keeps the review.

**Job time limit.** See *Time limit* in [Background jobs](#background-jobs).

`test_limits.py` covers each of these: the address in either mode, the widget's markup,
missing, forged, too long and valid tokens, Cloudflare unreachable, each quota and guard
(and that local mode has none), a refused station on Add stations (#351), retries, the
purge of `JobStart`, the soft time limit, and the heartbeat's hard stop.
`test_deploy_files.py` checks that `.env.example` and `compose.yaml` carry every setting,
and that `web` is the only app service on `egress`.

### Image in CI and on ghcr.io

The image of [Deployment](#deployment) is built and tested on every pull request and push
to `main`, and published only when a GitHub Release is published (#122; user decisions of
2026-11-14 and 2026-11-15). The registry is the **GitHub Container Registry**,
`ghcr.io/geoffwalmsley/climpact-web`, as a public package: the repository is public, so
storage and pulls cost nothing, CI pushes with the workflow's own `GITHUB_TOKEN`, and the
Droplet pulls without credentials. It replaced the DigitalOcean Container Registry planned
in #12.

**One script, three workflows.** `scripts/image.sh` holds the steps, so they run the same
locally, in CI and in a release:

| Step | Does |
| --- | --- |
| `build <image>` | `docker buildx build --platform linux/amd64 --provenance=false --sbom=false --load`, with a local layer cache (`BUILDX_CACHE_FROM`/`_TO`) and the version and revision as OCI labels |
| `smoke <image>` | runs the image as deployed (`--read-only`, tmpfs `/tmp`, a media volume, the hosted variables) against an empty Postgres on `SMOKE_NETWORK`: `migrate`; `manage check --deploy` (fails on errors only: the HSTS warning is expected); the `web` role, whose `/healthz` must report the database ok, whose landing page must answer 200 behind `X-Forwarded-Proto: https` and 301 without it, running as uid 10001 on a read-only root, until Docker's `HEALTHCHECK` reports healthy; the built-in Sydney sample as a station job (with the zip) through `worker --once`; and a clean exit 0 on `docker stop` |
| `scan <image>` | Grype (`anchore/grype` v0.121.0, its official image pinned by digest) over `docker save`'s archive: the table in the log, the counts by severity and the critical findings in the job summary, and a warning annotation when there are criticals; never fails the build (yet) |
| `tags <git tag> <prerelease>` | the registry tags: `X.Y.Z` for `vX.Y.Z`, plus `latest` only when the release is not marked pre-release and has no `a`/`b`/`rc` suffix; any other tag shape fails. `tags-selftest` checks it on fixed cases |
| `publish <image> <repo> <tags>` | `docker tag` and `docker push` each tag |

- `image.yml` is a reusable workflow (`workflow_call`) with a Postgres 16 service: tags,
  restore the layer cache, build, smoke test, scan, tag locally, and with `artifact: true`
  keep the tested image (`docker save`) as the one-day `image` artifact. It never pushes and
  its token is read-only.
- `ci.yml`'s `image` job calls it with `save-cache: true`, as a dry run: the tags are those
  `v<climpact_web.__version__>` would get.
- `release.yml` runs on `release: published`. Its `image` job calls `image.yml` with the
  release's tag and pre-release flag, building from the tagged commit; its `publish` job
  (`needs: image`) loads that artifact, logs in with `echo "$GITHUB_TOKEN" | docker login
  ghcr.io --password-stdin`, pushes the tags, writes the digest to the job summary, logs
  out and deletes untagged package versions. A pull request that changes `release.yml`
  runs its `image` job as a dry run; `publish` runs only for a release. Since #131 the
  PyPI jobs come first, and `image` runs only after the packages are published: after
  `pypi` for a release, after `testpypi-check` for a pre-release (see
  [Releases and PyPI](#releases-and-pypi)).

**What pushes.** Only a published release: `vX.Y.Z` pushes `:X.Y.Z` and moves `:latest` to
it (`latest` follows the last published final release, so publishing an older patch moves
it back); a pre-release pushes only its version tag and never `latest`. The Droplet runs
an exact version, never `latest`: the `deploy` job (#126) deploys a final release's
`X.Y.Z`, and pre-releases are not deployed. Merges to `main` and pull requests push nothing. The image
pushed is the one the smoke test and scan ran on, carried between the jobs as the
artifact, not a rebuild.

**Credentials.** Every job has `contents: read` only, except `publish`, which adds
`packages: write`; there is no stored registry secret or personal token. Checkouts use
`persist-credentials: false`. Only GitHub-owned actions and `astral-sh/setup-uv` are
allowed (see [Development](#development)), so the image steps use the `docker` CLI on the
runner rather than Docker's own actions, and Grype runs from its container image.

**Layer cache.** `actions/cache` keeps buildx's local cache (`type=local`, `mode=max`, so
the builder stage's dependency layer is included) under a key hashed from the
`Dockerfile`, `.dockerignore`, `uv.lock` and the `pyproject.toml` files. A run whose key
hits reuses the dependency layers and rebuilds only the sources (a minute or so); `ci.yml`
saves a new cache only when the key misses, and releases only restore. Caches saved on
`main` are readable by every pull request and release tag. The GitHub Actions cache
backend (`type=gha`) is not used, because its runtime token reaches only actions, not `run`
steps, and the action that exposes it is third-party.

**Registry upkeep.** Release tags are kept, for rollback. The image is a single-platform
manifest with no attestations, so each release is exactly one package version; an
untagged version appears only when a tag is pushed again (a re-run), and `publish` deletes
those (warning, not failing, if the token may not). This is safe only while the image is
single-platform: a multi-platform image's per-platform manifests are untagged versions too.
The package's `org.opencontainers.image.source` label (in the `Dockerfile`) links it to the
repository. A package that `GITHUB_TOKEN` creates may start private: after the first
release, check its visibility under the package's settings and make it public once.

**Testing it without a release.** A pull request shows the build, smoke test, scan and the
dry-run tags passing. The publish path was checked locally (2026-11-15, Docker Desktop
29): `docker save` → `docker load` → `scripts/image.sh publish` to a local `registry:2`
pushed `0.1.0` and `latest` for `v0.1.0`, and only `0.2.0rc1` for a pre-release
`v0.2.0rc1`, as one OCI manifest each. The first real release is the first end-to-end run
of `publish` and the untagged cleanup: by the user's decision (2026-11-15) that is
#131's first release, the pre-release `v0.1.0rc1`, so the first image is `:0.1.0rc1`
(#123 waits for it).

### Releases and PyPI

Both packages are on PyPI, released together from a GitHub Release (#131; user decisions
of 2026-11-14). The steps for the maintainer, including the one-time setup of the
publishers and environments, are in `RELEASING.md`.

**Names.** The core's distribution is `climpact`, so the pip name, the import name and the
command match (`pip install climpact`); it was `climpactpy` until #131 and was never
published under that name. The web app is `climpact-web`. The GitHub repository keeps the
name `climpactpy`, which the URLs, the Kanban and the reference data (the gridded R runs'
template `var_daily_climpactpy_historical_NA_...` and author `climpactpy reference`, see
`reference/README.md`) still carry. The name `climpact` implies the official software, so
PyPI ownership moves to WMO at handover (#12). Everything the port writes names it
**Climpact for Python** with the R version it ports, never plain "Climpact":
`io.output_files.software_credit()` gives `Climpact for Python X.Y.Z (port of Climpact
3.4.3)`, used by `climpact --version`, the plot and sector plot footers and the PDF
report's footer, cover and `Creator`; the report's `Author` and the gridded netCDF
`history` use `SOFTWARE_NAME`, and the netCDF attribute is `climpact_python_version`.

**Versions.** One version number for both, SemVer in its PEP 440 form, starting at
`0.1.0`; tags are `vX.Y.Z`. The version is in three places: `climpact.__version__`,
`climpact_web.__version__` (hatch reads each package's version from it) and climpact-web's
dependency `climpact[plots]==X.Y.Z`. The pin is written in `pyproject.toml` rather than
generated at build time; `[tool.uv.sources]` still resolves it to the workspace member in
development. `scripts/set_version.py X.Y.Z` sets all three, `packages/climpact-web/tests/test_packaging.py`
checks they agree, and `release.yml` checks the tag against them. A release is a bump pull
request (`set_version.py`, `uv lock`, a `CHANGELOG.md` entry), then a GitHub Release
`vX.Y.Z` from `main`. `a`/`b`/`rc` versions are pre-releases: GitHub's pre-release box must
match the version (`packaging.version.Version.is_prerelease`), and they go to TestPyPI only.

**Package contents.** hatchling builds both. The wheels hold the package folder: the core
its modules and `data/climate.indices.csv`; climpact-web its templates, static files (the
committed, built `css/climpact.css` included), help guides, sample data and outputs,
migrations and locale, but not `core/tailwind/` (only `scripts/build-css.sh` and the token
tests read it). Static files are shipped as sources: local mode collects them into the
data folder on start, hosted mode runs `collectstatic` (the image does it at build time).
The sdists hold `src/`, `README.md`, `LICENSE` and `pyproject.toml` only; the tests are not
shipped, as they need the repository's `reference/` data. Metadata: the PEP 639 licence
expression `GPL-3.0-or-later` with `license-files`, classifiers (Python 3.12-3.14, Science/
Research, Atmospheric Science, OS independent; Django 6.0 for the web), project URLs and
the package READMEs, written for PyPI with absolute links. `scripts/check_dists.py`
compares each wheel's file list with the files git tracks under `src/` (printing it),
rejects tests, reference data and bytecode, and checks the names, versions and the pin;
`scripts/smoke_dists.sh` installs the wheels in a clean virtualenv away from the checkout
and checks `climpact --version`, the imports and versions, that `climpact-web` starts and
answers `/healthz` with the database ok, and that its stylesheet is collected and served.
Both run in CI's `dist` job and in every release. The builds use `uv build --no-sources`,
so they depend only on the publishable metadata, and are byte-for-byte reproducible from
the same commit and hatchling version (checked locally).

**`release.yml`.** Triggered by `release: published` only (and, as a dry run of `version`,
`build` and `image`, by a pull request changing the file):

| Job | Does |
| --- | --- |
| `version` | tag = `v` + both `__version__` values + the pin; pre-release box = `is_prerelease`; the tagged commit is on `main`. Fails before any build or upload |
| `test` | `uv sync --locked`, ruff and the full suite (parity included) on the tagged commit, Python 3.12 |
| `build` | `uv build --all-packages --no-sources`, `check_dists.py`, `twine check --strict` (twine 7.0.0, which reads metadata 2.5), `smoke_dists.sh`; the files as the `dists` artifact |
| `testpypi` | needs `test` and `build`; `uv publish --trusted-publishing always` to TestPyPI, environment `testpypi` |
| `testpypi-check` | `scripts/fetch_published.py`: TestPyPI's JSON API lists both files of both packages with the built SHA-256s (waits up to 10 minutes); the downloaded wheels go through `smoke_dists.sh` |
| `pypi` | releases only, not pre-releases; environment `pypi`, which requires the maintainer's approval; `uv publish` to PyPI |
| `assets` | `gh release upload` of the four files (`contents: write`), after `pypi`, or `testpypi-check` for a pre-release |
| `image`, `publish` | the image (see [Image in CI and on ghcr.io](#image-in-ci-and-on-ghcrio)), after the same jobs as `assets` |
| `deploy` | last, final releases only (not a pre-release, a merge or a pull request): asks climpact.app's deploy hook to deploy `X.Y.Z` and waits for `/healthz` to report it; environment `production` (see [Deploy on release](#deploy-on-release)) |

Uploads use `uv publish` with Trusted Publishing (OIDC), not `pypa/gh-action-pypi-publish`:
the repository's Actions settings allow only GitHub-owned actions and `astral-sh/setup-uv`.
No API token is stored. Only `testpypi` and `pypi` have `id-token: write`, each in its own
environment, so the publishers on the two indexes name different environments (both
limited to `v*` tags, see `RELEASING.md`), and only real PyPI waits for approval. Both pass
`--check-url`, so a re-run skips files an index already has. Unlike the PyPA action,
`uv publish` does not make PEP 740 attestations, so the uploads carry none (attestations
were out of #131's scope). Concurrency `release-<ref>`, never cancelled.

### Design system

The visual language and shared components (#71). The R Shiny app (`climpact/ui`,
`climpact/www/styles.css`: shinydashboard boxes, a sidebar menu, tabs as steps) is the
baseline it replaces. [`DESIGN.md`](DESIGN.md) at the repository root is the short
reference for design work and reviews: who the app is for, the tokens and components in
brief, and the rules a change must keep, with each rule not yet met marked **Target** and
the ticket that meets it. Since 17 November 2026 the targets are those of the expert
workspace direction (#230); its screens are boards on a design canvas that `DESIGN.md`
links and maps to tickets, and web tickets are built to them with the `build-to-design`
skill (`.claude/skills/build-to-design/SKILL.md`). This section describes how the system
is built. The wireframes and mockups of the earlier redesign (#171) in `docs/design/` are
kept for the record and marked superseded.

**Look.** Calm and plain: neutral surfaces, ink for actions, colour only for data and
status (#196), strong type hierarchy, generous spacing. System fonts only (`--font-sans`, `--font-mono`): no
web fonts are downloaded, for bandwidth and offline use, and every script the operating
system supports displays. Icons are a sprite drawn for this project
(`icons/icons.svg`, same licence as the package, 2px strokes on a 24px grid), inserted
with `{% icon "name" %}` (decorative, `aria-hidden`) or `{% icon "name" "Label" %}`
(announced as an image).

**Tokens.** The Tailwind theme, `@theme static` in `core/tailwind/theme.css` (#118),
emitted as CSS custom properties on `:root`: colours (`--color-*`), chart colours
(`--chart-*`), type scale (`--text-*`), the spacing step, radii, shadows, widths,
breakpoints and control heights. Where Tailwind has a namespace for a token it is also a
utility (`--color-surface` gives `bg-surface`, `text-surface`, `border-surface`;
`--text-sm` gives `text-sm`; `--radius-md` gives `rounded-md`). Tailwind's default theme
is not loaded, so these are the only colours, sizes and breakpoints there are. The values
are those of #71; #118 renamed only what Tailwind names differently:

| Before #118 | Since #118 | Utility |
| --- | --- | --- |
| `--space-1` ... `--space-16` (0.25rem steps) | `--spacing: 0.25rem`; `--spacing(N)` in the components | `p-4`, `gap-5`, `mt-12` (same values) |
| `--weight-medium`, `--weight-bold` | `--font-weight-medium`, `--font-weight-bold` (and `-normal`, `-semibold`) | `font-medium`, `font-bold` |
| `--leading`, `--leading-tight` | `--leading-normal`, `--leading-tight` | `leading-tight` |
| `--content-width`, `--prose-width` | `--container-content`, `--container-prose` | `max-w-content`, `max-w-prose` |
| (media queries in rem) | `--breakpoint-sm` 40rem, `-md` 52rem, `-lg` 60rem, `-xl` 64rem | `sm:`, `max-sm:` ... |

Components use only tokens: a test fails on a hex colour in the source outside the two
token blocks. The dark values are one `@variant dark { ... }` block in `base.css`; the
`dark` variant is defined in `climpact.css` as "the OS prefers dark and the toggle did not
choose light, or the toggle chose dark", so the built file carries the dark block twice
(`@media (prefers-color-scheme: dark) { :root:not([data-theme=light]) }` and
`:root[data-theme=dark]`), from one source. The theme toggle in the header (system, light,
dark) sets `data-theme` on `<html>` (or removes it for the system setting) and stores the
choice in `localStorage` (`climpact-theme`); a small blocking script in `<head>`
(`js/theme.js`, not inline because of the Content Security Policy) applies the stored
choice before the page paints. Before #118 the dark values were a separate
`theme-dark.css` whose `media` attribute the toggle switched. Without JavaScript the system
setting applies and the toggle stays hidden. The toggle fires `climpact:themechange` on
`document`, so charts can redraw.

**Colour roles (#196).** Before #196 one blue accent (`--color-accent`, with `-hover`,
`-soft` and `-contrast`) did every job. It is gone, and each colour has one:

| Tokens | Light | Dark | Used for |
| --- | --- | --- | --- |
| `--color-ink`, `-hover`, `-contrast` | `#111827`, `#374151`, `#ffffff` | `#e6eaef`, `#c3cad3`, `#0e1218` | primary buttons, the current tab, step and site-nav link, the running state (progress bar, spinner, current stage, running batch item and status mark), interactive icons, the selected chip, the skip link |
| `--color-link`, `-hover` | `#1f55a3`, `#173f7a` | `#8db6f2`, `#b8d0f6` | links, underlined (`a` in `base.css`; #227, ink until then) |
| `--color-brand`, `-contrast` | `#0a5aa8`, `#ffffff` | `#6db3f2`, `#08111b` | the logo's mark only |
| `--color-focus` | `#0b57d0` | `#8ab4f8` | focus rings, the targeted help heading and the tour's target |
| `--color-selected` | `#eaf2ff` | `#1c2a3d` | selected rows (QC findings and tables, with an ink edge), the targeted help topic, `::selection` |
| `--color-success`, `-warning`, `-danger` | unchanged | unchanged | the verdict and run state only. Info alerts and badges are neutral: ink icon and border on the sunken surface |
| `--color-heat`, `-cold`, `-rain`, `-drought`, `-other`, each with `-soft` | see `DESIGN.md` | see `DESIGN.md` | a theme's data |

Hovers are neutral (the sunken surface; links thicken their underline and take
`--color-link-hover`). Links became blue in #227, as on the design canvas: the values are
close to the canvas's link blue but not the same, chosen to pass 4.5:1 on every
background a link sits on (5.4:1 or more; the closest is light on the danger tint, 6.25:1). A theme's hue is
applied by a class on a block, `hue-heat`, `hue-cold`, `hue-rain`, `hue-drought` or
`hue-other` (`results.css`), which sets `--hue` and `--hue-soft` for what is inside it:
`hue-dot`, the pill (`badge--hue`), the sparkline
(`.spark__line` falls back to the neutral outside a hue block) and the index page's
theme pill, chart line, open points and running mean (`index-page.css`; the running mean
is the hue mixed towards the text colour with `color-mix`, #237). `stations.themes.hue_of` maps a theme to its hue: Heat, Cold, Rain and Drought their
own, the "Also measured" themes (Averages, Growing season and degree days, Your own index)
and the cards in no theme the neutral. `Card.hue` and `ThemeResult.hue` give it to the
templates: the filter rail's themes (`filter-pill hue-*`, #236), the Indices' rows
(`<tr class="hue-*">`, with a dot before the code), the detail pane (`index-detail hue-*`:
its chart line) and the index page's chart and statistics (`index-page__body hue-*`).
`charts.js` draws a series with the token `--hue` where a frame has one (`palette(el)`
reads it from the frame's computed style at each draw, so the line follows the theme
toggle). The SPI and SPEI bars keep `--chart-1` and `--chart-2` (wet and dry), and the
daily and QC charts keep the variable roles (`--chart-tmax`, `-tmin`, `-prcp`). The static
PNG plots and the PDF report are unchanged.

The mockup values were provisional. Adjusted until the tests passed: Drought from
`#8a5a2b` to `#693b04` (light) and from `#d4a46e` to `#fcca93` (dark), because Heat and
Drought were ΔE 2.4 apart under protan and deutan simulation in both themes; Cold
`#1d6fd6` to `#196cd3` and Rain `#0f7f71` to `#077c6e` (light), to reach 4.5:1 on their
tints; and the neutral, which the mockups did not give a value, `#222a36` (light) and
`#828c97` (dark), because a mid grey falls on Rain's teal under deuteranopia. The light
status colours are #71's, not the mockups' slightly different ones.

**Contrast.** `tests/test_design_tokens.py` reads the token values from the theme and the dark block
and computes WCAG 2.1 contrast ratios for every pairing the components use, in both
themes: text, muted text, ink, links and their hover (on the surfaces, the selection
and the status tints, #227) and status text on each surface and on each tinted
background, including the theme tints and the selection (4.5:1), button labels on their
fills (4.5:1), each theme hue as text on the surface and on its tint (4.5:1), and input
borders, focus rings, the brand mark, status icons, theme hues and chart line roles
against their backgrounds (3:1, WCAG 1.4.11). All pass; the closest are light Cold and
Rain on their tints (4.52:1 and 4.54:1, needs 4.5), the dark neutral on its tint (4.64:1)
and light input borders on the sunken surface (3.43:1, needs 3). The trend scale (#227)
is checked as its cells use it: `--color-surface` on the strong steps and `--color-text`
on the weak ones at 4.5:1 (the closest, white on light `--chart-increase-2`, 5.42:1); the
strong step at least 2 contrast units further from the surface than the weak one, darker
in light and brighter in dark; the coverage steps in order away from the surface, the
last at least 3:1; and the four trend steps apart under protan and deutan simulation
(ΔE 8).

**Colour vision.** `test_design_tokens.py` also simulates protanopia and deuteranopia
(Machado, Oliveira and Fernandes 2009, full severity) and measures OKLab distance (ΔE
x100), with the data-viz validator's thresholds. The five theme hues are compared pair by
pair, since tiles, chips and dots sit side by side: worst ΔE 10.1 light and 9.2 dark
(target 8), normal-vision floor 16.4 light and 15.3 dark (floor 15). The chart palette's
categorical slots are compared neighbour by neighbour (target 8, normal floor 15: worst 9.1
light, 8.4 dark; normal 19.6 and 19.3) and the variable roles as a set (floor 6, since
they always have a legend: 8.6 light, 6.5 dark).

**Chart palette.** For #75 (and the static plots of #74, #79):

| Tokens | Use |
| --- | --- |
| `--chart-1` ... `--chart-8` | categorical series, assigned in this order and never cycled |
| `--chart-tmax`, `--chart-tmin`, `--chart-prcp` | the variables: red, blue, teal |
| `--chart-trend`, `--chart-trend-band` | trend line (ink, dashed) and its confidence band |
| `--chart-flag` | QC flags: hollow ring markers in ink, told apart from series by shape |
| `--chart-grid`, `--chart-axis` | gridlines and axes |
| `--map-seq-<kind>-1` ... `-8` | the gridded map's eight bins (#295), by the index's kind: `temp` (blue through pale yellow to red), `warm`, `cool`, `wet`, `dry`; they replaced the five-step `--chart-seq-*` |
| `--map-div-temp-1` ... `-8`, `--map-div-wet-1` ... `-8` | the gridded map's diverging scales (#296): eight bins symmetric about zero, blue to red (`temp`) and brown to teal (`wet`), paler towards zero in light and darker towards it in dark; Anomaly and Trend, and SPI and SPEI's classes; reversed for the indices where more means cooler or drier |
| `--chart-div-1` ... `-7` | diverging, blue to red through grey, e.g. anomalies (until #296 also the gridded map's SPI and SPEI classes) |
| `--chart-decrease-2`, `-decrease-1`, `-increase-1`, `-increase-2` | the trend scale (#227): a significant decrease (blue) or increase (orange), weak and strong, for the trend grid (#238); the strong step is darker in light, brighter in dark |
| `--chart-coverage-1` ... `-3` | coverage (#227): a year complete, 1–3 days missing, 4 or more, for Quality's coverage strip (#235) |

The gridded map's scales (#295) were designed in OKLCH and are checked as the variable
roles are (`test_design_tokens.py::test_map_scales_stand_apart`): every bin apart from
`--color-surface-sunken`, the colour of a cell with no value, by ΔE 8 or more under protan
and deutan simulation (worst: light `cool` 8.1; dark `warm` 15.2), neighbouring bins by
the floor of 6, since the legend labels each bin (worst: light `warm` 6.4, dark `wet`
6.5), and the four count scales moving away from the sunken surface in contrast, bin by
bin: darker towards more in light, brighter in dark. `temp` runs from blue through pale
yellow to red in both themes. The diverging scales (#296,
`test_map_diverging_scales_stand_apart`) are checked the same way, with the neighbours
across zero: apart from the sunken surface by ΔE 11.5 or more (light `wet`), neighbours
by 7.7 or more (dark `wet`); each half moves away from the sunken surface from zero out;
and the Trend view's dot (`--color-text` or `--color-surface`, whichever contrasts more
with the bin) is at least 4.2:1 on every bin.

The categorical order was checked with a colour-vision-deficiency validator (OKLab
distance under protan, deutan and tritan simulation) against the light surface
(`#ffffff`) and the dark surface (`#151c24`): worst adjacent pair ΔE 9.1 light, 8.4 dark
(target 8), normal-vision floor 19.6 and 19.3 (floor 15). `tmax`, `tmin` and `prcp`
were checked as a set with every pair compared: they pass in light; in dark the
`prcp`-`tmax` pair is ΔE 6.5, inside the band that is acceptable with labels, and the two
rarely share a chart. In the light theme categorical slots 3, 4 and 5 are below 3:1 on
white (2.2-2.8:1), so charts that use them must label series directly or offer the table
view, which every chart frame has. Since #196 the same checks run in the test suite, in
Python (see "Colour vision" above). `chart-palette.json` carries the same
colours for both themes (`trend_scale` and `coverage` since #227), for code that cannot read CSS; it is generated with
`uv run python -m climpact_web.core.tokens` and a test fails when it is out of date.
In the browser `Climpact.chartPalette()` returns the live values for the current theme.

**Components.** Template includes in `core/templates/components/`; each file starts with
a comment listing its parameters. Labels are passed in already translated
(`{% translate "Start" as label %}{% include "components/button.html" with label=label %}`).

| Component | Notes |
| --- | --- |
| `button` | primary, secondary, ghost, danger; `lg`, `sm`, icon only, `full_width`, `busy` (spinner, `aria-busy`), link when `href` is given; disabled links render as disabled buttons; `form_id` (a submit button outside its form) and `describedby` (`aria-describedby`) |
| `field`, `field_errors`, `form_errors` | label, hint, inline error with an icon, unit suffix; no help link of its own (#177: the section's Help button has the help, and the hint is kept for values that need one); radio groups as a fieldset; the error summary links to each field and takes focus. Hint and error ids are Django's (`<id>_helptext`, `<id>_error`), which Django puts in the widget's `aria-describedby` with `aria-invalid` |
| `dropzone` | a label around a real, visible file input; `ui.js` hides the input visually, adds drag and drop and shows the file name |
| `file_button` | a form with a label, a file input and a submit button (#174); `ui.js` makes the label the button (`data-class`), hides the input and the submit button, and sends the form when a file is chosen. The page says near it what choosing a file does, in the hint the input is described by (`<id>_helptext`). No page uses it since #199 (Quality's "Upload a corrected file" became "Replace file", the File sheet); it stays on `/patterns/` |
| `alert`, `messages`, `toasts` | info, success, warning, error, each with its own icon; dismissible; Django messages render as alerts; toasts via `Climpact.toast()` or an `HX-Trigger: {"toast": {...}}` response header; error toasts stay until dismissed |
| `card`, `badge`, `stat`, `summary_list` | cards can be one link (the title's link covers the card); badges always carry text; a stat without a note keeps its value on the same line as its neighbours' |
| `table` | the data table (#227, `table-wrap--data`, `table--data`): one frame (`border`, `--radius-sm`) on the surface, rows 32px high and one line each, a sticky header on the sunken tint over a `border-strong` rule; caption, `numeric` columns at the end and `code` columns, both mono with tabular figures; `selected` marks a row `aria-current="true"` (selected tint, ink edge on its first cell); a focusable scrolling region for wide tables, empty text. Page tables still use the plain `.table` until their tickets move them |
| `context_bar` | the context bar (#227) under the header on a station's pages, drawn by `stations/_workspace.html` (see [A station's pages](#a-stations-pages)): an optional breadcrumb with the previous and next item (`breadcrumb`, `step_previous`, `step_next`: an index's page passes the station / Indices and the previous and next index, `{code, name}` named codes first, #237; a station's pages in a workspace of several stations the workspace / "Station 2 of 6" and the previous and next station, `workspace.station_nav`, #234; the workspace's own pages draw it through `stations/_space_bar.html`), the title (`heading` makes it the h1; `title_template` a title of its own, an index's h1 and theme pill), `lead_template` (a line under it, an index's definition), the provenance line (`provenance`: `{text, phone}` parts, mono with tabular figures), the page's `actions` and the phone's ⋯ menu, the tabs (`workspace_tabs`), and `below` (the Inputs bar). `flow` keeps it across the window but in the page's flow, not sticky (an index's page, which has no tabs); `static` shows it in place, not sticky, for `/patterns/` |
| `tabs` | links to panels without JS (all panels show); `ui.js` makes an ARIA tablist (arrow keys mirrored for right-to-left, Home, End) |
| `workspace_tabs` | a station's sections, Quality, Indices and Files (#179; Data until #198, Results until #236), from `stations.workspace.sections`: links in a `nav` named "Station sections", the current one `aria-current="page"` (not an ARIA tablist: each tab is its own page, and Tab moves between them), with the `tabs` component's look (`.tabs__list`, `.tabs__tab`). Each has a status mark (`status-dot--<state>`): an icon of its own shape (`check-circle`, `warning`, `clock`, `refresh`, `circle`, `lock`) and a word, shown for "Needs attention", "Out of date", "Running" and "Checking…", screen-reader only for the others. Indices' tab says "No indices" (`warning`, in the warning colour, the word shown; state `empty`) instead of the green Done when the run shown made no index table (`workspace.made_no_indices`, #298). Quality's tab shows the checks' verdict instead of "Done" (#222): "Ready" (`check-circle`), "Usable" (`warning`) or "Fix first" (`error`), the verdict band's icons, as a small pill in the verdict's status colour on its soft tint, followed by the count of values that look wrong ("Usable · 21"; `Section.count`, grouped by `numbers.grouped`, none when nothing looks wrong). The count is `aria-hidden` and read as ", 21 values look wrong" (`Section.count_label`). Under 40rem the pill is its icon alone (`max-sm:sr-only` on the word, `max-sm:hidden` on the count), so the three tabs stay on one line at 320px. A section not available yet is a `span`, not a link. The section pages' h1 is the station's name (`stations/_workspace.html`), their `<title>` the section's |
| `stale_banner` | results kept on the page after an input changed (#179): an `alert` (info with the new run's progress inside while it is on the way, warning with one action otherwise) saying what changed; the results below sit in `.stale-content` (a dashed warning edge, sparklines greyed, text at full contrast so the contrast checks still hold) |
| `progress`, `stages` | native `<progress>` (indeterminate when no value), a politely announced note, and the list of job stages (done, current, pending, failed) for #73 |
| `skeleton`, `empty_state`, `disclosure` | loading placeholder (`aria-busy`), empty state with an action (a link, or an Inputs sheet with `action_sheet`; its title an h3, or `level`), a `<details>` that opens in place (the help topics of #81 build on it; see [Help](#help)) |
| `dialog` | native `<dialog>` opened by `data-dialog-open`; cancel and close use `method="dialog"` |
| Inputs panel | (#198, `components/inputs.css`, `stations/_inputs.html`) an `aside` named "Your inputs": a `dl` of rows (`inputs-panel__item`: muted name, semibold value, one link at the end), on `--color-surface-sunken`; a changed row has `--color-warning-soft` and the word; runs beneath in `runbox progress` boxes. Beside the content (16rem) when `.station-page`, a container, is at least 52rem wide, sticky under the workspace header; otherwise the Inputs bar takes its place, and without JavaScript the panel is above the content |
| Inputs bar | (#203, `inputs-bar` in `components/workspace.css`, `stations/_inputs_bar.html`) the panel in one line under the workspace tabs: "Inputs:", the base period and "defaults" or the settings not the default, each changed input in `--color-warning` (and the bar on `--color-warning-soft`), each run under way, and a small secondary Edit that opens the Inputs sheet. Full width under a hairline on phones. Shown on `/patterns/` (`pattern__phone`) |
| Page menu | (#203, `page-menu` in `components/workspace.css`) the ⋯ `<details>` at the end of the phone header's name line, its summary an icon button (`more`, "Page actions" for screen readers), its panel raised at the inline end with the page's actions one a line. Shown on `/patterns/` |
| Side sheet | (#198, `sheet`, `js/sheet.js`) a modal `<dialog>` at the inline end, full height, at most 26rem wide: header with the title and a close button, the form's body (`sheet__body`), an `impact` note in the warning tint saying what applying updates, and a foot (`sheet__foot`) with Apply and Cancel. Its `.sheet__panel` fills the dialog, so a click on the dialog itself is on the backdrop. The body scrolls and the foot stays, so a long form (the index settings, #199, in `settings-group`s under rules) keeps Apply in view. Any link opens a sheet with `components/button.html`'s `sheet` or `data-sheet-open`. Shown on `/patterns/` with the panel, the base period's sheet and the index settings' |
| `drawer` | the help drawer (#177, decision E): one `<aside id="help-drawer">` per page, in `base.html` after `<main>` (a top-level complementary landmark), hidden until a section's Help button opens it. Not modal: no backdrop and no focus trap. From 64rem it is a sticky column beside the content (`drawer-layout--open` on the grid that holds `<main>` and the drawer), below that it follows the content. `js/drawer.js` copies the button's `<template>` into it and focuses its title; Escape or the close button closes it and focus goes back to the button, unless focus has moved on to the page. See [Help](#help) |
| Section header | (#197) `<div class="section-header">`: the section's heading, an optional `section-header__note` (muted, small), then `{% section_help %}`'s Help pill (`help-button`: a 30px pill with a ringed question mark and a word, `margin-inline-start: auto`, so it ends the row on every section). The word is "Help" or the `label=` given ("What do the levels mean?" on the Quality verdict); `quiet=True` makes it a quiet link ("How the checks work" on Quality, "How to read the table" in the Indices' rail); the accessible name is the label, a colon and the section's title. The header's Help (`#app-help`, `base.html`; a pill until #227, now a quiet link) leads to the page's guide (`navigation.page_help`, `PAGE_GUIDES` by URL name or namespace; the help's index elsewhere, `aria-current="page"` on the help pages); Help is not among the header links (`Destination("help", in_nav=False)`) |
| One surface level | (#197, `components/workspace.css`) a page's sections are `page-section`s on the page, separated by `stack--xl` (48px) and a section header, not cards. A box marks one object (a chart frame, a detail pane, a progress card). Tables (`table-wrap`) have no frame, except the data table (#227): hairline rows, the header row small and muted on the page's colour (the surface's inside a card, dialog, drawer or chart frame, `--table-head-bg`). A `disclosure` is a row between hairlines, not a box, and Quality's rail (`qc-rail`, #264) is framed lists of rows. The answer band (`answer-band`) went with #236: Quality's verdict is a verdict strip (#235), and the Indices answer in one line above the table. `group-label` and `stat__label` are small, uppercase and muted |
| `chart_frame` | title (an `h3`, or the level given as `heading`), text summary, legend, plot area with a skeleton until a chart draws into `[data-chart-plot]`, CSV link and table view; with `data_url` an interactive chart (#75, see [Charts](#charts)). The header is a two-column grid: the CSV button keeps its top-right slot when the summary arrives with the data (#115) |
| `segmented` | (#237, `components/index-page.css`) one choice of two or three as links in one strip, the current one (`aria-current`) ink: the index page's Values / Anomaly and Annual / Monthly |
| `index_name` | an index named codes first (#218): the code in mono (`index-code`, without the code background), then the short name; `title` for a page heading, the name a step lighter. Used by the index page's heading and previous/next links, Files' index table and the sector correlation table; the Indices' table sets code and name in two columns |
| `spark` | a decorative sparkline beside a trend given in words (#78): the series and its Sen's slope as SVG paths in a 240 x 60 box, its theme's hue (#196). The theme tiles that used it (`theme_headline`, #175, #200) went with #236 |
| `theme_toggle` | see Tokens |

**Navigation before the screens exist.** `core/navigation.py` lists the destinations
(workspaces, single station, sample data, batch, gridded and help) with the URL name each
later ticket adds (`stations:add` since #233, `stations:new` and `stations:upload`
before; `stations:add_sample`, `gridded:start` (#85), `help:index` (#81) and `jobs:list`
all exist now). Until a URL exists, the landing page shows that action disabled or
"Available soon" and the header leaves it out. Gridded is offered when `GRIDDED_ENABLED` is
set: always in local mode, as in R, and in hosted mode only with
`CLIMPACT_WEB_GRIDDED_HOSTED`. The batch and gridded step URLs are named in `BATCH_STEPS`
and `GRIDDED_STEPS` for the same reason. "Try with sample data" is a one-button POST form, since it creates the session's
analysis.

**The app shell (#227).** The header is one row across the window, about 48px high (it
was in the 72rem column, 69px): the logo and "Climpact" (to the landing page), the header
links, then Index reference, Help and the theme toggle at the end. The header links are
only Workspaces and Gridded (`in_nav`); Single station, Batch and Your calculations went,
and the landing page leads to Get started (Add stations). Workspaces opens the Workspaces
page (`stations:workspaces`, `/w/`, #242); it is `aria-current="page"` there and `aria-current="true"`
on Add stations and every `/w/` page (`Destination.sections`, URL names or
paths, `nav_items`), drawn in ink
with an underline. Index reference (`navigation.index_reference_url`) leads to the
definitions in the guide to the indices (`/help/indices/#the-indices`) until a reference
page of its own exists (`help:index_reference`, #319). Help (`#app-help`) keeps its destination (the page's guide) but is
a quiet underlined link like Index reference, no longer the ringed pill, as on the canvas.
Help is `aria-current="page"` on the help's pages, except on `/help/indices/` and the
pages under it, where Index reference is current instead (`"page"` there, `"true"` under
it; `navigation.index_reference_current`, #325).
The landing page's tour points at Workspaces (`data-nav='workspaces'`).

**The header stays in view (#284).** In a window at least 30rem high the header is
sticky at the top of every page (`.site-header`, `components/header.css`, `z-index` 25:
above popovers, below toasts and the tour; the skip link is 30, so it shows over it). It
sets `--site-header-height` on the root: `js/site-header.js` (deferred, every page)
measures the header's height with a `ResizeObserver` into `--site-header-measured`, and
the CSS falls back to one row, `3rem + 1px` (49px), or two between 600px and 52rem, where
the links wrap under the brand (89px), which are the heights without JavaScript (no theme
toggle then; 51px and 91px with it). In a shorter window it is 0 and nothing sticks. The
root's `scroll-padding-block-start` is that height plus 1rem, so focus and a `#fragment`
clear the header on every page. `--frame-height` is the header plus the context bar
(`--context-bar-height`): what the context bar's pages keep their sticky parts under (see
[A station's pages](#a-stations-pages)). The help drawer and the guide's table of
contents stick under the header too.

**Header on phones (#115).** Below 600px (37.5rem) the header's links are hidden and a
"Menu" `<details class="site-menu">` after the theme toggle holds the same links and,
since #227, Index reference (`base.html`), and since #203 the theme toggle too (a second `theme_toggle.html` in the
menu's panel, `site-menu__theme`; the header's own is hidden there, `ui.js` keeps both in
step), so "Climpact" is no longer cut off beside the toggle at 375px. The header stays one row (69px at 390px, was 153px) and the menu works
without JavaScript. Its panel drops over the page below the header. The row does not wrap
(`flex-wrap: nowrap`, the brand may shrink), and below 23rem the brand shows its mark only
and the button its icon only, with "Climpact" and "Menu" kept as their accessible names, so
the row fits at 320px whatever the system's fonts (CI's Linux fonts are wider than macOS's;
`test_accessibility.py` also checks the row with a wide font).

**Number and date formats (#115).** Counts are shown with the thousands grouped in the
interface language (`29,220` in English) everywhere: the `count` template filter
(`core/templatetags/ui.py`, `number_format(..., force_grouping=True)`) on the load
summary, the QC tables and plots, the index pages and the gridded checks, as the chart
summaries already did. Dates of data are ISO (`1936-01-01`) everywhere, as the station
files, the tables and R's outputs: the chart summaries (`charts/data.py`) and the charts'
read-out and announcements (`charts.js`). Dates of the app's own events (when results are
deleted, when a job started) stay written out ("14 November 2026"). The output files are
not affected.

**The number rules (#226).** Every other number a page shows is written by
`core/numbers.py`, the one formatting module (the rules are in `DESIGN.md`, Typography):
U+2212 for minus (`numbers.minus`, also in the index names and definitions that hold a
number, `numbers.in_text`: "TN below −2 °C"), and never "−0.0"; slopes signed and per
decade with their units (`numbers.per_decade`: "+0.21 °C/decade", "+1.31 pp/decade");
slopes and 95% intervals to two places in °C, days, % and the unitless indices, one in
mm and degree-days (`numbers.slope_decimals`), rounded half up from the value as written
(`Decimal(repr(value))`, so the trend file's 0.03125 shows as 0.0313, as `floatformat`
did); intervals as "−0.22 to 0.31" (`numbers.interval`); anomalies to one place with a
sign (`numbers.anomaly`; the standardised anomalies chart's payload has
`signed_digits: 1`, which `charts.js` and the summary follow); coordinates as "33.86° S
151.21° E" (`numbers.coordinates`, the Inputs panel); counts grouped,
"65,720" (`numbers.grouped`, the Quality tab's count, #222); a no-break
space between a value and its unit. The Quality tables keep the file's own precision
(`numbers.file_value`) with U+2212, except the days around a value, which have one
decimal (`numbers.fixed`, #235), and what the screen works out (a month's limit and usual
range, over and beyond by, TN − TX), one decimal, signed where the sign says something
(`numbers.signed`, #264). Server-drawn charts (`stations/qc_plots.py`,
`sector_plots.py`, `preview.py`) and `charts.js` (its y-axis ticks, read-out and table
view) write minus the same way. Templates use the `decimals` and `coordinates` filters
of `{% load ui %}`. Text the user types and the downloads keep the hyphen-minus: a CSV is
written as the files are (Quality's flagged values CSV too, #235), and the help still
says to write `-99.9` for a missing value.

**Pages.** The landing page (`/`, #242) is described in [Landing page and
Workspaces](#landing-page-and-workspaces).
The pattern library (`/patterns/`, with `PATTERN_LIBRARY`) shows every component, the
palette and the icons, and is what the user review and the accessibility audit (#83) use.

**Responsive and right-to-left.** Layouts use flex and grid with `auto-fill` columns, so
they reflow down to 320px wide and at 200% zoom without horizontal scrolling (every page
type is checked by `test_accessibility.py`, see [Accessibility](#accessibility)); wide
tables scroll inside their own region. Grids that hold forms and charts use a
`minmax(0, 1fr)` column, so content such as a drawn chart cannot hold them wider than the
window, and headings break long words (station names). Only logical properties are used: a test fails on
`left`, `right`, `top`, `bottom`, `width` or `height` properties in the stylesheet source,
and on inline-axis utilities that do not flip in templates (`pl-`, `mr-`, `left-`,
`text-right` ...; `ps-`, `me-`, `start-`, `text-end` instead).
Motion is reduced under `prefers-reduced-motion`; borders are drawn in system colours
under `forced-colors`.

**Size.** Since #118 every page loads one stylesheet, `css/climpact.css`: 61.9 KB minified,
11.3 KB gzipped, with every page's components (before, a page loaded `main.css`, 5.8 KB
gzipped, `help.css`, 1.6 KB, the dark theme when it applied, and its own page
stylesheets). Tests hold it under 98 KB (95.5 KB until #235 added the verdict and coverage strips and Quality's worklist; 95 KB until #222; 91 KB until #227 added the link and chart tokens, the app
shell, the context bar and the data table; 86 KB until #203 added the phone layout; 81 KB until #201 added the New station page;
77 KB until #198 added the Inputs panel and the side sheet; 74 KB until #197 added the section header, one
surface level and the sticky workspace header; 71 KB until #196 added the colour roles, the theme hues and
the pattern library's interface swatches; 70 KB until #179 added the workspace tabs'
status marks and the out-of-date block; 83 KB until #202 added Quality's list and
detail; it is 97.4 KB) and 17.5 KB gzipped (16.7 KB; 17 KB until #235; 16.25 KB until #227; 15.5 KB until #203; 15 KB until #202; 14.75
KB until #201; 14 KB until #198; 13.5 KB until #197; 13 KB until #196; 12.5 KB until #177 added the drawer). `ui.js` is about
14.5 KB, held under 14.5 KB (12 KB until #83 added the announcer and focus keeping,
14 KB until #174 added the file button; the New station page's behaviour is its own
`setup.js`, 1.4 KB, so `ui.js` did not grow);
`tour.js` (about 6.5 KB) loads on the landing page only, held under 8 KB. Whole-page
budgets are in [Size budget](#size-budget) (#82).

### Stylesheet and Tailwind

Since #118 the stylesheet is written for Tailwind CSS v4 and built by its standalone CLI.

**The CLI.** One executable, Tailwind CSS v4.3.3, from the official
`tailwindlabs/tailwindcss` GitHub release; no npm, no `node_modules`, no Python wrapper,
nothing installed globally. `scripts/fetch-tailwind.sh` downloads it for the platform
(macOS arm64 or x64, Linux x64 or arm64) into `bin/tailwindcss` (git-ignored) and installs
it only if its SHA-256 matches the hash pinned in the script, copied from the release's
`sha256sums.txt` (Tailwind publishes no artifact attestations, so the pin is the integrity
control). The user reviewed and approved this method on 2026-11-14 (#118); v4.3.4 and
v4.3.5 were then under two weeks old and were skipped. Upgrade only in a pull request that
changes the version and every hash together.

**Build.** `scripts/build-css.sh` runs `bin/tailwindcss --input climpact.css --output
../static/climpact_web/css/climpact.css --minify` in `core/tailwind/`;
`scripts/build-css.sh --watch` rebuilds on every change to a template, script or source
file while developing. Run it beside `CLIMPACT_WEB_DEBUG=true uv run climpact-web`: with
`DEBUG` nothing is collected and WhiteNoise rereads the files, so each rebuild shows on the
next page load (without `DEBUG`, `climpact-web` collects the static files when it starts,
so a rebuild shows after a restart). The built file is committed,
so `pip`/`uv` installs, the `core` CI job and the containers need no Tailwind; the `web`
CI job fetches the pinned CLI, rebuilds and fails if the committed file differs, and
`test_design_tokens.py::test_compiled_css_is_up_to_date` does the same locally when
`bin/tailwindcss` exists (skipped otherwise, required in CI with
`CLIMPACT_REQUIRE_TAILWIND`).

**Layers.** `climpact.css` declares `@layer theme, base, vendor, components, utilities`:
the tokens (`theme.css`); dark token values and element styles (`base.css`); uPlot's own
stylesheet (`vendor/uplot/uPlot.min.css`, imported, so chart pages no longer link it and
the chart styles can restyle its overlays from a higher layer); the components
(`components/*.css`); Tailwind's utilities, generated only for the class names found in the
templates and scripts (`@source`). Tailwind's Preflight reset is not used: the base styles
were written as the reset, and Preflight would strip list bullets, make the inline SVG
icons block-level and restyle form controls, which the "same look" aim of #118 ruled out.

**Components and utilities.** What is repeated, or written by Python, JavaScript or
Markdown, is a component class in `@layer components` (BEM names as before: the header and
menu, buttons, form fields, alerts, progress and stages, cards and badges,
tables, tabs, disclosures, chart frame, dialog; the file problems and field sets shared by
the station, batch and gridded pages; batch items, index cards, sparklines, the help
article and the tour; the SVG plots' classes written in `qc_plots.py`, `sector_plots.py`
and `maps.py`). One-off layout is written with utilities in the templates (`flex flex-wrap
items-center gap-3`, `grid gap-5 grid-cols-fill-64`, `text-sm text-text-muted`, `sr-only`,
`max-w-prose`, `print:hidden`). Two custom utilities, `grid-cols-fill-N` and
`grid-cols-fit-N`, make wrapping grids with columns of at least N spacing steps
(`repeat(auto-fill | auto-fit, minmax(min(100%, N * 0.25rem), 1fr))`). Components are
plain CSS, emitted whether or not a scanned file names them, so classes built at run time
(`batch-item--{{ status }}`, `ramp-{{ kind }}`) must be component classes, written out in full in a
template or script, or listed with `@source inline()`. Words in the templates that would
make unwanted utilities (`table`, `container`, `ring` ...) are excluded with `@source not
inline()`. `test_static.py::test_every_template_class_is_styled` fails when a template
names a class that is neither generated nor a component (apart from a short list of
script and test hooks), so a mistyped utility, or one in a file Tailwind does not scan,
fails in CI.

**Visual parity.** The migration aimed at the same look, not a redesign: screenshots of
every main page (station steps, results, an index, downloads, sector, batch, gridded,
help, jobs, the pattern library; desktop and phone, light and dark) before and after are
in the pull request (see its notes for the differences found).

**Review snapshots.** `climpact-web manage design_snapshots <folder>` saves the landing
page, pattern library, 404 page, the job pages (a running, a finished and a failed
job and the job list), a station's setup page (#201: the sample's file read, with a new
file's problems, details errors; the empty New station page and the batch pages went with
#271), Quality before the checks have run, the indices being calculated (#178), and the help
pages (index, a guide, the indices guide, the topic list, a search), rendered from
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
`uv run climpact-web manage makemessages -l en --no-obsolete`. A pull request that adds,
changes or removes a user-facing string refreshes it. `tests/test_catalogue.py` (#205)
keeps it current: it copies the package to a temporary folder, runs `makemessages -l en
--no-obsolete` there and fails if the regenerated `django.po` has a message (context,
`msgid`, `msgid_plural`) that the committed one lacks, or the other way round, listing them
and the command. It compares the set of messages, not the file, so the `#:` location
comments (which move whenever code above a string changes), the `POT-Creation-Date` header
and gettext versions' line wrapping do not fail it; locations may lag until the next
refresh. Keep `\u` escapes out of Python messages: Ubuntu 24.04's xgettext 0.21 keeps
`\u00a0` as written, newer versions decode it, so the two catalogues differ (and the 0.21
one never matches at run time). `core/numbers.py` joins every value and its units with a
no-break space outside the messages for this reason (#226), and
`tests/test_numbers.py` checks that no msgid holds one. Without GNU gettext (`xgettext`, `msgmerge`, `msguniq`, `msgattrib`) it skips,
unless `CLIMPACT_REQUIRE_GETTEXT` is set (CI), when it fails. To add a
language, add it to `LANGUAGES` in `settings.py`, run `makemessages -l <code>`, translate
the `.po` file and run `compilemessages`. The help guides are translated as Markdown files, one folder per
language, with English as the fallback (see [Help](#help)).

### Tests

pytest-django with `web_test_settings` (set in `pytest.ini` and the package's
`pyproject.toml`; the tests folder is put on the path by `pythonpath`). The settings clear
every `CLIMPACT_WEB_*` variable and `DATABASE_URL`, and point the data folder at a
temporary folder, so tests never touch the user's data; the database is SQLite in memory.
`test_settings.py` loads `settings.py` afresh under different environments (local
defaults, hosted with a Postgres `DATABASE_URL`, each required hosted variable missing).
`test_cli.py::test_serves_local_mode` starts `python -m climpact_web --no-browser --port 0`
on a fresh data folder, fetches `/healthz`, `/` (gzipped when asked) and the collected,
hashed `climpact.css` (Brotli, immutable cache) and its plain name, and stops it with SIGTERM. Postgres is not installed on the development machine; CI's `web-postgres` job
runs hosted mode against a Postgres 16 service container: `check --deploy`, `migrate`,
`collectstatic` and `/healthz`, then queues a station job (Madrid) and runs it with
`runworker --once`, which claims it with `SELECT ... FOR UPDATE SKIP LOCKED`.
`test_worker_process.py` runs the worker as a real process on a SQLite file: killed with
SIGKILL in the middle of a station run, the job is failed by `purgejobs` once the heartbeat
is stale, and after a retry a new worker runs it to the end; stopped with SIGTERM, the job
is queued again. `test_cli.py` checks that `climpact-web` starts a worker and stops it. `test_cli.py::test_proxy_options` and
`test_proxy_headers_reach_django` check the waitress options for a trusted proxy and that
`X-Forwarded-Proto` then becomes the request's scheme. The image itself is built and
smoke-tested in CI's `image` job against Postgres too (see
[Image in CI and on ghcr.io](#image-in-ci-and-on-ghcrio)).
`test_queue_postgres.py` (#119) runs only when `DATABASE_URL` is a Postgres URL (the test
settings drop it for their own in-memory SQLite database and keep it as
`CLIMPACT_TEST_POSTGRES_URL`), so it skips locally and runs in `web-postgres`, where
`CLIMPACT_TEST_POSTGRES_REQUIRED=1` makes a missing URL fail instead. It creates a database
of its own on that server, migrates it, and drops it at the end. Four worker processes
(`JobWorker` with a test job kind, each with its own connection; heartbeat 0.3 s, stale
after 1.5 s, poll 0.05 s) wait until all are registered, then 40 jobs are queued. Each job
must succeed with `attempts` 1, leave exactly one marker file (written by the runner, named
after the job and the process) from the process of the worker recorded on the row, and more
than one worker must have taken jobs. Then the worker running a long job is killed with
SIGKILL: the surviving workers' `reap_stale` fails it ("no heartbeat" in the log, not
before the stale time), a retry runs it on another worker (`attempts` 2, one marker per
attempt), and 8 more jobs queued meanwhile run once each. The survivors stop cleanly on
SIGTERM. A second test runs the workspace migration (#231) back and forward on its own
Postgres database (`migration_workspaces.py`, which `test_workspace.py` also runs on
SQLite).

### Background jobs

Calculations never run in a web request: a view queues a **job** and a **worker** process
runs it, reporting progress through the core's callbacks (#72, see
[Progress reporting](#progress-reporting)).

**Choice of backend (#73).** The queue is the database: a `Job` table and a worker that
polls it (`climpact-web manage runworker`). The development machine may not install
system services, and the local install should not need any, so Redis (RQ, Celery) was
ruled out (issue comment of 2026-11-14). Django's tasks framework (new in Django 6.0) ships
no production backend, only immediate and dummy ones, and was not in Django 5.2 when this
was decided. The
`django-tasks` package's database backend was considered, but the progress pages need
stage progress, heartbeats and cancel requests on the job row anyway, so it would add a
dependency without removing much code; the worker is about 400 lines in `jobs/worker.py`.
It works the same on SQLite (local) and Postgres (hosted).

**Job queue: the database, not Redis (#119).** Asked again whether background jobs should
move to Redis, the decision is to keep the database queue and add no Redis (RQ, Celery):

- *Local mode* is a desktop-style app: `climpact-web` starts the server and its worker
  with no other service. Redis would be a second program every user installs and runs.
- *The workload* is few, long jobs (seconds to many minutes of CPU per station, batch or
  gridded run). Redis helps with thousands of short jobs a second; here a claim takes
  milliseconds in the database.
- *The queue already has what Redis would add*: atomic claims (`SELECT ... FOR UPDATE
  SKIP LOCKED` on Postgres, `claim()` in `jobs/worker.py`), heartbeats and stale-job
  recovery, cancellation, progress and retention. RQ or Celery would need these rebuilt
  or bolted on, plus a results store, which would still be the database.
- *Hosting*: hosted mode already needs Postgres; Redis would be one more managed service
  to run and secure. Hosted deployment sizes Postgres, not Redis.

`test_queue_postgres.py` backs this for hosted mode: several worker processes on Postgres,
every job run exactly once, none claimed twice, and a killed worker's job recovered by the
stale-heartbeat reaper (see [Tests](#tests)). Revisit if hosted mode needs many workers on
several machines and the claim query becomes a bottleneck, or if Django's tasks framework
(`django.tasks`, Django 6) gains a mature production backend with progress reporting and
cancellation. Django ships none, and the `django-tasks` package's database backend has
neither feature today, so switching would lose what the progress pages rely on.

**The `Job` model** (`jobs/models.py`): a UUID primary key (unguessable URLs); `kind` (the
runner); `owner` (a random token kept in the browser session, `jobs_owner`: only that
session sees the job; a token rather than the session key, so rotating the session key
does not orphan jobs); `params` (JSON); `title`; `status` (`queued`, `running`,
`succeeded`, `failed`, `cancelled`); `stage`, `step`, `total` (the last progress callback;
`percent` from them); `created_at`, `started_at`, `finished_at`, `heartbeat_at`; `worker`;
`attempts`; `cancel_requested`; `client` (hosted mode: the client address that started
the job, for the quotas, #125; blank in local mode); `error` (the message for the user); `log` (the operator
log: one timestamped line per attempt, the outcome, the run time, and the traceback of a
failure); `result` (JSON from the runner: files written, zip); `inputs` (#179, JSON: the
inputs a station workspace's `qc` or `station` job was made from, for staleness, see
[A station's pages](#a-stations-pages); empty for other jobs). The job's folder is
`<RUNS_DIR>/<id>/` with `input/` (uploads) and `output/` (what the core writes). The
`Worker` table lists running workers (`name`, `started_at`, `seen_at`). `JobStart` (hosted
mode) records each job started or retried (`client`, `kind`, `created_at`, and `change`:
the jobs of one change are one row, #254) for the daily quota, which counts these rather
than jobs because a user can delete jobs; a purger
deletes the rows older than two days.

**Runners** (`jobs/registry.py`, `jobs/runners.py`). `@register("kind")` maps a kind to a
function `runner(ctx: JobContext) -> dict`. The context has the params, the folders, the
progress callback and `input_file(name)` (which refuses names outside `input/`). The
built-in runners call the same core functions as the command line, so the files are the
same: `station` (`run_station`, with plots, zip and the PDF report, `report`, whose path
is the result's `report`; `qc` takes the QC thresholds, so the
QC files of a full run match Quality's), `qc` (`run_station` with no index modules and the
thresholds given: only the `qc/` files and their zip, as the R app's step 2 writes; the
runner's result also maps each output key to its file, `reports`), `batch` (`run_batch`; one progress
count for the whole batch, the sum of each station's last step over the sum of their
`pipeline_stages` + `plot_steps` (+ 1 for the report) totals; a failed station counts as done; `workers`
defaults to 1; each station's own progress goes to `output/stations.json`, see
[Batch page](#batch-page)), `sector` (`run_sector_correlation` on a station file and the index
tables of a finished `station` job, or of one station of a `batch` job; its result also
holds what the sector comparison shows: each scatter plot's file and regression, read back from its CSV
with the core's `regression`, and the correlation table's file), `gridded-thresholds` and `gridded-indices`
(`write_grid_thresholds`, `write_grid_indices`; input files are read in place from the
paths given; `max_values`, `rechunk`, `tmp_dir` (default the job's folder) and
`copy_to`, a folder the written files are also copied to; `gridded-indices` then writes
`trends.nc` with `write_grid_trends` unless `trends` is false, as its last stage,
`trends`, shown as "Trends and the map", and lists it last in the result's `files`; see
[Gridded trends](#gridded-trends); both write when each stage began to `stages.json` in
the job's folder (`StageTimes`, #294: `check` when the job starts, then each stage the
core reports as its first step comes, dated when the one before ended; the grid's
blocks, whether a cell-first copy is made and its size), for the run's stages on its Map
tab, and report the core's "rechunking the input needs … GB" (an `OSError`) as a
`JobError`, "Not enough disk space for the cell-first copy", so it is shown, not logged
as unexpected). The parameters of each are in
the module docstring. The batch page (#80) creates batch jobs, the gridded pages (#85)
the gridded ones and a station's sector comparison (#90) the sector ones. The `station` runner also takes `plot_title` (the settings' "Plot title", passed to
`run_station`). The core is imported inside each runner, so the web server never imports
xclim.

**The worker** (`jobs/worker.py`, `JobWorker`) runs one job at a time:

- *Claiming* is atomic. Where the database has `SELECT ... FOR UPDATE SKIP LOCKED`
  (Postgres), the oldest unlocked queued row is locked and marked running in one
  transaction. Elsewhere (SQLite) a conditional `UPDATE ... SET status='running' WHERE
  id=? AND status='queued'` takes a candidate; a worker whose update changes no row tries
  the next. Each claim increments `attempts`. Speculative runs (#178, `params["speculative"]`
  true) are claimed only when no other job waits: `claim` tries the ordinary jobs, oldest
  first, then the speculative ones, so a run nobody has asked for yet never holds up one
  somebody has. The worker cannot be pre-empted: a speculative run already running
  finishes (or is cancelled) first.
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
- *Time limit* (hosted mode, `JOB_TIME_LIMIT_MINUTES`, default 60, #125): past the limit
  the progress callback raises `JobTimedOut` (a `BaseException`, like `JobCancelled`) and
  the job fails with `TIME_LIMIT_MESSAGE`, retry offered. A stage that reports no progress
  can't be interrupted from Python, so once the limit plus `JOB_TIME_LIMIT_GRACE_SECONDS`
  (60) has passed, the heartbeat thread fails the job itself (`Heartbeat.hard_stop`) and
  ends the worker process with `os._exit(3)`. Docker restarts it (`restart:
  unless-stopped`), and batch pool processes end with the container's main process. No
  limit in local mode.
- *Retry* (`Job.retry`) queues a failed or cancelled job again with the same inputs and
  parameters, at the back of the queue; its output folder is emptied when it starts. In
  hosted mode it counts as a new job for the quotas.

In local mode `climpact-web` starts the worker as a **child process**
(`python -m climpact_web manage runworker --name <host>:<pid>/worker-<n>`) rather than a
thread: a crash or an out-of-memory error in a calculation does not take the web server
down, and the worker's imports (xclim, matplotlib) stay out of the server process.
Hosted mode runs `runworker` processes alongside the web servers (#12); more workers
claim different jobs. `runworker --once` runs the jobs waiting now and exits.

**Pages** (`/jobs/`). `jobs/` lists the session's jobs, except speculative runs that were
cancelled (#178: replaced after a change to the data, never asked for; their own page still
answers). Station runs are started from
the single-station steps (see [A station's pages](#a-stations-pages)), which
replaced #73's minimal form at `jobs/station/new`; the station file is copied into the
job as `input/station.txt`, never under a name from the browser.
`jobs/<id>/` is the job page; `jobs/<id>/progress` the progress fragment;
`jobs/<id>/cancel` and `jobs/<id>/retry` (POST; a `next` field naming a URL of the site
returns there instead of the job page, as the Indices' progress does); `jobs/<id>/files/<path>` downloads an
output file of a finished job (paths outside `output/` give 404). Any other session gets
404, as for a job that does not exist. The templates use the design system's components
(see [Design system](#design-system)): a status badge (`jobs/_status.html`), the progress
bar and note, alerts for failure, cancellation and a missing worker, the zip download
button and the file list in a disclosure; the list is a table with an empty state, and
the station form uses the field and drop zone components with an error summary. The
header linked to the list as Workspaces from #227 until the Workspaces page (#242)
replaced it there. The list stays for the gridded runs, which are not workspaces: the
Workspaces page links to it when the session has one, and so do the gridded setup page,
the gridded guide and a job's page.

**Polling.** The fragment replaces itself (`hx-swap="outerHTML"`) after a delay the
server chooses: `hx-trigger="load delay:<n>s, climpact:visible from:document"` with
`data-poll-hidden` (`ui.js` fires `climpact:visible` when the tab is shown and adds
`hidden=true|false` to the request; htmx's eval'd filters and `js:` values are not allowed
by the [Content Security Policy](#content-security-policy)). The delay is 1 s for the first 10 s of a
run, 2 s up to a minute and 5 s after; 30 s while the tab is hidden, and a poll at once
when it is shown again. A finished job's fragment has no `hx-get`, so polling stops. It
shows the status, the readable stage (`jobs/stages.py`: `indices:climpact:spi` is
"Calculating the indices"; the stage's ids after the first ":", a module, an index or a
file, are not shown, #226), step *n* of *total* with the percentage, the time so far and
a linear estimate of the time left (from the second step and 2 s on), for a queued job a
warning when no worker has been seen for `JOB_STALE_SECONDS`, and the cancel, retry and download controls.
Each GET is a plain request, so polling works through proxies and survives a dropped
connection (the next poll carries on).

**Retention** (`jobs/retention.py`). A finished job and its folder are deleted
`JOB_RETENTION_DAYS` (default 7, `CLIMPACT_WEB_RETENTION_DAYS`) after it finished; a queued
job that never ran, that long after it was created. Running jobs are never deleted, nor
are the jobs another app still shows: apps register them with `register_keeper(func)`,
`func()` giving their ids (the stations app keeps every job a station or batch shows,
`stations.retention.kept_jobs`, #231; the gridded app every job a run shows,
`gridded.retention.kept_jobs`, #301, #330). Folders
under `RUNS_DIR` named like a job id but belonging to none (an interrupted upload) are
deleted once older than the period. The worker purges at start and every hour
(`JOB_CLEANUP_INTERVAL`); `climpact-web manage purgejobs` does it on demand (and fails
stale jobs), for cron in a deployment. Every template gets `job_retention_days` (context
processor `climpact_web.jobs.context_processors.jobs`), with `workspace_expiry`, for the
New station page (#76, #201) to state the period; the job page shows the job's deletion
date. Other apps register their own clean-up with `register_purger(func)`; each purge
calls `func(now, days)` (the stations app deletes its workspaces this way, so the jobs app
knows nothing of them).

**Storage** (`jobs/storage.py`). `LocalJobStorage` creates the folders, saves uploads
(`save_input(job, name, file, folder="")`: the name is reduced to a file name, and a
folder, one plain word chosen by the code, puts it in `input/<folder>/`; `create_job` takes
such files as `"<folder>/<name>"` keys),
empties `output/` before a run, resolves download paths and deletes a job's folder. The
core reads and writes ordinary files, so a worker always works on a local folder. The
hosted deployment (#12) is one host whose web and worker containers mount the same Docker
volume at `CLIMPACT_WEB_MEDIA_ROOT`, so this class works unchanged. A deployment without a
shared filesystem could subclass it to copy `input/` down from object storage before a run
and `output/` up after it and serve downloads from there; `CLIMPACT_WEB_JOB_STORAGE` names
the class.

Browser tests of the finished pages are in `test_accessibility.py` (#83, see
[Accessibility](#accessibility)). `test_components.py` renders every component with sample parameters and
checks the accessibility hooks in the markup (labels, `aria-describedby`, `aria-invalid`,
`aria-current`, roles, the no-JS fallbacks), that the pattern library includes every
component, that every icon used exists in the sprite, the landing page with and without
the later screens' URLs (a stub URLconf), and the snapshot command.
`test_design_tokens.py` checks contrast, colour vision (#196), the chart palette export and the size budgets
(`test_charts.py` those of the chart assets);
`test_static.py` checks logical properties in every stylesheet and that `ui.js` has no
imports or network requests.

### A station's pages

A station's pages (#76-#79, #90, #178, #179) replace the R app's tabs
(`climpact/modules/singleStationStep1UI.R` to `singleStationStep4UI.R`). Since #179 a
station is a workspace of sections, shown as tabs under its name (decision A): since #198
Quality (#77; a compact worklist since #235), Indices (#78, #79; Results until #236)
and Files (#79, #176), beside the Inputs panel ("Your inputs"), where everything the user gave is changed
("Inputs panel" below). Since #233 a first visit is Add stations ([Add stations](#add-stations)):
one file added there is checked and calculated as the New station page (#201, "New station
page" below) did, and opens Quality; that page stays as a station's setup page, for a new
file that needs new details (its first-visit form, the sample and `/station/validate`'s
twin for it went with #271). There are no steps and no step indicator. R's step 3, the index settings, is
the Inputs panel's Index settings sheet since #199 ("Adjust and recalculate" on Results
from #178): the indices are calculated with the defaults while the user looks at the
quality checks ("Speculative calculation" below). The output pages hold no forms but the
decision ("Go to indices", #235; "See results" from #202, "Use this data" before), search and filters, and small actions (Delete, Try again,
Cancel, Recalculate).
R's step 4, sector correlation (#90), is an action on Indices since #173 (on Results
until #236), and its page shows the Indices tab as current. A change to an input keeps the work and marks what
depends on it out of date ("Workspace and staleness" below).

**Workspaces (#231).** A `Workspace` (`stations/models.py`) holds stations and the settings
they share (#230, decision 5): a UUID; `owner` (the job owner token); `name` (blank until
the user names it, #234; `display_name` gives the Flow board's default, one station's own
name or "3 stations, 17 Nov"); `created_at`; `updated_at`, the last change to it or any
of its stations or batches (`Station.save` and `BatchRun.save` bring it forward,
`bring_forward`); the shared settings `base_start`, `base_end` (R's defaults, 1971 and
2000), `qc_params` (#77: the `QCParams` fields entered, empty until changed, so R's
defaults) and `index_settings` (the index settings and output options in
`workspace.settings_of` form, empty for the defaults; stored when the Index settings sheet
changes them, #254); and `undo`, the last change to the settings while it can be undone
(below). Since #254 every station of the workspace reads its base period, thresholds and
index settings from it, and the sheets write them there ("Settings belong to the
workspace" below). A new station, uploaded or the sample, makes a workspace of one with
the defaults (Add stations; a station's setup page then sets its base period,
`views.set_base_period`, or, in a workspace of several stations, changes it for all with
`calculation.change_settings`). A new batch makes a workspace of its own, with no custom
index (`batch.fill.batch_index_settings`), and every station of its run is the
workspace's from when the run is queued (#255, [Batch page](#batch-page)). Deleting a workspace's
last station or batch deletes it. Existing analyses and batches were dropped by #231's
migration, not migrated (the maintainer's decision): `stations/0006_workspace_station`
replaces `StationAnalysis` with `Station`, and `batch/0002_workspace` deletes the batches
and adds `BatchRun.workspace`. Their jobs are kept by nothing and expire as usual; their
folders go as stray folders. #254's migration (`stations/0007_workspace_settings`)
copies a station's own base period and thresholds, and the settings of its latest run,
onto its workspace (each a workspace of one under #253), then removes them from
`Station`; `jobs/0004_workspace_settings` adds `JobStart.change`. #255's
`batch/0003_batch_fills_workspace` copies a batch's base period onto its workspace, removes
`BatchRun.base_start` and `base_end`, and adds `BatchRun.filled_job`; it reads no files
(the stations are added when the results are next shown).
`tests/migration_workspaces.py` checks both on SQLite (`test_workspace.py`) and Postgres
(`test_queue_postgres.py`).

**Workspace URLs (#256).** A workspace is `/w/<id>/` (`stations:workspace`,
`Workspace.get_absolute_url`), its stations `/w/<id>/<slug>/…` (`Station.url(name, *args)`
reverses `stations:<name>` with the workspace and the slug; templates use
`{% url 'stations:<name>' analysis.workspace_id analysis.slug %}`) and its batch
`/w/<id>/batch/…` (`BatchRun.url(name)`: a batch makes its own workspace, so the workspace
names it; `batch.views.get_run` takes the workspace's). `batch` is therefore not a station
slug, nor are `add` (Add stations' `/w/<id>/add/`, #233) and the overview's `settings`,
`progress`, `rename` and `undo` (#234), and `files` (the workspace's Files,
`/w/<id>/files/`, #239) and `compare` (Compare an index, `/w/<id>/compare/`, #238,
and its overlays, `/w/<id>/compare/<code>/overlay`, #276)
(`models.RESERVED_SLUGS`: a station named Batch is `batch-2`), and the batch's routes
are included before the stations' (`climpact_web/urls.py`). Every lookup is by the
session's owner token on both the station or batch and its workspace
(`views.get_analysis`, `batch.views.get_run`), so another session's workspace, a slug the
workspace doesn't have, or a station under another workspace gives 404.

- **`/w/<id>/`** (`views_workspace.workspace_page`) is the workspace's address. A
  workspace of one station opens it straight away, at its furthest section (the Flow
  board: "one station: open it straight away, no overview"): Quality while it waits,
  Indices once calculated or failed (which say why: `views_indices.batch_failure`, from
  `batch.fill.run_states`), the New station page for one the batch had no file for. A
  workspace of two or more opens its overview (#234, [Workspace overview](#workspace-overview)),
  after `batch.fill.fill_workspace` has recorded how a finished batch went. Without
  stations, files waiting on Add stations open their review, and a batch the old upload
  checked and never ran leads to Add stations (its check page went with #271). Every link
  to a batch's results goes here (`BatchRun.results_url`): the redirect after Add
  stations adds several stations, and the breadcrumb. `progress`, `rename`, `settings` and
  `undo` are the overview's own addresses, so they are not station slugs either.
- **Pages with no workspace yet** keep their addresses: `/add/` (Add stations, #233),
  `/add/sample` and `/add/sample-batch`, the station's sample files and the sample
  metadata file. `/station/new`, `/station/`, `/station/sample`, `/batch/` and
  `/batch/sample` lead to `/add/`, a GET or a POST: the old New station form, the old batch
  upload and the old samples went with #271 (`views.upload`, `batch.views.start` and
  `sample`). `/station/validate` checks the workspace's base period sheet as it is typed. A
  workspace is made when files are dropped on Add stations, and the redirect after it goes
  to the new address. Files waiting on Add stations are a batch with no job: `/w/<id>/` and
  `/w/<id>/batch/` lead to their review, and a batch that ran comes before them
  (`batch.views.get_run`); `/w/<id>/batch/` of a batch that ran leads to `/w/<id>/`.
- **Old addresses** (`views.old_station_url`, `batch.views.old_batch_url`): a GET or HEAD of
  `/station/<id>/<path>` or `/batch/<id>/<path>` redirects, with its query string, to the
  station's or batch's address under its workspace while it is kept, and gives 404 after
  that or to another session. `results` becomes `indices` and the old `indices` becomes
  `recalculate` (`OLD_PATHS`); the rest keep their path, except a batch's `results`, which
  goes to `/w/<id>/`, as does `/w/<id>/batch/results` (`batch.views.old_results`), its
  address before the change. The redirect is temporary (302),
  as a station's address follows its slug, which follows its name until the details are
  confirmed, and the old addresses go when their workspace expires. POSTs are not
  redirected (405): a form from a page from before #256 is sent again from the new page.
  `batch:open_station` (`/batch/<id>/open/<name>`, kept by #255 for old pages) is gone.
- **The charts' data** keep the station's id (`/charts/station/<id>/daily.json`,
  `views.get_station`): an API the pages call, not an address a person sees or bookmarks.
- The header's Workspaces is current on every `/w/` page (`navigation.DESTINATIONS`).

**Data model (#76).** A `Station` (`stations/models.py`; `StationAnalysis` before #231) is
one station of a workspace going through the steps: a UUID primary key; `workspace`;
`slug`, which names it in its workspace (#231: made from the station name by `slug_for`,
unique in the workspace, `sydney`, `sydney-2`; it follows the name while the station is
at step `upload`, then is kept); `owner` (the session's job owner token, so a
session sees its stations and its jobs, and any other session gets 404); `source`
(`upload` or `sample`); `file_name` (as uploaded, display only); `summary` (JSON from
`station_file.summarise`: first and last dates, days, per variable the days present and
missing, days with data per year, monthly means for the preview); `warnings` (about the
file); the metadata `station_name`, `latitude`, `longitude` (null until given; the base
period is the workspace's since #254, and `Station.metadata` takes it from there);
`file_hash` (#179, the SHA-256
of the station file as kept, `models.file_digest`, set by `save_station_text`); `step`,
the furthest point reached (`upload`, `qc` once the details are confirmed, `indices` once
the user chose "See results", then `results` and `sector`). It only moves forward since
#179; and `qc_job`, `indices_job`, `sector_job`, links to the `Job` rows of the later steps (null on
delete). The file is kept in the analysis's own folder, `<MEDIA_ROOT>/stations/<id>/station.txt`
(not under `RUNS_DIR`, whose stray folders the jobs app deletes); a job copies it into
its own `input/` when queued; a job the station shows is kept as long as the station
(`retention.kept_jobs`). A change to the
file or the metadata keeps the job links (#179; `reset_later_steps` is gone): each job
records the inputs it was made from in `Job.inputs`, and the workspace compares them with
the analysis's. The checks set `qc_job`, the speculative run and the Index settings sheet
`indices_job`, the sector comparison `sector_job`. The thresholds and index settings are
the workspace's (#254). A station of a batch (`source` `batch`, #255) keeps the index
values of its line in the batch's metadata file as its own (`origin["params"]`), its
state in the batch's latest run (`origin["run"]`) and, when the batch calculated it,
`origin["job"]` and `origin["inputs"]`, what the batch's results were made from
(`workspace.batch_results`; a station that failed, or has not finished a run, has none).

**Workspace and staleness (#179, `stations/workspace.py`).** `create_job` takes `inputs`,
which `calculation.queue_qc` and `calculation._create` fill (`workspace.job_inputs`):
`file` (the hash), `data` (what the provenance lines say about that file, #269,
`workspace.file_record`: its name as uploaded, first and last year, days, and the
variables with values, from `Station.file_name` and `Station.summary`), `metadata` (name,
latitude, longitude, base period), `qc` (the thresholds with R's defaults filled in,
`workspace.qc_values`) and, for a `station` run, `settings` (`workspace.settings_of`: the
`IndexParams` fields, plot title, plots, zip and report). A batch's `origin["inputs"]`
has `data` too, from the file the batch read (`batch.fill.batch_inputs`). `data` is never
compared (`file` is): it only describes the file. Jobs queued before #269 have no `data`,
and their lines describe the current file, as before. The workspace's provenance file
uses the record too (#307, `workspace_files.provenance`, below). `workspace.differences` names what differs between a job's inputs and the
analysis's: `file`, `name`, `location`, `base_period`, `qc`, `settings`. The checks depend
on the file, the thresholds and the name (their files are named after the station); a run
on all of them. The current `settings` are the station's (`workspace.station_settings`,
#254): the workspace's `index_settings` with the defaults filled in
(`workspace.workspace_settings`, `default_settings`), the station's own values in place of
the workspace's (`workspace.own_params`). A batch's custom index is its workspace's too
(#255): a workspace made by the old batch upload starts with none, as Climpact for R's
batch calculates none, so the fallback to the batch job's custom index that #254 had is
gone. A workspace started on Add stations (#233) has the default settings, the custom
index included, whether its stations run one by one or as a batch: its batch zip then has
the custom index's files, which R's batch never writes (a web-only difference; the core's
batch and its parity test are unchanged). Before #254 the settings
were those of the latest run asked for and were not compared when deciding what to queue;
now a change to them is an input change like the others. An input a job did not record
(a job from before #179) never differs. A section
is out of date when the job it shows differs (`qc_changes`, `run_changes`). This is
computed from the database alone, never from the session, so it is the same in every
browser tab open on the analysis and in hosted mode (a test changes the base period in one
tab and reads it in another).

A section shows the latest finished job of its kind: `shown_qc` is `qc_job` if it has
finished, else the checks it replaces; `shown_run` is `indices_job` if it has finished,
else the run it replaces, else the batch's results (`origin`). The replaced job is named in
the new job's `params["replaces"]` (#178's recalculation, now for the checks too,
`workspace.replaces_for` carrying it from a job still waiting). After a change,
`calculation.bring_up_to_date` (called by a station's setup page, Add stations and the
Inputs panel's sheets) runs `workspace.settle`, which cancels what is still queued or running for the
old inputs and, when an input was changed back, links the finished job of those inputs again
instead of calculating it twice; then it queues the checks and the run that are not of the
current inputs. A replacement run is speculative before "See results" and an ordinary job
(the user's own, counted by the hosted limits) after it; a refusal by the limits is logged
and leaves the results out of date with "Recalculate". A new file, from the File sheet
(which Quality's "Replace file" opens too, #199), queues the new checks and run at once
when the details still fit it; when the base period no longer fits the new data, the
station's New station page (`stations:setup`) asks for a new one first. The File sheet
keeps the station name; Replace on the New station page renames a station still named
after its old file.

The pages show it: Quality keeps the old checks under an out-of-date banner (the new checks'
progress, or their failure), with no "See results" until the new checks have finished
(`qc_continue` refuses out-of-date checks); the Indices keep the old results in a
`stale-content` block under a banner that says what changed ("You changed the base period
to 1981–2010. These results use 1971–2000.") and shows the new run's progress, or offers
"Recalculate" (`.../indices` POST with `recalculate=1`: `calculation.recalculate` promotes a
waiting run of the current inputs, or queues one with the latest settings); an index page,
the sector comparison and Files say so too. When the replacement finishes it is shown and
the section is current again. A change to the index settings now gives the same banner
("You changed the settings."), as the settings are an input of the workspace's (#254);
the Recalculation card is left for a run of unchanged inputs ("Recalculate", "Try again",
or Apply with the same settings). The header says nothing of the new inputs for the old
results (#223): while the results shown are out of date, the provenance line of the
Indices, an index page and Files describes the run on the page
(`workspace.provenance_inputs`: its recorded file data, coordinates, base period,
thresholds and settings, in place of the current ones; so after a new file the years are
the old file's, #269, which the Inputs panel and bar show as
"· changed"), and "Download all" is the old run's zip, so it reads "Download all (out of
date)" in the context bar and its ⋯ menu, "Download all (zip, 8.0 MB, out of date)" on
Files, and is secondary in both until the new results are ready, cancelled or not. Quality keeps the verdict's level and its count of values
that look wrong in the checks' `result["verdict"]` and `result["verdict_wrong"]`
(`workspace.remember_verdict`, called by `views.qc_context` before it builds the tabs, so
the first page after the checks shows their verdict), for the Quality tab (#222).
`workspace.qc_verdict` reads them, and works the verdict out from the checks once
(`qc_review.review`) when it was not kept: checks not yet shown, or a verdict kept before
#222 with its level alone. The review of checks reads the station's rows from the copy of
the file those checks read, in their job's `input/` (`qc_review.checked_file`:
`input_dir / params["station_file"]`, saved by `create_job` when the checks were queued),
not from the station's current file (#308). So while out-of-date checks are shown after a
new file, Quality's verdict, counts, year table, check values, charts and flagged values
CSV all describe the file they read, and the verdict kept with them is theirs: before
#308 the old checks were read against the new file (the Sydney sample replaced by its
1990–2015 years read "Fix the file first. 55 of 80 years too incomplete"), and that verdict
was kept with the old checks. A job whose copy is missing has no review (the page shows no
verdict, `qc_table` and `qc_flagged` answer 404) rather than one of another file; every
`qc` job has its copy, which goes only with the job's whole folder. The review is
built from the copy rather than from the job's outputs alone because the check rows,
the selected value's days around it, the line numbers and the charts all show the file's
values, which `nastatistics.csv` and the QC files do not hold.

**Settings belong to the workspace (#254, `calculation.change_settings`).** The Base period,
Quality thresholds and Index settings sheets change the workspace's settings, from any of
its stations' pages. `change_settings` checks the hosted limits once (`check_job_quotas`:
a refusal changes nothing), keeps what it changes for undo, saves the new settings, and
brings every station of the workspace up to date (`calculation.refresh`: `settle`, then the
checks where the thresholds changed and the run where its inputs changed, each replacing
the job shown). Every job one change queues carries the same id, `params["change"]`
(`jobs.models.CHANGE`, `calculation.new_change`; a change to one station's file or details,
`bring_up_to_date`, is a change of its own too, as are a new station's checks and
speculative run). A one-station workspace behaves as before. The Index settings sheet
writes the workspace's settings and options, except the values that are the station's own
(a batch line's): those change for that station alone (`origin["params"]`), and the
workspace's stay (`views.apply_settings`); the sheet says which they are. Applying
unchanged settings queues this station's run again; unchanged thresholds run its checks
again when they failed, were stopped or never ran. A sheet of a workspace of several
stations says that it applies to all of them (`workspace.impact`, not shown while a
workspace has one station), and every settings sheet that the change can be undone until
its replacement is ready.

**Undo (#254, decision 5 of #231).** `Workspace.undo` records the last change to the
settings: its id, the settings before it, and each station's `qc_job`, `indices_job` and
own index values before it. `workspace.undo_available` is true while one of the change's
jobs still waits or runs, so until the recalculation has finished (also when some stations
have finished and others not). Then the Inputs panel shows "Undo the change" under the
runs (`stations/_input_runs.html`, also in its polled refresh, which takes the page's
address from htmx's `HX-Current-URL` header), and the Inputs bar a small "Undo"
(`stations/_inputs_bar.html`); the panel and the bar are never shown together, so a page
has one. It is a plain POST form (`stations/_undo_form.html`) to `stations:undo`
(`/w/<id>/<station>/undo`), so it works without JavaScript. `calculation.undo` cancels the
change's jobs still waiting or running, puts the settings and the stations' own values
back, and links each station's jobs from before the change again
(`workspace.restore_if_cancelled` for one cancelled meanwhile), so the earlier checks and
results are current again; then back to the page (`next`) with a message. Once the
recalculation has finished, the form is gone and a stale form says the change can no longer
be undone. A change to one station's file or details forgets the record
(`calculation.forget_undo`), as its earlier jobs no longer fit; so does a change that queued
nothing. The jobs the record names are kept while it is there (`retention.kept_jobs`). A view reads
where the change stands from `workspace.change_state(space)` (a `ChangeState`: its jobs,
how many finished, failed or were cancelled, `finished`, and `can_undo`), or None when the
record is empty; the run status line on the workspace's overview uses it for Undo (#234).

**Tabs (#179).** `workspace.sections` gives each section its address and state, and
`stations/_workspace.html` draws the context bar (#227, `components/context_bar.html`;
the workspace header of #197 before it): the station's name as the h1 of the three
section pages, the provenance line (`workspace.provenance`: the coordinates, the years
and their count, "base" and the base period, "ET-SCI defaults" or how many quality
thresholds and index settings are not the default, and "climpact" with the core's
installed version, `importlib.metadata`; on a phone only the years; the shown run's values
while its results are out of date, #223), the page's actions
(the Indices' "Compare with sector data" and "Download all",
`stations/_results_actions.html`) and `components/workspace_tabs.html`. Quality's
provenance line describes the data the checks read instead (#235, `workspace.quality_provenance`,
as the Quality board draws it): the coordinates, the years, the days and the variables
with data ("21,915 days · PR TX TN") and the file's name; while the checks shown are out
of date (a new file whose checks are on the way, failed or were cancelled), those of the
file they read, from their `inputs["data"]` (`workspace.quality_data`, #269), not of the
file that replaced it. The other pages' lines leave the
file name out; the Inputs panel's File row has the file. The title is the station
name given, the file name only when there is none. The bar sits on the surface over a
hairline across the window: a layer behind it (`.context-bar::before`, 100vmax past
each side, with the border below; #239, a box-shadow clipped to the bar's height until
then, which also cut off the ⋯ menu, the citation and Export ▾ that open below the
bar), so it stays a child of `.station-page`, and
`.site-main` clips its inline overflow (`overflow-x: clip`, which makes no scrolling box)
so it never covers the help drawer; the page's top padding is 0. `workspace.context`
also sets `data_page`, so `base.html` gives a station's pages the whole window, with no
max width (#263; 92rem from #227 until then), instead of the 72rem content column. The bar is sticky (`.context-bar`,
a direct child of `.station-page`) under the site header (#284; at the window's top until
then) in a window at least 30rem high; shorter, where it would hide most of the page, it
scrolls away, and so does the header. The page's `scroll-padding-block-start` is
`--frame-height` (the header's height and the bar's) plus 1rem, so an element that takes
focus, or a `#fragment`, is never under either (WCAG 2.4.11); `js/context-bar.js` keeps
`--context-bar-height` to its real height with a `ResizeObserver` (9rem without
JavaScript). What sticks under the bar (Quality's rail, the Indices' rail and pane
contents, the Inputs panel) uses `--frame-height` for its offset and its maximum height.
A table's sticky header row sticks inside its own scrolling frame, so it does not move
with the page's frame. The skip link, when focused, sits 4px from the top, over the
header.

**Phones (#203, proposal 7).** Below 40rem (`components/workspace.css`) the context bar
is the name at `--text-md` and a ⋯ button on one line, and the provenance line only the
years (the base period is in the Inputs bar, the file name in the File sheet). The page's
actions are in that button's menu: `components/context_bar.html` includes the `actions`
template twice, in `context-bar__actions` (hidden on phones) and in a `<details
class="page-menu">` (shown only on phones), a disclosure rather than an ARIA menu, so it
works without JavaScript; `js/context-bar.js` closes it on Escape (focus back on the
summary) and on a click or focus outside it. The bar sticks above the header's foot by
the height of what is above the tabs, `--context-bar-above`, which `js/context-bar.js`
measures: only the header, the tabs and the Inputs bar stay in view (#284), and the scroll
padding is their height (the header's and the bar's, minus that). Until #203 the header was sticky only from 40rem wide. The
tabs' padding is smaller, so the three fit on one line at 320px. Sheets are the full
width. The states (`workspace.section_states`): Quality
`locked` until the details are confirmed, `stale`, `checking` (running), `attention`
(failed or stopped), or the verdict of the checks shown: `ready`, `usable` or `fix` (#222;
`done` only if the verdict cannot be worked out); Indices `locked` until "Go to indices", then `stale`, `running`,
`attention` (the first run failed), `todo` (no run at all), `empty` (no index table, #298)
or `done`; Files `locked` until there are checks or
results, `stale` when either is. Each tab is its own page, so the existing URLs stay as
they were (the Cloudflare rate-limit rules name them), the pages stay as light as before,
and they work without JavaScript; they are therefore links with `aria-current="page"`,
not an ARIA tablist. The New station page has no tabs and no Inputs panel (#201), and
neither has an index's page (#237), a drill-down from the Indices with a breadcrumb.

**Inputs panel (#198, `stations/_inputs.html`).** `workspace.context` adds the panel to
every section page once the station is set up (`workspace.set_up`: the details confirmed,
complete and fitting the data), and to the sector page; an index's page has the sheets but
not the panel (#237). `workspace.inputs_panel`
lists, in `PANEL_INPUTS` order: the file (its days and variables, "Replace"), the station
(latitude and longitude), the base period, the quality thresholds and the index settings
("Defaults" or "N changed", `workspace.changed_text`: `workspace.thresholds_changed`
counts the thresholds that differ from `QC_DEFAULTS`; `workspace.settings_changed` counts
the station's settings (the workspace's, with its own values) that differ from the settings
form's initial values, a
custom index other than the default one, a plot title of the user's, and each of the
plots, zip and report switched off, without importing the core). Each has one link,
which opens its side sheet (`workspace.sheet_url`; `input_urls` gives each sheet's
address to the page's other links, such as Quality's "Replace file"). The index settings
have no link, and no sheet, before "See results" (`workspace.sheet_keys`): only the
results use them. An input is highlighted, "· changed", when one
of the `differences` names it covers differs between the current inputs and the checks
or results shown (`workspace.changed_inputs`). Under the list, the checks and the run of
the new inputs show their progress (`stations/_input_runs.html`, a run only after "Use
this data"), polled by htmx from `stations:inputs_progress`, which answers `HX-Refresh`
once they have all finished.

**Inputs bar (#203, `stations/_inputs_bar.html`).** Where `.station-page` is narrower than
52rem, so the panel would not be beside the content, the panel is hidden and a one-line
bar under the tabs takes its place, in the workspace header (so it sticks with the tabs).
Both rules are inside `@media (scripting: enabled)`: without JavaScript the bar is hidden
and the panel stays above the content, as before. `workspace.inputs_bar` (in
`inputs_panel`'s `inputs_bar`) gives its words: the base period and "defaults", or "N
setting(s) not the default" (the thresholds and index settings counted together), then
"<input> changed" for each highlighted input (`inputs-bar--changed`, the warning tint)
and the label of each run under way ("Checking quality", "Recalculating"). The bar is
reloaded with the page when the runs finish, by the panel's polling, which goes on while
the panel is hidden. Its Edit, a button, opens `#sheet-inputs` (`stations/_inputs.html`), a
sheet with the panel's list (`stations/_inputs_list.html`, without the `data-input`
marks); an Edit there opens that input's sheet over it, a second modal dialog, and the
browser returns focus to the list when it closes. A sheet opened by the address returns
focus to the bar's Edit when the panel is hidden. An input's own page
(`input_edit.html`, `no_inputs_bar`) has no bar.

Each sheet is a modal `<dialog>` (`stations/_input_sheets.html`, `js/sheet.js`) with only
its input's form (`stations/_input_form.html`, `views.input_form`): the File sheet the
`UploadForm` (its own ids, `auto_id="sheet_%s"`, apart from the New station page's file
field), the Station sheet `StationForm` (name, latitude, longitude) and the Base period
sheet `BasePeriodForm`, both `MetadataForm` restricted to their fields and checked against
the data the same way, their fields validated as they change by `stations:validate`; the
Quality thresholds sheet `QCParamsForm` (#199); the Index settings sheet `IndexParamsForm`
with the plots, zip and report options (#199, `stations/_settings_fields.html`, its groups
validated as they change by `stations:indices_validate`). The sheet says what applying will
update, from the dependency rules (`workspace.impact` from `workspace.affected`:
Quality if `QC_INPUTS` has one of the input's names, Indices if `RUN_INPUTS` has, Files
with either; the station's location updates Indices and Files, its name Quality too).
Then one primary button, Apply, and Cancel. It posts to `stations:edit_input`
(`/w/<id>/<station>/inputs/<file|station|base-period|thresholds|settings>`), which applies
the change and returns to the page it came from (`next`, only one of this station's pages:
a path under `Station.url()`).
The file and station call `bring_up_to_date`. The base period, new thresholds
(`views.apply_thresholds`) and new index settings (`views.apply_settings`) change the
workspace's settings for every station (`calculation.change_settings`, above); the same
thresholds run the checks again when they failed, were stopped or never ran, which is how
Quality's "Run the checks" works since its form went, and the same index settings queue
the station's run again (`calculation.queue_station_run`), which replaces the results
shown when it has finished. Without JavaScript the Edit link is that address: a page with the same
form (`stations/input_edit.html`), where a form with errors also returns. The sheet is
modal, unlike the help drawer (DESIGN.md): focus starts on the first field and stays
inside, Escape, Cancel, the close button or the backdrop closes it and discards what was
typed, and focus returns to the Edit link. The forms keep their Turnstile widget, as
`edit_input` is `human_required` (five sheets, so up to five widgets per page in hosted
mode). The index settings are a long form: the sheet keeps its width (26rem) and its
body scrolls between the header and the foot, so Apply is always in view. A sheet's
section help opens in place (`{% section_help ... inline=True %}`, a disclosure), as the
drawer would be behind the modal sheet.

The old addresses of the forms the sheets replaced open them (#199): Indices at
`?settings=open` (old links; `&back=<key>` returns to that index) marks the Index settings
sheet `data-sheet-autoopen` and `js/sheet.js` opens it as the page loads; without
JavaScript a `<noscript>` refresh in the head (`stations/_open_sheet.html`) goes on to the
sheet's page. `js/sheet.js` also opens the settings sheet for `#adjust` and the
thresholds sheet for `#thresholds`, the old forms' anchors, which stay on the page (the
settings line on the Indices, the thresholds line under Quality's worklist) for a browser without
JavaScript. Closing a sheet opened this way focuses its Edit in the panel.

**The Data tab folds into Quality (#198).** Data's summary (`_summary.html`: the period,
missing values by variable, the daily series and the days with data per year) is a
section of Quality, "Your data" (`id="your-data"`), so the Quality page loads the chart
code. Since #235 it shows only while the checks run (or failed); once they have run the
coverage strip takes its place and its anchor (`id="your-data"` on the strip's wrapper). Once the station is set up, `stations:load` (Data's address) and `stations:setup`
redirect to `.../quality#your-data`; before that, and when a new file no longer fits the
details, they lead to the station's setup page (the New station page). The station's own
address, `/w/<id>/<station>/` (`stations:station`), opens Indices after "See results",
Quality once set up, else the setup page.

**Migrations (#179).** `jobs/0003_workspace_inputs` adds `Job.inputs`,
`stations/0004_workspace_inputs` adds `StationAnalysis.file_hash`, and
`stations/0005_backfill_workspace_inputs` filled them for the analyses of the time. #231's
migration (above) has since dropped those analyses.

**URLs.** A station's pages are under its workspace since #256, `/w/<id>/<station>/`
(the station's slug), written `...` below. `.../setup` is a station's setup page
(`stations:setup`, the New station page of #201); `/station/` (`stations:upload`, the
upload page until #201), `/station/new` (`stations:new`, the New station page with no
station yet, #201) and `/station/sample` (`stations:sample`, the sample on its setup page)
lead to Add stations, GET or POST, since their forms went (#233, #271); `.../load`
(`stations:load`, Data until #198, the details until #201) redirects to the setup page, or
once the station is set up to Quality's "Your data", GET or POST; `.../setup/validate`
(htmx, POST: a group of the details checked as it changes, against the file) and
`/station/validate` (the same without a file, for the workspace's base period sheet);
`/station/sample.txt` downloads the sample file (R links to it too); `.../`
(`stations:station`, #179) the furthest section reached (Indices after "See results", else
Quality once the details are confirmed, else the setup page); `.../file` (POST, the
old Load page's "Use a different file") is gone since #201; `.../series.csv` the daily
series; `.../delete` (POST); `.../undo` (POST, #254); `.../inputs/<key>`
(`stations:edit_input`, #198, #199) a sheet of the Inputs panel as a page, POST applies
it; `.../inputs/progress` (htmx); `.../quality` Quality (`stations:qc`),
`.../quality/progress` (htmx), `.../quality/checks/<check>` (htmx: one page of a check's
table, `?page=` or `?date=`), `.../quality/continue` (POST: "Go to indices");
`.../quality/flagged.csv` (`stations:qc_flagged`, #235: every flagged value of the checks
shown, one row each: date, check, kind ("look wrong" or "worth a look"), variable, value as
the file has it, units and what it was checked against; `qc_review.flagged_rows`);
`.../quality/run` and `.../quality/file` are gone since #199 (the thresholds and file
sheets); `.../indices` Indices (`stations:results`: the URL names kept their names when
the paths moved), `.../indices/progress` (htmx), `.../indices/<key>` one index
(`stations:result`; `?series=` the monthly series, `?view=anomaly` the anomalies; the
standardised anomalies' address, `anomalies.json`, went with #237); `.../recalculate`
(`stations:recalculate`; `.../indices` until #256, the Calculate step's address until
#178): POST with `recalculate=1` is "Recalculate" on out-of-date results (#179), any other
POST (a settings form from a page from before #199) goes to the settings sheet's page, and
GET redirects to `.../indices?settings=open` (with `&back=<key>` for `?index=<key>`), which
opens the Index settings sheet; `.../settings/validate` (`stations:indices_validate`,
`.../indices/validate` until #256; htmx, POST: the settings sheet's field checks);
`.../sector` the sector comparison (`stations:sector`; POST queues the comparison, `?order=strength`
sorts the bars), `.../sector/progress` (htmx); `/station/sample-sector.csv` R's sample
sector file (`stations:sector_sample`); `.../downloads` the Files page
(`stations:downloads`, #79, #176). No index key is `progress`, which comes before
`indices/<key>` in `stations/urls.py`.

**New station page (#201), a station's setup page since #233.** Proposal 4 of #171's
second review ("One setup screen, then the workspace"): a first visit asked only for what
must be given, on one page (`stations/new.html`, `views.new_station`), in two numbered
steps, then one button. Add stations (#233) is the first visit now, and #271 removed the
page's first-visit form (`/station/new` with no station: the drop zone, "Use the sample
data", the sample's download link, the session's recent analyses and the empty name that
took the file's). What stays is the page of a station whose details are not done: a new
file (from the File sheet or Replace here) that needs new details, or a batch's station
whose file was missing (`stations:setup`).

1. **Your file.** A file card (`_file_card.html`: the
   file name, "✓ Read: 1936–2015, 29,220 days", Replace) and a strip of days with data per
   year (`views.year_strip`: an SVG bar a year, as tall as its emptiest variable's share
   of the year, amber when a variable misses more than 15 days, climdex.pcic's
   `max.missing.days` for annual values, `MAX_MISSING_YEAR_DAYS`, checked against the
   core's `climpact.missing.MAX_MISSING_DAYS` by a test; its text alternative counts and
   names those years; an SVG, as the Content Security Policy allows no inline styles).
   The Sydney sample, which misses at most a few days in a year, has none. Warnings about the file show under it.
2. **Station details.** Name, latitude, longitude and base period (`MetadataForm`,
   "Station details" below), with short hints only. A name left empty is the station's
   (the file's name until it is changed), as R does. The base period is the workspace's.

Then one primary button, **Check and calculate**, with a note beside it that the quality
thresholds and index settings use the defaults and can be changed later in Inputs. It
saves the details, moves `step` to `qc` and calls `calculation.bring_up_to_date`, which
queues the checks and the speculative run together (#178), and opens Quality (the Indices,
when only they are affected: a station in use whose new file needed new details). The
retention notice is one quiet line at the foot (#173), beside Delete and "Start again
with another station" (Add stations).

It is one multipart form (`#new-station`), so it works without JavaScript: a new file and
the details can be sent together with "Check and calculate", or the file first with
"Read the file" (`intent=read`, a redirect back to the page), then the details. With
JavaScript (`js/setup.js`) a file chosen with Replace is sent at once (WCAG 3.2.2); the
details typed beside it go with it and those valid on their own are kept
(`views.keep_typed_details`). Back on the page, focus moves to the file card
(`data-focus-on-load`, set once by the session after a read), unless an error summary
takes it. Replace is a file button inside the form (the file button of #174, sent with
its own hidden "Read the file"). Errors are shown inline, each with its summary, which
takes focus: a file that cannot be read (its problems, the details kept as typed, the
station's file unchanged), and wrong details (the error summary over the details; a good
file sent with them is kept). The Turnstile widget is in the form, before "Check and
calculate"; the view is `human_required`. A station already
set up has no setup page: later changes are made in the Inputs panel. The days-per-year
table, missing values and daily series are Quality's "Your data" (#198), not on this
page.

`station_file.inspect_station_bytes` checks the file before anything is saved:

- *Problems* stop the file: empty, not text (a zip or Excel workbook, or NUL bytes), no
  data rows, a line without six values, a value that is not a number (`NA` is accepted as
  missing, as R reads it; "na", "N/A" and similar get "write missing values as -99.9 (or
  NA, in capitals)"; a comma inside a number gets a note that commas
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

**"Your data" (Quality, #198; compact since #202; only while the checks run since #235).** Chips for the period, years and days
(from the first row's date to the last, as R's quality control), the days missing and
the share missing per variable (one value per date, the last row of a repeated date, as
the indices use) and, once the checks of this file have run, the years too incomplete for
annual values; then disclosures: the missing days per year (`qc/nastatistics`, the
Missing data section before #202), the daily series and the days with data in each year;
and a CSV download of the daily series. The preview (`preview.py`) is two small inline SVG charts of monthly
means (maximum and minimum temperature, monthly total precipitation; months with fewer
than 20 days are gaps), drawn on the server in the chart tokens. Since #75 the section
shows the interactive daily series instead (`charts:station_daily?flags=0`: without the QC
flags, #173; its CSV link is `stations:series`), and the static preview is the fallback
inside `<noscript>`. See [Charts](#charts).

**Station details.** The fields are exactly those of the R app: station name,
latitude, longitude, base period first and last year (`MetadataForm`). The name defaults
to the file name without its extension (as the command line does), reduced to letters,
digits, spaces and `.()-_` (it becomes folder and file names). Rules and messages:

| Field | R app | Python |
| --- | --- | --- |
| Station name | required ("Please enter a station name") | required; the characters above, not starting with a dot |
| Latitude, longitude | default 0, 0; must lie in -90..90 and -180..180 | start empty and are required (a forgotten 0 would put the station in the Southern Hemisphere); same ranges; latitude 0 gets a warning that it counts as Southern Hemisphere |
| Base period | default 1971-2000; years >= 0; the help says it "must be within the limits of the dates in the station data", but nothing checks it before the run | same defaults; the last year must not be before the first; a base period with no year inside the data is an error; partial coverage is a warning naming the years covered; 359 days or fewer of the base period inside the data (`MIN_BASE_DAYS`, the core's rule) is a warning that the percentile indices cannot be calculated, as the run would go ahead in R too |
| Sample | a link to the file; the user uploads it and types the metadata | one click on Add stations (#233): the station "Sydney Observatory Hill" (#219) with latitude -33.86 and longitude 151.21 (as in `reference/stations.csv`), checked and calculated at once; its Quality opens |

**htmx.** The form is split into groups (`MetadataForm.UNITS`: name, latitude, longitude,
base period). Each group is a `<div>` with `hx-post` to `.../setup/validate` (or
`/station/validate` on the workspace's base period sheet, which has no file),
`hx-trigger="change"`, `hx-include="closest form"` and `hx-vals` naming the group; the
server validates the whole form and returns only that group, re-rendered with its
errors and warnings, which replaces the old one (`outerHTML`). Without JavaScript the
whole form is posted and the page shows every error with the error summary.
"Check and calculate" is the one button, below the fields it confirms (#173, #201). #114
had put a second button, "Details look right", above the fields when they were already
valid; #173 removed it.

**Quality: the quality checks (#77).** Replaces the R app's step 2
(`singleStationStep2UI.R`, `singleStationStep2.R`, `services/quality_control_checks.R`) and
its QC plots. R shows six thresholds, a "Check Data Quality" button, a slideshow of the
QC PNGs and the folder or zip of the QC files, and enables "Next" once the checks ran
without errors; the user corrects the file outside the app and loads it again.

- *Thresholds* (`QCParamsForm`): R's six numeric inputs with its defaults, limits and
  tooltips: `iqr_temp` (3, 1-10), `iqr_prec` (5, at least 1), `prec_max` (200 mm, 0-1500),
  `temp_max` (50 °C, 0-60), `flatline_days` (5, 3-15), `jump` (20 °C, 5-30), each with its
  `qcparam.*` help topic. `QC_DEFAULTS` repeats `QCParams`' defaults so the web server
  does not import the core (a test checks they agree). Saved on the workspace
  (`Workspace.qc_params`, #254); changing them replaces every station's checks and run,
  with the same settings (#178), since the full run's QC files use them too (the `station`
  runner's `qc` parameter). The old checks and results stay, out of date, meanwhile (#179).
- *The job*: confirming the details (Add stations, or "Check and calculate" on a station's
  setup page) queues a `qc` job at once with the saved thresholds (R
  waits for a click), so the results are usually there when the page opens; changing the
  thresholds or uploading a corrected file queues another, cancelling one still waiting.
  The page polls `.../quality/progress` (progress bar, stage, time) and reloads when the
  job has finished (`HX-Refresh`; a `<noscript>` refresh without JavaScript). While the job
  is queued or running the page says "Running the quality checks…" and has no thresholds
  form of its own (the thresholds are edited in the Inputs panel's sheet since #199), so
  nothing suggests the checks must be started by hand (#114). Once there are results,
  "Change the thresholds" on the line under them opens the thresholds sheet
  (`stations/_qc_details.html`). A failed, stopped or never-run check says so and offers
  "Run the checks" (`stations/_qc_run_again.html`), which opens the same sheet; its Apply
  runs them with the thresholds shown.
- *Results* (`qc_review.review`): read back from the job's `qc/` files, the files the
  user downloads, so every row of every file is reachable on the screen, with the
  station's rows from the copy of the file the checks read (`qc_review.checked_file`,
  #308). Since #174 the
  page is a short worklist (the Sydney sample's went from about 8,250 px to about 2,100 px
  at 1280 px wide), since #202 a list and detail (3,125 px to 2,414 px at 1280 px wide,
  with "Your data" now on the page in full), and since #235 a compact worklist to the
  Quality board (at 1280 px: the Sydney sample 2,323 px to 1,885 px, the QC stress file
  4,617 px to 2,295 px, Sydney with TX and TN swapped on every 100th row 3,850 px to
  2,072 px), in this order:
  - *The verdict strip and the one decision* (`qc_review.verdict`, decision B of #174;
    `components/verdict_strip.html`, `stations/_qc_verdict.html`). Only the checks whose
    findings are almost always mistakes (`kind == "error"`: TN ≥ TX, out of range,
    repeated dates; their rows, one per date for repeated dates) set the level; outliers,
    jumps and flat runs are counted and never change it. Green "Ready to use." when
    nothing looks wrong; amber "Usable." when up to 0.1% of the values checked look
    wrong; red "Fix the file first." above 0.1%, or when more than 10% of the years are
    too incomplete for annual values. Both limits are `VERDICT_LIMITS` (`VerdictLimits`).
    The level in bold and one sentence ("21 values look wrong; the indices can run with
    them as they are.") are the strip's heading; under it one mono line of counts: the
    values checked (PR, TX and TN present on each date, the row the indices use for a
    repeated date), how many look wrong and their share, how many are worth a look, the
    values missing and their share of all of them (`values_missing`), and the years too
    incomplete when there are any. The buttons at its end: "Flagged values (CSV)" when
    anything was flagged, then one primary button, "Go to indices" (green, amber; "See
    results" from #202), with "Replace file" before it on amber; on red "Replace file" is
    primary, with "Go to indices anyway" before it. "Replace file" opens the panel's File
    sheet (#199). Continuing is always possible once the checks have run (R also allows it
    whatever they found; R has no verdict).
  - *The coverage strip* (`components/coverage_strip.html`, `stations/_qc_coverage.html`,
    `Review.coverage`): the missing days per year of PR, TX and TN from `qc/nastatistics`,
    a cell a year in the coverage steps (none, 1–3 days, 4 or more), each variable's total,
    the years under them; its note says whether every year passes the annual completeness
    rule, or which years are too incomplete. Its table view is the disclosure "Missing
    days per year": the years with any, with the months that have more than 3 missing
    days and the years left without an annual value (more than 15 days, or such a month:
    [Missing data](#missing-data)).
  - *The checks and the selected check's detail* (#202, #235, #264, the Quality board
    redrawn on 17 November; `stations/_qc_review.html`, `_qc_rail_item.html`,
    `_qc_detail.html`, `_qc_values.html`). At the inline start a rail of the checks that
    found something (`Review.items`, `qc_review.Item`, each a `qc_review.Group`): *Look
    wrong* (`wrong_groups`: TN ≥ TX, Out of range, Repeated date, in R's order) and
    *Worth a look* (`worth_groups`: the outliers by variable and direction, "Heavy rain
    days", "High maximum", from the sections of `qc/outliers`; the TX and TN jumps, "Large
    day-to-day change" in the rail and "≥ 20 °C" in the detail's title; the flat runs,
    "Same TN 6+ days": more than `flatline_days` equal values; the largest first). Each
    check is a row with its variables ("PR", "PR TX TN", "all rows"), twelve small bars
    by calendar month (`Group.bars`) and its count. Beside the rail (20rem, from a 60rem
    page, sticky under the header and the context bar and scrolling inside itself when
    taller than the window; after it otherwise, with "Back to the list") the selected check's detail:
    its kicker ("Worth a look · PR · 67 values"), its title and one sentence
    (`Group.lede`: when its values fall, `Group.mostly`, what the check means with its
    thresholds, then what to look at first), "These values (CSV)" (`quality/flagged.csv
    ?check=<key>&group=<group>`) and "Show on the daily chart" (the selected value); two
    charts drawn on the server with axes, *When* (`when_chart`: each value against its
    date across the record, `Row.plot`, the selected one ringed; three value ticks, from
    zero for amounts, `_nice`; up to seven years) and *By calendar month* (`months_chart`:
    twelve bars with count ticks; "Table" shows its table in the chart's place, both show
    without JavaScript), each read out by pointer and keyboard (#283, `when_readout`,
    `months_readout`; a When value picked selects its row; see [Charts](#charts)); then
    the values table and the selected value side by side. The
    values table has only the columns the check needs (`value_columns`, `Row.values`):
    heavy and light rain Date, PR, the month's limit (the box plot's whisker), Over or
    Under by; TN ≥ TX Date, TN, TX, TN − TX; out of range Date, PR, TX, TN; repeated date
    Date, Rows, Lines in the file; temperature outliers Date, the value, the month's usual
    range, Beyond by; jumps Date, the value, the next day's, the change; flat runs Date,
    the value, Days in a row, From (the run's first day). It has 12 rows a page
    (`PAGE_SIZE`), largest first (`Row.size`: how far beyond what the check expects, the
    change, the run's length, the rows of a date; `Check.sorted_rows`) or by date. The
    selected value (`Review.value`, `build_finding`, the largest by default): its date and
    check, its sentence, codes first ("PR 350.5 mm, 328.6 mm over the limit for
    December", "TN 9.5 °C is above TX 8.2 °C"), a chart of the 3 days either side
    (`WINDOW_DAYS`, 7 either side until #264): PR bars with the limit dashed
    (`_bar_chart`) for a rain check, otherwise TX and TN lines with the value ringed
    (`_chart`), the day as a band; the same days as a table to one decimal (the chart's
    table view; the day in bold, the check's other values marked), a repeated date's rows,
    and the line(s) of the station file that give the date (`StationRows.lines`, read by
    `qc_review.file_lines`: "Line 465 in the file"). Without JavaScript every link is an
    address: a check `?show=<id>` (its `table_id`; an unknown id the first), its page,
    order and value `?<id>_page=`, `_sort=` and `_value=` (`views.check_state`; with no
    `show`, the check these name, `views.selected_item`). Every check's detail is in the
    page, the others `hidden`. With JavaScript (`qc.js`) a check shows its detail in place,
    marks it (`aria-current`), puts `?show=` in the address (`replaceState`) and
    announces the detail's title in a polite live region; when the detail is below the
    rail, focus moves to its title, and "Back to the list" returns it to the check. A
    value's date (or a click anywhere on its row), the sort and the pager swap the values
    fragment in place (htmx, `.../quality/checks/<check>?group=&page=&sort=&date=`,
    `views.qc_table`); the When chart's ring then moves to the selected value
    (`data-ring-x`, `data-ring-y`), the address takes the link's, the value's title is
    announced and focus stays on what was used. Keyboard: Tab moves between the checks,
    Enter selects. "How the checks work" (a quiet help link, `{% section_help quiet=True
    %}`) opens the verdict's help with every check's topic. Like the Indices (#263),
    Quality has no Inputs panel beside it since #264: "Edit inputs" on the provenance
    line, so the rail and the detail have the width; at 1280 px nothing scrolls sideways
    with the 67 heavy rain days of the QC stress file.
  - *Checks that found nothing*: one line ("4 checks found nothing: ...").
  - *Daily values, with the flags* and *Distributions*, two disclosures, then one line
    with the thresholds the checks used (a link opens their sheet) and the link to the
    quality-control files in Files (#176). "Details", one disclosure holding them, until
    #235.
- *Tables*: each check in the rail has its values table in pages of 12 (htmx,
  `.../quality/checks/<check>?group=<variable>-<direction>&page=&sort=`; plain links with
  `?show=<table>&<table>_page=&<table>_sort=` without JavaScript, the table being
  `outliers-prcp-high`, `tx_jumps`, ...). The tables add what the files leave out: both
  days and the change for jumps (the TX file holds the change and the TN file the day's
  value, R's slip, see [Quality control](#quality-control)), the first day of a flat run,
  the month's limit or usual range for an outlier (the whiskers of `qc.boxplot_stats`)
  and how far beyond it, the lines of a repeated date (one table row per date). The
  flagged value is in bold. The flagged values CSV keeps every file's columns.
- *Daily charts* (the "Daily values" disclosure): one per variable (TX, TN, DTR, precipitation) in tabs,
  from `charts:station_daily?variable=`, with the flags of the job's thresholds as rings.
  "Show on the daily chart" in a check's detail opens the disclosure and the selected
  value's chart and moves it to the date (marked with a dashed line, focus on the chart);
  a click on a ring selects that value in the first check that found it (loading the
  page that holds it; `qc_table` answers a check that did not find the date with no
  content), shows that check's detail and focuses the value (#202, #264). See [Charts](#charts) for the API.
- *Distributions* (a disclosure; `qc_plots`, inline SVG with a table each), R's QC plots:
  monthly box plots (`fourboxes`, whiskers at the thresholds, so the values beyond them
  are the outliers), box plots by year (`boxseries`, whiskers at 4 IQR for precipitation
  and 3 for temperatures, as R), decimal values (`roundcheck`) and the precipitation
  histogram (days of 1 mm or more in 2 mm bins to 40 mm and one above, as `plotToFile`).
- *Thresholds* (under Details): one line, R's defaults or how many were changed, with a
  link that opens the Quality thresholds sheet (#199). No form on the page.
- *Replace file* (the verdict's button, and the panel's Replace): the File sheet. The new
  file replaces the old one, the station details and thresholds are kept and the checks
  and the run start again, the old ones shown out of date until then (#179); if the base
  period no longer fits the new data, the station's New station page opens to change it.
  A file with problems is refused with the same messages as on that page, on the sheet's page, and the
  previous results stay. When the checks failed, were stopped or have not run, "Run the
  checks" opens the thresholds sheet, whose Apply runs them.
- *Files* (under Details): one link to the quality-control files on the Files page
  (`#quality-files`). Since #176 the Quality page offers no download itself; each QC file
  and their zip (`<station>.zip`, the station's `qc/` folder, as R's QC zip) are on Files.

**Speculative calculation (#178; decision D, on in local and hosted mode).** The Calculate
step only confirmed defaults: every index is calculated, the defaults are almost always
kept, and a run takes seconds. So when "Check and calculate" confirms the station details
(the New station page, #201),
`calculation.speculate` queues a `station` job with the workspace's settings
(`previous_params`, the defaults until changed), behind the quality checks, marked
`params["speculative"] = True` (`jobs.models.SPECULATIVE`). It is the same job, with the
same `IndexParams`, thresholds and files, that the Calculate button queued before, so the
outputs are identical. "Go to indices" on Quality (every verdict, "Go to indices anyway"
included; "See results" until #235) calls `calculation.commit`: the run becomes the user's own (`jobs.views.promote`
sets the key to false and records the start for the daily quota, unless its change, the
checks queued with it, already has one, #254) and the page goes
straight to the Indices, which show the dashboard if it has finished and its progress if not.
Without a run (refused, cancelled), one is queued then. Until "See results", no page shows
it: the Indices redirect to Quality, an index page and Files act as if there were no run
(`workspace.committed`).

A run of old inputs is never shown as current. Changing the details, loading another
file or changing the thresholds (the Inputs panel's sheets) cancels a run still waiting or running for the old inputs (`workspace.settle`,
`Job.request_cancel`: at once if queued, at the next progress step if running) and, except
for a new file on Data (the details must be confirmed again), queues another
(`calculation.bring_up_to_date`), with the workspace's settings. Before "See results"
the replacement is speculative; after it, the finished results stay on the page, out of
date, until it has finished (#179). "Your calculations" leaves the cancelled speculative
runs out. An analysis opened from a batch (`origin`) gets no speculative run: it shows the
batch's results until it is recalculated here, or until a change makes them out of date,
which queues its own run.

How it fits the hosted limits ([Security of the hosted site](#security-of-the-hosted-site)):
the worker takes a speculative run only when no other job waits (`claim`), it is queued
only while fewer than `SPECULATIVE_MAX_QUEUED` jobs wait and the client has room under
`MAX_ACTIVE_JOBS_PER_IP`, and it counts towards neither the queue cap, nor the client's
active jobs, nor the daily quota until "See results". So it uses the worker's idle time:
it never takes a place a user's job needs, and it delays another job by at most the rest of
one run when the worker is already on it. A default Sydney run (80 years, plots, report and
zip) takes 11.9 s on an Apple M-series laptop (2.4 s without plots, plus about 3 s of
imports per worker start); the 1-vCPU Droplet is slower (the full flow took 15 s natively and
26 s under Rosetta, "Size and memory" in [Deployment](#deployment)). Wasted runs, of users who leave
at the checks or change the data, cost that worker time and the run's folder until the
retention purge (a few MB, `JOB_RETENTION_DAYS`), never a user's quota.

**The Index settings sheet (#78, #178, #199).** `IndexParamsForm` (`stations/forms_indices.py`) has
every field of R's step 3 (`climpact/modules/singleStationStep3UI.R`): plot title, d for
WSDId and CSDId (1 to 10), d for Rxdday and for TXdTNd/TXbdTNbd (1 or more), the base
temperatures of HDDheat, CDDcold and GDDgrow, nn for Rnnmm (0 or more), the extra SPI/SPEI
time scale (1 or more months) and the custom threshold index (variable TN, TX, TM, PR or
DTR, operator, threshold), with R's defaults. The fields' own limits give plain messages,
and `clean()` then runs the core's `climpact.batch.validate_params` (R's
`validate_climdexInputParams`) on the `IndexParams` built from them, so the form accepts
exactly what the core accepts (a test checks every boundary). Each field has its unit, a
short hint with R's default. The fields are grouped (plots, spell lengths, degree days,
precipitation and drought, your own index, the heatwave note, files), each group with its
help in place (a disclosure: the sheet is modal, so the drawer would be behind it), which
has the groups' `param.*` topics and how the index is named (with 3 days, WSDId
is written as `wsdi3`; #177). Each group is checked by htmx as it changes
(`stations:indices_validate`), which shows warnings that do not stop the run: d = 6 for
WSDId or CSDId, Rx1day/Rx5day, R10mm/R20mm and the 3, 6 and 12-month scales duplicate
indices always calculated. R's station screen has no EHF definition (station runs always
use Nairn and Fawcett 2013, the only one `climdex.hwEHF` accepts); the form says so.

The form (`_settings_fields.html` in the sheet's `_input_form.html`) was "Adjust and
recalculate", a disclosure after the catalogue on Results, until #199; it is now the Inputs
panel's Index settings sheet, on every station page once the data is in use. Its groups
are divided by rules, not cards (DESIGN.md: no cards inside cards); the sheet's body
scrolls between its header and its foot, so Apply stays in view. It starts from the
station's settings (`previous_params`: the workspace's, with the station's own values from
a batch's metadata line, `origin`; the defaults until changed). A form with errors returns on the
sheet's page with the error summary. The results' header names the settings in one line
(`views_indices.settings_line`: "Climpact's default settings.", or "Settings changed:"
and the settings that differ from `IndexParams()`), with a link that opens the sheet; an
index that depends on a setting, Files' "Not made" notes and a failed run's "Change the
settings" open it too. Its one button, Apply, is at the foot, described by what it
updates ("Updates Indices and Files. Quality stays as it is. About half a minute for 80
years of data."). New settings change the workspace's and recalculate
every station ("Settings belong to the workspace" above); for this station that is a
`station` job (`calculation.queue_station_run`: QC files, every index, and the plots, the zip and the
PDF report unless unticked) with the workspace's thresholds (`qc`, from
`Workspace.qc_params`), as
`indices_job`, cancelling a run of the analysis still waiting or running. When the run it
replaces had finished, the job's `params["replaces"]` names it, and the Indices keep those
results on the page until the new run has finished (below).

**Indices: progress.** While the first run is queued or running, `stations:results` shows its
progress: a bar, step *n* of *total*, the time so far and left, and the stages of the run
(read, quality checks, homogeneity, indices with the product being calculated, writing,
plots, zip) with the `stages` component. The fragment (`stations:results_progress`) polls
with the job page's delays; when the job succeeds it answers `HX-Redirect`, so the page
becomes the dashboard. A failure shows the job's error, the stage it stopped at, "Try
again" (returning to the Indices) and "Change the settings". The results URL stays the same
while the job is kept. The Index settings sheet is in the Inputs panel meanwhile, so the
settings can be changed before the first run ends. With no run at all (a speculative run
refused in hosted mode and the ordinary one too, or one cancelled), the page says the
indices are not calculated yet, with one button, "Check the settings and calculate",
which opens the sheet.

**Indices: a recalculation** keeps the results it replaces (`params["replaces"]`) on the
page, with its progress in a panel above them ("Recalculating", then "The results below use
the previous settings"); `views_indices.current_source` (from `workspace.shown_run`) serves the replaced run to the Indices, the index
pages, Files and the sector comparison meanwhile. When it succeeds, the fragment's
`HX-Redirect` shows the new results; when it fails, the panel says so with "Try again";
when it is cancelled, the analysis's `indices_job` goes back to the replaced run
(`workspace.restore_if_cancelled`; for a batch station, back to the batch's results). A
recalculation with new settings is a change of input (#179): the results it replaces show
the out-of-date banner ("You changed the settings.") with its progress inside, rather than
this panel, which stays for a run of the same inputs.

**Indices: the table** (`stations/results.py`, `results.html`, `_indices.html`; the
section was named Results until #236; its address is `indices` since #256, and its URL
name is still `stations:results`). Every index
table of the run is on it: the core's `climpact.plots.index_plots` gives the plotted
series (with their R descriptions, units and Sen's slope trends, as the PNGs and the
charts), grouped into one card per index (`txx` with `txx_ANN`, `txx_MON` and the two
`day_of_` series; each heatwave aspect, each SPI/SPEI scale and the custom index have
their own card), and the daily `EHFdaily` and `ECFdaily` tables, which R does not plot,
get cards of their own. For the Sydney sample that is 80 cards for the 114 tables. Since
#236 (the Results board of the design canvas) the page is a filter rail, one line that
answers, one dense table and a detail pane; the theme tiles and the answer band (#175,
#200) are gone. Since #263 they use the whole window: the rail and the pane are
full-height columns against the window's edges (`station-page--indices`: `.indices`
reaches out through the page's gutter), the rail on the page's colour and the pane on the
surface, each behind a hairline; the notes above them (out of date, a recalculation,
skipped indices) and the retention line below keep the page's margins.

The table opens sorted by the size of the trend (#263, the board's "sorted by |slope /
unit|"): `views_indices.DEFAULT_SORT`, `"size"`, the absolute slope per decade in the
index's own units, largest first, rows without a trend last, ties in the help
catalogue's order (temperature thresholds, extremes, percentiles, seasons,
precipitation, heatwaves, drought, your own index). With the Sydney sample that opens on
GDDgrow10 (+69.0 degree-days a decade), then CDDcold18 and HDDheat18; the first row's
detail is shown. No column has this order, so no header has `aria-sort`, and the address
and the rail's form leave it out. Indices are
named codes first (#218): each row leads with the code (`Card.code`, from
`results.display_name`: `TXx`, `Rx3day`, `TX90-HWN`, `SPI3`, `EHFdaily`), in mono, with its
theme's dot; then the short name (`Card.title`, from `results.short_name`: the catalogue's
`SHORT_NAMES` in `help/indices.py`, such as "Hottest day", with the output's parameter
filled in, "Wettest 3 days" for `rx3day`; each heatwave aspect in the words of the
indices guide, "Number of heatwaves", the code saying which definition; the daily EHF and
ECF tables; the user's own index from its threshold, "Days TN > 0 °C"; a long name ends in
an ellipsis rather than widening the table). The short names were approved by the
maintainer on 17 November 2026. The six columns (#263, `views_indices._row`): Code,
Index (its full name in a `title` where it ends in an ellipsis), Slope per decade (signed,
by the number rules of #226, with its unit beside it, muted, after a no-break space:
"+5.15 days", a percentage's in percentage points, "+1.31 pp", the `pp` an `abbr`), 95%
interval ("3.79 to 6.54"), Significant ("yes" with the theme's dot when the interval
excludes zero; a dash, read "no", when it does not) and the series as a sparkline (headed
by its years, "1936–2015"; 9rem where the page is at least 86rem wide, 6rem narrower).
The Unit and Mean columns went with #263: the mean is in the detail pane. An index
without a trend shows a dash, and screen readers hear why: "Too few values", "No trend
line" (TX95t) or "Daily values". Rows are the data table's (#227): 32px, one line each,
in one frame, the table scrolling with the page. With the Sydney sample at 1280 x 1180 px
26 rows are in view and the table needs no sideways scroll at 1280px or wider; the
qc_stress file (`reference/input/qc_stress_1961-2020.txt`) leaves the Index column about
110px at 1280px, so long names end in an ellipsis there. Sparklines are SVG paths drawn on the server (integer
coordinates in a 240 x 60 box; long series averaged into 240 columns; gaps where values
are missing; the trend line dashed; SPI and SPEI as bars above and below zero;
`components/spark.html`), so the page loads no chart code.

The line above the table answers: "**22 of 80** indices with a significant trend · TMm
+0.19 °C/decade" (the mean temperature's slope, when it has one), beside the live line
("Showing 9 of 80 indices. Sorted by Slope per decade, descending.", or "Sorted by the
size of the trend, largest first." for the default; `aria-live="polite"`).
The filter rail at the inline start (`filter-rail`): "Find", a search that matches the
code, the short name, R's long name and the definition (`Card.search_text`); "Theme", a
list of plain rows (#263; the current one on `--color-selected` with an ink edge, as a
selected table row), All, Heat, Cold, Rain, Drought and "Also measured" (every other row, the
daily EHF and ECF tables included; `Card.chip`, `themes.chip_of`), each with its dot and
count (`?theme=`); "Significant only" (`?significant=1`); the line "Significant: the 95%
interval of Sen's slope excludes zero."; the help as a quiet link ("How to read the
table"); and at its foot the settings line (#178) and "Change the settings", which opens
the Index settings sheet. `js/results.js` filters as you type and keeps the state in the
URL; without JavaScript the rail is a GET form sent to the page and the server filters
(`dashboard_context`). Code, Index, Slope per decade and Significant sort the table
(`views_indices.sort_cards`, `?sort=code|name|trend|significance&dir=ascending|descending`,
and `size` for the default order):
codes and names A to Z first (case-folded, by code point; short names repeat across the
heatwave definitions, so names tie by code), slopes and significance largest first; other
ties keep the catalogue's order, and rows without a trend stay last when sorting by the
slope (a slope sorts by its value in the index's own units). Without JavaScript each header
is a link to the page sorted by it, the filters and the selected index kept, and the
rail's form keeps the sort and selection in hidden fields; `results.js` makes the headers
buttons and sorts in place the same way, `aria-sort` on the sorted column. Every row is
in the HTML whatever the filters hide, and an index page's breadcrumb ("Indices") returns
to its row, selected (`?show=<key>#index-<key>`).

**Indices: the detail pane** (`stations/index_detail.py`, `_index_detail.html`). Each
row's code is a link to `?show=<key>` (the filters and order kept); the server shows that
index's detail in the pane beside the table, the first row shown by default, and every
other detail is in the page, hidden (about 80 KB gzipped for the whole page with the
Sydney sample). With JavaScript the link shows the detail in place, marks the row
(`is-selected`, the link `aria-current`), keeps `?show=` in the address and announces the
index's name. The detail: the code and theme ("SU · Heat"), the short name as a heading,
the definition; a chart drawn on the server (`index_detail.chart`, SVG in a 380 x 200 box,
about the width of the pane's content (#263) so its ticks stay about 11px, the plot 50
units from the left for a tick of six figures): the series as a line in the theme's
hue (or SPI and SPEI as bars from zero; longer series averaged into 129 columns), Sen's
slope dashed across it (the core's intercept and slope, as the sparkline), the base period
of the run shown (`views_indices.run_base`, from the job's recorded metadata) as a band
labelled "base period", and axes: three values (the whole numbers around the data and the
middle) and three times (the first, the middle and the last). Since #283 it reads out each
value by pointer and keyboard and a year opens the index page at it (`?at=`;
`index_detail.readout`, see [Charts](#charts)). Its text alternative
(`index_detail.summary`) names the series, its years, the lowest and highest values and
when, and the slope and interval; the caption says "Annual SU (days), with Sen's slope
dashed.". Then six statistics in two columns (#263; one column when the pane's content is
under 20rem, as at 1280px): the slope per decade, its 95% interval, the mean over the
record ("Mean, 1936–2015", the mean of the values present, with the slope's places and
the index's units), whether the trend is significant in words ("Yes: the interval
excludes zero" or "No"), the years (or months) used, "79 of 80", and the method, "Sen's
slope (zyp)"; then the links: "Open full page" (the index's
page, with the interactive chart, its table view and CSV), the series' CSV and R's PNG,
and "Monthly values" (the index page's monthly series) where there is one. Side by side
from a 76rem page (#263): the rail 14rem (12.5rem until the page is 86rem wide, so the
names keep some room at 1280px), the table, the pane `clamp(22rem, 28%, 32rem)`; the
contents of the rail and the pane (`filter-rail__body`, `indices__pane-body`) sticky under
the header and the context bar, the pane's scrolling inside itself. From 48rem the rail beside the table
and the pane under it; narrower, the rail above the table (its themes a wrapping row), the
detail after it, focus moving to it, with "Back to the list" (hidden beside the table:
until #263 a later rule showed it there too). On a phone (below 40rem) each row is two
lines (code, name and sparkline; then the slope with its unit, interval and
significance) and the header a line of the sort buttons, by CSS only. Since #286 the row
is a wrapping flex line, not a grid of fixed columns: the cells take the width of what
they hold (the code at least 5.5rem, the slope 7.75rem, so the intervals line up; the
name takes what is left and ends in an ellipsis), `order` puts the sparkline on the first
line and an empty `::after` of full width breaks the line, and the significance sits at
the second line's end. What does not fit wraps whole to a third line (at 320px, "yes"
after a long slope and interval) instead of running into its neighbour, as the interval
did into "yes" in the old grid's 1fr column.

On the Indices the Inputs panel does not sit beside the section (#236), nor on Quality
since #264 (`station-page--inputs-bar`, the `_workspace.html` include's `edit_inputs`),
so the rail, table and pane have the width. Since #263 (Quality #264) "Edit inputs" at the end of the provenance line
(`stations/_edit_inputs.html`, the context bar's `provenance_end`) opens the Inputs sheet
where the page is at least 52rem wide; narrower, the Inputs bar under the tabs takes its
place (and the link is hidden). On wider pages the bar shows only while it says more than
the line: an input changed since the results shown (`inputs-bar--changed`) or a run under
way, with its "Undo". Without JavaScript the panel shows above the section, as on a
narrow page, and "Edit inputs" leads to it. Closing a sheet opened by an old address puts focus on the first visible link that
opens it (`js/sheet.js`): the panel's Edit, or on the Indices the settings line's link.

The themes (`Card.theme`, from `stations/themes.py`, the one place the mapping lives;
Decision C of #171, by the catalogue's short name, so parameterised outputs such as
`rx3day`, `r30mm`, `wsdi1` and `24month_spi` follow `rxdday`, `rnnmm`, `wsdid` and `spi`):

| Theme | Short names | Sydney cards |
| --- | --- | --- |
| Heat | su, tr, txge30, txge35, txx, tnx, tx90p, tn90p, tx95t, wsdi, wsdid, txdtnd, hw (the Tx90 and Tn90 heatwaves), hwEHF (the EHF heatwaves) | 30 |
| Cold | fd, tnlt2, tnltm2, tnltm20, id, tnn, txn, tx10p, tn10p, csdi, csdid, txbdtnbd | 12 |
| Rain | prcptot, sdii, r10mm, r20mm, rnnmm, rx1day, rx5day, rxdday, cwd, r95p, r99p, r95ptot, r99ptot | 13 |
| Drought | spi, spei, cdd | 9 |
| Also measured: Averages | txm, tnm, tmm, txgt50p, dtr | 5 |
| Also measured: Growing season and degree days | gsl, gddgrown, hddheatn, cddcoldn, tmge5, tmlt5, tmge10, tmlt10 | 8 |
| Also measured: Your own index | the custom index, with its definition | 1 |
| No theme ("Also measured" in the rail) | `EHFdaily`, `ECFdaily` (daily values, no trend) | 2 |

A test checks that every short name of the core's `climate.indices.csv` is in exactly one
theme, and that every card of the lat0 run has a theme or is one of the two daily tables.
Until #236 each of the four themes had a tile with a sentence written from its trends and
its three largest changes against the index's own variability (`Card.change`); the tiles,
the sentences (`themes.finding`, `themes.summary`) and that ranking are gone: the page
filters the data rather than narrate it. The page also lists, above the
rail and table, the index tables the core did not write (every value missing, the job's `skipped`) with the
likely reason: a variable the file has none of, a base period with too little data for
the percentiles, or else the missing-data rules. A run that wrote no index table at all
(a station whose TX, TN and PR are all missing, #268) has no rail, table or pane: above
that list the page shows the `empty_state` "No index to show", whose "Replace the file"
opens the File sheet, and `dashboard_context` selects no row. Its Indices tab, its row of
the workspace overview and the run status line say "No indices" instead of Done (#298,
`workspace.made_no_indices`: the run's `RunSource.has_tables` is false). The context bar carries the page's
two actions (#200, the Results mockup): "Compare with sector data" (secondary) and
"Download all (zip, *size*)" (primary); without a zip, "All files and the report" (the
Files page) takes the primary's place. The Files tab beside Indices replaces #173's
secondary link to Files. The labels are short ("Download all", not "Download
everything", on every page that offers the zip), which keeps the row on one line at
1280px with wider fonts too (#115). The zip is the page's one download of the whole run
(#176: the downloads card that listed the report, the PDF of all plots and the summary
files is gone; they are on Files); each index's detail links its own CSV and PNG (#236).
The settings used are one line since #178, replacing the "Settings used" card, at the
rail's foot since #236, and are changed in the Inputs panel's sheet since #199. The
sector comparison's section below the catalogue (#173) is gone: it is the header's
secondary action again (#200). Building the
cards reads every table and computes the trends (about 0.9 s for the Sydney run), so the
result is cached in memory (8 runs), keyed by the files' modification times, the
parameters and the language.

**Indices: one index** (`stations:result`, `result.html`, `stations/index_page.py`; #237,
the Index board). A drill-down from the Indices: the context bar
(`components/context_bar.html` with `title_template`, `lead_template` and `flow`: in the
page's flow, not sticky, with no tabs and no Inputs panel) has the breadcrumb (the station,
then "Indices", which returns to the index's row) with the previous and next index named
codes first ("← TXge35 Days TX ≥ 35 °C", "TNn Coldest night →", #218); the code and
short name as the h1 with the theme as a pill; the definition and unit, R's long name
when it differs from the short name ("Name in Climpact for R: Max TX.", `Card.r_name`),
where the index depends on a setting a link that opens it in the Index settings sheet,
and "About this index" (the help, a quiet link); the provenance line; and its files: the
series' CSV, R's plot ("PNG (R style)", when the run drew it) and "Copy citation"
(`index_page.citation`: the station, the index, its years and base period, the climpact
version and the date; a disclosure that shows the text without JavaScript,
`js/index-page.js` a button that copies it). A run of new inputs under way, or results
out of date, show as an alert under the bar.

The page shows one series: the annual one, or the monthly one where the index has it
(`?series=`, "Annual" and "Monthly" as a segmented control); a day-of-occurrence series
is not shown on its own but as the table's date column, and its old address opens the
main series. The chart is drawn on the server (`index_page.chart`, `_index_chart.html`),
like the detail pane's, in an 860 x 340 box: the base period as a band; round values
(`index_page.nice_ticks`) and years (the first, every 5, 10 or 20 years, the last) on the
axes, the y axis titled with the code and units ("TXx °C"); Sen's slope (the core's
`PlotTrend`, as the trend file and R's plots) dashed, and its 95% interval as a shaded
band between the lines of the lower and upper slopes through the slope's middle; the
values as a line with gaps where they are missing (bars from zero for SPI and SPEI); the
11-year running mean (`index_page.running_mean`: centred, where at least half the window
has values; 133 months for a monthly series); and each value left out as an open point
at the base-period mean. "Anomaly from 1971–2000" draws the same less the base period's
mean (`index_page.anomalies`: of the series, or for a monthly series of the value's
calendar month, so the anomaly is not the season); both charts are in the page and
`?view=anomaly` (or `js/index-page.js`, in place) shows the other. Not for SPI and SPEI,
which are standardised already, nor without a base period inside the series. Its text
alternative gives the years, the lowest and highest values and the trend
(`index_detail.summary`); the table is its table view and the CSV is in the context bar.
Below 32rem the chart scrolls inside its region. With JavaScript (#283) `charts.js` draws
the same marks from the page's data (`index_page.payload`) in its place, with the
read-out, zoom and move, Show all and PNG and SVG of the view, fitting the width at every
size; the server's chart is then the printed one (see [Charts](#charts)). `?at=<year>`
(`YYYY-MM` monthly) selects that row (`aria-current`, scrolled into view inside the
table's region) and reads the value out on the chart.

Beside the chart, "Trend": Sen's slope per decade and its 95% interval (#226 rules:
"+0.03 °C/decade", "−0.22 to 0.31", "pp" for a percentage), significant ("Yes, interval
excludes 0"), the years (or months) used, the base-period mean and the record with when
(`index_page.record`: the highest, or the lowest for TNn, TXn, SPI and SPEI,
`index_page.low_is_record`), each with the index's units (`numbers.with_unit`, #173, #189);
then why each value was left out (`index_page.left_out`, up to three named, then a count):
for a year, the days the station file misses of the variables the index needs (the most
of any of them, from the file's summary, `index_page.missing_days`): "1996 left out: 10
days missing, so the year fails the completeness rule" (the climdex rule, more than 15
days or a month with more than 3, see [Missing data](#missing-data)); a month after the
first value fails the monthly rule; a value before the first (SPI's and SPEI's first
months) or a year with no days missing simply has no value. Under them, the values as a
data table, most recent first (`index_page.table`): the year or month, the value, its
anomaly (one decimal, signed), its rank (1 the record, ties sharing the better rank), the
date of the maximum (or minimum) from the core's `day_of_` table where the index has one
(the day of the year, or of the month, as a date), and a note ("Record", or why the value
was left out). TX95t, a threshold for each day of the year, is drawn and listed in the
year's order, with no rank or record. The daily EHF and ECF pages list the ten highest
days instead of a chart. The trend file's rows, the standardised anomalies' chart and the
interactive chart of before #237 are gone from the page: the trend file is on Files.

**Files (#79, #176)** (`stations:downloads`, `stations/downloads.py`, `downloads.html`).
R's step 3 gives one link to the zip of the station folder (`singleStationStep3.R`,
`zipFiles`; the folder's path in the local app). Here every file of the station is on one
page, Files, each button labelled with its format and size (Django's `filesizeformat`, in
the interface language), for slow connections (`components/download_link.html`). Other
pages link to it instead of listing files (#176, DESIGN.md "Don't offer downloads
everywhere"): the Indices have one "Download all (zip)" (the Files tab beside it), Quality one link
under Details, an index page its series' CSV and R's plot (#237). The groups, in order:

- *The whole calculation*: the zip (R's layout, `zip_station`, with `climpact_run.json`
  added, #239: `stations:station_zip`, see [Workspace files](#workspace-files);
  "Download all", the page's one primary button, as on the Indices) and the PDF report (see [PDF report](#pdf-report)); one that
  was not made (unticked in the settings, or a job older than the report) says so and
  links to the Index settings sheet (#199).
- *Summary files*: the trend and threshold files.
- *Quality checks* (`downloads.quality_downloads`): the files of the Quality page's check
  (the `qc` job: each check's CSV and the missing values, in a closed disclosure, and
  their zip). The calculation's own `qc/` copies are the same files, written with the
  same thresholds, and stay in its zip; they are listed here only when there is no `qc`
  job (a station opened from a batch run).
- *Plots*: `<station>_all_plots.pdf`, and one line on where the rest are (each series' PNG
  in its index's row; the chart's PNG and SVG export of the current zoom on each index
  page, #75).
- *Sector comparison*, when the run shown has a finished sector comparison (#90, `views_sector.sector_job`):
  its `corr/` zip and each CSV and PNG, linked from the sector job.
- *Each index*: grouped as the dashboard, one closed disclosure per group (the File group
  pattern) whose summary gives the count of indices and their total size: for each series
  its table (CSV; the `day_of_` series point to the index's table, which holds the dates)
  and its PNG. Below 40rem each row becomes a block with its buttons side by side.
- *Other files* (`downloads.other_downloads`): any other file in the station's folder, so
  that every file the run wrote can be downloaded; empty for a normal run.

After the quality checks and before a calculation (or before "See results", #178), Files
holds the quality checks alone, with a link to the Indices; with neither, it redirects to
the Indices, and while a calculation runs, to its progress there. `test_downloads.test_files_page_reaches_every_file_of_the_station` walks both
jobs' output folders and the zip's members, and checks each is reachable from Files, and
that every file link on the Indices, an index page and Quality is on Files too.

Everything is a file a job wrote; the page only reads sizes (`stat`). The job page (each
file and the zip, `jobs.views.output_size`) and the workspace's Files (#239) show sizes
too; the station's zip is the one file made on request (#239: R's zip with the provenance
file added, kept with the workspace's files). The Sydney page is 119 KB of HTML, 42.1 KB gzipped with
its files.

**Recalculating keeps the user on the same index.** An index that depends on a setting
links to the Index settings sheet (#199), whose Apply returns to that index's page
(`next`); it stays there, out of date when the inputs changed, with the run's progress in
the Inputs panel, and reloads once the new run has finished. An old address with
`?settings=open&back=<key>` returns to the results URL with `?index=<key>`, which opens
that index once the new run has finished. When the
setting renames the index (`rx3day` to `rx7day`, a new SPI scale, a new custom index), it
is found by `results.signature`, which keeps the parameterised index, the extra SPI/SPEI
scale and the custom index together; an old index URL redirects the same way.

**Batch stations.** A station of a batch's workspace (`origin`, #255) shows its outputs
in the batch job (`charts.views.job_stations`, its own `skipped_outputs`) on the same
dashboard, with a note, until it is calculated again here; the Index settings sheet
starts from its metadata line's parameters and the workspace's custom index (none unless
changed). Its row on the workspace overview leads to this dashboard. An index page's
breadcrumb starts with the workspace (`workspace.workspace_page`) when it has several
stations, which leads to its overview, `/w/<id>/` (#234). A workspace of one station has
no workspace crumb, as `/w/<id>/` opens the station itself.
A station that failed in the batch says why on its Indices, above "Check the settings and
calculate" (`views_indices.batch_failure`).

R behaviour not copied in R's steps 3 and 4 (the settings and the results), and why:

| R step 3 | Python |
| --- | --- |
| A step of its own, hidden until the quality checks have run without error, and nothing calculated until "Calculate" | no settings step (#178): the indices are calculated with the defaults as soon as the station details are confirmed, while the checks run; "See results" opens the results; the settings are the Inputs panel's Index settings sheet (#199; "Adjust and recalculate" on Results from #178) |
| Parameters checked only when "Calculate" is pressed, one `need()` message at a time | every field checked as it changes, with the core's rules and the output name |
| A plot title is required | optional; empty uses the station title, as R's default does |
| The custom index is always calculated | on by default (R's TN > 0), and can be left out |
| Plots and zip always made | both on by default, each can be left out |
| One download: the zip of the station folder (or the folder's path) | the zip, a PDF report (not in R, beside the zip), the plots PDF and every file with its size on the Files page (#79, #176) |
| Results: a carousel of the PNGs and a link to the folder or zip | one line that answers, then every index in one dense table with its slope per decade, 95% interval, significance and sparkline, filtered by theme, significance and search, sorted by the size of the trend or by column (#200, #236, #263), the selected index's chart, statistics (with its mean) and links in a detail pane beside it (#236), an interactive chart per series with trend, anomalies and the trend file's rows, the tables not written and why |

**Sector data (#90).** Replaces the R app's step 4 (`singleStationStep4UI.R`,
`singleStationStep4.R`; the calculation is the core's `climpact.sector`, see
[Sector correlation](#sector-correlation)). `stations/views_sector.py`, one page at
`stations:sector`:

- *Before the indices*: R's "Please calculate climate indices." becomes an info alert
  with a link to the Indices (or to the progress while the indices job runs).
- *The form* (`SectorForm`, `sector_file.py`): R's inputs and defaults. The sector file
  (a drop zone around a file input; the help topic `sector.file`); "Title" (the station
  name, as R fills it in); "Label for y axis" (empty; `js/sector.js` fills it with the
  chosen file's name up to its first `_` or `.` as R does, and the server uses the same
  default, `default_y_label`, for an empty label); "Detrend data" (ticked). "Use the sample
  data" submits the same form with R's `wheat_yield_nsw_1922-1999.csv` (bundled, 795
  bytes) instead of a file, and the file can be downloaded (R links to it). The form
  starts from the last comparison's title and detrend setting.
- *The checks* (`inspect_sector_bytes`), before anything is queued, with the core's rules
  (`read_sector_file`): a header row whose first column is `Year`, exactly two
  comma-separated columns, a whole-number year and a number, empty, `NA` or -99.9 on every
  line, years increasing with none repeated, some values present. Each problem names the
  line of the file and shows it (at most 10, with a count of the rest; the station file's template
  `_problems.html`), with hints for a semicolon or tab separator and a decimal comma. It
  also checks what R checks only when it runs: at least 10 years in common between the
  station file and the sector file (`MIN_COMMON_YEARS`, years with a missing value
  counted, as R), quoting R's message "not able to make a correlation, since there is no
  data in common!". The accepted text is stored as UTF-8 without a BOM. A test checks
  the core reads every file the check accepts the same way.
- *The job*: a `sector` job on the run the results dashboard shows (the analysis's
  `indices_job`, or its batch station's outputs, `origin`), with the analysis's station
  file and the checked sector file copied into its `input/`, plots and zip on. A job
  queued earlier and not started is cancelled. While it runs the page polls
  `stations:sector_progress` (the progress bar, time, and four stages: read, correlate,
  write the tables and plots, zip), which answers `HX-Redirect` when it has finished. A
  sector job made from another run of the indices (the indices were calculated again) is
  not shown.
- *Errors*: a failed job shows its message in an alert above the form, open again. The
  core's `SectorCorrelationError` messages are R's, so R's case (an index with no year in
  common with the sector data) reads "Error: not able to make a correlation, since there is
  no data in common!", as R's `textOutput`, with a plain explanation.
- *Results* (`sector_plots.py`, `_sector_results.html`), read back from the job's CSV files:
  what was compared (column, file, detrended or not, years in common) and the zip of the
  `corr/` folder (`<station>_corr.zip`, R's `zipFiles(corrdir)`); the correlation with each
  index as horizontal bars from zero, temperature and precipitation indices in
  `--chart-tmax` and `--chart-prcp` with a legend, each value written at the end of its bar
  and NA at zero, in R's order or strongest first (`?order=strength`, a plain link); the four
  scatter plots (mean TN, mean TX, mean temperature, days above 30 °C against the sector
  series) with the least-squares line and R's equation and R² (rounded to 2 decimals, the
  numbers the PNG prints, from the job's result). Each chart has "View as table" (a native
  `<details>`; the index names link to their result pages), its CSV and the core's PNG.
  The settings fold into "Change the file or the settings" once there are results, as R
  collapses its "Settings" panel.
- *Why inline SVG, not the uPlot charts of #75*: neither chart is a time series; the page
  then loads no chart code (45 KB gzipped in all) and works without JavaScript. Points and
  bars carry `<title>` read-outs on hover; the tables are the keyboard and screen-reader
  view. On a phone the bar chart keeps a readable width (34rem) in a region that scrolls
  sideways.
- *Batch stations*: a station opened from a batch's results is compared with the batch
  run's index tables (the runner reads `<folder>/<station>/indices/` of the batch job),
  with a note saying so.

R behaviour not copied in the sector comparison, and why:

| R step 4 | Python |
| --- | --- |
| A plot title is required ("Please enter a plot title") | filled in with the station name as in R, and an empty title also means the station name, as in the index settings |
| The file is read only when "Calculate Correlations" is pressed; a malformed file gives an R error or, with years out of order, wrong numbers (see [Sector correlation](#sector-correlation-1)) | checked on upload, every problem listed with its line; fewer than 10 years in common is found before the job runs |
| Results: a carousel of the PNGs and a link to the folder or zip | the bar chart and scatter plots drawn on the page, each with its table, CSV and PNG, and the zip |
| The indices must have been calculated in the same session | the comparison uses the run kept for the analysis (or its batch station) for `JOB_RETENTION_DAYS` |

**Retention (per workspace since #231).** `WORKSPACE_EXPIRY`
(`CLIMPACT_WEB_WORKSPACE_EXPIRY`; on when hosted, off locally) decides whether workspaces
expire. When on, a workspace is deleted, with its stations, batches and their folders,
`JOB_RETENTION_DAYS` after its last change (`Workspace.updated_at`), unless a job of one
of its stations or batches is queued or running (`stations/retention.py`,
`purge_expired_workspaces`, run with every purge of expired jobs). When off, a workspace
stays until the user deletes it. The workspace's Files (#239,
`<MEDIA_ROOT>/stations/<workspace>/files/`) go with it (`Workspace.delete_files`), and the
purge's stray-folder sweep leaves a living workspace's folder alone. Either way the jobs a station or batch shows are kept
(`kept_jobs`): its checks, run and sector comparison, the finished run or checks a
replacement in progress, failed or cancelled replaces on the page (`params["replaces"]`),
a batch station's batch job (`origin["job"]`), and each batch's job. So results never
disappear under a page; a replaced job is purged on its own schedule once its replacement
has succeeded. Other jobs (replaced runs no longer shown; gridded runs' where they
expire, see [Gridded pages](#gridded-pages)) keep the jobs app's rule. Folders under `stations/` and `batches/` that belong to no station or batch
are deleted once older than the period. With expiry on, the pages state the period and
the date the workspace will be deleted; with it off, that the data stay on this computer
until deleted. "Delete this data now" deletes the station at once, and its workspace if
nothing else is left in it (`test_workspace.py`: `test_retention_keeps_the_jobs_a_station_shows`,
`test_retention_deletes_the_workspace_once_idle`,
`test_without_expiry_nothing_a_workspace_shows_is_deleted`).

### Add stations

Add stations (#233, boards `AddStations.dc.html` and the drop zone of `Start.dc.html`) is
the one way into a workspace, for one station or many; New station and the batch's first
page lead to it. `stations/views_add.py`, `stations/add_stations.py`,
`stations/templates/stations/add.html`, `js/add-stations.js`.

- **Addresses.** `/add/` starts a workspace: the drop zone, the file format and the
  settings every station will share. "Use the sample station" (`/add/sample`) adds the
  Sydney sample, named "Sydney Observatory Hill" (#219), to a new workspace and opens its
  Quality, checked and calculated at once. `/w/<id>/add/` adds stations to a workspace.
  Dropped files wait at `/w/<id>/add/<files>/` for review; `/add/sample-batch` (the help's
  "Use the sample batch") puts R's sample batch there.
- **Waiting files** are a `BatchRun` of the workspace with no job: its `files/` folder and
  `metadata.txt` as a batch keeps them. Each station file is read once, when it arrives
  (`add_stations.read_files`, the single-station check `inspect_station_bytes`), and what
  was found is kept in `BatchRun.report`: `files` (each file's problems, warnings,
  repeated dates and short summary, in the order they came), `metadata` (the metadata
  file's stations by file, read with `batch.check.check_metadata`, and its problems),
  `upload_problems` (`batch.check.unpack`: a zip that cannot be opened, two files of one
  name) and `edits` (what was typed in the table). A file of the same name replaces the
  one before; a later metadata file replaces the earlier one. Loose files and zips are
  taken alike; a metadata file is recognised by its first line (`looks_like_metadata`).
- **The review table** (`add_stations.review`), a row per station file and one per
  metadata line whose file did not come: the file, the station name, latitude and
  longitude (inputs), the period, the days, the index settings ("Defaults", or the
  metadata line's values that differ from the workspace's, "Custom (wsdin 4)"), and Read.
  Every problem is found in one pass: a file that cannot be read ("Not read: line 1 has 4
  values, expected 6 (year month day PR TX TN)", the problem's `short` text, and how many
  more), a missing or out-of-range latitude or longitude, a station name missing, not
  allowed or given twice, a metadata value out of range (`batch.check.parameter_problems`,
  R's `validate_climdexInputParams`), a base period the data do not reach. The name and
  coordinates are checked by the New station form's rules (`stations.forms.MetadataForm`).
  Repeated dates, a base period the data barely cover and the other file warnings are
  warnings, not problems. Default names come from the file (`tidy_name`: no extension, no
  trailing year range, underscores as spaces, lower-case words capitalised), coordinates
  from the metadata file. The line under the table names the problems in a sentence; a
  disclosure lists every problem and warning with its line in the file.
- **One form** holds the drop zone, the table and (through `form="add-form"`) the settings
  panel, so whatever is sent keeps what was typed: more files, the sample, the settings,
  Cancel or "Add N stations and check them" (`intent=add`), the only one that adds. Enter
  sends the form's default button, a hidden "Check the table" (`intent=check`): from a
  cell without JavaScript, or from a field of "Change workspace settings" (outside the
  form, with `form="add-form"`), with or without it. `review_page` treats it as Apply
  (#318): what was typed is kept, valid settings are applied ("The settings are changed
  for every station."), settings that are not valid come back with why and the panel
  open, and the review page opens again, checked. A form sent with no intent, or one the
  page does not know, also goes back to the review page. Without JavaScript the files go
  with "Add the files". With it a chosen or dropped file is
  sent at once, the table is checked as it is typed (`add_check`, JSON: each row's state,
  the line under the table and the button's label; what was typed is kept), a column
  pasted from a spreadsheet fills the cells under the one pasted into (two columns,
  latitude and longitude, fill both), and Enter moves down a row.
- **Adding** takes the complete rows; the others stay out. One row becomes a station of
  the workspace with its own jobs, as New station did: its checks and a speculative run
  (`calculation.bring_up_to_date`), then its Quality. Added to a workspace that has other
  stations, its run is the user's own at once, as a batch's stations' are (#277: the
  station is at `Step.INDICES` before its jobs are queued, so the run is an ordinary job),
  and the workspace's page opens. Its metadata line's index values are its own (`origin["params"]`).
  Several rows run as a batch that fills the workspace (`add_many`, `batch.fill`): the
  waiting files become the batch, a `batch` job with the workspace's base period, custom
  index and plots, each station named in the batch by its file's stem (made safe and
  unique, as R names a batch's stations and their folders), with the name the user gave
  as its station name (the job's `names` parameter, so `fill.batch_inputs` records it and
  the results are current). A station's own index values are only its metadata line's
  (`own_params`), the job's metadata file has the workspace's for the rest. Each station's
  quality checks are queued beside the batch as one change for the hosted limits; the
  workspace's address shows its overview (#234), with the stations checked and calculated
  as they go. Either way, a station that was in the workspace before and whose run was
  still speculative (a workspace of one, before "Go to indices") is put in use as "Go to
  indices" would (`calculation.commit_workspace`, #277): a workspace of several stations
  has chosen to calculate, and its overview, Files and trend grid show every station's
  results. A batch's stations are left to their batch.
- **Settings.** The panel "Applies to every station" lists the base period, the
  thresholds, the index settings and the plots. While the workspace has no station they
  change in place ("Change workspace settings": the base period, the plots and PDF
  reports and, locally, the stations calculated at the same time); afterwards a change
  recalculates every station and is made from a station's Inputs or the workspace's
  Workspace settings (#234). Below 90rem the panel is one line above the files, so the
  table keeps its eight columns without scrolling sideways at 1280px. A workspace started
  here has the default settings, the custom index included, for one station or many.
- **Cancel** deletes the waiting files, with a workspace that holds nothing else.

### Batch page

The batch (#80) replaces the R app's batch screen (`climpact/modules/batchStep1UI.R` and
`batchStep1.R`): many stations from R's batch metadata file, run as one job. Since #233
its first page and check page are [Add stations](#add-stations)'s, and stations added
there run as a batch; #271 removed the batch's own pages (the upload page `/batch/`, the
check page `/w/<id>/batch/` with its add files, options and run forms, and the sample and
delete forms; `batch/start.html`, `check.html`, `_options.html`, `_retention.html`,
`UploadForm`, `AddFilesForm`). Its results are the workspace's overview since #234
([Workspace overview](#workspace-overview)).

**Addresses** (`batch/urls.py`): `/batch/` and `/batch/sample` lead to `/add/`, GET or
POST; `/batch/sample-metadata.txt` downloads R's `climpact.sample.batch.metadata.txt`
(bundled unchanged in `batch/sample_data/`; R links to it) as a template, and Add
stations' "Use the sample batch" (`/add/sample-batch`) puts it with two copies of the
Sydney file, under the two names it lists, on Add stations' review (R ships the same file
twice; the package keeps the one gzipped copy of the single-station sample).
`/w/<id>/batch/` (`batch:check`, the check page until #271; `/batch/<id>/` before #256,
which redirects) leads to the files waiting on Add stations, to `/w/<id>/` once they were
added, or to Add stations for a batch the old upload checked and never ran.
`/w/<id>/batch/results` (and `/batch/<id>/results`) lead to `/w/<id>/`, where the
workspace's overview (#234) shows the `batch` job of the stations added: the run status
line and a Stations-table row a station, polled while it runs. The batch results page,
its progress fragment, per-station downloads and "What is in the zip" went with #234;
each station's files are on its Files tab, and the workspace's are Files' (#239).

**Data model.** A `BatchRun` (`batch/models.py`): UUID; `owner` (the job owner token: any
other session gets 404); `source` (`upload`, `sample`); `metadata_name` (as uploaded); the
review of Add stations as JSON (`report`, `stations/add_stations.py`, with the `stations`
`add_many` queues); the run options `workers`
and `plots` (the base period is the workspace's since #255); `job` (null on delete);
`filled_job`, the run whose outcome was recorded on the workspace's stations (#255, null
on delete). Files live in
`<MEDIA_ROOT>/batches/<id>/`: `metadata.txt` and `files/<name>`, each station file under
its own name without folders (hidden names are ignored). Every change checks the whole
batch again. Since #231 a batch has a `workspace`, made with it, and is deleted with it
(see the retention of workspaces in [A station's pages](#a-stations-pages));
`batch/retention.py` deletes only stray batch folders. The batch and its stations share
their workspace's retention, and deleting the workspace deletes them (#274; the batch
page's own "Delete these files now" went with #271).

**Reading the files** (`batch/check.py`). Add stations reads a metadata file with its
`check_metadata`, zips with `unpack` and a metadata line's index values with
`parameter_problems`, and `metadata_text` writes the job's metadata file. The old check
page's whole check (`check_batch`: each station *ready*, *file missing* or *has problems*)
and the "not run" stations it made were removed in #311 (decision of 2026-11-20): Add
stations adds only rows it can run, so its batches never leave a station out, and the
batches of the old upload do not outlive their workspace's retention. The tests make their
batches at model level with every station's file (`tests/made.py`'s `batch`).
The metadata file is walked with
`read_batch_metadata`'s rules (whitespace-separated fields, `#` comments and blank lines
skipped, the first line the header) and every problem is reported in plain language with
its line and the line's text, as the station file check does (`stations/station_file.py`): empty or not text, no
stations, a line without 12 values (with a note when commas are used), a value that is not
a number, a whole-number column (`wsdin`, `csdin`, `rxnday`, `txtn`, `SPEI`) with a
fraction, two lines giving the same station name. A test checks that the core reads what
the check accepts to the same stations. Any of these makes the metadata file unusable, as
`read.table` stops R's whole batch. A first line that looks like a station (12 fields, a
number second) is a warning: R and the core read it as the header, so that station is
left out. `parameter_problems` applies R's `validate_climdexInputParams` rules (the same
as `climpact.batch.validate_params`, checked against it by a test).

**Options** (`batch/forms.py`'s `OptionsForm`, Add stations' "Change workspace
settings" since #233). The R screen's base period (here 1971-2000 by default) and, in the
local install only, the number of cores ("Stations to calculate at the same time", 1 to
the number of cores, R's messages for both limits), plus a "Draw the plots of every index
and write each station's PDF report" checkbox. The old check page's live check of them
(base period coverage, a time estimate) went with #271; Add stations' review checks each
station's coverage of the base period instead.

**The job** (`views_add.queue_batch`, #271: `add_many` and the tests' batches share it).
The job takes the workspace's base period and custom index (`custom`, none for a batch's
workspace unless its settings were changed) and the run's `workers` and `plots`. It
writes a metadata file in R's format with the stations (`check.metadata_text`, numbers written so they read back the same) and copies
their files as UTF-8 to `input/stations/`, then queues a `batch` job with `zip`,
`station_zips`, `report` (with the plots), `folder` (the metadata file's name without its extension, as R names the
batch folder and zip). The runner runs `run_batch` (a failing station fails alone, its error in R's error
file); zips each finished station to `output/stations/<station>.zip` (as R's
single-station zip) and the whole batch folder to `output/<folder>.zip`; with `report`,
`run_batch` writes each station's PDF report to `output/reports/<station>_report.pdf`,
outside the batch folder, so the zip keeps R's layout. During the run
`BatchStatus` writes each station's state to `output/stations.json` (atomically, when a
station starts or ends and at most every 0.5 s), which the progress fragment reads; at the
end the job's `result` lists each station with its files, error, error file, zip and
report. The overview's run status line offers the whole zip with its size. A
station's error is shown without the exception's class name or the job folder's path.

**A batch fills its workspace (#255, `batch/fill.py`).** A batch is a way to fill a
workspace, not a separate kind of result (#230, decision 5). Every station of its metadata
file is a `Station` of the batch's workspace, whether it calculated or not: the workspace
overview (`Calculate.dc.html`, #234) has a Stations-table row for each, with its run state
(Done, Calculating with its percentage, Waiting, Not run once its batch job was cancelled,
Failed with why).

- *When the run is queued* (`queue_batch`), `add_stations` adds them all: `source` `batch`,
  name, location, slug and the station file (from the batch's `files/`, when it can be
  read), and `origin = {"batch", "station", "params", "run"}`: the batch, the station's
  name in it, the `IndexParams` fields of its metadata line, and its state in this run
  (`{"job", "state", "error"}`). Each station is `waiting`, at step `qc` (its address
  leads to Quality, its checks not yet run). The job gets `stations_added`.
- *When the job is cancelled* (Cancel on the run status line), a station still waiting on
  it is `not_run` with "The run was cancelled." (`run_states` reads it from the job, so
  nothing is recorded).
- *When the job has succeeded*, `fill_workspace` records how it went, the first time the
  workspace's overview or its polled fragment is shown, or one of its stations is opened
  (`stations.views.filled`, through `get_analysis`, for a station opened first). A station that calculated gets
  `origin["job"]`, `["outputs"]` (its folder in the job's `output/`) and `["inputs"]`
  (`batch_inputs`: the file and details the job was given, the run's base period and custom
  index, R's default thresholds, the workspace's output options, as `plots` is a run
  option and not an input of the results), and `run.state` `done`. One that failed gets
  `failed` with R's or our error in words (`plain_error`: no exception class or job path)
  and no results: not the batch's, nor an earlier run's. It is at step `indices`, so it
  opens on Indices, which say nothing was calculated and lead to the settings, where the
  fix usually is (another base period). It is idempotent (`BatchRun.filled_job`, under a
  row lock); a station the user deleted during the run is not added again. A job queued
  before `stations_added` adds its stations here, as they would have been when queued.

A new run of the batch updates its stations when queued (file, details, `run` waiting)
while they keep the results they show, out of date if their inputs changed, until the new
run's replace them (with the station's own jobs from before the run). `run_states(stations)`
gives each station's `RunState` (state, percent, error, job): its own run when one was
queued after the batch's (a change to the workspace's settings, #254), else its batch
run's, live from the runner's `stations.json` while the job runs (`station_status`).
`run_progress(run)` gives the run as a whole for the run status line: done of total,
failed, calculating, waiting, elapsed, remaining, finished.
A settings change has its own, `workspace.change_state` (#254). The overview's run status
line sums up the stations' `RunState`s instead, so a batch and a recalculation read the
same. Each row links to the station's furthest section. A change to the workspace's
settings recalculates the batch's stations like any others (#254), each with its own
metadata values, as one change for the hosted limits; their Quality has no checks until
then, so that change queues their checks too. Stations without a file are skipped. This
keeps one dashboard implementation (the single-station steps) rather than a second one for
batches.

R behaviour not copied, and why:

| R batch screen | Python |
| --- | --- |
| Base period defaults to 1970-2010 | 1971-2000, as R's single-station screen, the command line and WMO's reference period |
| Number of cores defaults to 1 | up to 4, one core left free and no more than the stations; 1 when hosted (where the option is hidden, as in R) |
| A station listed but not uploaded is skipped silently; problems appear only after the run, in error files | Add stations' review lists every file's problems before anything runs, and adds only the rows that can run |
| A bad parameter or malformed metadata line stops the whole batch | a malformed metadata file is reported line by line before anything runs; a bad parameter blocks only its station's row |
| Plots are always drawn | a setting of the workspace (plots and reports are about two thirds of the run time) |
| One zip of the batch folder | the same zip, each station's own zip and its PDF report |
| Station files only as separate uploads | separate files or zips, with the metadata file in the zip if wanted |

### Workspace overview

A workspace of two or more stations opens on its overview, `/w/<id>/` (#234; boards
`Workspace.dc.html` and `Calculate.dc.html`; `stations/views_workspace.py`,
`stations/overview.py`, `stations/workspace.html`). It replaced the batch results page and
the batch steps.

- **The workspace's context bar** (`stations/_space_bar.html`, through
  `components/context_bar.html`): "Workspace", the name (`Workspace.display_name`) as the
  h1, the provenance line (`views_workspace.bar_context`: the station count, the base
  period, "ET-SCI defaults" or how many thresholds and index settings are not the default,
  the climpact version, "kept until" the deletion date where workspaces expire) with
  Workspace settings and Rename at its end, Add stations, and the tabs Overview, Compare an
  index (#238) and Files (#239). Export ▾ (#239, `_space_actions.html`) on
  the overview, Compare an index and Files: Everything (zip), the trends and indices of all stations (CSV),
  and All files; until every station has finished it says the files are not made yet.
- **The run status line** (`overview.status_line`): from the stations' rows. While any
  station waits or calculates: "Calculating indices: 3 of 5 stations done." with the
  batch job's time left, a bar (the finished stations plus each calculating one's
  percentage) and Cancel (the batch job, `jobs:cancel`) or "Undo the change" when a change
  to the workspace's settings can still be undone (`stations:workspace_undo`,
  `calculation.undo`). Once finished, quiet: how many were calculated and in how long
  (from the first job's start to the last one's end) and the stations not run and why.
  The batch's zip is no longer offered here (#239): Export ▾ and Files have the
  workspace's files, made from whatever each station shows.
  Red when one failed: it is named with its error, and Workspace settings is offered.
  Stations not run (`not_run`, their batch job cancelled) are not counted in the total. A station
  whose run made no index table (#298) has finished but is not counted as calculated:
  "1 of 2 stations calculated in 16 s. Empty Hill has no indices: every value is
  missing." (the reason when the job's `skipped` lists the indices; "2 stations have no
  indices; their rows say how to fix them." for several), still quiet unless one failed.
- **The Stations table** (`overview.rows`), in the order the stations were added
  (`overview.ordered`: `created_at`, then name): the name (a link to the station's
  furthest section, `workspace.home_url`), coordinates, years, the share of all values
  missing over PR, TX and TN, the Quality verdict with its count (`workspace.qc_verdict`;
  "Checking…" while the checks run; "–" without checks), the indices state
  (`batch.fill.run_states`; a station of no batch with no run of its own uses its Indices
  tab's state; a station's own run that is not in use yet, before "Go to indices", is not
  shown, as its Indices are locked: "–", #277; "Out of date" instead of Done when the
  results shown are from before a change, `workspace.run_changes`, its replacement
  cancelled, #279; "No indices" when the run shown made no index table,
  `workspace.made_no_indices`, every index skipped as for a file whose TX, TN and PR are
  all missing, muted as "Not run" is, `Indices.empty` and `data-indices="empty"`, #298)
  with its fix ("Replace the file" for a station with no indices, the File sheet's page,
  `workspace.sheet_url`; "Fix the file" for one not run without a usable file,
  "Fix quality first" for one not run whose verdict is Fix first, "Change base period"
  when a failure names the base period), and how many of its indices have a significant
  trend, "22 of 80" (`results.results_for`, cached, the same count as the Indices'
  answer line), counted from the results the station's Indices show (`workspace.shown_run`),
  as Files and the trend grid are, so the four agree (#277).
- **Trends across stations** under the table (#238, [Trends across
  stations](#trends-across-stations)).
- **Live.** While a station waits, calculates or is checked, `#workspace-progress` (the
  status line, the table and the trends) polls `stations:workspace_progress` with the job page's
  delays (`poll_delay`), which records a finished batch first (`fill_workspace`); it stops
  once nothing is on the way, and asks for a reload (`HX-Refresh`) when the workspace is
  down to one station. Focus on Cancel survives the swap (`ui.js`), and the first sentence
  is announced, at once when the run has finished.
- **Rename** (`stations:workspace_rename`): a page with the name; empty gives the default
  back ("6 stations, 17 Nov", or the one station's name).
- **Workspace settings** (`stations:workspace_settings`): the base period, quality
  thresholds and index settings as the Inputs panel lists them; each Edit opens its form
  on a page of its own (`stations:workspace_setting`, the Inputs panel's form,
  `_input_form.html` with `action`), which applies it through
  `calculation.change_settings` with the first station as the change's anchor (it changes
  every station, as the station's sheets do) and returns to the overview. The base period
  is not checked against one station's data here: a station that does not cover it fails
  in its run and is named in red. The index settings start from the workspace's
  (`workspace.workspace_settings`), so a station's own metadata-line values stay its own.
- **Station pages** in a workspace of several stations start their context bar's
  breadcrumb with the workspace and "Station 2 of 6", with the previous and next station
  (`workspace.station_nav`); a workspace of one station has "Add stations" at the end of
  the provenance line instead (`stations/_station_links.html`). Every station set up has
  "Copy to workspace…" there too, and "Copy…" at the end of its row of the Stations table
  (#241, [Copy to workspace](#copy-to-workspace)).
- **A workspace that is not here** (another browser's, deleted or never made): any
  `/w/<id>/…` address gives 404 with "This workspace is not here", how long workspaces
  are kept where they expire, and Add stations (`404.html`, from the URL's
  `workspace_id`), without saying whether another session's exists.

### Copy to workspace

"Copy to workspace…" (#241; the Flow board's rules: "Copy to workspace… from a station to
put it in another; it is recalculated with that workspace's settings";
`stations/copy_station.py`, `stations/views_copy.py`, `stations/copy.html`) puts a copy of
a station in another workspace of this browser's, or in a new one. It is offered at the
end of a station's provenance line (`stations/_station_links.html`, `copy_url` from
`workspace.context`) and as "Copy…" at the end of each row of the workspace's Stations
table (`overview.Row.copy_url`), for a station that is set up (`workspace.set_up`: a file
and details that fit it). The page, `/w/<id>/<station>/copy` (`stations:copy`), is a page
of the station, under its context bar: the workspaces that hold a station, changed last
first, each with its name, station count (unless its default name says it) and base
period, and "A new workspace, with this workspace's settings"; Copy and Cancel (back to
`next`, the page it was opened from).

- **What is copied:** the station file, its name and location, its file name, summary and
  warnings, and its own index values (a batch metadata line's, `origin["params"]`).
  Nothing of its jobs or the batch it came from: its checks and run are queued again
  (`calculation.bring_up_to_date`) with the settings of the workspace it goes to. The
  station copied, its jobs and its workspace are not changed.
- **A new workspace** starts with the settings of the station's workspace (base period,
  thresholds, index settings), so the copy gives the same results until they are changed.
  The copy's run is in use at once if the station's was (`workspace.committed`, "Go to
  indices"); then it opens on its Indices, else on its Quality.
- **An existing workspace** has several stations after the copy, so the copy's run, and
  any station's there still speculative, is in use at once (`calculation.commit_workspace`,
  #277), and its overview opens with a message. A workspace that has a station of the same
  name (any case) is marked in the list and refused with why: the results are named after
  the station.
- The hosted limits are checked before anything is copied (`check_job_quotas`), and the
  page's form carries the Turnstile widget (`human_required`).

### Landing page and Workspaces

The landing page, Get started and Workspaces (#242; the Landing, Start, WorkspaceList and
Flow boards).

- **Landing page** (`core/templates/core/home.html`, `core.views.home`, `core/landing.py`):
  bands across the window (the base template's `bleed`: no width or gutter on the main's
  container, each band's content up to 77.5rem). A returning visitor (a session with a
  workspace) gets "Welcome back. Continue with <the workspace changed last>" and All
  workspaces (`workspace_list.latest`). The hero has Get started (`/add/`, also at the end
  of the header from 40rem, the `header_action` block) and "See an example: Sydney,
  1936–2015", a POST to `stations:add_sample` with `show=indices`: the sample is added and
  checked as "Use the sample station" does, its run is made the user's at once
  (`calculation.commit`, as "Go to indices"; a run the hosted limits refuse leaves the
  Indices offering to calculate it) and its Indices open. The preview beside it is the
  sample's real output, read from `charts/sample_outputs/sydney` (Climpact's files for
  the sample, text-identical to R's): TXx drawn as the Indices' detail pane draws a series
  (`index_detail.chart`, with its text alternative), and SU, TR, TN10p and PRCPTOT as rows
  of the Indices table (slope per decade, `pp` for a percentage, 95% interval,
  significant), all from the core's trend fit (`results.trend_summary`), cached per
  language. The facts are constants in `core/landing.py`, from the parity summary: 80
  indices; 16 reference datasets (14 stations and the `lat0` and `qc_stress` test cases);
  all 1,791 CSV files written for them text-identical to Climpact for R 3.4.3. A test checks
  the run counts and the R version against `reference/stations.csv` and the reference
  output when the repository is there. "How it works" has three miniatures of the real
  screens (hidden from screen readers), whose values are the reference runs' own (three
  reference files and coordinates; `qc_stress`'s verdict, "Usable · 21", and three of its
  findings; the trend grid of Sydney, Perth and Darwin). Then What you get, What you need
  (the format, the template and the metadata file's guide) and a closing Get started with
  the retention sentence. The first-run tour (#81) stays, with its steps updated.
- **Get started** is Add stations' empty page (`/add/`, #233). A returning visitor also
  gets "Or continue a workspace": the three workspaces changed last (Name, Stations,
  Updated, and "Deleted on" where workspaces expire) and All workspaces
  (`views_add.start_context`, `RECENT`).
- **Workspaces** (`/w/`, `stations:workspaces`, `views_workspace.workspaces_page`,
  `stations/workspace_list.py`, `stations/workspaces.html` and `_workspaces_table.html`)
  replaced "Your calculations" in the header. Every workspace of the session (`owner`),
  most recently changed first, in one data table: Name (a link to the workspace, with a
  hint under it: one station's years, several stations' first two names "and N more", or
  the files waiting to be added on Add stations), Stations, Status (one station: its
  Quality verdict pill with its count, as its tab; several: the counts by verdict, "2
  ready", "1 usable", "1 fix first", "1 checking"; and "1 failed" for the stations whose
  indices failed, as their Stations rows say: a speculative run is not counted), Base
  period, Updated ("today 09:42", "yesterday 16:10", "15 Nov"), "Deleted on" where
  workspaces expire (`WORKSPACE_EXPIRY`; in warning colour with "in 2 days", "tomorrow" or
  "today" when under three days away), Save file (#240, for a workspace with a station set
  up) and Delete. "Open a workspace file" sits beside "New workspace", and a note under the
  table says what Save file does. Locally the lead says the workspaces stay until deleted;
  hosted, a second note says how it differs on one's own computer.
- **Delete a workspace** (`/w/<id>/delete`, `stations:workspace_delete`,
  `views_workspace.delete_workspace`, `stations/workspace_delete.html`): a page naming its
  stations and saying they can't be recovered, then a POST that cancels the jobs still
  queued or running for it, deletes its files (`Workspace.delete_files`) and the rows,
  and returns to Workspaces. Another session's workspace is 404. The workspace's Files
  link to it too ("Delete workspace now", #274, with `?from=files`, so Cancel goes back to
  Files; Cancel goes to Workspaces otherwise). `delete` is a reserved station slug.
- **Keep a workspace longer** (`/w/<id>/keep`, POST only, `stations:workspace_keep`,
  `views_workspace.keep`, #274): "Keep 7 more days" on the workspace's Files where
  workspaces expire (`WORKSPACE_EXPIRY`). It counts the workspace as changed now
  (`Workspace.touch`, `updated_at`), so `Workspace.expires_at` and the deletion by
  `stations/retention.py` move to `JOB_RETENTION_DAYS` from now (the label names that
  number), then returns to Files with a message naming the new date, which the context
  bar's "kept until" and "Keeping the files" show. Locally (no expiry) there is no Keep and
  the URL is 404; another session's workspace is 404. Like Rename and Delete it starts no
  job, so it is not in the Cloudflare rate limit (`deploy/cloudflare/rate-limit.txt`, the
  job-starting URLs only). `keep` is a reserved station slug.
- The page-not-found page at a workspace's address leads to Workspaces and to a new
  workspace; the refused page (#125) to Workspaces.

### Workspace file

Save file and Open a workspace file (#240; the WorkspaceList and Start boards;
`stations/workspace_file.py`, `stations/views_workspace_file.py`,
`stations/workspace_open.html`). Hosted workspaces are deleted after the retention period
and belong to one browser; the file keeps one, or moves it to another computer.

- **Save file** (`/w/<id>/workspace.zip`, `stations:workspace_file`, on each row of
  Workspaces) downloads `climpact_workspace.zip`, made in a temporary file and streamed:
  - `workspace.json`: `format` `climpact-workspace`, `format_version` 1 (`FORMAT_VERSION`),
    the software, when it was saved, the workspace's name, its settings with every value
    filled in (`base_period`, `quality_thresholds`, `indices` in `workspace_settings`
    form), and each station: its name, its entry (`stations/<slug>.txt`), its original
    file name, the SHA-256 of the file (`Station.file_hash`), latitude, longitude, years,
    its own index values (`workspace.own_params`), whether it is the sample and whether its
    results were in use (`workspace.committed`).
  - `stations/<slug>.txt`: each station's file as the workspace keeps it.
  - `metadata.txt`: the stations in R's batch metadata format (`check.metadata_text`, each
    with every index value it is calculated with), so `stations/` can be run as a batch
    in Climpact for R. Opening ignores it.
  - `climpact_run.json`: #239's provenance file (`workspace_files.provenance`).
  Only stations that are set up (`workspace.set_up`) are saved; a workspace with none has
  no Save file (the address returns to Workspaces with a message).
- **Open a workspace file** (`/w/open/`, `stations:workspace_open`) is a page of its own,
  from Workspaces' "Open a workspace file" and Get started's "Or open a saved workspace
  file": the file field, the Turnstile widget (`human_required`; the page works without
  JavaScript) and Open. `open_into` makes a new workspace of this session with the saved
  name and settings (none stored where they are the defaults) and adds the stations
  through Add stations' own routes: their files wait in a `BatchRun` with a report built
  from the manifest (each file read once, `add_stations.read_file`; the metadata rows
  carry the locations and own index values, the edits the names), reviewed by
  `add_stations.review`, then one station is added by `views_add.add_one` (and its run is
  made the user's again, `calculation.commit`, when it was in use; it opens on its
  Indices, else its Quality) and several by `views_add.add_many` (a batch; the overview
  opens). A batch runs with R's default quality thresholds (`batch.fill.batch_inputs`), so
  when the workspace has its own each station is also queued as a station run
  (`calculation.refresh`) in the batch's change, which `add_many` now returns: one job for
  the hosted limits. The limits are checked before anything is made
  (`check_job_quotas`); a refusal by them, or by the review (a row that Add stations would
  not add, named with its problem), makes nothing.
- **The zip is untrusted** (`read`). Each refusal is a `NotAWorkspaceFile` with a plain
  message under the field, and nothing is made: not a zip; over the upload limit
  (`MAX_UPLOAD_MB`, the middleware's 413, checked again on the upload); no
  `workspace.json` (a zip of station files is pointed to Add stations); more than
  `MAX_ENTRIES` entries (`check.MAX_FILES` stations and the others); an entry that is not
  part of the format (only `workspace.json`, `metadata.txt`, `climpact_run.json`,
  `stations/` and `stations/<slug>.txt` with a slug's characters are allowed), with a
  backslash or NUL, an absolute path or drive letter, `.` or `..`, a symbolic link, the
  encrypted flag, a compression other than stored or deflated, or a name given twice;
  more uncompressed data than `MAX_UNPACKED_BYTES` (`check.MAX_UNPACKED_BYTES`, 500 MB) in
  all, `MAX_STATION_BYTES` (64 MB) in a station file or `MAX_MANIFEST_BYTES` (4 MB) in the
  others, checked against the header first and then counted while each entry is read in
  64 KB chunks, with an entry that unpacks to more than `MAX_RATIO` (200) times its
  compressed size past its first megabyte refused as a zip bomb (a header that understates
  a size fails zipfile's CRC check, "cannot be read"); `workspace.json` not UTF-8 JSON
  (`NaN` and `Infinity` refused) or not an object; another `format`, a missing
  `format_version` or a newer one ("saved by a newer version of Climpact (format 2; this
  one reads format 1)"); settings the settings pages would refuse (the base period's two
  years in order, `QCParamsForm`, `IndexParamsForm`, booleans for the output options); no
  stations, more than `check.MAX_FILES`, a station without a name or numeric coordinates,
  own index values that are not `IndexParams` fields with numbers, a station file missing
  or listed twice, a station file whose SHA-256 differs from the saved one, a station file
  in `stations/` that no station lists; and whatever Add stations' review refuses (an
  unreadable file, a coordinate out of range, a name given twice, a base period the data
  do not reach). The station's original file name is only used once made safe
  (`safe_file_name`: no folders, letters, digits and `._()- `).
- `tests/test_workspace_file.py` saves and opens a batch workspace with a failed station
  and compares its stations, settings and trends after both are calculated, and tests
  each refusal.

### Workspace files

The workspace's Files tab, `/w/<id>/files/` (#239; board `Files.dc.html`;
`stations/workspace_files.py`, `stations/views_files.py`, `stations/workspace_files.html`).
A workspace of one station has none: the address leads to its station's Files.

- **The workspace files**, each with its size: *Everything* (`/w/<id>/files/everything.zip`:
  each station's folder in R's batch layout, `<station>/indices/…`, `plots/`, `trend/`,
  `thres/`, `qc/`, a failed station's `<station>.errors.txt` as R's batch zip writes it,
  and the three files below at the top; CSV deflated, PNG and PDF stored, as
  `climpact.plots.zip_folder`), *Trends, all stations* (`trends.csv`) and *Indices, all
  stations* (`indices.csv`). They download as `<workspace name>.zip`,
  `<workspace name>_trends.csv` and `<workspace name>_indices.csv`. "What is in the zip"
  (from the batch results page until #234) is under them.
- **Trends, all stations** (`workspace_files.trends_csv`): `station, index, slope, lower,
  upper, significant, years_used, units, out_of_date`, one row per station and index: the trend the
  Indices show (`results.Card.trend` of the index's main series, the annual one where
  there is one), Sen's slope and its 95% bounds **per decade** (R's trend file's annual
  values times 10, monthly times 120), `significant` yes or no (the interval excludes
  zero), the years with a value, and the slope's unit ("°C/decade"). An index without a
  trend (too few values, R's `min_trend_data`) has empty slope and bounds; TX95t's day of
  the year and the daily EHF and ECF tables have no row. `units` is a column the board does
  not draw, so the slope's unit is in the file. `out_of_date` (#279) is yes for every row
  of a station whose results are from before a change (`workspace_files.Entry.out_of_date`:
  its recalculation failed, was not run or was cancelled), no otherwise. A station
  without results, or whose run made no index table (#298), has no row.
- **Indices, all stations** (`workspace_files.indices_csv`): `station, index, year, month,
  value`, long format: every yearly value (month empty) and monthly value of each
  station's index tables, from the values the charts read (`results.RunResults.plots`),
  written with 15 significant digits as R's tables, a missing value empty. The daily
  tables and TX95t stay in the stations' folders. `index` is the code the app shows
  (`TXx`, `SPI3`, `TX90-HWN`); `station` the station's name.
- **By station** (`workspace_files.table`): a data table of each station's R files:
  Folder (zip) (the station's zip with its provenance file, below), Report (PDF), All
  plots (PDF), Trends (`<station>_trend.csv`), Thresholds (`<station>_thres.csv`),
  Missing values (the checks' `nastatistics` file) and Quality flags (how many other files
  the checks wrote, a link to them on the station's Files). Each is a link with its size
  or says why it is missing: "not run", "failed", "calculating", "waiting", "checking",
  or "–" ("none" for screen readers) for a file the run did not make (plots or report
  switched off).
- **`climpact_run.json`** (`workspace_files.provenance`) in every zip the app offers for
  results: Everything, and each station's zip (R's `<station>.zip` as the run wrote it,
  copied with the file added, or the station's folder zipped when the run made no zip;
  `stations:station_zip`, `/w/<id>/<station>/zip`, also the station's Files and the
  Indices' "Download all"). It holds `software` (the climpact version and the Climpact
  version it ports), `created` (UTC), `workspace`, `base_period`, `index_settings` (the
  provenance line's "ET-SCI defaults" or how many settings are not the default),
  `settings` (the quality thresholds and the index settings in full), `trend` and per
  station its name, file name, SHA-256 (`Station.file_hash`, the file as kept), latitude,
  longitude, years and its folder, or why it has no results. A station whose results are
  out of date says so and what changed since (`results`: "out of date: made before a
  change to the file and the coordinates"; the file, the station's name, the coordinates,
  the base period, the quality thresholds or the index settings, from
  `workspace.run_changes`), and its file name, SHA-256, years and coordinates are those
  the shown run read (#307, `workspace_files._made_from`, from
  `workspace.recorded_inputs`), so after "Replace file" or new coordinates the old results
  in the zip are not described by the new file. A run from before #269 recorded no `data`:
  its entry names the current file (name, hash and years together, never a mix of two
  files). While its new run is on the way a station has no results in the files, which
  are not made; the workspace file's record (#240) then describes its current file, the
  one the workspace file holds. The record's `base_period` and `settings` stay the
  workspace's current ones; an out-of-date station's `results` names those its results
  were made before. A station's zip holds its own station only. The page shows the
  file (scrolling in its frame), and "Copy methods text" (`workspace_files.methods_text`):
  one sentence made from it, with the version, the base period, the settings and the trend
  method. Without JavaScript it is a disclosure that shows the text (`js/copy.js`).
- **Keeping the files**: when the workspace's files are deleted (or, local, that they stay
  until deleted), then "Keep 7 more days" (a plain POST form whose button looks like a link,
  where workspaces expire) and "Delete workspace now" (in danger colour, the Workspaces
  list's confirmation page), both from #274 (see Workspaces above).
- **Made once, kept until something changes.** The files are made from the results each
  station shows (`workspace.shown_run`, the batch's or its own run) the first time Files,
  a download or a station's zip asks for them (`workspace_files.build`), in a folder named
  by a fingerprint of what they come from (the workspace's name, base period, thresholds
  and index settings, the climpact version, and per station its name, file, coordinates,
  run and whether its results are out of date), written to a temporary folder and renamed,
  so two requests never see half a folder; older folders are deleted. While a station
  waits or calculates, or says done but its job has not finished (a batch zips after its
  last station), nothing is made: Files says so, Export ▾ says so, and the downloads lead
  to Files; a station's zip is then R's zip as the run wrote it. Out-of-date results
  (#223) make "Download (out of date)". With the 8 stations of the heavy-data check
  (Sydney, `qc_stress_1961-2020.txt`, Alice Springs, Darwin, Perth, Nairobi, a failed and a
  left-out one) Everything is 42.5 MB, the trends 35 KB and the indices 9.0 MB, made in a
  few seconds on the first visit.

### Trends across stations

The trend grid and the interval plot (#238; board `Workspace.dc.html`;
`stations/trend_grid.py`, `stations/_trends.html`, `js/trends.js`), under the overview's
Stations table and alone on Compare an index, `/w/<id>/compare/`
(`views_workspace.compare_page`; a workspace of one station leads to its Indices).

- **What it reads.** The results each station shows, as Files reads them
  (`workspace_files.entries`, the overview's rows passed in so they are made once; the
  cards from `results.results_for`, cached): each index's `results.Card.trend`, Sen's
  slope and 95% bounds per decade. A station without results shown (not run, failed,
  waiting, or not yet opened with "Go to indices") is a row of hatched cells. While any
  station waits or calculates the section says the trends come once every station has
  been calculated, and comes in with the overview's last poll.
- **Out-of-date trends** (#279). A station whose results are out of date
  (`workspace_files.Entry.out_of_date`: the run shown differs from its inputs because its
  recalculation failed, was not run or was cancelled) keeps its trends, as its Indices
  do: its row is `trend-grid__stale` (a dashed warning edge at the start of its name
  cell, the `stale-content` edge), "· out of date" follows its name (the dot
  `aria-hidden`, "These trends are from before the last change." in its `title`), and
  each cell's and dot's words end ", out of date" (`trend_grid._out_of_date`); its name
  in the interval plot is tagged the same (`Bar.out_of_date`). `trend_grid.SHOW_FAILED_OUT_OF_DATE`
  (on) is the maintainer's choice for a failed station: off, its out-of-date trends
  are hidden and its row hatched "· failed" as the Calculate board draws a failed row
  (`_Station.failed`, `GridRow.failed`; the plot lists it "failed"). Its rows stay in the
  CSV either way, marked `out_of_date` yes.
- **A station with no indices** (#315). A station whose run shown made no index table
  (every index skipped, as for a file whose TX, TN and PR are all missing;
  `results.RunSource.has_tables` false, the overview's "No indices", #298) has nothing to
  draw: its row is hatched as a station without results (`_Station.no_indices`,
  `GridRow.no_indices`, `trend-grid__empty`), "· no indices" follows its name (the dot
  `aria-hidden`, as "· failed"), each cell's words are "<code>: no indices", and the
  interval plot lists it "<name>: no indices" under "Not shown". Out-of-date results that
  made no index are drawn the same, without the out-of-date tag. It has no rows in the
  CSV, as a station without results has none: there is no slope to write, and an empty
  row would read as "too few values for a trend".
- **Columns** (`trend_grid.columns_for`): TXx, TNn, TN90p, TX10p, SU, TR, WSDI,
  PRCPTOT, Rx1day, R95p and CDD, those some station has; "Choose indices" offers every
  index with a trend at some station, by theme (`trend_grid.available`). A choice is
  `?cols=` (repeated), kept for the workspace in the session
  (`trend_grid.SESSION_KEY`; `?cols=default` forgets it); the chosen columns keep the
  defaults' order first, then the order offered.
- **Cells** (`trend_grid._cell`): the slope (`numbers.slope`) always written; filled on
  the trend scale when the interval excludes zero, the strong step when the slope is at
  least half the column's largest significant slope (`_scale`), the weak one below;
  `not-significant` (a dashed edge), `invalid` ("–", too few values for a trend), `none`
  (hatched: no results, failed, or no indices). Each is a link to the station's index page with the slope, interval and
  significance in words for screen readers.
- **The interval plot** (`trend_grid.interval_plot`): every column's is in the page, the
  selected one (`?index=`, else the first column) shown; `js/trends.js` switches them in
  place when a column's code is clicked and keeps the address. The axis is symmetric about
  zero, to a round end past every interval (`index_page.nice_ticks`); stations without a
  trend are listed under it.
- **CSV** (`views_workspace.compare_csv`, `/w/<id>/compare/trends.csv?cols=…`,
  `trend_grid.grid_csv`): the rows of the workspace's Trends file
  (`workspace_files.trends_csv`, same columns, `out_of_date` included) for the grid's indices, a column of the grid
  a block of rows, the stations in the overview's order; one index for the plot's "CSV,
  all stations". `test_trend_grid.py` checks it against R's per-station trend files.
- **Overlay the series** (#276; `stations/overlay.py`, `stations/workspace_overlay.html`
  with `stations/_overlay_chart.html`, also on `/patterns/`,
  `views_workspace.overlay_page`). The interval plot's "Overlay the series" opens
  `/w/<id>/compare/<code>/overlay`, a page of its own under Compare an index (the
  maintainer's decision on #276; no board draws it, so it is built to `DESIGN.md`'s
  chart rules): the index's series at every station with values, on shared axes, the
  series whose trend the grid shows (`results.Card.main`: annual where the index has it,
  monthly for SPI and SPEI). The years are every year from the first value to the last,
  a station's missing ones gaps (a value with no neighbour a dot). Each drawn station is
  a categorical slot, `--chart-1` to `--chart-8` in the overview's order, never cycled,
  so **eight stations at most** are drawn: with more, the first eight, and "Choose the
  stations drawn" (a GET form, `?stations=<slug>` repeated; more than eight chosen draws
  the first eight and says so); the summary says how many are drawn, and the values table
  and the CSV have every station. Stations are read as the grid reads them
  (`trend_grid._stations`, which keeps each station's plots): an out-of-date station is
  drawn and tagged "· out of date" in the legend and the table, and the summary names it;
  one without results, failed (when `SHOW_FAILED_OUT_OF_DATE` is off), with no indices,
  without the index or with every value missing is listed under "Not shown", as the
  interval plot lists it. The chart is drawn on the server (`overlay.chart`, the
  index page's axes and margins in a 1000 x 340 box, the chart without JavaScript and in
  print) and, with JavaScript, by `charts.js` from the page's own data
  (`overlay.payload`, `#overlay-chart-data`, kind `overlay`: the years, each drawn
  station's values, label and slot token), with the read-out (the year, then each
  station with a value), zoom, move, Show all, and PNG and SVG of the view, whose
  legend wraps onto as many rows as it needs. Under it the text summary (the series and
  its years, the stations, the highest and lowest values with their station and year,
  how many stations have a significant trend), and the values as a data table, a row a
  year, most recent first, a column a station. The CSV (`views_workspace.overlay_csv`,
  `/w/<id>/compare/<code>/indices.csv`, `overlay.index_csv`) is the workspace's Indices
  file (`workspace_files.indices_csv`) cut to the index's rows. Like the trends, the
  page waits while a station is calculated (the CSV is a 404 meanwhile), a workspace of
  one station leads to its Indices, and an index no station has a trend of is a 404.

### Help

The in-app help (#81) replaces the R app's long user guide
(`climpact/www/user_guide/Climpact_user_guide.md`) and its per-tab "Instructions" boxes and
hover tooltips (`bsTooltip` in `modules/singleStationStep2UI.R`, `singleStationStep3UI.R`).
It has five parts, all in the `help` app: **contextual help topics**, **section help** that
opens them in a drawer beside the page (#177), **guide pages** written in Markdown, a **search** and an A-Z
**list of topics**, and a short optional **first-run tour** of the landing page. The
help's own pages share one frame (#325). The
standalone user guide and handover documents are #12.

**The help frame** (#325, the Help boards; `help/templates/help/frame.html`, which every
help page extends: the home, the guides, the topics A to Z, search and a section's help
page). Three columns within the content width (72rem): the **help contents** (14rem) at
the inline start, the page (up to the prose width, 42rem), and **On this page** (12.5rem)
at the inline end, with an optional box under it for the page's one call to action (the
`help_action` context: title, text, link label and URL; #319's pages use it). The
contents (`help/contents.py`, `{% help_contents %}`, `help/_contents.html`) are a "Search
help" field (a GET form to `help:search`), "Help home", then three groups under
`group-label`s, which are not headings: Guides (`GUIDE_ORDER` without `faq` and
`accessibility`), Reference (Index reference, Command line, File formats with the four
format pages under it) and More (questions and troubleshooting, help topics A to Z, the
accessibility statement). They are plain links; the current page's has
`aria-current="page"` and the filter rail's selected style (the `selected` tint, an ink
edge at the inline start). Each Reference link names the URL its page will have
(`help:index_reference`, `help:command_line`, `help:formats`, `help:format`); until #319
adds those URLs the links resolve to `None` and are left out, and so is the empty group.
On this page (`help/_toc.html`) lists the page's `toc` (a guide's `##` and `###`
headings; the topics' groups); `js/help-toc.js` marks the section in view
(`aria-current="true"`, the last heading above the top third of the window). Responsive,
by a container query on `.help-frame`, so the help drawer counts: the contents beside the
page from a 49rem frame (a 52rem window), a "Help contents" `<details>` under the
breadcrumb below it; On this page and the action beside the page from 61rem (a 64rem
window), On this page a `<details>` between the page's header and its text below it. Each
part is in the page twice, as a column and as a disclosure, and the stylesheet shows one,
so the frame needs no JavaScript. In a window at least 30rem high the two columns stay
in view under the site header and scroll inside themselves when taller than the window.

**The help home** (`help/index.html`, the Help board): the h1 and lead, a large search
form (live results as before), "Reference" (a card each for Index reference and File
formats, which until #319 lead to `indices#the-indices` and `gridded#input-files`; the
Command line card has no page or section to lead to yet, so it is left out;
`contents.reference_cards`), "Guides" (a numbered list of each guide's title and summary,
in `GUIDE_ORDER`), "Common questions" (five questions of the `faq` guide, named by their
headings, and "All questions"), "Sample data" and "Take the tour of the start page".

**Contextual help topics** (`help/topics.py`). A topic is an id, a title, one or two
plain sentences and the guide section that says more (`Topic.url`, a guide and an
anchor). The station pages show topics through their sections' help (below). The gridded
pages still show some in place with

```django
{% load help %}{% help_topic "gridded.files" %}
```

which renders a `<details>` (no JavaScript): the title as a quiet link-style summary
(`help-topic--compact`, in `core/tailwind/components/help.css`), and when opened the text in a tinted panel
with "More in the guide: ..." linking to the section. `variant="block"` gives the bordered
`disclosure` instead, `summary="..."` replaces the title. A topic can also have a
`question`, which the in-place link says instead of the title when the title would repeat or
contradict the heading it sits under (#115): the QC checks ("What counts as too large?"
under "Values too large"), the missing days, the daily series. The title stays the topic's name in the list of topics. An unknown id raises
`UnknownTopic` with `DEBUG` or `HELP_STRICT` (set in the test settings); otherwise it is
logged and nothing is shown, so a typo cannot break a page in production.

**Section help** (`help/sections.py`, #177, decision E). A field no longer has a help
link of its own (`components/field.html` lost its `help=` parameter): each section of a
screen has one Help button at the end of its section header (#197; an ⓘ after the
heading before), which opens the section's help in the drawer
(`components/drawer.html`, see [Design system](#design-system)).

```django
{% load help %}<div class="section-header"><h2 id="details-title">…</h2>{% section_help "load.details" %}</div>
{% section_help "result.index" topics=card.help_topics title=card.code %}
{% section_help "quality.verdict" label=levels_label %}  {# "What do the levels mean?" #}
```

In a modal side sheet (#199: the Quality thresholds and Index settings sheets) the drawer
would be behind the sheet, so `inline=True` renders the same help in a disclosure that
opens in place under the group's heading (`data-help-section`), with the help's word
shown and the accessible name "Help: <title>".

A `Section` (`S(...)` in `SECTIONS`) has an id `<page>.<section>`, the section's title, its
topic ids, a few short `Note`s (a sentence, with an optional heading) and optionally an
`extra` template for help that needs markup (the station file's format and example,
`help/sections/_station_file_format.html`). The tag renders, in `help/_section_help.html`:
a link to `/help/sections/<id>/` (`help:section`, the same help on a page of its own, for
browsers without JavaScript), a hidden button that `js/drawer.js` shows in place of the
link, both showing a ringed question mark and the word "Help" (or `label=`) and named
"Help: <title>" (or "<label>: <title>", `aria-label`), and a
`<template>` with the help (`help/_section_body.html`: the notes, the extra template, each
topic's title and text, and one "More in the guide" link per guide, to the first of the
section's topics in it). `topics=` puts the screen's own topics first (an index page adds
its index and its setting, `Card.help_topics`), `title=` names the help after them
("Help: TXx"); the help page takes the same as `?topics=`. Long explanations moved from
the pages into these notes (#177's copy pass): the verdict's three levels and their limits
(`qc_review.VERDICT_LIMITS`, checked by a test), how the box plots are drawn, why the
largest trends come first, how parameterised indices are named, what each group of files
holds. An unknown section or topic fails as `help_topic` does. The station pages' ids:

| Page | Sections |
| --- | --- |
| A station's setup page (New station, #201) | `upload.file` (Your file), `load.details` (Station details) |
| Quality | `quality.verdict`, `quality.wrong`, `quality.worth`, `quality.missing`, `quality.daily`, `quality.distributions`, `quality.thresholds`, and `load.data` for "Your data" (#198) |
| Calculate | `calculate.plots`, `calculate.spells`, `calculate.degree`, `calculate.prcp`, `calculate.custom`, `calculate.ehf`, `calculate.files` |
| Indices, an index, Files | `results.catalogue`; `result.index` (a quiet "About this index" link, #237); `files.page` |
| Sector | `sector.data`, `sector.plot`, `sector.correlation`, `sector.scatter` |
| Gridded (fields that had a help link) | `gridded.task`, `gridded.output`, `gridded.settings`, `gridded.computing` |

**Topic ids for the screens.** All exist and point at written guide sections; the
sections above and the remaining `{% help_topic %}`s use them.

| Family | Ids |
| --- | --- |
| Station file and details (#76, applied) | `station.file`, `station.name`, `station.latitude`, `station.longitude`, `station.base_period` |
| QC checks and plots (#77, applied): `qc.<file>` as in `QC_REPORTS` | `qc.outliers`, `qc.tmaxmin`, `qc.toolarge`, `qc.duplicates`, `qc.tx_jumps`, `qc.tn_jumps`, `qc.tx_flatline`, `qc.tn_flatline`, `qc.nastatistics`, `qc.rounding` (decimal histograms), `qc.precip_histogram`, `qc.daily_series`, `qc.homogeneity` |
| QC thresholds (#77, applied): `QCParams` fields | `qcparam.iqr_temp`, `qcparam.iqr_prec`, `qcparam.prec_max`, `qcparam.temp_max`, `qcparam.flatline_days`, `qcparam.jump` |
| Index settings (#78, applied) | `param.plot_title`, `param.wsdi_days`, `param.csdi_days`, `param.rx_days`, `param.txtn_days`, `param.hdd_base`, `param.cdd_base`, `param.gdd_base`, `param.rnnmm`, `param.spei_months`, `param.custom` (variable, operator and threshold) |
| Indices (#78, applied) | `index.<short name>` for every short name of `climate.indices.csv` (`index.txx`, `index.rxdday`, `index.hw`, `index.hwEHF`, `index.spi` ...); `index_topic_for_output(name)` maps an output name to its id: `rx3day_ANN` to `index.rxdday`, `TX90-HWN_ANN` to `index.hw`, `3month_spi_MON` to `index.spi`, a custom index such as `TXge40` to `param.custom` |
| Trends and results (#78, #79) | `trend.sen_slope`, `trend.confidence`, `trend.significance`, `trend.minimum_data`, `trend.seasons`, `results.missing_value`, `results.standardised`, `results.thresholds`, `results.files` |
| Sector (#90) | `sector.file`, `sector.title`, `sector.y_label`, `sector.detrend`, `sector.correlation`, `sector.regression` |
| Gridded (#85, applied) | `gridded.files`, `gridded.variables`, `gridded.base_period`, `gridded.thresholds_file`, `gridded.indices`, `gridded.output`, `gridded.institution`, `gridded.workers`, `gridded.max_values` |

A screen that needs a topic not listed adds it to `HAND_WRITTEN` with a guide anchor that
exists; the tests below check both.

**Index definitions** come from the core's `climate.indices.csv`, the single source:
`help/indices.py` builds one entry per short name (`catalogue()`), adding a display name in
the usual spelling (`TXx`, `Rx1day`, `R95pTOT`), a short name for people (`SHORT_NAMES`,
#218: "Hottest day", "Wettest %(n)s days", translatable; `IndexInfo.short_name()` fills in
the parameter, or the definition's letter, "Wettest d days", before one is chosen), a group, the parameter topic for
user-defined indices, sentence-case long names and `°C` for `degrees_C`. The definitions
are shown as the core writes them (for example "Annual warmest daily TX"). Long names the
file gets wrong are corrected in `LONG_NAME_FIXES` (only `tmge10`, whose R long name says
"TX" though it counts TM days, #217; see [R behaviour not to be
copied](#r-behaviour-not-to-be-copied)); the gridded form's index list uses it too. A test
checks that every long name naming TX, TN or TM names a variable its definition uses.
Index topic titles are the code and short name ("TXx Hottest day"); their texts are the
definition plus units, and R's long name when it differs ("Name in Climpact for R: Max
TX.", `topics.r_name_sentence`).

**Guide pages** (`help/guides.py`). `guides/<language>/<slug>.md`, starting with `title:` and
`summary:` lines (Markdown `meta` extension), rendered with Python-Markdown (`markdown`, a
pure-Python dependency added for #81) with `toc`, `tables`, `fenced_code`, `attr_list`,
`def_list` and `sane_lists`. Headings get ids from their text or an explicit `{#id}`;
the page shows them in the help frame's On this page (above), and links to the previous
and next guide.
Rendered guides are cached per file version, file language and interface language. The
Markdown is the app's own text, so it is rendered as trusted HTML. Links use two schemes
resolved at render time, so guides do not depend on where the app is mounted:
`guide:<slug>#<anchor>` and `url:<url name>#<anchor>` (the anchor optional; a page that
does not exist yet, such as `gridded:start`, keeps the link text without a link). Tables
are wrapped in the table
component's scrolling region, named by the heading above the table (#83).

The guides, in order (`GUIDE_ORDER`): preparing a station file (`station-file`), choosing a
base period (`base-period`), reading the quality checks (`quality-control`), the indices
(`indices`), interpreting trends (`trends`), batch processing (`batch`), sector correlation
(`sector`), gridded data (`gridded`, local mode), questions and troubleshooting (`faq`)
and the accessibility statement (`accessibility`, #83, see [Accessibility](#accessibility)).
They are rewritten from the R guide for meteorological-service staff, checked against the
Python code rather than the R text where they differ: the flatline check flags more than
`flatline_days` (5) equal values, not R's "4 or more"; `tmaxmin` lists TN >= TX; jumps are
>= 20 °C; the trend file has no p-value, so significance is read from whether the 95%
bounds exclude zero; the SPI and SPEI trend labels for the 6- and 12-month scales do not
name the month used; the `tx95t` trend row is across days of the year. The indices guide
ends with the catalogue: the line `[[index-catalogue]]` is replaced, before rendering, by a
`###` heading per group and a `####` entry per index anchored `index-<short name>`, headed
by its code and short name ("Rxdday Wettest d days"; definition, R's long name, units, yearly or monthly, whether it uses the base period, which setting it
takes), so every index has a linkable, searchable definition.

Not ported from the R guide: installing R and starting the Shiny app, screenshots of the
R screens (the app's own screens explain themselves, and pages stay small), the ET-SCI
background chapter, the netCDF wrapper-script instructions (replaced by the gridded guide
for the gridded screen and command line) and the reference lists beyond the papers each
guide relies on.

**Search and topic list.** `/help/search/?q=` finds the guide sections (`##` and `###`,
catalogue entries included) and topics containing every word of the query, title matches
first, with an excerpt. It is a plain GET form; with htmx the results replace
`#help-results` as you type (300 ms after the last key), on the help home and the search
page. The help contents' "Search help" field submits to the same address, without live
results. `/help/topics/` lists every topic by family, A to Z, each with
its text and a link to its section (anchors `topic-<id>`); its families are its On this
page.

**Sample data.** The help home lists the samples (#325, a short list in place of #81's
cards): the station (its file, and "Open it in a workspace", the one-click POST form of
Add stations), the batch (its metadata file, and the same form for the sample batch),
the grid where gridded runs are offered (`GRIDDED_ENABLED`: "Open it on Gridded", the
gridded sample's POST form, a 3 × 4 cut of R's sample grid) and the sector data (R's
`wheat_yield_nsw_1922-1999.csv`, `stations:sector_sample`, also offered by the sector
step, #90).

**First-run tour** (`help/tour.py`, `js/tour.js`, `help/_tour.html`). Four steps on the
landing page (Get started and See an example, "How it works", the header's Help link and
Workspaces in the header; #242 dropped the step on the other ways to run Climpact), passed as `json_script` data with translated text. On a first
visit a dismissible invitation appears ("Take the tour" or "No thanks"); starting,
finishing or dismissing stores `climpact-tour=done` in `localStorage`, so it is offered
once. `/?tour=1` (the help index's "Take the tour" link) starts it at once. The tour box is
a non-modal dialog placed under (or above) its target, docked to the bottom of the screen
below 40rem; focus moves to its title, Escape closes it and focus returns. Steps whose
target is not on the page are skipped. Without JavaScript the invitation stays hidden.
No library is used.

**Translations.** Template strings and topic texts are marked as usual. Guides are
translated as files: a guide missing in the interface language (`pt-br`, then `pt`) falls
back to English, with a notice and `lang="en"` on the article. The index names and
definitions are core data that `makemessages` cannot find, so
`help/index_messages.py` lists them with `gettext_noop`; regenerate it with
`uv run python -m climpact_web.help.indices` when `climate.indices.csv` changes (a test
fails when it is out of date; ruff's line-length rule is off for that file only). They
are passed through `gettext` when shown.

**Tests** (`tests/test_help.py`). Every guide renders with a table of contents and no
unresolved `guide:`/`url:` link; **no broken help link**: every link on the help pages,
the landing page, Add stations, its review and a station's setup page that goes to `/help/` or an `#anchor`
answers 200 and the anchor exists on the target page (over 300 links); every topic's guide
and anchor exist; every id used in a template (`help_topic`) exists; every section used in a
template (`section_help`) exists and its topics too, and no field is given a help topic;
the field component shows a field's hint and no help link of its own (the latitude's, in
`test_field_component_has_no_help_link_of_its_own`; no test checks that every field has a
hint); the Help button's link, button and template; every section's help page, and
`?topics=`; one hidden drawer on every
page; the verdict's help states `VERDICT_LIMITS`; Add stations, its review and a station's setup
page show their topics. `test_qc_review.py`, `test_indices_results.py` and `test_sector_web.py` check that
each station page has its sections' Help buttons in order and no help link under a field;
`test_help.py` checks the header's Help button leads to the page's guide; and the
browser tests open the drawer by keyboard (Tab to the Help button, Enter, Escape, focus
back) and from every Help button of every station page, and Tab through the Indices and
Quality with the context bar stuck at the top and never over the focused element
(WCAG 2.4.11); the
catalogue covers every short name of `climate.indices.csv` exactly once, with a group,
display name, units and an entry in the indices guide; output-name mapping;
`index_messages.py` is current; search (full page and htmx fragment); the English fallback
and a translated guide; the tour's data, targets and labels. The help frame (#325):
every help page has the contents (the three groups' links in order, the column and the
disclosure, one h1), the current page marked, Reference links that join the contents and
the home's cards by their URL name alone, On this page and the call to action in both
places, the home's lists, and Index reference current on `/help/indices/`; in the
browser, the columns and disclosures at 1280, 900 and 375px, no sideways scroll, the
columns stuck under the header and the section in view marked
(`test_help_frame_at_each_width`), and the help home and a guide in the sticky-overlap
check.

### Gridded pages

The gridded pages (#85) replace the R app's two gridded screens
(`climpact/modules/griddedStep1UI.R` and `griddedStep1.R`, indices;
`griddedStep2UI.R` and `griddedStep2.R`, thresholds) with one flow that runs the core's
`gridded-thresholds` and `gridded-indices` runners as background jobs.

**Where it is offered** (decided 2026-11-14, recorded in #85). On in local mode, as in R.
Off in hosted mode unless `CLIMPACT_WEB_GRIDDED_HOSTED` is set (large uploads, long jobs
and storage cost; to be revisited only with a bigger Droplet, #12), with uploads limited to
`CLIMPACT_WEB_GRIDDED_MAX_UPLOAD_MB` (200 by default). `settings.GRIDDED_ENABLED` holds the
result: with it off every `/gridded/` URL is 404 and the landing page and header leave
Gridded out. Paths on the server's disk are only ever accepted in local mode: in hosted
mode the folder listing, the paths box, the thresholds path, the number of cores, the
temporary folder and "copy the results to a folder" are not offered, and a posted path is
ignored.

**Gridded** (`gridded:start`, `/gridded/`; #289, the GridList board). A run is a place of
its own, like a workspace, not a flow of steps (no step indicator since #289; the
`steps` component and `navigation.gridded_steps` went with it). `/gridded/` lists the
session's runs, most recently changed first (`gridded/runs.py`, `entries`): Run (its
name, a link), Grid (rows × columns and the spacing, from the coordinates' range), Period,
Thresholds (the base period; ", file kept" when the run wrote a thresholds file; "From
<run>" when it read the thresholds file another of the session's runs wrote, matched by
resolved path, or "From <file name>"), Calculates, State (`runs.state`: "Not started",
"Not started: precipitation units" and the like from the variable checks, "Waiting to
start", "Calculating · 38%" with a bar, "Failed", "Cancelled", "Finished 18 Nov, 21 min")
and, where runs expire, Kept until (`expires_at`; "–" while a job is queued or running;
left out locally, as Workspaces' "Deleted on"), then a line on how long runs are kept
("Runs stay on this computer until you forget them" locally). With no runs, one line and
the sample grid. Then three boxes: stations or a grid, scenarios, the sample.
Workspaces' note links here when the session has gridded runs.

A run is named from its files until it is renamed (`runs.default_name`): the first file's
name without the variable names (the guessed ones, ERA5's `mx2t`, `mn2t` and `t2m`, and the
run's chosen ones, #321), `day`, the dates and the extension, then the spacing and the
period ("era5 SEA 0.25°, 1961–2020"); the sample is "Sample grid, 1991–2010".
`GriddedRun.name` holds a name given on `<run>/rename/` (empty: the default again).

**A run's pages** (#289, the GridFiles board). `gridded/_run_bar.html` draws
`components/context_bar.html`, sticky as a station's: "Gridded / run", the name as the
h1, the provenance line (`runs.provenance`: rows × columns and the cells with data,
counted once from the first annual index file, in stripes of rows with all their years at
once (#295: a time step at a time decompressed the whole file once a step, 19 s on a
700 x 900 grid), and kept in the run's options; the period and calendar; the base period; the indices and files, or
"calculating"; the climpact version; kept until, where runs expire), Rename and Forget this run (a
confirmation page, then POST), "Run again with other files" (to New gridded run) once
no job is queued or running, and "Download all (zip, size)" once every job has
succeeded; then the tabs:

- **Map**, `/gridded/<id>/` (`gridded:run`): while the run is queued or calculates, or
  after it failed or was cancelled, its stages (**Stages**, below); once every job has
  finished, the index rail, the map and the cell pane (**Map**, below). A thresholds-only
  run says it has no map. A run not started yet redirects to its set-up. The old
  `<id>/results` redirects here (301, with its query string).
- **Files**, `/gridded/<id>/files/` (`gridded:files`): the index files of the indices job
  (`runs.file_rows`: the code and short name, as the station pages write them, the
  frequency, the file, the netCDF variables in it from `maps.data_variables`, cached by
  path and modification time, the size), grouped by theme (`themes.chip_of`: Heat, Cold,
  Rain, Drought, Other), by the variable an index needs (the core's `_BY_VARIABLE`) or by
  frequency (`?by=`, a GET form; htmx swaps the groups), each group a framed disclosure,
  the first open, with its zip (`gridded:zip`, `<id>/zip/<by>/<group>.zip`). Beside them:
  Download all; the links as a text file (`gridded:links`), one absolute URL per output
  file for `wget -i`, each with a key (`?k=`, Django's signing with its own salt, the
  run's id, valid `JOB_RETENTION_DAYS` + 1 days) that lets `gridded:file` serve that run's
  files without the browser's session, since a download tool has none; the folder the
  files were copied to (`copy_to`, local mode); the run's record: `run.json`
  (`runs.record`: the software and versions, the inputs with their size and SHA-256, the
  variables, the grid, the settings without the internal keys, and the jobs; hosted, no
  server paths), `climpact.log` (the jobs' operator logs, thresholds first, with any
  error; hosted, only their timestamped lines, so no traceback names the server's
  folders) and the thresholds file when the run kept one; then a note on reading the
  files. The inputs' checksums are worked out the first time `run.json` is asked for and
  kept in the run's options while each file's size and modification time stay the same.
- **Set-up**, `/gridded/<id>/setup/` (`gridded:setup`): the set-up page under the bar.
  Before the run has started it has a context bar of its own, in the page's flow:
  "Gridded / New run / set-up" over the run's name as its h1, with Rename, the line
  "Climpact has read the headers of N files. Nothing has been calculated yet.", and
  "Choose other files" and "Forget this run" at its end. After a run the summary panel
  says what the results are (when they were calculated, in how long on how many cores,
  what was written) and, as the form changes, which sections differ from the settings
  that made them ("Changed: Base period."). **Start again with changes** keeps the
  results (#293): the new jobs and their settings wait in `next_thresholds_job`,
  `next_indices_job` and `next_settings`, so Map, Files, the provenance line and
  `run.json` describe the results shown; `GriddedRun.settle` (on every request for the
  run, and on Gridded) puts them in place once every new job has succeeded, deletes the
  old jobs and their folders, and takes the new settings (keeping the inputs'
  checksums). A new start that fails or is cancelled leaves the results as they were,
  and Set-up says so; while it calculates, Set-up says "Calculating again" and Gridded's
  State shows its progress. A run that never finished is started again in place.

**Retention** (`gridded/retention.py`, #301, #330). Gridded runs follow
`WORKSPACE_EXPIRY`, as workspaces do, and in both modes `kept_jobs` (a keeper) keeps the
four jobs each run shows (`thresholds_job`, `indices_job` and a new start's
`next_thresholds_job`, `next_indices_job`), with their folders under `RUNS_DIR`, whatever
their age, as `stations.retention.kept_jobs` does for workspaces. When it is on (hosted),
`purge_expired_gridded` deletes a run and its own folder (uploads) `JOB_RETENTION_DAYS`
after its last change (`GriddedRun.updated_at`: created, started, renamed), unless one of
its four jobs is queued or running, and deletes those jobs and their folders with it
(`delete_jobs`), rather than leaving them to the next purge. So a run renamed after its
jobs finished keeps its results until its own Kept until date (before #330 the jobs went
`JOB_RETENTION_DAYS` after they finished, and the run was listed with its results gone).
When it is off (local), a run stays until Forget this run deletes it: no run is purged;
once the run is forgotten its jobs fall back to the jobs app's rule. Locally
`GriddedRun.expires_at` is None, so
`runs.kept_until` is empty: Gridded leaves out its Kept until column, the provenance line
its "kept until", and the note under the list, the set-up's retention line and its "Ready
to start" panel say runs stay on this computer until forgotten. Either way, folders under
`<MEDIA_ROOT>/gridded/` that belong to no run are deleted once older than the period, and
files read in place are never touched (`test_gridded_web.py`:
`test_hosted_runs_and_their_jobs_go_after_the_retention_period`,
`test_hosted_run_renamed_after_its_jobs_finished_keeps_them_until_it_expires`,
`test_local_runs_and_their_jobs_stay_until_forgotten`, `test_delete_and_retention`).

**New run and set-up:**

1. `/gridded/new/` (`gridded:new`, #292, the GridNew board): a narrow page (55rem). In
   local mode, "Files on this computer": a folder listing (`gridded/_listing.html`,
   `listing.listing`) with a path bar (the folders above as links, and a field for any
   folder; `?dir=` opens one, otherwise the folder listed last in the session, else the
   home folder), then the folder's subfolders as links and its netCDF files (`.nc`,
   `.nc4`, `.netcdf`), each with a checkbox, its daily variables, its years ("1961–2020")
   and its size. These come from the file's header (`inspection.inspect_file`), kept in
   memory by path, size and modification time (`listing.describe`, up to 4,096 files), so
   moving between folders reads nothing again. A file that cannot be chosen is greyed with
   its checkbox off and says why in the variables column: "no time axis", "no daily grid",
   "thresholds file" (it holds `THRESHOLD_FILE_VARIABLES`; its dates are its
   `base_period`), its calendar when unsupported, "dates cannot be read" or "cannot be
   opened". "Paste paths or a pattern instead" (a native `<details>`, open when it holds
   text) is the paths box: a path or a pattern a line, `*` and `?` expanded with `glob`,
   sorted, folders left out (`forms.expand_pattern`); a pattern that matches nothing says
   so. The files ticked and those typed are read together, each once (`PathsForm`):
   each path must be absolute, exist, be readable and start with a netCDF-3 or HDF5
   signature. Under the listing, what is chosen ("3 files chosen · tasmax, tasmin, pr ·
   561.0 MB", `listing.summary`) and Read the files. The listing's links and the folder
   field post the same form (`action=browse:<folder>`, `action=open`, the form's first,
   hidden, default button, so Enter in the field opens that folder), so it works without
   JavaScript; files ticked in other folders ride along as hidden fields. With htmx only
   the listing is swapped, and a change to a checkbox or the paths box asks for the line
   saying what is chosen (`?tick=1`). In hosted mode, "Upload netCDF files": the drop zone
   states the limit (`GRIDDED_MAX_UPLOAD_MB`) and how long files are kept
   (`JOB_RETENTION_DAYS`) before anything is uploaded, then one line on the ways round it
   (Climpact on your own computer, or `cdo sellonlatbox`); kept in
   `<MEDIA_ROOT>/gridded/<id>/input/`. `gridded:upload` still takes a post in local mode,
   but the page no longer offers it there. Up to 200 files (`forms.MAX_FILES`, #291, for
   a variable split by year; `DATA_UPLOAD_MAX_NUMBER_FILES` is 1000 so that an upload of
   more than Django's default of 100 files reaches the form's own message). Then "Try
   the sample grid": `grid_sample`, a 3 x 4 cut of R's sample grid, bundled and read in
   place from the package.
2. `/gridded/<id>/setup/` (#293, the GridSetup board): one page of sections divided by
   hairlines beside a summary panel (22.5rem, sticky; under the form below 64rem).
   What each file holds is read from its metadata and coordinates only
   (`inspection.inspect_file`: netCDF4 and cftime, no data): the grid, dates, calendar,
   latitude and longitude ranges, format and size, and every variable with time, Y and X
   dimensions (found as the core reader finds them) with its description and units.
   - **Files** (#291; `gridded/_files_table.html`): a row for the files that hold the
     same variables (`inspection.group_files`): one file, or a variable split across many
     as "20 files, 1991–2010", a native `<details>` listing each file and its dates; then
     the daily variables, grid, dates, calendar and total size, and **Header**, which
     shows the row's first file's header as `ncdump -h` prints it
     (`setup_page.header_text`; `gridded:file_header`, `<run>/setup/header/<n>/`: a page
     of its own, or the text alone with `?format=text`, which `js/gridded.js` shows in a
     dialog). Locally the files' folder is under the name. Unsupported calendars
     (`all_leap`, `julian`), files with no daily grid and unreadable time axes have a row
     of their own saying why, in plain language.
   - **Variables**: a table of TX, TN and precipitation, the variable chosen for each
     (one choice per name, "tmax (K) · 20 files"), its units in the file, how it is read
     (`setup_page.read_as`, from the core's `unit_conversion`: "°C (K − 273.15)",
     "mm/day (× 86400)", or "°C" and "mm/day" as they are) and a Check ("Readable",
     "Units", "Not chosen", "Not usable"). A variable that cannot be used has a faint
     danger tint and its message under the table: for units Climpact cannot read, what it
     reads and how to convert (`setup_page.units_help`), with a CDO command and a Copy
     button for precipitation in metres (ERA5's `tp`: `-mulc,1000`) and an hourly rate
     (`mm/h`, `kg m-2 h-1`: `-mulc,24`), each setting the units to `mm/day`, through
     `-mergetime` and a pattern for a variable split across files. Then one mono line:
     the grid with its bounds, the period and days, the calendar, and "same grid and time
     axis in every file ✓" when nothing is wrong. The checks are the core reader's
     (`inspection.check_names`: one file, or files that join along time as the core joins
     them, `inspection.join_problem`: the same grid, calendar and units, no overlap, no
     gap; not chosen twice; units the core converts; the same grid and dates as the
     others).
   - **What to calculate**: indices, a thresholds file only, or both, as three radio
     cards; for the indices, "Percentile thresholds": from the base period of these
     files, or read from a thresholds file (a path locally, with Browse; an upload
     hosted).
   - **Base period**: the first and last year beside a timeline of the data's years with
     the base period marked (an SVG drawn with percentages, so no style attribute), and
     the coverage ("The data cover all 10,958 days of 1971–2000 (at least 360 needed).").
   - **Indices**: "55 of 55 · 88 files", All, None and "Without the slow ones"
     (JavaScript); four columns by the variable needed (the core's `_BY_VARIABLE`), each
     index a checkbox with its code and short name, "slow" on HW, HWEHF, SPI and SPEI; then
     the numbered indices' parameters in one row, named by code (WSDId, CSDId, Rxdday,
     TXdTNd, Rnnmm, HDDheatn, CDDcoldn, GDDgrown) with their units. At least one index is
     needed (none no longer means all).
   - **Output files**: the file name template with an example of the names it gives, the
     thresholds file name (when one is kept), Institution and Institution ID, and "Also
     copy the results to" (local mode, with Browse).
   - **Computing**, closed, its summary giving the current values (cores, values at once,
     cell-first copy).

   The **summary panel** (`gridded/_summary.html`, `setup_page.build` and `panel_for`) is
   the check: "Ready to start", or "Before you start" with each problem linked to its
   field; then each check with its mark: Grid, Period, Variables, Base period, Writes
   (index files, or the thresholds file, and their size), Disk (local mode: what the run
   needs with the temporary copy, against the free space where the jobs write), Cell-first
   copy (when it will be made: the core's `read_amplification` and `rechunk_bytes`, read
   once for the files as they are, `setup_page.reading`) and Time; then the one Start
   button and a line on what happens next. The estimates are labelled "about": the size
   is that of the values before compression (float32, a day-of-extreme variable where the
   index has one, three scales for SPI and SPEI, `trends.nc`, and float64 for the
   thresholds file); the time is 0.015 s per cell and year of data for every index on
   one core (15% less without the heatwaves, SPI and SPEI) and 0.0005 s for a thresholds
   file, divided by the cores, measured on the sample grid tiled to 12 x 16 cells
   (`setup_page.INDICES_SECONDS`). As the form changes, htmx posts it to `gridded:checks`,
   which answers the panel and, out of band, the parts of the form that follow it (each
   variable's units, how it is read and its check, the units help, the Together line, the
   timeline and coverage, the indices' count, the example file name and the Computing
   line). Without JavaScript the form posts and the page draws the same panel, with the
   form's errors.

   **Browse** (#320, local mode only; `gridded/_browse_field.html`, `views.setup_browse`)
   sits at the end of the thresholds file's path and the copy folder's. It is a submit
   button of the set-up form (`action=browse:<field>`), so it works without JavaScript,
   and opens New run's folder listing (`gridded/_listing.html` with `pick` set,
   `listing.picking`) under its field: at the folder of the path typed (or the nearest
   folder above it, for a copy folder still to be made), else the folder of the run's
   files, else the folder New run listed last or the home folder. For the thresholds file
   every netCDF file is listed but only thresholds files (a thresholds variable, the
   base period as their dates) can be chosen, by their name; the copy folder's listing
   has folders only and "Choose this folder". Its folder links and folder field post
   `browse:<field>:<folder>` and `open:<field>`; choosing posts `pick:<field>:<path>`
   (which also sets the thresholds to come from a file) and Close posts `close`. Without
   JavaScript each of these draws the page again from the form posted: the summary panel
   checks it, but the fields show no errors, as with htmx before Start. The form's first
   button is a hidden default one (`action=default`), so Enter in a field starts the run
   as before but opens the folder typed while a listing is open. With htmx the listing
   alone is swapped in its place (the other closed), focus goes to its folder field, and
   `js/gridded.js` fills the field on a choice (its `change` asks for the checks again)
   and takes focus back to it, or back to Browse on Close. Hosted mode has neither field's
   Browse, and refuses these actions (400). Tests: `test_gridded_web.py` browses for a
   thresholds file and for the copy folder without JavaScript and with htmx (where each
   opens, moving up, a folder typed and one that is not there, choosing, Close, Enter
   while browsing and with no listing open, nothing started) and finds none in hosted
   mode; `test_accessibility.py` opens both listings, chooses a folder and closes one by
   keyboard, with axe on an open listing.

   On "Start", the form is validated, and the files are opened with the
   core's `open_grid` (`inspection.preflight`), so a file the core would refuse fails
   here, its message in the panel, rather than in the job.
3. Starting opens the run's Map: the run's stages (thresholds first, then indices; the
   worker takes the oldest queued job first), polled by htmx (**Stages**, below), the
   cell-first copy while the input is rechunked and "Trends and the map" while
   `trends.nc` is written after the indices (#290; the map's Base mean, Anomaly and
   Trend views and its grid mean read it, #296). When the last job finishes the map takes the stages' place without a reload.
   The files are on the run's Files tab; "Download all (zip)" and each group's zip are
   `ZIP_STORED`, built in a temporary file.

**Options, against R's screens:**

| R gridded screens | Python |
| --- | --- |
| Input files: upload only (`fileInput`, so the files are copied into Shiny's temporary folder) | local mode: files ticked in a folder listing that shows each one's variables and dates, or paths and `*` patterns, read in place; hosted: uploads |
| Variable names typed in, defaults `precip`, `tmax`, `tmin` | chosen from the files' daily grid variables; guessed from R's defaults, then CMIP and other common names, then units and standard names; checked at once |
| Two screens: indices, or thresholds | "What to calculate": indices, thresholds file only, or thresholds file then indices (two jobs on the same files; the indices compute their own thresholds, as R's indices screen does) |
| Thresholds file for the indices (`thresholdFiles`, several allowed) | "Read them from a thresholds file": one file, by path (local) or upload (hosted); refused when the data have a day in its base period, as `check_thresholds_file` (and R) require |
| Output file name pattern, default `var_daily_climpact.sample_historical_NA_1991-2010.nc` | the same CMIP5 form, checked (six parts, years, `.nc`), default the core's `var_daily_climpact_historical_NA_<first>-<last>.nc`; example names shown |
| Thresholds output file name, default `sample_data.thresholds.1991-2010.nc` | default `<first file's name>.thresholds.<base start>-<base end>.nc`; letters, digits and `._+-` only |
| Output written to `www/output/<institute ID>_ncdf` (or `_thres`) inside the app | each job's own folder, downloaded from the page; local mode can also copy the files to a chosen folder (`copy_to`) |
| Institute name and ID, required | the same |
| Base period, default 1991-2010 | 1971-2000 when the data cover it, else 1991-2010, else the data's first 30 years; fewer than 360 days of it in the data is an error (R stops in the run); with a thresholds file, any overlap with the data is an error |
| Number of cores, default 1 | default up to 4, one left free; 1 to the number of cores (local mode only) |
| Indices to calculate, a comma-separated list, empty for all | checkboxes in four columns by variable, codes first, all ticked; the heatwave, SPI and SPEI indices marked as slow; at least one needed |
| EHF definition: Perkins and Alexander (PA13) or Nairn and Fawcett (NF13) | NF13 only, stated in the index parameters' help: `climdex.hwEHF` accepts only NF13 (see [Gridded indices](#gridded-indices)) |
| Number of data values to process at once (millions), default 10 | the same field; default the core's 5, or less for a small grid, so that it is read in about 20 blocks (`default_max_values`): progress is reported after each block, and a grid of one or two blocks would show none for most of the run |
| The wrapper script's index parameters (wsdi, csdi, rx, txtn days, base temperatures, rnnmm) are fixed in the screen | editable in one row under the indices, defaults `WRAPPER_PARAMS`; ranges as `validate_params` |
| No rechunking | the core's `--rechunk` (automatic, always, never) and, in local mode, its `--tmp-dir` |
| A modal warns that the run takes hours; the browser must stay open until "Done" appears | a background job with progress; the page can be closed and the run opened again from Gridded |
| Errors in a modal with R's message | the error on the Map tab in words, with the setting that fixes it linked on Set-up (values read at once and cores for memory, the files for a gap, Variables for units) and the run's log; starting again keeps the finished stages (#294) |

**Stages** (#294, the GridRun board; `gridded/stages.py`, `gridded/_stages.html`,
`gridded/_stages_table.html`). While a run is queued or calculates, or after it failed or
was cancelled, its Map tab shows, in the map's place:

- **The run status line** (the workspace overview's pattern, `run-status`): "Calculating
  indices: 62%." (or "Checking the files.", "Making the cell-first copy: 40%.",
  "Calculating thresholds", "Calculating trends", "Waiting to start.", "Cancelling…"),
  the time left (`stages._time_left`: linear, once the last main stage, the indices or a
  thresholds-only run's thresholds, has done two blocks in two seconds; never while a
  main stage waits after the current one), the time so far since the first job started,
  "You can close this page.", a bar, and Cancel (`gridded:cancel`, POST: every queued or
  running job of the run, or of its new start; `Job.request_cancel`). Stopped: "The run
  failed in the indices stage." (danger edge) or "The run was cancelled in the indices
  stage.", what is kept, "Change the settings" (to the fix) or "Start again on Set-up",
  and Forget this run. Its first sentence is announced through `#announcer`
  (`data-announce`, at most every 10 s, at once when the run stops), so no more often
  than the poll (`jobs.views.poll_delay`).
- **The stages table** (`stages.stage_rows`): one table for the run's jobs, not a card a
  job: Check the files, Read the thresholds file (indices from a thresholds file: no
  stage of the core's, so done with the check, or failed when the check failed on the
  file), Cell-first copy (only when the first job made one), Thresholds (the thresholds
  job), Indices, Trends and the map. An indices job after a thresholds job opens and
  copies the files again (the two jobs are independent: the indices compute their own
  thresholds), which its Indices row counts in its time and states ("Checking the files",
  "Copying the files by cell · 40%"). Each row's state comes from its job's status and
  `stages.json` (`stages.job_stages`): done, running ("62% · block 812 of 1,300": the
  core counts the copy's slabs and the blocks together, so the block is the step less
  the copy's steps, `total - blocks`), waiting, failed ("Failed in block 233 of 1,300"),
  cancelled, not run, or "Kept from the last start" (a job that finished before this
  start's newest job was queued). A job that failed before its stage's first step is
  put in that stage: after the files were opened (`opened`), in the copy or the main
  stage; after the copy's last slab, in the main stage; after the last block, in the
  trends. Time is each stage's own, `m:ss`. A job run before `stages.json` existed shows
  its whole time on its main stage.
- **On failure** (`stages.failure_for`), under the table: the error in words (out of
  memory: "The run ran out of memory in block 233 of 1,300.", with the block's values
  and their memory, 8 bytes a value, per core and on all cores), what to change, with a
  button to the field on Set-up (out of memory: "Values read at once", suggesting half,
  and the cores, `#id_max_values`; no room for the cell-first copy: `#id_rechunk`; a gap,
  overlap, grid, calendar or units differing between a variable's files: Files; units
  Climpact cannot read: Variables; a variable not found: Variables; a thresholds file
  that does not fit: What to calculate; the base period; the hosted time limit: Indices;
  otherwise Set-up), what is kept, and The run's log (`climpact.log`). The match is on
  the core's and the worker's messages.
- **Beside it**, "What is being calculated": the files (the variables chosen and their
  size), the grid and period, the base period, the indices and the files they make
  (`index_files` of the core), cores and values read at once, when it started; All
  settings (Set-up); that it runs in the background and is on Gridded until a date, or,
  where runs do not expire (local, #301), until it is forgotten.

`gridded:progress` answers the poll with the same block. Once the run stops it also
brings the run's bar up to date out of band (`_run_bar_update.html`: the provenance line
and the actions, in the bar and its ⋯ menu, swapped by selector, so the bar's script
keeps its elements). Once every job has finished (`stages.view` is None) it answers with
an empty map (`data-gmap-load`) in the stages' place, which `js/gridded-map.js` fills at
once with the map part (`X-Climpact-Part: map`), as a link in the map does: htmx drops
`<script>` elements from what it swaps (`allowScriptTags: false`), so the map's data
could not come in the poll's answer. A thresholds-only run gets its note instead.

**A thresholds-then-indices run works out its thresholds in both jobs** (#333, decided
2026-11-20: kept as it is). The indices job of a `task: both` run is queued with no
thresholds file and computes its own, as R's indices screen does, rather than reading the
file the thresholds job writes. The input of such a run always covers the base period,
and the percentile indices then need climdex's in-base bootstrapped thresholds in the base
years (`compute_block_thresholds`, `bootstrap_quantiles`), which a thresholds file does
not hold: `check_thresholds_file` refuses one for data with a base-period day, as R does
(see [Gridded indices](#gridded-indices)). What the file could replace, the out-of-base
percentiles, is a small part of the indices job: on the sample grid (3 × 4 cells,
1991-2010, base 1991-2000, one core) the indices job took 4.6 s, its thresholds 1.9 s, of
which the bootstrap 1.87 s and the out-of-base percentiles 0.01 s. The two jobs stay
independent (several workers run them side by side), and each opens and checks the files
and, for files chunked by time, makes its own cell-first copy (a temporary file that
lasts one job, `GriddedInput.block_reader`), which the stages table shows in the Indices
row.

**Starting again keeps the finished stages.** `views.queue_jobs` keeps a finished job of
the last start (or of the results shown, for a new start of a finished run) whose
parameters are those of the new start but for the computing ones (`workers`,
`max_values`, `rechunk`, `tmp_dir`), rather than queueing it again. So a
thresholds-then-indices run whose indices failed after its thresholds file was written
begins again at the indices; a change to the files or base period runs both. A failed
job's own finished stages (its copy, a part of its blocks) are not kept: it runs again
from its start.

**A new start beside the results** (#293). While a new start of a finished run
calculates, Map shows its status line above the map it will replace ("Map and Files show
the run of … until this one has finished, then its results."), its stages in a
disclosure ("Stages of the new start", open when it failed); a new start that failed or
was cancelled says so ("The last start failed in the indices stage. Map and Files still
show the run of …"). When it finishes, the poll deletes the old map out of band and puts
the new one in place.

**Map** (#295, the GridMap board; `gridded/map_page.py`, `gridded/_map.html`,
`gridded/_cell_pane.html`, `js/gridded-map.js`). No map tiles or network services
(offline and low bandwidth). A data page in the station Indices' three columns: the index
rail (14rem), the map, the cell pane (`clamp(22rem, 28%, 32rem)`), side by side from a
76rem page; from 48rem the rail beside the map and the pane under them; narrower, one
column.

- *State.* Everything is in the query string, so every view is an address and works
  without JavaScript: `index` (a rail entry: the file's index, `txx`, `rx3day`, or a
  heatwave variable, `hwn_tx90`), `freq` (`ANN`, `MON`, `DAY`), `year` and `month` (`day`
  for `tx95t`), `scale` (SPI and SPEI: 3, 6 or 12 months), `cell` (the file's `y,x`;
  `cell_y` and `cell_x` from the form without JavaScript; `goto`, "lat, lon", the nearest
  cell, `maps.nearest_cell`, a turn either way for 0–360° grids), `view` (`base`,
  `anomaly`, `trend`; Year without), `series` (`grid`, the pane's mean over the grid),
  `q` (the rail's Find). Defaults: TXx (else the first index), annual, the last year (of
  December, for a monthly file) with a value (`last_step_with_values`), the 12-month
  scale, the cell with a value nearest the middle, Year. An address asking for a view or
  the grid mean the layer has none of shows Year and the cell. The old explorer's `file` and `t` still open the same map, and
  `<id>/results` still redirects (301) with its query string.
- *Rail* (`map_page.entries`): every index the run calculated, a heatwave file's
  variables each an entry (`hwn_tx90` is `TX90-HWN`, named as the station pages name it),
  by theme (`themes.chip_of`, the Files tab's groups), codes first, the short name and the
  frequencies it has; the selected one on the selected tint with an ink edge. Find
  filters as you type (a GET form without JavaScript).
- *Toolbar*: the code and short name (h2), the catalogue's definition and the file's
  name; the view (`map_page.VIEWS`: Year, Base mean, Anomaly, Trend; see *Views*,
  below); Annual / Monthly (a frequency without a file struck through, not a link); the
  scale for SPI and SPEI; the stepper (‹ 2019 ›, by month for a monthly file, by day for
  `tx95t`; Year and Anomaly only); one line on what is shown, and under it, when the
  three views are unavailable, why; Download ▾: "Map as PNG"
  (`gridded:map_png?download=1`: `map_image.figure_png`, the cells, coastline, places,
  axes, title and legend drawn by matplotlib, light colours), "Map as CSV"
  (`gridded:map_csv`, every cell's latitude, longitude and value: the year's, the base
  mean, the anomaly, or on Trend the slope per decade and its 95% interval, named
  `txx_trend_1961-2020.csv` and so on) and the netCDF file (`gridded:file`). The PNG and
  CSV follow the view.
- *Views* (#296, `gridded/map_views.py`). Year (the value in one year or month), Base
  mean (`<index>_base_mean` of `trends.nc`), Anomaly (the year's value minus the base
  mean) and Trend (`<index>_slope`, Sen's slope per decade over the run's years, with a
  dot on each cell whose 95% interval, `_lower` to `_upper`, excludes zero; the legend
  says "Dot: the 95% interval excludes zero (583 of 896 cells)"). `trends.nc` holds the
  annual series only, so the three views (and the grid mean) are offered for an annual
  file, and for SPI and SPEI at the 12-month scale in December (choosing one moves the
  map there; the other scales are then unavailable and Anomaly steps by year); for a
  day-of-year file, or a run without `trends.nc` (calculated before #290, or with its
  trends turned off, the job's `trends` false) they are shown unavailable,
  `aria-disabled`, with the reason in a line under the controls
  (`map_views.unavailable`). `trends.nc` is read once per index (holding
  `netcdf.LOCK`, as every netCDF read on a request thread) and kept
  (`map_views.CACHE_BYTES`, 128 MB); its base period and trend period come from its
  attributes.
- *A monthly file's views* (#348). Base mean, Anomaly and the grid mean are of the chosen
  month, with or without `trends.nc`, computed in the web app from the month's values in
  every year (`map_views.month_trends`, kept with `trends.nc`'s fields):
  `climpact.gridded.trends.base_means` over the base period (the job's `base_start` and
  `base_end`, else the run's), and the cos-latitude weighted mean of each year
  (`climpact.gridded.trends`' weighted sums, in stripes of rows as `write_grid_trends`
  reads them), so the numbers are what the core would write for that month's series
  (`test_a_months_base_mean_and_grid_mean_are_the_cores`). The weights are the Y
  coordinate's cosine when it is latitude (its standard name or units say so, or its
  name, `Layer.y_latitude`); the index files hold no other latitude (a projected grid's
  two-dimensional latitude is in the input), so a month of such a grid has no grid mean,
  and the note says so. The hint names the month ("Mean of May in 1971–2000."), and the
  downloads too (`txx_05_base_mean_1971-2000.csv`, `txx_05_grid_mean.csv`). Trend is not
  offered for a monthly file ("Trend is of the annual series: choose Annual."): a
  month's Sen's slope on request was measured too slow on a large grid (on a synthetic
  700 x 900 grid of 60 years, chunked as the core writes it: reading one month 7.5 s,
  `sen_trends` of its 630,000 cells 4.5 s with 4 threads, 2.7 s with 11, 16.4 s with
  one), and writing monthly trends into `trends.nc` is left for a decision (#348).
- *The map.* Every cell, never thinned (the explorer's 2,500-cell cap, `MAX_MAP_CELLS`,
  went with it). `gridded:map_png` (`<id>/map.png`) is the field as an indexed PNG with
  one pixel per cell, north up and west left whatever the order of the file's rows and
  columns (`maps.frame`, `display_order`), each pixel its bin's colour and a cell with no
  value transparent (`map_image.raster_png`, written with zlib; no imaging library). The
  page draws it in an SVG `<image>` scaled without smoothing (`image-rendering:
  pixelated`) on the sunken surface, the plot's height from the grid's extent and the
  cosine of its mean latitude (at most 2.5 times its width), so the cells keep their
  aspect; over it the coastline (with a light halo, so it shows on the darkest bins),
  three to five places with a halo, the axes in degrees (`maps._ticks`: 1, 2, 3 or 5
  times a power of ten, or 10–90° steps for a wide grid) and the selected cell's outline,
  clipped to the plot. Both themes' PNGs are in the SVG and the stylesheet shows the one
  of the page's theme (`gmap__raster--light`, `--dark`). A grid whose axes are not
  latitude and longitude (`rlat`, `x`) has no coastline or places and plain axes.
- *Outline* (`gridded/outline.py`): `gridded/data/outline.npz` (233 KB) holds Natural
  Earth's 1:50m coastline and populated places (v5.1.2, public domain), built by
  `scripts/build-map-outline.py`, which names the source files. `coastline(box,
  tolerance)` gives the runs of each line inside the grid's box with a point either side
  (the SVG clips them), thinned to about 1.5 SVG units and without specks smaller than
  that, the outline shifted a turn for 0–360° grids; a global 145 x 192 grid's coastline
  is about 150 KB of path. `places(box)` picks up to five, most prominent first (scale
  rank, then population), none near the edge or another.
- *Colour.* Eight fixed bins per index and view, from a sequential scale by the index's
  kind (`maps.kind_of`): `temp` (values in °C, blue through pale yellow to red), `warm`
  (Heat counts, and the other indices where more is warmer), `cool` (Cold counts,
  `hddheatn`, `tmlt5`, `tmlt10`), `wet` (Rain), `dry` (Drought); tokens `--map-seq-<kind>-1`
  ... `-8` in both themes, in `chart-palette.json` as `map_sequential` (see
  [Design system](#design-system)). The breaks (`maps.edges_for`) are round numbers a
  round step apart (`nice_edges`) over the 2nd to 98th percentiles of the values of up to
  20 years spread over the file (of the month, for a monthly file), from at most 250,000
  cells each, starting at zero for counts and amounts: fixed for the file, so one year's
  map compares with another's; values beyond the ends are in the end bins. SPI and SPEI
  use their standard classes (−2, −1.5, −1, 1, 1.5, 2; McKee et al. 1993), near normal
  split at zero (#296) so the eight bins are symmetric about it, on the wet diverging
  scale (dry brown, wet teal). Base mean uses the kind's sequential scale with breaks over
  the base means (`map_views.sequential_edges`; SPI and SPEI diverging). Anomaly and
  Trend use a diverging scale (`map_views.scale_of`): `--map-div-temp-*` (blue for
  cooler, red for warmer) for temperatures and counts, `--map-div-wet-*` (brown for
  drier, teal for wetter) for Rain, Drought, SPI and SPEI, reversed for the `cool` and
  `dry` kinds (FD, ID, CSDI, TX10p, TN10p, CDD and the like), so warmer and wetter read
  the same way on every map; in `chart-palette.json` as `map_diverging`. Their breaks
  (`map_views.symmetric_edges`) are symmetric about zero, a round step apart, the last at
  or above the 98th percentile of the values' size: on Anomaly over the anomalies of up
  to 20 years of the file (`anomaly_edges`), so the years compare. The legend: the bins
  with their breaks, "Cells with a value: low to high" for the map shown, "No value",
  and on Trend the dot's key with the count.
- *Dots on Trend.* The PNG draws each cell `map_views.dot_factor` pixels a side (about
  1.5 SVG units a pixel for the cell's drawn width; 2 to 64, at most 4 million pixels,
  so 2 on a large grid) and a disc about 3.5 units across in the middle of each
  significant cell (`dot_mask`; one pixel where the cells are small, a texture over the
  area), in `--color-text` or `--color-surface`, whichever stands out more from the
  cell's bin (`with_dots`). The values the read-out uses (`map.f32`) then hold a second
  grid, 1 where the interval excludes zero, and the read-out says "significant" or "not
  significant".
- *Interaction* (`js/gridded-map.js`). Links and forms in the map swap the map block in
  place (`X-Climpact-Part: map`; the view answers `gridded/_map.html` alone and `Vary`
  says so), push the address (Back and Forward work) and keep focus on the control used.
  The cell under the pointer is read out in a line under the map and a tooltip, from
  `gridded:map_values` (`<id>/map.f32`: float32, the map's order, NaN for no value,
  fetched when first needed, gzipped); a click selects it. The map is one focusable group
  (`aria-roledescription` "map"): the arrow keys move the selected cell (Shift: ten), a
  polite live region reads it out with its value, and the pane follows after 0.6 s
  (Enter at once): the pane alone is swapped (`X-Climpact-Part: pane`) and the address,
  links and forms take the new cell. Without JavaScript the map is an image with its
  text alternative, and a `<noscript>` form chooses the cell by latitude and longitude.
  The PNG, values and map CSV leave the cell out of their address, so they stay cached
  (`Cache-Control: private, max-age=86400`, an `ETag` of the file and the query; 304).
- *Cell pane*: "Selected cell" or "Mean over the grid" (#296: `<index>_grid_mean` of
  `trends.nc`, the cos-latitude weighted mean of the cells with a value, titled "Mean
  over 1,896 cells" with "Weighted by the cosine of latitude; cells with no value left
  out.", the same chart, statistics, values table and CSV, `txx_grid_mean.csv`;
  unavailable without `trends.nc`, as the views; for a monthly file the month's, #348;
  choosing a cell shows the cell); the cell's
  centre in mono as the h2, its place in the grid and its bounds; Go to (a GET form,
  `map_page.parse_goto`: `−33.86, 151.21` or `33.86 S 151.21 E`; outside the grid or
  unreadable it says so). The series: by year, of the chosen month for a monthly file,
  by day of the year for `tx95t` (`map_page._series`), as the index page's interactive
  chart (#283: `index_page.payload` with the base period, the 11-year running mean,
  Sen's slope and its 95% interval; `data-chart-at` marks the year on the map), with
  `index_detail.chart` as the server's drawing without JavaScript and in print. Then the
  statistics in the station pane's order: Sen's slope per decade, 95% interval,
  significant, the base-period mean, the year shown with its anomaly, the record (highest,
  or lowest for TNn, TXn, SPI and SPEI); then the values by year as a table and "This
  series as CSV" (`gridded:series_csv`). Where `trends.nc` has the series (#296), the
  slope, its interval and the base mean are its numbers for the cell, the ones the map
  shows (`map_page.trends_summary`; for a monthly file the base mean is the month's,
  #348); otherwise the trend is `climpact.trends.plot_trend`
  of the series, computed on request, the function `trends.nc` uses (the end-to-end test
  compares them). The chart's line is always computed on request. When a
  station of the browser's workspaces (the same owner token) lies in the cell, a box
  names it (and its workspace) with "Open its TXx", the station's index page
  (`stations:result`; a heatwave entry's key is its code, `TX90-HWN`).
- *Reading.* The core's index files hold each cell's whole series in one chunk, so one
  year's map reads and decompresses the whole file. `maps.variable_values` therefore
  reads a variable once, whole, as float32 with fill values and non-finite values (R's
  `-Inf` EHF-HWPS) as NaN, and keeps the most recently used ones in memory up to
  `maps.CACHE_BYTES` (256 MB; a larger variable is read a step or a cell at a time, and
  remembered as too large, so its header is not opened again to find out); the
  breaks are kept per file. A monthly variable too large to keep is read a month at a
  time (#348, `maps.month_values`: the month's step in every year in one strided read,
  which decompresses the file once) and the month kept with the variables when it fits,
  so the month's other years, its Base mean and Anomaly need no further read: on the
  synthetic 700 x 900 monthly grid of 60 years (1.8 GB as float32, 706 MB on disk), the
  first map of a month takes 8 to 11 s (the read; a machine under load), the month's
  other years 0.04 s and its Anomaly 0.13 s, where every year's map read the file again
  (6.4 s) before. Measured on synthetic files chunked as the core writes them
  (60 years of random values, zlib level 4, Apple M-series laptop): a 700 x 900 grid's
  page takes 0.92 s on its first visit (the whole read and the run bar's count of cells
  with data included) and 0.08 s after, its PNG (263 KB) 0.1 s; a global 145 x 192
  grid 0.18 s and 0.05 s. `test_gridded_map.py` counts, rather than times, the chunks
  each request decompresses (a wall-clock limit of a second failed on a GitHub runner,
  #354): on both grids the first visit decompresses the file twice (read whole and
  kept, and the run bar's count), the PNG and the values not at all; their time is only
  held under 5 s.
- *Threads.* The HDF5 library in the netCDF4 wheels is not built thread-safe, and the
  server answers requests on several threads (waitress): a Map page and its PNG, values
  and CSVs open the same files at once, which failed on CI with "NetCDF: Can't open HDF5
  attribute" and could crash the server. Every netCDF file the web app reads on a request
  thread is opened, read and closed holding one reentrant lock (`gridded/netcdf.py`:
  `dataset(path)` for the map's reads, the rail's heatwave variables, the run bar's cell
  count, New run's listing and the set-up page's file header; `LOCK` around the set-up
  page's inspection, the core reader's pre-flight and its estimate of how the files will
  be read); the jobs run in the worker's own process. `test_gridded_map.py` checks that
  every open on the Map's requests holds the lock, and runs the Map's reads (a layer, a
  year's values, a cell's series, the breaks, the cell count, a file's description) from
  eight threads at once with cold caches: without the lock that test failed about one run
  in six to eight ("NetCDF: Not a valid ID", "NetCDF: HDF error").

**Help** (see [Help](#help)). `gridded.files` is on New run (step 1). On the set-up
page the help is on request (#293): a quiet link in What to calculate
(`gridded.thresholds_file`, `gridded.base_period`), the index parameters (`param.<field>`,
and the note that the EHF definition is Nairn and Fawcett's only), Output files
(`gridded.output`, `gridded.institution`) and Computing (`gridded.workers`,
`gridded.max_values`); `gridded.variables` and `gridded.indices` are in the help index and
the guide. The gridded guide (`help/guides/en/gridded.md`) describes the screens.

**Data model.** `GriddedRun` (`gridded/models.py`): UUID; `owner` (the job owner token);
`name` (given on Rename, #289; blank: `runs.default_name`, through `display_name`);
`source` (`path`, `upload`, `sample`); `files` (each file's inspection as JSON); `names`
(the netCDF variable of `tasmax`, `tasmin`, `pr`); `options` (the set-up form's values and
the pre-flight result, plus what is worked out once: `checksums`, kept when the run is
started again, and `cells_with_data`, by indices job); `thresholds_job`, `indices_job`;
`next_thresholds_job`, `next_indices_job` and `next_settings` (`{"options", "names"}`),
a new start of a finished run waiting beside its results (#293, migration
`0003_gridded_run_next`). Retention as for workspaces when
they expire, whatever `WORKSPACE_EXPIRY` says (`gridded/retention.py`):
`JOB_RETENTION_DAYS` after the last change unless a job (or a new start's) is
queued or running; only the run's own folder (uploads) is deleted, never a file read in
place. Gridded's note and the run's "kept until" say so in both modes; keeping local runs
until they are forgotten, as the GridList board's note has it, is #301.

**Checked in a browser** (headless Chrome over the DevTools protocol, local mode;
screenshots in the review folder of #85): Climpact's full sample grid
(`climpact.sampledata.gridded.1991-2010.nc`, 19 x 24 cells, 38 MB, netCDF-3) chosen by path
with the folder browser, thresholds then all 88 indices with 4 cores and rechunking forced
(the "Preparing the input files" stage shows): the thresholds took 4 s and the indices
2 min 16 s on a laptop; the bundled 3 x 4 sample; an upload of `grid_filled_360day` (two
files); `grid_stations` thresholds, then `grid_future` indices with that file (and its
refusal when the base period overlaps the data). The map, cell clicks, the variable,
time and scale selects, the tables, light and dark themes, and 375px wide pages (no
horizontal scrolling) were checked. The Map of #295 was checked on synthetic index files of a
47 x 55 grid of south-eastern Australia at 0.25° (1961–2020) with a station of the
browser in Sydney's cell: the rail, the map with its coastline and places, the legend, the
pane and its chart, light and dark at 1280px; the read-out under the pointer, the arrow
keys and the live region, the pane following, the rail, stepper, Back and Go to.

**Tests** (`test_gridded_web.py`): inspection of the sample, the 360-day reference grid in
two files, and broken files; the path checks, browser and upload (and the 413 above the
gridded limit); hosted mode off by default and, when on, uploads without paths; the
set-up checks and every validation message; the pre-flight; a full run of the sample
(thresholds, then five indices with `rx_days` 3, copied to a folder) with the map,
series, CSVs and zip, the CSV values checked against the netCDF; indices of `grid_future`
with the thresholds file of `grid_stations`, as R's reference run (Gridded's "From
<run>" and "file kept"); a failed job; the map drawing; ownership and retention. Since
#289: Gridded with no runs and with runs in each state, rename, the default names and
spacing, the run's bar (breadcrumb, h1, provenance line, actions, tabs), the old results
address's redirect, the Files tab's groups by theme, variable and frequency, a group's
zip, the links for `wget -i` (a file served to another client with the key, not without),
`run.json` (the sample's SHA-256) and `climpact.log`, the Forget page, and no stepper on
any gridded page. Since #291: the sample split into 20 yearly files, inspected and
grouped (one choice per variable, the joined period), a gap, an overlap and units or a
calendar that differ, each named by its files; up to 200 files by path and upload (150
uploads reach the form); the Files table's row for the 20 files, and a full run of them;
a file that cannot be used in a row of its own. Since #293: the set-up page's sections
in the board's order and its one Start button; the Variables table's units and how they
are read; the Together line, timeline, coverage, the indices by code and the summary
panel's checks; the htmx answer with its out-of-band parts as the form changes (a base
period without enough days, a variable chosen twice, fewer indices, no index, a
thresholds file only, a cell-first copy); how each unit is read and converted
(`read_as`, `units_help`: metres, hourly rates, split files, units with no command);
the estimates (files, size, time, the base period's days in each calendar); ERA5-like
files with `tp` in metres (the problem, its CDO command, no job) and once converted; a
file's header (the page, the text, another session); a finished run's Set-up tab,
"Changed:", starting again with the results kept until the new run has finished, then
replaced (the old job and its folder deleted), and a new start that fails leaving them. Since #295 (`test_gridded_map.py` and the end-to-end test): the rail
(heatwave variables as entries, frequencies), the map of the last year, the SPI map of a
month at a scale, the old explorer's addresses, the pane and map parts and `Vary`, the
series CSV and the values against the netCDF, the pane's slope against `trends.nc`, the
PNG's size, 304 and orientation (one pixel per cell, transparent where there is no value),
the report figure, the bins, breaks and scales by kind, the palettes against the tokens,
the frame's orientation, cosine aspect and axes (a 0–360° global grid, a rotated grid
without an outline), the outline's coastline and places, Go to and its errors, the form
without JavaScript, the station box only for a station of this browser in the cell,
every cell drawn on 145 x 192 and 700 x 900 grids from one read of the file (#354:
chunks decompressed counted), and 404 for another
session. Since #296 (`test_gridded_map_views.py`): the scale by view and kind (FD and
CDD reversed, also through the page and the PNG's palette), the symmetric breaks, a
cell's Trend value in the map's values, CSV and pane against `trends.nc` and
`climpact.trends.sen_trend`, the dots (their count, the PNG's pixels), Base mean and
Anomaly against `trends.nc` with the same breaks every year, the grid mean (title, slope,
CSV against a weighted mean), SPI's views at the 12-month scale in December, a monthly
file and runs without `trends.nc` or with trends off keeping Year with the reason, and
the netCDF lock held by every read of the views. In a browser (`test_accessibility.py`):
axe on the Map in both themes, 320px, and the map by keyboard; since #296 also axe on the
Trend view with the grid mean, and the views and the grid mean by keyboard.

### Size budget

The app must work on slow connections (#11). #82 set the budgets, which CI enforces in its
own step (`tests/test_page_budget.py`, also part of the full `pytest` run), and made pages
and static files smaller on the wire. The user was away when the budgets were set; they
follow the examples in the issue and are recorded on #82.

**Budgets.** A page's cost is everything the browser fetches before it can render: the
HTML and every stylesheet, script, icon sprite and favicon it links. Content htmx loads
afterwards (progress fragments, the set-up checks) and chart data are not counted.

| Budget | Limit | Measured |
| --- | --- | --- |
| First page (landing, `/`) | 100 KB gzipped in total | 34.9 KB |
| Any other page, chart code included | 300 KB gzipped in total | 147.7 KB at most (the quality-check results, #77, #174, #202); 124.8 KB for the gridded results, worst-case map, with the chart code |
| Any page's HTML, uncompressed (parsing and memory on slow devices) | 2 MB | 1.4 MB at most (the gridded results, worst-case map) |
| Chart code (uPlot, `charts.js`, #75) | only on pages marked `charts=True` | Quality (its "Your data" series since #198, and the checks' charts), a station index's page (#78; again since #283, after #237 drew it on the server only) and the gridded results |
| Each static file, gzipped as served | `ASSET_BUDGETS` in the test | e.g. `climpact.css` 16.7 of 16.75 KB (16.5 KB before #235 added Quality's worklist and its strips; 15.6 KB before #227 added the tokens, app shell, context bar and data table; 14.8 KB before #203 added the phone layout; 14.4 KB before #202 added Quality's list and detail; 14.1 KB before #201 added the New station page; 14.2 KB before #200 removed the index cards and accordions; 14 KB before #198, 13.5 KB before #197, 13 KB before #196), `drawer.js` 1.0 of 1 KB, `site-header.js` 0.4 of 0.5 KB (every page, #284), `help-toc.js` 0.6 of 0.75 KB (help pages with On this page, #325), `context-bar.js` 0.9 of 1 KB (station pages only; `workspace.js` until #227, #197; 0.4 KB until #203 added the phone's ⋯ menu and sticky offset), `setup.js` 0.6 of 0.75 KB (a station's setup page only, #201; 0.7 KB until #271 removed the first visit's drop zone), `sheet.js` 1.3 of 1.5 KB (station pages only, #198; 1 KB until #199 opened a sheet from an old address), htmx 16.9 of 18 KB, `ui.js` 4.4 of 4.5 KB, `theme.js` 0.3 of 0.5 KB, `turnstile.js` 2.0 of 2.5 KB (Turnstile pages only) |

Every stylesheet, script, SVG and JSON file in the package must have an entry in
`ASSET_BUDGETS` (a test fails otherwise); #75's files: uPlot 21.5 of 24 KB, `charts.js`
10.6 of 14 KB (with #77's additions), uPlot's CSS 0.7 of 1 KB (vendored as released; since #118 it is built into `climpact.css` and no page links it), gzipped. To add a page, add a
function returning its URL to `PAGES`. #77 added `qc.css` and `qc.js` (1.5 KB each) and the
quality-check results page (the Sydney sample checked: every section, the four chart
frames and the distribution plots, 371.8 KB of HTML, mostly the inline SVG box plots by
year). #174 made it a worklist: 472.3 KB of HTML (51.2 KB gzipped), the extra being each
group's first table page and the days around each finding, all in closed `<details>`;
`qc.js` 1.8 of 2 KB. #202 made it a list and detail: 564.6 KB of HTML (72.2 KB
gzipped, 147.7 KB with everything it links), the extra being every item's detail in the
page, hidden but the selected one, each finding's chart of the 30 days either side, and
"Your data"; `qc.js` 2.7 of 3 KB. #235 made it a compact worklist: 567.2 KB of HTML
(72.1 KB gzipped), each finding's chart now of the 7 days either side, the tables' rows
denser; `qc.js` 3.0 of 3 KB. #264 made it a rail of checks and the selected check's
detail: 531.7 KB of HTML (71.3 KB gzipped), each check's two charts and one selected value
with the 3 days either side in place of every finding's chart; `qc.js` 3.2 of 3.5 KB,
`climpact.css` 18.7 of 19 KB (the raw stylesheet's limit 114,000 bytes, 110,000 before).
#283 made the charts read out their values: the index page loads the chart code again and
carries its chart's data (TXx: 93.1 KB of HTML, 15.9 KB gzipped, 101.0 KB with everything
it links; monthly: 416.7 KB, 57.8 KB gzipped, 143.0 KB); the Indices' detail charts carry
only where each value is drawn, their values fetched when first used (610.1 KB of HTML,
89.5 KB gzipped; about 1 KB gzipped more than before); Quality's check charts carry their
values (550.2 KB, 75.9 KB gzipped, 168.2 KB in total). `charts.js` 15.4 of 16 KB,
`chart-readout.js` 3.6 of 4 KB, `qc.js` 3.5 of 3.75 KB, `index-page.js` 1.3 of 1.5 KB.
#295 drew the gridded map as a PNG with every cell, under an SVG of the coastline: a
global 145 x 192 grid's Map is 170 KB of HTML and a 700 x 900 one 253 KB (mostly the
coastline's path and the form's latitude and longitude selects), the PNG 12 KB and 263 KB
(random values; real fields compress better), linked, not inline; `gridded-map.js` 3.7 of
4 KB; `climpact.css` 24.7 of 25 KB (raw limit 156,000 bytes, 142,000 before): the 80 map
tokens in two themes, the rail, map, legend and pane.
#276 (Overlay the series) took `climpact.css` to 26.8 of 27 KB (26.75 KB before; raw
limit 172,000 bytes, 170,000 before): the overlay page, its chart's slots and the values
table.
#78 added `results.css` (2 KB) and `results.js` (1 KB; 1.5 KB since #113 made the groups collapse; 2.25 KB since #200 added the column sorting, 2.0 KB used); #90 `sector.css` (1.5 KB) and
`sector.js` (0.75 KB) and the sector comparison's results page (R's sample wheat file against the Sydney
run: 42 bars, four scatter plots and their tables as inline SVG, no chart code). #79 added the station
downloads page (Files since #176, which grouped its files in closed disclosures and added
the quality checks' files: 119.1 KB of HTML, 7.3 KB gzipped) (the same run as the dashboard: every table and file with its size) and
its rules to `results.css`. #118 replaced every stylesheet with the one built by Tailwind
(`climpact.css`, 12.5 KB budget): pages that loaded few page stylesheets grew by 2 to 5 KB
gzipped (the landing page from 34.9 to 39.8 KB), since the one file carries every page's
components, and it is fetched once and cached for every page after.

**How it is measured.** The test runs `collectstatic` with the deployment storage into a
temporary folder, renders each page type with the real views (creating the session's
analysis, batch, job or gridded run first), asks for it with `Accept-Encoding: gzip, br`,
and adds the gzipped HTML to the size of the `.gz` copy of each linked file (the file itself
if WhiteNoise kept no compressed copy). Gzip is the budget because every browser and proxy
supports it; Brotli is printed as well. The pages measured (`PAGES` in the test, by the
names it prints): the landing page; Add stations, starting a workspace, and its review of
the sample batch; a station's setup page with the sample loaded (`station sample loaded`);
Quality with the checks queued (`station quality`) and with their results, Results while
the first run goes on (`station calculating`, #178), the dashboard of a finished run with
every index (R's `lat0` reference output for the Sydney sample), one index's page (TXx,
with the chart code) and a monthly one, the sector results (#90) and the Files page
(`station downloads`, #79, #176); the workspace overview of the sample batch queued; the
job list and a job; gridded start, new run, set-up, results of a finished run on a
100 x 100 grid (values all different) and its files; the help index, a guide, the indices
guide, the topic list and a search; and the 404 page. The pattern library is left out
(development only). The sizes print at the end of the test run, largest first. Measured
again for #346 on 2026-11-21 (KB); the table before it, last measured for #199, named
pages that have since gone (step 1 and step 2, replaced by Add stations and a station's
setup page, #201, #233):

| Page | HTML | HTML gzip | Total gzip | Total Brotli |
| --- | ---: | ---: | ---: | ---: |
| station quality results | 550.3 | 75.9 | 175.2 | 162.2 |
| station results, 80 indices | 610.2 | 89.5 | 150.5 | 141.5 |
| station index, monthly | 416.8 | 57.9 | 150.0 | 137.9 |
| station quality | 103.3 | 23.4 | 115.6 | 103.5 |
| gridded results, 100x100 grid | 78.2 | 17.9 | 112.8 | 100.4 |
| station index | 93.2 | 15.9 | 108.0 | 95.9 |
| station sector results | 165.9 | 22.0 | 76.8 | 68.7 |
| station downloads | 180.7 | 14.8 | 69.2 | 61.2 |
| gridded set-up | 54.6 | 9.7 | 64.4 | 56.3 |
| station calculating | 60.4 | 9.0 | 63.4 | 55.4 |
| help topics | 53.7 | 10.2 | 62.8 | 55.0 |
| help indices | 37.2 | 8.1 | 60.8 | 53.0 |
| landing | 22.3 | 6.1 | 60.5 | 52.5 |
| add stations, review | 16.6 | 4.1 | 58.4 | 50.4 |
| help guide | 21.0 | 5.3 | 58.0 | 50.1 |
| station sample loaded | 25.5 | 5.2 | 57.8 | 50.0 |
| workspace overview | 15.9 | 3.7 | 57.4 | 49.5 |
| help search | 22.8 | 5.2 | 57.2 | 49.6 |
| add stations | 10.5 | 2.9 | 57.2 | 49.2 |
| gridded files | 14.9 | 3.8 | 56.8 | 49.0 |
| help | 19.1 | 4.2 | 56.3 | 48.6 |
| gridded new run | 20.0 | 3.6 | 55.6 | 48.0 |
| gridded start | 9.7 | 2.6 | 54.7 | 47.1 |
| job | 9.5 | 2.5 | 54.6 | 46.9 |
| jobs | 7.8 | 2.1 | 54.2 | 46.5 |
| not found | 7.1 | 1.9 | 53.9 | 46.3 |

About 52 KB of every page is shared and cached after the first (the 404 page links only
these): `climpact.css` (27.9 KB), htmx (16.5 KB), `ui.js` (4.4 KB), the icon sprite
(1.5 KB), `drawer.js` (1.0 KB), `site-header.js` (0.4 KB), `theme.js` and the favicon
(0.2 KB each), all gzipped.

**Compression and caching.**

- *Static files* (`core/storage.py`): `StaticFilesStorage` is WhiteNoise's
  `CompressedManifestStaticFilesStorage`, so `collectstatic` writes each file under a name
  with a hash of its contents (`main.f3fea2c28438.css`) and gzip and Brotli copies (the
  `brotli` package is a dependency). WhiteNoise sends the Brotli or gzip copy the browser
  accepts, and hashed names with `Cache-Control: max-age=315360000, public, immutable`, so
  a returning visitor fetches only the HTML. Hosted mode collects at deployment; local mode
  collects into `<data dir>/static` when `climpact-web` starts (about 0.25 s once the files
  are there), with `LocalStaticFilesStorage`, which falls back to the plain name for a file
  not collected (served from the package by WhiteNoise's finders, with a 60 s cache), so a
  page never fails for want of `collectstatic` (`climpact-web manage ...` commands, tests).
  `StaticFilesMiddleware` is WhiteNoise without its warning when that folder does not exist
  yet. `design_snapshots` renders plain names, as it copies the source folder.
- *Minified CSS*: the storage strips comments and whitespace from stylesheets as it saves
  them (`minify_css`): strings are kept, and spaces are removed only next to `{ } ; ,`, so
  selectors such as `.a :focus` keep their meaning; a test checks that every stylesheet
  keeps the same sequence of selectors and declarations. Since #118 the stylesheet arrives
  minified by Tailwind, and this pass changes little. Scripts are not minified: htmx comes minified, and minifying `ui.js` would
  need a JavaScript minifier for about 1 KB gzipped; the sources stay readable.
- *Pages*: `CompressionMiddleware` is Django's `GZipMiddleware` limited to text answers
  (HTML, htmx fragments, JSON, CSV, SVG); streamed files (zips, netCDF, PNG) are left
  alone. Django pads each compressed answer with random bytes against BREACH and masks the
  CSRF token afresh on every response. Pages compress to between a quarter and a third of their size.
- *Gridded map*: since #295 the map is a PNG with one pixel per cell, linked from the
  page, so every cell is drawn and the page grows only with the coastline (about 150 KB of
  path for a global grid, before gzip) and the form's latitude and longitude selects; a
  700 x 900 grid's page is 253 KB of HTML. Until then an inline SVG of at most 2,500 cells
  (`MAX_MAP_CELLS`, 40,000 before #82, when a 100 x 100 grid gave 5.5 MB of HTML).

**Slow 3G.** Measured once, for #82 on 2026-11-14, with headless Chrome over the
DevTools protocol (`Network.emulateNetworkConditions` with DevTools' Slow 3G values:
2,000 ms latency, 50,000 bytes/s down and up), local mode started with `climpact-web` on
a fresh data folder, cache disabled for the first visits. Times are from the start of
navigation; bytes
are the transferred sizes of every request. These are historical: the station pages
timed, step 1 and its "Continue" to step 2, have since been replaced by Add stations and
a station's setup page (#201, #233), which have not been timed this way (their sizes are
in the table above).

| Visit | First contentful paint | Loaded | Transferred | `main` before #82 |
| --- | ---: | ---: | ---: | --- |
| Landing, first visit | 5.1 s | 7.5 s | 34.9 KB, 8 requests | 5.7 s, 8.7 s, 129.6 KB |
| Station step 1 (upload), first visit | 4.3 s | 6.7 s | 33.3 KB, 9 requests | 5.1 s, 7.9 s, 124.5 KB |
| Landing, cache warm | 2.1 s | 2.1 s | 4.6 KB | 2.1 s, 2.3 s, 13.5 KB |
| Step 1 from the landing page | 2.1 s | 2.1 s | 3.8 KB | 2.1 s, 2.3 s, 11.7 KB |
| "Try with sample data" (POST and redirect) | 4.1 s | 4.4 s | 20.1 KB | 4.1 s, 5.6 s, 77.1 KB |
| "Continue" to step 2 (POST and redirect) | 4.1 s | 4.1 s | 3.2 KB | 4.1 s, 4.2 s, 9.4 KB |

The station flow of that time was usable on Slow 3G: each step showed in about two round
trips once the shared files were cached, and the first visit was dominated by latency
(connection, HTML,
then the stylesheets and scripts in parallel), not by bytes. Before #82 the landing page
was 129.6 KB in local mode, over its budget: neither the HTML nor the static files were
compressed there. In hosted mode the static files were already compressed, but not the
pages. The scripts are `defer`red, so the first paint waits only for the stylesheets.

### Charts

The interactive charts (#75) for the QC review (#77), results dashboard (#78), gridded
clicked-cell series (#85). The sector screen (#90) draws its bar chart and scatter
plots as inline SVG instead (see [A station's pages](#a-stations-pages)). The R app draws static PNGs (and
`plotly` only for the QC histograms); here the static PNGs and PDF are still written by the
core (`climpact.plots`, see [Plots and zip archive](#plots-and-zip-archive)), and the
screens show the same series as interactive charts.

**Pieces.** uPlot 1.6.32, vendored in `vendor/uplot/` (MIT; version, source URLs and
SHA-256s in its README, checked by `test_charts.py`); `js/charts.js`, a plain script
with no build step that hydrates the design system's `chart_frame`; the chart styles
(`core/tailwind/components/charts.css`, in the one stylesheet); the
`charts` app, whose JSON views give each chart its data. ECharts was not added: every chart
the screens need (lines, bars, markers, a trend overlay, two synchronised panels) is a time
series uPlot draws, and a trimmed ECharts build is several times uPlot's size against the
budget of #82.

**Template API.** A page with charts loads the assets in its `head` block and includes the
frame with a data URL:

```django
{% load charts %}
{% block head %}{% chart_scripts %}{% endblock %}

{% url "charts:station_daily" analysis.pk as daily_url %}
{% include "components/chart_frame.html" with id="daily-chart" title=title data_url=daily_url csv_href=csv_url height="24rem" only %}

{% url "charts:job_series" job.pk "txx_ANN" as txx_url %}
{% include "components/chart_frame.html" with id="txx" title=title data_url=txx_url|add:"?station="|add:station image_src=png_url only %}
{# an example: the index page draws its chart on the server (#237) and from the page's own data (#283) #}
```

**The page's own data** (#283). A frame with `data-chart-data="<id>"` instead of a data
URL reads its payload from the page's JSON script of that id: the index page
(`stations/result.html`) writes `index_page.payload` with `json_script` as
`#index-chart-data`, so its chart needs no request and draws exactly what the server
computed (the base-period means, the running means, the anomalies and why each value was
left out, none of which the `charts:job_series` payload has). Its frame is
`.index-figure`, not `chart_frame`: the server's chart (`_index_chart.html`) stays inside
it, unchanged, and shows without JavaScript; `_index_chart_tools.html` adds
`chart_toolbar.html`, the plot (`hidden` until drawn) and `chart_readout.html` (the parts
`chart_frame` includes too). Once drawn the figure gets `is-hydrated`, which hides the
server's chart on screen and shows it in print instead of the plot. If the data cannot be
drawn, the server's chart stays. `data-chart-view` names the view drawn first
(`index-page.js` changes it with the Values / Anomaly links,
`ClimpactCharts.setView(frame, key)`), `data-chart-at` a value to mark and read out
(`?at=1944`, which also selects that row of the values table).

Include it with `only`: otherwise a page variable named like a parameter (`summary`,
`legend`, `height` ...) leaks into the frame; Quality (the station file's summary,
`summary_context`) and the gridded set-up page both have a `summary` of their own.

`chart_frame` parameters: `id`, `title`, `summary`, `legend`, `height` (CSS length of the
plot area, default 16rem; the daily chart splits it 60/40 between its panels), `csv_href`,
`table_template`, and for an interactive chart `data_url` and `image_src` (a static image,
such as the run's PNG, shown instead without JavaScript). A summary, legend or CSV link
left out is filled in from the data; without `table_template` the table view is built from
the data. `{% chart_scripts %}` writes uPlot and
`charts.js` (deferred) and `#climpact-chart-text`, the script's strings in the interface
language. Only pages that include it load chart code: the landing page and Add stations
do not (tested). Frames swapped in by htmx are hydrated on `htmx:load`;
`ClimpactCharts.hydrate(element)` does it by hand.

**Data URLs** (`charts/urls.py`). All are GET-only and private to the session, like the
pages (another session's analysis or job is 404):

| URL name | Path | Payload |
| --- | --- | --- |
| `charts:station_daily` | `/charts/station/<analysis>/daily.json?variable=&flags=` | `daily`: the analysis's station file, with QC flags; `variable` (`tmax`, `tmin`, `dtr`, `prcp`) gives one variable alone, as the QC screen shows them (#77); `flags=0` leaves the flags and the summary's sentence about them out, for the station file's summary that Quality shows before the checks have results (`stations/_summary.html`, #173) |
| `charts:job_series_list` | `/charts/jobs/<job>/series.json?station=` | `series-list`: each plotted series of a station, in R's order, with `name`, `title`, `step`, `bars`, `url` (its data) and `csv` (its index file, `jobs:file`) |
| `charts:job_series` | `/charts/jobs/<job>/series/<name>.json?station=` | `index`: one series (`txx_ANN`, `txx_MON`, `3month_spi_MON`, `TX90-HWN_ANN`, `day_of_txx_ANN`, `tx95t_DAY` ...) |
| `charts:sample_daily`, `charts:sample_series` | `/charts/sample/...` | the pattern library's examples (with `PATTERN_LIBRARY` only) |

A job must have succeeded. `station` may be left out for a `station` job; for a `batch`
job it names a station that finished, and its `IndexParams` are read from the job's
metadata file (the output names of parameterised indices depend on them). Other apps
serve the same payload kinds from their own views with `charts.views.json_response` (the
caching); the gridded map's cell pane (#295) puts the index page's payload
(`index_page.payload`) in its page instead.

**Payloads** (`charts/data.py`, compact JSON, columnar, `version` 1):

- `daily`: `start` (first date) and `days`; `series`, one per variable (`tmax`, `tmin`,
  `prcp`, or the one asked for; `dtr` is TX - TN, token `--chart-7`) with `label`, `short`, `unit`, `panel`, `token` (the `--chart-*` colour) and
  `values`, one per day, `null` where missing; `flags.points`, `[day, variable, check]`.
  The x values are implicit (day *i* is `start` + *i*), so only values travel. The days are
  the core's `merged_rows` (every date from the first row to the last; a repeated date takes
  its last row, as the indices and the CSV download do; a test checks the payload against
  the CSV). The flags come from the core's QC checks (`climpact.qc`: `outliers`,
  `too_large`, `tmax_le_tmin`, `jumps`, `flatline`, `duplicate_dates`) run on the same rows
  with the thresholds of the analysis's latest quality check, else the workspace's
  (`Workspace.qc_params`; `views.analysis_qc_params`), each placed on the value the check reports: the outlier's
  variable (a DTR outlier on both temperatures and on DTR), each value over the `toolarge`
  limits, both temperatures and DTR for `tmaxmin`, the date a jump or flatline is reported
  on, and every variable of a repeated date (`duplicates`; no ring where the day's last row
  is missing, but the read-out and table view list it). `panels` names the panels of the
  series present (temperature, DTR, precipitation).
- `index`: `x` (decimal years, mid-month for monthly series, day of the year for
  `tx95t`), `y`, `dates` (the event dates of `txx`, `rx1day` ...), `title`, `units`,
  `axis`, `step`, `bars` (SPI and SPEI; optional `bar_labels` names the bars above and
  below zero instead of "wet" and "dry"), and `trend` (`slope`, `lower`, `upper`,
  `intercept`, `p_value`) with the core's `trend_text`. Everything comes from
  `climpact.plots.index_plots`, the function the static plots use, given a mapping that
  reads only the one table asked for: the trend is the trend file's Sen's slope and bounds
  (checked against the sample run's trend file) with `zyp.sen`'s intercept, drawn from the
  first to the last position, so the chart and the PNG show the same line.
- `index` with `layers` and `views` (#283, `stations.index_page.payload`, the index page
  only): `layers` has `base` (`from`, `to` in x units, `label`: the base period's band,
  whole years), `notes` (`[index, why]` of each value left out, as the table's Note),
  `smooth_label`, `gap_label`, `anomaly_label`, and `interval` (draw Sen's slope's 95%
  interval as a bow tie: the lines of `trend.lower` and `trend.upper` through the
  slope's middle, as `index_page.chart`). `views` has `values` and, where the page has
  the anomaly view, `anomaly`: each with `y`, `smooth` (the 11-year running mean of that
  view), `gaps` (`[index, level]`: the open point of each value left out, at the
  base-period mean or zero), `axis` (the y axis's title), `offset` (subtracted from the
  trend line: the base-period mean for anomalies) and, for anomalies, `signed_digits`.
  Values are rounded as the read-out writes them (`charts.data.shown`); the anomaly
  view's `y` and `smooth` once, to `signed_digits` places, half up as
  `numbers.anomaly` (`numbers.rounded`), so the read-out, which formats them again,
  gives the statistics' number, not a two-place value rounded twice (#349).
- `overlay` (#276, `stations.overlay.payload`, Overlay the series only): `x` (the years,
  or mid-month decimal years), `title`, `units`, `axis`, `step`, and `series`, one per
  drawn station, with `label` (its name, "· out of date" after it when it is), `short`
  (its name, for the read-out), `token` (its categorical slot, `--chart-1` to
  `--chart-8`) and `values` (`null` where missing, rounded as `charts.data.shown`).
  `charts.js` draws a line each (a dot for a value with no neighbour) and its read-out
  names only the stations with a value at the year.

Each payload has `summary`, a plain-language description written on the server and
translated: the period, extremes with their dates, missing values, flagged values, and the
trend per decade with its 95% interval and whether the interval excludes zero
(significance as in the trends guide; the trend file has no p-value). The daily payload of
an 80-year station is about 420 KB, 100 KB gzipped; an annual series 2-3 KB, a monthly one
about 30 KB.

**Caching.** Each response has an `ETag` (a hash of the source files' paths, modification
times and sizes, the parameters, the language, the schema version and the app version) and
`Last-Modified` (the newest source file), with `Cache-Control: private, no-cache`: the
browser keeps the data and revalidates, and an unchanged file answers 304 without being
read. Built payloads are also kept in a small in-process cache (24 entries) keyed by the
ETag. Responses are gzipped when the browser accepts it (`gzip_page`).

**Behaviour** (`js/charts.js`):

- *Lazy loading*: a frame's data is fetched when it comes within 200px of the viewport
  (`IntersectionObserver`; at once where there is none). Until then the frame's skeleton
  shows; a failed fetch replaces it with a message pointing to the CSV.
- *Daily*: a panel per kind of variable present, sharing the x axis, cursor and zoom:
  temperature (TX and TN lines), DTR, precipitation (bars); flagged values as hollow rings in `--chart-flag`, told apart by
  shape, small (7px) and at 75% opacity so the series shows through (#115: the Sydney
  sample has 423); the legend's "Flagged by the quality checks" entry is a toggle button
  (`aria-pressed`) that hides and shows them on every panel, and in the PNG and SVG
  exports; while hidden, a click picks the day under the pointer. Missing days as gaps. *Index*: a line (with hollow markers for annual series),
  in its theme's hue (`--hue` from the frame's `hue-*` class, #196; `--chart-1` without
  one), the trend dashed in `--chart-trend`; SPI and SPEI as bars, wet (`--chart-1`) and
  dry (`--chart-2`), as in the static plots. *Index with layers* (#283): drawn as the
  server's chart is: the line without markers (1.4px) in `var(--hue, var(--color-other))`
  and the running mean (2.2px) in its `color-mix` towards the text colour, both resolved
  by the browser from the frame's CSS; the base period's band and label (the label only
  where the part in view is wide enough) and the bow tie in the text colour at 5% and 9%,
  under the series (uPlot's `drawAxes` hook); the zero line of the anomalies in
  `--chart-axis`; Sen's slope dashed; the values left out as open points (8px). The y
  range takes in the bow tie's ends.
- *Zoom and move*: drag across the plot to zoom, double-click to show all; the toolbar
  (zoom in, zoom out, earlier, later, show all) and, on the focused plot, the keyboard
  (`+`/`-`, Shift with an arrow key, `0`). The visible range is announced politely
  ("Showing 1972-03-31 to 1977-04-01") to screen readers after keyboard or button use.
  Zoom stops at 7 days (daily) or 4 steps.
- *Read-out*: the hovered date with each value, the event date and the QC checks that
  flagged it, in a line under the plot (hidden from screen readers). Since #283 the
  keyboard reaches it: on the focused plot the left and right arrow keys move a cursor
  (uPlot's, with its crosshair and points) from value to value, Home and End to the first
  and last in view, the view following a cursor that leaves it; each value is announced
  in the status line. An index chart with layers reads out the year (or `YYYY-MM`, as the
  table) with the date of the extreme, the value with its unit, the anomaly, the running
  mean, or why the value was left out.
- *Table view*: "View as table" lists the values in view (date, each series, trend, event
  date, flags), up to 1,000 rows; with more in view it asks to zoom in or use the CSV.
  It follows the zoom while open.
- *Export*: PNG (the canvases at the screen's pixel ratio, with title, visible range and
  legend) and SVG (redrawn from the data of the current view, each pixel column of a long
  series reduced to its lowest and highest value; uPlot's own axis ticks, read from its
  undocumented `_splits` and `_values`, with a fallback).
- *Themes*: colours come from `Climpact.chartPalette()`; on `climpact:themechange` the
  charts are redrawn at the same zoom. Width follows the container (`ResizeObserver`).
- *Picking and focusing a date* (#77, daily charts): `ClimpactCharts.focusDate(frame or
  id, "YYYY-MM-DD", {span: days})` shows `span` days (default 61) around the date, marks it
  with a dashed vertical line (`--chart-flag`), shows its read-out and announces the range;
  it loads the chart first if it has not been drawn (returns a Promise).
  `ClimpactCharts.get(frame or id)` returns the chart. A click on a daily chart that is not
  a drag dispatches `climpact:chartpick` on the figure (bubbling) with `{date, index,
  checks, flagged}`: the nearest flagged day within 8px (`checks` the QC check keys that
  flagged it), else the day under the pointer; the day is marked. The QC screen's `qc.js`
  uses both.
- Numbers and month names use the page language (`Intl`); days are ISO dates (#115); dates are UTC. The plot area is
  `dir="ltr"`: time runs left to right in right-to-left languages too, as in printed charts.

**Accessibility.** The figure is labelled by the title and described by the summary; the
plot area is focusable (`role="group"`, `aria-roledescription="chart"`, described by the
summary and the keyboard hint), so a screen reader announces the summary on focus; the
table view and the CSV carry the data. Without JavaScript the toolbar and table stay hidden,
the frame shows `image_src` or a note, and the station step shows the static monthly
overview.

**Performance.** With the Sydney sample (29,220 days, three variables and 423 flags) in
headless Chrome at 390px wide with the CPU throttled 4x (a mid-range phone), each zoom or
move redraws in 18-37 ms. Pages and charts were checked in light and dark themes and at
390px; screenshots are in the review folder of the PR.
#276 (Overlay the series) took `charts.js` to 16.3 KB gzipped and its budget to 17 KB: the
overlay's model, a dot for a value with no neighbour, and the PNG and SVG exports'
legends wrapping onto rows.

**Size.** `charts.js` is about 35 KB (10.4 KB gzipped); uPlot 51.1 KB (22.0 KB gzipped);
together 32.4 KB gzipped, plus 1.3 KB of CSS gzipped. #283 (the index page's layers and views, the keyboard read-out) made
`charts.js` 54.8 KB (15.8 KB gzipped; 12.1 KB before; 56.9 KB and 16.3 KB gzipped with
Overlay the series, #276), and added `chart-readout.js`
(10.2 KB, 3.7 KB gzipped) for the charts drawn on the server. They are held by #82's
`ASSET_BUDGETS` and may load only on pages marked `charts=True` (see
[Size budget](#size-budget)): a station's setup page with the sample loaded (57.8 KB
gzipped in total, measured for #346; it shows no chart today), Quality with the checks
queued (115.6 KB) and with their results (175.2 KB, #77), a station index's page
(108.0 KB, 150.0 KB for a monthly index; #78, #283) and the gridded results (112.8 KB on a
100 x 100 grid), all under the 300 KB page budget. The results
dashboard (#78) has no chart code: its sparklines are inline SVG.

**Tests** (`tests/test_charts.py`): the vendored files' hashes; `charts.js` makes one
request (the data URL) and has no other dependencies; chart assets only on
chart pages; the daily payload (days, gaps, extremes, summary) and that it matches the CSV
download; the QC flags against the core checks (the sample's TN >= TX day, TX jumps and
`toolarge` days, every outlier row, stricter thresholds flagging more); index payloads
against the trend file and `index_plots`; SPI bars, `day_of_` without trend; the views'
JSON, 304 on `If-None-Match` and `If-Modified-Since`, new validators after a file
changes, gzip, 404 for another session, an unfinished job, an unknown series or station;
batch stations; the pattern library examples; the frame's markup, and that a page's own
`summary` does not leak into it. The gridded cell pane's chart (#295) is the index
page's payload in the page (`data-chart-data`), checked in `test_gridded_web.py`.
`test_index_page.py` and `test_indices_results.py` (#283) check the index page's payload
(layers, views, gaps at the base-period mean, notes, the trend's offset) against the
tables, `?at=`, and the Indices' read-out data against `charts:job_series`;
`test_qc_review.py` the read-outs of When (by date, at the ring's place), By calendar
month and the 7-day chart; `test_accessibility.py` reads out the index chart (annual,
anomalies, SPI by month), the Indices' detail chart (Enter opens the index page at that
year) and Quality's three charts (Enter on When selects the row) by keyboard.
`test_qc_review.py` (#77) checks that every flag of the `qc_stress` station's QC files is
on the chart of its variable and in its table (every page), the per-variable payloads, the
thresholds against `QCParams` and R's limits, the job's files against R's, the verdict
(green, amber and red, both red triggers at and just over their limits, and the limits
changed in one place), the findings and groups of the stress station, the missing-data
rules, the table pages of the checks and groups and the page of a date, re-uploading a corrected
file (the details and thresholds kept), "See results" opening the results of the
speculative run (#178) and 404 for another session.
The drawing itself was checked by hand as above; `test_accessibility.py` (#83) checks the
charts' keyboard use, announcements, table view and that they redraw to fit when the
window narrows. #77's linking (a table row to the chart, a ring to its
table rows on another page, the pager's focus) and the QC page at 390px and in both themes
were checked in headless Chrome over the DevTools protocol; screenshots are in the PR's
review folder.

**Read-outs of the server's charts** (#283, `js/chart-readout.js`, on the Indices and
Quality pages and the pattern library). The Indices' detail chart and Quality's When, By
calendar month and 7-day charts stay SVG drawn on the server; an `svg[data-readout]`
becomes focusable (`role="group"`, `aria-roledescription="chart"`, described by the
`components/readout.html` keyboard hint) with a crosshair (`--chart-axis`, dashed) and a
ring (the text colour) on the nearest value, written in the read-out line under it; the
arrow keys, Home and End move between values, each announced in the status line, and
Enter (or a click) acts: `href` opens it with the value's key (the Indices: the index page
at `?at=1944`), `pick` dispatches `climpact:readoutpick` (When: `qc.js` asks
`stations:qc_table` for that date in the table's order, which answers its page, and
selects it). `data-readout` is single-quoted compact JSON (`charts.data.attr_json`): either
`points` (`[x, y or null, key, text]`: By calendar month, the 7-day chart) or a series
(`v`, or `src`, the series' `charts:job_series` URL, fetched when the chart is first used,
so the Indices page carries no values: about 1 KB gzipped for 80 detail charts instead of
45 KB; x from `x0` and `dx`, or day offsets `d`; y from `low`, `high`, `top`, `bottom`;
keys from `when`; the text from `label`, `unit` and the number rules). Built by
`index_detail.readout`, `qc_review.when_readout`, `months_readout` and `days_readout`.
Without JavaScript the SVG is unchanged.

**Pattern library.** "Interactive charts" shows the four kinds (daily with flags, annual
with trend, monthly, SPI bars) from the Sydney sample, through the same views. The design
snapshots (`design_snapshots`) open from disk without a server, so their charts show the
"could not be loaded" message.

### Accessibility

The audit of the finished app against WCAG 2.1 AA (#83). The full record (what was
checked, each finding and its fix, the screen reader checklist) is
`packages/climpact-web/docs/accessibility-audit.md`; the statement for users is the help
guide `accessibility` (`/help/accessibility/`), linked from every page's footer: target
WCAG 2.1 AA, status "partially conforms" until the screen reader checks are done by
hand, what was tested and how, the known limitations and how to report a problem.

**How the pages are checked.** `tests/test_accessibility.py` starts `climpact-web` on a
free port with its worker, in a fresh data folder, and drives the Chrome already on the
machine (`tests/browser.py`: headless, a temporary profile, the DevTools protocol over a
WebSocket with `websocket-client`; nothing is downloaded or installed). Chrome is found
from `CHROME`, then the usual install paths and `PATH`; without it the tests skip with a
message, unless `CLIMPACT_A11Y_REQUIRE_CHROME` is set (CI). The `site` fixture goes
through the Sydney sample station (every section, a recalculation, the sector comparison
with the sample sector file), a second sample station whose base period is changed and its
new run cancelled (Indices out of date under "Recalculate", #179), the sample
batch and the 3 x 4 sample grid (thresholds, then `txx`, `fd` and `spi`) in the browser, so
the worker runs real jobs (about a minute), and collects 38 pages and states, including
forms answered with errors (Add stations without a file and with a file it cannot read,
#233, and a station's setup page with wrong details, #201; the setup page is reached by a
new file from the File sheet that the base period does not fit, #271), the 413 page (a real over-limit upload) and the 500 page
(rendered from its template). The `audit` fixture opens each page once and reads:

| Check | How |
| --- | --- |
| axe-core | every rule tagged `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa` or `best-practice`, in the light theme and at 320 px; `color-contrast` and `link-in-text-block` again in the dark theme (`prefers-color-scheme` emulated, after the colour transitions end) |
| reflow | `scrollWidth` against the viewport at 320 CSS px and at 200% zoom (640 px at device scale 2), after the page has drawn, as when a user zooms; content inside a scrolling region is allowed to be wider |
| keyboard | Tab from a marker at the top of the body until focus leaves the page: every stop visible (or, for a visually hidden input, the control drawn for it) with an outline or box shadow on it or a near ancestor; no stop twice before the cycle ends (a trap); the skip link first, and Enter on it focuses `main`; no positive `tabindex` |
| forced colours | the same traversal under `forced-colors: active`, where only outlines count |
| reduced motion | under `prefers-reduced-motion: reduce`, no animation or transition over 0.1 s on any element or pseudo-element, and no smooth scrolling |
| structure | `lang`, a title, one `main`, one `h1`, the skip link's target, names on regions, focusable groups, toolbars, navigation and tab lists |

While the jobs run the fixture also runs axe on each progress page, records what the
announcer says, and checks that focus on the batch's Cancel button survives the polls.
Widget tests work the tabs, the workspace tabs (#179: one Tab stop each in order, named
with their status in words, `aria-current="page"` on the current one, Enter opens a
section, a section not yet available is no Tab stop), dialog, drop zone (Space opens the file chooser, caught with
`Page.setInterceptFileChooserDialog`), an index chart, the tour, the help search and the
gridded map by keyboard (#295: the arrow keys move the cell and the pane follows; the
stepper and the rail keep focus), and the quality worklist (#174): a group opens and closes
from its summary, "Show on chart" opens Details and focuses the chart, the "Upload a
corrected file" button is a Tab stop that shows its focus and opens the file chooser, and
axe passes with every disclosure open, light and dark (axe skips closed ones). The
phone layout (#203) and the sticky header (#284):
`test_sticky_header_and_context_bar_never_cover_focus` Tabs through the Indices, Quality, an
index's page, the landing page and a guide at 1280 and 320 px and fails when focus is
under the header or the context bar (on a phone the tabs and the Inputs bar stay under the
header, the name gone; in a 440px-high window neither sticks);
`test_fragment_targets_clear_of_the_header` follows a `#fragment` far down the Indices,
Quality, Files and a guide at 1280 and 375 px; `test_no_overlapping_sticky_elements`
scrolls the station and workspace pages at 320, 375, 1280 and 1440 px and checks that
nothing stuck to the window covers anything else stuck to it (what slides under the
header is hidden by it), and that the page never scrolls sideways; `test_phone_inputs_bar_opens_the_sheets`
opens the Inputs sheet from the bar and an input's sheet from it by keyboard, with axe at
375 and 320 px and Escape stepping back; `test_page_menu_by_keyboard` works the ⋯ menu;
`test_indices_phone_rows_keep_their_cells_apart` (#286) checks at 320 and 375 px, light
and dark, that no visible content of an Indices row's cell overlaps another's, runs out of
the row or is clipped (the name's ellipsis aside), also with the longest numbers written
into the first row.
`test_axe_every_page` fails on a serious or critical axe
violation and `test_no_axe_violations_at_all` on any; all pass. The whole module takes
about two and a half minutes locally (160 s on 2026-11-16; three of them in CI), so it is
marked `browser` (`pytestmark`; the marker is registered in `pytest.ini` and in
`packages/climpact-web/pyproject.toml`) and the default `addopts` deselect it with
`-m "not browser"` (#180): a plain `uv run pytest` starts neither Chrome nor the server.
Run it with `uv run pytest -m browser` (or `uv run pytest -m browser
packages/climpact-web/tests/test_accessibility.py`, or from `packages/climpact-web`), before a pull
request that touches templates, CSS or JavaScript. The last `-m` on the command line wins,
so `-m browser` replaces the default; naming the file without it deselects every test in
it, the axe hash check included. `CLIMPACT_A11Y_REPORT=<folder>` writes `report.json` and screenshots
of every page (light, dark, forced colours, 320 px). axe-core (4.14.0, MPL-2.0) is a test
asset in `tests/assets/axe-core/`, injected with `Runtime.evaluate`; its README records the
source URL and SHA-256, which `test_vendored_axe_is_the_pinned_release` checks. It is
never served or packaged.

**Where the time goes, and the waits (#182).** Before each check `Chrome.settle()`
(`browser.py`) waits until the page has loaded, no htmx request is in flight and no
chart is loading (`BUSY`). `charts.js` loads a chart only when it comes within 200 px of
the viewport, so a chart further down the page or in a hidden tab panel keeps its
skeleton until it is scrolled to: `BUSY` counts only charts that have asked for their
data, or are in view and about to. It used to count every skeleton, and on the pattern
library and the quality results each of the audit's four waits per page ran to its 10 s
timeout (86 s of the audit, and 10 s on each test that opened the pattern library), with
the same page in the end. After the dark theme is switched on, `transitions_done()` waits
for the running transitions to end rather than a fixed 0.6 s; the batch's focus check
waits for the progress to replace itself, and the chart test for each announcement,
rather than sleeping. What is left is mostly the jobs themselves (the `site` fixture,
about a minute: quality checks, the station run, the sector comparison, the batch and the
grid) and axe (about 1.3 s a page with all its modes). The jobs are not overlapped: the
local worker runs one job at a time, and the fixture watches each progress page while its
job runs (axe, the announcements, the batch's focus), so the jobs could not run unseen
side by side.

**Announcements and focus across htmx swaps.** Progress fragments replace themselves at
every poll (`hx-swap="outerHTML"`), so a live region inside one is new each time and
screen readers do not read it. The page shell has one persistent live region,
`#announcer` (`role="status"`, in `components/toasts.html`); a fragment marks its news
with `data-announce` (the stage of the checks, a station run, a sector comparison, a
batch, a gridded job and the job page) and `ui.js` copies the text there after a swap when
it has changed, at most every 10 s unless the element says `data-announce="now"` (the end
of a batch or a job, the help search's result count, the batch estimate, the gridded
set-up checks). `ui.js` also notes the focused control before an htmx swap and focuses
the same control after it (same id, or the same kind of control in a form with the same
action), so a keyboard user on Cancel is not dropped to the top of the page at each poll.

**Fixed by the audit.** Progress not announced and focus lost at each poll (above);
charts holding the page wide after a zoom or a narrower window, the gridded set-up form
and a calculation's long title wider than 320 px (see Responsive and right-to-left under
[Design system](#design-system)); the tour returning focus to its hidden invitation (now
to `main`); the 500 page given a `main`, a way back and theme-following system colours;
help guide tables, download tables and the index page's trend table given their own
names; the index chart's heading level; the pattern library's duplicate step indicator
names and second `h1`.

**Known limitations.** The PDF report and plots PDF are not tagged PDF/UA (matplotlib
cannot write a structure tree; PR #109); follow-up #110. The PNG plots have no text inside
the files (their data are in the CSVs). The gridded map's cells are mouse targets only;
the latitude and longitude selects are the keyboard route, and the map has a table.
Screen readers (VoiceOver, NVDA) cannot be driven here: the checklist in the audit file is
done by hand.

## Development

```sh
uv sync
uv run ruff check . && uv run ruff format --check .
uv run pytest               # in parallel (pytest-xdist, -n auto); -n 0 for one process
uv run pytest -m browser    # the browser accessibility checks, before a PR touching templates, CSS or JS
```

- The repository is a [uv](https://docs.astral.sh/uv/) workspace (#116; it replaced the
  two editable pip installs of #68). The root `pyproject.toml` is not a package: it lists
  the members `packages/climpact` (distribution `climpact`) and `packages/climpact-web`,
  and has a `dev` dependency group with both members and every development tool.
  `uv sync` makes `.venv` from `uv.lock` with both packages editable and that group;
  commands run through `uv run`. Each member also has its own `dev` group (PEP 735,
  replacing the old `[dev]` extras; plain pip 25.1+ can install it with `pip install
  --group`): the core's is what the `core` CI job installs. Groups are not transitive, so
  a tool added to a member's group must be added to the root's too. `.python-version`
  pins Python 3.12 for development, which is also the minimum (`requires-python >=3.12`
  in both packages, ruff `target-version = "py312"`; #117, needed by Django 6.0). `uv.lock` is committed and resolved for every supported Python; after
  changing a dependency, run `uv lock`. New T3 worktrees get the environment from the
  project's setup script, which should run `uv sync`.
- The `climpact-example-plugin` test package is installed by writing its metadata into a
  temporary folder (`tests/test_modules.py`), so its test needs no pip in the venv (uv
  venvs have none). To install it by hand: `uv pip install
  packages/climpact/tests/plugins/climpact_example_plugin`.
- CI installs uv with `astral-sh/setup-uv` (pinned to a commit SHA, uv 0.13.8, with its
  cache), sets the job's Python with its `python-version` input, and installs with
  `uv sync --locked` (fails if `uv.lock` does not match the `pyproject.toml` files).
- Every action in `.github/workflows/` is pinned to a full commit SHA, with the release
  tag in a comment (`actions/checkout` v7.0.1, `actions/upload-artifact` v7.0.2,
  `actions/download-artifact` v8.0.2, `actions/cache` v6.1.0 (its `restore` and `save`
  sub-actions), `astral-sh/setup-uv` v10.3.3, all running on Node 24), so a moved or compromised tag
  cannot change what CI runs.
  The repository's Actions settings are meant to enforce this ("require actions to be
  pinned to a full-length commit SHA", allowing only GitHub-owned actions and
  `astral-sh/setup-uv`), so an unpinned or unlisted action fails the run. To upgrade
  one, change the SHA and the tag comment together, using the commit the release tag
  points to (`gh api repos/<owner>/<action>/commits/<tag> --jq .sha`).
- CI has seven jobs. `secrets` (#138) runs gitleaks over the whole git history
  (`gitleaks git --log-opts="--all" --redact`, checkout with `fetch-depth: 0`) with the
  default rules and the allowlist in `.gitleaks.toml`. It downloads the pinned gitleaks
  release binary and installs it only if its SHA-256 matches the hash in `ci.yml` (no
  third-party action, read-only token, checkout pinned to a commit SHA); upgrade the
  version and hash together. `.gitleaks.toml` allowlists only exact placeholder values
  (`regexTarget = "secret"`, anchored), never paths: in gitleaks 8.30 a global allowlist's
  `paths` skip the whole file even with `condition = "AND"`, so they would hide a real
  secret added to that file. Run the same scan locally with `gitleaks git
  --log-opts="--all" --redact .`. `core` and `web` run on Python 3.12, 3.13 and 3.14: `core` checks
  `uv lock --check`, installs only the core with its dev group (`uv sync --locked
  --package climpact`), runs ruff, checks that `climpact_web` is neither installed nor
  imported in `packages/climpact`, and runs `pytest packages/climpact` (the full core
  suite, parity included; like every test step, in parallel with the default `-n auto`,
  one worker per vCPU, see [Running the tests in parallel](#running-the-tests-in-parallel)); `web` installs both packages (`uv sync --locked`), fetches the
  pinned Tailwind CLI (`scripts/fetch-tailwind.sh`), rebuilds the stylesheet and fails if
  the committed `css/climpact.css` differs (#118), installs GNU gettext from apt and runs
  `pytest packages/climpact-web` with `CLIMPACT_REQUIRE_GETTEXT=1`, so the message
  catalogue check fails rather than skips without `xgettext` (#205; see
  [Translations](#translations)) (without the size budget, which it `--ignore`s, and the
  accessibility tests, which the default `-m "not browser"` deselects), the size budget as its own step
  (`pytest packages/climpact-web/tests/test_page_budget.py`, see
  [Size budget](#size-budget)), `climpact-web manage check` and `makemigrations --check`. `web-postgres` installs the web package with the `postgres` extra and no dev group (`uv sync --locked --package climpact-web --extra postgres --no-default-groups`) and runs hosted mode against a Postgres 16 service
  container, including a station job through the worker (see [Tests](#tests)); a last
  step adds the dev group (`uv sync --locked --package climpact-web --extra postgres`)
  and runs `test_queue_postgres.py`, several workers competing for claims.
  `web-accessibility` (Python 3.12) runs `test_accessibility.py -m browser` in the runner's
  preinstalled Google Chrome (`CHROME=$(which google-chrome)`,
  `CLIMPACT_A11Y_REQUIRE_CHROME=1`, so a missing Chrome fails rather than skips) and keeps
  the report and screenshots as the `accessibility-report` artifact (see
  [Accessibility](#accessibility)). `image` calls the reusable `image.yml`, which builds
  the production image, smoke-tests it against Postgres and scans it, pushing nothing;
  `dist` builds both packages' sdists and wheels as a release does and checks them
  (`scripts/check_dists.py`, `twine check`, `scripts/smoke_dists.sh`; see
  [Releases and PyPI](#releases-and-pypi)). `release.yml` runs on a published GitHub
  Release and is the only workflow that uploads, pushes or deploys (see
  [Image in CI and on ghcr.io](#image-in-ci-and-on-ghcrio) and
  [Deploy on release](#deploy-on-release)).
- Start the web app with `uv run climpact-web` (see [Running the web app](#running-the-web-app)).

- Compute gridded thresholds with
  `uv run climpact gridded-thresholds <netCDF files> --out <file> [--tmax ... --base-start ...]`;
  a variable split along time takes its files, or a quoted pattern (`'tasmax_*.nc'`).
- Compute gridded indices with
  `uv run climpact gridded-indices <netCDF files> --out <dir> [--thresholds <file> --indices ... --workers N] [--trends]`
  (`--trends` also writes `trends.nc`, see [Gridded trends](#gridded-trends)).
- Correlate sector data with a station already run with
  `uv run climpact sector-correlation <station file> <sector CSV> --out <dir> [--no-detrend] [--plots] [--zip]`.
- Run a station from the command line with
  `uv run climpact run <station file> --out <dir> [--lat ... --lon ...] [--plots] [--zip] [--report]`
  (`climpact run --help` lists the options), or a batch with
  `uv run climpact batch <metadata file> <data dir> --out <dir> [--workers N]`.
- Python 3.12+, xclim 1.0.x, netCDF4 and dask (gridded data); matplotlib 3.8+ for the
  plots (the optional `plots` extra, also in the `dev` groups). The web package uses
  Django 6.0.x (`django>=6.0,<6.1`; #117 moved it from 5.2 LTS). Python 3.14 is in the CI
  matrix because every compiled dependency has wheels for it: numpy, scipy, pandas,
  matplotlib, brotli and psycopg-binary ship cp314 wheels, and netCDF4 and cftime ship
  `cp311-abi3` wheels, which cover it (xarray, xclim and Django are pure Python).
  CI runs on Python 3.12, 3.13 and 3.14 on **Ubuntu 24.04**
  (x86_64, glibc 2.39), pinned rather than `ubuntu-latest`. Its glibc is the C maths library
  the R reference was made with, so CI checks the SPI and SPEI files for text identity; on
  macOS they are checked to 1e-10 relative (`tests/libm.py`). Newer glibc releases differ:
  Ubuntu 26.04's `lgamma` differs from glibc 2.39 in the last bit on some inputs, so
  `test_libm_lgamma_matches_glibc_2_39` checks against fixed values printed in the R image.
- Always work inside `.venv`, through `uv run`.
- To regenerate the R reference outputs, station, sector correlation or gridded, see `reference/README.md`. Re-running changes the
  `Date_of_calculation` line in every CSV, so only commit a re-run when the numbers are
  meant to change.
- Work is tracked as GitHub issues on the
  [climpactpy Kanban](https://github.com/users/geoffwalmsley/projects/2), grouped under
  epics (#8 station parity, #9 QC, #10 gridded, #11 web, #12 deployment). Branches are
  named `<issue>-<slug>` and PRs say `Closes #N`. Each ticket names the reference files it
  should make pass. The full workflow is in `.claude/skills/ticket/SKILL.md`. A web ticket
  that changes what users see also names its design canvas boards (a "Design" section) and
  is built and checked against them with `.claude/skills/build-to-design/SKILL.md`; its
  pull request carries a "Design check".
