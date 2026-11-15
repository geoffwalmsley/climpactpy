title: Reading the quality checks
summary: What each quality check looks for, how to read its results, and what to do about what it finds.

## How to use the checks

The quality checks look for values that are possible errors. They **only report**:
nothing in your data is changed, and the indices are calculated from the file as loaded.

1. Run the checks and look at the plots and tables.
2. For each value flagged, compare it with the original records, neighbouring stations
   or the weather at the time.
3. Correct real errors in your file (or set them to -99.9), load it again and re-run the
   checks.
4. Leave values that are correct, even if they are unusual: extremes are what the indices
   measure.

A flagged value is not necessarily wrong, and a clean result does not prove the data are
right.

## Outliers {#outliers}

Values far from the usual range for their calendar month. For each month, Climpact draws
a box from the lower to the upper quartile of all the years' values. A value is an outlier
when it lies more than **3 box-lengths** (interquartile ranges) beyond the box for
maximum temperature, minimum temperature and the diurnal temperature range, and more than
**5** for precipitation. Only days with precipitation are used for its box, and only
high values count.

The outlier file lists each one under a heading: `Prec up` for high precipitation,
`TX up` and `TX low` for high and low maximum temperatures, and the same for TN and DTR.
Each row gives all four values of the day, which often shows the cause, such as a minimum
temperature typed into the maximum column.

The plots of outliers **per year** give an overview of the whole record and show years
where problems cluster.

You can change the two multiples (3 and 5) before running the checks. A smaller number
flags more values.

## Minimum at or above maximum {#maximum-below-minimum}

Days where the minimum temperature is **equal to or higher than** the maximum. These are
nearly always errors: swapped columns, a typing error, or readings from different days.

## Values too large {#values-too-large}

Daily precipitation above **200 mm** or below 0, and temperatures above **50 °C** or below
**-50 °C**. Such values can be real, so check them against other records. You can change
both limits before running the checks.

## Repeated dates {#repeated-dates}

Dates that appear more than once in the file. The indices use the last row of a repeated
date, so remove the others.

## Jumps {#jumps}

Days where the maximum or minimum temperature changed by **20 °C or more** from the day
before. Large jumps happen (a cold front), but they are also a sign of a typing error or a
missing minus sign. The date given is the first of the two days compared.

## Repeated values {#repeated-values}

The same maximum or minimum temperature on **more than 5 days in a row** (the change from
one day to the next is zero for at least 5 days). A long run of identical values usually
means a value was copied forward or the instrument was stuck. The date is that of the last
change in the run, and the file gives the number of repeated values.

## Missing days {#missing-days}

The number of missing days in each year for each variable. Use it to see whether a year
will have index values: a month with **more than 3** missing days, or a year with **more
than 15**, gets no value, and a year with a missing month gets no yearly value either. See
[Missing data](guide:indices#missing-data).

## Decimal values {#decimal-values}

How often each decimal, from .0 to .9, occurs. With careful readings they should be about
equally common. Many more .0 and .5 values show that observers rounded, which makes counts
of days above a fixed threshold (such as 25 °C) jump.

## Daily series and histograms {#daily-series-and-histograms}

The daily values of precipitation, maximum and minimum temperature and the diurnal
temperature range over the whole record, with missing days marked. Look for gaps,
periods that look different from the rest, and values that stand out.

The precipitation histogram shows how often each amount of 1 mm or more occurs. A sudden
change in the smallest amounts reported can show a new instrument or a change in how
small amounts were recorded.

## The files {#the-files}

| File | Content |
| --- | --- |
| `<station>_outliers.csv` | outliers by variable and direction |
| `<station>_tmaxmin.csv` | days with the minimum at or above the maximum |
| `<station>_toolarge.csv` | values beyond the limits |
| `<station>_duplicates.csv` | repeated dates |
| `<station>_tx_jumps.csv`, `<station>_tn_jumps.csv` | large day-to-day changes |
| `<station>_tx_flatline.csv`, `<station>_tn_flatline.csv` | runs of repeated values |
| `<station>_nastatistics.csv` | missing days per year |

The files are in the `qc` folder of the results, in the same format as Climpact for R.
A file with nothing to report says so, for example "NO DUPLICATE DATES FOUND".

## What the checks do not find {#what-the-checks-do-not-find}

The checks look at single values. They do not test **homogeneity**: steps in a series
caused by a station move, a new instrument, a change of observing time or growth of a town
around the station. These can create false trends in the indices. If you are working with
observations, test and adjust for them with tools made for the purpose (for example
RHtests) before calculating indices, and use station history records where you have them.
