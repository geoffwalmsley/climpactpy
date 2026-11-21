title: Index notes
summary: The text of the index reference's pages that the catalogue does not hold.

<!--
The index reference (#319, help/reference.py) reads this file. It is not a guide.

- "## kind: <kind>": How it is calculated, written once per kind of index. {code} is the
  index's code (TX90p), {pct} its percentile where it has one.
- "## <short name>": one index. The first paragraph is the page's lead (and its
  description for search engines): one plain sentence. A paragraph starting
  "Read with care:" is the "Read with care" box. Other paragraphs are added to How it is
  calculated, after the kind's text.
-->

## kind: fixed-count

Each day is compared with the fixed value in the definition, and {code} is the number of
days in the year (or month) that meet it.

Nothing comes from the base period, so the values of different stations and periods
compare directly.

## kind: percentile-count

For each calendar day, Climpact takes the values on the 5 days centred on it in every
year of the base period and finds their {pct}. That is the day's threshold.

{code} is then the share of days in each year (or month) beyond its day's threshold. In
the base period it is close to the percentile's share by construction, so a change shows
how far the climate has moved since.

Inside the base period the thresholds are bootstrapped, as in climdex.pcic, so the years
of the base period are not compared with themselves.

## kind: threshold-value

For each calendar day, Climpact takes TX on the 5 days centred on it in every year of
the base period and finds their 95th percentile.

The result is one value per calendar day, the same for every year, so it has no trend.
It is the threshold a day's TX is compared with, not a count of days.

## kind: spell

Days beyond their calendar day's percentile threshold, found as for the percentile
indices from a 5-day window in the base period, are marked. Every run of marked days long
enough to count adds its days to {code}, the total for the year.

Spells are cut at the end of the year: a spell that crosses it counts its days in each
year, and only when each part is long enough.

## kind: dual-spell

A day is marked when both TX and TN are beyond their calendar day's percentile
thresholds, found from a 5-day window in the base period. {code} is the number of runs
of the chosen number of marked days in the year.

## kind: rain-spell

A wet day has at least 1 mm of precipitation, a dry day less. {code} is the length of
the longest run, counted in the year the run ends.

## kind: extreme

{code} is the extreme value of each year (and of each month, where there are monthly
values). The result files give the date it happened too.

## kind: rain-extreme

For a total over several days, Climpact sums the precipitation of every run of that many
days in a row and takes the largest. {code} is the largest total of each year (and of each
month). The result files give its date too.

## kind: mean

{code} is the mean over the days of each year (and of each month).

## kind: rain-total

Only wet days, with at least 1 mm, count. {code} is calculated over the days of each year
(and of each month, where there are monthly values).

## kind: rain-percentile

The {pct} comes from the wet days (at least 1 mm) of the base period: one value for the
station, not one per calendar day. {code} uses the days of each year wetter than it.

## kind: degree-days

For each day, the difference between the daily mean temperature (TM) and the base
temperature is taken when it is on the counted side, and {code} adds the differences up
over the year.

The base temperature is a setting, so the file name carries it: with 18 °C, HDDheat is
written hddheat18.

## kind: season

The season is found from the daily mean temperature (TM), and its length counted in
days.

## kind: drought

Precipitation is summed over the time scale ending in each month. For each calendar
month, a distribution is fitted to those sums in the base period, and each sum is turned
into the value of a standard normal distribution with the same probability.

So 0 is the base period's median, −1 is drier than about 84% of the base period, and −2
drier than about 98%.

## fd

The number of days when the daily minimum temperature (TN) is below 0 °C.

## tnlt2

The number of days when the daily minimum temperature (TN) is below 2 °C.

## tnltm2

The number of days when the daily minimum temperature (TN) is below −2 °C.

## tnltm20

The number of days when the daily minimum temperature (TN) is below −20 °C.

## id

The number of days when the daily maximum temperature (TX) stays below 0 °C.

## su

The number of days when the daily maximum temperature (TX) is above 25 °C.

## tr

The number of nights when the daily minimum temperature (TN) stays above 20 °C.

## gsl

The length of the growing season: from the first run of 6 days with the daily mean
temperature (TM) above 5 °C to the first run of 6 days below 5 °C in the second half of
the season.

In the Northern Hemisphere the season starts after 1 January and ends after 1 July. In
the Southern Hemisphere it is counted from July to June, so the station's latitude
matters; latitude 0 counts as southern, as in Climpact for R.

## txx

The highest daily maximum temperature (TX) of each year or month: the hottest day.

## tnn

The lowest daily minimum temperature (TN) of each year or month: the coldest night.

## tnx

The highest daily minimum temperature (TN) of each year or month: the warmest night.

## txn

The lowest daily maximum temperature (TX) of each year or month: the coldest day.

## dtr

The mean difference between the daily maximum and minimum temperature (TX − TN) over
each year or month.

## wsdi

The number of days in a year that are part of a warm spell: at least 6 days in a row when
TX is above its 90th percentile.

WSDI fixes the spell at 6 days, as ETCCDI defines it. WSDId is the same with a length you
choose.

## wsdid

The number of days in a year that are part of a warm spell: at least d days in a row when
TX is above its 90th percentile. You choose d.

WSDI is the same with d fixed at 6. With d = 1 every warm day counts.

Read with care: with d = 1, as in Climpact for R, a year with any day missing has no value.

## csdi

The number of days in a year that are part of a cold spell: at least 6 days in a row when
TN is below its 10th percentile.

CSDI fixes the spell at 6 days, as ETCCDI defines it. CSDId is the same with a length you
choose.

## csdid

The number of days in a year that are part of a cold spell: at least d days in a row when
TN is below its 10th percentile. You choose d.

CSDI is the same with d fixed at 6. With d = 1 every cold night counts.

Read with care: with d = 1, as in Climpact for R, a year with any day missing has no value.

## txgt50p

The percentage of days when the daily maximum temperature (TX) is above its median (50th
percentile) for that time of year in the base period.

## tx10p

The percentage of days when the daily maximum temperature (TX) is below the 10th
percentile of TX for that time of year in the base period.

## tx90p

The percentage of days when the daily maximum temperature (TX) is above the 90th
percentile of TX for that time of year in the base period.

## tn10p

The percentage of days when the daily minimum temperature (TN) is below the 10th
percentile of TN for that time of year in the base period.

## tn90p

The percentage of days when the daily minimum temperature (TN) is above the 90th
percentile of TN for that time of year in the base period.

## tmge5

The number of days when the daily mean temperature (TM) is at least 5 °C.

## tmlt5

The number of days when the daily mean temperature (TM) is below 5 °C.

## tmge10

The number of days when the daily mean temperature (TM) is at least 10 °C.

## tmlt10

The number of days when the daily mean temperature (TM) is below 10 °C.

## txge30

The number of days when the daily maximum temperature (TX) is at least 30 °C.

## txge35

The number of days when the daily maximum temperature (TX) is at least 35 °C.

## tx95t

The 95th percentile of the daily maximum temperature (TX) for each calendar day, from the
base period: the threshold of a very warm day.

## hddheatn

How much heating a place needs: the sum, over the year, of how far the daily mean
temperature (TM) falls below a base temperature, 18 °C by default.

## cddcoldn

How much cooling a place needs: the sum, over the year, of how far the daily mean
temperature (TM) rises above a base temperature, 18 °C by default.

## gddgrown

The warmth available for crops to grow: the sum, over the year, of how far the daily mean
temperature (TM) rises above a base temperature, 10 °C by default.

## cdd

The largest number of days in a row with less than 1 mm of precipitation.

Read with care: a spell that crosses the end of a year counts in the year it ends, so CDD
can be longer than a year, with the years before written as missing. Read CDD with care
in dry climates.

## cwd

The largest number of days in a row with at least 1 mm of precipitation.

Read with care: a spell that crosses the end of a year counts in the year it ends, so CWD
can be longer than a year, with the years before written as missing.

## r10mm

The number of days with at least 10 mm of precipitation.

## r20mm

The number of days with at least 20 mm of precipitation.

## rx1day

The largest precipitation total on a single day of each year or month.

## rx5day

The largest precipitation total over 5 days in a row in each year or month.

## prcptot

The total precipitation of the wet days, those with at least 1 mm, in each year or month.

## sdii

The mean precipitation on a wet day: the year's wet-day total divided by the number of wet
days (at least 1 mm).

## r95p

The year's precipitation on very wet days: days wetter than the 95th percentile of the
wet days in the base period.

## r99p

The year's precipitation on extremely wet days: days wetter than the 99th percentile of
the wet days in the base period.

## r95ptot

The share of the year's wet-day total that falls on very wet days: R95p as a percentage
of PRCPTOT.

R95p is divided by PRCPTOT of the same year and multiplied by 100.

## r99ptot

The share of the year's wet-day total that falls on extremely wet days: R99p as a
percentage of PRCPTOT.

R99p is divided by PRCPTOT of the same year and multiplied by 100.

## rxdday

The largest precipitation total over d days in a row in each year or month. You choose d.

Rx1day and Rx5day are always calculated as well.

## rnnmm

The number of days with at least nn mm of precipitation. You choose nn.

R10mm and R20mm are always calculated as well.

## txdtnd

The number of times in a year that both TX and TN are above their 95th percentile for d
days in a row. You choose d, from 2 to 10.

## txbdtnbd

The number of times in a year that both TX and TN are below their 5th percentile for d
days in a row. You choose d, from 2 to 10.

## hw

Heatwaves of three or more days in a row when TX (or TN) is above its 90th percentile,
over the extended summer: how many there were, how long and how hot.

The percentiles come from a 15-day window in the base period. Heatwaves are counted over
the extended summer only: November to March in the Southern Hemisphere, May to September
in the Northern. For each year: the number of heatwaves (HWN), the days in them (HWF),
the longest (HWD), their mean temperature (HWM) and the peak temperature of the hottest
(HWA).

Read with care: a year without heatwaves has HWN and HWF of 0 and the others missing. In
the Southern Hemisphere the last year is missing, since its summer is incomplete.

## hwEHF

Heatwaves measured by the excess heat factor (EHF) of Nairn and Fawcett (2015): how many,
how long, how severe and how intense, over the whole year.

The EHF combines how hot the last three days were compared with the 95th percentile of the
daily mean temperature in the base period, and with the month before. Heatwaves are runs
of days with a positive EHF. Besides number, days, longest and mean duration, Climpact
gives the peak and total severity (EHF divided by the 85th percentile of positive EHF in
the base period: above 1 is severe, above 3 extreme) and intensity (raw EHF).

Read with care: intensity is comparable only at the same station; use severity to compare
stations. A heatwave that crosses the new year counts in both years.

## spi

How unusual the precipitation of the past 3, 6 or 12 months is, compared with the same
months in the base period. Below −1 is drier than normal, below −2 extremely dry.

The distribution fitted is a gamma distribution, allowing for months with no precipitation.

Read with care: a base period of at least 30 years gives the most reliable values. SPI is
recommended by WMO for meteorological drought; see the WMO Handbook of drought indicators
and indices (2016) for others.

## spei

How unusual the precipitation minus potential evaporation of the past 3, 6 or 12 months
is, compared with the same months in the base period. Below −1 is drier than normal,
below −2 extremely dry.

Potential evaporation is estimated from TX and TN with Hargreaves' equation, so SPEI
needs them as well as precipitation. The sums are of precipitation minus potential
evaporation, and the distribution fitted is a generalised logistic distribution.

Read with care: a base period of at least 30 years gives the most reliable values. No
drought index is best for every drought; see the WMO Handbook of drought indicators and
indices (2016).

## tmm

The mean of the daily mean temperature (TM) over each year or month.

## txm

The mean of the daily maximum temperature (TX) over each year or month.

## tnm

The mean of the daily minimum temperature (TN) over each year or month.
