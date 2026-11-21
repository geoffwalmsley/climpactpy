"""URL routes. Each app adds its own include here."""

from django.urls import include, path

from climpact_web.help import seo

urlpatterns = [
    # For search engines (#319): the help is the indexable part of the hosted site.
    path("robots.txt", seo.robots, name="robots"),
    path("sitemap.xml", seo.sitemap, name="sitemap"),
    path("i18n/", include("django.conf.urls.i18n")),
    path("jobs/", include("climpact_web.jobs.urls")),
    # Stations and batches (``/station/…``, ``/batch/…``) and the workspaces they belong to
    # (``/w/<id>/…``, #256). The batch's routes come first: ``/w/<id>/batch/`` is not a
    # station (stations.models.RESERVED_SLUGS).
    path("", include("climpact_web.batch.urls")),
    path("", include("climpact_web.stations.urls")),
    path("gridded/", include("climpact_web.gridded.urls")),
    path("help/", include("climpact_web.help.urls")),
    path("charts/", include("climpact_web.charts.urls")),
    path("", include("climpact_web.core.urls")),
]
