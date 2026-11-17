"""The hosted site's abuse limits (#125): Turnstile on the forms that create work, per-client
quotas, the queue and disk guards, and the job time limit. All off in local mode."""

import datetime as dt
import logging
import re
import time

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, RequestFactory
from django.utils import timezone

from climpact_web.core import limits
from climpact_web.jobs import registry, worker
from climpact_web.jobs.models import Job, JobStart, Status
from climpact_web.jobs.registry import register
from climpact_web.jobs.retention import purge_expired
from climpact_web.jobs.views import OWNER_KEY
from climpact_web.jobs.worker import claim, run_job
from climpact_web.stations.models import Station

IP = "203.0.113.7"
OTHER_IP = "198.51.100.9"
TOKEN_FIELD = "cf-turnstile-response"


def rows(days=800) -> str:
    first = dt.date(2000, 1, 1)
    lines = []
    for k in range(days):
        d = first + dt.timedelta(days=k)
        lines.append(f"{d.year} {d.month} {d.day} {k % 7 * 0.5:.1f} {20 + k % 5} {10 + k % 3}")
    return "\n".join(lines) + "\n"


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.RUNS_DIR = tmp_path / "media" / "runs"
    settings.JOB_PROGRESS_INTERVAL = 0
    return settings


@pytest.fixture
def hosted(settings, monkeypatch):
    """Hosted mode's limits (the rest of the hosted settings are left as in local mode),
    with plenty of free disk unless a test says otherwise."""
    settings.IS_HOSTED = True
    settings.MAX_ACTIVE_JOBS_PER_IP = 2
    settings.MAX_DAILY_JOBS_PER_IP = 30
    settings.MAX_QUEUED_JOBS = 20
    settings.SPECULATIVE_MAX_QUEUED = 3
    settings.MIN_FREE_DISK_GB = 2
    settings.TURNSTILE_SITE_KEY = settings.TURNSTILE_SECRET_KEY = ""
    monkeypatch.setattr(limits, "free_disk_bytes", lambda path: 100 * 1024**3)
    return settings


@pytest.fixture
def turnstile(hosted, monkeypatch):
    """Turnstile on, with Cloudflare's answer faked: tokens starting "ok" pass."""
    hosted.TURNSTILE_SITE_KEY = "test-site-key"
    hosted.TURNSTILE_SECRET_KEY = "test-secret-key"
    calls = []

    def fake(token, remote_ip):
        calls.append((token, remote_ip))
        if token.startswith("ok"):
            return {"success": True, "hostname": "climpact.app"}
        return {"success": False, "error-codes": ["invalid-input-response"]}

    monkeypatch.setattr(limits, "siteverify", fake)
    return calls


@pytest.fixture
def test_runners():
    added = []

    def add(kind, func):
        register(kind)(func)
        added.append(kind)

    yield add
    for kind in added:
        registry.RUNNERS.pop(kind, None)


def visitor(ip=IP, owner="owner-a") -> Client:
    """A browser behind Cloudflare: every request carries its CF-Connecting-IP."""
    client = Client(HTTP_CF_CONNECTING_IP=ip)
    session = client.session
    session[OWNER_KEY] = owner
    session.save()
    client.cookies["sessionid"] = session.session_key
    return client


def upload(client, **extra):
    return client.post(
        "/station/new",
        {"station_file": SimpleUploadedFile("stn.txt", rows().encode()), "intent": "read", **extra},
    )


def make_job(owner="owner-a", client="", **fields) -> Job:
    return Job.objects.create(kind="station", owner=owner, client=client, **fields)


def metadata(**extra) -> dict:
    return {
        "station_name": "Testville",
        "latitude": "-33.9",
        "longitude": "151.2",
        "base_start": "2000",
        "base_end": "2001",
        **extra,
    }


# --- The client address -------------------------------------------------------------------


def test_client_ip_trusts_cloudflare_only_in_hosted_mode(settings):
    request = RequestFactory().get("/", HTTP_CF_CONNECTING_IP=IP, REMOTE_ADDR="10.0.0.5")
    settings.IS_HOSTED = False
    assert limits.client_ip(request) == "10.0.0.5"
    settings.IS_HOSTED = True
    assert limits.client_ip(request) == IP
    forged = RequestFactory().get("/", HTTP_CF_CONNECTING_IP="nonsense", REMOTE_ADDR="10.0.0.5")
    assert limits.client_ip(forged) == "10.0.0.5"


def test_client_key_groups_an_ipv6_network(settings):
    settings.IS_HOSTED = True
    one = RequestFactory().get("/", HTTP_CF_CONNECTING_IP="2001:db8:1:2::1")
    two = RequestFactory().get("/", HTTP_CF_CONNECTING_IP="2001:db8:1:2:abcd::9")
    other = RequestFactory().get("/", HTTP_CF_CONNECTING_IP="2001:db8:1:3::1")
    assert limits.client_key(one) == limits.client_key(two) == "2001:db8:1:2::/64"
    assert limits.client_key(other) != limits.client_key(one)
    assert limits.client_key(RequestFactory().get("/", HTTP_CF_CONNECTING_IP=IP)) == IP


# --- Turnstile ------------------------------------------------------------------------------


@pytest.mark.django_db
def test_turnstile_is_off_in_local_mode_and_without_keys(settings, client):
    settings.TURNSTILE_SITE_KEY = "test-site-key"
    settings.TURNSTILE_SECRET_KEY = "test-secret-key"
    assert not limits.turnstile_enabled()  # local mode
    assert "cf-turnstile" not in client.get("/station/new").content.decode()
    assert upload(client).status_code == 302
    settings.IS_HOSTED = True
    settings.TURNSTILE_SITE_KEY = settings.TURNSTILE_SECRET_KEY = ""
    assert not limits.turnstile_enabled()  # hosted, no keys


@pytest.mark.django_db
def test_job_forms_show_the_widget_once_with_its_script(turnstile):
    html = visitor().get("/station/new").content.decode()
    assert html.count('class="cf-turnstile" data-sitekey="test-site-key"') == 1
    assert html.count("challenges.cloudflare.com/turnstile/v0/api.js") == 1
    assert "<noscript>" in html
    # The widget sits inside the New station form, before "Check and calculate" (#201).
    form = html.split('action="/station/new"', 1)[1].split("</form>", 1)[0]
    assert form.index("cf-turnstile") < form.index('value="go"')
    # Pages without such a form load nothing from Cloudflare.
    assert "challenges.cloudflare.com" not in visitor().get("/help/").content.decode()


@pytest.mark.django_db
def test_a_form_without_a_valid_token_is_refused(turnstile, caplog):
    client = visitor()
    with caplog.at_level(logging.WARNING, logger="climpact_web.limits"):
        response = upload(client)
    assert response.status_code == 400
    assert "could not confirm that you are a person" in response.content.decode()
    assert not Station.objects.exists() and turnstile == []
    assert f"from {IP}: turnstile-missing" in caplog.text

    with caplog.at_level(logging.WARNING, logger="climpact_web.limits"):
        response = upload(client, **{TOKEN_FIELD: "forged"})
    assert response.status_code == 400 and not Station.objects.exists()
    assert turnstile == [("forged", IP)]
    assert "turnstile-failed:invalid-input-response" in caplog.text

    assert upload(client, **{TOKEN_FIELD: "x" * 3000}).status_code == 400  # too long


@pytest.mark.django_db
def test_a_valid_token_lets_the_form_through(turnstile):
    client = visitor()
    response = upload(client, **{TOKEN_FIELD: "ok-1"})
    assert response.status_code == 302
    analysis = Station.objects.get()
    # The next step, which queues the quality checks, needs a token of its own.
    url = f"/station/{analysis.pk}/setup"
    assert client.post(url, metadata()).status_code == 400
    assert not Job.objects.exists()
    assert client.post(url, metadata(**{TOKEN_FIELD: "ok-2"})).status_code == 302
    job = Job.objects.get(kind="qc")
    assert job.client == IP
    run = Job.objects.get(kind="station")  # the speculative run (#178), same client
    assert run.is_speculative and run.client == IP


@pytest.mark.django_db
def test_cloudflare_unreachable_refuses_with_busy(turnstile, monkeypatch):
    def down(token, remote_ip):
        raise OSError("no route to host")

    monkeypatch.setattr(limits, "siteverify", down)
    response = upload(visitor(), **{TOKEN_FIELD: "ok"})
    assert response.status_code == 503 and response["Retry-After"] == "60"
    assert not Station.objects.exists()


@pytest.mark.django_db
def test_get_requests_and_the_sample_need_no_token(turnstile):
    client = visitor()
    assert client.get("/station/new").status_code == 200
    assert client.post("/station/sample").status_code == 302
    assert turnstile == []


@pytest.mark.django_db
def test_forms_wait_for_their_token(turnstile):
    """The sample's setup page (#163, #201): one widget in its one form (the file and the
    details), and no button outside it that sends it (#173). The widget
    names turnstile.js's callbacks and carries the texts it shows while the form waits;
    turnstile.js comes once, before Cloudflare's script."""
    client = visitor()
    load = client.post("/station/sample")["Location"]
    html = client.get(load).content.decode()
    assert 'form="station-details"' not in html  # the shortcut that raced the token is gone
    widgets = re.findall(r'<div class="cf-turnstile"[^>]*>', html)
    assert len(widgets) == 1
    for widget in widgets:
        assert 'data-callback="climpactTurnstileDone"' in widget
        assert 'data-error-callback="climpactTurnstileError"' in widget
        for name in ("wait", "slow", "failed", "retry"):
            assert re.search(rf'data-text-{name}="[^"]+"', widget), name
        assert "data-retry=" not in widget  # a Turnstile setting: never 'Try again' (#169)
    forms = re.findall(r"<form\b.*?</form>", html, re.S)
    assert [f.count('class="cf-turnstile"') for f in forms if "cf-turnstile" in f] == [1]
    assert html.count("js/turnstile.js") == 1
    assert html.index("js/turnstile.js") < html.index("turnstile/v0/api.js")


@pytest.mark.django_db
def test_no_turnstile_script_without_turnstile(hosted):
    client = visitor()
    load = client.post("/station/sample")["Location"]
    html = client.get(load).content.decode()
    assert "cf-turnstile" not in html and "turnstile.js" not in html


# --- Quotas ---------------------------------------------------------------------------------


def start_qc(client):
    """Upload, then the station details: the request that queues a job."""
    response = upload(client)
    assert response.status_code == 302, response.content.decode()[:500]
    analysis_id = response["Location"].split("/")[2]
    return client.post(f"/station/{analysis_id}/setup", metadata())


@pytest.mark.django_db
def test_active_jobs_per_client(hosted, caplog):
    client = visitor()
    assert start_qc(client).status_code == 302
    assert start_qc(client).status_code == 302
    with caplog.at_level(logging.WARNING, logger="climpact_web.limits"):
        response = start_qc(client)
    assert response.status_code == 429
    assert "You already have 2 calculations waiting or running" in response.content.decode()
    assert f"from {IP}: active-quota:2" in caplog.text
    # The two checks, each with its speculative run (#178): a station's checks and run
    # are one change, which counts once (#254).
    assert Job.objects.filter(kind="qc").count() == 2
    assert Job.objects.filter(kind="station").count() == 2
    # Another address is not held up; a finished or cancelled job frees a place.
    assert start_qc(visitor(OTHER_IP, owner="owner-b")).status_code == 302
    first = Job.objects.filter(client=IP).first()
    first.request_cancel()  # its change's run still waits: no place yet
    assert start_qc(client).status_code == 429
    for job in Job.objects.filter(params__change=first.params["change"]):
        job.request_cancel()
    assert start_qc(client).status_code == 302


@pytest.mark.django_db
def test_jobs_per_client_per_day(hosted):
    hosted.MAX_DAILY_JOBS_PER_IP = 3
    hosted.MAX_ACTIVE_JOBS_PER_IP = 0  # off
    client = visitor()
    for _ in range(3):
        assert start_qc(client).status_code == 302
    Job.objects.all().delete()  # deleting jobs does not reset the count
    response = start_qc(client)
    assert response.status_code == 429 and "in the last 24 hours" in response.content.decode()
    assert start_qc(visitor(OTHER_IP, owner="owner-b")).status_code == 302
    # A day later the count starts again.
    JobStart.objects.update(created_at=timezone.now() - dt.timedelta(hours=25))
    assert start_qc(client).status_code == 302


@pytest.mark.django_db
def test_a_full_queue_refuses_new_jobs(hosted):
    hosted.MAX_QUEUED_JOBS = 3
    for n in range(3):
        make_job(owner=f"o{n}", client=f"192.0.2.{n}")
    response = start_qc(visitor())
    assert response.status_code == 503 and response["Retry-After"] == "300"
    assert "busy just now" in response.content.decode()
    assert Job.objects.count() == 3


@pytest.mark.django_db
def test_low_disk_refuses_uploads_and_jobs(hosted, monkeypatch, caplog):
    monkeypatch.setattr(limits, "free_disk_bytes", lambda path: 1024**3)  # 1 GB < 2 GB
    client = visitor()
    with caplog.at_level(logging.WARNING, logger="climpact_web.limits"):
        response = upload(client)
    assert response.status_code == 503 and "busy just now" in response.content.decode()
    assert "disk-low:1024MB" in caplog.text
    assert client.post("/station/sample").status_code == 503
    assert not Station.objects.exists()


def test_free_disk_of_a_folder_not_made_yet(tmp_path):
    assert limits.free_disk_bytes(tmp_path / "not" / "yet") > 0


@pytest.mark.django_db
def test_retry_counts_against_the_quotas(hosted):
    client = visitor()
    failed = make_job(client=IP, status=Status.FAILED)
    make_job(client=IP)
    make_job(client=IP)
    assert client.post(f"/jobs/{failed.pk}/retry").status_code == 429
    failed.refresh_from_db()
    assert failed.status == Status.FAILED
    Job.objects.filter(status=Status.QUEUED).update(status=Status.SUCCEEDED)
    assert client.post(f"/jobs/{failed.pk}/retry").status_code == 302
    failed.refresh_from_db()
    assert failed.status == Status.QUEUED
    assert JobStart.objects.filter(client=IP).count() == 1


@pytest.mark.django_db
def test_no_quotas_in_local_mode(settings, client):
    settings.MAX_ACTIVE_JOBS_PER_IP = 1
    settings.MAX_QUEUED_JOBS = 1
    settings.MIN_FREE_DISK_GB = 10**9
    for _ in range(3):
        assert start_qc(client).status_code == 302
    # The checks and a speculative run each time (#178): no limit in local mode.
    assert Job.objects.count() == 6 and not JobStart.objects.exists()
    assert set(Job.objects.values_list("client", flat=True)) == {""}


# --- Speculative runs (#178) -----------------------------------------------------------------


def speculative_jobs():
    return Job.objects.filter(kind="station", params__speculative=True)


@pytest.mark.django_db
def test_speculative_runs_do_not_count_against_the_quotas(hosted):
    """A speculative run takes no place in the client's quotas or the queue's until the
    user asks for it. It is one change with the checks queued with it (#254), so asking
    for it charges nothing more to the daily count."""
    hosted.MAX_QUEUED_JOBS = 2
    client = visitor()
    assert start_qc(client).status_code == 302
    assert speculative_jobs().count() == 1
    assert JobStart.objects.filter(client=IP).count() == 1  # the checks only
    # The queue holds the checks and the speculative run: one ordinary job, room for one.
    assert start_qc(visitor(OTHER_IP, owner="owner-b")).status_code == 302
    analysis = Station.objects.filter(owner="owner-a").get()
    Job.objects.filter(pk=analysis.qc_job.pk).update(status=Status.SUCCEEDED)
    assert client.post(f"/station/{analysis.pk}/quality/continue").status_code == 302
    analysis.refresh_from_db()
    assert not analysis.indices_job.is_speculative
    assert JobStart.objects.filter(client=IP).count() == 1  # the checks' change


@pytest.mark.django_db
def test_speculative_runs_wait_for_a_quiet_queue(hosted, caplog):
    """No speculative run while SPECULATIVE_MAX_QUEUED jobs wait: "Use this data" then
    queues an ordinary one, within the usual limits."""
    for n in range(3):
        make_job(owner=f"o{n}", client=f"192.0.2.{n}")
    client = visitor()
    with caplog.at_level(logging.INFO, logger="climpact_web.stations"):
        assert start_qc(client).status_code == 302
    assert "speculative-queue:4" in caplog.text
    assert not speculative_jobs().exists()
    analysis = Station.objects.get()
    assert analysis.indices_job is None
    Job.objects.filter(pk=analysis.qc_job.pk).update(status=Status.SUCCEEDED)
    client.post(f"/station/{analysis.pk}/quality/continue")
    analysis.refresh_from_db()
    job = analysis.indices_job
    assert job.kind == "station" and job.status == Status.QUEUED and not job.is_speculative
    hosted.SPECULATIVE_MAX_QUEUED = 0  # off
    Job.objects.all().delete()
    assert start_qc(visitor(OTHER_IP, owner="owner-b")).status_code == 302
    assert not speculative_jobs().exists()


@pytest.mark.django_db
def test_old_quota_records_are_purged():
    JobStart.objects.create(client=IP, created_at=timezone.now() - dt.timedelta(days=3))
    JobStart.objects.create(client=IP)
    purge_expired()
    assert JobStart.objects.count() == 1


# --- The job time limit ------------------------------------------------------------------------


def run_next() -> Job:
    job = claim("test-worker")
    assert job is not None
    return run_job(job)


@pytest.mark.django_db
def test_a_job_past_the_time_limit_is_stopped(settings, test_runners):
    settings.IS_HOSTED = True
    settings.JOB_TIME_LIMIT_MINUTES = 0.001  # 60 ms

    def slow(ctx):
        ctx.progress("one", 1, 3)
        time.sleep(0.1)
        ctx.progress("two", 2, 3)
        return {}

    test_runners("slow", slow)
    Job.objects.create(kind="slow", owner="o")
    job = run_next()
    assert job.status == Status.FAILED
    assert "ran for longer than this site allows (0.001 minutes)" in job.error
    assert job.can_retry and "time limit" in job.log


@pytest.mark.django_db
def test_no_time_limit_in_local_mode(settings, test_runners):
    settings.JOB_TIME_LIMIT_MINUTES = 0.001

    def slow(ctx):
        ctx.progress("one", 1, 2)
        time.sleep(0.1)
        ctx.progress("two", 2, 2)
        return {}

    test_runners("slow", slow)
    Job.objects.create(kind="slow", owner="o")
    assert run_next().status == Status.SUCCEEDED


@pytest.mark.django_db
def test_heartbeat_ends_a_job_stuck_past_the_limit(settings, monkeypatch):
    settings.JOB_TIME_LIMIT_MINUTES = 30
    exits = []
    monkeypatch.setattr(worker.os, "_exit", exits.append)
    job = make_job(status=Status.RUNNING, heartbeat_at=timezone.now())
    beat = worker.Heartbeat("w1", 10)
    beat.job_id = job.pk
    beat.hard_deadline = time.monotonic() + 60
    beat.beat()
    assert exits == []
    beat.hard_deadline = time.monotonic() - 1
    beat.beat()
    assert exits == [3]
    job.refresh_from_db()
    assert job.status == Status.FAILED and "(30 minutes)" in job.error
    assert "worker process ended" in job.log
