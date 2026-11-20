title: Choosing a base period
summary: What the base period is used for, which years to choose, and what happens when the data do not cover it.

## What the base period does

Many indices compare each day with what is normal for that time of year at the station:
"days warmer than the 90th percentile" (TX90p), warm spells (WSDI), heavy rain (R95p) and
others. Climpact calculates those **percentile thresholds** from the years of the base
period, then counts against them in every year of the record.

Percentile thresholds make stations in different climates comparable: a hot day in the
tropics and a hot day in a temperate climate are each judged against their own normal.

The indices that use the base period are marked "uses the base period" in
[the list of indices](guide:indices#the-indices).

## Which years to choose

- **30 years if you can.** A long base period captures more of the natural variability.
  Having 30 good years matters more than matching particular years.
- **1961-1990** is the WMO reference for long-term climate change assessment.
- **1991-2020** is the WMO reference for climate monitoring.
- **1971-2000** is Climpact's default, as in Climpact for R.

Choose years with good data: few missing days and no known problems from the
[quality checks](guide:quality-control). Use the same base period for stations you want
to compare.

## When the data do not cover it {#coverage}

The base period must lie within the years of your file.

- If it covers **part** of the base period, Climpact uses the years that have data and
  tells you how many.
- If **less than a year** of the base period is in the file, the percentile thresholds
  cannot be calculated, and neither can the indices that use them. The other indices are
  calculated as usual.
- A day's threshold also needs at least 10% of the days around it in the base period to
  have data.

## Inside the base period

Inside the base period, a year would be compared with thresholds partly calculated from
itself, which makes exceedances look rarer than outside it. Climpact corrects this as
Climpact for R does (Zhang et al., 2005): for each year in the base period, the thresholds
are recalculated from the other years, with one of them repeated to keep the length, and
the results averaged. This is why the calculation takes longer with a long base period.

The correction applies to the temperature percentage indices (TX10p, TX90p, TN10p, TN90p
and TXgt50p). The other indices that use the base period do not need it.

## Batches {#batches}

Every station of a workspace uses the **same base period**, so in a batch choose years
that every station has data for. Add stations checks each file against it before anything
is calculated. A station with less than a year of data in the base period says "Read ·
under a year in the base period": it can be added, and is calculated without its
percentile indices. A file with no data in the base period is a problem, and is not added
until the base period or the file changes.

## The threshold file {#the-threshold-file}

The results include `thres/<station>_thres.csv`: the thresholds for each of the 365 days
of the year, for example `tmax_q90` for the 90th percentile of the maximum temperature.
They are calculated over a 5-day window around each day, and the heatwave thresholds
(`HW_TX90`, `HW_TN90`, `HW_TAVG90`) over a 15-day window. The file is for interest; the
indices have already used it.

## Reference

Zhang X, Hegerl G, Zwiers F W and Kenyon J (2005). Avoiding inhomogeneity in
percentile-based indices of temperature extremes. *Journal of Climate* 18, 1641-1651.
