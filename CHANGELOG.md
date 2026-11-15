# Changelog

All notable changes to `climpact` and `climpact-web`, which are released together with one
version number ([RELEASING.md](RELEASING.md)). Versions follow
[Semantic Versioning](https://semver.org/); the format follows
[Keep a Changelog](https://keepachangelog.com/).

## Unreleased

## 0.1.0 - 2026-11-15

The first release on PyPI. The same code as 0.1.0rc1, which was published to TestPyPI
and checked; see that entry for what it contains.

## 0.1.0rc1 - 2026-11-15

The first release: the Python port of Climpact 3.4.3 and its web app.

- `climpact`: the Climpact indices of daily climate extremes for stations (single and
  batch runs), quality control, thresholds, trends, sector correlation and gridded
  (netCDF) data, written as Climpact's output files, with plots and a PDF report (the
  `plots` extra). Checked against R Climpact reference runs (see TECHNICAL.md for the
  parity status and the differences from R).
- `climpact-web`: the browser app for station, batch and gridded runs, on your own
  computer (`climpact-web`) or hosted (the `ghcr.io/geoffwalmsley/climpact-web` image).
- The core's distribution is named `climpact` (it was `climpactpy` during development,
  never published) and outputs credit "Climpact for Python X.Y.Z (port of Climpact
  3.4.3)". The gridded default file name template is now
  `var_daily_climpact_historical_NA_<first year>-<last year>.nc`.
