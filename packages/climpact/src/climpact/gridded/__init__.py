"""Gridded (netCDF) data: reading CF netCDF grids, and Climpact's gridded outputs.

- :mod:`climpact.gridded.io` reads tasmax, tasmin and pr from one or more CF netCDF
  files as climdex.pcic.ncdf does (masking, scaling and unit conversion), lazily and in
  blocks of cells, so that a grid of any size is processed in bounded memory.
- :mod:`climpact.gridded.thresholds` computes the base-period thresholds of every cell
  and writes them in the layout of ``climpact.ncdf.thresholds.wrapper.r``.
- :mod:`climpact.gridded.indices` computes the indices of every cell and writes them in
  the layout of ``climpact.ncdf.wrapper.r``.
"""

from climpact.gridded.indices import write_grid_indices
from climpact.gridded.io import GriddedInput, open_grid
from climpact.gridded.thresholds import cell_thresholds, write_grid_thresholds

__all__ = [
    "GriddedInput",
    "cell_thresholds",
    "open_grid",
    "write_grid_indices",
    "write_grid_thresholds",
]
