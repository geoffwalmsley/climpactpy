title: Station file format
summary: A plain text file with one row per day and six columns: year, month, day, precipitation (mm), maximum and minimum temperature (°C). It is the format of Climpact for R and RClimDex, so their files work unchanged.

``` { #example }
year month day prcp tmax tmin
1936 1 1 0.3 23.7 18.7
1936 1 2 0.5 24.1 17.7
1936 1 3 -99.9 25 19.7
```

[Download the sample station file](url:stations:sample_file) (Sydney Observatory Hill,
1936–2015).

## Columns {#columns}

| # | Column | Unit | Rules |
| --- | --- | --- | --- |
| 1 | Year | – | A whole number, for example 1961 |
| 2 | Month | – | 1 to 12 |
| 3 | Day | – | 1 to 31; dates that do not exist are dropped with a warning |
| 4 | Precipitation (PR) | mm | 0 or more |
| 5 | Maximum temperature (TX) | °C | The day's highest temperature |
| 6 | Minimum temperature (TN) | °C | The day's lowest temperature |

- Columns separated by spaces, tabs or commas.
- A full stop for decimals: `32.4`, not `32,4`.
- A first row of column names is allowed and skipped.

## Missing values {#missing-values}

Write a missing value as **-99.9**. `NA` (in capitals) is accepted too, as in Climpact for
R. Never leave a value blank: it moves the other values into the wrong columns. Other
codes, such as `na`, `N/A` or `-`, are refused.

A day missing from the file altogether counts as missing for all three variables. A whole
column can be -99.9 if the station does not measure that variable; the indices that need
it are then not calculated.

How much missing data each index accepts is on its page in the
[Index reference](url:help:index_reference).

## Order and repeated dates {#order}

Keep the rows in date order; if they are not, Climpact sorts them and says so. A row dated
before the first row or after the last is left out, as in Climpact for R. If a date
appears twice, the indices use the last row and the quality checks list the repeat.

## Common problems {#problems}

| Message | What to do |
| --- | --- |
| A line without six values | Write -99.9 in place of the missing value. |
| A value that is not a number | It has letters, or a comma as the decimal mark. Fix that line. |
| The file is not text | Save the spreadsheet as tab-delimited text or CSV first. |
| Write missing values as -99.9 | The file uses another code, such as `na` or `N/A`. |

Each problem is shown with its line number in your file.

## Station details {#details}

The file holds no name or position. Give them when you add the station (or with `--name`,
`--lat` and `--lon` on the [command line](guide:command-line#run)). The latitude matters:
it decides the hemisphere, and so the season of GSL and of the Tx90 and Tn90 heatwaves.
How to prepare and add a file is in [Preparing a station file](guide:station-file).
