from django.urls import path

from climpact_web.charts import views

app_name = "charts"

# Data for the interactive charts (#75). See TECHNICAL.md, "Charts".
urlpatterns = [
    path("station/<uuid:analysis_id>/daily.json", views.station_daily, name="station_daily"),
    path("jobs/<uuid:job_id>/series.json", views.job_series_list, name="job_series_list"),
    path("jobs/<uuid:job_id>/series/<str:name>.json", views.job_series, name="job_series"),
    path("sample/daily.json", views.sample_daily, name="sample_daily"),
    path("sample/series/<str:name>.json", views.sample_series, name="sample_series"),
]
