"""The station's Files section (#79, #176): every file a user can download, in one place.
The zip in Climpact for R's layout, the PDF report, the summary files, the quality-control
files, the plots and each index's table and plot, every one with its size, for slow
connections. Other pages link here instead of listing files (DESIGN.md, "Don't offer
downloads everywhere").

Everything is a file a job wrote; nothing is made in the request. The chart images of
the current view (PNG and SVG) are made in the browser by the index pages' charts
(``js/charts.js``); this page says where to find them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from climpact_web.stations.results import RunResults, RunSource


@dataclass(frozen=True)
class Download:
    label: str
    path: str  # relative to the job's output/, for jobs:file
    size: int  # bytes
    kind: str  # zip, pdf, csv, png
    note: str = ""

    @property
    def name(self) -> str:
        return Path(self.path).name


def _download(source: RunSource, path: Path, label: str, kind: str, note: str = ""):
    if not path.is_file():
        return None
    return Download(label, source.relative(path), path.stat().st_size, kind, note)


def zip_path(source: RunSource) -> Path | None:
    """The station's zip: the job's ``zip`` (a station job) or the batch's station zip."""
    job = source.job
    if source.from_batch:
        entry = station_entry(source)
        rel = entry.get("zip")
    else:
        rel = job.result.get("zip")
    return job.output_dir / rel if rel else None


def report_path(source: RunSource) -> Path:
    """Where the job wrote the PDF report (:func:`climpact.report.report_file`): beside
    the station folder, or ``reports/`` of a batch job."""
    job = source.job
    rel = station_entry(source).get("report") if source.from_batch else job.result.get("report")
    if rel:
        return job.output_dir / rel
    if source.from_batch:
        return job.output_dir / "reports" / f"{source.station}_report.pdf"
    return source.folder / f"{source.station}_report.pdf"


def station_entry(source: RunSource) -> dict:
    stations = source.job.result.get("stations", [])
    return next((s for s in stations if s.get("name") == source.station), {})


def main_downloads(source: RunSource) -> dict:
    """The zip, the report and the plots PDF (each ``None`` when the run made none)."""
    station = source.station
    zip_file = zip_path(source)
    return {
        "zip": _download(
            source,
            zip_file,
            _("Everything"),
            "zip",
            _("Every file of the run, in the folder layout of Climpact for R."),
        )
        if zip_file
        else None,
        "report": _download(
            source,
            report_path(source),
            _("Report"),
            "pdf",
            _("The settings, the quality checks, and a page per index with its plot."),
        ),
        "all_plots": _download(
            source,
            source.station_dir / "plots" / f"{station}_all_plots.pdf",
            _("All plots"),
            "pdf",
            _("Every plot as a page, in Climpact for R's order."),
        ),
    }


# The run's summary files: (folder, file name without the station prefix, label, contents).
SUMMARY_FILES = (
    ("trend", "trend", gettext_lazy("Trends"), gettext_lazy("Sen's slope of every index")),
    ("thres", "thres", gettext_lazy("Thresholds"), gettext_lazy("Base-period percentiles")),
)
# The files of the qc folder: (file name without the station prefix, label), in the order
# of the Quality page.
QC_FILES = (
    ("tmaxmin", gettext_lazy("TX at or below TN")),
    ("toolarge", gettext_lazy("Out of range")),
    ("duplicates", gettext_lazy("Repeated dates")),
    ("outliers", gettext_lazy("Outliers")),
    ("tx_jumps", gettext_lazy("Jumps in TX")),
    ("tn_jumps", gettext_lazy("Jumps in TN")),
    ("tx_flatline", gettext_lazy("Flat runs in TX")),
    ("tn_flatline", gettext_lazy("Flat runs in TN")),
    ("nastatistics", gettext_lazy("Missing values")),
)
QC_ORDER = {name: i for i, (name, _label) in enumerate(QC_FILES)}


def summary_downloads(source: RunSource) -> list[Download]:
    out = []
    for folder, name, label, note in SUMMARY_FILES:
        path = source.station_dir / folder / f"{source.station}_{name}.csv"
        if d := _download(source, path, str(label), "csv", str(note)):
            out.append(d)
    return out


def qc_downloads(source: RunSource) -> list[Download]:
    """The run's own ``qc/`` files (also in its zip)."""
    out = []
    for name, label in QC_FILES:
        path = source.station_dir / "qc" / f"{source.station}_{name}.csv"
        if d := _download(source, path, str(label), "csv"):
            out.append(d)
    return out


def _qc_label(path: Path, station: str) -> str:
    name = path.stem.removeprefix(f"{station}_")
    return str(dict(QC_FILES).get(name, path.name))


def quality_downloads(analysis, source: RunSource | None) -> dict | None:
    """The quality-control files: those of the Quality page's check (the ``qc`` job, #77),
    every file it wrote and its zip; or, with no such check (a station from a batch run),
    the run's own ``qc/`` files. None when there are neither."""
    from climpact_web.stations.workspace import shown_qc

    qc_job = shown_qc(analysis)  # out of date while new checks run (#179)
    if qc_job is not None:
        root = qc_job.output_dir
        station = qc_job.result.get("station", "")
        files = []
        for rel in qc_job.result.get("files", []):
            path = root / rel
            if path.is_file():
                kind = path.suffix.lstrip(".")
                files.append(Download(_qc_label(path, station), rel, path.stat().st_size, kind))
        files.sort(key=lambda d: QC_ORDER.get(Path(d.path).stem.removeprefix(f"{station}_"), 99))
        zip_file = None
        if (rel := qc_job.result.get("zip")) and (root / rel).is_file():
            zip_file = Download(_("Quality-control files"), rel, (root / rel).stat().st_size, "zip")
        if not files and zip_file is None:
            return None
        return {"job": qc_job, "zip": zip_file, "files": files, "size": totals(files)}
    if source is None:
        return None
    files = qc_downloads(source)
    if not files:
        return None
    return {"job": source.job, "zip": None, "files": files, "size": totals(files)}


def other_downloads(source: RunSource, listed: set[str], covered: set[str]) -> list[Download]:
    """Every other file in the station's folder: not ``listed`` (paths relative to the
    job's output) and not ``covered`` (file names offered from another job, the quality
    check's), so that every file the run wrote can be downloaded from the Files page."""
    out = []
    for path in sorted(p for p in source.station_dir.rglob("*") if p.is_file()):
        rel = source.relative(path)
        if rel in listed or path.name in covered:
            continue
        out.append(
            Download(
                rel.removeprefix(f"{source.station}/"),
                rel,
                path.stat().st_size,
                path.suffix.lstrip(".") or "file",
            )
        )
    return out


def index_downloads(source: RunSource, run: RunResults) -> list[dict]:
    """Each index, grouped as the dashboard, with each series' table and plot."""
    sections = []
    for section in run.sections():
        cards = []
        for card in section["cards"]:
            rows = []
            for series in card.series:
                table = source.index_source.table_path(series.name.removeprefix("day_of_"))
                png = source.station_dir / "plots" / f"{source.station}_{series.name}.png"
                rows.append(
                    {
                        "series": series,
                        # A day_of_ series has no table of its own: its dates are in the
                        # index's table, which is listed with the index's own series.
                        "csv": None
                        if series.name.startswith("day_of_")
                        else _download(source, table, series.name, "csv"),
                        "png": _download(source, png, series.name, "png"),
                    }
                )
            cards.append({"card": card, "rows": rows})
        size = totals(d for c in cards for r in c["rows"] for d in (r["csv"], r["png"]))
        sections.append(
            {"key": section["key"], "label": section["label"], "cards": cards, "size": size}
        )
    return sections


def sector_downloads(job) -> dict | None:
    """The files of the station's finished sector comparison (step 5, #90): its
    ``corr/`` zip and each CSV and PNG, or None when there is none."""
    from climpact_web.jobs.models import Status

    if job is None or job.status != Status.SUCCEEDED:
        return None
    out = {"job": job, "zip": None, "files": []}
    root = job.output_dir
    if (rel := job.result.get("zip")) and (root / rel).is_file():
        out["zip"] = Download(_("Sector comparison (zip)"), rel, (root / rel).stat().st_size, "zip")
    for rel in job.result.get("files", []):
        path = root / rel
        if path.is_file() and path.suffix in (".csv", ".png"):
            out["files"].append(
                Download(path.name, rel, path.stat().st_size, path.suffix.lstrip("."))
            )
    return out if out["zip"] or out["files"] else None


def totals(items) -> int:
    return sum(d.size for d in items if d is not None)
