"""The station workspace (#179, #198): the section tabs and their states, the Inputs panel
and its edits, results kept and marked out of date after a change to each input until
their replacement has finished, the workspace's addresses (Data's leading to Quality), two
browser tabs on one analysis in hosted mode, retention, and the migration that records the
inputs."""

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
        "quality": "done", "results": "done", "files": "done",
    }  # fmt: skip
    return analysis, qc, run


def states(html) -> dict[str, str]:
    """The tabs' states, as the page shows them."""
    return dict(re.findall(r'data-tab="(\w+)" data-state="(\w+)"', html))


def page(client, analysis, path="results") -> str:
    response = client.get(f"/station/{analysis.pk}/{path}")
    assert response.status_code == 200, (path, response.get("Location"))
    return response.content.decode()


def edit(client, analysis, key, data, back="results"):
    """Apply an input's sheet (#198) opened on the page ``back``; returns the response."""
    base = f"/station/{analysis.pk}"
    return client.post(f"{base}/inputs/{key}", {**data, "next": f"{base}/{back}"})


def changed(html) -> set[str]:
    """The inputs the panel highlights as changed."""
    return set(re.findall(r'data-input="([\w-]+)" data-changed', html))


def assert_kept(*jobs):
    """The jobs of the old inputs are kept, finished: nothing was deleted or reset."""
    for job in jobs:
        job.refresh_from_db()
        assert job.status == Status.SUCCEEDED


# ---- each input marks what depends on it out of date ---------------------------------------


def test_new_base_period_marks_results_out_of_date_until_replaced(client):
    analysis, qc, run = in_use(client)
    base = f"/station/{analysis.pk}"
    response = edit(client, analysis, "base-period", {"base_start": "1981", "base_end": "2010"})
    # The checks do not use the base period: back to the results it changes.
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
    assert states(html) == {"quality": "done", "results": "stale", "files": "stale"}
    # The panel highlights the base period, with the run's progress beneath it.
    assert changed(html) == {"base-period"} and 'data-run="run"' in html
    assert "Base period · changed" in html and 'data-run="qc"' not in html
    assert "out of date" in page(client, analysis, "results/txx")
    assert "Some files are out of date" in page(client, analysis, "downloads")
    assert "Out of date" not in page(client, analysis, "quality").split('data-tab="results"')[0]
    # The new run finishes: it is shown, and current.
    finish(new)
    html = page(client, analysis)
    assert "out of date" not in html and 'class="stale-content' not in html
    assert states(html)["results"] == "done" and "base period 1981–2010" in html
    assert changed(html) == set() and "data-run=" not in html


def test_corrected_file_marks_quality_and_results_out_of_date_until_replaced(client):
    analysis, qc, run = in_use(client)
    base = f"/station/{analysis.pk}"
    old_hash = analysis.file_hash
    # Quality's "Replace file" opens the File sheet (#199).
    assert f'href="{base}/inputs/file?next=' in page(client, analysis, "quality")
    edit(client, analysis, "file", {"station_file": _station_upload()}, back="quality")
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
    assert states(html) == {"quality": "stale", "results": "stale", "files": "stale"}
    assert changed(html) == {"file"}
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
    response = edit(client, analysis, "thresholds", thresholds, back="quality")
    assert response["Location"] == f"{base}/quality"  # back where the sheet was opened
    analysis.refresh_from_db()
    new_qc, new_run = analysis.qc_job, analysis.indices_job
    assert new_qc.inputs["qc"]["prec_max"] == 150 and new_run.params["qc"]["prec_max"] == 150
    assert_kept(qc, run)
    html = page(client, analysis, "quality")
    assert "You changed the quality-control thresholds." in html and "Checking again" in html
    assert changed(html) == {"thresholds"} and 'data-run="qc"' in html
    assert "Quality thresholds · changed" in html and ">1 changed<" in html
    html = page(client, analysis)
    assert "You changed the quality-control thresholds." in html
    assert states(html)["results"] == "stale" and "data-results-section" in html
    assert run_next() == new_qc
    finish(new_run)
    assert states(page(client, analysis)) == {"quality": "done", "results": "done",
                                              "files": "done"}  # fmt: skip


def test_new_settings_mark_results_out_of_date_until_replaced(client):
    analysis, qc, run = in_use(client)
    response = edit(client, analysis, "settings", {**defaults(), "rx_days": "7", "report": "on"})
    assert response["Location"] == f"/station/{analysis.pk}/results"
    analysis.refresh_from_db()
    new = analysis.indices_job
    assert new.inputs["settings"]["params"]["rx_days"] == 7 and analysis.qc_job == qc
    assert_kept(qc, run)
    html = page(client, analysis)
    assert "You changed the settings." in html and "Results are out of date. Recalculating" in html
    assert states(html)["quality"] == "done" and states(html)["results"] == "stale"
    assert changed(html) == {"settings"} and "Index settings · changed" in html
    assert ">1 changed<" in html.split('data-input="settings"')[1].split("</div>")[0]
    assert 'data-run="run"' in html  # the run's progress beneath the panel
    finish(new, rename={"rx3day": "rx7day"})
    html = page(client, analysis)
    assert "out of date" not in html and "Days for Rxdday 7 days" in html


def test_changing_a_detail_back_shows_the_old_results_again(client):
    """Undoing a change links the results of those inputs again, without a new run."""
    analysis, _qc, run = in_use(client)
    edit(client, analysis, "base-period", {"base_start": "1981", "base_end": "2010"})
    analysis.refresh_from_db()
    pending = analysis.indices_job
    edit(client, analysis, "base-period", {"base_start": "1971", "base_end": "2000"})
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
    edit(
        client, analysis, "station", {"station_name": STATION, "latitude": "-10", "longitude": "0"}
    )
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


@pytest.mark.parametrize("address", ["inputs/file", "file"])
def test_replaced_file_marks_sections_out_of_date_until_replaced(client, address):
    """The File sheet's Replace (#198), and the details page's form to use a different
    file once the station is set up: the checks and the run of the new file are queued
    at once, the old ones kept, out of date."""
    analysis, qc, run = in_use(client)
    base = f"/station/{analysis.pk}"
    response = client.post(
        f"{base}/{address}", {"station_file": _station_upload(), "next": f"{base}/downloads"}
    )
    assert response["Location"] == (f"{base}/downloads" if address != "file" else f"{base}/load")
    analysis.refresh_from_db()
    assert analysis.qc_job.params["replaces"] == str(qc.pk)
    assert analysis.indices_job.params["replaces"] == str(run.pk)
    assert_kept(qc, run)
    html = page(client, analysis, "downloads")
    assert states(html) == {"quality": "stale", "results": "stale", "files": "stale"}
    # The old Data form renames a station named after its file; the sheet keeps the name.
    assert changed(html) - {"station"} == {"file"}
    assert ("station" in changed(html)) == (address == "file")
    assert 'data-run="qc"' in html and 'data-run="run"' in html


def test_new_station_name_checks_again_and_new_location_does_not(client):
    """The Station sheet: the latitude and longitude change only the results; the name
    the checks too, whose files are named after it. Its sheet says so before applying."""
    analysis, qc, run = in_use(client)
    html = page(client, analysis)
    sheet = re.search(r'<dialog class="sheet" id="sheet-station".*?</dialog>', html, re.S).group(0)
    assert "Updates Results and Files. Quality stays as it is." in sheet
    assert "A new station name updates Quality too" in sheet
    edit(
        client, analysis, "station", {"station_name": STATION, "latitude": "-10", "longitude": "5"}
    )
    analysis.refresh_from_db()
    assert analysis.qc_job == qc and analysis.indices_job != run
    assert (analysis.latitude, analysis.longitude) == (-10, 5)
    html = page(client, analysis)
    assert changed(html) == {"station"} and "−10°" not in html and "-10°, 5°" in html
    edit(
        client,
        analysis,
        "station",
        {"station_name": "renamed", "latitude": "-10", "longitude": "5"},
    )
    analysis.refresh_from_db()
    assert analysis.qc_job != qc and analysis.station_name == "renamed"
    assert states(page(client, analysis))["quality"] == "stale"


def test_each_sheet_says_what_applying_updates(client):
    """From the dependency rules of #179 (workspace.QC_INPUTS, RUN_INPUTS)."""
    analysis, _qc, _run = in_use(client)
    html = page(client, analysis, "quality")
    sheets = dict(
        re.findall(r'<dialog class="sheet" id="sheet-([\w-]+)"(.*?)</dialog>', html, re.S)
    )
    assert set(sheets) == {"file", "station", "base-period", "thresholds", "settings"}
    assert "Updates Quality, Results and Files." in sheets["file"]
    assert "Updates Results and Files. Quality stays as it is." in sheets["base-period"]
    assert "Updates Quality, Results and Files." in sheets["thresholds"]
    assert "Updates Results and Files. Quality stays as it is." in sheets["settings"]
    for key, sheet in sheets.items():
        # One primary button, Apply, and Cancel; the form posts to the edit page.
        assert sheet.count('class="button"') == 1 and ">Apply<" in sheet and ">Cancel<" in sheet
        assert f'action="/station/{analysis.pk}/inputs/{key}"' in sheet
        assert f'name="next" value="/station/{analysis.pk}/quality"' in sheet
    assert workspace.affected(["qc"]) == ["quality", "results", "files"]
    assert workspace.affected(["settings"]) == ["results", "files"]


def test_the_panel_lists_every_input_on_every_section(client):
    analysis, _qc, _run = in_use(client)
    base = f"/station/{analysis.pk}"
    for path in ("quality", "results", "downloads", "results/txx", "sector"):
        html = page(client, analysis, path)
        inputs = re.findall(r'data-input="([\w-]+)"', html)
        assert inputs == ["file", "station", "base-period", "thresholds", "settings"], path
        # The edits are links: each sheet's page without JavaScript.
        assert f'href="{base}/inputs/base-period?next=%2Fstation%2F{analysis.pk}%2F' in html
        assert 'data-sheet-open="sheet-base-period"' in html
        assert 'id="sheet-base-period"' in html
    html = page(client, analysis)
    assert "29,220 days · 3 variables" in html or re.search(r"[\d,]+ days · 3 variables", html)
    assert "1971–2000" in html and html.count(">Defaults<") == 2
    # Each input opens its sheet, the thresholds and index settings too (#199).
    for key in ("file", "station", "base-period", "thresholds", "settings"):
        assert f'href="{base}/inputs/{key}?next=%2Fstation%2F{analysis.pk}%2Fresults"' in html
        assert f'data-sheet-open="sheet-{key}"' in html and f'id="sheet-{key}"' in html


def test_the_index_settings_wait_for_use_this_data(client):
    """Before "Use this data" only the results use the index settings: no Edit, no sheet
    and no page for them (#198, #199). The thresholds sheet is there from the start."""
    analysis = ready_analysis(client)
    base = f"/station/{analysis.pk}"
    html = page(client, analysis, "quality")
    item = html.split('data-input="settings"')[1].split("</div>")[0]
    assert ">Defaults<" in item and "<a " not in item
    assert 'id="sheet-settings"' not in html and 'id="sheet-thresholds"' in html
    assert client.get(f"{base}/inputs/settings")["Location"] == f"{base}/quality"
    assert client.post(f"{base}/inputs/settings", defaults())["Location"] == f"{base}/quality"
    assert Job.objects.filter(kind="station").count() == 1  # only the speculative run


def test_no_settings_forms_on_the_output_tabs(client):
    """#199: Quality, Results and Files hold no settings form, only the decision, search
    and filters, and small actions (Delete, Try again, Recalculate). Every input is
    changed in the Inputs panel's sheets."""
    analysis, _qc, _run = in_use(client)
    base = f"/station/{analysis.pk}"
    allowed = {f"{base}/quality/continue", f"{base}/delete", f"{base}/results", ""}
    for path in ("quality", "results", "downloads", "results/txx", "sector"):
        html = re.sub(r"<dialog.*?</dialog>", "", page(client, analysis, path), flags=re.S)
        forms = re.findall(r"<form([^>]*)>(.*?)</form>", html, re.S)
        for attrs, body in forms:
            action = re.search(r'action="([^"]*)"', attrs)
            action = action.group(1) if action else ""
            if path == "sector":
                continue  # the sector file's upload, the sector comparison's own input
            assert action in allowed, (path, action)
            for name in ("iqr_temp", "rx_days", "hdd_base", "station_file", "base_start"):
                assert f'name="{name}"' not in body, (path, name)
        assert "quality/run" not in html and "quality/file" not in html, path
        assert "Adjust and recalculate" not in html and "Upload a corrected file" not in html


def test_the_edit_pages_work_without_javascript(client):
    """Each Edit is a link to a page with the sheet's form; an invalid form comes back to
    it with its errors, and Cancel and a valid form go back to the page it came from."""
    analysis, _qc, run = in_use(client)
    base = f"/station/{analysis.pk}"
    for key, title in [("file", "Replace the file"), ("station", "Station"),
                       ("base-period", "Base period"), ("thresholds", "Quality thresholds"),
                       ("settings", "Index settings")]:  # fmt: skip
        html = page(client, analysis, f"inputs/{key}?next={base}/downloads")
        assert f'<h1 class="sheet__title">{title}</h1>' in html
        assert f'href="{base}/downloads"' in html and ">Cancel<" in html  # Cancel goes back
        assert "<dialog" not in html and "data-sheet-close" not in html
    html = page(client, analysis, "inputs/station")
    assert f'value="{STATION}"' in html and 'name="base_start"' not in html
    response = edit(client, analysis, "base-period", {"base_start": "2010", "base_end": "1990"})
    assert response.status_code == 200
    html = response.content.decode()
    assert (
        "The last year must not be before the first year." in html and "data-error-summary" in html
    )
    response = edit(client, analysis, "file", {})
    assert response.status_code == 200 and "Choose a station file." in response.content.decode()
    analysis.refresh_from_db()
    assert analysis.indices_job == run  # nothing changed
    # Only this station's pages are returned to.
    outside = {"base_start": "1971", "base_end": "2000", "next": "https://evil.example/"}
    response = client.post(f"{base}/inputs/base-period", outside)
    assert response["Location"] == f"{base}/results"
    assert client.get(f"{base}/inputs/nothing").status_code == 404
    assert Client().get(f"{base}/inputs/station").status_code == 404


# ---- the tabs ------------------------------------------------------------------------------


def test_tabs_follow_the_workspace_from_the_first_visit(client):
    load = client.post("/station/sample")["Location"]
    analysis = StationAnalysis.objects.get()
    html = client.get(load).content.decode()
    assert states(html) == {"quality": "locked", "results": "locked", "files": "locked"}
    # A tab not available yet is not a link; each says its status in words.
    assert '<span class="tabs__tab" data-tab="results" data-state="locked">' in html
    assert '<span class="sr-only">Not available yet</span>' in html
    # The first visit's details: no section is current, and no Inputs panel yet.
    assert 'aria-current="page"' not in html.split("tabs__list")[1].split("</nav>")[0]
    assert "data-inputs-panel" not in html and 'name="base_start"' in html
    assert client.get(f"/station/{analysis.pk}/inputs/station")["Location"] == load
    client.post(load, DETAILS)
    html = page(client, analysis, "quality")
    assert states(html) == {"quality": "running", "results": "locked", "files": "locked"}
    assert "data-inputs-panel" in html and 'data-run="qc"' in html
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
    # Each step's address is its tab's (Quality, Results, Files), kept as it was; Data's
    # leads to "Your data" on Quality (#198).
    for path, tab in [("quality", "quality"), ("results", "results"), ("downloads", "files")]:
        assert re.search(rf'data-tab="{tab}"[^>]*aria-current="page"', page(client, analysis, path))
    assert client.get(f"{base}/load")["Location"] == f"{base}/quality#your-data"
    html = page(client, analysis, "quality")
    assert 'id="your-data"' in html and "Missing values by variable" in html
    assert 'data-tab="data"' not in html
    # The old Calculate step opens the Index settings sheet over Results (#178, #199).
    response = client.get(f"{base}/indices?index=txx")
    assert response["Location"] == f"{base}/results?settings=open&back=txx"
    assert "data-sheet-autoopen" in page(client, analysis, "results?settings=open")
    # The old anchors #adjust and #thresholds are kept for js/sheet.js to open the sheets.
    assert 'id="adjust"' in page(client, analysis, "results")
    assert 'id="thresholds"' in page(client, analysis, "quality")
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
    edit(first, analysis, "base-period", {"base_start": "1981", "base_end": "2010"})
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
