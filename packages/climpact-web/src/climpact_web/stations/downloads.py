"""The downloads of a finished station run (#79): the zip in Climpact for R's layout, the
PDF report, the combined plots PDF, the summary and quality-control files, and each index's
table and plot, every one with its size, for slow connections.

Everything is a file the job wrote; nothing is made in the request. The chart images of
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
            _(
                "Every file of the run in Climpact for R's folder layout: indices, plots, "
                "qc, thres and trend."
            ),
        )
        if zip_file
        else None,
        "report": _download(
            source,
            report_path(source),
            _("Report"),
            "pdf",
            _(
                "The station and settings, what the quality checks found, and a page per index "
                "with its plot and trends, with a table of contents."
            ),
        ),
        "all_plots": _download(
            source,
            source.station_dir / "plots" / f"{station}_all_plots.pdf",
            _("All plots"),
            "pdf",
            _("Every plot as a page, in Climpact for R's order."),
        ),
    }


# The run's other files: (folder, file name without the station prefix, label, contents).
SUMMARY_FILES = (
    ("trend", "trend", gettext_lazy("Trends"), gettext_lazy("Sen's slope of every index")),
    ("thres", "thres", gettext_lazy("Thresholds"), gettext_lazy("Base-period percentiles")),
    ("qc", "nastatistics", gettext_lazy("Missing values"), gettext_lazy("Days missing per year")),
)
QC_FILES = (
    ("tmaxmin", gettext_lazy("TX at or below TN")),
    ("toolarge", gettext_lazy("Values too large")),
    ("duplicates", gettext_lazy("Repeated dates")),
    ("outliers", gettext_lazy("Outliers")),
    ("tx_jumps", gettext_lazy("Jumps in TX")),
    ("tn_jumps", gettext_lazy("Jumps in TN")),
    ("tx_flatline", gettext_lazy("Flat runs in TX")),
    ("tn_flatline", gettext_lazy("Flat runs in TN")),
)


def summary_downloads(source: RunSource) -> list[Download]:
    out = []
    for folder, name, label, note in SUMMARY_FILES:
        path = source.station_dir / folder / f"{source.station}_{name}.csv"
        if d := _download(source, path, str(label), "csv", str(note)):
            out.append(d)
    return out


def qc_downloads(source: RunSource) -> list[Download]:
    out = []
    for name, label in QC_FILES:
        path = source.station_dir / "qc" / f"{source.station}_{name}.csv"
        if d := _download(source, path, str(label), "csv"):
            out.append(d)
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
        sections.append({"key": section["key"], "label": section["label"], "cards": cards})
    return sections


def totals(items) -> int:
    return sum(d.size for d in items if d is not None)
