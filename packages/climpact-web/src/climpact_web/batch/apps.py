from django.apps import AppConfig


class BatchConfig(AppConfig):
    name = "climpact_web.batch"
    label = "batch"
    verbose_name = "Batch processing"

    def ready(self) -> None:
        from climpact_web.batch.retention import purge_expired_batches
        from climpact_web.jobs.retention import register_purger

        register_purger(purge_expired_batches)
