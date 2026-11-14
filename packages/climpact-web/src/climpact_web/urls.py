"""URL routes. Each app adds its own include here (stations, gridded: #76-#85)."""

from django.urls import include, path

urlpatterns = [
    path("i18n/", include("django.conf.urls.i18n")),
    path("jobs/", include("climpact_web.jobs.urls")),
    path("", include("climpact_web.core.urls")),
]
