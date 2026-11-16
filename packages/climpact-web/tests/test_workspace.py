"""The station workspace (#179): the section tabs and their states, results kept and marked
out of date after a change to each input until their replacement has finished, the
workspace's addresses, two browser tabs on one analysis in hosted mode, retention, and the
migration that records the inputs."""

import datetime as dt
import re

import pytest
from django.test import Client
from django.utils import timezone
from test_indices_results import STATION, _station_upload, defaults, finish, ready_analysis
from test_qc_review import run_next

from climpact_web.jobs.models import Job, Status
from climpact_web.jobs.retention import purge_expired
from climpact_web.stations import workspace
from climpact_web.stations.forms import QC_DEFAULTS
from climpact_web.stations.models import StationAnalysis, Step

pytestmark = pytest.mark.django_db

DETAILS = {"station_name": STATION, "latitude": "0", "longitude": "0",
           "base_start": "1971", "base_end": "2000"}  # fmt: skip


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.RUNS_DIR = tmp_path / "media" / "runs"
    settings.JOB_RETENTION_DAYS = 7
    return settings


def in_use(client) -> tuple[StationAnalysis, Job, Job]:
    """The Sydney sample through the real flow: the details confirmed, the checks run, the
    speculative run finished (with R's lat0 outputs) and "Use this data". Returns the
    analysis, its checks and its run, each with the inputs it was made from."""
    analysis = ready_analysis(client)
    qc = run_next()
    assert qc.kind == "qc" and qc.status == Status.SUCCEEDED, qc.error
    run = finish(analysis.indices_job)
    response = client.post(f"/station/{analysis.pk}/quality/continue")
    assert response["Location"] == f"/station/{analysis.pk}/results"
    analysis.refresh_from_db()
    assert (analysis.qc_job, analysis.indices_job, analysis.step) == (qc, run, Step.RESULTS)
    assert workspace.section_states(analysis) == {
        "data": "done", "quality": "done", "results": "done", "files": "done",
    }  # fmt: skip
    return analysis, qc, run


def states(html) -> dict[str, str]:
    """The tabs' states, as the page shows them."""
    return dict(re.findall(r'data-tab="(\w+)" data-state="(\w+)"', html))


def page(client, analysis, path="results") -> str:
    response = client.get(f"/station/{analysis.pk}/{path}")
    assert response.status_code == 200, (path, response.get("Location"))
    return response.content.decode()


def assert_kept(*jobs):
    """The jobs of the old inputs are kept, finished: nothing was deleted or reset."""
    for job in jobs:
        job.refresh_from_db()
        assert job.status == Status.SUCCEEDED


# ---- each input marks what depends on it out of date ---------------------------------------


def test_new_base_period_marks_results_out_of_date_until_replaced(client):
    analysis, qc, run = in_use(client)
    base = f"/station/{analysis.pk}"
    response = client.post(f"{base}/load", {**DETAILS, "base_start": "1981", "base_end": "2010"})
    # The checks do not use the base period: straight to the results it changes.
    assert response["Location"] == f"{base}/results"
    analysis.refresh_from_db()
    new = analysis.indices_job
    assert analysis.qc_job == qc and new != run and new.status == Status.QUEUED
    assert new.params["replaces"] == str(run.pk) and not new.is_speculative  # the user's own
    assert new.inputs["metadata"]["base_start"] == 1981
    assert_kept(qc, run)
    html = page(client, analysis)
    assert "Results are out of date. Recalculating" in html
    assert "You changed the base period to 1981–2010. These results use 1971–2000." in html
    assert 'class="stale-content' in html and "data-results-section" in html  # still shown
    assert 'id="results-progress"' in html
    assert states(html) == {"data": "done", "quality": "done", "results": "stale",
                            "files": "stale"}  # fmt: skip
    assert "out of date" in page(client, analysis, "results/txx")
    assert "Some files are out of date" in page(client, analysis, "downloads")
    assert "Out of date" not in page(client, analysis, "quality").split('data-tab="results"')[0]
    # The new run finishes: it is shown, and current.
    finish(new)
    html = page(client, analysis)
    assert "out of date" not in html and 'class="stale-content' not in html
    assert states(html)["results"] == "done" and "base period 1981–2010" in html


def test_corrected_file_marks_quality_and_results_out_of_date_until_replaced(client):
    analysis, qc, run = in_use(client)
    base = f"/station/{analysis.pk}"
    old_hash = analysis.file_hash
    client.post(f"{base}/quality/file", {"station_file": _station_upload()})
    analysis.refresh_from_db()
    assert analysis.file_hash != old_hash and analysis.step == Step.RESULTS
    new_qc, new_run = analysis.qc_job, analysis.indices_job
    assert new_qc.params["replaces"] == str(qc.pk) and new_run.params["replaces"] == str(run.pk)
    assert new_qc.inputs["file"] == new_run.inputs["file"] == analysis.file_hash
    assert_kept(qc, run)
    # Quality: the old checks, under a banner with the new checks' progress; no decision
    # until they have finished.
    html = page(client, analysis, "quality")
    assert "Checking again" in html and "You loaded a different station file." in html
    assert 'id="qc-progress"' in html and 'id="qc-verdict-title"' in html
    assert "/quality/continue" not in html
    assert states(html) == {"data": "done", "quality": "stale", "results": "stale",
                            "files": "stale"}  # fmt: skip
    assert client.post(f"{base}/quality/continue")["Location"] == f"{base}/quality"
    # The new checks finish (the worker takes them first): Quality is current again.
    assert run_next() == new_qc
    html = page(client, analysis, "quality")
    assert "Checking again" not in html and "/quality/continue" in html
    assert states(html)["quality"] == "done" and states(html)["results"] == "stale"
    finish(new_run)
    assert states(page(client, analysis))["results"] == "done"


def test_new_thresholds_mark_quality_and_results_out_of_date_until_replaced(client):
    analysis, qc, run = in_use(client)
    base = f"/station/{analysis.pk}"
    thresholds = {**{k: str(v) for k, v in QC_DEFAULTS.items()}, "prec_max": "150"}
    client.post(f"{base}/quality/run", thresholds)
    analysis.refresh_from_db()
    new_qc, new_run = analysis.qc_job, analysis.indices_job
    assert new_qc.inputs["qc"]["prec_max"] == 150 and new_run.params["qc"]["prec_max"] == 150
    assert_kept(qc, run)
    html = page(client, analysis, "quality")
    assert "You changed the quality-control thresholds." in html and "Checking again" in html
    html = page(client, analysis)
    assert "You changed the quality-control thresholds." in html
    assert states(html)["results"] == "stale" and "data-results-section" in html
    assert run_next() == new_qc
    finish(new_run)
    assert states(page(client, analysis)) == {"data": "done", "quality": "done",
                                              "results": "done", "files": "done"}  # fmt: skip


def test_new_settings_mark_results_out_of_date_until_replaced(client):
    analysis, qc, run = in_use(client)
    base = f"/station/{analysis.pk}"
    client.post(f"{base}/indices", {**defaults(), "rx_days": "7"})
    analysis.refresh_from_db()
    new = analysis.indices_job
    assert new.inputs["settings"]["params"]["rx_days"] == 7 and analysis.qc_job == qc
    assert_kept(qc, run)
    html = page(client, analysis)
    assert "You changed the settings." in html and "Results are out of date. Recalculating" in html
    assert states(html)["quality"] == "done" and states(html)["results"] == "stale"
    finish(new, rename={"rx3day": "rx7day"})
    html = page(client, analysis)
    assert "out of date" not in html and "Days for Rxdday 7 days" in html


def test_changing_a_detail_back_shows_the_old_results_again(client):
    """Undoing a change links the results of those inputs again, without a new run."""
    analysis, _qc, run = in_use(client)
    base = f"/station/{analysis.pk}"
    client.post(f"{base}/load", {**DETAILS, "base_start": "1981", "base_end": "2010"})
    analysis.refresh_from_db()
    pending = analysis.indices_job
    client.post(f"{base}/load", DETAILS)
    analysis.refresh_from_db()
    pending.refresh_from_db()
    assert analysis.indices_job == run and pending.status == Status.CANCELLED
    assert Job.objects.filter(kind="station").count() == 2  # nothing new queued
    assert states(page(client, analysis))["results"] == "done"


def test_out_of_date_results_without_a_run_offer_recalculate(client, settings):
    """When no replacement could be queued (here it was cancelled), the banner offers one
    action, "Recalculate", which queues the run of the current inputs."""
    analysis, _qc, run = in_use(client)
    base = f"/station/{analysis.pk}"
    client.post(f"{base}/load", {**DETAILS, "latitude": "-10"})
    analysis.refresh_from_db()
    client.post(f"/jobs/{analysis.indices_job.pk}/cancel")
    html = page(client, analysis)
    assert "Results are out of date</h2>" in html
    assert "You changed the latitude or longitude." in html
    form = re.search(r'<form method="post" action="[^"]+/indices"[^>]*>.*?</form>', html, re.S)
    assert 'name="recalculate" value="1"' in form.group(0)
    analysis.refresh_from_db()
    assert analysis.indices_job == run  # the cancelled run gave its place back
    assert client.post(f"{base}/indices", {"recalculate": "1"})["Location"] == f"{base}/results"
    analysis.refresh_from_db()
    new = analysis.indices_job
    assert new.status == Status.QUEUED and new.inputs["metadata"]["latitude"] == -10
    assert new.params["replaces"] == str(run.pk)


def test_new_file_on_data_marks_sections_out_of_date_until_confirmed(client):
    analysis, qc, run = in_use(client)
    base = f"/station/{analysis.pk}"
    client.post(f"{base}/file", {"station_file": _station_upload()})
    analysis.refresh_from_db()
    assert (analysis.qc_job, analysis.indices_job) == (qc, run)  # kept; nothing queued yet
    html = page(client, analysis, "quality")
    assert "The checks are out of date" in html and f'href="{base}/load"' in html
    assert states(html) == {"data": "done", "quality": "stale", "results": "stale",
                            "files": "stale"}  # fmt: skip
    # Confirming the details checks the new file and calculates it again.
    assert client.post(f"{base}/load", DETAILS)["Location"] == f"{base}/quality"
    analysis.refresh_from_db()
    assert analysis.qc_job != qc and analysis.indices_job != run


# ---- the tabs ------------------------------------------------------------------------------


def test_tabs_follow_the_workspace_from_the_first_visit(client):
    load = client.post("/station/sample")["Location"]
    analysis = StationAnalysis.objects.get()
    html = client.get(load).content.decode()
    assert states(html) == {"data": "todo", "quality": "locked", "results": "locked",
                            "files": "locked"}  # fmt: skip
    # A tab not available yet is not a link; each says its status in words.
    assert '<span class="tabs__tab" data-tab="results" data-state="locked">' in html
    assert '<span class="sr-only">Not available yet</span>' in html
    assert re.search(r'data-tab="data"[^>]*aria-current="page"', html)
    client.post(load, DETAILS)
    html = page(client, analysis, "quality")
    assert states(html) == {"data": "done", "quality": "running", "results": "locked",
                            "files": "locked"}  # fmt: skip
    assert "<span>Running</span>" in html  # the word shows for a state that needs the user
    run_next()
    html = page(client, analysis, "quality")
    assert states(html)["quality"] in ("done", "attention") and states(html)["files"] == "done"


def test_a_failed_check_and_a_red_verdict_need_attention(client):
    analysis = ready_analysis(client)
    Job.objects.filter(pk=analysis.qc_job.pk).update(status=Status.FAILED, error="Broken.")
    assert states(page(client, analysis, "quality"))["quality"] == "attention"
    Job.objects.filter(pk=analysis.qc_job.pk).update(
        status=Status.SUCCEEDED, result={"verdict": "fix"}
    )
    analysis.refresh_from_db()
    assert workspace.section_states(analysis)["quality"] == "attention"


# ---- addresses -------------------------------------------------------------------------------


def test_old_step_addresses_lead_to_their_tabs(client):
    analysis = ready_analysis(client)
    base = f"/station/{analysis.pk}"
    # Before "Use this data": the workspace's address opens Quality, Results go there too.
    assert client.get(f"{base}/")["Location"] == f"{base}/quality"
    assert client.get(f"{base}/results")["Location"] == f"{base}/quality"
    run_next()
    finish(analysis.indices_job)
    client.post(f"{base}/quality/continue")
    assert client.get(f"{base}/")["Location"] == f"{base}/results"
    # Each step's address is its tab's (Data, Quality, Results, Files), kept as it was.
    for path, tab in [("load", "data"), ("quality", "quality"), ("results", "results"),
                      ("downloads", "files")]:  # fmt: skip
        assert re.search(rf'data-tab="{tab}"[^>]*aria-current="page"', page(client, analysis, path))
    # The old Calculate step leads to "Adjust and recalculate" on Results (#178).
    response = client.get(f"{base}/indices?index=txx")
    assert response["Location"] == f"{base}/results?settings=open&back=txx#adjust"
    # Another session cannot open any of them.
    assert Client().get(f"{base}/").status_code == 404


# ---- several browser tabs, hosted mode -------------------------------------------------------


def test_two_tabs_see_the_same_state_from_what_is_stored(client, settings, monkeypatch):
    """Hosted mode, one session with two browser tabs open on the analysis. A change made
    in one tab shows as out of date in the other: staleness comes from the jobs' recorded
    inputs, not from anything kept in the session."""
    from climpact_web.core import limits

    settings.IS_HOSTED = True
    settings.TURNSTILE_SITE_KEY = settings.TURNSTILE_SECRET_KEY = ""
    monkeypatch.setattr(limits, "free_disk_bytes", lambda path: 100 * 1024**3)
    analysis, _qc, run = in_use(client)
    first, second = client, Client()
    second.cookies = first.cookies  # the same browser: the same session cookie
    base = f"/station/{analysis.pk}"
    session_before = dict(first.session.items())
    assert states(page(second, analysis))["results"] == "done"
    first.post(f"{base}/load", {**DETAILS, "base_start": "1981", "base_end": "2010"})
    assert dict(first.session.items()) == session_before  # nothing about it in the session
    html = page(second, analysis)
    assert "You changed the base period to 1981–2010" in html and states(html)["results"] == "stale"
    # The second tab's out-of-date form changes it back: both see the old results again.
    second.post(f"{base}/load", DETAILS)
    for tab in (first, second):
        assert states(page(tab, analysis))["results"] == "done"
    analysis.refresh_from_db()
    assert analysis.indices_job == run


# ---- retention -------------------------------------------------------------------------------


def test_retention_purges_out_of_date_jobs_as_before(client, settings):
    """Out-of-date jobs are kept only as long as any job: the purge deletes them on their
    own schedule, and the analysis still opens (here on the run in progress)."""
    analysis, _qc, run = in_use(client)
    new_base = {**DETAILS, "base_start": "1981", "base_end": "2010"}
    client.post(f"/station/{analysis.pk}/load", new_base)
    analysis.refresh_from_db()
    new = analysis.indices_job
    long_ago = timezone.now() - dt.timedelta(days=settings.JOB_RETENTION_DAYS + 1)
    Job.objects.filter(pk=run.pk).update(finished_at=long_ago)
    purge_expired()
    assert not Job.objects.filter(pk=run.pk).exists() and not run.folder.exists()
    analysis.refresh_from_db()
    assert analysis.indices_job == new  # the analysis was changed today: kept
    html = page(client, analysis)
    assert 'id="results-progress"' in html and states(html)["results"] == "running"
    # The analysis itself goes once it has not changed for the retention period, unless one
    # of its jobs is still queued or running.
    StationAnalysis.objects.filter(pk=analysis.pk).update(updated_at=long_ago)
    purge_expired()
    assert StationAnalysis.objects.filter(pk=analysis.pk).exists()
    new.request_cancel()
    analysis.qc_job.request_cancel()
    purge_expired()
    assert not StationAnalysis.objects.filter(pk=analysis.pk).exists()


# ---- the migration ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_migration_records_the_inputs_of_existing_jobs(settings):
    from migration_backfill import check

    check(settings.MEDIA_ROOT)
