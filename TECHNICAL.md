# climpactpy technical notes

Technical documentation for the Python port of [Climpact](https://github.com/ARCCSS-extremes/climpact).
It covers how the code is organised, how results are checked against the R version, and
every known difference between the Python and R implementations and how each is handled.

Reference version: **Climpact R v3.4.3** (commit `5ee0cfe`), with climdex.pcic 1.2-0.

## Status

The Python port reproduces **65 of the 117** R reference files for each reference run, with
none failing:

| Area | Ported | Not yet ported |
| --- | --- | --- |
| Threshold counts | fd, tnlt2, tnltm2, tnltm20, id, su, tr, txge30, txge35, tmge5, tmge10, tmlt5, tmlt10, r10mm, r20mm, rNNmm, custom index | |
| Means and totals | dtr, tmm, txm, tnm, prcptot, sdii | |
| Extremes (with dates) | txx, tnn, tnx, txn, rx1day, rx3day (rxdday), rx5day | |
| Spells (with dates) | cdd, cwd | gsl |
| Degree days | hddheat, cddcold, gddgrow | |
| Percentile indices | | tx90p, tx10p, tn90p, tn10p, txgt50p, tx95t, wsdi, csdi, wsdid, csdid, txdtnd, txbdtnbd, r95p, r99p, r95ptot, r99ptot |
| Heatwaves | | Tx90/Tn90 (5 aspects each), EHF (8 aspects, daily EHF/ECF) |
| Drought | | SPI, SPEI (3, 6, 12 months and custom) |
| Other outputs | qc/nastatistics | thresholds file, trend file, other QC outputs, plots |

Progress is printed at the end of every test run (see [Parity testing](#parity-testing)).

The Python port computes output **tables in memory**; it does not yet write Climpact-format
CSV files, plots or zip archives.

## Repository layout

```
src/climpact/
  config.py          StationMetadata, IndexParams, CustomIndex (Climpact app defaults)
  station.py         StationRun and load_station()
  io/
    station.py       read Climpact/RClimDex station text files; build the xarray Dataset
    climpact_csv.py  read Climpact (R) output CSV files
  missing.py         climdex.pcic missing-data rules; registered with xclim as "climdex"
  outputs.py         registry of products that build Climpact-format output tables
  products/
    tables.py        shape results into Climpact's table layouts; standardised anomalies
    indices.py       index products
    qc.py            QC products
  compare.py         tiered comparison of tables against the R reference
  rnumerics.py       exact emulation of R's extended-precision sum/cumsum
tests/
  parity/            one test per R reference file, plus progress reporting
  test_*.py          unit tests
reference/
  input/             station input data used by the tests
  output/            R reference outputs (CSV only; plots are gitignored)
  r/, run_r_reference.sh   Docker setup that produces reference/output (see reference/README.md)
```

## Data flow

```
station text file
  -> io.station.read_station_file   DataFrame(date, prcp, tmax, tmin), invalid dates dropped
  -> io.station.station_dataset     xarray Dataset on a full-year daily axis
  -> StationRun(data, metadata, params)
  -> outputs.build_all(run)         {"indices/fd_ANN": DataFrame, ...}
```

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
copied into the Dataset attributes.

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

`time` is the year (as a number) for annual tables and `"YYYY-MM"` for monthly tables.
The standardised column is `(x - mean) / sd` over all non-missing periods, using the sample
standard deviation; it is missing where the series is constant or has fewer than two values.

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

## Use of xclim

xclim 1.0 is used where its result is identical to R's or within tolerance. All calls go
through `run_xclim`, which sets `check_missing="climdex"`, `as_dataset=False` (xclim 1.0
returns a `Dataset` by default), and logs rather than raises CF-compliance and
data-validation warnings.

| Uses xclim | Computed directly, and why |
| --- | --- |
| Threshold counts (`tn_days_below`, `tx_days_above`, `tg_days_*`, `wetdays`, ...) | Temperature max/min/mean (txx, tnn, tnx, txn, tmm, txm, tnm): xclim's kelvin round trip changes values (see below) |
| `daily_temperature_range`, `wet_precip_accumulation`, `daily_pr_intensity` | rx1day: computed with the other extremes so the date of occurrence comes from the same data |
| `heating_degree_days`, `cooling_degree_days`, `growing_degree_days` | rx3day/rx5day: xclim's window is trailing, R's is centred (see below) |
| | cdd/cwd: R's handling of spells across years and its start/end dates have no xclim equivalent |
| | Custom index: R's mask choice per variable differs from xclim's (see below) |

## Parity testing

### Reference outputs

`reference/output/` holds the R outputs of Climpact v3.4.3 for the Sydney Observatory Hill
station (1936-2015), produced by the Docker setup in `reference/` (see `reference/README.md`):

| Run | Settings |
| --- | --- |
| `lat0` | Climpact app defaults: latitude 0, longitude 0, base period 1971-2000. Reproduces the stored reference in the original repo's `tests/output_compare` exactly |
| `sydney` | As `lat0` but at the station's real coordinates (-33.86, 151.21) |

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
lat0: 65/117 reference files reproduced, 0 failing, 52 not yet ported
sydney: 65/117 reference files reproduced, 0 failing, 52 not yet ported
```

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
  tier and need no special handling.
- *Exception, Rx3day/Rx5day dates:* when two windows have the same true precipitation
  total, R's rounding noise decides which window's date is reported (3 of 1,920 monthly
  dates differed with plain numpy). `climpact.rnumerics` emulates R's extended-precision
  `sum` and `cumsum` exactly using integer arithmetic, so ties resolve as in R on every
  platform. numpy's `longdouble` is not used because it is only 80-bit on x86 (on Apple
  Silicon it is a plain double). `tests/test_rnumerics.py` checks the emulation against
  native x87 `longdouble` on the x86 CI runners.
- The emulation is only used where it changes a result (the Rx running sums). It should be
  considered for other index calculations if new tie-related mismatches appear.

**xclim converts temperatures to kelvin internally.** Indicators such as `tx_max` and
`tg_mean` return kelvin, and converting °C → K → °C changes the last bits of about 84% of
values.

- *Handling:* temperature maxima, minima and means are computed directly with xarray
  (`period_stat`), which is the same arithmetic as R's `tapply`. Results are identical to R.
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

**Custom index masks.** In R's `calculate.custom.index`, TM uses only the TN missing mask
(not TX), and DTR uses both TX and TN masks.

- *Handling:* replicated. A TM custom index can therefore have a value in a month where TX
  has more than 3 missing days; this matches R.

**tmm mask.** R masks tmm with the TN and TX masks (not a TM mask); dtr uses the TM mask.
Both are equivalent to "missing if either TX or TN is missing", which is what Python does.

**SU threshold.** Climpact's code counts TX **>** 25 °C, although a code comment says
`>=`. Python follows the code.

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
| Values are written with 15 significant digits and `-99.9` for missing | tables hold full-precision floats; comparisons parse R's text, so the 15-digit rounding is covered by the `CLOSE` tier (and is exact for `EXACT` values) |
| No file is written when an index is missing for every period | not yet handled: Python returns an all-missing table |
| A 7-line metadata header (version, date of calculation, ...) | not yet written; ignored when comparing |

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

A full station run (80 years, all ported indices) takes about 9 seconds, mostly per-call
overhead in xclim (metadata, unit checks) and recomputing the missing-data mask for each
call. Caching masks per variable and frequency, or calling xclim's compute functions
directly, are the obvious improvements. The R-precision emulation takes about 30 ms per
80-year series.

## Development

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest
```

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
