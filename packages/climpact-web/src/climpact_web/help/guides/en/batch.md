title: Batch processing
summary: Calculating the indices for many stations in one run: the metadata file, the station files, the options and the results.

## When to use a batch

Use a batch when you have more than a few stations. You give one **metadata file** that
lists the stations and their settings, and their station files; Climpact checks every
station, then calculates them all in the background. Each station gets the same results
as a single station would, except the sector correlation, which is only on the
single-station steps.

To see how it works, use the [sample batch](url:batch:start): two stations made from the
Sydney sample data.

## The metadata file {#the-metadata-file}

A text file with a first line of column names, then **one line per station**. Separate the
values with spaces or tabs. Lines starting with `#` are ignored. It is the batch metadata
file of Climpact for R, so files prepared for it work unchanged. The
[sample metadata file](url:batch:sample_metadata) is a good template.

```
station_file	latitude	longitude	wsdin	csdin	Tb_HDD	Tb_CDD	Tb_GDD	rxnday	rnnmm	txtn	SPEI
sydney_a.txt	-33.86	151.21	3	3	18	18	10	3	30	2	24
sydney_b.txt	-33.86	151.21	3	3	18	18	10	3	30	2	24
```

The 12 columns, in this order:

| Column | Meaning |
| --- | --- |
| `station_file` | the station file's name, without any folder |
| `latitude`, `longitude` | decimal degrees, negative south and west |
| `wsdin` | days for WSDId (1 to 10) |
| `csdin` | days for CSDId (1 to 10) |
| `Tb_HDD`, `Tb_CDD`, `Tb_GDD` | base temperatures for heating, cooling and growing degree days (°C) |
| `rxnday` | days for Rxdday (1 or more) |
| `rnnmm` | rain amount for Rnnmm (mm, 0 or more) |
| `txtn` | days for TXdTNd and TXbdTNbd (1 or more) |
| `SPEI` | extra SPI and SPEI time scale, in months |

What each setting does is explained in [The indices](guide:indices#settings). A batch has
no custom index.

## Station files {#station-files}

Each station file has the usual six-column format: see
[Preparing a station file](guide:station-file). Name each file **exactly** as in the
`station_file` column, including capitals and the extension. The station's name, used for
its results, is the file name without the extension, so it may only contain letters,
digits, spaces and `. ( ) - _`.

Choose several files at once, or put them in a zip; the zip can hold the metadata file
too.

## The check

Before anything runs, Climpact lists every station as:

- **ready**, perhaps with warnings (dates dropped, repeated dates, latitude 0);
- **file missing**: no file of that name was loaded. A file with the same name in other
  capitals or with another extension is pointed out;
- **has problems**: the file or the metadata line has errors, each given with its line.

Add or replace files on the same page and the stations are checked again. You can start
with some stations not ready: they are left out, and the results say why.

## Options {#options}

Base period
:   The same for every station. See [Choosing a base period](guide:base-period#batches).

Stations at the same time
:   On your own computer only: how many stations are calculated in parallel, one per
    processor core. Leave a core free if you want to keep working.

Draw the plots
:   On by default. Plots take about two thirds of the time; the tables and trend file are
    written either way.

As a rough guide, a station takes about 10 seconds with plots and 4 without.

## Results

While it runs, the page shows the progress of the whole batch and of each station. You
can leave the page: the calculation carries on, and you can return to it from
[Your calculations](url:jobs:list).

When it has finished you can download everything in one zip, laid out as Climpact for R
does, or each station's zip. A station that failed has an error file
(`<station>.errors.txt`) explaining why; correct its file and run it again. "Open as a
single station" takes a finished station to the single-station steps, to look at its
charts.
