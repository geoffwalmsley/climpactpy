"""A station run: data, metadata and index parameters together."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import xarray as xr

from climpact.config import IndexParams, StationMetadata
from climpact.io.station import read_station_file, station_dataset
from climpact.thresholds import Thresholds, compute_thresholds


@dataclass
class StationRun:
    """Everything needed to compute Climpact outputs for one station."""

    data: xr.Dataset
    metadata: StationMetadata
    params: IndexParams = field(default_factory=IndexParams)

    @cached_property
    def thresholds(self) -> Thresholds:
        """Base-period percentile thresholds, computed on first use and cached.

        Raises :class:`climpact.thresholds.InsufficientBaseData` when the base period
        has too little data.
        """
        return compute_thresholds(self.data, self.metadata.base_start, self.metadata.base_end)


def load_station(
    path: str | Path,
    metadata: StationMetadata,
    params: IndexParams | None = None,
) -> StationRun:
    """Read a station text file and prepare it for index calculation."""
    df = read_station_file(path)
    return StationRun(
        data=station_dataset(df, metadata),
        metadata=metadata,
        params=params or IndexParams(),
    )
