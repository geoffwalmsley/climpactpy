title: Gridded data
summary: Calculating the indices on gridded netCDF data, such as model output or gridded observations, on your own computer.

## Where it runs

Gridded data are large and take a long time to process, so gridded calculations run only
in the version of Climpact installed on **your own computer**, as in Climpact for R. The
files are read where they are on your disk; nothing is uploaded. They are also available
from the `climpact` command line.

A small grid takes minutes; a national grid over decades can take hours.

## Input files {#input-files}

One to three **CF-compliant netCDF** files with daily:

- maximum temperature, in K, °C (`degC`, `C`, `degrees_C`);
- minimum temperature, in the same units;
- precipitation, in kg m⁻² d⁻¹ (the same as mm per day) or kg m⁻² s⁻¹.

Each variable must be in exactly one file, with time, latitude (Y) and longitude (X)
dimensions, and the files must share their time axis. Give the name of each variable as
it appears in the files, for example `tasmax`, `tasmin` and `pr`. Missing values follow
the `missing_value` or `_FillValue` attribute.

The standard, `noleap` (`365_day`) and `360_day` calendars are supported. `ncdump -h` shows
a file's variables, units and calendar. NCO (`ncrename`, `ncatted`) and CDO help fix names
and units.

Climpact for R's sample grid, `climpact.sampledata.gridded.1991-2010.nc` (24 by 19 cells
over Australia, 1991 to 2010), is a quick test.

## Running a grid {#running-a-grid}

Choose the indices to calculate (all by default; fewer finish sooner), the base period and
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
`r20mm_ANN_climpactpy_historical_NA_1991-2010.nc`. Your institution's name and id, if
given, are written into the files' attributes.

View them with Panoply or Ncview, or read them with Python, R or any netCDF tool.

## Things to know

- SPI and SPEI need a long base period: with 10 years or less, many values are missing.
- Latitude decides the hemisphere of each cell, for the growing season and heatwaves.
- Results match Climpact for R's gridded output. Differences are listed in the technical
  notes that come with the software.
