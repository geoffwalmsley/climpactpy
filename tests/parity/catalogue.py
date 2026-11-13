"""Catalogue of the R reference outputs and the tolerance tier for each file."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from climpact.compare import Tier
from climpact.config import StationMetadata

REFERENCE_DIR = Path(__file__).parents[2] / "reference" / "output"
STATIONS_CSV = REFERENCE_DIR.parent / "stations.csv"


@dataclass(frozen=True)
class Run:
    """One R reference run: a row of reference/stations.csv."""

    name: str  # run name, e.g. "sydney"; outputs are in reference/output/<name>/<station>/
    station_id: str  # GHCN-Daily station id
    station: str  # input file stem and R output folder, e.g. "phoenix_1961-2020"
    latitude: float
    longitude: float
    source: str  # "ghcn", "climpact" (Climpact's sample file) or "synthetic"

    @property
    def qc_only(self) -> bool:
        """Synthetic stations exist to exercise the QC checks: only their ``qc/`` files
        are compared with R."""
        return self.source == "synthetic"

    @property
    def input_path(self) -> Path:
        return REFERENCE_DIR.parent / "input" / f"{self.station}.txt"

    @property
    def output_dir(self) -> Path:
        return REFERENCE_DIR / self.name / self.station

    @property
    def metadata(self) -> StationMetadata:
        return StationMetadata(name=self.station, latitude=self.latitude, longitude=self.longitude)


def _read_runs() -> dict[str, Run]:
    with STATIONS_CSV.open(newline="") as f:
        return {
            row["run"]: Run(
                name=row["run"],
                station_id=row["id"],
                station=f"{row['name']}_{row['start']}-{row['end']}",
                latitude=float(row["lat"]),
                longitude=float(row["lon"]),
                source=row["source"],
            )
            for row in csv.DictReader(f)
        }


RUNS = _read_runs()
# The Climpact sample station, used by the lat0 and sydney runs and by unit tests.
STATION = RUNS["sydney"].station
FOLDERS = ("indices", "thres", "trend")
# QC files compared with R.
QC_FILES = (
    "nastatistics",
    "tmaxmin",
    "toolarge",
    "duplicates",
    "tx_jumps",
    "tn_jumps",
    "tx_flatline",
    "tn_flatline",
    "outliers",
)

STANDARDISED = "standardised values (using all years)"

# Files whose index values are counts, extremes or event lengths: compared exactly.
# Their standardised-anomaly column is still compared with the CLOSE tier.
_EXACT = re.compile(
    r"^(fd|tnlt2|tnltm2|tnltm20|id|su|tr|txge30|txge35|tmge5|tmge10|tmlt5|tmlt10"
    r"|r10mm|r20mm|r\d+mm|TNgt0|txx|tnn|tnx|txn|rx1day|cdd|cwd|gsl"
    r"|wsdi\d*|csdi\d*|tx\d+tn\d+|txb\d+tnb\d+"
    r"|(TX90|TN90|EHF)-(HWN|HWF|HWD))_(ANN|MON)$"
)

# Reference files that fail because of a filed bug, keyed by a pattern on ``ReferenceFile.id``.
# They are strict xfails: once the bug is fixed the test XPASSes, which fails, so remove the entry.
KNOWN_BUGS: dict[re.Pattern[str], str] = {
    # re.compile(r"^oxford/indices/dtr_(ANN|MON)$"): "known bug #40: ...",
}


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
        station = RUNS[self.run].station
        return REFERENCE_DIR / self.run / station / self.folder / f"{station}_{self.name}.csv"

    @property
    def tier(self) -> Tier:
        if self.folder == "qc" or _EXACT.match(self.name):
            return Tier.EXACT
        return Tier.CLOSE

    @property
    def column_tiers(self) -> dict[str, Tier]:
        return {STANDARDISED: Tier.CLOSE}

    @property
    def id(self) -> str:
        return f"{self.run}/{self.key}"

    @property
    def known_bug(self) -> str | None:
        """Reason this file is expected to fail, if it is listed in ``KNOWN_BUGS``."""
        return next((reason for pat, reason in KNOWN_BUGS.items() if pat.search(self.id)), None)


def reference_files() -> list[ReferenceFile]:
    files = []
    for run in RUNS.values():
        for folder in () if run.qc_only else FOLDERS:
            for path in sorted((run.output_dir / folder).glob("*.csv")):
                name = path.stem.removeprefix(f"{run.station}_")
                files.append(ReferenceFile(run=run.name, folder=folder, name=name))
        for name in QC_FILES:
            if (run.output_dir / "qc" / f"{run.station}_{name}.csv").exists():
                files.append(ReferenceFile(run=run.name, folder="qc", name=name))
    return files
