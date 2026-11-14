"""The worker as a real process on a file database: killed in the middle of a job, the job
fails with a retry (not a page that hangs), and the retried job completes."""

import json
import os
import signal
import sqlite3
import subprocess
import sys
import time

import pytest
from test_jobs import station_text

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="uses SIGKILL")

SETUP = """
import os, django
os.environ["DJANGO_SETTINGS_MODULE"] = "climpact_web.settings"
django.setup()
"""

CREATE_JOB = """
import json, sys
from climpact_web.jobs.models import Job
job = Job.objects.create(kind="station", owner="o", params=json.loads(sys.argv[-1]))
job.input_dir.mkdir(parents=True)
(job.input_dir / "station.txt").write_text(open(sys.argv[-2]).read())
print(job.pk)
"""


def manage(env, *args, check=True):
    return subprocess.run(
        [sys.executable, "-m", "climpact_web", "manage", *args],
        env=env,
        capture_output=True,
        text=True,
        check=check,
        timeout=120,
    )


def django_script(env, code, *args):
    """Run Python ``code`` with the app's settings (as the worker sees them)."""
    return subprocess.run(
        [sys.executable, "-c", SETUP + code, *args],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )


def job_row(db, job_id):
    with sqlite3.connect(db) as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT * FROM jobs_job WHERE id = ?", (job_id.replace("-", ""),)
        ).fetchone()
    return dict(row)


def wait_for(predicate, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError("timed out")


@pytest.fixture
def env(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLIMPACT_WEB_")}
    env.pop("DJANGO_SETTINGS_MODULE", None)
    env.update(
        CLIMPACT_WEB_DATA_DIR=str(tmp_path / "data"),
        CLIMPACT_WEB_JOB_HEARTBEAT_SECONDS="0.5",
        CLIMPACT_WEB_JOB_STALE_SECONDS="2",
        CLIMPACT_WEB_JOB_POLL_SECONDS="0.2",
    )
    (tmp_path / "data").mkdir()
    manage(env, "migrate", "--verbosity", "0")
    return env


def test_killed_worker_fails_the_job_with_a_retry(env, tmp_path):
    station = tmp_path / "station.txt"
    station.write_text(station_text())
    params = {
        "station_file": "station.txt",
        "metadata": {"name": "stn", "base_start": 2000, "base_end": 2001},
        "plots": True,  # about a hundred steps: time to kill it in the middle
        "zip": True,
    }
    out = django_script(env, CREATE_JOB, str(station), json.dumps(params))
    job_id = out.stdout.strip().splitlines()[-1]
    db = tmp_path / "data" / "db.sqlite3"

    worker = subprocess.Popen(
        [sys.executable, "-m", "climpact_web", "manage", "runworker", "--name", "doomed"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        row = wait_for(lambda: (r := job_row(db, job_id))["step"] > 0 and r)
        assert row["status"] == "running" and row["worker"] == "doomed"
        assert row["step"] < row["total"]
        worker.send_signal(signal.SIGKILL)
        worker.wait(timeout=10)
    finally:
        if worker.poll() is None:
            worker.kill()
    assert job_row(db, job_id)["status"] == "running"  # nobody has noticed yet

    time.sleep(2.5)  # longer than CLIMPACT_WEB_JOB_STALE_SECONDS
    out = manage(env, "purgejobs")
    assert "marked 1 stalled job(s) failed" in out.stdout
    row = job_row(db, job_id)
    assert row["status"] == "failed"
    assert row["error"].startswith("The calculation stopped unexpectedly")
    assert "no heartbeat" in row["log"]

    # Try again: the next worker runs it to the end.
    django_script(
        env,
        f"from climpact_web.jobs.models import Job; assert Job.objects.get(pk='{job_id}').retry()",
    )
    out = manage(env, "runworker", "--once")
    assert "Ran 1 job(s)." in out.stdout
    row = job_row(db, job_id)
    assert row["status"] == "succeeded", row["log"]
    assert row["attempts"] == 2 and row["step"] == row["total"]
    assert (tmp_path / "data" / "media" / "runs" / job_id / "output" / "stn.zip").is_file()


def test_stopping_the_worker_queues_its_job_again(env, tmp_path):
    station = tmp_path / "station.txt"
    station.write_text(station_text())
    params = {"station_file": "station.txt", "metadata": {"name": "stn"}, "plots": True}
    out = django_script(env, CREATE_JOB, str(station), json.dumps(params))
    job_id = out.stdout.strip().splitlines()[-1]
    db = tmp_path / "data" / "db.sqlite3"
    worker = subprocess.Popen(
        [sys.executable, "-m", "climpact_web", "manage", "runworker"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for(lambda: job_row(db, job_id)["step"] > 0)
        worker.terminate()  # SIGTERM, as climpact-web sends on exit
        assert worker.wait(timeout=30) == 0
    finally:
        if worker.poll() is None:
            worker.kill()
    row = job_row(db, job_id)
    assert (row["status"], row["step"]) == ("queued", 0)
    assert "queued again" in row["log"]
