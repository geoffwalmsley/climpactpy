"""The job queue: one row per calculation, claimed and run by a worker
(``climpact-web manage runworker``). The database is the queue, so the local install needs
no other service (no Redis); see TECHNICAL.md, "Background jobs"."""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Status(models.TextChoices):
    QUEUED = "queued", _("Waiting to start")
    RUNNING = "running", _("Running")
    SUCCEEDED = "succeeded", _("Finished")
    FAILED = "failed", _("Failed")
    CANCELLED = "cancelled", _("Cancelled")


FINISHED = (Status.SUCCEEDED, Status.FAILED, Status.CANCELLED)

# The key of ``Job.params`` that marks a speculative run (#178): a station calculation
# started with the default settings before the user asked for it, while they look at the
# quality checks. It becomes an ordinary job (the key is set to false) when the user
# chooses to use the data. Until then the worker takes it only when no other job waits,
# the hosted limits do not count it, and "Your calculations" leaves it out once cancelled.
SPECULATIVE = "speculative"


# The key of ``Job.params`` that names the change a job was queued for (#254): every job a
# change to a workspace queues (each station's checks and run) carries the same id, and the
# hosted limits count them as one (core.limits). Undo cancels them together.
CHANGE = "change"


def change_groups(jobs, besides: str = "") -> int:
    """How many starts ``jobs`` (a queryset) are, the jobs of one change counting once;
    with ``besides``, leaving out that change's."""
    groups = set()
    for pk, params in jobs.values_list("pk", "params"):
        groups.add((params or {}).get(CHANGE) or f"job:{pk}")
    groups.discard(besides)
    return len(groups)


def speculative_q() -> models.Q:
    """Jobs that are still speculative (a JSON lookup, so no migration was needed)."""
    return models.Q(**{f"params__{SPECULATIVE}": True})


def ordinary_q() -> models.Q:
    """Every other job. Not ``~speculative_q()``: in SQL that is unknown, so false, for the
    jobs whose parameters do not have the key."""
    return ~models.Q(params__has_key=SPECULATIVE) | models.Q(**{f"params__{SPECULATIVE}": False})


class Job(models.Model):
    """A calculation run in the background.

    ``kind`` names the runner (:mod:`climpact_web.jobs.registry`) and ``params`` its
    JSON parameters. Input files are in :attr:`input_dir` and results in
    :attr:`output_dir`, both in the job's own folder under ``RUNS_DIR``. ``owner`` is a
    random token kept in the browser session that created the job: only that session sees
    it. ``error`` is the message shown to the user; ``log`` is for operators (timings and
    tracebacks) and never shown in the browser.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=50)
    owner = models.CharField(max_length=64, db_index=True)
    # Hosted mode: the client that started the job, for the per-client quotas
    # (climpact_web.core.limits.client_key); blank in local mode.
    client = models.CharField(max_length=64, blank=True, db_index=True)
    params = models.JSONField(default=dict, blank=True)
    title = models.CharField(max_length=200, blank=True)

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.QUEUED, db_index=True
    )
    stage = models.CharField(max_length=200, blank=True)
    step = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    worker = models.CharField(max_length=200, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    cancel_requested = models.BooleanField(default=False)

    error = models.TextField(blank=True)
    log = models.TextField(blank=True)
    result = models.JSONField(default=dict, blank=True)
    # The inputs the job was produced from, recorded when it is queued, so a station
    # workspace can tell when its results are out of date (#179): ``file`` (the station
    # file's SHA-256), ``metadata``, ``qc`` (the thresholds) and, for a station run,
    # ``settings``. Empty for the jobs that do not track them (batch, gridded, sector).
    inputs = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "created_at"])]

    def __str__(self) -> str:
        return f"{self.kind} job {self.id} ({self.status})"

    # Files --------------------------------------------------------------------------

    @property
    def folder(self) -> Path:
        return Path(settings.RUNS_DIR) / str(self.id)

    @property
    def input_dir(self) -> Path:
        return self.folder / "input"

    @property
    def output_dir(self) -> Path:
        return self.folder / "output"

    # State --------------------------------------------------------------------------

    @property
    def is_finished(self) -> bool:
        return self.status in FINISHED

    @property
    def is_speculative(self) -> bool:
        return bool((self.params or {}).get(SPECULATIVE))

    @property
    def can_cancel(self) -> bool:
        return self.status in (Status.QUEUED, Status.RUNNING) and not self.cancel_requested

    @property
    def can_retry(self) -> bool:
        return self.status in (Status.FAILED, Status.CANCELLED)

    @property
    def percent(self) -> int:
        if self.status == Status.SUCCEEDED:
            return 100
        if not self.total:
            return 0
        return min(100, int(100 * self.step / self.total))

    def elapsed(self, now: dt.datetime | None = None) -> dt.timedelta | None:
        """Time spent running (to now, or to the end of a finished job)."""
        if self.started_at is None:
            return None
        end = self.finished_at or now or timezone.now()
        return max(end - self.started_at, dt.timedelta(0))

    def remaining(self, now: dt.datetime | None = None) -> dt.timedelta | None:
        """A linear estimate of the time left, once a few steps are done."""
        elapsed = self.elapsed(now)
        if self.status != Status.RUNNING or elapsed is None or not self.total:
            return None
        if self.step < 2 or elapsed < dt.timedelta(seconds=2):
            return None
        return elapsed * (self.total - self.step) / self.step

    # Actions ------------------------------------------------------------------------

    def request_cancel(self) -> None:
        """Cancel: a queued job at once, a running one at its next progress step (the
        worker sees ``cancel_requested``)."""
        jobs = Job.objects.filter(pk=self.pk)
        if not jobs.filter(status=Status.QUEUED).update(
            status=Status.CANCELLED, finished_at=timezone.now()
        ):
            jobs.filter(status=Status.RUNNING).update(cancel_requested=True)

    def retry(self) -> bool:
        """Queue a failed or cancelled job again, with the same inputs and parameters (at
        the back of the queue). False if the job is in any other state."""
        return bool(
            Job.objects.filter(pk=self.pk, status__in=(Status.FAILED, Status.CANCELLED)).update(
                status=Status.QUEUED,
                cancel_requested=False,
                error="",
                result={},
                stage="",
                step=0,
                total=0,
                created_at=timezone.now(),
                started_at=None,
                finished_at=None,
                heartbeat_at=None,
                worker="",
            )
        )

    @property
    def expires_at(self) -> dt.datetime:
        """When the job and its files are deleted (see :mod:`climpact_web.jobs.retention`)."""
        start = self.finished_at or self.created_at
        return start + dt.timedelta(days=settings.JOB_RETENTION_DAYS)


class JobStart(models.Model):
    """A job started (or retried) in hosted mode, kept for two days: the per-client daily
    quota counts these rather than jobs, which the user can delete. The jobs of one change
    (``params["change"]``, a workspace's recalculation, #254) are one start, recorded with
    the first of them."""

    client = models.CharField(max_length=64)
    kind = models.CharField(max_length=50, blank=True)
    change = models.CharField(max_length=36, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=["client", "created_at"])]

    def __str__(self) -> str:
        return f"{self.kind} job started by {self.client} at {self.created_at}"


class Worker(models.Model):
    """A running worker process, seen at each heartbeat: lets pages tell whether any
    worker is running, and operators see which."""

    name = models.CharField(max_length=200, primary_key=True)
    started_at = models.DateTimeField(default=timezone.now)
    seen_at = models.DateTimeField(default=timezone.now)

    def __str__(self) -> str:
        return self.name
