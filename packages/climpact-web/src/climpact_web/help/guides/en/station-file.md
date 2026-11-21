title: Preparing a station file
summary: The file format Climpact reads, how to write missing values, adding a station, and changing its file and details later.

## The format

A station file is a plain text file with **one row per day** and **six columns**:

1. year (a whole number, for example 1961);
2. month (1 to 12);
3. day (1 to 31);
4. precipitation, in millimetres;
5. maximum temperature, in degrees Celsius;
6. minimum temperature, in degrees Celsius.

Separate the columns with spaces, tabs or commas. Use a full stop for decimals
(`32.4`, not `32,4`). A first row of column names is allowed; Climpact skips it.

```
year month day prcp tmax tmin
1936 1 1 0.3 23.7 18.7
1936 1 2 0.5 24.1 17.7
1936 1 3 -99.9 25 19.7
```

This is the format of Climpact for R and RClimDex, so files prepared for them work
unchanged. The [station file format](guide:format-station-file) page has the
specification on its own. The [sample station file](url:stations:sample_file) is a good template.

## Missing values {#missing-values}

Write a missing value as **-99.9**. `NA` (in capitals) is accepted too, as in Climpact
for R, but -99.9 is the standard code and works in every Climpact and RClimDex version.
Do not leave a value blank: a blank moves the other values into the wrong columns, and
the file is refused. Other codes, such as `na`, `N/A` or `-`, are refused too.

A day missing from the file altogether is treated as missing for all three variables, so
you do not need to add rows for days with no observations. A whole column can be -99.9
if the station does not measure that variable; the indices that need it are then not
calculated.

How much missing data the indices accept is described in
[The indices](guide:indices#missing-data).

## Order and repeated dates

Keep the rows in date order. If they are not, Climpact sorts them and tells you. A row
dated before the first row or after the last is left out, as in Climpact for R, so sort
the file if the first or last row is out of place. If a date appears twice, the indices
use the **last** row for that date and the quality checks list the repeat, so remove the
extra rows and replace the file.

Dates that do not exist (31 April, 29 February in a year that is not a leap year) are
dropped with a warning.

## Common problems

| What you see | What to do |
| --- | --- |
| A line without six values | A value is missing from that line. Write -99.9 in its place. |
| A value that is not a number | It has letters, or a comma as the decimal mark. Fix that line. |
| The file is not text | Save the spreadsheet as text (tab-delimited) or CSV first. |
| "Write missing values as -99.9" | The file uses a code for missing values other than -99.9 or `NA`, such as `na` or `N/A`. |

Add stations shows the first problem in the file's row of the table. Under the table,
"Every problem and warning, with its line in the file" lists them all with the **line
number in your file**, so you can find them in any text editor. Fix the file and choose
it again: it replaces the one in the table.

## Adding a station {#adding-a-station}

On [Add stations](url:stations:add), choose the station file, or drop it on the page.
Climpact reads it and shows it as a row of the review table: the file, the station
details, the period, the number of days and what reading found. Nothing is calculated
yet. Give the station details in the row, then choose "Add 1 station and check it".

The first station starts a **workspace**. A workspace holds your stations and their
settings, and you can add more stations to it later. To add many stations at once,
choose all their files together, with a metadata file for their coordinates: see
[Batch processing](guide:batch).

## Station details {#station-details}

In the file's row of the review table, give:

Station name
:   Used in the names of the result files and folders and on the plots. Letters, digits,
    spaces and `. ( ) - _` only. It starts from the file name, without the extension or
    a trailing range of years: `sydney_1936-2015.txt` becomes "Sydney".

Latitude and longitude
:   In decimal degrees: negative south of the equator and west of Greenwich. The
    **latitude matters**: it decides the hemisphere, and so the season used for the
    growing season length (GSL) and the Tx90 and Tn90 heatwaves. Latitude 0 counts as the
    Southern Hemisphere, as in Climpact for R. The longitude does not change any index.

The **base period** is the years the percentile thresholds are calculated from. It is the
workspace's, the same for every station. The panel beside the table, "Applies to every
station", shows it. Before the first station is added, change it under "Change workspace
settings". See [Choosing a base period](guide:base-period).

## The station's pages {#the-stations-pages}

Adding one station opens its Quality. The quality checks run, and the indices are
calculated beside them. The station has three tabs:

Quality
:   What the checks found, with a verdict: Ready, Usable or Fix first. "Go to indices"
    shows the indices. See [Reading the quality checks](guide:quality-control).

Indices
:   Every index with its trend, and a page for each index. "Compare with sector data" is
    here too: see [Sector correlation](guide:sector).

Files
:   The PDF report and every result file, each on its own.

A workspace of one station opens on the station. "Add stations" adds more to the same
workspace. With two or more, the workspace has an overview of its stations: see
[Following the calculation](guide:batch#following-the-calculation). Every workspace is
in [Workspaces](url:stations:workspaces).

## Changing the file or the details {#changing-the-file-or-the-details}

Beside the tabs, **Your inputs** lists what you gave: File, Station, Base period, Quality
thresholds and, once you have gone to the indices, Index settings. Replace or Edit opens a
side sheet with the form. The sheet says what applying will update. Choose Apply.

- A new file keeps the station details and thresholds.
- The base period, the quality thresholds and the index settings are the workspace's. A
  change applies to every station of the workspace, and you can undo it until the new
  results are ready. A workspace of several stations also has them in Workspace settings,
  at the top of its overview.
- The results shown stay, marked out of date, until their replacement is ready.

## Before you start

- Check the data with the quality checks, on the station's Quality, before you trust any
  index. See [Reading the quality checks](guide:quality-control).
- Climpact does not test homogeneity: jumps caused by a station move or a new instrument.
  Check and adjust for those first if you are working with observations.
- To try Climpact without your own data, choose "Use the sample station" on
  [Add stations](url:stations:add) (Sydney Observatory Hill, 1936 to 2015). The help
  home's [Sample data](url:help:index#samples-title) has it too.
