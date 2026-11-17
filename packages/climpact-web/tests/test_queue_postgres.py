"""The job queue on Postgres with several workers at once (#119): real worker processes,
each with its own database connection, claim jobs with ``SELECT ... FOR UPDATE SKIP
LOCKED``. Every job runs exactly once, none is claimed twice, and the job of a worker that
is killed is failed by the other workers' stale-heartbeat reaper and runs again on retry.

It also checks the workspace migration (#231) on Postgres: existing analyses and batches
are dropped, their jobs kept, and the new models and JSON lookups on them work
(``migration_workspaces.py``).

Runs when ``DATABASE_URL`` points at Postgres (CI's ``web-postgres`` job; the test settings
keep it as ``CLIMPACT_TEST_POSTGRES_URL``) and skips otherwise. It creates a database of
its own on that server and drops it at the end. With ``CLIMPACT_TEST_POSTGRES_REQUIRED``
set, a missing URL fails instead of skipping, so CI cannot skip it by accident.
"""

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

POSTGRES_URL = os.environ.get("CLIMPACT_TEST_POSTGRES_URL", "")
if not POSTGRES_URL and os.environ.get("CLIMPACT_TEST_POSTGRES_REQUIRED"):
    raise RuntimeError("CLIMPACT_TEST_POSTGRES_REQUIRED is set but DATABASE_URL is not Postgres")

pytestmark = [
    pytest.mark.skipif(not POSTGRES_URL, reason="needs a Postgres DATABASE_URL"),
    pytest.mark.skipif(sys.platform == "win32", reason="uses SIGKILL"),
]

WORKERS = 4
JOBS = 40
HEARTBEAT = 0.3
STALE = 1.5

SETUP = """
import os, django
os.environ["DJANGO_SETTINGS_MODULE"] = "climpact_web.settings"
django.setup()
"""

# A worker with a test job kind. Each run leaves a marker file named after the job and the
# process, so a job run twice leaves two. With ``hang``, the first attempt runs for a minute
# (progress every 0.1 s), long enough to kill its worker in the middle; a retry is quick.
WORKER = """
import signal, sys, time
from pathlib import Path
from climpact_web.jobs.registry import register
from climpact_web.jobs.worker import JobWorker

@register("queue-test")
def run(ctx):
    markers = Path(ctx.params["markers"])
    first = not any(markers.glob(ctx.job_id + ".*"))
    (markers / f"{ctx.job_id}.{os.getpid()}.{time.monotonic_ns()}").touch(exist_ok=False)
    steps, pause = (600, 0.1) if ctx.params.get("hang") and first else (2, 0.05)
    for step in range(1, steps + 1):
        time.sleep(pause)
        ctx.progress("work", step, steps)
    return {"pid": os.getpid()}

worker = JobWorker(name=sys.argv[-1], cleanup=False)
signal.signal(signal.SIGTERM, lambda signum, frame: worker.stop.set())
worker.run()
"""

ENQUEUE = """
import json, sys
from climpact_web.jobs.models import Job
params = json.loads(sys.argv[-1])
count = int(sys.argv[-2])
for _ in range(count):
    print(Job.objects.create(kind="queue-test", owner="t", params=params).pk)
"""

RETRY = """
import sys
from climpact_web.jobs.models import Job
assert Job.objects.get(pk=sys.argv[-1]).retry()
"""


def connect(url):
    import psycopg  # the `postgres` extra; a Postgres URL without it is an error, not a skip

    return psycopg.connect(url, autocommit=True)


def with_database(url, name):
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path="/" + name))


@pytest.fixture
def env(tmp_path):
    """The environment of a worker: its own Postgres database, migrated, a data folder and
    short heartbeat, stale and poll intervals."""
    name = f"climpact_queue_test_{uuid.uuid4().hex[:12]}"
    with connect(POSTGRES_URL) as con:
        con.execute(f'CREATE DATABASE "{name}"')
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLIMPACT_WEB_")}
    env.pop("DJANGO_SETTINGS_MODULE", None)
    env.update(
        DATABASE_URL=with_database(POSTGRES_URL, name),
        CLIMPACT_WEB_DATA_DIR=str(tmp_path / "data"),
        CLIMPACT_WEB_JOB_HEARTBEAT_SECONDS=str(HEARTBEAT),
        CLIMPACT_WEB_JOB_STALE_SECONDS=str(STALE),
        CLIMPACT_WEB_JOB_POLL_SECONDS="0.05",
    )
    (tmp_path / "data").mkdir()
    (tmp_path / "markers").mkdir()
    try:
        subprocess.run(
            [sys.executable, "-m", "climpact_web", "manage", "migrate", "--verbosity", "0"],
            env=env,
            check=True,
            timeout=120,
        )
        yield env
    finally:
        with connect(POSTGRES_URL) as con:
            con.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def django_script(env, code, *args):
    out = subprocess.run(
        [sys.executable, "-c", SETUP + code, *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout


def enqueue(env, count, **params):
    return django_script(env, ENQUEUE, str(count), json.dumps(params)).split()


def rows(env, sql, *args):
    with connect(env["DATABASE_URL"]) as con:
        return con.execute(sql, args).fetchall()


def jobs(env):
    """Every job: {id: (status, worker, attempts, error, log)}."""
    found = rows(env, "SELECT id, status, worker, attempts, error, log FROM jobs_job")
    return {str(row[0]): row[1:] for row in found}


def wait_for(predicate, timeout=60, message="timed out"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError(message)


def markers(tmp_path):
    """The runs each job has had: {job id: [pid, ...]}."""
    runs = {}
    for path in (tmp_path / "markers").iterdir():
        job_id, pid, _ = path.name.split(".")
        runs.setdefault(job_id, []).append(int(pid))
    return runs


def start_worker(env, name, log_dir: Path):
    log = open(log_dir / f"{name}.log", "w")  # noqa: SIM115 (closed with the process)
    proc = subprocess.Popen(
        [sys.executable, "-c", SETUP + WORKER, name],
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    proc.log = log
    return proc


def test_several_workers_run_each_job_once_and_recover_a_killed_one(env, tmp_path):
    names = [f"worker-{i}" for i in range(WORKERS)]
    workers = {name: start_worker(env, name, tmp_path) for name in names}
    doomed = None
    try:
        # All workers polling before the jobs arrive, so they compete for every claim.
        wait_for(
            lambda: len(rows(env, "SELECT name FROM jobs_worker")) == WORKERS,
            message="the workers did not all start",
        )
        ids = enqueue(env, JOBS, markers=str(tmp_path / "markers"))
        assert len(ids) == JOBS

        wait_for(
            lambda: all(row[0] == "succeeded" for row in jobs(env).values()),
            message=f"not every job finished: {jobs(env)}",
        )
        found = jobs(env)
        assert sorted(found) == sorted(ids)  # no job lost, none added
        assert all(attempts == 1 for _, _, attempts, _, _ in found.values())  # claimed once
        runs = markers(tmp_path)
        assert sorted(runs) == sorted(ids)
        assert all(len(pids) == 1 for pids in runs.values()), runs  # ran once
        by_worker = {worker for _, worker, _, _, _ in found.values()}
        assert by_worker <= set(names)
        assert len(by_worker) > 1, "only one worker took jobs: no concurrency was tested"
        # Each job ran in the process of the worker recorded as having claimed it.
        pids = {name: proc.pid for name, proc in workers.items()}
        assert all(runs[job][0] == pids[found[job][1]] for job in ids)

        # Kill the worker running a long job: the others notice its heartbeat stopped.
        (slow,) = enqueue(env, 1, markers=str(tmp_path / "markers"), hang=True)
        doomed = wait_for(lambda: (r := jobs(env)[slow])[0] == "running" and r[1])
        wait_for(lambda: rows(env, "SELECT step FROM jobs_job WHERE id = %s", slow)[0][0] > 0)
        workers[doomed].send_signal(signal.SIGKILL)
        workers[doomed].wait(timeout=10)
        killed_at = time.monotonic()
        status, worker, attempts, error, log = wait_for(
            lambda: (r := jobs(env)[slow])[0] != "running" and r,
            timeout=STALE + 10,
            message="the killed worker's job was not reaped",
        )
        assert time.monotonic() - killed_at >= STALE - HEARTBEAT  # not before it was stale
        assert (status, worker, attempts) == ("failed", doomed, 1)
        assert error.startswith("The calculation stopped unexpectedly")
        assert "no heartbeat" in log

        # The user retries: one of the surviving workers runs it to the end; new jobs queued
        # meanwhile run once each, too.
        django_script(env, RETRY, slow)
        more = enqueue(env, 8, markers=str(tmp_path / "markers"))
        wait_for(
            lambda: all(jobs(env)[job][0] == "succeeded" for job in [slow, *more]),
            message=f"jobs after the kill did not finish: {jobs(env)}",
        )
        status, worker, attempts, _, _ = jobs(env)[slow]
        assert worker != doomed and attempts == 2
        runs = markers(tmp_path)
        assert sorted(runs[slow]) == sorted([pids[doomed], pids[worker]])  # once per attempt
        assert all(len(runs[job]) == 1 for job in more)
        assert all(jobs(env)[job][2] == 1 for job in more)
        assert len(jobs(env)) == JOBS + 1 + len(more)
    finally:
        for proc in workers.values():
            if proc.poll() is None:
                proc.terminate()
        for proc in workers.values():
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            proc.log.close()
    # The surviving workers stopped cleanly on SIGTERM.
    exits = {name: proc.returncode for name, proc in workers.items() if name != doomed}
    assert all(code == 0 for code in exits.values()), {
        name: (tmp_path / f"{name}.log").read_text() for name in exits
    }


def test_workspace_migration_on_postgres(env, tmp_path):
    """The workspace migration (#231) back and forward on Postgres, with the same checks as
    on SQLite (``test_workspace.py``)."""
    tests = Path(__file__).resolve().parent
    code = f"import sys; sys.path.insert(0, {str(tests)!r})\n" + (
        "from django.conf import settings\n"
        "from migration_workspaces import check\n"
        "check(settings.MEDIA_ROOT)\n"
        "print('migration ok')\n"
    )
    assert "migration ok" in django_script(env, code)
