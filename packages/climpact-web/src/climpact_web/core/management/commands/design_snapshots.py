"""Save the landing page, pattern library and other pages as static HTML for design review (#71).

    climpact-web manage design_snapshots <folder>

Writes ``index.html`` (landing page), ``patterns.html`` (pattern library), ``404.html``,
the job pages with example jobs (``job-running.html``, ``job-finished.html``,
``job-failed.html``, ``jobs.html``), the single-station step 1 pages with the sample data
(``station-upload.html``, ``station-upload-problems.html``, ``station-load.html``,
``station-load-errors.html``, ``station-qc.html``, and ``station-calculating.html``: the
indices' progress with "Adjust and recalculate", #178), the batch pages (``batch-start.html``,
``batch-check.html``, ``batch-running.html``, ``batch-results.html``), the help pages
(``help.html``, ``help-guide.html``, ``help-indices.html``, ``help-topics.html``,
``help-search.html``, #81) and a dark-theme copy of each
(``*-dark.html``), with the static files copied alongside, so the pages open straight from
disk (``file://``) in any browser without a server. The icon sprite is inlined, since
browsers will not load an external sprite from ``file://``. Nothing touches the database:
the example jobs and station analyses are never saved.
"""

import datetime as dt
import re
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.shortcuts import render
from django.test import Client, RequestFactory, override_settings
from django.utils import timezone

STATIC_APP = Path(__file__).resolve().parents[2] / "static" / "climpact_web"
SPRITE_URL = "static/climpact_web/icons/icons.svg"

PAGES = {
    "index": "/",
    "patterns": "/patterns/",
    "404": "/this-page-does-not-exist/",
    "help": "/help/",
    "help-guide": "/help/quality-control/",
    "help-indices": "/help/indices/",
    "help-topics": "/help/topics/",
    "help-search": "/help/search/?q=base+period",
}


def to_static_files(html: str) -> str:
    """Point static URLs at the copied folder and inline the icon sprite."""
    static_url = "/" + settings.STATIC_URL.lstrip("/")
    html = html.replace(f'"{static_url}', '"static/')
    sprite = (STATIC_APP / "icons" / "icons.svg").read_text()
    sprite = re.sub(r"<!--.*?-->", "", sprite, flags=re.S)
    sprite = sprite.replace("<svg ", '<svg hidden aria-hidden="true" ', 1)
    html = html.replace(f'href="{SPRITE_URL}#', 'href="#')
    return re.sub(r"(<body[^>]*>)", lambda m: m.group(1) + sprite, html, count=1)


def job_pages() -> dict[str, str]:
    """The job pages (#73) for example jobs in each state, rendered without a database."""
    from climpact_web.jobs.models import Job, Status
    from climpact_web.jobs.stages import stage_label

    now = timezone.now()
    ago = lambda **kw: now - dt.timedelta(**kw)  # noqa: E731
    running = Job(kind="station", title="Sydney Observatory Hill", status=Status.RUNNING,
                  stage="indices:climpact:txx", step=9, total=14, created_at=ago(minutes=2),
                  started_at=ago(seconds=72))  # fmt: skip
    finished = Job(kind="station", title="Sydney Observatory Hill", status=Status.SUCCEEDED,
                   step=14, total=14, created_at=ago(minutes=5), started_at=ago(minutes=4),
                   finished_at=ago(minutes=2), result={"zip": "Sydney.zip"})  # fmt: skip
    files = [{"name": n, "size": size} for n, size in (
        ("Sydney_report.pdf", 467_000), ("Sydney/indices/Sydney_txx_ANN.csv", 4_200),
        ("Sydney/indices/Sydney_tnn_ANN.csv", 4_100), ("Sydney/plots/Sydney_txx_ANN.png", 61_000),
        ("Sydney/trend/Sydney_trend.csv", 14_000), ("Sydney/qc/Sydney_tmax_outliers.csv", 9_000),
        ("Sydney.zip", 7_400_000))]  # fmt: skip
    failed = Job(kind="station", title="Perth Airport", status=Status.FAILED, stage="failed",
                 created_at=ago(hours=1), started_at=ago(minutes=59), finished_at=ago(minutes=59),
                 error="Line 1204 has 3 values; each line needs year, month, day, "
                 "precipitation, maximum and minimum temperature.")  # fmt: skip
    queued = Job(kind="batch", title="13 GHCN stations", status=Status.QUEUED,
                 created_at=ago(seconds=20))  # fmt: skip

    def progress(job, **extra):
        return {"job": job, "stage_label": stage_label(job.stage), "elapsed": "",
                "remaining": "", "delay": 1, "worker_missing": False, "zip_file": None,
                "files": [], **extra}  # fmt: skip

    request = RequestFactory().get("/jobs/")
    pages = {
        "job-running": ("jobs/job_detail.html",
                        progress(running, elapsed="1 min 12 s", remaining="40 s")),
        "job-finished": ("jobs/job_detail.html",
                         progress(finished, elapsed="2 min 3 s", zip_file="Sydney.zip",
                                  zip_size=7_400_000, files=files)),
        "job-failed": ("jobs/job_detail.html", progress(failed, elapsed="1 s")),
        "jobs": ("jobs/job_list.html", {"jobs": [queued, running, finished, failed]}),
    }  # fmt: skip
    return {name: render(request, t, c).content.decode() for name, (t, c) in pages.items()}


def station_pages() -> dict[str, str]:
    """Steps 1 and 2 of the single-station flow (#76, #77: before the checks have run) and
    the indices being calculated, with "Adjust and recalculate" (#78, #178), with the sample
    data, rendered without a database. The results of the checks and of the indices need a
    finished job's files; their screenshots are in the PRs (#77, #78)."""
    from climpact_web.jobs.models import Job, Status
    from climpact_web.stations import calculation, views, views_indices, workspace
    from climpact_web.stations.forms import MetadataForm, UploadForm
    from climpact_web.stations.models import Source, StationAnalysis, Step
    from climpact_web.stations.station_file import inspect_station_bytes

    request = RequestFactory().get("/station/")
    inspection = inspect_station_bytes(views.sample_bytes())
    sample = StationAnalysis(source=Source.SAMPLE, file_name=views.SAMPLE_NAME,
                             summary=inspection.summary, updated_at=timezone.now(),
                             **views.SAMPLE_METADATA)  # fmt: skip
    upload = {"form": UploadForm(), "inspection": None, "file_name": "", "recent": [],
              "sample_name": views.SAMPLE_NAME,
              "max_upload_mb": settings.MAX_UPLOAD_MB}  # fmt: skip
    bad = inspect_station_bytes(
        b"year month day prcp tmax tmin\n1961 1 1 0 31.2 18.0\n1961 1 2 0.4 30.1\n"
        b"1961 1 3 na 29.8 17.1\n1961 1 4 1,2 28.0 16.5\n"
    )
    form = MetadataForm(views.initial_metadata(sample), summary=sample.summary)
    form.is_valid()

    uploaded = StationAnalysis(source=Source.UPLOAD, file_name="perth_airport.txt",
                               summary=inspection.summary, station_name="perth_airport",
                               updated_at=timezone.now(),
                               warnings=["2 rows have dates that do not exist (the first is "
                                         "line 7362: 1956-2-29). They are left out, as in "
                                         "Climpact for R."])  # fmt: skip
    errors = MetadataForm(data={"station_name": ".perth", "latitude": "-133.9",
                                "longitude": "", "base_start": "1900", "base_end": "1920"},
                          summary=uploaded.summary)  # fmt: skip
    errors.is_valid()
    sample.step = Step.QC
    running = Job(kind="station", title=sample.station_name, status=Status.RUNNING,
                  stage="indices:climpact:txx", step=9, total=14, started_at=timezone.now(),
                  params={"plots": True, "zip": True, "report": True})  # fmt: skip
    pages = {
        "station-upload": ("stations/upload.html", upload),
        "station-upload-problems": ("stations/upload.html",
                                    {**upload, "inspection": bad,
                                     "file_name": "perth_airport.txt"}),
        "station-load": ("stations/load.html", views.load_context(request, sample, form)),
        "station-load-errors": ("stations/load.html",
                                views.load_context(request, uploaded, errors)),
        "station-qc": ("stations/qc.html", views.qc_context(request, sample)),
        "station-calculating": ("stations/results_progress.html", {
            "analysis": sample, "job": running, "phases": views_indices.phases(running),
            **workspace.context(sample, "results"), "stage_label": "Calculating indices (txx)",
            "elapsed": "4 s", "remaining": "", "delay": 1, "worker_missing": False,
            "form": calculation.settings_form(sample), "settings_source": "default",
            "open_settings": False}),
    }  # fmt: skip
    return {name: render(request, t, c).content.decode() for name, (t, c) in pages.items()}


def batch_pages() -> dict[str, str]:
    """The batch page (#80): the start page, a check with every status, a running batch and
    its results, rendered without a database."""
    from climpact_web.batch import check, views
    from climpact_web.batch.forms import UploadForm
    from climpact_web.batch.models import BatchRun
    from climpact_web.core.navigation import batch_steps
    from climpact_web.jobs.models import Job, Status

    request = RequestFactory().get("/batch/")
    now = timezone.now()
    start = {"form": UploadForm(), "steps": batch_steps("upload"), "recent": [],
             "max_upload_mb": settings.MAX_UPLOAD_MB, "sample_metadata": views.SAMPLE_METADATA,
             "columns": views.column_rows()}  # fmt: skip

    sydney = views.sample_files()["sydney_observatory_hill_1936-2015.txt"]
    header = "\t".join(check.COLUMNS) + "\n"
    meta = header + "".join(
        f"{name}\t{lat}\t{lon}\t3\t3\t18\t18\t10\t3\t30\t2\t24\n"
        for name, lat, lon in [
            ("alice_springs_1961-2020.txt", -23.8, 133.89),
            ("darwin_1961-2020.txt", -12.42, 130.89),
            ("perth_airport_1961-2020.txt", -31.93, 115.98),
            ("Sydney.txt", -33.86, 151.21),
            ("madrid_retiro_1961-2020.txt", 40.41, -3.68),
        ]
    )
    files = {
        "alice_springs_1961-2020.txt": sydney,
        "darwin_1961-2020.txt": sydney,
        "perth_airport_1961-2020.txt": b"1961 1 1 0 31.2 18.0\n1961 1 2 0.4 30.1\n"
        + b"1961 1 3 na 29.8 17.1\n",
        "sydney.txt": sydney,
        "notes.txt": b"x",
    }
    run = BatchRun(metadata_name="australia.txt", report=check.check_batch(
        meta.encode(), files).to_json(), updated_at=now, workers=4)  # fmt: skip
    checked = views.check_context(request, run)

    job = Job(kind="batch", title="australia.txt", status=Status.RUNNING, step=41, total=92,
              stage="darwin_1961-2020: indices:climpact:txx", created_at=now,
              started_at=now - dt.timedelta(seconds=38),
              params={"base_start": 1971, "base_end": 2000})  # fmt: skip
    run.job = job

    def row(name, state, **extra):
        return {"name": name, "state": state, "step": 0, "total": 46, "stage_label": "",
                "percent": 0, "error_text": "", "skip_lines": [], "zip": None,
                "error_file": None, "opened_url": None, **extra}  # fmt: skip

    skip = ["No file named Sydney.txt was uploaded, but sydney.txt was. Names must match the "
            "metadata file exactly, including capitals and the extension."]  # fmt: skip
    running_rows = [
        row("alice_springs_1961-2020", "done", step=46, percent=100),
        row("darwin_1961-2020", "running", step=17, percent=36,
            stage_label="Calculating indices (txx)"),
        row("madrid_retiro_1961-2020", "waiting"),
        row("perth_airport_1961-2020", "skipped", skip_lines=["Line 2 has 5 values; each line "
            "needs 6: year, month, day, precipitation, maximum and minimum temperature."]),
        row("Sydney", "skipped", skip_lines=skip),
    ]  # fmt: skip
    common = {"run": run, "job": job, "elapsed": "38 s", "remaining": "47 s", "delay": 1,
              "worker_missing": False, "zip_file": None, "total_stations": 3,
              "stage_label": "darwin_1961-2020: Calculating indices (txx)",
              "steps": batch_steps("results", {"upload": "/batch/", "check": "#"})}  # fmt: skip

    def counts(done, failed, running, waiting):
        return {"done": done, "failed": failed, "skipped": 2, "running": running,
                "waiting": waiting}  # fmt: skip

    running = {**common, "rows": running_rows, "counts": counts(1, 0, 1, 1)}

    finished_job = Job(kind="batch", title="australia.txt", status=Status.SUCCEEDED, step=92,
                       total=92, created_at=now, started_at=now - dt.timedelta(seconds=95),
                       finished_at=now, params={"base_start": 1971, "base_end": 2000},
                       result={"zip": "australia.zip"})  # fmt: skip
    finished_run = BatchRun(metadata_name="australia.txt", report=run.report, updated_at=now)
    finished_run.job = finished_job
    finished_rows = [
        row("madrid_retiro_1961-2020", "failed", error_file="australia/madrid.errors.txt",
            error_text="The rows are not in date order: the last row (1961-01-01) is dated "
            "before the first (2020-12-31). Sort the file by date."),
        row("alice_springs_1961-2020", "done", zip="stations/alice_springs_1961-2020.zip"),
        row("darwin_1961-2020", "done", zip="stations/darwin_1961-2020.zip",
            opened_url="#"),
        *running_rows[3:],
    ]  # fmt: skip
    finished = {**common, "run": finished_run, "job": finished_job, "rows": finished_rows,
                "elapsed": "1 min 35 s", "remaining": "", "zip_file": "australia.zip",
                "counts": counts(2, 1, 0, 0)}  # fmt: skip
    pages = {
        "batch-start": ("batch/start.html", start),
        "batch-check": ("batch/check.html", checked),
        "batch-running": ("batch/results.html", running),
        "batch-results": ("batch/results.html", finished),
    }
    return {name: render(request, t, c).content.decode() for name, (t, c) in pages.items()}


def dark(html: str) -> str:
    return html.replace("<html ", '<html data-theme="dark" ', 1)


class Command(BaseCommand):
    help = "Save the landing page and pattern library as static HTML for design review."

    def add_arguments(self, parser):
        parser.add_argument("folder", type=Path)

    def handle(self, *args, folder: Path, **options):
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / "static" / "climpact_web"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(STATIC_APP, target)
        with override_settings(
            # Plain static names, matching the copied folder (not collected, hashed ones)
            STORAGES={
                **settings.STORAGES,
                "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
            },
            PATTERN_LIBRARY=True,
            ALLOWED_HOSTS=["testserver"],
            SESSION_ENGINE="django.contrib.sessions.backends.signed_cookies",
            MESSAGE_STORAGE="django.contrib.messages.storage.cookie.CookieStorage",
        ):
            client = Client()
            pages = {}
            for name, url in PAGES.items():
                response = client.get(url)
                expected = 404 if name == "404" else 200
                if response.status_code != expected:
                    raise RuntimeError(f"{url} answered {response.status_code}")
                pages[name] = response.content.decode()
            pages.update(job_pages())
            pages.update(station_pages())
            pages.update(batch_pages())
        for name, html in pages.items():
            html = to_static_files(html)
            (folder / f"{name}.html").write_text(html)
            (folder / f"{name}-dark.html").write_text(dark(html))
        self.stdout.write(f"wrote {', '.join(pages)} (light and dark) to {folder}")
