"""Deleting workspaces (#231), with their stations, batches and files, past the retention
period, and keeping the jobs they show.

When ``WORKSPACE_EXPIRY`` is on (hosted), a workspace is deleted ``JOB_RETENTION_DAYS``
after the last change to it or to any of its stations or batches (``Workspace.updated_at``),
unless one of their jobs is still queued or running. Locally it is off, and a workspace
stays until the user deletes it. Either way a job that a station or batch still shows is
never purged (:func:`kept_jobs`): it goes with the workspace. Folders left without a
station (an interrupted upload, or the analyses dropped by #231's migration) are deleted
once older than the retention period.

This runs wherever expired jobs are purged (the worker, ``climpact-web manage
purgejobs``), registered in :class:`.apps.StationsConfig`.
"""

from __future__ import annotations

import datetime as dt
import logging
import shutil
import uuid
from pathlib import Path

from django.conf import settings
from django.db.models import Q

from climpact_web.jobs.models import Job, Status

logger = logging.getLogger("climpact_web.stations")

ACTIVE = (Status.QUEUED, Status.RUNNING)


def kept_jobs() -> set[str]:
    """The ids of the jobs a station or batch shows: the checks, the run and the sector
    comparison of each station, the finished jobs they replace on the page until they
    succeed (``params["replaces"]``), the batch job a station opened from a batch shows
    (``origin["job"]``), and each batch's job."""
    from climpact_web.batch.models import BatchRun
    from climpact_web.stations.models import Station, Workspace
    from climpact_web.stations.workspace import REPLACES

    kept: set[str] = set()
    for qc, run, sector, origin in Station.objects.values_list(
        "qc_job", "indices_job", "sector_job", "origin"
    ):
        kept.update(str(pk) for pk in (qc, run, sector) if pk)
        if (origin or {}).get("job"):
            kept.add(str(origin["job"]))
    # A finished job of the old inputs stays on the page while its replacement is queued,
    # running, failed or cancelled (workspace.replaced_job).
    shown = Job.objects.filter(pk__in=kept).exclude(status=Status.SUCCEEDED)
    for params in shown.values_list("params", flat=True):
        if (params or {}).get(REPLACES):
            kept.add(str(params[REPLACES]))
    kept.update(str(pk) for pk in BatchRun.objects.exclude(job=None).values_list("job", flat=True))
    # The jobs a change to a workspace's settings replaced, while it can be undone (#254).
    for undo in Workspace.objects.exclude(undo={}).values_list("undo", flat=True):
        for jobs in (undo or {}).get("stations", {}).values():
            kept.update(str(pk) for key, pk in jobs.items() if key.endswith("_job") and pk)
    return kept


def busy_workspaces() -> Q:
    """Workspaces with a job still queued or running."""
    return (
        Q(stations__qc_job__status__in=ACTIVE)
        | Q(stations__indices_job__status__in=ACTIVE)
        | Q(stations__sector_job__status__in=ACTIVE)
        | Q(batches__job__status__in=ACTIVE)
    )


def purge_expired_workspaces(now: dt.datetime, days: int) -> int:
    from climpact_web.stations.models import Station, Workspace, stations_dir

    cutoff = now - dt.timedelta(days=days)
    count = 0
    if settings.WORKSPACE_EXPIRY:
        busy = Workspace.objects.filter(busy_workspaces()).values("pk")
        for workspace in Workspace.objects.filter(updated_at__lt=cutoff).exclude(pk__in=busy):
            workspace.delete_files()
            Workspace.objects.filter(pk=workspace.pk).delete()
            count += 1

    known = {str(pk) for pk in Station.objects.values_list("pk", flat=True)}
    delete_stray_folders(stations_dir(), known, cutoff)
    if count:
        logger.info("Deleted %d expired workspace(s)", count)
    return count


def delete_stray_folders(root: Path, known: set[str], cutoff: dt.datetime) -> None:
    """Delete the folders under ``root`` named by an id not in ``known`` and not changed
    since ``cutoff``."""
    if not root.is_dir():
        return
    for folder in root.iterdir():
        if folder.name in known or not _is_uuid(folder.name):
            continue
        if folder.stat().st_mtime < cutoff.timestamp():
            shutil.rmtree(folder, ignore_errors=True)


def _is_uuid(name: str) -> bool:
    try:
        uuid.UUID(name)
    except ValueError:
        return False
    return True
