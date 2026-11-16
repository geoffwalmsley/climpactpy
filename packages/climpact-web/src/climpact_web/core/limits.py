"""Abuse limits for the hosted site (#125): a human check on the forms that create work,
per-client job quotas, and guards on the queue and the disk.

Everything here is off in local mode (``settings.IS_HOSTED`` false), so the offline
install and the tests behave as before. In hosted mode:

- **Turnstile** (:func:`verify_turnstile`): Cloudflare's check that the visitor is a person.
  On when both ``TURNSTILE_SITE_KEY`` and ``TURNSTILE_SECRET_KEY`` are set. The
  ``{% turnstile %}`` tag (``core/templatetags/ui.py``) puts the widget in a form; views
  that take an upload or start a job are wrapped in :func:`human_required`, which checks the
  token the widget adds (``cf-turnstile-response``) with Cloudflare's siteverify API.
- **Quotas** (:func:`check_job_quotas`, called by ``create_job`` and the retry view): at
  most ``MAX_ACTIVE_JOBS_PER_IP`` jobs waiting or running, and ``MAX_DAILY_JOBS_PER_IP``
  jobs started in 24 hours, per client; no new job while more than ``MAX_QUEUED_JOBS``
  wait.
- **Disk** (:func:`check_disk`): no upload and no job while ``MEDIA_ROOT``'s disk has less
  than ``MIN_FREE_DISK_GB`` free.
- **Speculative runs** (#178, :func:`check_speculative_quotas`): the station calculation
  started with the defaults while the user looks at the quality checks. It is queued only
  while fewer than ``SPECULATIVE_MAX_QUEUED`` jobs wait and the client has fewer than
  ``MAX_ACTIVE_JOBS_PER_IP`` jobs waiting or running; it is left out of the other counts
  above (the queue, the client's active jobs, the daily starts) until the user asks for it,
  and the worker takes it only when no other job waits. A refusal is silent: the run is
  queued as an ordinary job when the user chooses to use the data.

A refusal raises :class:`Refused`; :class:`~climpact_web.middleware.RefusalMiddleware`
logs it (client, reason, path, so the Cloudflare rules can be tuned) and answers with a
page in plain language. The checks are not atomic: two requests at the same moment may
both pass, so a quota can be overrun by a job or two. They are a brake, not a lock.
"""

from __future__ import annotations

import datetime as dt
import functools
import ipaddress
import json
import logging
import shutil
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext

logger = logging.getLogger("climpact_web.limits")

TOKEN_FIELD = "cf-turnstile-response"
TOKEN_MAX_LENGTH = 2048  # Cloudflare's limit on a token


@dataclass
class Refused(Exception):
    """A request refused by a limit: ``message`` for the visitor, ``reason`` (a short
    code) for the log, and the HTTP ``status`` of the answer."""

    reason: str
    message: str
    status: int = 429
    retry_after: int | None = None

    def __str__(self) -> str:
        return self.reason


# The client -----------------------------------------------------------------------------


def client_ip(request) -> str:
    """The visitor's IP address. In hosted mode, Cloudflare's ``CF-Connecting-IP``
    header: the origin is reachable only through the Cloudflare Tunnel, so the header
    cannot be forged by the visitor. Anywhere else the header is ignored (anyone could
    send it) and the address is the connection's (``REMOTE_ADDR``)."""
    if settings.IS_HOSTED:
        header = request.META.get("HTTP_CF_CONNECTING_IP", "").strip()
        if _valid_ip(header):
            return header
    return request.META.get("REMOTE_ADDR", "") or ""


def client_key(request) -> str:
    """What the quotas count by: the IPv4 address, or the /64 network of an IPv6 address
    (one connection is usually given a whole /64, so its addresses are one visitor)."""
    ip = client_ip(request)
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return ip[:64]
    if address.version == 6:
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)


def _valid_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


# Turnstile ------------------------------------------------------------------------------


def turnstile_enabled() -> bool:
    return bool(
        settings.IS_HOSTED and settings.TURNSTILE_SITE_KEY and settings.TURNSTILE_SECRET_KEY
    )


def siteverify(token: str, remote_ip: str) -> dict:
    """Ask Cloudflare whether ``token`` is valid; its JSON answer."""
    data = {"secret": settings.TURNSTILE_SECRET_KEY, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip
    body = urllib.parse.urlencode(data).encode()
    request = urllib.request.Request(settings.TURNSTILE_VERIFY_URL, data=body, method="POST")
    with urllib.request.urlopen(request, timeout=settings.TURNSTILE_TIMEOUT) as response:
        return json.load(response)


def verify_turnstile(request) -> None:
    """Refuse the request unless it carries a valid Turnstile token (when Turnstile is on).
    Checked once per request: a token can be redeemed only once."""
    if not turnstile_enabled() or getattr(request, "_turnstile_ok", False):
        return
    token = request.POST.get(TOKEN_FIELD, "")
    if not token or len(token) > TOKEN_MAX_LENGTH:
        raise Refused(
            "turnstile-missing",
            _(
                "We could not confirm that you are a person: the check above the button did "
                "not finish. It needs JavaScript. Go back, wait for the check to show a tick, "
                "and try again."
            ),
            status=400,
        )
    try:
        answer = siteverify(token, client_ip(request))
    except (OSError, ValueError) as exc:  # network errors, timeouts, a garbled answer
        logger.error("Turnstile siteverify failed: %s", exc)
        raise Refused(
            "turnstile-unavailable",
            _("We could not check that you are a person just now. Try again in a minute."),
            status=503,
            retry_after=60,
        ) from exc
    if not answer.get("success"):
        codes = ",".join(answer.get("error-codes") or []) or "unknown"
        raise Refused(
            f"turnstile-failed:{codes}",
            _(
                "We could not confirm that you are a person, or the check expired. Go back, "
                "reload the page and try again."
            ),
            status=400,
        )
    request._turnstile_ok = True


# Disk and queue -------------------------------------------------------------------------

BUSY_MESSAGE = gettext_lazy(
    "Climpact is busy just now and cannot take new calculations. Your data were not "
    "changed. Try again in a few minutes."
)


def free_disk_bytes(path: Path) -> int:
    """Free space on the disk that holds ``path`` (or its nearest existing parent)."""
    path = Path(path)
    while not path.exists() and path != path.parent:
        path = path.parent
    return shutil.disk_usage(path).free


def check_disk() -> None:
    """Refuse when the disk holding ``MEDIA_ROOT`` is nearly full (hosted mode)."""
    if not settings.IS_HOSTED or settings.MIN_FREE_DISK_GB <= 0:
        return
    free = free_disk_bytes(settings.MEDIA_ROOT)
    if free < settings.MIN_FREE_DISK_GB * 1024**3:
        raise Refused(
            f"disk-low:{free // 1024**2}MB", str(BUSY_MESSAGE), status=503, retry_after=600
        )


def check_job_quotas(request) -> None:
    """Refuse a new job (or a retry) when the queue, the disk or this client's quotas are
    full (hosted mode)."""
    if not settings.IS_HOSTED:
        return
    from climpact_web.jobs.models import Job, JobStart, Status, ordinary_q

    check_disk()
    if settings.MAX_QUEUED_JOBS > 0:
        queued = Job.objects.filter(
            ordinary_q(), status=Status.QUEUED, cancel_requested=False
        ).count()
        if queued >= settings.MAX_QUEUED_JOBS:
            raise Refused(f"queue-full:{queued}", str(BUSY_MESSAGE), status=503, retry_after=300)
    key = client_key(request)
    if settings.MAX_ACTIVE_JOBS_PER_IP > 0:
        active = Job.objects.filter(
            ordinary_q(),
            client=key,
            status__in=(Status.QUEUED, Status.RUNNING),
            cancel_requested=False,
        ).count()
        limit = settings.MAX_ACTIVE_JOBS_PER_IP
        if active >= limit:
            raise Refused(
                f"active-quota:{active}",
                ngettext(
                    "You already have %(count)d calculation waiting or running. Wait for it "
                    "to finish (or cancel it on the Jobs page), then try again.",
                    "You already have %(count)d calculations waiting or running. Wait for "
                    "one to finish (or cancel one on the Jobs page), then try again.",
                    active,
                )
                % {"count": active},
                retry_after=60,
            )
    if settings.MAX_DAILY_JOBS_PER_IP > 0:
        since = timezone.now() - dt.timedelta(days=1)
        today = JobStart.objects.filter(client=key, created_at__gte=since).count()
        limit = settings.MAX_DAILY_JOBS_PER_IP
        if today >= limit:
            raise Refused(
                f"daily-quota:{today}",
                ngettext(
                    "You have started %(count)d calculation in the last 24 hours, the most "
                    "this site allows. Try again tomorrow, or install Climpact on your own "
                    "computer, which has no limits.",
                    "You have started %(count)d calculations in the last 24 hours, the most "
                    "this site allows. Try again tomorrow, or install Climpact on your own "
                    "computer, which has no limits.",
                    today,
                )
                % {"count": today},
                retry_after=3600,
            )


def check_speculative_quotas(request) -> None:
    """Refuse a speculative run (#178) unless the queue is short and the client is not
    already using its share of the worker (hosted mode). The caller drops the run quietly."""
    if not settings.IS_HOSTED:
        return
    from climpact_web.jobs.models import Job, Status

    check_disk()
    if settings.SPECULATIVE_MAX_QUEUED <= 0:
        raise Refused("speculative-off", str(BUSY_MESSAGE), status=503)
    queued = Job.objects.filter(status=Status.QUEUED, cancel_requested=False).count()
    if queued >= settings.SPECULATIVE_MAX_QUEUED:
        raise Refused(f"speculative-queue:{queued}", str(BUSY_MESSAGE), status=503)
    if settings.MAX_ACTIVE_JOBS_PER_IP > 0:
        active = Job.objects.filter(
            client=client_key(request),
            status__in=(Status.QUEUED, Status.RUNNING),
            cancel_requested=False,
        ).count()
        if active >= settings.MAX_ACTIVE_JOBS_PER_IP:
            raise Refused(f"speculative-active:{active}", str(BUSY_MESSAGE))


def client_key_if_hosted(request) -> str:
    """The client key stored on a job: blank in local mode, as :func:`record_job_start`."""
    return client_key(request) if settings.IS_HOSTED else ""


def record_job_start(request, kind: str) -> str:
    """Note a job started by this client, for the daily quota; returns the client key
    (stored on the job in hosted mode, blank in local mode)."""
    if not settings.IS_HOSTED:
        return ""
    from climpact_web.jobs.models import JobStart

    key = client_key(request)
    JobStart.objects.create(client=key, kind=kind[:50])
    return key


def purge_job_starts(now: dt.datetime, days: int) -> int:
    """Delete the daily-quota records older than two days (run with every purge)."""
    from climpact_web.jobs.models import JobStart

    return JobStart.objects.filter(created_at__lt=now - dt.timedelta(days=2)).delete()[0]


# Views ----------------------------------------------------------------------------------


def human_required(view):
    """For a view whose POST uploads a file or starts a job: a valid Turnstile token (when
    Turnstile is on) and enough free disk (hosted mode). GETs pass straight through."""

    @functools.wraps(view)
    def wrapped(request, *args, **kwargs):
        if request.method == "POST":
            verify_turnstile(request)
            check_disk()
        return view(request, *args, **kwargs)

    return wrapped


def disk_required(view):
    """For a view whose POST writes files without a human check (the sample data): enough
    free disk (hosted mode)."""

    @functools.wraps(view)
    def wrapped(request, *args, **kwargs):
        if request.method == "POST":
            check_disk()
        return view(request, *args, **kwargs)

    return wrapped
