"""Save the landing page and pattern library as static HTML for design review (#71).

    climpact-web manage design_snapshots <folder>

Writes ``index.html`` (landing page), ``patterns.html`` (pattern library), ``404.html``,
the job pages with example jobs (``job-running.html``, ``job-finished.html``,
``job-failed.html``, ``jobs.html``), the single-station step 1 pages with the sample data
(``station-upload.html``, ``station-upload-problems.html``, ``station-load.html``,
``station-load-errors.html``, ``station-qc.html``) and a dark-theme copy of each
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

PAGES = {"index": "/", "patterns": "/patterns/", "404": "/this-page-does-not-exist/"}


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
    files = ["Sydney/indices/Sydney_txx_ANN.csv", "Sydney/indices/Sydney_tnn_ANN.csv",
             "Sydney/plots/Sydney_txx_ANN.png", "Sydney/trend/Sydney_trend.csv",
             "Sydney/qc/Sydney_tmax_outliers.csv", "Sydney.zip"]  # fmt: skip
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
                                  files=files)),
        "job-failed": ("jobs/job_detail.html", progress(failed, elapsed="1 s")),
        "jobs": ("jobs/job_list.html", {"jobs": [queued, running, finished, failed]}),
    }  # fmt: skip
    return {name: render(request, t, c).content.decode() for name, (t, c) in pages.items()}


def station_pages() -> dict[str, str]:
    """Step 1 of the single-station flow (#76), with the sample data, rendered without a
    database."""
    from climpact_web.core.navigation import station_steps
    from climpact_web.stations import views
    from climpact_web.stations.forms import MetadataForm, RunAllForm, UploadForm
    from climpact_web.stations.models import Source, StationAnalysis, Step
    from climpact_web.stations.station_file import inspect_station_bytes

    request = RequestFactory().get("/station/")
    inspection = inspect_station_bytes(views.sample_bytes())
    sample = StationAnalysis(source=Source.SAMPLE, file_name=views.SAMPLE_NAME,
                             summary=inspection.summary, updated_at=timezone.now(),
                             **views.SAMPLE_METADATA)  # fmt: skip
    upload = {"form": UploadForm(), "inspection": None, "file_name": "", "recent": [],
              "steps": station_steps("upload"), "sample_name": views.SAMPLE_NAME,
              "max_upload_mb": settings.MAX_UPLOAD_MB}  # fmt: skip
    bad = inspect_station_bytes(
        b"year month day prcp tmax tmin\n1961 1 1 0 31.2 18.0\n1961 1 2 0.4 30.1\n"
        b"1961 1 3 NA 29.8 17.1\n1961 1 4 1,2 28.0 16.5\n"
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
    pages = {
        "station-upload": ("stations/upload.html", upload),
        "station-upload-problems": ("stations/upload.html",
                                    {**upload, "inspection": bad,
                                     "file_name": "perth_airport.txt"}),
        "station-load": ("stations/load.html", views.load_context(request, sample, form)),
        "station-load-errors": ("stations/load.html",
                                views.load_context(request, uploaded, errors)),
        "station-qc": ("stations/qc.html",
                       {"analysis": sample, "steps": station_steps("qc", sample.step_urls()),
                        "run_form": RunAllForm()}),
    }  # fmt: skip
    return {name: render(request, t, c).content.decode() for name, (t, c) in pages.items()}


def dark(html: str) -> str:
    html = html.replace("<html ", '<html data-theme="dark" ', 1)
    return html.replace(
        'media="(prefers-color-scheme: dark)" id="theme-dark"', 'media="all" id="theme-dark"'
    )


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
        for name, html in pages.items():
            html = to_static_files(html)
            (folder / f"{name}.html").write_text(html)
            (folder / f"{name}-dark.html").write_text(dark(html))
        self.stdout.write(f"wrote {', '.join(pages)} (light and dark) to {folder}")
