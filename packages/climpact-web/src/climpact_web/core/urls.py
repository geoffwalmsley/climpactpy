from django.urls import path

from climpact_web.core import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("patterns/", views.patterns, name="patterns"),
    path("healthz", views.healthz, name="healthz"),
]
