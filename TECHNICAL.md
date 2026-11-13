# climpactpy technical notes

Technical documentation for the Python port of [Climpact](https://github.com/ARCCSS-extremes/climpact).
It covers how the code is organised, how results are checked against the R version, and
every known difference between the Python and R implementations and how each is handled.

Reference version: **Climpact R v3.4.3** (commit `5ee0cfe`), with climdex.pcic 1.2-0.

## Status

The Python port reproduces **71 of the 117** R reference files for Sydney (`lat0` and
`sydney`), and every ported file R wrote for all 13 GHCN stations, with none failing (see
[Reference outputs](#reference-outputs)). Every ported file is also written text-identical
to R's on all 15 runs, apart from the `Date_of_calculation` line:

| Area | Ported | Not yet ported |
| --- | --- | --- |
| Threshold counts | fd, tnlt2, tnltm2, tnltm20, id, su, tr, txge30, txge35, tmge5, tmge10, tmlt5, tmlt10, r10mm, r20mm, rNNmm, custom index | |
| Means and totals | dtr, tmm, txm, tnm, prcptot, sdii | |
| Extremes (with dates) | txx, tnn, tnx, txn, rx1day, rx3day (rxdday), rx5day | |
| Spells (with dates) | cdd, cwd | gsl |
| Degree days | hddheat, cddcold, gddgrow | |
| Percentile indices | tx95t, r95p, r99p, r95ptot, r99ptot | tx90p, tx10p, tn90p, tn10p, txgt50p, wsdi, csdi, wsdid, csdid, txdtnd, txbdtnbd |
| Heatwaves | | Tx90/Tn90 (5 aspects each), EHF (8 aspects, daily EHF/ECF) |
| Drought | | SPI, SPEI (3, 6, 12 months and custom) |
| Other outputs | qc/nastatistics, thresholds file (`thres/thres`), CSV files for all ported outputs | trend file, other QC outputs, plots, zip archive |

Progress is printed at the end of every test run (see [Parity testing](#parity-testing)).

The Python port writes every ported output as a Climpact-format CSV file, text-identical
to R's apart from the `Date_of_calculation` line (see [Writing output files](#writing-output-files)).
It does not yet write plots or zip archives.

## Repository layout

```
src/climpact/
  cli.py             command line: `climpact run <station file> --out <dir>`
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
    thresholds.py    thresholds file and tx95t products
    qc.py            QC products
  compare.py         tiered comparison of tables against the R reference
  rnumerics.py       exact emulation of R's extended-precision sum, cumsum, mean and var
tests/
  parity/            one test per R reference file, plus progress reporting
  test_*.py          unit tests
  data/              unit-test fixtures (quantiles printed by R)
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

`climpact run` (`climpact.cli`) runs the whole chain for one station file. Station
settings and every `IndexParams` value are options; defaults are the Climpact app
defaults, and the station name defaults to the file name without its suffix.

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

The Dataset is currently one-dimensional in time. A `station` dimension for batch runs and
`(lat, lon)` dimensions for gridded data are planned; the index code operates along `time`
and should not need to change.

### Index parameters

`IndexParams` holds the user-set parameters with the Climpact app defaults:

| Parameter | Default | Used by |
| --- | --- | --- |
| `wsdi_days`, `csdi_days` | 1 | wsdid, csdid (not yet ported) |
| `rx_days` | 3 | rxdday (output named `rx3day`) |
| `txtn_days` | 2 | txdtnd, txbdtnbd (not yet ported) |
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
  `calculate.custom.index`. `qc/nastatistics` has an empty description.
- **Body:** a header row and data rows, unquoted, joined by `", "` (`write.index.csv`) or
  `","` (`write.NA.statistics`). Missing values (NaN or None) are written as `-99.9`.
  Numbers are formatted by `format_r_number`, a port of R's `formatReal`/`scientific`
  (`src/main/format.c`) with 15 significant digits.
- **All-missing indices:** an index table whose values are missing in every period is not
  written, as in `write.index.csv` (`services/write_indices.R`, line 11). `climpact run`
  lists the files it skipped.
- **`thres/thres`:** R writes it with a plain `write.table` in `quality_control_checks.R`,
  so it has no metadata header and writes missing values as `NA`. A `None` description in
  `_DESCRIPTIONS` means no header, and `_NA_TOKENS` holds the `NA` token.

`write_climpact_csv` (in `climpact.io.climpact_csv`) writes one file and is the inverse of
`read_climpact_csv`. An output key with no description or file format is an error, so a new
product must add its format in `output_files.py` before its files can be written.

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
| TX, TN, TM q90, 15-day window (`HW_TX90`, `HW_TN90`, `HW_TAVG90`) | Climpact `quality_control_checks.R`, `get.outofbase.quantiles(n = 15)` | `Thresholds.heatwave[var]` |
| Wet-day (≥ 1 mm) precipitation q5, q10, q50, q90, q95, q99 | climdex.pcic `get.prec.var.quantiles`, R `quantile(type = 8)` | `Thresholds.precipitation[q]` (a number) |

`var` is `tasmax`, `tasmin` or `tas`. For index code:

- `Thresholds.daily(var, q, time)` gives the threshold for each date of a series, using
  climdex's day-of-year mapping (`day_of_year`: 29 February takes 28 February's
  threshold, later days of a leap year shift back by one).
- `Thresholds.base[var]` is the `(years, 365)` base-period matrix the temperature
  thresholds came from, and `window_values` returns the `(365, years, window)` window
  values. These are the inputs to the in-base bootstrap.
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
| | r95p, r99p, r95ptot, r99ptot: one threshold per station, not per day of year, and R's extended-precision `sum` is needed for the 15th digit (see below) |
| | Custom index: R's mask choice per variable differs from xclim's (see below) |
| | Base-period thresholds: xclim's `percentile_doy` gives different values (see below) |

## Parity testing

### Reference outputs

`reference/output/<run>/<station>/` holds the R outputs of Climpact v3.4.3, produced by the
Docker setup in `reference/` (see `reference/README.md`). Each row of `reference/stations.csv`
is one run. `tests/parity/catalogue.py` reads it to build `RUNS`, so adding a row (with its input
file and R outputs) adds a run to the parity suite. Every run uses the Climpact app defaults
(base period 1971-2000) at the coordinates in `stations.csv`.

| Run | Station | Input | Parity (of R files) |
| --- | --- | --- | --- |
| `lat0` | Sydney Observatory Hill 1936-2015 at latitude 0, longitude 0. Reproduces the stored reference in the original repo's `tests/output_compare` exactly | Climpact's sample file | 71/117 |
| `sydney` | The same file at its real coordinates (-33.86, 151.21) | Climpact's sample file | 71/117 |
| `minneapolis`, `phoenix`, `alice_springs`, `darwin`, `perth`, `madrid`, `potsdam` | NH and SH continental, arid, tropical and Mediterranean climates, 1961-2020 | GHCN-Daily | 71/117 each |
| `oxford`, `dublin` | Maritime; TX and TN often missing on different days | GHCN-Daily | 71/115 and 71/117 |
| `yakutsk`, `beijing` | Extreme cold; missing-data rules (months with no data) | GHCN-Daily | 71/117 each |
| `new_delhi`, `nairobi` | Patchy base periods; R writes fewer files | GHCN-Daily | 53/83 and 46/60 |

GHCN inputs are converted by `reference/fetch_ghcn.py`: values divided by 10, `-99.9` for
missing, and values with a GHCN QC flag set to missing. Sydney keeps Climpact's own sample
file. A GHCN conversion of the same station (ASN00066062) has every shared value identical,
but GHCN has 89 more temperature days and QC-flags 96 values Climpact's file keeps, so it
would not reproduce the stored reference (details in `reference/README.md`).

Climpact writes no CSV for an index that is missing in every period, so stations with patchy
data have fewer reference files (`oxford` 112 index files, `new_delhi` 80, `nairobi` 57,
against 114). The catalogue lists only the files R wrote.

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
alice_springs: 71/117 reference files reproduced, 0 failing, 50 not yet ported
beijing: 71/117 reference files reproduced, 0 failing, 50 not yet ported
darwin: 71/117 reference files reproduced, 0 failing, 50 not yet ported
dublin: 71/117 reference files reproduced, 0 failing, 50 not yet ported
lat0: 71/117 reference files reproduced, 0 failing, 50 not yet ported
madrid: 71/117 reference files reproduced, 0 failing, 50 not yet ported
minneapolis: 71/117 reference files reproduced, 0 failing, 50 not yet ported
nairobi: 46/60 reference files reproduced, 0 failing, 14 not yet ported
new_delhi: 53/83 reference files reproduced, 0 failing, 30 not yet ported
oxford: 71/115 reference files reproduced, 0 failing, 44 not yet ported
perth: 71/117 reference files reproduced, 0 failing, 50 not yet ported
phoenix: 71/117 reference files reproduced, 0 failing, 50 not yet ported
potsdam: 71/117 reference files reproduced, 0 failing, 50 not yet ported
sydney: 71/117 reference files reproduced, 0 failing, 50 not yet ported
yakutsk: 71/117 reference files reproduced, 0 failing, 50 not yet ported
alice_springs: 71/117 written CSV files text-identical to R, 0 differing
beijing: 71/117 written CSV files text-identical to R, 0 differing
darwin: 71/117 written CSV files text-identical to R, 0 differing
dublin: 71/117 written CSV files text-identical to R, 0 differing
lat0: 71/117 written CSV files text-identical to R, 0 differing
madrid: 71/117 written CSV files text-identical to R, 0 differing
minneapolis: 71/117 written CSV files text-identical to R, 0 differing
nairobi: 46/60 written CSV files text-identical to R, 0 differing
new_delhi: 53/83 written CSV files text-identical to R, 0 differing
oxford: 71/115 written CSV files text-identical to R, 0 differing
perth: 71/117 written CSV files text-identical to R, 0 differing
phoenix: 71/117 written CSV files text-identical to R, 0 differing
potsdam: 71/117 written CSV files text-identical to R, 0 differing
sydney: 71/117 written CSV files text-identical to R, 0 differing
yakutsk: 71/117 written CSV files text-identical to R, 0 differing
```

The "reference files reproduced" lines come from `tests/parity/test_parity.py`, which
compares tables with the tolerance tiers. The "text-identical" lines come from
`tests/parity/test_csv_text.py`, which writes every built table with `write_outputs` and
requires the file to equal R's line for line, ignoring only the `Date_of_calculation` line.
It also checks that no file is written that R does not write: on `oxford`, `new_delhi` and
`nairobi` this exercises the rule that all-missing index tables are skipped.

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
  (0.1 °C resolution) and thresholds. Expect to need the same care as the Rx ties when
  porting them.

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
tables and none of the percentile indices (tx95t, r95p, r99p, r95ptot, r99ptot).

**Result.** `thres/thres` and `indices/tx95t_DAY` pass at `CLOSE` for both runs. Every
threshold value is identical to R's file after formatting to the 15 significant digits R
writes; `EXACT` cannot be used because the file holds rounded values. The tx95t
standardised column differs by up to 1.4e-13 relative (mean and standard deviation
arithmetic).

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
| No file is written when an index is missing for every period | same (`write_outputs`); `build_all` still returns the all-missing table. Exercised by `oxford`, `new_delhi` and `nairobi` |
| A 7-line metadata header (version, date of calculation, ...) | same; `Climpact_version` is `3.4.3`. Ignored by the table comparison; only `Date_of_calculation` is ignored by the text comparison |
| `tx95t_DAY`: `write.index.csv` writes the row names of an unnamed vector as `time`, so every `time` is `-99.9` | reproduced: `time` is missing on every row |
| `thres.csv` is written by a plain `write.table`: no metadata header, missing values as `NA` (not `-99.9`), and each precipitation threshold repeated on all 365 rows (`as.data.frame` recycling) | reproduced; `write_outputs` writes it with no header and `NA` (`_DESCRIPTIONS`/`_NA_TOKENS` in `io/output_files.py`) |
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

## Performance

A full station run (80 years, all ported indices) takes about 10 seconds to build (7 s for
a 60-year GHCN station), plus about 0.5 seconds to write the CSV files. The whole test suite
with 15 runs, including the text comparison, takes about 130 seconds. The extra runs are not
marked `slow`; #23 tracks speed-ups. Most of the time is per-call
overhead in xclim (metadata, unit checks) and recomputing the missing-data mask for each
call. Caching masks per variable and frequency, or calling xclim's compute functions
directly, are the obvious improvements. The R-precision emulation takes about 30 ms per
80-year series for a sum, and about 0.2 s for a series of monthly means.

## Development

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest
```

- Run a station from the command line with
  `.venv/bin/climpact run <station file> --out <dir> [--lat ... --lon ...]`
  (`climpact run --help` lists the options).
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
