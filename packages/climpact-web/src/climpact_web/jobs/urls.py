from django.urls import path

from climpact_web.jobs import views

app_name = "jobs"

urlpatterns = [
    path("", views.job_list, name="list"),
    path("<uuid:job_id>/", views.job_detail, name="detail"),
    path("<uuid:job_id>/progress", views.job_progress, name="progress"),
    path("<uuid:job_id>/cancel", views.job_cancel, name="cancel"),
    path("<uuid:job_id>/retry", views.job_retry, name="retry"),
    path("<uuid:job_id>/files/<path:relative>", views.job_file, name="file"),
]
