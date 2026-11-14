from django.urls import path

from climpact_web.stations import views

app_name = "stations"

# The step URLs of an analysis. The later steps add theirs: "results" (#79) and "sector"
# (#90), named as in core.navigation.STATION_STEPS; "indices" is a placeholder until #78.
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
    path("<uuid:analysis_id>/quality/run", views.qc_run, name="qc_run"),
    path("<uuid:analysis_id>/quality/progress", views.qc_progress, name="qc_progress"),
    path("<uuid:analysis_id>/quality/checks/<slug:check>", views.qc_table, name="qc_table"),
    path("<uuid:analysis_id>/quality/file", views.qc_replace, name="qc_replace"),
    path("<uuid:analysis_id>/quality/continue", views.qc_continue, name="qc_continue"),
    # Step 3 placeholder until #78: the whole calculation with the default parameters.
    path("<uuid:analysis_id>/indices", views.indices, name="indices"),
    path("<uuid:analysis_id>/indices/run-all", views.run_all, name="run_all"),
]
