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
``write.hwEHF.csv`` does the same for the eight EHF heatwave files and the daily EHF and
ECF series (``EHFdaily``, ``ECFdaily``, separated by ``","``), unless HWF is missing in
every year.

SPI and SPEI are written by ``write.precindex.csv`` (``services/write_prec_index.R``):
``time, spi`` or ``time, spei`` with the same header block, one file per scale
(``3month_spi_MON`` ...), all four written unless every value of all four is missing,
so a scale that is missing throughout is still written.
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

# Heatwave files (write.hw.csv, write.hwEHF.csv): written even when missing for every year.
_HEATWAVE_FILE = re.compile(
    r"^((TX90|TN90)-HW[MANDF]|EHF-HW(PS|PI|LS|LI|D|MD|N|F))_ANN$|^(EHF|ECF)daily$"
)
_HEATWAVE_ASPECTS = {
    "HWM": "magnitude",
    "HWA": "amplitude",
    "HWN": "number",
    "HWD": "duration",
    "HWF": "frequency",
}

# SPI/SPEI files (write.precindex.csv): written even when missing in every month.
_PRECINDEX_FILE = re.compile(r"^\d+month_(spi|spei)_MON$")
# Description line of the SPI/SPEI files (the header passed by calculate.spi/spei).
_PRECINDEX_DESCRIPTIONS = {
    "spi": "Standardised Precipitation Index",
    "spei": "Standardised Precipitation-Evapotranspiration Index",
}

# Descriptions written by write.hwEHF.csv (the daily ones say 29 February is omitted;
# it is not).
_EHF_DESCRIPTIONS = {
    "EHF-HWPS_ANN": "Heatwave peak severity (HWPS): Mean of the maximum severity of each EHF"
    " heatwave.",
    "EHF-HWPI_ANN": "Heatwave peak intensity (HWPI): Mean of the maximum intensity of each EHF"
    " heatwave.",
    "EHF-HWLS_ANN": "Heatwave load severity (HWLS): Sum of daily EHF heatwave severities.",
    "EHF-HWLI_ANN": "Heatwave load intensity (HWLI): Sum of daily EHF heatwave intensities.",
    "EHF-HWD_ANN": "Heatwave duration (HWD): Duration of the longest EHF heatwave.",
    "EHF-HWMD_ANN": "Heatwave mean duration (HWMD): Mean EHF heatwave duration.",
    "EHF-HWN_ANN": "Heatwave number (HWN): Number of EHF heatwaves.",
    "EHF-HWF_ANN": "Heatwave frequency (HWF): Number of days contributing to EHF heatwaves.",
    "EHFdaily": "EHF daily values. Note that 29th February is omitted from this calculation.",
    "ECFdaily": "ECF daily values. Note that 29th February is omitted from this calculation.",
}

# Separator between fields of the header row and data rows, by output key.
# write.index.csv uses ", "; write.NA.statistics uses ",".
# write.hwEHF.csv writes the daily EHF and ECF files with ",".
# The trend file is written with cat(paste(..., sep = ",")).
_SEPARATORS = {
    "qc/nastatistics": ",",
    "indices/EHFdaily": ",",
    "indices/ECFdaily": ",",
    "trend/trend": ",",
}

# Description line of files not written by write.index.csv. ``None``: no header block.
_DESCRIPTIONS: dict[str, str | None] = {
    "qc/nastatistics": "",
    "thres/thres": None,
    "trend/trend": "Linear trend statistics",
}

# Missing-value token where it isn't write.index.csv's -99.9. quality_control_checks.R
# writes thres.csv with a plain write.table(na = "NA"); the trend file pastes NA as "NA".
_NA_TOKENS = {"thres/thres": "NA", "trend/trend": "NA"}


@cache
def _index_definitions() -> tuple[dict[str, str], ...]:
    text = resources.files("climpact.data").joinpath("climate.indices.csv").read_text()
    return tuple(csv.DictReader(text.splitlines(), delimiter="\t"))


def index_files(
    params: IndexParams, special: bool = False
) -> list[tuple[str, str, str, str | None, str]]:
    """The index files ``index.calc`` writes, in the order of ``climate.indices.csv``.

    One ``(short name, output name, file suffix, frequency, definition)`` per row, apart
    from the rows written by their own functions (``hw``, ``hwEHF``, ``spei``, ``spi``),
    which are included as they are in the file when ``special`` is true.
    The output name and definition include the parameter value for parameterised
    indices (``r30mm``, ``rx3day``, ...); ``frequency`` is ``"annual"``, ``"monthly"`` or
    ``None`` (``tx95t``).
    """
    n = format_r_number
    out = []
    for row in _index_definitions():
        short = name = row["Short.name"]
        definition = row["Definition"]
        flag = row["Annual.flag"]
        frequency = {"T": "annual", "F": "monthly"}.get(flag)
        suffix = "DAY" if name == "tx95t" else {"T": "ANN", "F": "MON"}.get(flag, "NA")
        if name in _NOT_INDEX_FILES:
            if special:
                out.append((short, name, suffix, frequency, definition))
            continue
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
        out.append((short, name, suffix, frequency, definition))
    return out


def index_descriptions(params: IndexParams) -> dict[str, str]:
    """``Description`` line of each index file, keyed by file name (e.g. ``fd_ANN``).

    Follows ``index.calc``: the definition column of ``climate.indices.csv``, replaced
    for parameterised indices by a definition that includes the parameter value.
    """
    n = format_r_number
    out = {f"{name}_{suffix}": definition for _, name, suffix, _, definition in index_files(params)}

    # write.hw.csv: "TX90 heatwave magnitude (HWM)".
    for definition in ("TX90", "TN90"):
        for short, aspect in _HEATWAVE_ASPECTS.items():
            out[f"{definition}-{short}_ANN"] = f"{definition} heatwave {aspect} ({short})"

    out.update(_EHF_DESCRIPTIONS)

    # calculate.spi, calculate.spei: 3, 6, 12 months and the custom scale.
    for scale in (3, 6, 12, params.spei_months):
        for index, description in _PRECINDEX_DESCRIPTIONS.items():
            out[f"{scale}month_{index}_MON"] = description

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
    ``write.index.csv`` does, apart from the heatwave, SPI and SPEI files (see the module
    docstring).
    Returns the path written for each key.
    """
    descriptions = index_descriptions(params)
    written = {}
    for key, table in tables.items():
        folder, name = key.split("/", 1)
        if folder == "indices":
            always_written = _HEATWAVE_FILE.match(name) or _PRECINDEX_FILE.match(name)
            if is_all_missing(table) and not always_written:
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
