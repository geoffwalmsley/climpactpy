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
