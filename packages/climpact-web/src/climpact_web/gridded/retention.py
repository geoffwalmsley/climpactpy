"""Deleting gridded runs (and their uploaded files) past the retention period, as
:mod:`climpact_web.stations.retention` does for workspaces.

When ``WORKSPACE_EXPIRY`` is on (hosted), a run is deleted ``JOB_RETENTION_DAYS`` after
its last change, unless one of its jobs (or those of a new start, #293) is queued or
running. Locally it is off, and a run stays until the user forgets it (#301): the run is
never purged, and :func:`kept_jobs` keeps the jobs it shows, with their folders. Either
way, folders under ``gridded/`` that belong to no run are deleted once older than the
period, and files read in place from this computer are never touched. Registered with the
jobs app's purge and keepers in :class:`.apps.GriddedConfig`."""

from __future__ import annotations

import datetime as dt
import logging

from django.conf import settings
from django.db.models import Q

from climpact_web.jobs.models import Status
from climpact_web.stations.retention import delete_stray_folders

logger = logging.getLogger("climpact_web.gridded")

JOB_FIELDS = ("thresholds_job", "indices_job", "next_thresholds_job", "next_indices_job")


def kept_jobs() -> set[str]:
    """The ids of the jobs the runs show, when runs don't expire (local); none otherwise,
    so hosted they keep the jobs app's rule."""
    from climpact_web.gridded.models import GriddedRun

    if settings.WORKSPACE_EXPIRY:
        return set()
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
            run.delete_files()
            count += GriddedRun.objects.filter(pk=run.pk).delete()[0]

    known = {str(pk) for pk in GriddedRun.objects.values_list("pk", flat=True)}
    delete_stray_folders(gridded_dir(), known, cutoff)
    if count:
        logger.info("Deleted %d expired gridded run(s)", count)
    return count
