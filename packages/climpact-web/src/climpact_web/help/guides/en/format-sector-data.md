title: Sector data file format
summary: A CSV file of yearly values with two columns, the year and your data, under a row of column names. It is the sector file of Climpact for R.

``` { #example }
Year,Wheat yield (t/ha)
1922,0.66
1923,0.76
1924,1.13
```

[Download the sample sector file](url:stations:sector_sample) (wheat yields, New South
Wales, 1922–1999).

## Columns {#columns}

| # | Column | Rules |
| --- | --- | --- |
| 1 | `Year` | The first row's name must be `Year`; then one whole year per row |
| 2 | Your data | The first row names it: the name is used on the plots |

- Values separated by commas.
- One row per year: write a missing year as -99.9; do not leave years out.
- At least 10 years in common with the station.

## Using it {#using-it}

The sector data are correlated with a station's yearly temperatures and indices, after
the station has been calculated: on the station's Indices, or with
`climpact sector-correlation` on the [command line](guide:command-line#sector-correlation).
How to read the results is in [Sector correlation](guide:sector).
