title: Batch processing
summary: Adding many stations at once: the station files, the metadata file, the review table, and following the calculation on the workspace's overview.

## When to use a batch

Use a batch when you have more than a few stations. On [Add stations](url:stations:add),
choose all their station files at once, with a **metadata file** that gives each station's
latitude, longitude and settings. Climpact reads every file and lists them in one table.
Nothing is calculated until you add them. Then every station is checked and calculated in
the background, in one workspace.

Each station of the workspace is a full station: it has its own Quality, Indices and
files, and you can compare it with sector data, as for a station added on its own.

To see how it works, open the sample batch from the help home's
[Sample data](url:help:index#samples-title): two stations made from the Sydney sample
data, with their metadata file.

## Station files {#station-files}

Each station file has the usual six-column format: see
[Preparing a station file](guide:station-file). Choose several files at once, drop them on
the page, or put them in a zip. The zip can hold the metadata file too. You can add more
files to the same table later. A file with the same name as one already there replaces it.

The table starts each station's name from its file name, without the extension or a
trailing range of years: `moruya_heads_069018.txt` becomes "Moruya Heads 069018". Change
it in the table if you like. The name is used for the station's results, so it may only
contain letters, digits, spaces and `. ( ) - _`. Two stations cannot have the same name.

## The metadata file {#the-metadata-file}

The metadata file is optional. Without one, type or paste each station's latitude and
longitude in the table.

It is a text file with a first line of column names, then **one line per station**.
Separate the values with spaces or tabs. Lines starting with `#` are ignored. It is the
batch metadata file of Climpact for R, so files prepared for it work unchanged. The
[sample metadata file](url:batch:sample_metadata) is a good template.

```
station_file	latitude	longitude	wsdin	csdin	Tb_HDD	Tb_CDD	Tb_GDD	rxnday	rnnmm	txtn	SPEI
sydney_a.txt	-33.86	151.21	3	3	18	18	10	3	30	2	24
sydney_b.txt	-33.86	151.21	3	3	18	18	10	3	30	2	24
```

The [batch metadata file format](guide:format-batch-metadata) page has the specification
on its own. The 12 columns, in this order:

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

Name each station file **exactly** as in the `station_file` column, including capitals and
the extension. If a file with a similar name came instead, the table says so.

A station whose line sets values other than the workspace's shows "Custom" in the table's
Index settings column. What each setting does is explained in
[The indices](guide:indices#settings). The metadata file has no column for a custom index.

## The review table {#the-review-table}

Before anything is calculated, Add stations shows a row for each station file: the file,
the station name, latitude and longitude, the period, the number of days, the index
settings, and what reading the file found.

- **Read**, with the share of missing values: the station is ready to add. A warning may
  follow, such as repeated dates or less than a year of data in the base period. The
  station can still be added, and its quality checks list what was found.
- A **problem**, in red: the file could not be read, a latitude or longitude is missing or
  out of range, a station name is missing or given twice, a metadata value is out of
  range, or the file has no data in the base period. A file named in the metadata file
  that did not come has a row too.

Type a name, latitude or longitude in the table, or paste a column from a spreadsheet:
it fills the cells below the one you paste into. Add or replace files on the same page,
and the table is checked again. Under the table, "Every problem and warning, with its line
in the file" lists them all, and one sentence says what is left to fix.

"Add 5 stations and check them" adds only the rows that are ready. A row with a problem is
not added. Fix it first, or add the others now and add it later with Add stations on the
workspace's overview.

## Settings {#options}

The panel beside the table, "Applies to every station", shows the workspace's settings.
Before the workspace has any stations, change them under "Change workspace settings":

Base period
:   The same for every station. See [Choosing a base period](guide:base-period#batches).

Stations to calculate at the same time
:   On your own computer only: how many stations are calculated in parallel, one per
    processor core. Leave a core free if you want to keep working.

Plots and PDF reports
:   On by default. Plots and reports take about two thirds of the time; the tables and
    trend file are written either way.

As a rough guide, a station takes about 10 seconds with plots and 4 without.

The quality thresholds and index settings start at their defaults. Once the workspace has
stations, change the settings with Workspace settings on its overview. Every station is
then calculated again.

## Following the calculation {#following-the-calculation}

Adding two or more stations opens the workspace's overview. (One station opens on its
Quality.) Each station's quality checks run beside its calculation.

The **run status line** above the Stations table sums up the run. While it runs, it says
how many stations are done and about how long is left. When it has finished, it says how
many stations were calculated and how long it took. It turns red only when a station
failed, and names it.

The **Stations table** has a row for each station: its period, missing values, Quality
verdict, Indices and how many indices have a significant trend. The Indices column says
Waiting, Calculating with how far it has got, Done, Not run or Failed. The rows update as
each station finishes, and a finished station opens while the others are still being
calculated.

You can leave the page. The calculation carries on, and the workspace is in
[Workspaces](url:stations:workspaces).

### Cancel and "Not run" {#cancel}

Cancel on the run status line stops the batch. Stations that have finished keep their
results. The others say "Not run", and the line says "The run was cancelled." To
calculate one later, open it: its Indices offer "Check the settings and calculate".

### A station that failed {#a-station-that-failed}

Its row says "Failed:" and why, on a red tint, and the run status line names it. When the
base period is the cause, "Change base period" opens the workspace's base period.
Otherwise correct the station file and replace it from the station's Inputs: the station
is calculated again. A station whose values are all missing has "No indices", with
"Replace the file".

## Files {#files}

Once every station has finished, **Export** on the overview and the workspace's **Files**
have the results:

- **Everything**: one zip with each station's results in a folder, laid out as Climpact
  for R writes them;
- the trends and the indices of all stations, each as one CSV file;
- each station's own files: the report, the plots, the trends, the thresholds and the
  quality-control files;
- `climpact_run.json`: how the results were made, with each station's file and settings.

A station that failed has a file `<station>.errors.txt` in the zip, with the reason.
