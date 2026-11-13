"""Example climpactpy plugin: one QC, one homogeneity and one index module.

- ``example_qc`` lists, per year, the days with TX above 35 degC (``qc/example_hot_days``).
- ``example_shift`` "detects" a break in TX on 1 January of the middle year, writes it to
  ``homogeneity/example_breaks`` and returns TX before the break raised by 1 degC, so the
  indices are calculated from adjusted data.
- ``example_indices`` writes the annual mean of TX (``indices/example_txmean_ANN``).

Entry points may name a class (called with no arguments) or a module object; the QC and
index modules here are classes, the homogeneity module an object.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from climpact.io.output_files import FileFormat, with_file_format
from climpact.modules import HomogeneityResult

ADJUSTMENT = 1.0


class HotDaysQC:
    name = "example_qc"

    def build(self, run, tables):
        tx = run.data["tasmax"]
        hot = (tx > 35).groupby("time.year").sum()
        table = pd.DataFrame({"Year": hot["year"].values, "Days": hot.values.astype(float)})
        return {"qc/example_hot_days": with_file_format(table, FileFormat("Days with TX > 35"))}


class Shift:
    name = "example_shift"

    def homogenise(self, run, tables):
        years = run.data["time.year"].values
        break_year = int((years[0] + years[-1] + 1) // 2)
        before = years < break_year
        adjusted = run.data.copy()
        adjusted["tasmax"] = run.data["tasmax"].where(~before, run.data["tasmax"] + ADJUSTMENT)
        adjusted["tas"] = (adjusted["tasmax"] + adjusted["tasmin"]) / 2
        breaks = pd.DataFrame(
            {"Date": [f"{break_year}-01-01"], "Variable": ["TX"], "Adjustment": [ADJUSTMENT]}
        )
        fmt = FileFormat("Breaks found and the adjustment applied before them", sep=",")
        return HomogeneityResult(
            tables={"homogeneity/example_breaks": with_file_format(breaks, fmt)},
            data=adjusted,
        )


SHIFT = Shift()


class TXMeanIndex:
    name = "example_indices"

    def build(self, run, tables):
        mean = run.data["tasmax"].groupby("time.year").mean()
        table = pd.DataFrame(
            {"time": mean["year"].values.astype(float), "example_txmean": np.round(mean.values, 3)}
        )
        return {"indices/example_txmean_ANN": with_file_format(table, FileFormat("Annual mean TX"))}
