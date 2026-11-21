title: Command line
summary: The climpact command calculates the same indices as this site, from a terminal or a script: one station, a batch, or a netCDF grid. Its results are the files of Climpact for R.

<p class="help-note">The options below are read from the command itself, climpact [[cli-version]]. <code>climpact &lt;command&gt; --help</code> prints them too.</p>

## Install {#install}

Climpact needs Python 3.12 or later. Install it with pip, in a virtual environment of its
own if you like:

```
$ pip install 'climpact[plots]'   # [plots] adds matplotlib, for the plots and the PDF report
$ climpact --version
```

## Commands {#commands}

[[cli-commands]]

## `climpact run` {#run}

Calculates the indices of one station and writes them as Climpact CSV files to
`OUT/NAME/`: `indices/`, `qc/`, `thres/` and `trend/`, in the layout of Climpact for R. The
defaults are those of this site.

`station_file` is a [station file](guide:format-station-file): year, month, day, PR, TX,
TN.

[[cli-command:run]]

### Example {#run-example}

```
$ climpact run sydney.txt --out results --lat -33.86 --lon 151.21 --base-start 1961 --base-end 1990 --plots
$ ls results/sydney
indices  plots  qc  thres  trend
```

## `climpact batch` {#batch}

Runs every station of a [batch metadata file](guide:format-batch-metadata), as
`climpact run` does, several at once. The index settings of each station come from the
metadata file. A station that fails is reported in `OUT/NAME.errors.txt` and the batch
carries on.

[[cli-command:batch]]

### Example {#batch-example}

```
$ climpact batch stations.txt data/ --out results --workers 4
```

## `climpact gridded-thresholds` {#gridded-thresholds}

Calculates the base-period percentile thresholds of every cell of a grid of daily TX, TN
and precipitation, and writes them to one netCDF file. Use it to calculate the percentile
indices of data with no day in the base period, such as a projection: see
[thresholds from another period](guide:gridded#thresholds-from-another-period). The input
files are described in [Gridded input files](guide:format-gridded-inputs).

[[cli-command:gridded-thresholds]]

### Example {#gridded-thresholds-example}

```
$ climpact gridded-thresholds 'historical/tasmax_*.nc' 'historical/tasmin_*.nc' 'historical/pr_*.nc' --out thresholds.nc --base-start 1981 --base-end 2010
```

## `climpact gridded-indices` {#gridded-indices}

Calculates the indices of every cell of a grid of daily TX, TN and precipitation, and
writes one netCDF file per index and frequency, in the layout of Climpact for R's netCDF
wrapper. With `--trends` it also writes `trends.nc`, the trend of every cell.

[[cli-command:gridded-indices]]

### Example {#gridded-indices-example}

```
$ climpact gridded-indices climpact.sampledata.gridded.1991-2010.nc --out grid --base-start 1991 --base-end 2010 --workers 4
$ ls grid
cdd_ANN_climpact_historical_NA_1991-2010.nc  csdi_ANN_climpact_historical_NA_1991-2010.nc  …
```

## `climpact sector-correlation` {#sector-correlation}

Correlates yearly sector data, such as crop yields, with the yearly temperatures and
indices of a station already calculated with `climpact run`, and writes the correlation
files of Climpact for R to `OUT/NAME/corr/`. The sector file is described in
[Sector data file](guide:format-sector-data).

[[cli-command:sector-correlation]]

### Example {#sector-correlation-example}

```
$ climpact run sydney.txt --out results
$ climpact sector-correlation sydney.txt wheat_yield_nsw_1922-1999.csv --out results --plots
```

## `climpact modules` {#modules}

Lists the quality-control, homogeneity and index modules installed, built in or added by
a plugin, with the options each takes.

[[cli-command:modules]]

## Plugins {#plugins}

A Python package can add modules to Climpact through three entry points: `climpact.qc`
(quality checks), `climpact.homogeneity` (a homogeneity test whose adjusted data are used
for the indices) and `climpact.indices` (more indices). Once the package is installed,
`climpact modules` lists them, and `--qc`, `--homogeneity` and `--indices` select them for
`climpact run` and `climpact batch`. `--module-option` and `--module-options` set their
options.

```
$ climpact modules
$ climpact run sydney.txt --out results --qc climpact,my_checks --module-option my_checks.limit=45
```
