"""Deleting batches (and their files) past the retention period, as
:mod:`climpact_web.stations.retention` does for station analyses: ``JOB_RETENTION_DAYS``
after the last change, unless the batch's job is queued or running. Registered with the
jobs app's purge in :class:`.apps.BatchConfig`."""

from __future__ import annotations

import datetime as dt
import logging
import shutil

from climpact_web.jobs.models import Status
from climpact_web.stations.retention import _is_uuid

logger = logging.getLogger("climpact_web.batch")


def purge_expired_batches(now: dt.datetime, days: int) -> int:
    from climpact_web.batch.models import BatchRun, batches_dir

    cutoff = now - dt.timedelta(days=days)
    expired = BatchRun.objects.filter(updated_at__lt=cutoff).exclude(
        job__status__in=(Status.QUEUED, Status.RUNNING)
    )
    count = 0
    for run in expired:
        run.delete_files()
        count += BatchRun.objects.filter(pk=run.pk).delete()[0]

    root = batches_dir()
    if root.is_dir():
        known = {str(pk) for pk in BatchRun.objects.values_list("pk", flat=True)}
        for folder in root.iterdir():
            if folder.name in known or not _is_uuid(folder.name):
                continue
            if folder.stat().st_mtime < cutoff.timestamp():
                shutil.rmtree(folder, ignore_errors=True)
    if count:
        logger.info("Deleted %d expired batch(es)", count)
    return count
