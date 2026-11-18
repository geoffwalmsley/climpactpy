from django.urls import include, path

from climpact_web.stations import (
    views,
    views_add,
    views_copy,
    views_downloads,
    views_files,
    views_indices,
    views_sector,
    views_workspace,
)

app_name = "stations"

# A station's pages (#256): ``/w/<workspace>/<station slug>/…``. Its sections are Quality
# ``quality``, Indices ``indices`` (``indices/<key>`` an index's page) and Files
# ``downloads``; ``setup`` is the New station page once its file is read, and ``load`` the
# first visit's details' old address. ``inputs/<key>`` is a sheet of the Inputs panel as a
# page: the file, the station, the base period, the thresholds and the index settings
# (#198, #199); ``copy`` is Copy to workspace… (#241). The station's own address opens
# the furthest section reached; ``recalculate`` is "Recalculate" on out-of-date results
# (and on GET the Index settings sheet over Indices). The URL names keep the names they
# had under ``/station/<id>/``: ``results`` is Indices and ``result`` an index's page.
station_patterns = [
    path("", views.station_home, name="station"),
    path("setup", views.new_station, name="setup"),
    path("setup/validate", views.validate, name="validate"),
    path("load", views.load, name="load"),
    path("inputs/progress", views.inputs_progress, name="inputs_progress"),
    path("undo", views.undo, name="undo"),
    path("inputs/<slug:key>", views.edit_input, name="edit_input"),
    path("series.csv", views.series, name="series"),
    path("delete", views.delete, name="delete"),
    path("copy", views_copy.copy, name="copy"),
    path("quality", views.qc, name="qc"),
    path("quality/progress", views.qc_progress, name="qc_progress"),
    path("quality/checks/<slug:check>", views.qc_table, name="qc_table"),
    path("quality/continue", views.qc_continue, name="qc_continue"),
    path("quality/flagged.csv", views.qc_flagged, name="qc_flagged"),
    # Indices and the index pages (#78, #236): stations/views_indices.py. ``progress`` comes
    # before ``<key>``; no index has that name.
    path("indices", views_indices.results, name="results"),
    path("indices/progress", views_indices.results_progress, name="results_progress"),
    path("indices/<str:key>", views_indices.result, name="result"),
    path("recalculate", views_indices.indices, name="recalculate"),
    path("settings/validate", views_indices.indices_validate, name="indices_validate"),
    # Sector data (#90): stations/views_sector.py.
    path("sector", views_sector.sector, name="sector"),
    path("sector/progress", views_sector.sector_progress, name="sector_progress"),
    # Files (#79): stations/views_downloads.py.
    path("downloads", views_downloads.downloads, name="downloads"),
    # The station's folder as a zip with its provenance file (#239): stations/views_files.py.
    path("zip", views_files.station_zip, name="station_zip"),
]

# The pages without a station yet keep their ``/station/`` addresses: the New station page
# (#201) and the sample. ``/station/`` is the upload page's old address. Any other
# ``/station/<id>/…`` address, from before #256, redirects to the station's new one while
# the station is kept (``views.old_station_url``).
urlpatterns = [
    # Add stations (#233): start a workspace, or add stations to one; the files dropped
    # wait under ``/w/<id>/add/<files>/`` to be reviewed and added (stations/views_add.py).
    path("add/", views_add.start, name="add"),
    path("add/sample", views_add.sample, name="add_sample"),
    path("add/sample-batch", views_add.sample_batch, name="add_sample_batch"),
    path("w/<uuid:workspace_id>/add/", views_add.add_to, name="add_to"),
    path("w/<uuid:workspace_id>/add/<uuid:run_id>/", views_add.review_page, name="add_review"),
    path("w/<uuid:workspace_id>/add/<uuid:run_id>/check", views_add.add_check, name="add_check"),
    path("station/", views.upload, name="upload"),
    path("station/new", views.new_station, name="new"),
    path("station/validate", views.validate, name="validate_new"),
    path("station/sample", views.sample, name="sample"),
    path("station/sample.txt", views.sample_file, name="sample_file"),
    path("station/sample-sector.csv", views_sector.sector_sample, name="sector_sample"),
    path("station/<uuid:station_id>/", views.old_station_url),
    path("station/<uuid:station_id>/<path:rest>", views.old_station_url),
    # The workspace (#256): its one station, or its overview (#234) with the overview's
    # progress, Rename, Workspace settings and Undo (stations/views_workspace.py). Its
    # batch (``/w/<id>/batch/…``, batch/urls.py) is included before these.
    path("w/<uuid:workspace_id>/", views_workspace.workspace_page, name="workspace"),
    path(
        "w/<uuid:workspace_id>/progress",
        views_workspace.workspace_progress,
        name="workspace_progress",
    ),
    path("w/<uuid:workspace_id>/rename", views_workspace.rename, name="workspace_rename"),
    path(
        "w/<uuid:workspace_id>/settings/",
        views_workspace.settings_page,
        name="workspace_settings",
    ),
    path(
        "w/<uuid:workspace_id>/settings/<slug:key>",
        views_workspace.setting,
        name="workspace_setting",
    ),
    path("w/<uuid:workspace_id>/undo", views_workspace.undo, name="workspace_undo"),
    # Compare an index (#238): the trend grid and its CSV.
    path("w/<uuid:workspace_id>/compare/", views_workspace.compare_page, name="workspace_compare"),
    path(
        "w/<uuid:workspace_id>/compare/trends.csv",
        views_workspace.compare_csv,
        name="workspace_compare_csv",
    ),
    # The workspace's Files (#239): stations/views_files.py.
    path("w/<uuid:workspace_id>/files/", views_files.files_page, name="workspace_files"),
    path(
        "w/<uuid:workspace_id>/files/everything.zip",
        views_files.download,
        {"what": "everything"},
        name="workspace_everything",
    ),
    path(
        "w/<uuid:workspace_id>/files/trends.csv",
        views_files.download,
        {"what": "trends"},
        name="workspace_trends",
    ),
    path(
        "w/<uuid:workspace_id>/files/indices.csv",
        views_files.download,
        {"what": "indices"},
        name="workspace_indices",
    ),
    path("w/<uuid:workspace_id>/<slug:slug>/", include(station_patterns)),
]
