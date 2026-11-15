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
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass, replace
from pathlib import Path
from queue import Empty

from climpact.config import CustomIndex, IndexParams, QCParams, StationMetadata
from climpact.modules import ModuleSelection
from climpact.progress import BatchProgress, Progress, Steps

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
    modules: ModuleSelection | None = None,
    progress: Progress | None = None,
    plots: bool = False,
    zip: bool = False,
    qc: QCParams | None = None,
    plot_title: str | None = None,
    report: bool = False,
    report_path: str | Path | None = None,
) -> tuple[dict[str, Path], list[str]]:
    """Build and write every output for one station, as ``climpact run`` does.

    ``modules`` selects the QC, homogeneity and index modules (default: the built-in
    ones). ``plots`` also draws R's index plots and combined PDF
    (:func:`climpact.plots.write_plots`, needs matplotlib), and ``zip`` then zips the
    station folder to ``<out_dir>/<station>.zip`` (:func:`climpact.plots.zip_station`).
    ``report`` also writes the PDF report (:func:`climpact.report.write_report`, needs
    matplotlib) to ``report_path``, by default ``<out_dir>/<station>_report.pdf``, beside the
    station folder so the zip keeps R's file list.
    ``plot_title`` replaces the station title at the top of every plot;
    ``qc`` holds the quality-control thresholds (default: the R app's, :class:`QCParams`).
    With no index modules (``ModuleSelection(indices=())``) only the QC files are written,
    as the R app's quality-control step does.
    ``progress(stage, step, total)`` is called after each stage: ``read``, the stages of
    :func:`~climpact.modules.pipeline_stages`, ``write``, then with ``plots`` the stages of
    :func:`~climpact.plots.plot_steps`, with ``report`` a ``report`` and with ``zip`` a last
    ``zip`` (see :mod:`climpact.progress`). Returns the files written, keyed by output key
    (plots as ``plots/<name>``, the report as ``report``, the zip file as ``zip``), and the
    output keys not written (missing in every period).
    """
    from climpact.io.output_files import write_outputs
    from climpact.modules import pipeline_stages, resolve, run_pipeline
    from climpact.station import load_station

    if plots or report:
        from climpact.plots import plot_steps, require_matplotlib

        require_matplotlib()  # fail before the run, not after it
    loaded = resolve(modules)
    steps = Steps(progress, 0)
    pipeline_progress = None
    if progress is not None:
        steps.total = len(pipeline_stages(loaded)) + 2
        steps.total += len(plot_steps(params)) if plots else 0
        steps.total += 1 if report else 0
        steps.total += 1 if zip else 0

        def pipeline_progress(stage: str, step: int, _total: int) -> None:
            steps.done(stage)

    run = load_station(station_file, metadata, params, qc)
    steps.done("read")
    tables = run_pipeline(run, loaded, pipeline_progress).tables
    written = write_outputs(tables, metadata, params, out_dir, date)
    skipped = sorted(set(tables) - set(written))
    steps.done("write")
    if plots:
        from climpact.plots import write_plots

        drawn = write_plots(tables, metadata, params, out_dir, steps.done, title=plot_title)
        written.update({f"plots/{name}": path for name, path in drawn.items()})
    if report:
        from climpact.report import write_report

        written["report"] = write_report(
            out_dir, metadata, params, report_path, qc=qc, title=plot_title, date=date
        )
        steps.done("report")
    if zip:
        from climpact.plots import zip_station

        written["zip"] = zip_station(out_dir, metadata.name)
        steps.done("zip")
    return written, skipped


def _process(
    station: BatchStation,
    data_dir: Path,
    out_dir: Path,
    base_start: int,
    base_end: int,
    date: dt.date | None,
    modules: ModuleSelection | None,
    plots: bool = False,
    report_dir: Path | None = None,
    progress: BatchProgress | None = None,
) -> StationResult:
    """Run one station, turning any exception into a failed result."""
    result = StationResult(station.name, station.station_file)
    station_progress = None
    if progress is not None:

        def station_progress(stage: str, step: int, total: int) -> None:
            progress(station.name, stage, step, total)

    try:
        from climpact.report import report_file

        validate_params(station.params)
        path = data_dir / station.station_file
        if not path.is_file():
            raise FileNotFoundError(f"station file not found: {path}")
        written, skipped = run_station(
            path,
            station.metadata(base_start, base_end),
            station.params,
            out_dir,
            date,
            modules,
            station_progress,
            plots=plots,
            report=report_dir is not None,
            report_path=None if report_dir is None else report_file(report_dir, station.name),
        )
    except Exception as exc:  # noqa: BLE001 - reported per station, the batch carries on
        detail = "".join(traceback.format_exception_only(exc)).strip()
        return replace(result, error=detail)
    return replace(result, written=len(written), skipped=tuple(skipped))


# Seconds to wait for the end of a finished station's progress, which is already sent.
_QUEUE_TIMEOUT = 60

# The progress queue of a worker process (set by _init_worker), or None.
_QUEUE = None
# The stage that marks the end of a station's progress on the queue.
_END = None


def _init_worker(queue) -> None:
    global _QUEUE
    _QUEUE = queue


def _send(station: str, stage: str | None, step: int, total: int) -> None:
    _QUEUE.put((station, stage, step, total))


def _process_in_worker(station: BatchStation, *args) -> StationResult:
    """``_process`` in a worker process, sending its progress to the parent's queue."""
    if _QUEUE is None:
        return _process(station, *args)
    try:
        return _process(station, *args, progress=_send)
    finally:
        _send(station.name, _END, 0, 0)


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
    modules: ModuleSelection | None = None,
    progress: BatchProgress | None = None,
    plots: bool = False,
    zip: bool = False,
    report_dir: str | Path | None = None,
) -> list[StationResult]:
    """Run every station and write its outputs to ``<out_dir>/<station>/``.

    Stations run in a pool of ``workers`` processes (default: one per CPU, at most one
    per station); ``workers=1`` runs them in this process. A station that fails does not
    stop the others: its error is written to ``<out_dir>/<station>.errors.txt``, and an
    error file left by an earlier run is removed first, as R does. ``custom`` is the
    custom index calculated for every station (R calculates none in batch mode).
    ``modules`` selects the QC, homogeneity and index modules and their options
    (default: the built-in ones); they are checked here, so an unknown module or a bad
    option raises before any station runs, and each worker process then loads them
    itself.
    ``on_result`` is called as each station finishes. Results are returned in metadata
    order.

    ``progress(station, stage, step, total)`` is called after each stage of each
    station, as :func:`run_station` reports them (see :mod:`climpact.progress`). With
    several workers the stages are sent back from the worker processes on a queue and the
    callback runs in this process and thread; a station's stages always come before its
    ``on_result``, and stages of different stations interleave.

    ``plots`` draws each station's plots and combined PDF, as :func:`run_station` does.
    ``zip`` zips the whole batch folder once every station has finished, to
    ``<out_dir>.zip`` next to it (:func:`climpact.plots.zip_batch`), as R's batch
    download does. ``report_dir`` writes each station's PDF report
    (:func:`climpact.report.write_report`) to ``<report_dir>/<station>_report.pdf``; it
    should be outside ``out_dir``, which is zipped as R's batch folder.
    """
    from climpact.modules import resolve

    resolve(modules)  # fail before the batch, not in every station
    if plots or report_dir is not None:
        from climpact.plots import require_matplotlib

        require_matplotlib()  # fail before the batch, not in every station
    stations = [replace(s, params=replace(s.params, custom=custom)) for s in stations]
    data_dir, out_dir = Path(data_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for station in stations:
        _error_file(out_dir, station.name).unlink(missing_ok=True)

    report_dir = Path(report_dir) if report_dir is not None else None
    args = [
        (s, data_dir, out_dir, base_start, base_end, date, modules, plots, report_dir)
        for s in stations
    ]
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
            finish(_process(*a, progress=progress))
        return _batch_done(stations, results, out_dir, zip)

    # spawn: the same start method on every platform, and no fork of a process whose
    # numerical libraries may be running threads.
    context = multiprocessing.get_context("spawn")
    # Progress comes back on a queue given to each worker when it starts. Each station's
    # stages end with an _END marker, and its result is handled only once the marker has
    # arrived, so its stages reach ``progress`` before its ``on_result``.
    queue = context.Queue() if progress is not None else None
    ended: set[str] = set()

    def receive(item: tuple) -> None:
        if item[1] is _END:
            ended.add(item[0])
        else:
            progress(*item)

    with ProcessPoolExecutor(
        max_workers=workers, mp_context=context, initializer=_init_worker, initargs=(queue,)
    ) as pool:
        futures = {pool.submit(_process_in_worker, *a): a[0] for a in args}
        pending = set(futures)
        while pending:
            done, pending = wait(
                pending, timeout=0.1 if queue else None, return_when=FIRST_COMPLETED
            )
            while queue is not None and not queue.empty():
                receive(queue.get())
            for future in done:
                station = futures[future]
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001 - e.g. a worker killed by the OS
                    detail = "".join(traceback.format_exception_only(exc)).strip()
                    result = StationResult(station.name, station.station_file, error=detail)
                else:
                    # The worker sent the marker before returning; wait for it to arrive.
                    try:
                        while queue is not None and station.name not in ended:
                            receive(queue.get(timeout=_QUEUE_TIMEOUT))
                    except Empty:  # never expected: the marker was sent before returning
                        pass
                finish(result)
    return _batch_done(stations, results, out_dir, zip)


def _batch_done(
    stations: list[BatchStation], results: dict[str, StationResult], out_dir: Path, zip: bool
) -> list[StationResult]:
    if zip:
        from climpact.plots import zip_batch

        zip_batch(out_dir)
    return [results[s.name] for s in stations]


def _error_file(out_dir: Path, name: str) -> Path:
    return out_dir / f"{name}.errors.txt"
