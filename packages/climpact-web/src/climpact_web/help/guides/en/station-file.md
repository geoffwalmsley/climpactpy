title: Preparing a station file
summary: The file format Climpact reads, how to write missing values, and the station details to give.

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
unchanged. The [sample station file](url:stations:sample_file) is a good template.

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

Keep the rows in date order. If they are not, Climpact sorts them and tells you. If a
date appears twice, the indices use the **last** row for that date and the quality
checks list the repeat, so remove the extra rows and load the file again.

Dates that do not exist (31 April, 29 February in a year that is not a leap year) are
dropped with a warning.

## Common problems

| What you see | What to do |
| --- | --- |
| A line without six values | A value is missing from that line. Write -99.9 in its place. |
| A value that is not a number | It has letters, or a comma as the decimal mark. Fix that line. |
| The file is not text | Save the spreadsheet as text (tab-delimited) or CSV first. |
| "Write missing values as -99.9" | The file uses a code for missing values other than -99.9 or `NA`, such as `na` or `N/A`. |

Climpact shows each problem with the **line number in your file**, so you can find it in
any text editor.

## Station details {#station-details}

After the file, give:

Station name
:   Used in the names of the result files and folders and on the plots. Letters, digits,
    spaces and `. ( ) - _` only. It defaults to the file name.

Latitude and longitude
:   In decimal degrees: negative south of the equator and west of Greenwich. The
    **latitude matters**: it decides the hemisphere, and so the season used for the
    growing season length (GSL) and the Tx90 and Tn90 heatwaves. Latitude 0 counts as the
    Southern Hemisphere, as in Climpact for R. The longitude does not change any index.

Base period
:   The years the percentile thresholds are calculated from. See
    [Choosing a base period](guide:base-period).

## Before you start

- Check the data with the quality checks in step 2 before you trust any index. See
  [Reading the quality checks](guide:quality-control).
- Climpact does not test homogeneity: jumps caused by a station move or a new instrument.
  Check and adjust for those first if you are working with observations.
- To try the steps without your own data, use the
  [sample station](url:stations:new) (Sydney Observatory Hill, 1936 to 2015).
