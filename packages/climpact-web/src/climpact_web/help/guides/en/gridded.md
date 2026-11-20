title: Gridded data
summary: Calculating the indices on gridded netCDF data, such as model output or gridded observations, on your own computer.

## Where it runs

Gridded data are large and take a long time to process, so gridded calculations run in
the version of Climpact installed on **your own computer**, as in Climpact for R. New
gridded run lists a folder of your computer: each netCDF file with its daily variables
and dates, read from its header. Tick the files you want, in as many folders as you need,
or paste their paths, where `*` and `?` match many files (`/data/agcd/tmax_*.nc`). They
are read where they are on your disk and never changed. A hosted Climpact offers gridded
runs only if its operator has switched them on, and then by upload only, up to the size
limit the page states. They are also available from the `climpact` command line.

The calculation runs in the background: you can close the page and come back to the run
from [Gridded](url:gridded:start), in the header, which lists your runs: their grid,
period, thresholds, what they calculate, how far they have got and how long they are
kept.

A small grid takes minutes; a national grid over decades can take hours.

## Input files {#input-files}

**CF-compliant netCDF** files (up to 200) with daily:

- maximum temperature, in K, °C (`degC`, `C`, `degrees_C`);
- minimum temperature, in the same units;
- precipitation, in kg m⁻² d⁻¹ (the same as mm per day) or kg m⁻² s⁻¹.

Each variable has time, latitude (Y) and longitude (X) dimensions. It may be in one file,
or split along time across several, one per year or decade as AGCD, ERA5 and CMIP6 come:
Climpact joins them in the order of their first day. The files of a variable must have the
same grid, calendar and units, with no day in two files and none missing between one file
and the next; set-up names the two files when they do not. One file may hold all three
variables. The three variables must share their time axis. Give the name of each variable as
it appears in the files, for example `tasmax`, `tasmin` and `pr`. Missing values follow
the `missing_value` or `_FillValue` attribute.

The standard, `noleap` (`365_day`) and `360_day` calendars are supported. `ncdump -h` shows
a file's variables, units and calendar. NCO (`ncrename`, `ncatted`) and CDO help fix names
and units.

Climpact for R's sample grid, `climpact.sampledata.gridded.1991-2010.nc` (24 by 19 cells
over Australia, 1991 to 2010), is a quick test. **Use the sample grid** on Gridded (**Try the sample grid** on New
gridded run) loads a 3 by 4 cut of it in one click.

After you choose the files, Climpact shows what each holds (variables, units, calendar,
grid and dates) and guesses which variable is which; check the guess before you go on.
Problems, such as units it cannot read or files with different dates, are shown there,
before anything is calculated.

## Running a grid {#running-a-grid}

Choose what to calculate: the **indices**, a **thresholds file only**, or a thresholds
file and then the indices. Then choose the indices (all by default; fewer finish sooner;
the heatwave, SPI and SPEI indices take most of the time), the base period and
the index settings, as for a station (see [The indices](guide:indices#settings)). On a
computer with several processor cores, more threads finish sooner. If the computer runs
short of memory, lower the number of values read at once.

There are no quality checks for gridded data. Check your data before calculating.

## Thresholds from another period {#thresholds-from-another-period}

Percentile indices need a base period inside the data. To calculate them for data with no
base-period years, such as a projection for 2050-2080, use the thresholds of another run:

1. calculate a **thresholds file** from the historical files, with the base period you want
   (for example 1981-2010);
2. calculate the indices of the future files, giving that thresholds file.

Both runs then use the same thresholds, so the indices are comparable. If your data cover
the base period, you do not need a thresholds file.

## Output files {#output-files}

One netCDF file per index and time scale, named in the CMIP5 style:
`<index>_<ANN or MON>_<model>_<scenario>_<run>_<first year>-<last year>.nc`, for example
`r20mm_ANN_climpact_historical_NA_1991-2010.nc`. Your institution's name and id, if
given, are written into the files' attributes.

Each run has its own page, with its name (Rename changes it), what it was made from, and
three tabs:

- **Map** maps an index: choose the index, the year (or month) and, for SPI and SPEI, the
  time scale. Choose a cell on the map, or its latitude and longitude, to see its values
  over time. The map and the series each have a table and a CSV file. While the run is
  calculating, Map shows how far it has got.
- **Files** lists every file, grouped by theme (or by the variable an index needs, or its
  frequency), with a zip of each group and of them all. For a big run, "the links as a
  text file" lists every file's address for a download tool, such as `wget -i`; the
  links work without this browser for as long as the run is kept. `run.json` records the
  settings, the software versions and a checksum of each input file; `climpact.log` when
  each part ran and any errors.
- **Set-up** shows the settings; changing them and starting again calculates the run
  again.

**Forget this run** deletes the run and its results (files read from your computer are
never touched).

View the files with Panoply or Ncview, or read them with Python, R or any netCDF tool.

## Things to know

- SPI and SPEI need a long base period: with 10 years or less, many values are missing.
- Latitude decides the hemisphere of each cell, for the growing season and heatwaves.
- Results match Climpact for R's gridded output. Differences are listed in the technical
  notes that come with the software.
