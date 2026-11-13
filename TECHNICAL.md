# climpactpy technical notes

Technical documentation for the Python port of [Climpact](https://github.com/ARCCSS-extremes/climpact).
It covers how the code is organised, how results are checked against the R version, and
every known difference between the Python and R implementations and how each is handled.

Reference version: **Climpact R v3.4.3** (commit `5ee0cfe`), with climdex.pcic 1.2-0.

## Status

The Python port reproduces **98 of the 117** R reference files for Sydney (`lat0` and
`sydney`), and every ported file R wrote for all 13 GHCN stations, with none failing (see
[Reference outputs](#reference-outputs)). Every ported file is also written text-identical
to R's on all 15 runs, apart from the `Date_of_calculation` line:

| Area | Ported | Not yet ported |
| --- | --- | --- |
| Threshold counts | fd, tnlt2, tnltm2, tnltm20, id, su, tr, txge30, txge35, tmge5, tmge10, tmlt5, tmlt10, r10mm, r20mm, rNNmm, custom index | |
| Means and totals | dtr, tmm, txm, tnm, prcptot, sdii | |
| Extremes (with dates) | txx, tnn, tnx, txn, rx1day, rx3day (rxdday), rx5day | |
| Spells (with dates) | cdd, cwd, gsl | |
| Degree days | hddheat, cddcold, gddgrow | |
| Percentile indices | tx95t, r95p, r99p, r95ptot, r99ptot, tx90p, tx10p, tn90p, tn10p, txgt50p (with the in-base bootstrap) | |
| Spell durations | wsdi, csdi, wsdid, csdid (`wsdi1`, `csdi1`), txdtnd, txbdtnbd (`tx2tn2`, `txb2tnb2`) | |
| Heatwaves | Tx90/Tn90 (HWM, HWA, HWN, HWD, HWF each) | EHF (8 aspects, daily EHF/ECF) |
| Drought | | SPI, SPEI (3, 6, 12 months and custom) |
| Other outputs | qc/nastatistics, thresholds file (`thres/thres`), CSV files for all ported outputs | trend file, other QC outputs, plots, zip archive |
| Running | single station (`climpact run`), batch of stations from R's metadata file (`climpact batch`) | gridded data |

Progress is printed at the end of every test run (see [Parity testing](#parity-testing)).

The Python port writes every ported output as a Climpact-format CSV file, text-identical
to R's apart from the `Date_of_calculation` line (see [Writing output files](#writing-output-files)).
It does not yet write plots or zip archives.

## Repository layout

```
src/climpact/
  cli.py             command line: `climpact run` (one station) and `climpact batch` (many)
  batch.py           batch mode: R's batch metadata file, run_station(), run_batch() process pool
  config.py          StationMetadata, IndexParams, CustomIndex (Climpact app defaults)
  station.py         StationRun (with cached base-period thresholds) and load_station()
  thresholds.py      base-period percentile thresholds; climdex and R type-8 quantiles
  data/
    climate.indices.csv  index definitions, copied unchanged from Climpact R (file headers)
  io/
    station.py       read Climpact/RClimDex station text files; build the xarray Dataset
    climpact_csv.py  read and write Climpact (R) output CSV files; R number formatting
    output_files.py  file names, folders and metadata headers; write_outputs()
  missing.py         climdex.pcic missing-data rules; registered with xclim as "climdex"
  outputs.py         registry of products that build Climpact-format output tables
  products/
    tables.py        shape results into Climpact's table layouts; standardised anomalies
    indices.py       index products
    heatwaves.py     Tx90/Tn90 heatwave products; hw_aspects(), shared with the EHF heatwaves
    thresholds.py    thresholds file and tx95t products
    qc.py            QC products
  compare.py         tiered comparison of tables against the R reference
  rnumerics.py       exact emulation of R's extended-precision sum, cumsum, mean and var
tests/
  parity/            one test per R reference file, plus progress reporting
  test_*.py          unit tests
  data/              unit-test fixtures (quantiles printed by R) and the R scripts that print them
reference/
  stations.csv       one row per R reference run: station, coordinates, period, input source
  fetch_ghcn.py      download GHCN-Daily stations and convert them to Climpact input files
  input/             station input data used by the tests
  output/            R reference outputs, output/<run>/<station>/ (CSV only; plots are gitignored)
  r/, run_r_reference.sh   Docker setup that produces reference/output (see reference/README.md)
```

## Data flow

```
station text file
  -> io.station.read_station_file   DataFrame(date, prcp, tmax, tmin), invalid dates dropped
  -> io.station.station_dataset     xarray Dataset on a full-year daily axis
  -> StationRun(data, metadata, params)
       run.thresholds               base-period thresholds, computed on first use and cached
  -> outputs.build_all(run)         {"indices/fd_ANN": DataFrame, ...}
  -> io.output_files.write_outputs  <out>/<station>/indices/<station>_fd_ANN.csv, ...
```

`climpact run` (`climpact.cli`) runs the whole chain for one station file
(`batch.run_station`). Station settings and every `IndexParams` value are options;
defaults are the Climpact app defaults, and the station name defaults to the file name
without its suffix. `climpact batch` runs the same chain for every station of an R batch
metadata file (see [Batch processing](#batch-processing)).

### Station data model

`station_dataset` returns an `xarray.Dataset` with dimension `time` and variables:

| Variable | Units | Meaning |
| --- | --- | --- |
| `pr` | mm/d | daily precipitation |
| `tasmax` | degC | daily maximum temperature (TX) |
| `tasmin` | degC | daily minimum temperature (TN) |
| `tas` | degC | `(tasmax + tasmin) / 2` (TM) |

The time axis always runs from 1 January of the first year to 31 December of the last
year in the file, as climdex.pcic's `climdexInput.raw` does. Days with no data are NaN.
Station metadata (name, latitude, longitude, base period) is kept in the `StationRun` and
copied into the Dataset attributes, together with `first_date` and `last_date`, the first
and last dates in the file before padding (used for climdex's base-period data check).

The Dataset is one-dimensional in time. Batch runs do not add a `station` dimension: each
station is a separate `StationRun` in its own process, because stations have their own
time axes, coordinates and parameters. `(lat, lon)` dimensions for gridded data are
planned; the index code operates along `time` and should not need to change.

### Index parameters

`IndexParams` holds the user-set parameters with the Climpact app defaults:

| Parameter | Default | Used by |
| --- | --- | --- |
| `wsdi_days`, `csdi_days` | 1 | wsdid, csdid (outputs named `wsdi1`, `csdi1`) |
| `rx_days` | 3 | rxdday (output named `rx3day`) |
| `txtn_days` | 2 | txdtnd, txbdtnbd (outputs named `tx2tn2`, `txb2tnb2`) |
| `hdd_base`, `cdd_base`, `gdd_base` | 18, 18, 10 °C | hddheat, cddcold, gddgrow |
| `rnnmm` | 30 mm | rNNmm (output named `r30mm`) |
| `spei_months` | 24 | custom SPI/SPEI scale (not yet ported) |
| `custom` | TN > 0 | custom threshold index (output named `TNgt0`) |

Parameter values in output names are formatted as R's `paste` does (`30`, not `30.0`).

### Output products

Every output file is built by a *product*: a function registered with `@outputs.product`
that takes a `StationRun` and returns `{output key: DataFrame}`. Keys follow the R output
paths, for example `indices/fd_ANN` or `qc/nastatistics`. Products return several tables
because names can depend on parameters (`r30mm`, `rx3day`, `hddheat18`).

Table layouts follow R's `write.index.csv`:

| Kind | Columns |
| --- | --- |
| Standard index | `time`, `<index>`, `standardised values (using all years)` |
| Extreme with date | `time`, `val`, `ymd` |
| Spell with dates | `time`, `start`, `duration`, `end` |
| Thresholds (`thres/thres`) | 365 rows, one per day of year: `tmax_q5` ... `tavg_q95`, `prec_q5` ... `prec_q99`, `HW_TN90`, `HW_TX90`, `HW_TAVG90` |
| Day of year (`tx95t_DAY`) | `time` (always missing, see below), `tx95t`, standardised anomaly; 365 rows |
| Heatwave aspect (`TX90-HWM_ANN` ...) | `time`, `<aspect>` (`HWM`, `HWA`, `HWN`, `HWD` or `HWF`); no standardised column (`write.hw.csv`) |

`time` is the year (as a number) for annual tables and `"YYYY-MM"` for monthly tables.
The standardised column is `(x - mean) / sd` over all non-missing periods, using the sample
standard deviation; it is missing where the series is constant or has fewer than two values.
As in R, it is computed from the values rounded to 15 significant digits, with R's
extended-precision `mean` and `sd` (see [Numerical precision](#numerical-precision)).

### Writing output files

`climpact.io.output_files.write_outputs(tables, metadata, params, out_dir)` writes the
tables returned by `build_all` the way R does:

- **Paths:** `<out_dir>/<station>/<folder>/<station>_<name>.csv` for key `<folder>/<name>`,
  as in R's `models/outputFolders.R` (`indices/`, `qc/`, `thres/`; `trend/` when ported).
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
  `TX90 heatwave magnitude (HWM)` and so on. `qc/nastatistics` has an empty description.
- **Body:** a header row and data rows, unquoted, joined by `", "` (`write.index.csv`) or
  `","` (`write.NA.statistics`). Missing values (NaN or None) are written as `-99.9`.
  Numbers are formatted by `format_r_number`, a port of R's `formatReal`/`scientific`
  (`src/main/format.c`) with 15 significant digits.
- **All-missing indices:** an index table whose values are missing in every period is not
  written, as in `write.index.csv` (`services/write_indices.R`, line 11). `climpact run`
  lists the files it skipped. The heatwave files are the exception: `write.hw.csv`
  (line 58) writes all ten `TX90-`/`TN90-` files unless every value of all ten is missing,
  so a file that is missing in every year is still written (`_HEATWAVE_FILE`). The
  heatwave product returns no tables in the all-missing case.
- **`thres/thres`:** R writes it with a plain `write.table` in `quality_control_checks.R`,
  so it has no metadata header and writes missing values as `NA`. A `None` description in
  `_DESCRIPTIONS` means no header, and `_NA_TOKENS` holds the `NA` token.

`write_climpact_csv` (in `climpact.io.climpact_csv`) writes one file and is the inverse of
`read_climpact_csv`. An output key with no description or file format is an error, so a new
product must add its format in `output_files.py` before its files can be written.

## Batch processing

`climpact batch <metadata file> <data dir> --out <dir>` ports Climpact's batch mode
(`climpact.batch.stations.r`, `server/batch_stations.R`). Options: `--base-start`,
`--base-end` (default 1971-2000, applied to every station, as R's command-line
arguments), `--workers` (processes; R's `cores_to_use`) and `--custom VAR OP VALUE`.

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
| QC warnings go to `<station>.warnings.txt`; QC plots and text files are written | QC beyond `qc/nastatistics` is not yet ported (#9) |
| Values are read with `colClasses` `integer` for `wsdin`, `csdin`, `rxnday`, `SPEI`, and `real` for `txtn` | `txtn` must also be a whole number (it is a day count; `IndexParams.txtn_days` is an `int`) |

**Parity.** `tests/parity/test_batch.py` runs a batch of `sydney`, `nairobi` and a
malformed file through a two-process pool, and checks that every file written for each
reference station is byte-identical to the file `write_outputs` writes for its single run
(same date), with the same set of files, and that the malformed file fails with an error
file while the others succeed. The single-run files are the ones `test_csv_text` checks
against R. `tests/test_batch.py` covers the metadata format, R's sample file, the error
cases and the command line.

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

## Base-period thresholds

`climpact.thresholds` computes every base-period threshold Climpact uses, once per
station. `StationRun.thresholds` computes them on first use and caches them
(`compute_thresholds`), so all percentile indices share one computation (about 20 ms).

| Threshold | R source | Python |
| --- | --- | --- |
| TX, TN, TM q5, q10, q50, q90, q95, 5-day window | climdex.pcic `get.outofbase.quantiles` / `zhang.running.qtile`, C++ `running_quantile_windowed` | `Thresholds.temperature[var][q]` (365 values) |
| TX, TN q10, q50, q90 inside the base period (Zhang et al. 2005 bootstrap) | climdex.pcic `zhang.running.qtile(get.bootstrap.data = TRUE)`, C++ `running_quantile_windowed_bootstrap` | `Thresholds.inbase(var, q)` (365 × years × (years − 1) values) |
| TX, TN, TM q90, 15-day window (`HW_TX90`, `HW_TN90`, `HW_TAVG90`) | Climpact `quality_control_checks.R`, `get.outofbase.quantiles(n = 15)` | `Thresholds.heatwave[var]` |
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
  [In-base bootstrap](#in-base-bootstrap)).
- `climdex_quantile_sorted` is climdex's C++ quantile, vectorised over the rows of a
  sorted matrix.
- When the station's dates cover 359 days of the base period or fewer,
  `compute_thresholds` raises `InsufficientBaseData` (climdex.pcic refuses to compute
  thresholds in that case), and the threshold and percentile index products produce no
  tables.

Both quantile functions are checked bit for bit against values printed by R 4.6.1 and
climdex.pcic (`tests/data/r_quantiles.txt`, made with the `reference/r` Docker image).

## Use of xclim

xclim 1.0 is used where its result is identical to R's or within tolerance. All calls go
through `run_xclim`, which sets `check_missing="climdex"`, `as_dataset=False` (xclim 1.0
returns a `Dataset` by default), and logs rather than raises CF-compliance and
data-validation warnings.

| Uses xclim | Computed directly, and why |
| --- | --- |
| Threshold counts (`tn_days_below`, `tx_days_above`, `tg_days_*`, `wetdays`, ...) | Temperature max/min/mean (txx, tnn, tnx, txn, tmm, txm, tnm): xclim's kelvin round trip changes values (see below) |
| `wet_precip_accumulation` (prcptot) | dtr, sdii, and the means tmm/txm/tnm: R's extended-precision `mean`/`sum` is needed for the 15th digit written to the CSV files (see below) |
| `heating_degree_days`, `cooling_degree_days`, `growing_degree_days` | rx1day: computed with the other extremes so the date of occurrence comes from the same data |
| | rx3day/rx5day: xclim's window is trailing, R's is centred (see below) |
| | cdd/cwd: R's handling of spells across years and its start/end dates have no xclim equivalent |
| | gsl: xclim's `growing_season_length` ends the season on TM ≤ 5 °C when it starts on TM > 5 °C (or starts on ≥ 5 °C when it ends on < 5 °C), where R uses > 5 and < 5; it returns no dates, and its Southern Hemisphere mask differs (see [Growing season length](#growing-season-length-gsl)) |
| | r95p, r99p, r95ptot, r99ptot: one threshold per station, not per day of year, and R's extended-precision `sum` is needed for the 15th digit (see below) |
| | Custom index: R's mask choice per variable differs from xclim's (see below) |
| | tx90p, tn90p, tx10p, tn10p, txgt50p: xclim's bootstrapping (`xclim.core.bootstrapping`) recomputes `percentile_doy`, which already differs from climdex's thresholds (see below), so it cannot match R exactly; the bootstrap and R's in-base averaging are ported directly |
| | wsdi, csdi, wsdid, csdid: xclim's `warm_spell_duration_index`/`cold_spell_duration_index` would need its own thresholds (`percentile_doy`, see below) and does not reproduce R's missing-value handling (`wsdi1` missing for any year with a missing day); txdtnd, txbdtnbd have no xclim equivalent. Both are ported directly (see below) |
| | Base-period thresholds: xclim's `percentile_doy` gives different values (see below) |
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
| `lat0` | Sydney Observatory Hill 1936-2015 at latitude 0, longitude 0. Reproduces the stored reference in the original repo's `tests/output_compare` exactly | Climpact's sample file | 98/117 |
| `sydney` | The same file at its real coordinates (-33.86, 151.21) | Climpact's sample file | 98/117 |
| `minneapolis`, `phoenix`, `alice_springs`, `darwin`, `perth`, `madrid`, `potsdam` | NH and SH continental, arid, tropical and Mediterranean climates, 1961-2020 | GHCN-Daily | 98/117 each |
| `oxford`, `dublin` | Maritime; TX and TN often missing on different days | GHCN-Daily | 96/115 and 98/117 |
| `yakutsk`, `beijing` | Extreme cold; missing-data rules (months with no data) | GHCN-Daily | 98/117 each |
| `new_delhi`, `nairobi` | Patchy base periods; R writes fewer files | GHCN-Daily | 74/83 and 51/60 |

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

If building a run's outputs raises, the `station_outputs` fixture caches the error, so every
test of that run fails at once instead of rebuilding the station for each file.

### Tolerance tiers

`climpact.compare.compare_tables` compares tables column by column:

| Tier | Applies to | Pass condition |
| --- | --- | --- |
| `EXACT` | counts, extremes, event lengths, QC counts | identical values |
| `CLOSE` | means, sums, percentages, degree days, standardised anomalies | `abs(py - r) <= 1e-6 * abs(r) + 1e-9` |
| `FITTED` | SPI, SPEI | at least 99% of values within 0.01 |

In every tier the pattern of missing values must be identical, and string columns (dates)
must match exactly. Metadata header lines (including `Date_of_calculation`) are not compared.
Tiers are assigned by file name in `tests/parity/catalogue.py`; the standardised column of
an `EXACT` file uses `CLOSE`.

**These tiers are the project's acceptance criteria** (decided 2026-11-13, #31). WMO could
not be consulted, so the project set them itself. A file may be moved to a looser tier only
with an entry under "Differences between Python and R" explaining why. `FITTED` is reserved
for fitted distributions.

### Running

```sh
.venv/bin/pytest                 # everything
.venv/bin/pytest tests/parity    # parity only
```

Files that no product builds are reported as `xfail` ("not yet ported"). A summary is
printed at the end:

```
=================================== R parity ===================================
alice_springs: 98/117 reference files reproduced, 0 failing, 19 not yet ported
beijing: 98/117 reference files reproduced, 0 failing, 19 not yet ported
darwin: 98/117 reference files reproduced, 0 failing, 19 not yet ported
dublin: 98/117 reference files reproduced, 0 failing, 19 not yet ported
lat0: 98/117 reference files reproduced, 0 failing, 19 not yet ported
madrid: 98/117 reference files reproduced, 0 failing, 19 not yet ported
minneapolis: 98/117 reference files reproduced, 0 failing, 19 not yet ported
nairobi: 51/60 reference files reproduced, 0 failing, 9 not yet ported
new_delhi: 74/83 reference files reproduced, 0 failing, 9 not yet ported
oxford: 96/115 reference files reproduced, 0 failing, 19 not yet ported
perth: 98/117 reference files reproduced, 0 failing, 19 not yet ported
phoenix: 98/117 reference files reproduced, 0 failing, 19 not yet ported
potsdam: 98/117 reference files reproduced, 0 failing, 19 not yet ported
sydney: 98/117 reference files reproduced, 0 failing, 19 not yet ported
yakutsk: 98/117 reference files reproduced, 0 failing, 19 not yet ported
alice_springs: 98/117 written CSV files text-identical to R, 0 differing
beijing: 98/117 written CSV files text-identical to R, 0 differing
darwin: 98/117 written CSV files text-identical to R, 0 differing
dublin: 98/117 written CSV files text-identical to R, 0 differing
lat0: 98/117 written CSV files text-identical to R, 0 differing
madrid: 98/117 written CSV files text-identical to R, 0 differing
minneapolis: 98/117 written CSV files text-identical to R, 0 differing
nairobi: 51/60 written CSV files text-identical to R, 0 differing
new_delhi: 74/83 written CSV files text-identical to R, 0 differing
oxford: 96/115 written CSV files text-identical to R, 0 differing
perth: 98/117 written CSV files text-identical to R, 0 differing
phoenix: 98/117 written CSV files text-identical to R, 0 differing
potsdam: 98/117 written CSV files text-identical to R, 0 differing
sydney: 98/117 written CSV files text-identical to R, 0 differing
yakutsk: 98/117 written CSV files text-identical to R, 0 differing
```

The "reference files reproduced" lines come from `tests/parity/test_parity.py`, which
compares tables with the tolerance tiers. The "text-identical" lines come from
`tests/parity/test_csv_text.py`, which writes every built table with `write_outputs` and
requires the file to equal R's line for line, ignoring only the `Date_of_calculation` line.
It also checks that no file is written that R does not write: on `oxford`, `new_delhi` and
`nairobi` this exercises the rule that all-missing index tables are skipped, and on
`new_delhi` the exception for heatwave files.

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
   matching the R file name.
3. Run `pytest tests/parity -k <name>`. Fix mismatches, or, if the difference comes from
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
  (`period_stat`) and the standardised column (`standardise`); sdii and the r95p, r99p,
  r95ptot and r99ptot totals use `r_sum`. All written files are then text-identical to
  R's. With numpy sums, 34 of the 3,752 r95p/r99p/r95ptot/r99ptot values of the 15 runs
  would be written with a different last digit.
- The emulation is only used where it changes a result. It should be considered for
  other index calculations if new tie-related or last-digit mismatches appear.

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
  `tests/test_climpact_csv.py`; the reference files have this case in `r10mm_ANN`.

**xclim converts temperatures to kelvin internally.** Indicators such as `tx_max` and
`tg_mean` return kelvin, and converting °C → K → °C changes the last bits of about 84% of
values.

- *Handling:* temperature maxima, minima and means are computed directly (`period_stat`):
  maxima and minima with xarray, means with `r_mean`, the same arithmetic as R's `tapply`
  with `mean`. Results are identical to R.
- Threshold counts are unaffected: xclim converts the threshold into the data's units, so
  comparisons are made on the original values.

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

- *Handling:* dtr is computed with xclim (which applies the climdex rule to TX and TN
  separately) and then masked with `valid_mask(ds.tas)`, the TM mask. Any period valid under
  the TM mask is also valid for TX and TN, so the result has exactly R's mask. Sydney's gaps
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
flags, and `hw_aspects` / `season_aspects` turn flags into the five annual aspects. The EHF
and ECF heatwaves (#21) go through the same `get.hw.aspects`, so `hw_aspects` takes any daily
flags (1/0/NaN) and values.

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
inside a heatwave (possible for EHF). `tests/test_heatwaves.py` checks the reproduced
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

### Station input

| R behaviour | Python |
| --- | --- |
| Commas are treated as separators; a header row is skipped when the first field is not an integer | same |
| Values equal to `-99.9` are missing | same |
| Rows with an invalid date (e.g. 29 February in a non-leap year) are dropped | same |
| If a date appears more than once, the last row wins (`create.filled.series`) | same. R's QC step also reports duplicates; QC is not yet ported |
| The time axis is padded to whole years; padded days count as missing | same |
| `northern.hemisphere = latitude > 0`, so latitude 0 is treated as Southern Hemisphere | same (`StationMetadata.northern_hemisphere`); matters for gsl and heatwaves |
| Years out of order are rejected by the QC step | not yet checked |

### Output files

| R behaviour | Python |
| --- | --- |
| Values are written with 15 significant digits and `-99.9` for missing | same, including R's digit-count quirk (`format_r_number`); tables in memory hold full-precision floats |
| No file is written when an index is missing for every period (`write.index.csv`; heatwave files differ, below) | same (`write_outputs`); `build_all` still returns the all-missing table. Exercised by `oxford`, `new_delhi` and `nairobi` |
| A 7-line metadata header (version, date of calculation, ...) | same; `Climpact_version` is `3.4.3`. Ignored by the table comparison; only `Date_of_calculation` is ignored by the text comparison |
| `tx95t_DAY`: `write.index.csv` writes the row names of an unnamed vector as `time`, so every `time` is `-99.9` | reproduced: `time` is missing on every row |
| `thres.csv` is written by a plain `write.table`: no metadata header, missing values as `NA` (not `-99.9`), and each precipitation threshold repeated on all 365 rows (`as.data.frame` recycling) | reproduced; `write_outputs` writes it with no header and `NA` (`_DESCRIPTIONS`/`_NA_TOKENS` in `io/output_files.py`) |
| `write.hw.csv` writes the ten Tx90/Tn90 heatwave files with `time, <aspect>` columns (no standardised column) and writes them even when one is missing in every year | reproduced (`_HEATWAVE_FILE` in `io/output_files.py`). Exercised by `new_delhi` |
| `index.calc` writes a plot PDF and a zip archive alongside the CSV files | not yet written |

### R behaviour not to be copied

These are known R bugs or limitations, found while reviewing the R code. They are not
reproduced; where they affect an output, the difference will be documented when that
output is ported.

- QC `humongous` and `tmaxmin` test `length(data.frame) == 0`, which counts columns, so the
  "none found" message is never written.
- QC `flatline_tn` labels its report "TX".
- QC checks re-read the data from a temporary file with `-99.9` sentinels rather than using
  the cleaned data.
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

## Performance

A full station run (80 years, all ported indices) takes about 12 seconds to build (9 s for
a 60-year GHCN station), plus about 0.5 seconds to write the CSV files. The whole test suite
with 15 runs, including the text comparison and the batch test, takes about 190 seconds.
A batch runs one station per process: Climpact's two sample stations (80 years each) take
about 19 seconds with `--workers 2`, against about 12 seconds for one station alone (each
spawned worker also imports xclim). The extra runs are not
marked `slow`; #23 tracks speed-ups. Most of the time is per-call
overhead in xclim (metadata, unit checks) and recomputing the missing-data mask for each
call. Caching masks per variable and frequency, or calling xclim's compute functions
directly, are the obvious improvements. The R-precision emulation takes about 30 ms per
80-year series for a sum, and about 0.2 s for a series of monthly means.

The temperature percentile indices (tx90p, tn90p, tx10p, tn10p, txgt50p, ANN and MON)
take 1.5-2.2 s per station (Apple M-series, measured on all 15 runs):

| Run | Bootstrap (5 variable/quantile pairs) | Indices | Total |
| --- | --- | --- | --- |
| `lat0`, `sydney` (80 years) | 0.8 s | 1.3 s | 2.1-2.2 s |
| other GHCN runs (60 years) | 0.7-0.8 s | 1.0 s | 1.7-1.9 s |
| `new_delhi`, `nairobi` (patchy) | 0.7 s | 0.9 s | 1.5-1.6 s |

The spell-duration indices (6 files) take about 0.2-0.25 s per station, and gsl about
0.03-0.1 s.

The bootstrap loops over the 365 days and handles all 870 (rm, dup) year pairs of a day
at once with numpy, so it takes about 0.16 s per variable and quantile, against 317,550
quantiles. Most of the rest is the per-period R-precision mean (`r_mean`) and the
missing-data masks.

## Development

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest
```

- Run a station from the command line with
  `.venv/bin/climpact run <station file> --out <dir> [--lat ... --lon ...]`
  (`climpact run --help` lists the options), or a batch with
  `.venv/bin/climpact batch <metadata file> <data dir> --out <dir> [--workers N]`.
- Python 3.11+, xclim 1.0.x. CI runs on Python 3.11, 3.12 and 3.13 (x86_64 Linux).
- Always work inside `.venv`.
- To regenerate the R reference outputs, see `reference/README.md`. Re-running changes the
  `Date_of_calculation` line in every CSV, so only commit a re-run when the numbers are
  meant to change.
- Work is tracked as GitHub issues on the
  [climpactpy Kanban](https://github.com/users/geoffwalmsley/projects/2), grouped under
  epics (#8 station parity, #9 QC, #10 gridded, #11 web, #12 deployment). Branches are
  named `<issue>-<slug>` and PRs say `Closes #N`. Each ticket names the reference files it
  should make pass. The full workflow is in `.claude/skills/ticket/SKILL.md`.
