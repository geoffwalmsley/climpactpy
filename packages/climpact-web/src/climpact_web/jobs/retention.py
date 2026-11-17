"""Deleting old jobs and their files.

Uploaded station data belongs to the user, so nothing is kept longer than
``JOB_RETENTION_DAYS`` (``CLIMPACT_WEB_RETENTION_DAYS``, default 7) after a job finishes,
or after it was created if it never ran. The upload page states the period
(``job_retention_days`` in every template, from the context processor). The worker purges
every ``JOB_CLEANUP_INTERVAL`` seconds; ``climpact-web manage purgejobs`` does it on demand
(or from cron, for a deployment without a worker running all the time).

A job another app still shows is kept whatever its age: the stations app registers the
jobs its workspaces show (:func:`register_keeper`), and they go with the workspace (#231).
"""

from __future__ import annotations

import datetime as dt
import logging
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from climpact_web.jobs.models import FINISHED, Job, Status, Worker
from climpact_web.jobs.storage import get_storage

logger = logging.getLogger("climpact_web.jobs")


@dataclass
class Purged:
    jobs: int = 0
    folders: int = 0
    other: int = 0  # rows deleted by the registered purgers (e.g. workspaces)


# Other apps' clean-up, run with every purge: functions (now, retention days) -> count.
PURGERS: list = []


# Other apps' jobs to keep: functions () -> a set of job ids (as strings).
KEEPERS: list = []


def register_keeper(func) -> None:
    """Never purge the jobs ``func()`` names (the stations app keeps the jobs a workspace
    shows for as long as the workspace)."""
    if func not in KEEPERS:
        KEEPERS.append(func)


def kept_job_ids() -> set[str]:
    kept: set[str] = set()
    for keeper in KEEPERS:
        kept |= keeper()
    return kept


def register_purger(func) -> None:
    """Run ``func(now, days)`` whenever expired jobs are purged (the stations app deletes
    its workspaces this way, so the jobs app needs no knowledge of them)."""
    if func not in PURGERS:
        PURGERS.append(func)


def retention_days() -> int:
    return settings.JOB_RETENTION_DAYS


def expired_jobs(now: dt.datetime | None = None):
    """Finished jobs past the retention period, and queued jobs that never started within
    it, except those another app still shows (:func:`register_keeper`). Running jobs are
    never deleted (a dead worker's are failed first)."""
    now = now or timezone.now()
    cutoff = now - dt.timedelta(days=settings.JOB_RETENTION_DAYS)
    return Job.objects.filter(
        Q(status__in=FINISHED, finished_at__lt=cutoff)
        | Q(status__in=FINISHED, finished_at__isnull=True, created_at__lt=cutoff)
        | Q(status=Status.QUEUED, created_at__lt=cutoff)
    ).exclude(pk__in=kept_job_ids())


def purge_expired(now: dt.datetime | None = None) -> Purged:
    """Delete expired jobs with their folders, and folders under ``RUNS_DIR`` that belong to
    no job and are older than the retention period (left by an interrupted upload)."""
    now = now or timezone.now()
    purged = Purged()
    storage = get_storage()
    for job in expired_jobs(now):
        storage.delete(job)
        purged.jobs += Job.objects.filter(pk=job.pk).delete()[0]

    runs = Path(settings.RUNS_DIR)
    cutoff = (now - dt.timedelta(days=settings.JOB_RETENTION_DAYS)).timestamp()
    if runs.is_dir():
        known = {str(pk) for pk in Job.objects.values_list("pk", flat=True)}
        for folder in runs.iterdir():
            if folder.name in known or not _is_uuid(folder.name):
                continue
            if folder.stat().st_mtime < cutoff:
                shutil.rmtree(folder, ignore_errors=True)
                purged.folders += 1

    for purger in PURGERS:
        purged.other += purger(now, settings.JOB_RETENTION_DAYS)

    Worker.objects.filter(seen_at__lt=now - dt.timedelta(days=1)).delete()
    if purged.jobs or purged.folders:
        logger.info("Deleted %d expired job(s) and %d stray folder(s)", purged.jobs, purged.folders)
    return purged


def _is_uuid(name: str) -> bool:
    try:
        uuid.UUID(name)
    except ValueError:
        return False
    return True
