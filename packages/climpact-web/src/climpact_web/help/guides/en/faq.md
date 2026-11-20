title: Questions and troubleshooting
summary: Answers to common questions, and what to do when something does not work.

## My file is refused {#file-refused}

Climpact lists each problem with the line of your file. The usual causes are a value
missing from a line, a blank or a code such as `N/A` instead of -99.9 (`NA` is accepted),
a comma used as the decimal mark, or a spreadsheet loaded instead of text. See
[Common problems](guide:station-file#common-problems).

## Some years have no index value {#years-missing}

A year needs at least 350 days of data (no more than 15 missing) and every month at least
all but 3 days. Look at the missing days per year in the
[quality checks](guide:quality-control#missing-days). See
[Missing data](guide:indices#missing-data).

## TX90p, WSDI and other indices are missing {#percentile-missing}

They need percentile thresholds from the base period. If less than a year of your base
period is in the file, they cannot be calculated. Choose a base period inside your data:
see [Choosing a base period](guide:base-period#coverage).

## CDD or CWD is missing in years with complete data {#cdd-missing}

A dry or wet spell that continues into the next year is counted in the year it ends, and
the years before are written as missing, so that no day is counted twice. A spell from
January 2000 to December 2002 gives 1,095 days in 2002 and nothing in 2000 and 2001.

## The growing season or heatwaves look wrong {#hemisphere}

Check the latitude: it decides the hemisphere, and with it the season used. Latitude 0
counts as the Southern Hemisphere.

## How long should the base period be? {#base-period-length}

30 years if possible: 1961-1990 for climate change assessment, 1991-2020 for monitoring.
See [Choosing a base period](guide:base-period#which-years-to-choose).

## Is a trend significant? {#trend-significant}

When its lower and upper bounds are both above zero, or both below. The trend file has no
p-value. See [Interpreting trends](guide:trends#confidence-bounds-and-significance).

## Are my results the same as Climpact for R? {#same-as-r}

Yes: the indices, thresholds, trends and quality checks are calculated to give the same
values as Climpact for R 3.4.3, and the files have the same names and layout. The plots are
drawn differently.

## Where is my data kept? {#data-kept}

In the version on your own computer, everything stays on that computer. On a shared
server, your files and results are kept for a few days (the page tells you how long) and
are only visible in your browser session; you can delete them at any time.

## The calculation is slow or seems stuck {#slow}

A station takes about 10 seconds with plots. The station's page shows the progress as it
goes. You can leave it and come back from [Workspaces](url:stations:workspaces). If a calculation stops
unexpectedly, the page says so and offers to try again.

## Can I add my own indices? {#own-indices}

One custom index, counting days above or below a value you choose, is in the Index
settings, under a station's Your inputs: see [Your own index](guide:indices#your-own-index). New indices for the ET-SCI set are
agreed by the expert team.

## Where can I use the results? {#use-results}

The index files are CSV, so any spreadsheet or statistics program reads them. Remove the
-99.9 missing values before calculating with them.
