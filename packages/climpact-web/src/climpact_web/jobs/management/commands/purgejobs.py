"""``climpact-web manage purgejobs``: delete jobs and files past the retention period."""

from django.conf import settings
from django.core.management.base import BaseCommand

from climpact_web.jobs.retention import purge_expired
from climpact_web.jobs.worker import reap_stale


class Command(BaseCommand):
    help = (
        "Delete jobs and their files older than the retention period "
        "(CLIMPACT_WEB_RETENTION_DAYS), and fail jobs whose worker has died."
    )

    def handle(self, *args, **options):
        failed = reap_stale()
        purged = purge_expired()
        self.stdout.write(
            f"Deleted {purged.jobs} job(s) older than {settings.JOB_RETENTION_DAYS} days and "
            f"{purged.folders} stray folder(s); marked {failed} stalled job(s) failed."
        )
