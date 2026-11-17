from django.urls import include, path

from climpact_web.batch import views

app_name = "batch"

# A batch's pages are its workspace's (#256): ``/w/<workspace>/batch/…``, as a batch makes
# its own workspace. They stay until Add stations (#233) and the workspace overview (#234)
# replace them. Its results are the workspace's own address, ``/w/<workspace>/``
# (``stations:workspace``), where the overview will be: ``results`` redirects there.
run_patterns = [
    path("", views.check_page, name="check"),
    path("files", views.add_files, name="add_files"),
    path("options", views.options, name="options"),
    path("run", views.run_batch, name="run"),
    path("results", views.old_results),
    path("progress", views.progress, name="progress"),
    path("delete", views.delete, name="delete"),
]

# Starting a batch, before it has a workspace, keeps ``/batch/``. Any ``/batch/<id>/…``
# address from before #256 redirects to the batch's new one while it is kept.
urlpatterns = [
    path("batch/", views.start, name="start"),
    path("batch/sample", views.sample, name="sample"),
    path("batch/sample-metadata.txt", views.sample_metadata_file, name="sample_metadata"),
    path("batch/<uuid:run_id>/", views.old_batch_url),
    path("batch/<uuid:run_id>/<path:rest>", views.old_batch_url),
    path("w/<uuid:workspace_id>/batch/", include(run_patterns)),
]
