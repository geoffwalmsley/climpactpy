"""The built-in job runners: thin wrappers that turn a job's JSON parameters into calls to
the core (``climpact``), so the web app computes exactly what the command line does.

The core is imported inside each runner, not at module level: importing ``climpact``
imports xclim (about 2 s), which only the worker needs, not the web server.

Parameters (``Job.params``) of each kind; file names are relative to the job's
``input/`` folder, and everything is written to its ``output/`` folder:

``station`` (``climpact run``)
    ``station_file``; ``metadata``: ``name``, ``latitude``, ``longitude``,
    ``base_start``, ``base_end``; ``params``: :class:`climpact.config.IndexParams` fields,
    ``custom`` as ``{"variable", "operator", "threshold"}`` or null; ``plots``, ``zip``,
    ``report`` (the PDF report, :mod:`climpact.report`, to ``output/<station>_report.pdf``);
    optional ``plot_title`` (printed on every plot instead of the station title, R's
    "Plot title" of step 3); optional ``modules``:
    ``{"qc": [...], "homogeneity": ..., "indices": [...]}``.
    Optional ``qc``: :class:`climpact.config.QCParams` fields (the QC files' thresholds).
``qc`` (the R app's quality-control step)
    ``station_file``, ``metadata`` as for ``station``, and ``qc``: :class:`QCParams`
    fields (left out: R's defaults). Runs only the QC modules and writes the ``qc/``
    files to ``output/<station>/qc/`` and their zip to ``output/<station>.zip``.
    Optional ``homogeneity``: the options of the core's homogeneity module ``detect``
    (#365; ``methods``, ``variables``, ``series``, ``level``, ``min_years``), which then
    also looks for breaks and writes ``homogeneity/breaks`` and ``homogeneity/tests`` to
    ``output/<station>/homogeneity/`` (in the zip too), with ``station_history``, a station
    history file in ``input/``. The yearly series it tested are written beside ``output/``
    to ``breaks_series.json`` for the Quality page's chart (:func:`break_series`; not a
    file to download), and a history file that cannot be read is left out, its error in
    the result's ``history_error``.
``batch`` (``climpact batch``)
    ``metadata_file``; ``data_dir`` (a folder in ``input/``, default ``input/`` itself);
    ``base_start``, ``base_end``, ``custom``, ``plots``, ``zip``, ``workers`` (default 1),
    ``modules``; ``folder``, the name of the batch folder in ``output/`` and of its zip
    (default ``batch``; the batch page uses the metadata file's name, as R);
    ``station_zips`` (also zip each finished station to ``output/stations/<name>.zip``);
    ``report`` (each finished station's PDF report to ``output/reports/<name>_report.pdf``).
    Each station's progress is written to ``output/stations.json`` (:class:`BatchStatus`).
``sector`` (``climpact sector-correlation``)
    ``station_job`` (the id of a finished ``station`` or ``batch`` job, whose index tables
    are used), ``station`` (the station's name; required for a batch job),
    ``station_file`` (optional: the station file in this job's ``input/``; default the
    station job's), ``sector_file``, ``detrend``, ``title``, ``y_label``, ``plots``,
    ``zip``. The result also describes the outputs for the step 5 screen (#90):
    ``sector_column``, ``detrended``, ``correlation`` (the table's file) and ``scatters``
    (each scatter's ``name``, ``file``, ``x_column``, ``x_label``, and its regression as
    the PNG prints it: ``slope``, ``intercept``, ``r_squared``, ``text``; null values when
    there is none).
``gridded-thresholds`` and ``gridded-indices`` (``climpact gridded-thresholds`` and
``gridded-indices``)
    ``input_files`` (absolute paths, read in place: files on this computer in local mode,
    or the gridded run's uploaded copies), ``names`` (``{"tasmax", "tasmin", "pr"}``),
    ``base_start``, ``base_end``, ``institution``, ``institution_id``, ``workers``,
    ``max_values`` (values read at once), ``rechunk`` (``auto``, ``yes``, ``no``),
    ``tmp_dir`` (for the rechunked copy; default the job's own folder), ``copy_to`` (a
    folder the written files are also copied to, local mode); for thresholds also
    ``out_file``; for indices also ``template``, ``indices``, ``thresholds_file``,
    ``params`` (IndexParams fields) and ``trends`` (default true: also write
    ``trends.nc``, the stage "trends" after "indices", :mod:`climpact.gridded.trends`).
    When each stage began is written to ``stages.json`` in the job's folder
    (:class:`StageTimes`), for the run's stages on its Map tab (#294).

The batch page (#80) creates batch jobs, the gridded pages (#85) the gridded ones and step
5 of a station (#90) the sector ones.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from climpact_web.jobs.registry import JobContext, JobError, register

INDEX_PARAM_FIELDS = (
    "wsdi_days",
    "csdi_days",
    "rx_days",
    "txtn_days",
    "hdd_base",
    "cdd_base",
    "gdd_base",
    "rnnmm",
    "spei_months",
)


def custom_index(value: dict | None):
    from climpact.config import CustomIndex

    if value is None:
        return None
    return CustomIndex(
        variable=value.get("variable", "TN"),
        operator=value.get("operator", ">"),
        threshold=float(value.get("threshold", 0.0)),
    )


def index_params(values: dict[str, Any] | None, base=None):
    """:class:`IndexParams` from JSON; fields left out keep the defaults (of ``base``)."""
    from dataclasses import replace

    from climpact.config import IndexParams

    values = dict(values or {})
    params = base if base is not None else IndexParams()
    changes = {k: values[k] for k in INDEX_PARAM_FIELDS if k in values}
    if "custom" in values:
        changes["custom"] = custom_index(values["custom"])
    return replace(params, **changes)


def module_selection(value: dict | None):
    from climpact.modules import ModuleSelection

    if not value:
        return None
    default = ModuleSelection()
    return ModuleSelection(
        qc=tuple(value.get("qc", default.qc)),
        homogeneity=value.get("homogeneity", default.homogeneity),
        indices=tuple(value.get("indices", default.indices)),
    )


QC_PARAM_FIELDS = ("iqr_temp", "iqr_prec", "prec_max", "temp_max", "flatline_days", "jump")


def qc_params(values: dict[str, Any] | None):
    """:class:`QCParams` from JSON; fields left out keep R's defaults."""
    from climpact.config import QCParams

    values = dict(values or {})
    changes = {k: values[k] for k in QC_PARAM_FIELDS if values.get(k) is not None}
    if "flatline_days" in changes:
        changes["flatline_days"] = int(changes["flatline_days"])
    return QCParams(**{k: v if k == "flatline_days" else float(v) for k, v in changes.items()})


def station_metadata(p: dict):
    from climpact.config import StationMetadata

    meta = p.get("metadata", {})
    return StationMetadata(
        name=meta.get("name") or Path(p["station_file"]).stem,
        latitude=float(meta.get("latitude", 0.0)),
        longitude=float(meta.get("longitude", 0.0)),
        base_start=int(meta.get("base_start", 1971)),
        base_end=int(meta.get("base_end", 2000)),
    )


def _relative(paths, root: Path) -> list[str]:
    return sorted(str(Path(p).relative_to(root)) for p in paths)


@register("station")
def run_station_job(ctx: JobContext) -> dict:
    from climpact.batch import run_station, validate_params

    p = ctx.params
    station_file = ctx.input_file(p["station_file"])
    metadata = station_metadata(p)
    params = index_params(p.get("params"))
    validate_params(params)
    written, skipped = run_station(
        station_file,
        metadata,
        params,
        ctx.output_dir,
        modules=module_selection(p.get("modules")),
        progress=ctx.progress,
        plots=bool(p.get("plots")),
        zip=bool(p.get("zip")),
        qc=qc_params(p.get("qc")),
        plot_title=p.get("plot_title") or None,
        report=bool(p.get("report")),
    )
    archive = written.pop("zip", None)
    report = written.pop("report", None)
    return {
        "station": metadata.name,
        "files": _relative(written.values(), ctx.output_dir),
        "skipped": list(skipped),
        "zip": _relative([archive], ctx.output_dir)[0] if archive else None,
        "report": _relative([report], ctx.output_dir)[0] if report else None,
    }


@register("qc")
def run_qc_job(ctx: JobContext) -> dict:
    """The quality-control step alone: the ``qc/`` files of the station and their zip
    (the R app's step 2, ``load_data_qc``), with the user's thresholds."""
    from dataclasses import asdict

    from climpact.batch import run_station
    from climpact.config import IndexParams
    from climpact.modules import ModuleSelection

    p = ctx.params
    metadata = station_metadata(p)
    thresholds = qc_params(p.get("qc"))
    station_file = ctx.input_file(p["station_file"])
    breaks = p.get("homogeneity")
    modules, history_error = ModuleSelection(indices=()), ""
    if breaks is not None:
        options = {k: breaks[k] for k in BREAK_OPTIONS if k in breaks}
        if p.get("station_history"):
            history_error = _history_error(ctx.input_file(p["station_history"]), metadata.name)
            if not history_error:
                options["station_history"] = str(ctx.input_file(p["station_history"]))
        modules = ModuleSelection(
            indices=(), homogeneity="detect", options={"homogeneity": {"detect": options}}
        )
    written, _skipped = run_station(
        station_file,
        metadata,
        IndexParams(),
        ctx.output_dir,
        modules=modules,
        progress=ctx.progress,
        zip=True,
        qc=thresholds,
    )
    archive = written.pop("zip")
    result = {
        "station": metadata.name,
        "files": _relative(written.values(), ctx.output_dir),
        "reports": {key: _relative([path], ctx.output_dir)[0] for key, path in written.items()},
        "zip": _relative([archive], ctx.output_dir)[0],
        "qc": asdict(thresholds),
    }
    if breaks is not None:
        history = options.get("station_history")
        path = ctx.output_dir.parent / BREAK_SERIES_FILE
        series = break_series(station_file, metadata, thresholds, history)
        path.write_text(json.dumps(series))
        result["breaks_series"] = BREAK_SERIES_FILE
        result["history_error"] = history_error
    return result


# The options of the homogeneity module ``detect`` a ``qc`` job passes on (#365), and the
# file it writes the yearly series to, for the Quality page's chart.
BREAK_OPTIONS = ("methods", "variables", "series", "level", "min_years")
BREAK_SERIES_FILE = "breaks_series.json"


def _history_error(path: Path, station: str) -> str:
    """Why the station history file can't be used, or "" when it can."""
    from climpact.homogeneity.detect import read_station_history

    try:
        read_station_history(path, station)
    except (ValueError, UnicodeDecodeError) as exc:
        return str(exc).replace(str(path), path.name)
    return ""


def break_series(station_file: Path, metadata, thresholds, history: str | None = None) -> dict:
    """The yearly series of the break detection, for the Quality page's chart (#365): the
    yearly mean TX and TN and the yearly PRCP total (mm), under the climdex rules, from the
    first year of the data (``first``), null where missing (the monthly series' breaks are
    drawn on the yearly means); and the station's events in the ``history`` file
    (``{"date", "text"}``, for the triangles under the chart)."""
    import math

    from climpact.config import IndexParams
    from climpact.homogeneity.detect import read_station_history
    from climpact.homogeneity.series import ANNUAL, VARIABLES, build_series
    from climpact.station import load_station

    run = load_station(station_file, metadata, IndexParams(), thresholds)
    out: dict = {"first": None, "values": {}, "history": []}
    if history:
        out["history"] = [
            {"date": e.date.isoformat(), "text": e.text}
            for e in read_station_history(history, metadata.name)
        ]
    for variable in VARIABLES:
        series = build_series(run, variable, ANNUAL)
        if out["first"] is None and series.years.size:
            out["first"] = int(series.years[0])
        values = [float(v) for v in series.values]
        if variable == "PRCP":
            values = [math.exp(v) for v in values]
        out["values"][variable] = [None if math.isnan(v) else round(v, 4) for v in values]
    return out


def station_steps(params, modules, plots: bool, report: bool = False) -> int:
    """The number of progress steps of one ``run_station`` (without zip)."""
    from climpact.modules import pipeline_stages, resolve

    total = len(pipeline_stages(resolve(modules))) + 2 + (1 if report else 0)
    if plots:
        from climpact.plots import plot_steps

        total += len(plot_steps(params))
    return total


STATIONS_FILE = "stations.json"  # a batch's per-station progress, in output/
_STATUS_INTERVAL = 0.5  # seconds between writes of the per-station progress


class BatchStatus:
    """Each station's state during a batch, written to ``output/stations.json`` for the
    batch page (``{"stations": [{"name", "state", "step", "total", "stage", "error"}]}``;
    ``state`` is ``waiting``, ``running``, ``done`` or ``failed``). Written atomically (a
    temporary file, then a rename) when a station starts or ends, and at most every 0.5 s
    in between."""

    def __init__(self, path: Path, totals: dict[str, int]):
        self.path = path
        self.stations = {
            name: {"name": name, "state": "waiting", "step": 0, "total": total, "stage": ""}
            for name, total in totals.items()
        }
        self.written = 0.0
        self.write()

    def update(self, name: str, force: bool = False, **values) -> None:
        import time

        entry = self.stations[name]
        force = force or values.get("state", entry["state"]) != entry["state"]
        entry.update(values)
        if force or time.monotonic() - self.written >= _STATUS_INTERVAL:
            self.write()

    def write(self) -> None:
        import json
        import time

        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"stations": list(self.stations.values())}))
        tmp.replace(self.path)
        self.written = time.monotonic()


@register("batch")
def run_batch_job(ctx: JobContext) -> dict:
    from climpact.batch import read_batch_metadata, run_batch
    from climpact.plots import zip_batch, zip_folder
    from climpact_web.jobs.forms import safe_station_name

    p = ctx.params
    metadata_file = ctx.input_file(p["metadata_file"])
    data_dir = ctx.input_dir / p.get("data_dir", ".")
    if not data_dir.resolve().is_relative_to(ctx.input_dir.resolve()) or not data_dir.is_dir():
        raise JobError("The folder of station files is missing.")
    stations = read_batch_metadata(metadata_file)
    if not stations:
        raise JobError("The metadata file lists no stations.")
    custom = custom_index(p.get("custom"))
    modules = module_selection(p.get("modules"))
    plots, zip_, report = bool(p.get("plots")), bool(p.get("zip")), bool(p.get("report"))
    folder = safe_station_name(p.get("folder") or "batch")

    # One count for the whole batch: each station's steps, then the zip. Stations may
    # interleave (several workers), so the count is the sum of each station's last step.
    from dataclasses import replace

    totals = {
        s.name: station_steps(replace(s.params, custom=custom), modules, plots, report)
        for s in stations
    }
    total = sum(totals.values()) + (1 if zip_ else 0)
    done = dict.fromkeys(totals, 0)
    status = BatchStatus(ctx.output_dir / STATIONS_FILE, totals)

    def progress(station: str, stage: str, step: int, _total: int) -> None:
        done[station] = step
        status.update(station, state="running", step=step, stage=stage)
        ctx.progress(f"{station}: {stage}", sum(done.values()), total)

    def on_result(result) -> None:
        if result.ok:
            status.update(result.name, state="done", step=totals[result.name])
        else:
            status.update(result.name, state="failed", error=result.error or "")
        if done[result.name] < totals[result.name]:  # a failed station: count it as done
            done[result.name] = totals[result.name]
            ctx.progress(f"{result.name}: failed", sum(done.values()), total)

    out_dir = ctx.output_dir / folder
    out_dir.mkdir(parents=True, exist_ok=True)
    results = run_batch(
        stations,
        data_dir,
        out_dir,
        base_start=int(p.get("base_start", 1971)),
        base_end=int(p.get("base_end", 2000)),
        custom=custom,
        workers=int(p.get("workers", 1)),
        on_result=on_result,
        modules=modules,
        progress=progress,
        plots=plots,
        report_dir=ctx.output_dir / "reports" if report else None,
    )
    station_zips = {}
    if p.get("station_zips"):  # each station on its own, beside the batch folder
        for r in results:
            if r.ok and (out_dir / r.name).is_dir():
                archive = ctx.output_dir / "stations" / f"{r.name}.zip"
                archive.parent.mkdir(parents=True, exist_ok=True)
                zip_folder(out_dir / r.name, archive, exclude_suffix=".zip")
                station_zips[r.name] = _relative([archive], ctx.output_dir)[0]
    if zip_:
        zip_batch(out_dir)
        ctx.progress("zip", total, total)

    def entry(r) -> dict:
        folder_path = out_dir / r.name
        return {
            "name": r.name,
            "station_file": r.station_file,
            "ok": r.ok,
            "written": r.written,
            "skipped_outputs": list(r.skipped),
            "error": r.error,
            "error_file": _relative([r.error_file], ctx.output_dir)[0] if r.error_file else None,
            "folder": _relative([folder_path], ctx.output_dir)[0] if r.ok else None,
            "zip": station_zips.get(r.name),
            "report": _relative([report_path], ctx.output_dir)[0]
            if r.ok
            and (report_path := ctx.output_dir / "reports" / f"{r.name}_report.pdf").is_file()
            else None,
        }

    return {
        "folder": folder,
        "stations": [entry(r) for r in results],
        "zip": f"{folder}.zip" if zip_ else None,
    }


@register("sector")
def run_sector_job(ctx: JobContext) -> dict:
    from climpact.sector import read_index_tables, run_sector_correlation
    from climpact_web.jobs.models import Job, Status

    p = ctx.params
    station_job = Job.objects.filter(pk=p.get("station_job"), kind__in=("station", "batch")).first()
    if station_job is None or station_job.status != Status.SUCCEEDED:
        raise JobError("Calculate the station's indices first: the station run was not found.")
    result = station_job.result or {}
    if station_job.kind == "batch":
        station = p.get("station") or ""
        if not any(s.get("ok") and s["name"] == station for s in result.get("stations", [])):
            raise JobError("Calculate the station's indices first: the station run was not found.")
        folder = station_job.output_dir / result.get("folder", "")
    else:
        station = result["station"]
        folder = station_job.output_dir
    if p.get("station_file"):
        station_file = ctx.input_file(p["station_file"])
    elif station_job.kind == "station":
        station_file = station_job.input_dir / station_job.params["station_file"]
    else:
        raise JobError("The station file was not given.")
    tables = read_index_tables(folder / station / "indices", station)
    written = run_sector_correlation(
        station_file,
        ctx.input_file(p["sector_file"]),
        ctx.output_dir,
        station,
        detrend_sector=bool(p.get("detrend", True)),
        title=p.get("title") or None,
        y_label=p.get("y_label") or None,
        index_tables=tables,
        plots=bool(p.get("plots")),
        zip=bool(p.get("zip")),
        progress=ctx.progress,
    )
    archive = written.pop("zip", None)
    return {
        "station": station,
        "files": _relative(written.values(), ctx.output_dir),
        "zip": _relative([archive], ctx.output_dir)[0] if archive else None,
        **_sector_outputs(written, ctx.output_dir),
    }


def _sector_outputs(written: dict, root: Path) -> dict:
    """What the step 5 screen shows of a sector run: the files of each scatter plot with
    its regression (read back from its CSV file, as the PNG prints it) and the table of
    correlations."""
    import math

    import pandas as pd

    from climpact.sector import SCATTERS, regression, regression_text

    def value(v):
        return None if v is None or math.isnan(v) else v

    scatters, column = [], ""
    for name, x_column, x_label in SCATTERS:
        key = next(k for k in written if k.startswith(f"corr_{name}_") and not k.endswith(".png"))
        table = pd.read_csv(written[key])
        column = table.columns[2]
        reg = regression(table[x_column].to_numpy(float), table[column].to_numpy(float))
        scatters.append(
            {
                "name": name,
                "file": Path(written[key]).relative_to(root).as_posix(),
                "x_column": x_column,
                "x_label": x_label,
                "slope": value(reg.slope) if reg else None,
                "intercept": value(reg.intercept) if reg else None,
                "r_squared": value(reg.r_squared) if reg else None,
                "text": regression_text(reg),
            }
        )
    bar = next(
        k for k in written if k.startswith("index-sector_correlation_") and not k.endswith(".png")
    )
    return {
        "sector_column": column,
        "detrended": column.startswith("Detrended"),
        "correlation": Path(written[bar]).relative_to(root).as_posix(),
        "scatters": scatters,
    }


STAGES_FILE = "stages.json"  # a gridded job's stages, in the job's folder beside output/


class StageTimes:
    """When each stage of a gridded job began, for the run's stages on its Map tab
    (#294): ``check`` (opening and checking the files) when the job starts, then each
    stage the core reports (``rechunk``, ``thresholds``, ``indices``, ``trends``) as its
    first step is reported, dated when the stage before it ended (its last step, or the
    files opened). Written to ``<job>/stages.json`` as ``{"stages": [{"stage", "at",
    "step"}], "opened", "blocks", "copy", "copy_bytes"}``: ``step`` is the count when the
    stage began; ``opened`` when the files were open and checked; ``blocks`` the grid's
    blocks, which tell the copy's steps from the blocks' when the core counts them
    together (:meth:`climpact.gridded.GriddedInput.block_reader`); ``copy`` whether the
    blocks are read from a cell-first copy, and its size. Written atomically, only when
    a stage begins: a handful of writes a job.

    Wraps the job's progress callback: ``times(stage, step, total)`` passes each step on.
    """

    def __init__(self, path: Path, progress):
        self.path = path
        self.progress = progress
        self.ended = self._now()
        self.stages = [{"stage": "check", "at": self.ended, "step": 0}]
        self.extra: dict = {}
        self.write()

    @staticmethod
    def _now() -> str:
        from django.utils import timezone

        return timezone.now().isoformat()

    def opened(self, inp) -> None:
        """The files are open and checked: the next stage begins now."""
        import warnings

        copy, size = False, 0
        try:
            with warnings.catch_warnings():  # block_reader warns, when it decides
                warnings.simplefilter("ignore")
                copy = bool(inp.will_rechunk())
                size = int(inp.rechunk_bytes()) if copy else 0
        except (OSError, ValueError, AttributeError):
            pass
        self.ended = self._now()
        self.extra = {
            "opened": self.ended,
            "blocks": sum(1 for _ in inp.blocks()),
            "copy": copy,
            "copy_bytes": size,
        }
        self.write()

    def __call__(self, stage: str, step: int, total: int) -> None:
        head = stage.split(":")[0]
        if head != self.stages[-1]["stage"]:
            self.stages.append({"stage": head, "at": self.ended, "step": max(step - 1, 0)})
            self.write()
        self.ended = self._now()
        self.progress(stage, step, total)

    def write(self) -> None:
        import json

        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"stages": self.stages, **self.extra}))
        tmp.replace(self.path)


def read_stage_times(folder: Path) -> dict:
    """A gridded job's ``stages.json`` (:class:`StageTimes`); {} when it has none (a job
    run before #294, or one not started)."""
    import json

    try:
        data = json.loads((folder / STAGES_FILE).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


# The core's OSError when the cell-first copy does not fit (GriddedInput.block_reader):
# shown to the user, as a JobError, rather than as an unexpected failure.
NO_ROOM_FOR_COPY = "rechunking the input needs"


def _no_room(exc: OSError) -> JobError | None:
    message = str(exc)
    if not message.startswith(NO_ROOM_FOR_COPY):
        return None
    return JobError(f"Not enough disk space for the cell-first copy: {message}.")


def _open_grid(ctx: JobContext, times: StageTimes | None = None):
    from climpact.gridded import open_grid
    from climpact.gridded.io import DEFAULT_MAX_VALUES

    p = ctx.params
    files = [Path(f) for f in p.get("input_files", [])]
    missing = [str(f) for f in files if not f.is_file()]
    if not files or missing:
        raise JobError(f"Input file not found: {', '.join(missing) or 'none given'}.")
    names = p.get("names") or None
    tmp_dir = Path(p["tmp_dir"]) if p.get("tmp_dir") else ctx.output_dir.parent / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        inp = open_grid(
            files,
            names=names,
            max_values=int(p.get("max_values") or DEFAULT_MAX_VALUES),
            rechunk={"auto": None, "yes": True, "no": False}[p.get("rechunk", "auto")],
            tmp_dir=tmp_dir,
        )
    except NotImplementedError as exc:
        raise JobError(str(exc)) from None
    if times is not None:
        times.opened(inp)
    return inp


def _stage_times(ctx: JobContext) -> StageTimes:
    """The job's :class:`StageTimes`, wrapping its progress callback."""
    times = StageTimes(ctx.output_dir.parent / STAGES_FILE, ctx.progress)
    ctx.progress = times
    return times


def _copy_results(ctx: JobContext, paths) -> str | None:
    """Copy the written files to the ``copy_to`` folder (local mode), if one was given."""
    import shutil

    folder = ctx.params.get("copy_to")
    if not folder:
        return None
    target = Path(folder)
    try:
        target.mkdir(parents=True, exist_ok=True)
        for path in paths:
            shutil.copy2(path, target / Path(path).name)
    except OSError as exc:
        raise JobError(f"The results could not be copied to {target}: {exc.strerror}.") from None
    return str(target)


def _author(p: dict) -> dict:
    return {"institution": p.get("institution"), "institution_id": p.get("institution_id")}


@register("gridded-thresholds")
def run_gridded_thresholds_job(ctx: JobContext) -> dict:
    from climpact.gridded import write_grid_thresholds

    p = ctx.params
    ctx.output_dir.mkdir(parents=True, exist_ok=True)
    inp = _open_grid(ctx, _stage_times(ctx))
    try:
        path = write_grid_thresholds(
            inp,
            ctx.output_dir / p.get("out_file", "thresholds.nc"),
            int(p.get("base_start", 1971)),
            int(p.get("base_end", 2000)),
            _author(p),
            int(p.get("workers", 1)),
            ctx.progress,
        )
    except OSError as exc:
        raise _no_room(exc) or exc from None
    copied = _copy_results(ctx, [path])
    return {"files": _relative([path], ctx.output_dir), "copied_to": copied}


@register("gridded-indices")
def run_gridded_indices_job(ctx: JobContext) -> dict:
    from climpact.gridded import write_grid_indices
    from climpact.gridded.indices import WRAPPER_PARAMS

    p = ctx.params
    ctx.output_dir.mkdir(parents=True, exist_ok=True)
    inp = _open_grid(ctx, _stage_times(ctx))
    thresholds = p.get("thresholds_file")
    if thresholds and not Path(thresholds).is_file():
        raise JobError(f"Thresholds file not found: {thresholds}.")
    try:
        paths = write_grid_indices(
            inp,
            ctx.output_dir,
            int(p.get("base_start", 1971)),
            int(p.get("base_end", 2000)),
            template=p.get("template") or None,
            params=index_params(p.get("params"), base=WRAPPER_PARAMS),
            thresholds_file=thresholds or None,
            author=_author(p),
            workers=int(p.get("workers", 1)),
            progress=ctx.progress,
            indices=p.get("indices") or None,
        )
    except OSError as exc:
        raise _no_room(exc) or exc from None
    if p.get("trends", True):
        from climpact.gridded.trends import TRENDS_FILE, write_grid_trends

        trends = write_grid_trends(
            paths,
            ctx.output_dir / TRENDS_FILE,
            int(p.get("base_start", 1971)),
            int(p.get("base_end", 2000)),
            latitude=inp.cell_latitude().values,
            workers=int(p.get("workers", 1)),
            progress=ctx.progress,
        )
        if trends is not None:
            paths = [*paths, trends]
    copied = _copy_results(ctx, paths)
    return {"files": _relative(paths, ctx.output_dir), "copied_to": copied}
