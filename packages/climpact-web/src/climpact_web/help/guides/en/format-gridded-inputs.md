title: Gridded input files
summary: CF-compliant netCDF files of daily maximum and minimum temperature and precipitation, on a latitude and longitude grid: one file for all three variables, a file for each, or a variable split along time across many.

``` { #example }
$ ncdump -h tasmax_day_1991-2010.nc
dimensions:
	time = UNLIMITED ; // (7305 currently)
	lat = 19 ;
	lon = 24 ;
variables:
	double time(time) ;
		time:units = "days since 1850-01-01" ;
		time:calendar = "standard" ;
	float tasmax(time, lat, lon) ;
		tasmax:units = "K" ;
		tasmax:_FillValue = 1.e+20f ;
```

## Variables {#variables}

| Variable | Usual name | Units |
| --- | --- | --- |
| Maximum temperature (TX) | `tasmax` | K, or °C (`degC`, `C`, `degrees_C`) |
| Minimum temperature (TN) | `tasmin` | the same as TX |
| Precipitation (PR) | `pr` | kg m⁻² d⁻¹ (mm per day), or kg m⁻² s⁻¹ |

Each variable has time, latitude (Y) and longitude (X) dimensions. Give the name of each
variable as it is in the files (`--tmax`, `--tmin` and `--prec` on the
[command line](guide:command-line#gridded-indices)). Missing values follow the
`missing_value` or `_FillValue` attribute.

## Files and time {#files}

- A variable may be in one file, or split along time across several, one per year or
  decade as AGCD, ERA5 and CMIP6 come; Climpact joins them in the order of their first day.
- The files of a variable must have the same grid, calendar and units, with no day in two
  files and none missing between one file and the next.
- One file may hold all three variables. The three variables must share their time axis.
- Up to 200 files on this site.

## Calendars {#calendars}

The standard, `noleap` (`365_day`) and `360_day` calendars are supported. `ncdump -h`
shows a file's variables, units and calendar; NCO (`ncrename`, `ncatted`) and CDO help fix
names and units. ERA5's precipitation in metres is not read: convert it to kg m⁻² d⁻¹
first.

## Sample grid {#sample}

Climpact for R's sample grid, `climpact.sampledata.gridded.1991-2010.nc` (24 by 19 cells
over Australia, 1991 to 2010), is a quick test. How to run a grid and read its results is
in [Gridded data](guide:gridded).
