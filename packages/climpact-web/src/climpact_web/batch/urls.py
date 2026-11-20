from django.urls import include, path

from climpact_web.batch import views

app_name = "batch"

# A batch's addresses are its workspace's (#256): ``/w/<workspace>/batch/…``, as a batch
# makes its own workspace. Its pages went with #271 (Add stations, #233, makes and queues
# a batch): ``check`` leads to the files waiting on Add stations, or to the workspace,
# whose overview (#234) at ``/w/<workspace>/`` (``stations:workspace``) shows the results,
# as ``results`` does.
run_patterns = [
    path("", views.check_page, name="check"),
    path("results", views.old_results),
]

# ``/batch/`` and ``/batch/sample``, the batch's first page and its sample before #233, lead
# to Add stations. Any ``/batch/<id>/…`` address from before #256 redirects to the batch's
# new one while it is kept.
urlpatterns = [
    path("batch/", views.start, name="start"),
    path("batch/sample", views.sample, name="sample"),
    path("batch/sample-metadata.txt", views.sample_metadata_file, name="sample_metadata"),
    path("batch/<uuid:run_id>/", views.old_batch_url),
    path("batch/<uuid:run_id>/<path:rest>", views.old_batch_url),
    path("w/<uuid:workspace_id>/batch/", include(run_patterns)),
]
