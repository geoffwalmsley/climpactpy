"""URL routes. Each app adds its own include here."""

from django.urls import include, path

urlpatterns = [
    path("i18n/", include("django.conf.urls.i18n")),
    path("jobs/", include("climpact_web.jobs.urls")),
    path("station/", include("climpact_web.stations.urls")),
    path("batch/", include("climpact_web.batch.urls")),
    path("gridded/", include("climpact_web.gridded.urls")),
    path("help/", include("climpact_web.help.urls")),
    path("", include("climpact_web.core.urls")),
]
