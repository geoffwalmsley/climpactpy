from django.apps import AppConfig


class GriddedConfig(AppConfig):
    name = "climpact_web.gridded"
    label = "gridded"
    verbose_name = "Gridded runs"

    def ready(self) -> None:
        from climpact_web.gridded.retention import kept_jobs, purge_expired_gridded
        from climpact_web.jobs.retention import register_keeper, register_purger

        register_purger(purge_expired_gridded)
        register_keeper(kept_jobs)
