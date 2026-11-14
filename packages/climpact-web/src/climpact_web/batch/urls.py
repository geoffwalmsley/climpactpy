from django.urls import path

from climpact_web.batch import views

app_name = "batch"

urlpatterns = [
    path("", views.start, name="start"),
    path("sample", views.sample, name="sample"),
    path("sample-metadata.txt", views.sample_metadata_file, name="sample_metadata"),
    path("<uuid:run_id>/", views.check_page, name="check"),
    path("<uuid:run_id>/files", views.add_files, name="add_files"),
    path("<uuid:run_id>/options", views.options, name="options"),
    path("<uuid:run_id>/run", views.run_batch, name="run"),
    path("<uuid:run_id>/results", views.results, name="results"),
    path("<uuid:run_id>/progress", views.progress, name="progress"),
    path("<uuid:run_id>/open/<str:name>", views.open_station, name="open_station"),
    path("<uuid:run_id>/delete", views.delete, name="delete"),
]
