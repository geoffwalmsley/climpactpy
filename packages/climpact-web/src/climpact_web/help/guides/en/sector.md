title: Sector correlation
summary: Comparing the indices with yearly data from a sector such as agriculture or health, and reading the results with care.

## What it does

After calculating a station's indices you can compare them with yearly data from a sector
that depends on the climate: crop yields, hospital admissions, energy demand. Climpact
gives:

- the **correlation** between your sector data and each index, as a bar chart and a table;
- **scatter plots** of the sector data against yearly mean maximum, minimum and mean
  temperature and the number of days above 30 °C, each with a fitted straight line, its
  equation and R².

Open it with **Compare with sector data** at the top of a station's Indices, once its
indices are calculated. It works the same for a station added in a batch. It uses the
indices the Indices show. If they are out of date, it uses them as they are, so compare
again once they are up to date.

## The sector file {#the-sector-file}

A CSV file of **yearly** values with two columns: the year and your data. The first row
holds the column names; the first must be `Year`, and the second names your data. Write a
missing year as -99.9; do not leave years out.

```
Year,Wheat yield (t/ha)
1922,0.66
1923,0.76
1924,1.13
```

Your data and the station must have **at least 10 years in common**. Climpact for R's
sample is yearly wheat yields for New South Wales, 1922 to 1999
(`wheat_yield_nsw_1922-1999.csv`), which goes with the Sydney sample station. "Use the
sample data" on the page uses it, and the help home's [Sample data](url:help:index#samples-title) has
it to download.

## Settings {#settings}

Under "Plot attributes":

Title
:   Printed on each plot. The station name if you leave it empty.

Label for y axis
:   The name and units of your data, for example *Wheat yield (t/ha)*. Taken from the file
    name if you leave it empty.

Detrend data
:   On by default. See below.

Then choose "Calculate correlations". The page shows the progress, then the results.

## Detrending {#detrending}

Many sector series rise or fall steadily for reasons that have nothing to do with the
weather: yields grow with better seed and farming, admissions with population. Over the
same years temperatures have also risen, so the two can correlate strongly without any
link between them. Detrending removes the straight-line trend from your data before the
comparison, so the correlation reflects how year-to-year changes in the sector follow
year-to-year changes in the climate. Keep it on unless you have removed such trends
yourself.

## Reading the results {#reading-the-results}

- The **correlation** ranges from -1 to 1. Values near 0 mean no linear relationship. The
  bar chart gives the coefficient of each index, with temperature and precipitation
  indices told apart.
- **R²** in the scatter plots is the share of the year-to-year variation in your data that
  the fitted line explains.
- With few years, quite large correlations arise by chance: with 20 years, a correlation
  needs to be above about 0.44 to be significant at the 5% level.
- With dozens of indices, some will correlate well by chance. Look for relationships that
  make physical sense.
- Correlation shows association, not cause.

Missing index values are correlated as the number -99.9, as in Climpact for R, which can
distort the correlation of an index with missing years. Treat those with caution.

## The files

The results are shown on the same page, and their files are on the station's Files, under
"Sector comparison". They are those of the `corr` folder: the correlation table
(`<station>_index-sector_correlation_<name>.csv`), the yearly temperature summaries used
for the scatter plots (`<station>_corr_tmax_<name>.csv` and so on), and the plots.
`<name>` is taken from your data's column name, with `detrended.` in front when detrended.
