from django.urls import path

from climpact_web.stations import views

app_name = "stations"

# The step URLs of an analysis. The later steps add theirs: "indices" (#78), "results"
# (#79) and "sector" (#90), named as in core.navigation.STATION_STEPS.
urlpatterns = [
    path("", views.upload, name="upload"),
    path("sample", views.sample, name="sample"),
    path("sample.txt", views.sample_file, name="sample_file"),
    path("<uuid:analysis_id>/load", views.load, name="load"),
    path("<uuid:analysis_id>/load/validate", views.validate, name="validate"),
    path("<uuid:analysis_id>/file", views.replace_file, name="replace_file"),
    path("<uuid:analysis_id>/series.csv", views.series, name="series"),
    path("<uuid:analysis_id>/delete", views.delete, name="delete"),
    path("<uuid:analysis_id>/quality", views.qc, name="qc"),
    path("<uuid:analysis_id>/quality/run-all", views.run_all, name="run_all"),
]
