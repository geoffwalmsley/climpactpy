from django.urls import path

from climpact_web.gridded import views

app_name = "gridded"

urlpatterns = [
    path("", views.start, name="start"),
    path("new/", views.new, name="new"),
    path("upload", views.upload, name="upload"),
    path("sample", views.sample, name="sample"),
    path("sample.nc", views.sample_file, name="sample_file"),
    path("<uuid:run_id>/", views.run_page, name="run"),
    path("<uuid:run_id>/files/", views.files, name="files"),
    path("<uuid:run_id>/setup/", views.setup, name="setup"),
    path("<uuid:run_id>/rename/", views.rename, name="rename"),
    path("<uuid:run_id>/checks", views.checks, name="checks"),
    path("<uuid:run_id>/results", views.results, name="results"),
    path("<uuid:run_id>/progress", views.progress, name="progress"),
    path("<uuid:run_id>/explore", views.explore, name="explore"),
    path("<uuid:run_id>/map.csv", views.map_csv, name="map_csv"),
    path("<uuid:run_id>/series.csv", views.series_csv, name="series_csv"),
    path("<uuid:run_id>/series.json", views.series_json, name="series_json"),
    path("<uuid:run_id>/download.zip", views.download_all, name="download_all"),
    path("<uuid:run_id>/zip/<slug:by>/<str:group>.zip", views.download_group, name="zip"),
    path("<uuid:run_id>/file/<path:relative>", views.run_file, name="file"),
    path("<uuid:run_id>/links.txt", views.links, name="links"),
    path("<uuid:run_id>/run.json", views.run_record, name="record"),
    path("<uuid:run_id>/climpact.log", views.run_log, name="log"),
    path("<uuid:run_id>/delete", views.delete, name="delete"),
]
