"""Write a run's output tables as Climpact's files, folders and metadata headers.

R writes each station's outputs to ``<out>/<station>/{indices,qc,thres,trend}/`` as
``<station>_<name>.csv`` (``models/outputFolders.R``). Index files carry the index
definition from ``server/climate.indices.csv`` as their ``Description`` line, with the
parameterised definitions ``index.calc`` builds (``services/calculate_indices.R``).
``write.index.csv`` writes no file when an index is missing for every period.

The heatwave files are written by ``write.hw.csv`` (``services/write_indices.R``) with
the same header block and missing-value token but no standardised-anomaly column. It
writes all ten Tx90/Tn90 files whenever any of them has a value, so a heatwave file
can be missing for every year; the products leave out the whole group otherwise.
"""

from __future__ import annotations

import csv
import datetime as dt
import re
from functools import cache
from importlib import resources
from pathlib import Path

import pandas as pd

from climpact.config import IndexParams, StationMetadata
from climpact.io.climpact_csv import MISSING_TOKEN, format_r_number, write_climpact_csv

# Climpact R version whose output files this port reproduces (``software_id``).
CLIMPACT_VERSION = "3.4.3"

# Rows of climate.indices.csv written by their own functions rather than write.index.csv.
_NOT_INDEX_FILES = {"hw", "hwEHF", "spei", "spi"}

# Heatwave files (write.hw.csv): written even when missing for every year.
_HEATWAVE_FILE = re.compile(r"^(TX90|TN90)-HW[MANDF]_ANN$")
_HEATWAVE_ASPECTS = {
    "HWM": "magnitude",
    "HWA": "amplitude",
    "HWN": "number",
    "HWD": "duration",
    "HWF": "frequency",
}

# Separator between fields of the header row and data rows, by output key.
# write.index.csv uses ", "; write.NA.statistics uses ",".
_SEPARATORS = {"qc/nastatistics": ","}

# Description line of files not written by write.index.csv. ``None``: no header block.
_DESCRIPTIONS: dict[str, str | None] = {"qc/nastatistics": "", "thres/thres": None}

# Missing-value token where it isn't write.index.csv's -99.9. quality_control_checks.R
# writes thres.csv with a plain write.table(na = "NA").
_NA_TOKENS = {"thres/thres": "NA"}


@cache
def _index_definitions() -> tuple[dict[str, str], ...]:
    text = resources.files("climpact.data").joinpath("climate.indices.csv").read_text()
    return tuple(csv.DictReader(text.splitlines(), delimiter="\t"))


def index_descriptions(params: IndexParams) -> dict[str, str]:
    """``Description`` line of each index file, keyed by file name (e.g. ``fd_ANN``).

    Follows ``index.calc``: the definition column of ``climate.indices.csv``, replaced
    for parameterised indices by a definition that includes the parameter value.
    """
    n = format_r_number
    out = {}
    for row in _index_definitions():
        name, definition = row["Short.name"], row["Definition"]
        if name in _NOT_INDEX_FILES:
            continue
        flag = row["Annual.flag"]
        frequency = {"T": "annual", "F": "monthly"}.get(flag)
        suffix = "DAY" if name == "tx95t" else {"T": "ANN", "F": "MON"}.get(flag, "NA")
        match name:
            case "rnnmm":
                name = f"r{n(params.rnnmm)}mm"
                definition = f"Number of days when precipitation >= {n(params.rnnmm)}"
            case "wsdid":
                name = f"wsdi{params.wsdi_days}"
                definition = (
                    f"Annual number of days with at least {params.wsdi_days} consecutive days"
                    " when TX > 90th percentile"
                )
            case "csdid":
                name = f"csdi{params.csdi_days}"
                definition = (
                    f"Annual number of days with at least {params.csdi_days} consecutive days"
                    " when TN < 10th percentile"
                )
            case "txdtnd":
                d = params.txtn_days
                name = f"tx{d}tn{d}"
                definition = (
                    f"Number of {d} consecutive days where both TX > 95th percentile"
                    " and TN > 95th percentile"
                )
            case "txbdtnbd":
                d = params.txtn_days
                name = f"txb{d}tnb{d}"
                definition = (
                    f"Number of {d} consecutive days where both TX < 5th percentile"
                    " and TN < 5th percentile"
                )
            case "rxdday":
                name = f"rx{params.rx_days}day"
                definition = f"Maximum {frequency} {params.rx_days}-day precipitation total"
            case "hddheatn":
                name = f"hddheat{n(params.hdd_base)}"
                definition = f"Annual sum of {n(params.hdd_base)} - TM"
            case "cddcoldn":
                name = f"cddcold{n(params.cdd_base)}"
                definition = f"Annual sum of TM - {n(params.cdd_base)}"
            case "gddgrown":
                name = f"gddgrow{n(params.gdd_base)}"
                definition = f"Annual sum of TM - {n(params.gdd_base)}"
        out[f"{name}_{suffix}"] = definition

    # write.hw.csv: "TX90 heatwave magnitude (HWM)".
    for definition in ("TX90", "TN90"):
        for short, aspect in _HEATWAVE_ASPECTS.items():
            out[f"{definition}-{short}_ANN"] = f"{definition} heatwave {aspect} ({short})"

    # calculate.custom.index: header "TN > 0", for both frequencies.
    if (spec := params.custom) is not None:
        for suffix in ("ANN", "MON"):
            out[f"{spec.name}_{suffix}"] = f"{spec.variable} {spec.operator} {n(spec.threshold)}"
    return out


def output_path(out_dir: str | Path, station: str, key: str) -> Path:
    """Path R writes output ``key`` (e.g. ``indices/fd_ANN``) to."""
    folder, name = key.split("/", 1)
    return Path(out_dir) / station / folder / f"{station}_{name}.csv"


def is_all_missing(table: pd.DataFrame) -> bool:
    """True when every value apart from the ``time`` column is missing."""
    values = table.drop(columns=["time"], errors="ignore")
    return bool(values.isna().all().all())


def file_metadata(
    metadata: StationMetadata, description: str, date: dt.date | None = None
) -> dict[str, str]:
    """Header values for one file, formatted as R's ``write_header`` does."""
    return {
        "Description": description,
        "Station": metadata.name,
        "Latitude": format_r_number(metadata.latitude),
        "Longitude": format_r_number(metadata.longitude),
        "Base_period": f"{metadata.base_start}-{metadata.base_end}",
        "Climpact_version": CLIMPACT_VERSION,
        "Date_of_calculation": (date or dt.date.today()).isoformat(),
    }


def write_outputs(
    tables: dict[str, pd.DataFrame],
    metadata: StationMetadata,
    params: IndexParams,
    out_dir: str | Path,
    date: dt.date | None = None,
) -> dict[str, Path]:
    """Write output tables (as returned by ``build_all``) as Climpact CSV files.

    Index tables that are missing for every period are skipped, as R's
    ``write.index.csv`` does, apart from the heatwave files (see the module docstring).
    Returns the path written for each key.
    """
    descriptions = index_descriptions(params)
    written = {}
    for key, table in tables.items():
        folder, name = key.split("/", 1)
        if folder == "indices":
            if is_all_missing(table) and not _HEATWAVE_FILE.match(name):
                continue
            try:
                description = descriptions[name]
            except KeyError:
                raise KeyError(f"no description for index file {name!r}") from None
        else:
            try:
                description = _DESCRIPTIONS[key]
            except KeyError:
                raise KeyError(f"no file format defined for output {key!r}") from None
        path = output_path(out_dir, metadata.name, key)
        write_climpact_csv(
            path,
            table,
            None if description is None else file_metadata(metadata, description, date),
            sep=_SEPARATORS.get(key, ", "),
            na=_NA_TOKENS.get(key, MISSING_TOKEN),
        )
        written[key] = path
    return written
