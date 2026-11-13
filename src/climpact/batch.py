"""Batch processing: many stations from one metadata file.

Ports Climpact's batch mode (``climpact.batch.stations.r`` and ``server/batch_stations.R``).
The metadata file is R's, read unchanged: a header row, then one row per station with 12
whitespace-separated columns::

    station_file latitude longitude wsdin csdin Tb_HDD Tb_CDD Tb_GDD rxnday rnnmm txtn SPEI

``station_file`` is a file name inside the data folder. The station name is the file name
without its last extension, as R's ``strip_file_extension``. The base period applies to
every station. As in R, batch runs calculate no custom index unless one is requested.

Each station is run in its own process and written to ``<out>/<station>/`` exactly as
``climpact run`` writes it. A station that fails is reported in ``<out>/<station>.errors.txt``
(R's error log name) and the rest of the batch carries on.
"""

from __future__ import annotations

import datetime as dt
import multiprocessing
import traceback
from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path

from climpact.config import CustomIndex, IndexParams, StationMetadata

# R's read.file.list.metadata col.names. The header row's own names are not checked.
COLUMNS = (
    "station_file",
    "latitude",
    "longitude",
    "wsdin",
    "csdin",
    "Tb_HDD",
    "Tb_CDD",
    "Tb_GDD",
    "rxnday",
    "rnnmm",
    "txtn",
    "SPEI",
)
_INTEGER_COLUMNS = {"wsdin", "csdin", "rxnday", "txtn", "SPEI"}


class BatchMetadataError(ValueError):
    """The metadata file cannot be read; R's ``read.table`` would stop the whole batch."""


@dataclass(frozen=True)
class BatchStation:
    """One row of the batch metadata file."""

    station_file: str
    latitude: float
    longitude: float
    params: IndexParams
    line: int  # line number in the metadata file, for messages

    @property
    def name(self) -> str:
        return strip_file_extension(self.station_file)

    def metadata(self, base_start: int, base_end: int) -> StationMetadata:
        return StationMetadata(
            name=self.name,
            latitude=self.latitude,
            longitude=self.longitude,
            base_start=base_start,
            base_end=base_end,
        )


@dataclass(frozen=True)
class StationResult:
    """Outcome of one station: the files written, or the error that stopped it."""

    name: str
    station_file: str
    written: int = 0
    skipped: tuple[str, ...] = ()
    error: str | None = None
    error_file: Path | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def strip_file_extension(file_name: str) -> str:
    """File name without its last extension (``a.b.txt`` -> ``a.b``), as R's function."""
    stem, dot, _ = file_name.rpartition(".")
    return stem if dot else file_name


def _number(text: str, column: str, line: int) -> float | int:
    try:
        value = float(text)
    except ValueError:
        raise BatchMetadataError(f"line {line}: {column} must be a number, got {text!r}") from None
    if column in _INTEGER_COLUMNS:
        if not value.is_integer():
            raise BatchMetadataError(f"line {line}: {column} must be a whole number, got {text!r}")
        return int(value)
    return value


def validate_params(params: IndexParams) -> None:
    """Raise ``ValueError`` for parameter values R's ``validate_climdexInputParams`` rejects."""
    problems = []
    if not 1 <= params.wsdi_days <= 10:
        problems.append("WSDId: value must be between 1 and 10")
    if not 1 <= params.csdi_days <= 10:
        problems.append("CSDId value must be between 1 and 10")
    if params.rx_days < 1:
        problems.append("RXnDAY: value must be a positive number")
    if params.txtn_days < 1:
        problems.append("TXdTNd and TXbdTNbd: value must be a positive number")
    if params.rnnmm < 0:
        problems.append("Rnnmm: value must be greater than or equal to zero")
    if params.spei_months < 1:
        problems.append("Custom SPEI/SPI time scale value must be a positive number")
    if problems:
        raise ValueError("\n".join(problems))


def read_batch_metadata(path: str | Path) -> list[BatchStation]:
    """Read R's batch metadata file (``read.file.list.metadata``).

    As ``read.table(header = TRUE)``: fields are separated by any whitespace, the first
    non-blank line is the header, blank lines and ``#`` comments are ignored. A row with
    the wrong number of fields or a non-numeric value is an error for the whole file.
    """
    rows = []
    for number, raw in enumerate(Path(path).read_text().splitlines(), start=1):
        fields = raw.split("#", 1)[0].split()
        if fields:
            rows.append((number, fields))
    if not rows:
        raise BatchMetadataError(f"{path}: no header row")
    stations = []
    for number, fields in rows[1:]:
        if len(fields) != len(COLUMNS):
            raise BatchMetadataError(
                f"{path}, line {number}: {len(fields)} fields, expected {len(COLUMNS)} "
                f"({' '.join(COLUMNS)})"
            )
        values = dict(zip(COLUMNS, fields, strict=True))
        n = {c: _number(values[c], c, number) for c in COLUMNS[1:]}
        params = IndexParams(
            wsdi_days=n["wsdin"],
            csdi_days=n["csdin"],
            rx_days=n["rxnday"],
            txtn_days=n["txtn"],
            hdd_base=n["Tb_HDD"],
            cdd_base=n["Tb_CDD"],
            gdd_base=n["Tb_GDD"],
            rnnmm=n["rnnmm"],
            spei_months=n["SPEI"],
            custom=None,
        )
        stations.append(
            BatchStation(values["station_file"], n["latitude"], n["longitude"], params, number)
        )

    seen: dict[str, BatchStation] = {}
    for station in stations:
        if station.name in seen:
            raise BatchMetadataError(
                f"{path}, lines {seen[station.name].line} and {station.line}: "
                f"{seen[station.name].station_file} and {station.station_file} "
                f"would both write to the station folder {station.name!r}"
            )
        seen[station.name] = station
    return stations


def run_station(
    station_file: str | Path,
    metadata: StationMetadata,
    params: IndexParams,
    out_dir: str | Path,
    date: dt.date | None = None,
) -> tuple[dict[str, Path], list[str]]:
    """Build and write every output for one station, as ``climpact run`` does.

    Returns the files written and the output keys not written (missing in every period).
    """
    from climpact.io.output_files import write_outputs
    from climpact.outputs import build_all
    from climpact.station import load_station

    run = load_station(station_file, metadata, params)
    tables = build_all(run)
    written = write_outputs(tables, metadata, params, out_dir, date)
    return written, sorted(set(tables) - set(written))


def _process(
    station: BatchStation,
    data_dir: Path,
    out_dir: Path,
    base_start: int,
    base_end: int,
    date: dt.date | None,
) -> StationResult:
    """Run one station, turning any exception into a failed result."""
    result = StationResult(station.name, station.station_file)
    try:
        validate_params(station.params)
        path = data_dir / station.station_file
        if not path.is_file():
            raise FileNotFoundError(f"station file not found: {path}")
        written, skipped = run_station(
            path, station.metadata(base_start, base_end), station.params, out_dir, date
        )
    except Exception as exc:  # noqa: BLE001 - reported per station, the batch carries on
        detail = "".join(traceback.format_exception_only(exc)).strip()
        return replace(result, error=detail)
    return replace(result, written=len(written), skipped=tuple(skipped))


def run_batch(
    stations: Iterable[BatchStation],
    data_dir: str | Path,
    out_dir: str | Path,
    base_start: int = 1971,
    base_end: int = 2000,
    custom: CustomIndex | None = None,
    workers: int | None = None,
    date: dt.date | None = None,
    on_result: Callable[[StationResult], None] | None = None,
) -> list[StationResult]:
    """Run every station and write its outputs to ``<out_dir>/<station>/``.

    Stations run in a pool of ``workers`` processes (default: one per CPU, at most one
    per station); ``workers=1`` runs them in this process. A station that fails does not
    stop the others: its error is written to ``<out_dir>/<station>.errors.txt``, and an
    error file left by an earlier run is removed first, as R does. ``custom`` is the
    custom index calculated for every station (R calculates none in batch mode).
    ``on_result`` is called as each station finishes. Results are returned in metadata
    order.
    """
    stations = [replace(s, params=replace(s.params, custom=custom)) for s in stations]
    data_dir, out_dir = Path(data_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for station in stations:
        _error_file(out_dir, station.name).unlink(missing_ok=True)

    args = [(s, data_dir, out_dir, base_start, base_end, date) for s in stations]
    workers = min(workers or multiprocessing.cpu_count(), max(len(stations), 1))
    results: dict[str, StationResult] = {}

    def finish(result: StationResult) -> None:
        if not result.ok:
            path = _error_file(out_dir, result.name)
            path.write_text(result.error + "\n")
            result = replace(result, error_file=path)
        results[result.name] = result
        if on_result:
            on_result(result)

    if workers <= 1:
        for a in args:
            finish(_process(*a))
    else:
        # spawn: the same start method on every platform, and no fork of a process
        # whose numerical libraries may be running threads.
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=workers, mp_context=context) as pool:
            futures = {pool.submit(_process, *a): a[0] for a in args}
            for future in as_completed(futures):
                station = futures[future]
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001 - e.g. a worker killed by the OS
                    detail = "".join(traceback.format_exception_only(exc)).strip()
                    result = StationResult(station.name, station.station_file, error=detail)
                finish(result)
    return [results[s.name] for s in stations]


def _error_file(out_dir: Path, name: str) -> Path:
    return out_dir / f"{name}.errors.txt"
