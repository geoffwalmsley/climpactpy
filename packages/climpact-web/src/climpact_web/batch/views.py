"""The batch's addresses (#80). A batch is a way to fill a workspace (#255): Add stations
(#233, ``stations.views_add``) makes one of the files dropped on it, and queues it when the
stations are added; the workspace's overview (#234, ``stations.views_workspace``) at the
workspace's address ``/w/<id>/`` (#256) shows each station's progress and then its state.

The batch's own pages went with #271: ``/batch/`` and ``/batch/sample`` lead to Add
stations, and ``/w/<id>/batch/`` to the files waiting there, or to the workspace once they
are added. What is left here: R's sample batch (Add stations' "Use the sample batch") and
its metadata file to download, and the batch's old addresses.

A batch is visible only to the browser session that created it, like a job: any other
session gets 404.
"""

from __future__ import annotations

from pathlib import Path

from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_safe

from climpact_web.batch.models import BatchRun
from climpact_web.jobs.views import OWNER_KEY

SAMPLE_DIR = Path(__file__).resolve().parent / "sample_data"
SAMPLE_METADATA = "climpact.sample.batch.metadata.txt"


def sample_files() -> dict[str, bytes]:
    """R's sample batch: two copies of the Sydney file under the names its metadata file
    gives (R ships the same file twice; the package keeps one, gzipped)."""
    from climpact_web.stations.views import sample_bytes

    data = sample_bytes()
    return {
        "sydney_observatory_hill_1936-2015.txt": data,
        "sydney_observatory_hill_batch_file_2.txt": data,
    }


def sample_metadata() -> bytes:
    return (SAMPLE_DIR / SAMPLE_METADATA).read_bytes()


def get_run(request, workspace_id) -> BatchRun:
    """The batch of the workspace ``workspace_id`` (#256), if it is this session's; 404
    otherwise. A batch makes its own workspace, so a workspace has one at most."""
    owner = request.session.get(OWNER_KEY) or "-"
    runs = BatchRun.objects.filter(workspace_id=workspace_id, owner=owner, workspace__owner=owner)
    # The batch that ran, before files waiting on Add stations (#233), a batch with no job.
    run = runs.exclude(job=None).first() or runs.first()
    if run is None:
        raise Http404
    return run


@require_safe
def old_batch_url(request, run_id, rest=""):
    """An address from before #256, ``/batch/<id>/<rest>``: a temporary (302) redirect to
    the batch's own under its workspace, with the query string, while the batch is kept;
    404 after that, or for another session's batch."""
    owner = request.session.get(OWNER_KEY) or "-"
    run = get_object_or_404(BatchRun, pk=run_id, owner=owner)
    target = run.results_url if rest == "results" else run.url("check") + rest
    query = request.META.get("QUERY_STRING", "")
    return redirect(f"{target}?{query}" if query else target)


@require_http_methods(["GET", "HEAD", "POST"])
def start(request):
    """The batch's first page's old address (before #233): to Add stations."""
    return redirect("stations:add")


@require_http_methods(["GET", "HEAD", "POST"])
def sample(request):
    """The sample batch's old address: to Add stations, whose "Use the sample batch" makes
    it (``stations:add_sample_batch``)."""
    return redirect("stations:add")


@require_safe
def sample_metadata_file(request):
    """R's sample metadata file, to use as a template (R links to it too)."""
    response = HttpResponse(sample_metadata(), content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{SAMPLE_METADATA}"'
    return response


@never_cache
@require_safe
def check_page(request, workspace_id):
    """``/w/<id>/batch/``, the batch's check page before #271: the files waiting on Add
    stations (#233), or the workspace once they are added. A batch checked by the old batch
    upload and never run has no review: Add stations."""
    run = get_run(request, workspace_id)
    if run.job_id:
        return redirect(run.results_url)
    if run.report.get("files") is not None:
        return redirect("stations:add_review", run.workspace_id, run.pk)
    return redirect("stations:add")


# ---- The results: the workspace overview (#234) ------------------------------------------


@require_safe
def old_results(request, workspace_id):
    """``/w/<id>/batch/results``: a temporary (302) redirect to the workspace's address,
    which shows the results (#256)."""
    run = get_run(request, workspace_id)
    query = request.META.get("QUERY_STRING", "")
    return redirect(f"{run.results_url}?{query}" if query else run.results_url)
