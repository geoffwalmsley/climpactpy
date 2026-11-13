"""A station run: data, metadata and index parameters together."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import pandas as pd
import xarray as xr

from climpact.config import IndexParams, QCParams, StationMetadata
from climpact.io.station import merged_rows, read_station_file, station_dataset
from climpact.thresholds import Thresholds, compute_thresholds


@dataclass
class StationRun:
    """Everything needed to compute Climpact outputs for one station."""

    data: xr.Dataset
    metadata: StationMetadata
    params: IndexParams = field(default_factory=IndexParams)
    qc: QCParams = field(default_factory=QCParams)
    # The rows the QC checks run on (io.station.merged_rows): duplicated dates keep every
    # row. None: rebuilt from ``data``, which has one row per date.
    qc_rows: pd.DataFrame | None = field(default=None, repr=False)

    @cached_property
    def thresholds(self) -> Thresholds:
        """Base-period percentile thresholds, computed on first use and cached.

        Raises :class:`climpact.thresholds.InsufficientBaseData` when the base period
        has too little data.
        """
        return compute_thresholds(self.data, self.metadata.base_start, self.metadata.base_end)

    @cached_property
    def rows(self) -> pd.DataFrame:
        """The rows the QC checks run on: ``date``, ``prcp``, ``tmax``, ``tmin``."""
        if self.qc_rows is not None:
            return self.qc_rows
        ds = self.data
        days = ds.sel(time=slice(ds.attrs.get("first_date"), ds.attrs.get("last_date")))
        return pd.DataFrame(
            {
                "date": pd.DatetimeIndex(days.time.values),
                "prcp": days["pr"].values,
                "tmax": days["tasmax"].values,
                "tmin": days["tasmin"].values,
            }
        )


def load_station(
    path: str | Path,
    metadata: StationMetadata,
    params: IndexParams | None = None,
    qc: QCParams | None = None,
) -> StationRun:
    """Read a station text file and prepare it for index calculation."""
    df = read_station_file(path)
    return StationRun(
        data=station_dataset(df, metadata),
        metadata=metadata,
        params=params or IndexParams(),
        qc=qc or QCParams(),
        qc_rows=merged_rows(df),
    )
