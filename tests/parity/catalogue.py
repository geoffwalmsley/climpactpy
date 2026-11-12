"""Catalogue of the R reference outputs and the tolerance tier for each file."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from climpact.compare import Tier

REFERENCE_DIR = Path(__file__).parents[2] / "reference" / "output"
STATION = "sydney_observatory_hill_1936-2015"
RUNS = ("lat0", "sydney")
FOLDERS = ("indices", "thres", "trend")
# Individual QC files that have a tabular format comparable with the reader.
QC_FILES = ("nastatistics",)

STANDARDISED = "standardised values (using all years)"

# Files whose index values are counts, extremes or event lengths: compared exactly.
# Their standardised-anomaly column is still compared with the CLOSE tier.
_EXACT = re.compile(
    r"^(fd|tnlt2|tnltm2|tnltm20|id|su|tr|txge30|txge35|tmge5|tmge10|tmlt5|tmlt10"
    r"|r10mm|r20mm|r\d+mm|TNgt0|txx|tnn|tnx|txn|rx1day|cdd|cwd|gsl"
    r"|wsdi\d*|csdi\d*|tx\d+tn\d+|txb\d+tnb\d+"
    r"|(TX90|TN90|EHF)-(HWN|HWF|HWD))_(ANN|MON)$"
)
_FITTED = re.compile(r"^\d+month_(spi|spei)_MON$")


@dataclass(frozen=True)
class ReferenceFile:
    run: str
    folder: str
    name: str  # file stem without the station prefix, e.g. "fd_ANN"

    @property
    def key(self) -> str:
        """Builder key, e.g. ``indices/fd_ANN``."""
        return f"{self.folder}/{self.name}"

    @property
    def path(self) -> Path:
        return REFERENCE_DIR / self.run / STATION / self.folder / f"{STATION}_{self.name}.csv"

    @property
    def tier(self) -> Tier:
        if _FITTED.match(self.name):
            return Tier.FITTED
        if self.folder == "qc" or _EXACT.match(self.name):
            return Tier.EXACT
        return Tier.CLOSE

    @property
    def column_tiers(self) -> dict[str, Tier]:
        return {STANDARDISED: Tier.CLOSE}

    @property
    def id(self) -> str:
        return f"{self.run}/{self.key}"


def reference_files() -> list[ReferenceFile]:
    files = []
    for run in RUNS:
        for folder in FOLDERS:
            for path in sorted((REFERENCE_DIR / run / STATION / folder).glob("*.csv")):
                name = path.stem.removeprefix(f"{STATION}_")
                files.append(ReferenceFile(run=run, folder=folder, name=name))
        for name in QC_FILES:
            files.append(ReferenceFile(run=run, folder="qc", name=name))
    return files
