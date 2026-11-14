"""The built-in job runners: thin wrappers that turn a job's JSON parameters into calls to
the core (``climpact``), so the web app computes exactly what the command line does.

The core is imported inside each runner, not at module level: importing ``climpact``
imports xclim (about 2 s), which only the worker needs, not the web server.

Parameters (``Job.params``) of each kind; file names are relative to the job's
``input/`` folder, and everything is written to its ``output/`` folder:

``station`` (``climpact run``)
    ``station_file``; ``metadata``: ``name``, ``latitude``, ``longitude``,
    ``base_start``, ``base_end``; ``params``: :class:`climpact.config.IndexParams` fields,
    ``custom`` as ``{"variable", "operator", "threshold"}`` or null; ``plots``, ``zip``;
    optional ``plot_title`` (printed on every plot instead of the station title, R's
    "Plot title" of step 3); optional ``modules``:
    ``{"qc": [...], "homogeneity": ..., "indices": [...]}``.
    Optional ``qc``: :class:`climpact.config.QCParams` fields (the QC files' thresholds).
``qc`` (the R app's quality-control step)
    ``station_file``, ``metadata`` as for ``station``, and ``qc``: :class:`QCParams`
    fields (left out: R's defaults). Runs only the QC modules and writes the ``qc/``
    files to ``output/<station>/qc/`` and their zip to ``output/<station>.zip``.
``batch`` (``climpact batch``)
    ``metadata_file``; ``data_dir`` (a folder in ``input/``, default ``input/`` itself);
    ``base_start``, ``base_end``, ``custom``, ``plots``, ``zip``, ``workers`` (default 1),
    ``modules``; ``folder``, the name of the batch folder in ``output/`` and of its zip
    (default ``batch``; the batch page uses the metadata file's name, as R);
    ``station_zips`` (also zip each finished station to ``output/stations/<name>.zip``);
    ``skipped``, stations left out before the run (``[{"name", "station_file",
    "error"}]``), whose error is written to ``<folder>/<name>.errors.txt`` like a failed
    station's. Each station's progress is written to ``output/stations.json``
    (:class:`BatchStatus`).
``sector`` (``climpact sector-correlation``)
    ``station_job`` (the id of a finished station job, whose station file and index
    tables are used), ``sector_file``, ``detrend``, ``title``, ``y_label``, ``plots``,
    ``zip``.
``gridded-thresholds`` and ``gridded-indices`` (``climpact gridded-thresholds`` and
``gridded-indices``)
    ``input_files`` (absolute paths, read in place: files on this computer in local mode,
    or the gridded run's uploaded copies), ``names`` (``{"tasmax", "tasmin", "pr"}``),
    ``base_start``, ``base_end``, ``institution``, ``institution_id``, ``workers``,
    ``max_values`` (values read at once), ``rechunk`` (``auto``, ``yes``, ``no``),
    ``tmp_dir`` (for the rechunked copy; default the job's own folder), ``copy_to`` (a
    folder the written files are also copied to, local mode); for thresholds also
    ``out_file``; for indices also ``template``, ``indices``, ``thresholds_file`` and
    ``params`` (IndexParams fields).

The batch page (#80) creates batch jobs and the gridded pages (#85) the gridded ones. The
sector runner is complete but has no screen yet: #90 adds the form that creates it.
"""

from __future__ import annotations

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
    )
    archive = written.pop("zip", None)
    return {
        "station": metadata.name,
        "files": _relative(written.values(), ctx.output_dir),
        "skipped": list(skipped),
        "zip": _relative([archive], ctx.output_dir)[0] if archive else None,
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
    written, _skipped = run_station(
        ctx.input_file(p["station_file"]),
        metadata,
        IndexParams(),
        ctx.output_dir,
        modules=ModuleSelection(indices=()),
        progress=ctx.progress,
        zip=True,
        qc=thresholds,
    )
    archive = written.pop("zip")
    return {
        "station": metadata.name,
        "files": _relative(written.values(), ctx.output_dir),
        "reports": {key: _relative([path], ctx.output_dir)[0] for key, path in written.items()},
        "zip": _relative([archive], ctx.output_dir)[0],
        "qc": asdict(thresholds),
    }


def station_steps(params, modules, plots: bool) -> int:
    """The number of progress steps of one ``run_station`` (without zip)."""
    from climpact.modules import pipeline_stages, resolve

    total = len(pipeline_stages(resolve(modules))) + 2
    if plots:
        from climpact.plots import plot_steps

        total += len(plot_steps(params))
    return total


STATIONS_FILE = "stations.json"  # a batch's per-station progress, in output/
_STATUS_INTERVAL = 0.5  # seconds between writes of the per-station progress


class BatchStatus:
    """Each station's state during a batch, written to ``output/stations.json`` for the
    batch page (``{"stations": [{"name", "state", "step", "total", "stage", "error"}]}``;
    ``state`` is ``waiting``, ``running``, ``done``, ``failed`` or ``skipped``). Written
    atomically (a temporary file, then a rename) when a station starts or ends, and at
    most every 0.5 s in between."""

    def __init__(self, path: Path, totals: dict[str, int], skipped: list[dict]):
        self.path = path
        self.stations = {
            name: {"name": name, "state": "waiting", "step": 0, "total": total, "stage": ""}
            for name, total in totals.items()
        }
        for item in skipped:
            self.stations[item["name"]] = {
                "name": item["name"],
                "state": "skipped",
                "step": 0,
                "total": 0,
                "stage": "",
                "error": item.get("error", ""),
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


def _skipped_stations(value, taken: set[str]) -> list[dict]:
    """The ``skipped`` parameter: stations the batch page found unusable before the run,
    as ``[{"name", "station_file", "error"}]``. Names are made safe for file names, and
    never the same as a station's that runs (``taken``) or another skipped one's."""
    from climpact.batch import strip_file_extension
    from climpact_web.jobs.forms import safe_station_name

    items = []
    taken = set(taken)
    for item in value or []:
        base = safe_station_name(
            str(item.get("name") or strip_file_extension(item.get("station_file", "")))
        )
        name, n = base, 1
        while name in taken:
            n += 1
            name = f"{base}_{n}"
        taken.add(name)
        items.append({**item, "name": name, "error": str(item.get("error", ""))})
    return items


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
    skipped = _skipped_stations(p.get("skipped"), {s.name for s in stations})
    custom = custom_index(p.get("custom"))
    modules = module_selection(p.get("modules"))
    plots, zip_ = bool(p.get("plots")), bool(p.get("zip"))
    folder = safe_station_name(p.get("folder") or "batch")

    # One count for the whole batch: each station's steps, then the zip. Stations may
    # interleave (several workers), so the count is the sum of each station's last step.
    from dataclasses import replace

    totals = {
        s.name: station_steps(replace(s.params, custom=custom), modules, plots) for s in stations
    }
    total = sum(totals.values()) + (1 if zip_ else 0)
    done = dict.fromkeys(totals, 0)
    status = BatchStatus(ctx.output_dir / STATIONS_FILE, totals, skipped)

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
    for item in skipped:  # in the zip too, under R's error file name
        (out_dir / f"{item['name']}.errors.txt").write_text(item["error"] + "\n")
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
        }

    return {
        "folder": folder,
        "stations": [entry(r) for r in results],
        "skipped": [
            {
                "name": item["name"],
                "station_file": item.get("station_file", ""),
                "error": item["error"],
                "error_file": f"{folder}/{item['name']}.errors.txt",
            }
            for item in skipped
        ],
        "zip": f"{folder}.zip" if zip_ else None,
    }


@register("sector")
def run_sector_job(ctx: JobContext) -> dict:
    from climpact.sector import read_index_tables, run_sector_correlation
    from climpact_web.jobs.models import Job, Status

    p = ctx.params
    station_job = Job.objects.filter(pk=p.get("station_job"), kind="station").first()
    if station_job is None or station_job.status != Status.SUCCEEDED:
        raise JobError("Calculate the station's indices first: the station run was not found.")
    station = station_job.result["station"]
    station_file = station_job.input_dir / station_job.params["station_file"]
    tables = read_index_tables(station_job.output_dir / station / "indices", station)
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
    }


def _open_grid(ctx: JobContext):
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
        return open_grid(
            files,
            names=names,
            max_values=int(p.get("max_values") or DEFAULT_MAX_VALUES),
            rechunk={"auto": None, "yes": True, "no": False}[p.get("rechunk", "auto")],
            tmp_dir=tmp_dir,
        )
    except NotImplementedError as exc:
        raise JobError(str(exc)) from None


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
    inp = _open_grid(ctx)
    path = write_grid_thresholds(
        inp,
        ctx.output_dir / p.get("out_file", "thresholds.nc"),
        int(p.get("base_start", 1971)),
        int(p.get("base_end", 2000)),
        _author(p),
        int(p.get("workers", 1)),
        ctx.progress,
    )
    copied = _copy_results(ctx, [path])
    return {"files": _relative([path], ctx.output_dir), "copied_to": copied}


@register("gridded-indices")
def run_gridded_indices_job(ctx: JobContext) -> dict:
    from climpact.gridded import write_grid_indices
    from climpact.gridded.indices import WRAPPER_PARAMS

    p = ctx.params
    ctx.output_dir.mkdir(parents=True, exist_ok=True)
    inp = _open_grid(ctx)
    thresholds = p.get("thresholds_file")
    if thresholds and not Path(thresholds).is_file():
        raise JobError(f"Thresholds file not found: {thresholds}.")
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
    copied = _copy_results(ctx, paths)
    return {"files": _relative(paths, ctx.output_dir), "copied_to": copied}
