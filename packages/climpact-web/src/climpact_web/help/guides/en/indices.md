title: The indices
summary: Types of indices, the settings you can change, how missing data are handled, the result files, and the definition of every index.

## What an index is

A climate index turns a long series of daily values into one number per year or month
that describes one aspect of the climate. Thirty years of daily maximum temperatures are
about 11,000 values; the yearly hottest day (TXx) reduces them to 30 that show whether the
hottest days are changing.

Climpact calculates the indices defined by the WMO Expert Team on Sector-specific Climate
Indices (ET-SCI), which include the ETCCDI indices. Most are of three kinds:

- **Extremes**, such as the hottest day of the year (TXx) or the wettest day (Rx1day).
- **Thresholds**, counting days above or below a value. The value can be fixed (days over
  25 °C, SU) or a percentile of the station's own climate (days warmer than the 90th
  percentile, TX90p). See [Choosing a base period](guide:base-period).
- **Durations**, such as the longest dry spell (CDD) or the growing season length (GSL).

## Settings {#settings}

Some indices have a part you choose. The defaults are those of Climpact for R.

| Setting | Index | Default |
| --- | --- | --- |
| Days for WSDId | warm spells of at least *d* days above the 90th percentile | 1 |
| Days for CSDId | cold spells of at least *d* days below the 10th percentile | 1 |
| Days for Rxdday | largest total over *d* days in a row | 3 |
| Days for TXdTNd and TXbdTNbd | runs of *d* hot (or cold) days and nights | 2 |
| Base temperature for HDDheat | heating degree days | 18 °C |
| Base temperature for CDDcold | cooling degree days | 18 °C |
| Base temperature for GDDgrow | growing degree days | 10 °C |
| Rain amount for Rnnmm | days with at least *nn* mm | 30 mm |
| Extra SPI and SPEI time scale | added to 3, 6 and 12 months | 24 months |

The name of the result shows the value used: Rxdday with 3 days is written `rx3day`,
Rnnmm with 30 mm is `r30mm`.

## Your own index {#your-own-index}

You can add one index of your own: the number of days each year and month when a variable
is above or below a value. Choose the variable (TX, TN, TM, the mean temperature, DTR, the
diurnal range, or precipitation), the comparison (<, ≤, >, ≥) and the value. Days with
TX ≥ 40 °C are written `TXge40`, using lt, le, gt and ge for the comparisons.

## Missing data {#missing-data}

The indices need nearly complete data, as in Climpact for R:

- a **month** with more than **3** missing days has no monthly value;
- a **year** with more than **15** missing days, or with any month missing, has no yearly
  value.

Missing values are written as **-99.9** in the index files. Remove them before calculating
with the values in a spreadsheet.

Spells that cross the end of a year are counted in the year they end. CDD and CWD, the
longest dry and wet spells, can therefore be longer than a year, with the years before
written as missing. Read CDD with care in dry climates.

## The index files {#the-index-files}

The results have one folder per kind of output, in the layout of Climpact for R:

| Folder | Content |
| --- | --- |
| `indices` | one CSV file per index and time scale, such as `<station>_su_ANN.csv` (yearly) and `<station>_su_MON.csv` (monthly) |
| `plots` | a plot of each index, and all of them in `<station>_all_plots.pdf` |
| `trend` | the trend of every index: see [Interpreting trends](guide:trends) |
| `thres` | the percentile thresholds: see [the threshold file](guide:base-period#the-threshold-file) |
| `qc` | the quality checks: see [Reading the quality checks](guide:quality-control) |
| `corr` | the sector correlation, if you ran it: see [Sector correlation](guide:sector) |

Each index file starts with a few lines describing the station and the index, then a
row per year or month. Most have a column of **standardised values**: each value minus the
mean of all years, divided by their standard deviation, so that indices with different
units can be compared. Indices that come with a date (such as TXx) give the date of the
extreme too.

Besides the zip, the **Files** page (the link from the results) offers a **PDF report**, which
Climpact for R does not make: the station and the settings used, what the quality checks
found, and a page per index with its plot and trends, with a table of contents and
bookmarks. It is a separate file, so the zip keeps the layout above. Files also lists
every other file on its own, with its size: the summary and quality-control files, the
plots and each index's table and plot. Each index page's chart also saves the view on
screen as a PNG or SVG image.

## Heatwaves

Climpact gives two families of heatwave indices.

**Tx90 and Tn90 heatwaves** are three or more days in a row when the maximum (or minimum)
temperature is above its 90th percentile for the time of year, calculated over a 15-day
window. They are counted over the extended summer only: November to March in the Southern
Hemisphere, May to September in the Northern. For each year: the number of heatwaves
(HWN), the days in them (HWF), the longest (HWD), their mean temperature (HWM) and the
peak temperature of the hottest (HWA). A year without heatwaves has HWN and HWF of 0 and
the others missing.

**Excess heat factor (EHF) heatwaves** follow Nairn and Fawcett (2015). The EHF combines
how hot the last three days were compared with the 95th percentile and with the month
before. Heatwaves are runs of days with a positive EHF, over the whole year. Besides number,
days, longest and mean duration, Climpact gives the peak and total **severity** (EHF divided
by the 85th percentile of positive EHF in the base period: above 1 is severe, above 3
extreme) and **intensity** (raw EHF, comparable only at the same station). A heatwave that
crosses the new year counts in both years.

## Drought: SPI and SPEI

The Standardised Precipitation Index (SPI) compares precipitation over the past 3, 6, 12
(and your extra) months with the same months in the base period. The Standardised
Precipitation Evapotranspiration Index (SPEI) does the same for precipitation minus
potential evaporation, estimated from temperature. Values below -1 are drier than normal,
below -2 extremely dry. They are monthly values. A base period of at least 30 years gives
the most reliable values; a short one leaves many months missing.

No index is best for every drought. SPI is recommended by WMO for meteorological drought;
see the WMO *Handbook of drought indicators and indices* (2016) for others.

## The indices {#the-indices}

Each definition below comes from Climpact's list of indices. TX is the daily maximum
temperature, TN the minimum, TM the mean of the two, DTR their difference and PR the
precipitation. A wet day has at least 1 mm.

[[index-catalogue]]

## References

Nairn J R and Fawcett R G (2015). The excess heat factor: a metric for heatwave intensity
and its use in classifying heatwave severity. *International Journal of Environmental
Research and Public Health* 12, 227-253.

Perkins S E and Alexander L V (2013). On the measurement of heat waves. *Journal of
Climate* 26, 4500-4517.

Zhang X, Alexander L, Hegerl G C and others (2011). Indices for monitoring changes in
extremes based on daily temperature and precipitation data. *WIREs Climate Change* 2,
851-870.
