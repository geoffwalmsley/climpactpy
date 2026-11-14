from django.urls import path

from climpact_web.gridded import views

app_name = "gridded"

urlpatterns = [
    path("", views.start, name="start"),
    path("upload", views.upload, name="upload"),
    path("sample", views.sample, name="sample"),
    path("sample.nc", views.sample_file, name="sample_file"),
    path("browse", views.browse, name="browse"),
    path("<uuid:run_id>/", views.setup, name="setup"),
    path("<uuid:run_id>/checks", views.checks, name="checks"),
    path("<uuid:run_id>/results", views.results, name="results"),
    path("<uuid:run_id>/progress", views.progress, name="progress"),
    path("<uuid:run_id>/explore", views.explore, name="explore"),
    path("<uuid:run_id>/map.csv", views.map_csv, name="map_csv"),
    path("<uuid:run_id>/series.csv", views.series_csv, name="series_csv"),
    path("<uuid:run_id>/series.json", views.series_json, name="series_json"),
    path("<uuid:run_id>/download.zip", views.download_all, name="download_all"),
    path("<uuid:run_id>/delete", views.delete, name="delete"),
]
