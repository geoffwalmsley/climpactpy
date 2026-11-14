from django.apps import AppConfig


class JobsConfig(AppConfig):
    name = "climpact_web.jobs"
    label = "jobs"
    verbose_name = "Background jobs"

    def ready(self) -> None:
        from climpact_web.jobs import runners  # noqa: F401  registers the built-in runners
