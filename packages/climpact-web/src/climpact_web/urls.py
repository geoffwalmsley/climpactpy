"""URL routes. Each app adds its own include here (gridded: #85)."""

from django.urls import include, path

urlpatterns = [
    path("i18n/", include("django.conf.urls.i18n")),
    path("jobs/", include("climpact_web.jobs.urls")),
    path("station/", include("climpact_web.stations.urls")),
    path("", include("climpact_web.core.urls")),
]
