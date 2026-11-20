from django.apps import AppConfig


class StationsConfig(AppConfig):
    name = "climpact_web.stations"
    label = "stations"
    verbose_name = "Stations and workspaces"

    def ready(self) -> None:
        from climpact_web.jobs.retention import register_keeper, register_purger
        from climpact_web.stations.retention import kept_jobs, purge_expired_workspaces

        register_purger(purge_expired_workspaces)
        register_keeper(kept_jobs)
