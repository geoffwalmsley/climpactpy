"""Deleting station analyses (and their files) past the retention period.

An analysis is deleted ``JOB_RETENTION_DAYS`` after it was last changed, unless one of its
jobs is still queued or running. Its jobs have their own retention
(:mod:`climpact_web.jobs.retention`). This runs wherever expired jobs are purged (the
worker, ``climpact-web manage purgejobs``), registered in :class:`.apps.StationsConfig`.
"""

from __future__ import annotations

import datetime as dt
import logging
import shutil
import uuid

from django.db.models import Q

from climpact_web.jobs.models import Status

logger = logging.getLogger("climpact_web.stations")


def purge_expired_analyses(now: dt.datetime, days: int) -> int:
    from climpact_web.stations.models import StationAnalysis, stations_dir

    cutoff = now - dt.timedelta(days=days)
    active = (Status.QUEUED, Status.RUNNING)
    expired = StationAnalysis.objects.filter(updated_at__lt=cutoff).exclude(
        Q(qc_job__status__in=active)
        | Q(indices_job__status__in=active)
        | Q(sector_job__status__in=active)
    )
    count = 0
    for analysis in expired:
        analysis.delete_files()
        count += StationAnalysis.objects.filter(pk=analysis.pk).delete()[0]

    # Folders left without an analysis (an interrupted upload).
    root = stations_dir()
    if root.is_dir():
        known = {str(pk) for pk in StationAnalysis.objects.values_list("pk", flat=True)}
        for folder in root.iterdir():
            if folder.name in known or not _is_uuid(folder.name):
                continue
            if folder.stat().st_mtime < cutoff.timestamp():
                shutil.rmtree(folder, ignore_errors=True)
    if count:
        logger.info("Deleted %d expired station analysis(es)", count)
    return count


def _is_uuid(name: str) -> bool:
    try:
        uuid.UUID(name)
    except ValueError:
        return False
    return True
