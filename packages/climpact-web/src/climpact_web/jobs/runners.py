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
    optional ``modules``: ``{"qc": [...], "homogeneity": ..., "indices": [...]}``.
``batch`` (``climpact batch``)
    ``metadata_file``; ``data_dir`` (a folder in ``input/``, default ``input/`` itself);
    ``base_start``, ``base_end``, ``custom``, ``plots``, ``zip``, ``workers`` (default 1),
    ``modules``.
``sector`` (``climpact sector-correlation``)
    ``station_job`` (the id of a finished station job, whose station file and index
    tables are used), ``sector_file``, ``detrend``, ``title``, ``y_label``, ``plots``,
    ``zip``.
``gridded-thresholds`` and ``gridded-indices`` (``climpact gridded-thresholds`` and
``gridded-indices``)
    ``input_files`` (absolute paths, read in place: local mode, #85), ``names``
    (``{"tasmax", "tasmin", "pr"}``), ``base_start``, ``base_end``, ``institution``,
    ``institution_id``, ``workers``; for indices also ``template``, ``indices``,
    ``thresholds_file`` and ``params`` (IndexParams fields).

The batch, sector and gridded runners are complete but have no screen yet: #80, #90 and
#85 add the forms that create these jobs.
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


def _relative(paths, root: Path) -> list[str]:
    return sorted(str(Path(p).relative_to(root)) for p in paths)


@register("station")
def run_station_job(ctx: JobContext) -> dict:
    from climpact.batch import run_station, validate_params
    from climpact.config import StationMetadata

    p = ctx.params
    meta = p.get("metadata", {})
    station_file = ctx.input_file(p["station_file"])
    metadata = StationMetadata(
        name=meta.get("name") or Path(p["station_file"]).stem,
        latitude=float(meta.get("latitude", 0.0)),
        longitude=float(meta.get("longitude", 0.0)),
        base_start=int(meta.get("base_start", 1971)),
        base_end=int(meta.get("base_end", 2000)),
    )
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
    )
    archive = written.pop("zip", None)
    return {
        "station": metadata.name,
        "files": _relative(written.values(), ctx.output_dir),
        "skipped": list(skipped),
        "zip": _relative([archive], ctx.output_dir)[0] if archive else None,
    }


def station_steps(params, modules, plots: bool) -> int:
    """The number of progress steps of one ``run_station`` (without zip)."""
    from climpact.modules import pipeline_stages, resolve

    total = len(pipeline_stages(resolve(modules))) + 2
    if plots:
        from climpact.plots import plot_steps

        total += len(plot_steps(params))
    return total


@register("batch")
def run_batch_job(ctx: JobContext) -> dict:
    from climpact.batch import read_batch_metadata, run_batch

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
    plots, zip_ = bool(p.get("plots")), bool(p.get("zip"))

    # One count for the whole batch: each station's steps, then the zip. Stations may
    # interleave (several workers), so the count is the sum of each station's last step.
    from dataclasses import replace

    totals = {
        s.name: station_steps(replace(s.params, custom=custom), modules, plots) for s in stations
    }
    total = sum(totals.values()) + (1 if zip_ else 0)
    done = dict.fromkeys(totals, 0)

    def progress(station: str, stage: str, step: int, _total: int) -> None:
        done[station] = step
        ctx.progress(f"{station}: {stage}", sum(done.values()), total)

    def on_result(result) -> None:
        if done[result.name] < totals[result.name]:  # a failed station: count it as done
            done[result.name] = totals[result.name]
            ctx.progress(f"{result.name}: failed", sum(done.values()), total)

    out_dir = ctx.output_dir / "batch"
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
        zip=zip_,
    )
    if zip_:
        ctx.progress("zip", total, total)
    return {
        "stations": [
            {"name": r.name, "ok": r.ok, "written": r.written, "error": r.error} for r in results
        ],
        "zip": "batch.zip" if zip_ else None,
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

    files = [Path(f) for f in ctx.params.get("input_files", [])]
    missing = [str(f) for f in files if not f.is_file()]
    if not files or missing:
        raise JobError(f"Input file not found: {', '.join(missing) or 'none given'}.")
    names = ctx.params.get("names") or None
    return open_grid(files, names=names, tmp_dir=ctx.output_dir / "tmp")


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
    return {"files": _relative([path], ctx.output_dir)}


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
    return {"files": _relative(paths, ctx.output_dir)}
