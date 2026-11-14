"""URL routes. Each app adds its own include here (stations, jobs, gridded: #73-#85)."""

from django.urls import include, path

urlpatterns = [
    path("i18n/", include("django.conf.urls.i18n")),
    path("", include("climpact_web.core.urls")),
]
