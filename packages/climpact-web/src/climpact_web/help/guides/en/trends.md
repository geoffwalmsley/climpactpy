title: Interpreting trends
summary: How Climpact calculates the trend of each index, what the bounds mean, and how to tell whether a trend is significant.

## Sen's slope {#sens-slope}

Climpact gives the trend of every index as **Sen's slope**: the median of the slopes
between every pair of values in the series. Because it takes the median, a few extreme
years hardly move it, which suits indices of extremes better than a least-squares line.
It is calculated as Climpact for R does, with the zyp and Kendall methods, and gives the
same numbers.

The slope is in the index's units **per year** for yearly values and **per month** for
monthly values. Multiply a yearly slope by 10 for the change per decade.

## Confidence bounds and significance {#confidence-bounds-and-significance}

With each slope come a **lower bound** and an **upper bound**: the 95% confidence interval
of the slope, from Kendall's test.

- If both bounds are **above zero**, the index has increased, and the trend is significant
  at the 5% level.
- If both are **below zero**, it has decreased significantly.
- If the interval **includes zero** (lower bound negative, upper bound positive), the data
  do not show a trend that can be told apart from chance at that level.

The trend file does **not** give a p-value. Read significance from the bounds as above.

### An example

For Sydney Observatory Hill, 1936 to 2015 (the sample data):

| Index | Lower bound | Slope | Upper bound | Reading |
| --- | --- | --- | --- | --- |
| SU, yearly | 0.38 | 0.52 | 0.65 | about 5 more summer days per decade; significant |
| TXx, yearly | -0.022 | 0.003 | 0.031 | no clear change in the hottest day of the year |

## When no trend is given {#when-no-trend-is-given}

A trend needs **at least 10 values** and **at least 70%** of the series present. When
either fails, the slope and both bounds are written as `NA`. An index that has no value in
any year has no row at all.

Bounds equal to the slope, often all 0, mean the series hardly varies: for example, frost
days at a station that never has frost.

## The trend file {#the-trend-file}

`trend/<station>_trend.csv` has one row per index and time scale, with the columns
`Index`, `Frequency`, `StartYear`, `EndYear`, `Lower bound`, `Slope` and `Upper bound`.

- `annual` and `monthly` rows are the trends of the yearly and monthly values.
- For monthly indices, `DJF`, `MAM`, `JJA` and `SON` rows give the trends of the seasonal
  values (December to February, and so on), one value per year.
- SPI and SPEI rows are trends of the values for single months of the year. The labels
  are those of Climpact for R: for the 6- and 12-month scales they do not name the month
  used (APR is August, OCT is October, JUN is January and DEC is December).
- The TX95t row is a slope across the 365 days of the year, not a trend over time. Ignore
  it.

## Reading trends with care

- A significant trend says the change is unlikely to be chance, not what caused it.
  Station moves and new instruments can create trends: see
  [What the checks do not find](guide:quality-control#what-the-checks-do-not-find).
- Short records give wide bounds. Compare stations over the same years.
- Trends in percentile indices are measured against the base period, so stations with the
  same base period compare best.
