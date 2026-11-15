"""The worker: claims queued jobs from the database, runs them and records their progress.

One worker runs one job at a time, in its own process (``climpact-web manage
runworker``); in local mode ``climpact-web`` starts one as a child process. More workers
(hosted mode) simply claim different jobs. See TECHNICAL.md, "Background jobs".

- **Claiming** is atomic: on databases with ``SELECT ... FOR UPDATE SKIP LOCKED``
  (Postgres) the oldest unlocked queued row is locked and taken; elsewhere (SQLite) a
  conditional ``UPDATE ... WHERE status = 'queued'`` takes a candidate, and whoever
  updates no row tries the next one.
- **Progress** from the core's callback is written to the job row at most every
  ``JOB_PROGRESS_INTERVAL`` seconds (and at the end), so a run of a hundred quick stages
  costs a handful of writes.
- **Heartbeat**: a thread updates ``heartbeat_at`` of the running job (and ``seen_at`` of
  the worker) every ``JOB_HEARTBEAT_SECONDS``, and picks up a cancel request there too, so
  it is noticed even during a long stage. A running job whose heartbeat is older than
  ``JOB_STALE_SECONDS`` belonged to a worker that died: :func:`reap_stale` marks it failed,
  with a retry offered.
- **Time limit** (hosted mode, ``JOB_TIME_LIMIT_MINUTES``, #125): a job still running
  after the limit is stopped at its next progress step and fails with
  :data:`TIME_LIMIT_MESSAGE`. A stage that reports no progress for a long time cannot be
  stopped that way, so once the limit plus ``JOB_TIME_LIMIT_GRACE_SECONDS`` has passed the
  heartbeat thread fails the job itself and ends the worker process (its container is
  restarted, and the worker's other threads and child processes go with it).
- **Cancel** takes effect at the next progress step: the callback raises
  :class:`~climpact_web.jobs.registry.JobCancelled`. **Stopping** the worker (SIGTERM,
  Ctrl+C) interrupts the running job the same way and queues it again, so it runs on the
  next start.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import socket
import threading
import time
import traceback
from collections.abc import Callable

from django.conf import settings
from django.db import close_old_connections, connection, connections, transaction
from django.utils import timezone

from climpact_web.jobs.models import Job, Status, Worker
from climpact_web.jobs.registry import (
    JobCancelled,
    JobContext,
    JobError,
    JobInterrupted,
    JobTimedOut,
    get_runner,
)
from climpact_web.jobs.storage import get_storage

logger = logging.getLogger("climpact_web.jobs")

STALE_MESSAGE = (
    "The calculation stopped unexpectedly: the program running it stopped or lost "
    "contact. You can try again."
)
CRASH_MESSAGE = (
    "The calculation stopped unexpectedly: the program running it crashed. You can try again."
)
UNEXPECTED_MESSAGE = (
    "Something went wrong during the calculation. The details have been logged for the "
    "administrator (job {id}). You can try again."
)
MEMORY_MESSAGE = "The calculation ran out of memory. Try a smaller file or fewer outputs."
TIME_LIMIT_MESSAGE = (
    "The calculation was stopped because it ran for longer than this site allows "
    "({minutes:g} minutes). Try fewer stations or outputs, or install Climpact on your own "
    "computer, which has no time limit."
)


def time_limit_seconds() -> float | None:
    """The wall-clock limit on one job, in seconds: hosted mode only; None for none."""
    minutes = settings.JOB_TIME_LIMIT_MINUTES
    if not settings.IS_HOSTED or minutes <= 0:
        return None
    return minutes * 60


def time_limit_message() -> str:
    return TIME_LIMIT_MESSAGE.format(minutes=settings.JOB_TIME_LIMIT_MINUTES)


def worker_name(pid: int | None = None) -> str:
    return f"{socket.gethostname()}:{pid or os.getpid()}"


def _log_line(text: str) -> str:
    return f"[{timezone.now().isoformat(timespec='seconds')}] {text}\n"


def append_log(job_id, text: str) -> None:
    """Append a line to a job's operator log."""
    job = Job.objects.filter(pk=job_id).only("log").first()
    if job is not None:
        Job.objects.filter(pk=job_id).update(log=job.log + _log_line(text))


# Claiming ------------------------------------------------------------------------------


def claim(worker: str) -> Job | None:
    """Take the oldest queued job for ``worker``, atomically; None if there is none."""
    now = timezone.now()
    claimed = {
        "status": Status.RUNNING,
        "worker": worker,
        "started_at": now,
        "heartbeat_at": now,
        "finished_at": None,
        "stage": "",
        "step": 0,
        "total": 0,
    }
    queued = Job.objects.filter(status=Status.QUEUED, cancel_requested=False).order_by("created_at")
    if connection.features.has_select_for_update_skip_locked:
        with transaction.atomic():
            job = queued.select_for_update(skip_locked=True).first()
            if job is None:
                return None
            Job.objects.filter(pk=job.pk).update(attempts=job.attempts + 1, **claimed)
        return Job.objects.get(pk=job.pk)
    for job_id, attempts in queued.values_list("pk", "attempts")[:20]:
        taken = Job.objects.filter(pk=job_id, status=Status.QUEUED, cancel_requested=False).update(
            attempts=attempts + 1, **claimed
        )
        if taken:
            return Job.objects.get(pk=job_id)
    return None


# Dead workers ----------------------------------------------------------------------------


def fail_jobs(jobs, message: str, log: str) -> int:
    """Mark running jobs failed (if they still are), with ``message`` for the user."""
    count = 0
    for job in jobs:
        count += Job.objects.filter(pk=job.pk, status=Status.RUNNING).update(
            status=Status.FAILED,
            error=message,
            finished_at=timezone.now(),
            log=job.log + _log_line(log),
        )
    return count


def reap_stale(now: dt.datetime | None = None) -> int:
    """Fail running jobs whose worker has stopped sending heartbeats."""
    now = now or timezone.now()
    cutoff = now - dt.timedelta(seconds=settings.JOB_STALE_SECONDS)
    stale = Job.objects.filter(status=Status.RUNNING, heartbeat_at__lt=cutoff)
    count = fail_jobs(
        list(stale),
        STALE_MESSAGE,
        f"no heartbeat for more than {settings.JOB_STALE_SECONDS} s: marked failed",
    )
    if count:
        logger.warning("Marked %d job(s) failed: their worker stopped sending heartbeats", count)
    return count


def release_jobs_of(worker: str, crashed: bool) -> int:
    """After a worker process has gone (``climpact-web`` knows when its own child stops):
    a crash fails its running job; a stop that did not finish in time queues it again."""
    jobs = list(Job.objects.filter(status=Status.RUNNING, worker=worker))
    if crashed:
        return fail_jobs(jobs, CRASH_MESSAGE, f"worker {worker} exited unexpectedly")
    count = 0
    for job in jobs:
        count += _requeue(job, f"worker {worker} was stopped: queued again")
    return count


def _requeue(job: Job, log: str) -> int:
    return Job.objects.filter(pk=job.pk, status=Status.RUNNING).update(
        status=Status.QUEUED,
        worker="",
        started_at=None,
        heartbeat_at=None,
        stage="",
        step=0,
        total=0,
        log=Job.objects.get(pk=job.pk).log + _log_line(log),
    )


# Running a job ---------------------------------------------------------------------------


class ProgressWriter:
    """The progress callback given to the core: keeps the latest step and writes it to the
    job row at most every ``interval`` seconds. Raises :class:`JobCancelled` when the job
    is cancelled, :class:`JobInterrupted` when the worker is stopping and
    :class:`JobTimedOut` after ``deadline`` (``time.monotonic()``; None for no limit)."""

    def __init__(
        self,
        job: Job,
        stop: threading.Event,
        cancel: threading.Event,
        interval: float,
        deadline: float | None = None,
    ):
        self.job = job
        self.stop = stop
        self.cancel = cancel
        self.interval = interval
        self.deadline = deadline
        self.last_write = 0.0
        self.stage, self.step, self.total = "", 0, 0
        self.stages: list[str] = []  # every stage reported, for the operator log

    def __call__(self, stage: str, step: int, total: int) -> None:
        self.stage, self.step, self.total = stage, step, total
        self.stages.append(stage)
        if self.stop.is_set():
            raise JobInterrupted
        if self.cancel.is_set():
            raise JobCancelled
        now = time.monotonic()
        if self.deadline is not None and now >= self.deadline:
            raise JobTimedOut
        if now - self.last_write >= self.interval or step == total:
            self.flush()
            self.last_write = now

    def flush(self) -> None:
        updated = Job.objects.filter(
            pk=self.job.pk, status=Status.RUNNING, cancel_requested=False
        ).update(stage=self.stage[:200], step=self.step, total=self.total)
        if not updated:  # cancelled, or no longer ours
            raise JobCancelled


class Heartbeat(threading.Thread):
    """Every ``interval`` seconds: the worker's ``seen_at`` and, while a job runs, its
    ``heartbeat_at``; sets ``cancel`` when the user has cancelled that job, and stops a job
    that has run past its ``hard_deadline`` (``time.monotonic()``) with :meth:`hard_stop`."""

    def __init__(self, worker: str, interval: float):
        super().__init__(name="climpact-web-heartbeat", daemon=True)
        self.worker = worker
        self.interval = interval
        self.job_id = None
        self.hard_deadline: float | None = None
        self.cancel = threading.Event()
        self.finished = threading.Event()

    def beat(self) -> None:
        now = timezone.now()
        Worker.objects.update_or_create(name=self.worker, defaults={"seen_at": now})
        job_id = self.job_id
        if job_id is not None:
            Job.objects.filter(pk=job_id, status=Status.RUNNING).update(heartbeat_at=now)
            if Job.objects.filter(pk=job_id, cancel_requested=True).exists():
                self.cancel.set()
            deadline = self.hard_deadline
            if deadline is not None and time.monotonic() >= deadline:
                self.hard_stop(job_id)

    def hard_stop(self, job_id) -> None:
        """A job that ran past its time limit and did not stop at a progress step: fail it
        and end the worker process at once (the main thread is stuck in the job, and
        Python cannot interrupt it). Docker restarts the worker."""
        limit = settings.JOB_TIME_LIMIT_MINUTES
        fail_jobs(
            list(Job.objects.filter(pk=job_id)),
            time_limit_message(),
            f"still running {settings.JOB_TIME_LIMIT_GRACE_SECONDS:g} s after the "
            f"{limit:g} min time limit: failed, worker process ended",
        )
        logger.error("Job %s ran past the time limit; ending worker %s", job_id, self.worker)
        os._exit(3)

    def run(self) -> None:
        try:
            while not self.finished.wait(self.interval):
                try:
                    self.beat()
                except Exception:  # a busy database must not stop the heartbeats
                    logger.exception("Heartbeat failed")
        finally:
            connections.close_all()


def user_message(exc: BaseException, job: Job) -> str:
    """The message shown to the user for a failed run: never a traceback."""
    if isinstance(exc, (JobError, ValueError)):
        message = str(exc) or exc.__class__.__name__
        return message.replace(f"{job.folder}{os.sep}", "")  # no server paths
    if isinstance(exc, FileNotFoundError):
        name = os.path.basename(exc.filename or "") or "?"
        return f"A file the calculation needs was not found: {name}."
    if isinstance(exc, MemoryError):
        return MEMORY_MESSAGE
    return UNEXPECTED_MESSAGE.format(id=job.pk)


def run_job(
    job: Job,
    stop: threading.Event | None = None,
    heartbeat: Heartbeat | None = None,
) -> Job:
    """Run a claimed job to the end and record the outcome; returns the job, reloaded."""
    stop = stop or threading.Event()
    cancel = heartbeat.cancel if heartbeat else threading.Event()
    cancel.clear()
    if heartbeat:
        heartbeat.job_id = job.pk
    limit = time_limit_seconds()
    deadline = time.monotonic() + limit if limit is not None else None
    progress = ProgressWriter(job, stop, cancel, settings.JOB_PROGRESS_INTERVAL, deadline)
    if heartbeat and deadline is not None:
        heartbeat.hard_deadline = deadline + settings.JOB_TIME_LIMIT_GRACE_SECONDS
    ctx = JobContext(
        job_id=str(job.pk),
        params=job.params,
        input_dir=job.input_dir,
        output_dir=get_storage().prepare_output(job),
        progress=progress,
        log=lambda text: append_log(job.pk, text),
    )
    append_log(job.pk, f"attempt {job.attempts} started by {job.worker}")
    started = time.monotonic()
    outcome: dict = {}
    try:
        result = get_runner(job.kind)(ctx)
    except JobInterrupted:
        _requeue(job, "worker stopping: interrupted and queued again")
        logger.info("Job %s interrupted, queued again", job.pk)
        return Job.objects.get(pk=job.pk)
    except JobCancelled:
        outcome = {"status": Status.CANCELLED, "error": ""}
        note = "cancelled"
    except JobTimedOut:
        outcome = {"status": Status.FAILED, "error": time_limit_message()}
        note = f"stopped at the {settings.JOB_TIME_LIMIT_MINUTES:g} min time limit"
        logger.warning("Job %s stopped at the time limit", job.pk)
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            _requeue(job, f"worker stopping ({exc.__class__.__name__}): queued again")
            raise
        expected = isinstance(exc, (JobError, ValueError, FileNotFoundError))
        outcome = {"status": Status.FAILED, "error": user_message(exc, job)}
        note = "failed:\n" + "".join(traceback.format_exception(exc))
        if expected:
            logger.info("Job %s failed: %s", job.pk, exc)
        else:
            logger.error("Job %s failed", job.pk, exc_info=exc)
    else:
        outcome = {
            "status": Status.SUCCEEDED,
            "error": "",
            "result": result or {},
            "step": progress.total or progress.step,
            "total": progress.total,
            "stage": progress.stage[:200],
        }
        note = "succeeded"
    finally:
        if heartbeat:
            heartbeat.job_id = None
            heartbeat.hard_deadline = None
    seconds = time.monotonic() - started
    log = Job.objects.get(pk=job.pk).log + _log_line(
        f"{note} after {seconds:.1f} s, {len(progress.stages)} progress steps"
    )
    if outcome["status"] == Status.FAILED and progress.step:
        # Show where it stopped.
        outcome.update(stage=progress.stage[:200], step=progress.step, total=progress.total)
    Job.objects.filter(pk=job.pk, status=Status.RUNNING).update(
        finished_at=timezone.now(), log=log, **outcome
    )
    return Job.objects.get(pk=job.pk)


# The worker loop ---------------------------------------------------------------------------


class JobWorker:
    """Polls for queued jobs and runs them one at a time until :attr:`stop` is set.

    Housekeeping happens in the same loop: stale jobs are reaped every heartbeat interval
    and expired jobs purged every ``JOB_CLEANUP_INTERVAL`` seconds (and at start), so a
    local install needs no scheduler.
    """

    def __init__(
        self,
        name: str | None = None,
        poll: float | None = None,
        once: bool = False,
        cleanup: bool = True,
        on_job: Callable[[Job], None] | None = None,
    ):
        self.name = name or worker_name()
        self.poll = settings.JOB_POLL_SECONDS if poll is None else poll
        self.once = once
        self.cleanup = cleanup
        self.on_job = on_job
        self.stop = threading.Event()
        self.heartbeat = Heartbeat(self.name, settings.JOB_HEARTBEAT_SECONDS)
        self._next_reap = 0.0
        self._next_purge = 0.0

    def housekeeping(self) -> None:
        from climpact_web.jobs.retention import purge_expired

        now = time.monotonic()
        if now >= self._next_reap:
            reap_stale()
            self._next_reap = now + settings.JOB_HEARTBEAT_SECONDS
        if self.cleanup and now >= self._next_purge:
            purge_expired()
            self._next_purge = now + settings.JOB_CLEANUP_INTERVAL

    def run(self) -> int:
        """Run jobs until stopped (or, with ``once``, until the queue is empty); returns the
        number of jobs run."""
        logger.info("Worker %s started", self.name)
        Worker.objects.update_or_create(
            name=self.name, defaults={"started_at": timezone.now(), "seen_at": timezone.now()}
        )
        self.heartbeat.start()
        count = 0
        try:
            while not self.stop.is_set():
                close_old_connections()
                try:
                    self.housekeeping()
                    job = claim(self.name)
                except Exception:  # e.g. the database is briefly locked: try again
                    logger.exception("Worker %s could not poll for jobs", self.name)
                    job = None
                if job is not None:
                    logger.info("Job %s (%s) started", job.pk, job.kind)
                    job = run_job(job, self.stop, self.heartbeat)
                    logger.info("Job %s %s", job.pk, job.status)
                    count += 1
                    if self.on_job:
                        self.on_job(job)
                    continue
                if self.once:
                    break
                self.stop.wait(self.poll)
        finally:
            self.heartbeat.finished.set()
            self.heartbeat.join(timeout=5)
            Worker.objects.filter(name=self.name).delete()
            logger.info("Worker %s stopped", self.name)
        return count


def worker_running(now: dt.datetime | None = None) -> bool:
    """Whether any worker has been seen recently."""
    now = now or timezone.now()
    cutoff = now - dt.timedelta(seconds=settings.JOB_STALE_SECONDS)
    return Worker.objects.filter(seen_at__gte=cutoff).exists()
