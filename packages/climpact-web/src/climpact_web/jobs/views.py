"""Job pages: follow a job's progress, cancel, retry, download results.

A job is visible only to the browser session that created it (``owner``): any other
session gets 404, the same as for a job that does not exist (or was deleted).
"""

from __future__ import annotations

import datetime as dt
import secrets

from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST, require_safe

from climpact_web.core.limits import (
    check_job_quotas,
    check_speculative_quotas,
    client_key_if_hosted,
    record_job_start,
)
from climpact_web.jobs.models import CHANGE, SPECULATIVE, Job, Status, ordinary_q
from climpact_web.jobs.stages import stage_label
from climpact_web.jobs.storage import get_storage
from climpact_web.jobs.worker import worker_running

OWNER_KEY = "jobs_owner"

# Polling of the progress fragment: soon after a job starts, then less often; much less
# often while the browser tab is hidden (it polls again as soon as it is shown).
HIDDEN_POLL_SECONDS = 30


def owner_token(request) -> str:
    """The session's job owner token, created on first use."""
    token = request.session.get(OWNER_KEY)
    if not token:
        token = secrets.token_urlsafe(24)
        request.session[OWNER_KEY] = token
    return token


def create_job(
    request,
    kind: str,
    params: dict,
    files: dict | None = None,
    title: str = "",
    speculative: bool = False,
    inputs: dict | None = None,
    change: str = "",
) -> Job:
    """Queue a job for this session, with its uploaded files (``{name: UploadedFile}``)
    saved into its ``input/`` folder; a key ``"<folder>/<name>"`` saves into a folder of
    ``input/`` (see :meth:`LocalJobStorage.save_input`). Workers see the job only when the
    transaction commits, after its files are in place.

    In hosted mode the queue, disk and per-client limits are checked first
    (:func:`~climpact_web.core.limits.check_job_quotas`), which may raise
    :class:`~climpact_web.core.limits.Refused`.

    A ``speculative`` job (#178) is checked against the limits for speculative runs instead
    (:func:`~climpact_web.core.limits.check_speculative_quotas`) and is not counted as a
    start for the daily quota until it is promoted (:func:`promote`). ``inputs`` records
    what the job is produced from (``Job.inputs``, the station workspace's, #179).
    ``change`` names the change the job is queued for (``params["change"]``, #254): the jobs
    of one change count as one against the hosted limits."""
    if speculative:
        check_speculative_quotas(request, change)
        params = {**params, SPECULATIVE: True}
    else:
        check_job_quotas(request, change)
    if change:
        params = {**params, CHANGE: change}
    storage = get_storage()
    with transaction.atomic():
        client = (
            client_key_if_hosted(request)
            if speculative
            else record_job_start(request, kind, change)
        )
        job = Job.objects.create(
            kind=kind,
            owner=owner_token(request),
            client=client,
            params=params,
            title=title[:200],
            inputs=inputs or {},
        )
        storage.create(job)
        for key, uploaded in (files or {}).items():
            folder, _, name = key.partition("/")
            if not name:
                folder, name = "", key
            storage.save_input(job, name, uploaded, folder)
    return job


def promote(request, job: Job) -> None:
    """Make a speculative job an ordinary one, now that the user has asked for it (#178):
    the worker takes it in turn, the hosted limits count it, and its start counts for the
    daily quota. Only the parameters change, so a worker running it is not disturbed."""
    if not job.is_speculative:
        return
    params = {**job.params, SPECULATIVE: False}
    if Job.objects.filter(pk=job.pk).update(params=params):
        job.params = params
        record_job_start(request, job.kind, params.get(CHANGE) or "")


def get_job(request, job_id) -> Job:
    return get_object_or_404(Job, pk=job_id, owner=request.session.get(OWNER_KEY) or "-")


def format_duration(value: dt.timedelta | None) -> str:
    if value is None:
        return ""
    seconds = int(round(value.total_seconds()))
    if seconds < 60:
        return _("%(s)d s") % {"s": seconds}
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return _("%(m)d min %(s)d s") % {"m": minutes, "s": seconds}
    hours, minutes = divmod(minutes, 60)
    return _("%(h)d h %(m)d min") % {"h": hours, "m": minutes}


def poll_delay(job: Job, hidden: bool, now: dt.datetime | None = None) -> int:
    if hidden:
        return HIDDEN_POLL_SECONDS
    elapsed = job.elapsed(now)
    if elapsed is None or elapsed < dt.timedelta(seconds=10):
        return 1
    if elapsed < dt.timedelta(minutes=1):
        return 2
    return 5


def progress_context(request, job: Job) -> dict:
    now = timezone.now()
    files, zip_file = [], None
    if job.status == Status.SUCCEEDED:
        names = list(job.result.get("files", []))
        if report := job.result.get("report"):  # the PDF report, beside the station (#79)
            names.insert(0, report)
        files = [{"name": n, "size": output_size(job, n)} for n in names]
        zip_file = job.result.get("zip")
    remaining = job.remaining(now)
    return {
        "job": job,
        "stage_label": stage_label(job.stage),
        "elapsed": format_duration(job.elapsed(now)),
        "remaining": format_duration(remaining) if remaining is not None else "",
        "delay": poll_delay(job, request.GET.get("hidden") == "true", now),
        "worker_missing": job.status == Status.QUEUED and not worker_running(now),
        "zip_file": zip_file,
        "zip_size": output_size(job, zip_file) if zip_file else 0,
        "files": files,
    }


def output_size(job: Job, relative: str) -> int:
    """Size in bytes of a file of the job's output, 0 when it is not there (#79)."""
    path = get_storage().output_file(job, relative)
    return path.stat().st_size if path is not None else 0


@require_safe
def job_list(request):
    """The session's jobs, without the speculative runs that were cancelled (#178): they
    were replaced after a change to the data, and the user never asked for them."""
    jobs = Job.objects.filter(owner=request.session.get(OWNER_KEY) or "-").filter(
        ordinary_q() | ~Q(status=Status.CANCELLED)
    )
    return render(request, "jobs/job_list.html", {"jobs": jobs})


@never_cache
@require_safe
def job_detail(request, job_id):
    job = get_job(request, job_id)
    return render(request, "jobs/job_detail.html", progress_context(request, job))


@never_cache
@require_safe
def job_progress(request, job_id):
    """The progress fragment, polled by htmx while the job is queued or running."""
    job = get_job(request, job_id)
    if job.status == Status.RUNNING:
        # A page left open must not wait for ever on a dead worker.
        from climpact_web.jobs.worker import reap_stale

        if reap_stale():
            job.refresh_from_db()
    return render(request, "jobs/_progress.html", progress_context(request, job))


def _back(request, job_id):
    """Back to the page the form was on (``next``, a URL of this site), else the job."""
    from django.utils.http import url_has_allowed_host_and_scheme

    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(
        target, {request.get_host()}, request.is_secure()
    ):
        return redirect(target)
    return redirect("jobs:detail", job_id=job_id)


@require_POST
def job_cancel(request, job_id):
    get_job(request, job_id).request_cancel()
    return _back(request, job_id)


@require_POST
def job_retry(request, job_id):
    """Run a failed or cancelled job again, with the same inputs and parameters. It counts
    as a new job for the hosted limits; no human check, since it starts no new upload."""
    job = get_job(request, job_id)
    if job.can_retry:
        check_job_quotas(request)
        if job.retry():
            record_job_start(request, job.kind)
    return _back(request, job_id)


@require_safe
def job_file(request, job_id, relative):
    job = get_job(request, job_id)
    if job.status != Status.SUCCEEDED:
        raise Http404
    path = get_storage().output_file(job, relative)
    if path is None:
        raise Http404
    return FileResponse(path.open("rb"), as_attachment=True, filename=path.name)
