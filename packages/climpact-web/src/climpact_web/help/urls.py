from django.urls import path

from climpact_web.help import views

app_name = "help"

urlpatterns = [
    path("", views.index, name="index"),
    path("search/", views.search_view, name="search"),
    path("topics/", views.topic_list, name="topics"),
    path("sections/<str:section_id>/", views.section, name="section"),
    path("<slug:slug>/", views.guide, name="guide"),
]
