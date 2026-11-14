from django.apps import AppConfig


class CoreConfig(AppConfig):
    """The UI shell: base templates, static files, home page and health check."""

    name = "climpact_web.core"
    label = "core"
    default_auto_field = "django.db.models.BigAutoField"
