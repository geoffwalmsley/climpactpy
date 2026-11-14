"""Deleting gridded runs (and their uploaded files) past the retention period, as
:mod:`climpact_web.batch.retention` does for batches: ``JOB_RETENTION_DAYS`` after the
last change, unless one of the run's jobs is queued or running. Files read in place from
this computer are never touched. Registered with the jobs app's purge in
:class:`.apps.GriddedConfig`."""

from __future__ import annotations

import datetime as dt
import logging
import shutil

from django.db.models import Q

from climpact_web.jobs.models import Status
from climpact_web.stations.retention import _is_uuid

logger = logging.getLogger("climpact_web.gridded")


def purge_expired_gridded(now: dt.datetime, days: int) -> int:
    from climpact_web.gridded.models import GriddedRun, gridded_dir

    cutoff = now - dt.timedelta(days=days)
    active = (Status.QUEUED, Status.RUNNING)
    expired = GriddedRun.objects.filter(updated_at__lt=cutoff).exclude(
        Q(thresholds_job__status__in=active) | Q(indices_job__status__in=active)
    )
    count = 0
    for run in expired:
        run.delete_files()
        count += GriddedRun.objects.filter(pk=run.pk).delete()[0]

    root = gridded_dir()
    if root.is_dir():
        known = {str(pk) for pk in GriddedRun.objects.values_list("pk", flat=True)}
        for folder in root.iterdir():
            if folder.name in known or not _is_uuid(folder.name):
                continue
            if folder.stat().st_mtime < cutoff.timestamp():
                shutil.rmtree(folder, ignore_errors=True)
    if count:
        logger.info("Deleted %d expired gridded run(s)", count)
    return count
