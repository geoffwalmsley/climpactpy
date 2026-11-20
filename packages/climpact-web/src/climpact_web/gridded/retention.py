"""Deleting gridded runs (and their uploaded files) past the retention period, as
:mod:`climpact_web.stations.retention` does for workspaces.

When ``WORKSPACE_EXPIRY`` is on (hosted), a run is deleted ``JOB_RETENTION_DAYS`` after
its last change, unless one of its jobs (or those of a new start, #293) is queued or
running, and its jobs and their folders go with it. Locally it is off, and a run stays
until the user forgets it (#301): the run is never purged. Either way :func:`kept_jobs`
keeps the jobs a run shows, with their folders, for as long as the run is there (#330),
so renaming a run after its jobs finished keeps its results until its own Kept until
date. Folders under ``gridded/`` that belong to no run are deleted once older than the
period, and files read in place from this computer are never touched. Registered with the
jobs app's purge and keepers in :class:`.apps.GriddedConfig`."""

from __future__ import annotations

import datetime as dt
import logging

from django.conf import settings
from django.db.models import Q

from climpact_web.jobs.models import Job, Status
from climpact_web.jobs.storage import get_storage
from climpact_web.stations.retention import delete_stray_folders

logger = logging.getLogger("climpact_web.gridded")

JOB_FIELDS = ("thresholds_job", "indices_job", "next_thresholds_job", "next_indices_job")


def kept_jobs() -> set[str]:
    """The ids of the jobs the runs show (and those of a new start): they go with the run,
    hosted or local, as a workspace's do (#330)."""
    from climpact_web.gridded.models import GriddedRun

    kept: set[str] = set()
    for ids in GriddedRun.objects.values_list(*JOB_FIELDS):
        kept.update(str(pk) for pk in ids if pk)
    return kept


def purge_expired_gridded(now: dt.datetime, days: int) -> int:
    from climpact_web.gridded.models import GriddedRun, gridded_dir

    cutoff = now - dt.timedelta(days=days)
    count = 0
    if settings.WORKSPACE_EXPIRY:
        active = (Status.QUEUED, Status.RUNNING)
        busy = Q()
        for field in JOB_FIELDS:
            busy |= Q(**{f"{field}__status__in": active})
        for run in GriddedRun.objects.filter(updated_at__lt=cutoff).exclude(busy):
            jobs = [getattr(run, field) for field in JOB_FIELDS]
            run.delete_files()
            count += GriddedRun.objects.filter(pk=run.pk).delete()[0]
            delete_jobs([job for job in jobs if job is not None])

    known = {str(pk) for pk in GriddedRun.objects.values_list("pk", flat=True)}
    delete_stray_folders(gridded_dir(), known, cutoff)
    if count:
        logger.info("Deleted %d expired gridded run(s)", count)
    return count


def delete_jobs(jobs: list[Job]) -> None:
    """Delete a purged run's jobs and their folders now, rather than at the next purge."""
    storage = get_storage()
    for job in jobs:
        storage.delete(job)
        Job.objects.filter(pk=job.pk).delete()
