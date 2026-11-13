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
- Runs as `linux/amd64` (emulated on Apple Silicon). On native arm64, climdex.pcic's bootstrapped
  in-base percentiles round differently and tx10p, tn10p, tx90p and csdi change in some base-period
  years. Use `PLATFORM=linux/arm64` to run natively anyway.
