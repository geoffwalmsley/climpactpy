# R reference

Runs the original Climpact v3.4.3 (R) in Docker, so no local R install is needed.

```sh
./reference/run_r_reference.sh          # build image, run both reference sets
./reference/run_r_reference.sh lat0     # stored-reference settings + Climpact's own CSV test
./reference/run_r_reference.sh sydney   # Sydney's real coordinates (-33.86, 151.21)
```

Expects the original repo at `../climpact` (override with `CLIMPACT_DIR`). It is mounted read-only.

Outputs go to `reference/output/<run>/sydney_observatory_hill_1936-2015/` (indices, thres, trend,
qc, plots), plus `r-package-versions.csv`, `climpact-commit.txt` and, for `lat0`,
`comparison_summary.csv`.

The CSV outputs are committed so tests can use them without Docker; plots (PNG/PDF) are gitignored.
Re-running changes the `Date_of_calculation` header line in every CSV, so only commit a re-run when the
numbers are meant to change.

| Run | Settings | Purpose |
| --- | --- | --- |
| `lat0` | Shiny UI defaults: lat 0, lon 0, base 1971-2000, WSDI/CSDI d=1, Rx3day, TX2TN2, R30mm, SPEI 24, custom TN > 0 | Reproduces `climpact/tests/output_compare` and runs its `test_output.R` |
| `sydney` | As above but lat -33.86, lon 151.21 | Second reference; only SPEI (Hargreaves PET uses latitude) differs |

## Pinned environment

- `rocker/r-ver:4.6.1`, CRAN from the Posit snapshot of 2026-09-18
- PCICt 0.5-4.4 from the CRAN archive; climdex.pcic 1.2-0 from GitHub commit `011cb78`
- Runs as `linux/amd64` (emulated on Apple Silicon). On native arm64, climdex.pcic's bootstrapped
  in-base percentiles round differently and tx10p, tn10p, tx90p and csdi change in some base-period
  years. Use `PLATFORM=linux/arm64` to run natively anyway.
