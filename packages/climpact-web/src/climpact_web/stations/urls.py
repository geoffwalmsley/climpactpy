from django.urls import path

from climpact_web.stations import views, views_downloads, views_indices, views_sector

app_name = "stations"

# An analysis's sections (#179, #198): Quality ``quality``, Results ``results`` and Files
# ``downloads``, the addresses of the steps they replace, so links and bookmarks keep
# working. ``load`` is the first visit's details, and once they are confirmed Data's old
# address leads to Quality's "Your data". ``inputs/<key>`` is a sheet of the Inputs panel
# as a page: the file, the station, the base period, the thresholds and the index settings
# (#198, #199). ``/station/<id>/`` opens the furthest section reached, and the old
# Calculate step (``indices``) the Index settings sheet over Results.
urlpatterns = [
    path("", views.upload, name="upload"),
    path("<uuid:analysis_id>/", views.workspace_home, name="workspace"),
    path("sample", views.sample, name="sample"),
    path("sample.txt", views.sample_file, name="sample_file"),
    path("sample-sector.csv", views_sector.sector_sample, name="sector_sample"),
    path("<uuid:analysis_id>/load", views.load, name="load"),
    path("<uuid:analysis_id>/load/validate", views.validate, name="validate"),
    path("<uuid:analysis_id>/file", views.replace_file, name="replace_file"),
    path("<uuid:analysis_id>/inputs/progress", views.inputs_progress, name="inputs_progress"),
    path("<uuid:analysis_id>/inputs/<slug:key>", views.edit_input, name="edit_input"),
    path("<uuid:analysis_id>/series.csv", views.series, name="series"),
    path("<uuid:analysis_id>/delete", views.delete, name="delete"),
    path("<uuid:analysis_id>/quality", views.qc, name="qc"),
    path("<uuid:analysis_id>/quality/progress", views.qc_progress, name="qc_progress"),
    path("<uuid:analysis_id>/quality/checks/<slug:check>", views.qc_table, name="qc_table"),
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
