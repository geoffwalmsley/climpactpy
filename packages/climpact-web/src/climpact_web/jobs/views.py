"""Job pages: follow a job's progress, cancel, retry, download results.

A job is visible only to the browser session that created it (``owner``): any other
session gets 404, the same as for a job that does not exist (or was deleted).
"""

from __future__ import annotations

import datetime as dt
import secrets

from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST, require_safe

from climpact_web.jobs.models import Job, Status
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


def create_job(request, kind: str, params: dict, files: dict | None = None, title: str = "") -> Job:
    """Queue a job for this session, with its uploaded files (``{name: UploadedFile}``)
    saved into its ``input/`` folder; a key ``"<folder>/<name>"`` saves into a folder of
    ``input/`` (see :meth:`LocalJobStorage.save_input`). Workers see the job only when the
    transaction commits, after its files are in place."""
    storage = get_storage()
    with transaction.atomic():
        job = Job.objects.create(
            kind=kind, owner=owner_token(request), params=params, title=title[:200]
        )
        storage.create(job)
        for key, uploaded in (files or {}).items():
            folder, _, name = key.partition("/")
            if not name:
                folder, name = "", key
            storage.save_input(job, name, uploaded, folder)
    return job


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
    files = []
    if job.status == Status.SUCCEEDED:
        files = list(job.result.get("files", []))
    remaining = job.remaining(now)
    return {
        "job": job,
        "stage_label": stage_label(job.stage),
        "elapsed": format_duration(job.elapsed(now)),
        "remaining": format_duration(remaining) if remaining is not None else "",
        "delay": poll_delay(job, request.GET.get("hidden") == "true", now),
        "worker_missing": job.status == Status.QUEUED and not worker_running(now),
        "zip_file": job.result.get("zip") if job.status == Status.SUCCEEDED else None,
        "files": files,
    }


@require_safe
def job_list(request):
    jobs = Job.objects.filter(owner=request.session.get(OWNER_KEY) or "-")
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


@require_POST
def job_cancel(request, job_id):
    get_job(request, job_id).request_cancel()
    return redirect("jobs:detail", job_id=job_id)


@require_POST
def job_retry(request, job_id):
    """Run a failed or cancelled job again, with the same inputs and parameters."""
    get_job(request, job_id).retry()
    return redirect("jobs:detail", job_id=job_id)


@require_safe
def job_file(request, job_id, relative):
    job = get_job(request, job_id)
    if job.status != Status.SUCCEEDED:
        raise Http404
    path = get_storage().output_file(job, relative)
    if path is None:
        raise Http404
    return FileResponse(path.open("rb"), as_attachment=True, filename=path.name)
