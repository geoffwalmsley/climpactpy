"""Station metadata and user-set index parameters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

CustomVariable = Literal["TX", "TN", "TM", "PR", "DTR"]
CustomOperator = Literal[">", ">=", "<", "<="]


@dataclass(frozen=True)
class StationMetadata:
    """Station description, as entered in step 1 of the Climpact R app."""

    name: str
    latitude: float = 0.0
    longitude: float = 0.0
    base_start: int = 1971
    base_end: int = 2000

    @property
    def northern_hemisphere(self) -> bool:
        # Matches climdex.pcic's `northern.hemisphere = lat > 0`: latitude 0 counts as south.
        return self.latitude > 0


@dataclass(frozen=True)
class CustomIndex:
    """User-defined threshold index, e.g. TN > 0 ("TNgt0")."""

    variable: CustomVariable = "TN"
    operator: CustomOperator = ">"
    threshold: float = 0.0

    @property
    def name(self) -> str:
        op = {">": "gt", ">=": "ge", "<": "lt", "<=": "le"}[self.operator]
        value = int(self.threshold) if float(self.threshold).is_integer() else self.threshold
        return f"{self.variable}{op}{value}"


@dataclass(frozen=True)
class IndexParams:
    """User-set index parameters. Defaults are the Climpact R app defaults."""

    wsdi_days: int = 1
    csdi_days: int = 1
    rx_days: int = 3
    txtn_days: int = 2
    hdd_base: float = 18.0
    cdd_base: float = 18.0
    gdd_base: float = 10.0
    rnnmm: float = 30.0
    spei_months: int = 24
    custom: CustomIndex | None = field(default_factory=CustomIndex)


@dataclass(frozen=True)
class QCParams:
    """Quality-control thresholds, as entered in step 2 of the Climpact R app.

    The defaults are the R app's (``load_data_qc``), also used by the reference runs.
    """

    # fourboxes (qc/outliers): boxplot whisker length, in interquartile ranges.
    iqr_temp: float = 3.0
    iqr_prec: float = 5.0
    # humongous (qc/toolarge): precipitation above prec_max mm or below 0, or a
    # temperature whose absolute value is above temp_max degC.
    prec_max: float = 200.0
    temp_max: float = 50.0
    # flatline_tx/tn (qc/*_flatline): runs of at least this many zero day-to-day changes.
    flatline_days: int = 5
    # jumps_tx/tn (qc/*_jumps): day-to-day changes of at least this many degC.
    jump: float = 20.0
