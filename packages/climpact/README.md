# climpact

Climpact for Python: a Python port of [Climpact](https://github.com/ARCCSS-extremes/climpact),
the R software for calculating indices of daily climate extremes (the ETCCDI and ET-SCI
indices) for station and gridded data. It reproduces the R Climpact output files, checked
against R reference runs. It is not the R Climpact itself: its outputs and plots name
themselves "Climpact for Python" with the version of R Climpact they port.

```sh
pip install climpact            # the core: indices, quality control, CSV and netCDF outputs
pip install 'climpact[plots]'   # with matplotlib, for the plots and the PDF report
```

Python 3.12 or later. The package is imported as `climpact` and installs the `climpact`
command:

```sh
climpact --version
climpact run station.txt --out outputs --lat -33.86 --lon 151.21
climpact --help
```

The browser app is a separate package, [climpact-web](https://pypi.org/project/climpact-web/).

See the [repository](https://github.com/geoffwalmsley/climpactpy) for usage, and the
[technical notes](https://github.com/geoffwalmsley/climpactpy/blob/main/TECHNICAL.md) for
the parity testing and the differences from R Climpact. Licensed under the GNU GPL,
version 3 or later, like R Climpact.
