"""Deleting batch folders left without a batch. A batch itself is deleted with its
workspace (#231, :mod:`climpact_web.stations.retention`); this removes the folders of
interrupted uploads and of the batches dropped by #231's migration, once older than the
retention period. Registered with the jobs app's purge in :class:`.apps.BatchConfig`."""

from __future__ import annotations

import datetime as dt

from climpact_web.stations.retention import delete_stray_folders


def purge_stray_batch_folders(now: dt.datetime, days: int) -> int:
    from climpact_web.batch.models import BatchRun, batches_dir

    known = {str(pk) for pk in BatchRun.objects.values_list("pk", flat=True)}
    delete_stray_folders(batches_dir(), known, now - dt.timedelta(days=days))
    return 0
