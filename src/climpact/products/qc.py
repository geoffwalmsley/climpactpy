"""Quality-control output tables."""

from __future__ import annotations

import pandas as pd

from climpact.outputs import register
from climpact.station import StationRun


@register("qc/nastatistics")
def na_statistics(run: StationRun) -> pd.DataFrame:
    """Missing days per year for each variable (R ``write.NA.statistics``)."""
    ds = run.data
    missing = ds[["pr", "tasmax", "tasmin"]].isnull().groupby("time.year").sum()
    return pd.DataFrame(
        {
            "Year": missing["year"].to_numpy().astype(float),
            "Prec": missing["pr"].to_numpy().astype(float),
            "TX": missing["tasmax"].to_numpy().astype(float),
            "TN": missing["tasmin"].to_numpy().astype(float),
        }
    )
