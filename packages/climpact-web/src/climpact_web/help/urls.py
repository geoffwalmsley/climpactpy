from django.urls import path

from climpact_web.help import views

app_name = "help"

urlpatterns = [
    path("", views.index, name="index"),
    path("search/", views.search_view, name="search"),
    path("topics/", views.topic_list, name="topics"),
    path("sections/<str:section_id>/", views.section, name="section"),
    # The Reference pages (#319): the index reference, the command line, the file formats.
    path("indices/", views.index_reference, name="index_reference"),
    path("indices/climate.indices.csv", views.index_csv, name="index_csv"),
    path("indices/<str:code>/", views.index_page, name="index"),
    path("command-line/", views.command_line, name="command_line"),
    path("formats/", views.formats, name="formats"),
    path("formats/<slug:slug>/", views.format_page, name="format"),
    path("<slug:slug>/", views.guide, name="guide"),
]
