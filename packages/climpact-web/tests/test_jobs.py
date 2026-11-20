"""Background jobs: the queue, the worker, progress pages, failures, retry, cancel and
retention."""

import datetime as dt
import re
import threading
import uuid
from pathlib import Path

import made
import numpy as np
import pandas as pd
import pytest
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from climpact_web.jobs import registry, worker
from climpact_web.jobs.models import Job, Status, Worker
from climpact_web.jobs.registry import JobContext, JobError, register
from climpact_web.jobs.retention import purge_expired
from climpact_web.jobs.stages import stage_label
from climpact_web.jobs.views import OWNER_KEY, poll_delay
from climpact_web.jobs.worker import JobWorker, claim, reap_stale, release_jobs_of, run_job

REPO = Path(__file__).resolve().parents[3]
SECTOR_FILE = REPO / "reference" / "input" / "sector" / "wheat_yield_nsw_1922-1999.csv"
BATCH_HEADER = (
    "station_file\tlatitude\tlongitude\twsdin\tcsdin\tTb_HDD\tTb_CDD\tTb_GDD\trxnday"
    "\trnnmm\ttxtn\tSPEI\n"
)


def batch_metadata(*names: str) -> str:
    return BATCH_HEADER + "".join(
        f"{n}.txt\t-30\t150\t3\t3\t18\t18\t10\t3\t30\t2\t24\n" for n in names
    )


def station_text(start="2000-01-01", end="2001-12-31", seed=0) -> str:
    """Synthetic daily data in Climpact's format (as the core's tests write it)."""
    dates = pd.date_range(start, end)
    rng = np.random.default_rng(seed)
    n = len(dates)
    tx = rng.normal(22, 4, n)
    tn = tx - rng.uniform(5, 10, n)
    rows = [
        f"{d.year} {d.month} {d.day} {p:.1f} {x:.1f} {m:.1f}"
        for d, p, x, m in zip(dates, rng.gamma(0.5, 4, n), tx, tn, strict=True)
    ]
    return "\n".join(rows) + "\n"


@pytest.fixture(autouse=True)
def job_settings(settings, tmp_path):
    settings.RUNS_DIR = tmp_path / "runs"
    settings.JOB_PROGRESS_INTERVAL = 0  # write every step, so tests see each one
    settings.JOB_RETENTION_DAYS = 7
    return settings


@pytest.fixture
def test_runners():
    """Runner kinds registered for a test only."""
    added = []

    def add(kind, func):
        register(kind)(func)
        added.append(kind)

    yield add
    for kind in added:
        registry.RUNNERS.pop(kind, None)


def owned_client(owner="owner-a") -> Client:
    client = Client()
    session = client.session
    session[OWNER_KEY] = owner
    session.save()
    client.cookies["sessionid"] = session.session_key
    return client


def make_job(kind="station", owner="owner-a", files=None, **fields) -> Job:
    job = Job.objects.create(kind=kind, owner=owner, **fields)
    job.input_dir.mkdir(parents=True, exist_ok=True)
    for name, text in (files or {}).items():
        (job.input_dir / name).write_text(text)
    return job


def station_job(owner="owner-a", plots=False, zip=False, text=None, **params) -> Job:
    return make_job(
        owner=owner,
        files={"station.txt": text or station_text()},
        params={
            "station_file": "station.txt",
            "metadata": {"name": "stn", "base_start": 2000, "base_end": 2001},
            "params": params,
            "plots": plots,
            "zip": zip,
        },
        title="stn",
    )


def run_next(name="test-worker", stop=None) -> Job:
    job = claim(name)
    assert job is not None
    return run_job(job, stop)


# --- A station run from the browser ----------------------------------------------------------


@pytest.mark.django_db
def test_station_run_from_the_browser_shows_each_stage(client, monkeypatch):
    from climpact.batch import run_station  # noqa: F401  (imported once, outside the timing)
    from climpact.modules import pipeline_stages, resolve

    # Step 1 (#76) loads the file and metadata, which queues the quality checks (#77) and a
    # speculative run with the default settings (#178); "Use this data" opens the results,
    # and the Index settings sheet there (#199) queues the run this test follows.
    load_url = made.station_to_set_up(client, station_text(), "my_station.txt").url("setup")
    metadata = {"station_name": "Testville", "latitude": "-33.9", "longitude": "151.2"}
    response = client.post(load_url, {**metadata, "base_start": "2000", "base_end": "2001"})
    assert response.status_code == 302
    qc_job = Job.objects.get(kind="qc")
    assert run_job(claim("w0"), None).status == Status.SUCCEEDED
    speculative = Job.objects.get(kind="station")
    assert speculative.is_speculative
    response = client.post(load_url.replace("/setup", "/quality/continue"))
    page = client.get(response["Location"]).content.decode()
    assert "Calculating indices" in page and 'id="sheet-settings"' in page
    from test_indices_results import defaults

    run_url = load_url.replace("/setup", "/inputs/settings")
    response = client.post(run_url, {**defaults(), "plots": ""})
    assert response.status_code == 302
    speculative.refresh_from_db()
    assert speculative.status == Status.CANCELLED  # replaced before it started
    job = Job.objects.exclude(pk__in=[qc_job.pk, speculative.pk]).get()
    assert response["Location"] == load_url.replace("/setup", "/indices")
    response = client.get(f"/jobs/{job.pk}/")
    assert (job.status, job.kind, job.title) == (Status.QUEUED, "station", "Testville")
    assert job.params["plots"] is False and job.params["zip"] is True
    assert (job.input_dir / "station.txt").read_text() == station_text()
    page = response.content.decode()
    assert "Waiting to start" in page and 'hx-get="/jobs/' in page

    # Each progress write, and what the progress fragment shows at that moment.
    seen = []
    flush = worker.ProgressWriter.flush

    def recording_flush(self):
        flush(self)
        fragment = client.get(f"/jobs/{job.pk}/progress").content.decode()
        seen.append((self.stage, self.step, self.total, fragment))

    monkeypatch.setattr(worker.ProgressWriter, "flush", recording_flush)
    assert JobWorker(name="w1", once=True, cleanup=False).run() == 1

    stages = ["read", *pipeline_stages(resolve(None)), "write", "zip"]
    assert [s[0] for s in seen] == stages
    assert [s[1] for s in seen] == list(range(1, len(stages) + 1))
    assert {s[2] for s in seen} == {len(stages)}
    for stage, step, total, fragment in seen[:-1]:
        assert f"Step {step} of {total}" in fragment
        assert stage_label(stage) in fragment
        assert 'hx-trigger="load delay:' in fragment  # still polling
    job.refresh_from_db()
    assert job.status == Status.SUCCEEDED, job.log
    assert (job.step, job.total, job.percent) == (len(stages), len(stages), 100)
    assert job.result["zip"] == "Testville.zip"
    assert "Testville/indices/Testville_fd_ANN.csv" in job.result["files"]
    assert "succeeded after" in job.log

    fragment = client.get(f"/jobs/{job.pk}/progress").content.decode()
    assert "hx-get" not in fragment  # finished: polling stops
    assert re.search(r"Download all results \(zip, [0-9.]+\xa0[KM]B\)", fragment)
    download = client.get(f"/jobs/{job.pk}/files/Testville.zip")
    assert download.status_code == 200
    assert download["Content-Disposition"].startswith("attachment")
    assert b"".join(download.streaming_content)[:2] == b"PK"
    assert client.get(f"/jobs/{job.pk}/files/../input/station.txt").status_code == 404
    assert client.get(f"/jobs/{job.pk}/files/nope.csv").status_code == 404
    assert "Testville" in client.get("/jobs/").content.decode()


# --- Polling ------------------------------------------------------------------------------------


@pytest.mark.django_db
def test_progress_fragment_polls_until_finished():
    client = owned_client()
    job = make_job(status=Status.QUEUED)
    html = client.get(f"/jobs/{job.pk}/progress").content.decode()
    assert 'hx-trigger="load delay:1s, climpact:visible from:document"' in html
    assert "data-poll-hidden" in html and "js:" not in html  # no eval under the CSP (#137)
    hidden = client.get(f"/jobs/{job.pk}/progress?hidden=true").content.decode()
    assert "load delay:30s" in hidden  # backs off while the tab is hidden
    Job.objects.filter(pk=job.pk).update(status=Status.CANCELLED, finished_at=timezone.now())
    html = client.get(f"/jobs/{job.pk}/progress").content.decode()
    assert "hx-get" not in html and "Try again" in html


def test_poll_delay_backs_off():
    now = timezone.now()
    job = Job(status=Status.RUNNING, started_at=now - dt.timedelta(seconds=3))
    assert poll_delay(job, hidden=False, now=now) == 1
    job.started_at = now - dt.timedelta(seconds=30)
    assert poll_delay(job, hidden=False, now=now) == 2
    job.started_at = now - dt.timedelta(minutes=5)
    assert poll_delay(job, hidden=False, now=now) == 5
    assert poll_delay(job, hidden=True, now=now) == 30


def test_estimate():
    now = timezone.now()
    job = Job(status=Status.RUNNING, started_at=now - dt.timedelta(seconds=10), step=1, total=4)
    assert job.remaining(now) is None  # too early to tell
    job.step = 2
    assert job.remaining(now) == dt.timedelta(seconds=10)
    assert job.percent == 50


@pytest.mark.django_db
def test_waiting_without_a_worker_says_so():
    client = owned_client()
    job = make_job(status=Status.QUEUED)
    assert "No calculation worker is running" in client.get(f"/jobs/{job.pk}/").content.decode()
    Worker.objects.create(name="w")
    assert "No calculation worker" not in client.get(f"/jobs/{job.pk}/").content.decode()


@pytest.mark.parametrize(
    "stage, label",
    [
        ("read", "Reading the data"),
        ("qc:climpact", "Checking the data quality"),
        # Words only: the stage's ids (module, index, file) are not shown (#226).
        ("indices:climpact:spi", "Calculating the indices"),
        ("indices:mymodule", "Calculating the indices"),
        ("plots:fd_ANN", "Drawing the plots"),
        ("write:tmin", "Writing the results"),
        ("thresholds", "Calculating the thresholds"),
        ("trends", "Trends and the map"),
        ("stn_a: indices:climpact:fd", "stn_a: Calculating the indices"),
        ("something-new", "something-new"),
        ("", ""),
    ],
)
def test_stage_labels(stage, label):
    assert stage_label(stage) == label


# --- Ownership ----------------------------------------------------------------------------------


@pytest.mark.django_db
def test_jobs_are_private_to_their_session():
    job = make_job(status=Status.SUCCEEDED, result={"files": []})
    mine, other, anonymous = owned_client("owner-a"), owned_client("owner-b"), Client()
    assert mine.get(f"/jobs/{job.pk}/").status_code == 200
    for client in (other, anonymous):
        assert client.get(f"/jobs/{job.pk}/").status_code == 404
        assert client.get(f"/jobs/{job.pk}/progress").status_code == 404
        assert client.post(f"/jobs/{job.pk}/retry").status_code == 404
        assert client.post(f"/jobs/{job.pk}/cancel").status_code == 404
        assert "stn" not in client.get("/jobs/").content.decode()
    assert mine.get(f"/jobs/{uuid.uuid4()}/").status_code == 404


# --- Failures and retry ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_core_validation_error_is_shown_as_a_message():
    job = station_job(wsdi_days=0)
    job = run_next()
    assert job.status == Status.FAILED
    assert job.error == "WSDId: value must be between 1 and 10"
    assert "Traceback" in job.log and "ValueError" in job.log
    html = owned_client().get(f"/jobs/{job.pk}/").content.decode()
    assert "WSDId: value must be between 1 and 10" in html
    assert "Traceback" not in html and "Try again" in html


@pytest.mark.django_db
def test_unreadable_station_file_fails_readably():
    station_job(text="this is not climate data\n")
    job = run_next()
    assert job.status == Status.FAILED
    assert job.error and "Traceback" not in job.error
    assert str(job.folder) not in job.error  # no server paths


@pytest.mark.django_db
def test_unexpected_error_is_logged_not_shown(test_runners):
    def broken(ctx):
        ctx.progress("read", 1, 3)
        raise RuntimeError("secret internals at /srv/app")

    test_runners("broken", broken)
    make_job(kind="broken")
    job = run_next()
    assert job.status == Status.FAILED
    assert "secret internals" not in job.error
    assert str(job.pk) in job.error and "try again" in job.error
    assert "RuntimeError: secret internals" in job.log
    assert (job.stage, job.step, job.total) == ("read", 1, 3)  # where it stopped


@pytest.mark.django_db
def test_retry_runs_the_job_again(test_runners):
    calls = []

    def flaky(ctx):
        calls.append(1)
        if len(calls) == 1:
            raise JobError("Not this time.")
        (ctx.output_dir / "out.txt").write_text("ok")
        return {"files": ["out.txt"]}

    test_runners("flaky", flaky)
    job = make_job(kind="flaky")
    assert run_next().error == "Not this time."
    client = owned_client()
    assert client.post(f"/jobs/{job.pk}/retry").status_code == 302
    job.refresh_from_db()
    assert (job.status, job.error, job.step) == (Status.QUEUED, "", 0)
    job = run_next()
    assert job.status == Status.SUCCEEDED and job.attempts == 2
    assert job.log.count("started by") == 2
    assert client.get(f"/jobs/{job.pk}/files/out.txt").status_code == 200
    # A succeeded job cannot be retried.
    client.post(f"/jobs/{job.pk}/retry")
    job.refresh_from_db()
    assert job.status == Status.SUCCEEDED


# --- Cancelling and stopping ------------------------------------------------------------------


@pytest.mark.django_db
def test_cancel_a_queued_job():
    job = make_job()
    owned_client().post(f"/jobs/{job.pk}/cancel")
    job.refresh_from_db()
    assert job.status == Status.CANCELLED and job.finished_at is not None
    assert claim("w") is None


@pytest.mark.django_db
def test_cancel_a_running_job_at_its_next_step(test_runners):
    def long(ctx):
        ctx.progress("one", 1, 3)
        owned_client().post(f"/jobs/{ctx.job_id}/cancel")  # the user clicks Cancel
        ctx.progress("two", 2, 3)
        ctx.progress("three", 3, 3)
        return {}

    test_runners("long", long)
    make_job(kind="long")
    job = run_next()
    assert job.status == Status.CANCELLED
    assert "cancelled" in job.log


@pytest.mark.django_db
def test_cancel_stops_a_batch_not_just_a_station(tmp_path):
    """JobCancelled is a BaseException: the core's per-station `except Exception` in
    run_batch must not swallow it and carry on with the next station."""
    job = make_job(
        kind="batch",
        files={
            "metadata.txt": batch_metadata("a", "b"),
            "a.txt": station_text(),
            "b.txt": station_text(seed=1),
        },
        params={"metadata_file": "metadata.txt", "base_start": 2000, "base_end": 2001},
    )
    flush = worker.ProgressWriter.flush

    def cancel_on_first_write(self):
        Job.objects.filter(pk=job.pk).update(cancel_requested=True)
        flush(self)

    worker.ProgressWriter.flush = cancel_on_first_write
    try:
        job = run_next()
    finally:
        worker.ProgressWriter.flush = flush
    assert job.status == Status.CANCELLED
    assert not (job.output_dir / "batch" / "b").exists()


@pytest.mark.django_db
def test_stopping_the_worker_queues_the_job_again(test_runners):
    stop = threading.Event()

    def long(ctx):
        ctx.progress("one", 1, 2)
        stop.set()  # SIGTERM arrives
        ctx.progress("two", 2, 2)
        return {}

    test_runners("long", long)
    make_job(kind="long")
    job = run_next(stop=stop)
    assert (job.status, job.worker, job.step) == (Status.QUEUED, "", 0)
    assert "queued again" in job.log


# --- Claiming and dead workers -------------------------------------------------------------


@pytest.mark.django_db
def test_claim_takes_each_job_once_oldest_first():
    now = timezone.now()
    new = make_job(created_at=now)
    old = make_job(created_at=now - dt.timedelta(minutes=1))
    make_job(status=Status.RUNNING)
    first, second = claim("w1"), claim("w2")
    assert (first.pk, second.pk) == (old.pk, new.pk)
    assert (first.worker, first.status, first.attempts) == ("w1", Status.RUNNING, 1)
    assert claim("w3") is None


@pytest.mark.django_db
def test_stale_running_job_fails_with_retry(settings):
    settings.JOB_STALE_SECONDS = 60
    now = timezone.now()
    stale = make_job(status=Status.RUNNING, heartbeat_at=now - dt.timedelta(minutes=5))
    alive = make_job(status=Status.RUNNING, heartbeat_at=now)
    assert reap_stale(now) == 1
    stale.refresh_from_db()
    alive.refresh_from_db()
    assert stale.status == Status.FAILED and stale.error == worker.STALE_MESSAGE
    assert stale.can_retry and alive.status == Status.RUNNING
    assert "no heartbeat" in stale.log


@pytest.mark.django_db
def test_progress_page_never_hangs_on_a_dead_worker():
    job = make_job(status=Status.RUNNING, heartbeat_at=timezone.now() - dt.timedelta(hours=1))
    html = owned_client().get(f"/jobs/{job.pk}/progress").content.decode()
    assert "stopped unexpectedly" in html and "Try again" in html and "hx-get" not in html


@pytest.mark.django_db
def test_release_jobs_of_a_stopped_worker():
    crashed = make_job(status=Status.RUNNING, worker="w1")
    stopped = make_job(status=Status.RUNNING, worker="w2")
    release_jobs_of("w1", crashed=True)
    release_jobs_of("w2", crashed=False)
    crashed.refresh_from_db()
    stopped.refresh_from_db()
    assert (crashed.status, crashed.error) == (Status.FAILED, worker.CRASH_MESSAGE)
    assert (stopped.status, stopped.worker) == (Status.QUEUED, "")


@pytest.mark.django_db
def test_heartbeat_updates_and_sees_cancel():
    job = make_job(status=Status.RUNNING, heartbeat_at=timezone.now() - dt.timedelta(minutes=1))
    beat = worker.Heartbeat("w1", 10)
    beat.job_id = job.pk
    beat.beat()
    job.refresh_from_db()
    assert timezone.now() - job.heartbeat_at < dt.timedelta(seconds=5)
    assert Worker.objects.filter(name="w1").exists() and not beat.cancel.is_set()
    Job.objects.filter(pk=job.pk).update(cancel_requested=True)
    beat.beat()
    assert beat.cancel.is_set()


# --- The other runners -------------------------------------------------------------------------


@pytest.mark.django_db
def test_batch_runner_counts_every_station():
    make_job(
        kind="batch",
        files={
            "metadata.txt": batch_metadata("a", "b", "missing"),
            "a.txt": station_text(),
            "b.txt": station_text(seed=1),
        },
        params={"metadata_file": "metadata.txt", "base_start": 2000, "base_end": 2001, "zip": True},
    )
    job = run_next()
    assert job.status == Status.SUCCEEDED, job.log
    assert job.step == job.total > 40
    stations = {s["name"]: s for s in job.result["stations"]}
    assert stations["a"]["ok"] and stations["b"]["ok"] and not stations["missing"]["ok"]
    assert (job.output_dir / "batch.zip").is_file()


@pytest.mark.django_db
def test_sector_runner_uses_a_finished_station_run():
    station_job(text=station_text("1980-01-01", "1999-12-31"))
    station = run_next()
    assert station.status == Status.SUCCEEDED, station.log
    make_job(
        kind="sector",
        files={"wheat.csv": SECTOR_FILE.read_text()},
        params={"station_job": str(station.pk), "sector_file": "wheat.csv"},
    )
    job = run_next()
    assert job.status == Status.SUCCEEDED, job.log
    assert job.step == job.total == 7
    assert any(f.startswith("stn/corr/") for f in job.result["files"])
    make_job(kind="sector", params={"station_job": str(uuid.uuid4()), "sector_file": "x"})
    assert "station run was not found" in run_next().error


def write_grid(path):
    import netCDF4

    dates = pd.date_range("1971-01-01", "1974-12-31")
    rng = np.random.default_rng(0)
    with netCDF4.Dataset(path, "w") as nc:
        nc.createDimension("time", None)
        nc.createDimension("lat", 2)
        nc.createDimension("lon", 2)
        t = nc.createVariable("time", "f8", ("time",))
        t.units, t.calendar = "days since 1950-01-01", "standard"
        t[:] = netCDF4.date2num(dates.to_pydatetime(), t.units, t.calendar)
        for name, units, values in (
            ("lat", "degrees_north", [-10, 10]),
            ("lon", "degrees_east", [0, 10]),
        ):
            v = nc.createVariable(name, "f8", (name,))
            v.units = units
            v[:] = values
        season = 8 * np.cos(2 * np.pi * dates.day_of_year.to_numpy() / 365.25)[:, None, None]
        shape = (dates.size, 2, 2)
        for name, units, values in (
            ("tasmax", "K", 295 + season + rng.normal(0, 3, shape)),
            ("tasmin", "K", 283 + season + rng.normal(0, 3, shape)),
            ("pr", "kg m-2 s-1", np.maximum(rng.gamma(0.5, 6, shape) - 1, 0) / 86400),
        ):
            v = nc.createVariable(name, "f4", ("time", "lat", "lon"), fill_value=1e20)
            v.units = units
            v[:] = values.astype("f4")
    return path


@pytest.mark.django_db
def test_gridded_runners(tmp_path):
    grid = write_grid(tmp_path / "grid.nc")
    common = {"input_files": [str(grid)], "base_start": 1971, "base_end": 1973}
    make_job(kind="gridded-thresholds", params=common)
    job = run_next()
    assert job.status == Status.SUCCEEDED, job.log
    assert job.result["files"] == ["thresholds.nc"] and job.step == job.total
    make_job(kind="gridded-indices", params={**common, "indices": ["fd", "su"]})
    job = run_next()
    assert job.status == Status.SUCCEEDED, job.log
    assert job.result["files"] and all(f.endswith(".nc") for f in job.result["files"])
    # Trends are on by default (#290): the last stage, after the indices.
    assert job.result["files"][-1] == "trends.nc" and job.stage == "trends"
    make_job(kind="gridded-indices", params={**common, "indices": ["fd"], "trends": False})
    job = run_next()
    assert job.status == Status.SUCCEEDED, job.log
    assert "trends.nc" not in job.result["files"]
    make_job(kind="gridded-indices", params={"input_files": [str(tmp_path / "no.nc")]})
    assert run_next().error == f"Input file not found: {tmp_path / 'no.nc'}."


def test_input_file_stays_in_the_input_folder(tmp_path):
    (tmp_path / "in").mkdir()
    (tmp_path / "secret").write_text("x")
    ctx = JobContext("id", {}, tmp_path / "in", tmp_path / "out")
    with pytest.raises(JobError, match="missing"):
        ctx.input_file("../secret")


@pytest.mark.django_db
def test_unknown_kind_fails_readably():
    make_job(kind="no-such-kind")
    assert run_next().error == "Unknown kind of job: 'no-such-kind'."


# --- Retention -----------------------------------------------------------------------------------


@pytest.mark.django_db
def test_old_jobs_and_files_are_deleted(settings):
    now = timezone.now()
    old = now - dt.timedelta(days=8)
    expired = [
        make_job(status=Status.SUCCEEDED, finished_at=old),
        make_job(status=Status.FAILED, finished_at=old),
        make_job(status=Status.QUEUED, created_at=old),
    ]
    kept = [
        make_job(status=Status.SUCCEEDED, finished_at=now - dt.timedelta(days=6)),
        make_job(status=Status.RUNNING, created_at=old, heartbeat_at=now),
        make_job(status=Status.QUEUED),
    ]
    stray_old = Path(settings.RUNS_DIR) / str(uuid.uuid4())
    stray_new = Path(settings.RUNS_DIR) / str(uuid.uuid4())
    other = Path(settings.RUNS_DIR) / "not-a-job"
    for folder in (stray_old, stray_new, other):
        folder.mkdir(parents=True)
    import os

    os.utime(stray_old, (old.timestamp(), old.timestamp()))
    os.utime(other, (old.timestamp(), old.timestamp()))

    purged = purge_expired(now)
    assert (purged.jobs, purged.folders) == (3, 1)
    assert set(Job.objects.values_list("pk", flat=True)) == {j.pk for j in kept}
    assert not any(j.folder.exists() for j in expired)
    assert all(j.folder.exists() for j in kept)
    assert not stray_old.exists() and stray_new.exists() and other.exists()


@pytest.mark.django_db
def test_retention_period_is_a_setting(settings):
    settings.JOB_RETENTION_DAYS = 1
    job = make_job(status=Status.SUCCEEDED, finished_at=timezone.now() - dt.timedelta(days=2))
    assert job.expires_at < timezone.now()
    assert purge_expired().jobs == 1
    page = owned_client().get("/jobs/").content.decode()
    assert "kept for 1 day after" in page


@pytest.mark.django_db
def test_purgejobs_command(capsys):
    make_job(status=Status.SUCCEEDED, finished_at=timezone.now() - dt.timedelta(days=30))
    call_command("purgejobs")
    assert "Deleted 1 job(s) older than 7 days" in capsys.readouterr().out
    assert not Job.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_worker_purges_on_its_schedule():
    make_job(status=Status.SUCCEEDED, finished_at=timezone.now() - dt.timedelta(days=30))
    JobWorker(name="w", once=True).run()
    assert not Job.objects.exists()
    assert not Worker.objects.exists()  # removed when the worker stops


# ---- Speculative runs (#178) ---------------------------------------------------------------


@pytest.mark.django_db
def test_your_calculations_leave_out_cancelled_speculative_runs():
    """A speculative run cancelled because the data changed was never asked for: it is not
    listed. Everything else is, cancelled ordinary jobs and running speculative ones too."""
    replaced = make_job(title="replaced", params={"speculative": True}, status=Status.CANCELLED)
    running = make_job(title="running", params={"speculative": True}, status=Status.RUNNING)
    promoted = make_job(title="promoted", params={"speculative": False}, status=Status.CANCELLED)
    cancelled = make_job(title="cancelled", status=Status.CANCELLED)
    failed = make_job(title="failed", params={"speculative": True}, status=Status.FAILED)
    page = owned_client().get("/jobs/").content.decode()
    listed = set(re.findall(r'href="/jobs/([^/"]+)/"', page))
    assert listed == {str(j.pk) for j in (running, promoted, cancelled, failed)}
    assert str(replaced.pk) not in page
    # Its own page still answers, for a link the user kept.
    assert owned_client().get(f"/jobs/{replaced.pk}/").status_code == 200


@pytest.mark.django_db
def test_claim_takes_speculative_runs_last():
    speculative = make_job(params={"speculative": True})
    ordinary = make_job()
    promoted = make_job(params={"speculative": False})
    assert claim("w") == ordinary
    assert claim("w") == promoted
    assert claim("w") == speculative
    assert claim("w") is None


@pytest.mark.django_db
def test_promote_makes_a_speculative_run_ordinary(rf):
    from climpact_web.jobs.views import promote

    job = make_job(params={"speculative": True, "plots": True})
    assert job.is_speculative
    promote(rf.post("/"), job)
    job.refresh_from_db()
    assert not job.is_speculative and job.params == {"speculative": False, "plots": True}
    promote(rf.post("/"), job)  # an ordinary job is left alone
    assert not job.is_speculative
