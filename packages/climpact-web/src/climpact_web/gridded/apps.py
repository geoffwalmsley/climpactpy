from django.apps import AppConfig


class GriddedConfig(AppConfig):
    name = "climpact_web.gridded"
    label = "gridded"
    verbose_name = "Gridded runs"

    def ready(self) -> None:
        from climpact_web.gridded.retention import purge_expired_gridded
        from climpact_web.jobs.retention import register_purger

        register_purger(purge_expired_gridded)
