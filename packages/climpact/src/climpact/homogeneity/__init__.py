"""Homogeneity break detection (#34).

- :mod:`.detect`: the built-in homogeneity module ``detect`` (``--homogeneity detect``),
  which runs the tests below on a station's series and writes the ``homogeneity/breaks``
  and ``homogeneity/tests`` tables. It reports breaks and does not adjust the data.
- :mod:`.series`: the series tested (annual and monthly mean TX and TN, log annual PRCP).
- :mod:`.pettitt`, :mod:`.snht`: Pettitt's test and the SNHT, as R's ``trend`` package,
  with :mod:`.segmentation` for several breaks.
- :mod:`.rhtests`: RHtestsV4's PMFred and PMTred.

The submodules are imported on use, so reading the series does not load the tests.
"""
