from django.urls import path

from climpact_web.stations import views, views_downloads, views_indices, views_sector

app_name = "stations"

# The step URLs of an analysis, named as in core.navigation.STATION_STEPS; the downloads
# page (#79) adds its own.
urlpatterns = [
    path("", views.upload, name="upload"),
    path("sample", views.sample, name="sample"),
    path("sample.txt", views.sample_file, name="sample_file"),
    path("sample-sector.csv", views_sector.sector_sample, name="sector_sample"),
    path("<uuid:analysis_id>/load", views.load, name="load"),
    path("<uuid:analysis_id>/load/validate", views.validate, name="validate"),
    path("<uuid:analysis_id>/file", views.replace_file, name="replace_file"),
    path("<uuid:analysis_id>/series.csv", views.series, name="series"),
    path("<uuid:analysis_id>/delete", views.delete, name="delete"),
    path("<uuid:analysis_id>/quality", views.qc, name="qc"),
    path("<uuid:analysis_id>/quality/run", views.qc_run, name="qc_run"),
    path("<uuid:analysis_id>/quality/progress", views.qc_progress, name="qc_progress"),
    path("<uuid:analysis_id>/quality/checks/<slug:check>", views.qc_table, name="qc_table"),
    path("<uuid:analysis_id>/quality/file", views.qc_replace, name="qc_replace"),
    path("<uuid:analysis_id>/quality/continue", views.qc_continue, name="qc_continue"),
    # Steps 3 and 4 (#78): stations/views_indices.py.
    path("<uuid:analysis_id>/indices", views_indices.indices, name="indices"),
    path(
        "<uuid:analysis_id>/indices/validate",
        views_indices.indices_validate,
        name="indices_validate",
    ),
    path("<uuid:analysis_id>/results", views_indices.results, name="results"),
    path(
        "<uuid:analysis_id>/results/progress",
        views_indices.results_progress,
        name="results_progress",
    ),
    path(
        "<uuid:analysis_id>/results/<str:name>/anomalies.json",
        views_indices.result_anomalies,
        name="result_anomalies",
    ),
    path("<uuid:analysis_id>/results/<str:key>", views_indices.result, name="result"),
    # Step 5, sector data (#90): stations/views_sector.py.
    path("<uuid:analysis_id>/sector", views_sector.sector, name="sector"),
    path(
        "<uuid:analysis_id>/sector/progress", views_sector.sector_progress, name="sector_progress"
    ),
    # The downloads page (#79): stations/views_downloads.py.
    path("<uuid:analysis_id>/downloads", views_downloads.downloads, name="downloads"),
]
