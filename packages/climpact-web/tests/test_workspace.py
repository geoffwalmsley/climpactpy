"""The station workspace (#179, #198): the section tabs and their states, the Inputs panel
and its edits, results kept and marked out of date after a change to each input until
their replacement has finished, the workspace's addresses (Data's leading to Quality), two
browser tabs on one analysis in hosted mode, retention, and the migration that records the
inputs."""

import datetime as dt
import re
from urllib.parse import quote

import made
import pytest
from django.test import Client
from django.utils import timezone
from test_indices_results import STATION, _station_upload, defaults, finish, ready_analysis
from test_qc_review import run_next

from climpact_web.jobs.models import Job, Status
from climpact_web.jobs.retention import purge_expired
from climpact_web.stations import workspace
from climpact_web.stations.forms import QC_DEFAULTS
from climpact_web.stations.models import Station, Step, Workspace

pytestmark = pytest.mark.django_db

DETAILS = {"station_name": STATION, "latitude": "0", "longitude": "0",
           "base_start": "1971", "base_end": "2000"}  # fmt: skip


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.RUNS_DIR = tmp_path / "media" / "runs"
    settings.JOB_RETENTION_DAYS = 7
    return settings


def in_use(client) -> tuple[Station, Job, Job]:
    """The Sydney sample through the real flow: the details confirmed, the checks run, the
    speculative run finished (with R's lat0 outputs) and "Use this data". Returns the
    analysis, its checks and its run, each with the inputs it was made from."""
    analysis = ready_analysis(client)
    qc = run_next()
    assert qc.kind == "qc" and qc.status == Status.SUCCEEDED, qc.error
    run = finish(analysis.indices_job)
    response = client.post(f"{analysis.url()}quality/continue")
    assert response["Location"] == f"{analysis.url()}indices"
    analysis.refresh_from_db()
    assert (analysis.qc_job, analysis.indices_job, analysis.step) == (qc, run, Step.RESULTS)
    assert workspace.section_states(analysis) == {
        "quality": "usable", "results": "done", "files": "done",
    }  # fmt: skip
    return analysis, qc, run


def states(html) -> dict[str, str]:
    """The tabs' states, as the page shows them."""
    return dict(re.findall(r'data-tab="(\w+)" data-state="(\w+)"', html))


def page(client, analysis, path="indices") -> str:
    response = client.get(f"{analysis.url()}{path}")
    assert response.status_code == 200, (path, response.get("Location"))
    return response.content.decode()


def edit(client, analysis, key, data, back="indices"):
    """Apply an input's sheet (#198) opened on the page ``back``; returns the response."""
    base = f"/w/{analysis.workspace_id}/{analysis.slug}"
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
    base = f"/w/{analysis.workspace_id}/{analysis.slug}"
    response = edit(client, analysis, "base-period", {"base_start": "1981", "base_end": "2010"})
    # The checks do not use the base period: back to the results it changes.
    assert response["Location"] == f"{base}/indices"
    analysis.refresh_from_db()
    new = analysis.indices_job
    assert analysis.qc_job == qc and new != run and new.status == Status.QUEUED
    assert new.params["replaces"] == str(run.pk) and not new.is_speculative  # the user's own
    assert new.inputs["metadata"]["base_start"] == 1981
    assert_kept(qc, run)
    html = page(client, analysis)
    assert "Results are out of date. Recalculating" in html
    assert "You changed the base period to 1981–2010. These results use 1971–2000." in html
    assert 'class="stale-content' in html and "data-results-table" in html  # still shown
    assert 'id="results-progress"' in html
    assert states(html) == {"quality": "usable", "results": "stale", "files": "stale"}
    # The panel highlights the base period, with the run's progress beneath it.
    assert changed(html) == {"base-period"} and 'data-run="run"' in html
    assert "Base period · changed" in html and 'data-run="qc"' not in html
    assert "out of date" in page(client, analysis, "indices/txx")
    assert "Some files are out of date" in page(client, analysis, "downloads")
    assert "Out of date" not in page(client, analysis, "quality").split('data-tab="results"')[0]
    # The new run finishes: it is shown, and current.
    finish(new)
    html = page(client, analysis)
    assert "out of date" not in html and 'class="stale-content' not in html
    assert states(html)["results"] == "done" and "base 1981–2010" in html
    assert changed(html) == set() and "data-run=" not in html


def test_corrected_file_marks_quality_and_results_out_of_date_until_replaced(client):
    analysis, qc, run = in_use(client)
    base = f"/w/{analysis.workspace_id}/{analysis.slug}"
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
    assert states(html)["quality"] == "usable" and states(html)["results"] == "stale"
    finish(new_run)
    assert states(page(client, analysis))["results"] == "done"


def test_new_thresholds_mark_quality_and_results_out_of_date_until_replaced(client):
    analysis, qc, run = in_use(client)
    base = f"/w/{analysis.workspace_id}/{analysis.slug}"
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
    assert states(html)["results"] == "stale" and "data-results-table" in html
    assert run_next() == new_qc
    finish(new_run)
    assert states(page(client, analysis)) == {"quality": "usable", "results": "done",
                                              "files": "done"}  # fmt: skip


def test_new_settings_mark_results_out_of_date_until_replaced(client):
    analysis, qc, run = in_use(client)
    response = edit(client, analysis, "settings", {**defaults(), "rx_days": "7", "report": "on"})
    assert response["Location"] == f"{analysis.url()}indices"
    analysis.refresh_from_db()
    new = analysis.indices_job
    assert new.inputs["settings"]["params"]["rx_days"] == 7 and analysis.qc_job == qc
    assert_kept(qc, run)
    html = page(client, analysis)
    assert "You changed the settings." in html and "Results are out of date. Recalculating" in html
    assert states(html)["quality"] == "usable" and states(html)["results"] == "stale"
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
    base = f"/w/{analysis.workspace_id}/{analysis.slug}"
    edit(
        client, analysis, "station", {"station_name": STATION, "latitude": "-10", "longitude": "0"}
    )
    analysis.refresh_from_db()
    client.post(f"/jobs/{analysis.indices_job.pk}/cancel")
    html = page(client, analysis)
    assert "Results are out of date</h2>" in html
    assert "You changed the latitude or longitude." in html
    form = re.search(r'<form method="post" action="[^"]+/recalculate"[^>]*>.*?</form>', html, re.S)
    assert 'name="recalculate" value="1"' in form.group(0)
    analysis.refresh_from_db()
    assert analysis.indices_job == run  # the cancelled run gave its place back
    assert client.post(f"{base}/recalculate", {"recalculate": "1"})["Location"] == f"{base}/indices"
    analysis.refresh_from_db()
    new = analysis.indices_job
    assert new.status == Status.QUEUED and new.inputs["metadata"]["latitude"] == -10
    assert new.params["replaces"] == str(run.pk)


@pytest.mark.parametrize("address", ["inputs/file", "setup"])
def test_replaced_file_marks_sections_out_of_date_until_replaced(client, address):
    """The File sheet's Replace (#198), and the setup page's (#201, a form left open)
    once the station is set up: the checks and the run of the new file are queued
    at once, the old ones kept, out of date."""
    analysis, qc, run = in_use(client)
    base = f"/w/{analysis.workspace_id}/{analysis.slug}"
    response = client.post(
        f"{base}/{address}",
        {"station_file": _station_upload(), "next": f"{base}/downloads", "intent": "read"},
    )
    assert response["Location"] == (f"{base}/downloads" if address != "setup" else f"{base}/setup")
    analysis.refresh_from_db()
    assert analysis.qc_job.params["replaces"] == str(qc.pk)
    assert analysis.indices_job.params["replaces"] == str(run.pk)
    assert_kept(qc, run)
    html = page(client, analysis, "downloads")
    assert states(html) == {"quality": "stale", "results": "stale", "files": "stale"}
    # The setup page renames a station named after its file; the sheet keeps the name.
    assert changed(html) - {"station"} == {"file"}
    assert ("station" in changed(html)) == (address == "setup")
    assert 'data-run="qc"' in html and 'data-run="run"' in html


def test_new_station_name_checks_again_and_new_location_does_not(client):
    """The Station sheet: the latitude and longitude change only the results; the name
    the checks too, whose files are named after it. Its sheet says so before applying."""
    analysis, qc, run = in_use(client)
    html = page(client, analysis)
    sheet = re.search(r'<dialog class="sheet" id="sheet-station".*?</dialog>', html, re.S).group(0)
    assert "Updates Indices and Files. Quality stays as it is." in sheet
    assert "A new station name updates Quality too" in sheet
    edit(
        client, analysis, "station", {"station_name": STATION, "latitude": "-10", "longitude": "5"}
    )
    analysis.refresh_from_db()
    assert analysis.qc_job == qc and analysis.indices_job != run
    assert (analysis.latitude, analysis.longitude) == (-10, 5)
    html = page(client, analysis)
    assert changed(html) == {"station"} and "10.00°\u00a0S 5.00°\u00a0E" in html
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
    assert "data-sheet-open" in sheets.pop("inputs")  # the phone's list of them (#203)
    assert set(sheets) == {"file", "station", "base-period", "thresholds", "settings"}
    assert "Updates Quality, Indices and Files." in sheets["file"]
    assert "Updates Indices and Files. Quality stays as it is." in sheets["base-period"]
    assert "Updates Quality, Indices and Files." in sheets["thresholds"]
    assert "Updates Indices and Files. Quality stays as it is." in sheets["settings"]
    for key, sheet in sheets.items():
        # One primary button, Apply, and Cancel; the form posts to the edit page.
        assert sheet.count('class="button"') == 1 and ">Apply<" in sheet and ">Cancel<" in sheet
        assert f'action="{analysis.url()}inputs/{key}"' in sheet
        assert f'name="next" value="{analysis.url()}quality"' in sheet
    assert workspace.affected(["qc"]) == ["quality", "results", "files"]
    assert workspace.affected(["settings"]) == ["results", "files"]


def test_the_panel_lists_every_input_on_every_section(client):
    """Every section has the Inputs panel; an index's page (#237) has none, as its board:
    its provenance line says what made it."""
    analysis, _qc, _run = in_use(client)
    base = f"/w/{analysis.workspace_id}/{analysis.slug}"
    assert "data-input=" not in page(client, analysis, "indices/txx")
    for path in ("quality", "indices", "downloads", "sector"):
        html = page(client, analysis, path)
        inputs = re.findall(r'data-input="([\w-]+)"', html)
        assert inputs == ["file", "station", "base-period", "thresholds", "settings"], path
        # The edits are links: each sheet's page without JavaScript.
        assert f'href="{base}/inputs/base-period?next={quote(analysis.url(), safe="")}' in html
        assert 'data-sheet-open="sheet-base-period"' in html
        assert 'id="sheet-base-period"' in html
    html = page(client, analysis)
    assert "29,220 days · 3 variables" in html or re.search(r"[\d,]+ days · 3 variables", html)
    panel = html.split("data-inputs-panel")[1].split("</aside>")[0]
    assert "1971–2000" in panel and panel.count(">Defaults<") == 2
    # Each input opens its sheet, the thresholds and index settings too (#199).
    for key in ("file", "station", "base-period", "thresholds", "settings"):
        assert f'href="{base}/inputs/{key}?next={quote(analysis.url(), safe="")}indices"' in html
        assert f'data-sheet-open="sheet-{key}"' in html and f'id="sheet-{key}"' in html


def bar(html) -> str:
    """The Inputs bar's line (#203), its words without the markup."""
    line = re.search(r'<p class="inputs-bar__text">(.*?)</p>', html, re.S).group(1)
    # Each change and run follows a dot (CSS).
    line = re.sub(r'<span class="inputs-bar__(changed|run)">', " · ", line)
    return " ".join(re.sub(r"<[^>]+>", " ", line).split())


def test_the_inputs_bar_says_the_panel_in_one_line(client):
    """#203: on phones the Inputs panel is one line under the tabs, on every section: the
    base period and whether the thresholds and settings are the defaults, then each input
    changed since what is shown and the run under way. Its Edit opens the Inputs sheet,
    the panel's list again (without the panel's data-input marks), on a page without
    JavaScript the panel itself. Not on an input's own page, which has no panel."""
    analysis, _qc, _run = in_use(client)
    assert "data-inputs-bar" not in page(client, analysis, "indices/txx")  # #237
    for path in ("quality", "indices", "downloads", "sector"):
        html = page(client, analysis, path)
        assert bar(html) == "Inputs: 1971–2000 · defaults", path
        assert 'data-sheet-open="sheet-inputs"' in html and 'id="sheet-inputs"' in html
        sheet = html.split('id="sheet-inputs"')[1].split("</dialog>")[0]
        assert 'data-sheet-open="sheet-base-period"' in sheet and "data-input=" not in sheet
    html = page(client, analysis, "inputs/base-period")
    assert "data-inputs-bar" not in html and 'id="sheet-inputs"' not in html
    # A threshold of the user's, then a new base period: the bar says both, and the run.
    thresholds = {**{k: str(v) for k, v in QC_DEFAULTS.items()}, "prec_max": "150"}
    edit(client, analysis, "thresholds", thresholds, back="quality")
    analysis.refresh_from_db()
    html = page(client, analysis)
    assert bar(html) == (
        "Inputs: 1971–2000 · 1 setting not the default · Quality thresholds changed"
        " · Checking quality · Recalculating"
    )
    assert run_next() == analysis.qc_job
    finish(analysis.indices_job)
    analysis.refresh_from_db()
    assert bar(page(client, analysis)).startswith("Inputs: 1971–2000 · 1 setting not the default")
    edit(client, analysis, "base-period", {"base_start": "1981", "base_end": "2010"})
    html = page(client, analysis)
    assert bar(html) == (
        "Inputs: 1981–2010 · 1 setting not the default · Base period changed · Recalculating"
    )
    assert "inputs-bar--changed" in html


def test_edit_inputs_on_the_provenance_line(client):
    """#263, #264: the Indices and Quality have "Edit inputs" at the end of the
    provenance line, which opens the Inputs sheet (without JavaScript, the panel above
    the section); the Inputs bar stays for narrow pages. Files keeps the panel and has no
    such link."""
    analysis, _qc, _run = in_use(client)
    for path in ("indices", "quality"):
        html = page(client, analysis, path)
        provenance = html.split('class="context-bar__provenance"')[1].split("</p>")[0]
        # Then "Add stations", as the workspace has one station (#234), and "Copy to
        # workspace…" (#241), back to this page.
        copy = (
            f"{analysis.url('copy')}?next={analysis.url('qc' if path == 'quality' else 'results')}"
        )
        assert provenance.endswith(
            '<a class="context-bar__edit" href="#inputs-title" data-sheet-open="sheet-inputs"'
            ' aria-haspopup="dialog">Edit inputs</a><a class="context-bar__add"'
            f' href="/w/{analysis.workspace_id}/add/">Add stations</a>'
            f'<a class="context-bar__add" href="{copy}">Copy to workspace…</a>\n'
        ), path
        assert 'id="inputs-title"' in html and "data-inputs-bar" in html
        assert "station-page--inputs-bar" in html, path
    assert "context-bar__edit" not in page(client, analysis, "downloads")


def test_a_station_page_uses_the_whole_window(client):
    """#263: a station's pages have no max width (#227 gave them 92rem); other pages keep
    the 72rem content width."""
    analysis, _qc, _run = in_use(client)
    for path in ("quality", "indices", "downloads"):
        html = page(client, analysis, path)
        main = html.split('<main id="main"')[1].split(">", 2)[1]
        assert "max-w-" not in main and "w-full" in main, path
    assert "max-w-content" in client.get("/").content.decode()


def test_the_page_actions_are_in_a_menu_on_phones(client):
    """#203: Results' actions (the sector comparison and Download all) are in the header,
    and again in its ⋯ menu, a <details> disclosure shown instead on phones (CSS)."""
    analysis, _qc, _run = in_use(client)
    html = page(client, analysis)
    menu = re.search(r'<details class="page-menu" data-page-menu>.*?</details>', html, re.S)
    assert menu and "Page actions" in menu.group(0)
    assert "Compare with sector data" in menu.group(0)
    assert "All files and the report" in menu.group(0)  # Download all without a zip
    header = html.split('class="context-bar__actions"')[1].split("</details>")[0]
    assert header.count("Compare with sector data") == 2  # the buttons, then the menu
    assert "data-page-menu" not in page(client, analysis, "quality")  # no actions there


def test_the_index_settings_wait_for_use_this_data(client):
    """Before "Use this data" only the results use the index settings: no Edit, no sheet
    and no page for them (#198, #199). The thresholds sheet is there from the start."""
    analysis = ready_analysis(client)
    base = f"/w/{analysis.workspace_id}/{analysis.slug}"
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
    base = f"/w/{analysis.workspace_id}/{analysis.slug}"
    allowed = {f"{base}/quality/continue", f"{base}/delete", f"{base}/indices",
               f"{base}/indices#catalogue", ""}  # fmt: skip
    for path in ("quality", "indices", "downloads", "indices/txx", "sector"):
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
    base = f"/w/{analysis.workspace_id}/{analysis.slug}"
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
    assert response["Location"] == f"{base}/indices"
    assert client.get(f"{base}/inputs/nothing").status_code == 404
    assert Client().get(f"{base}/inputs/station").status_code == 404


# ---- the tabs ------------------------------------------------------------------------------


def test_tabs_follow_the_workspace_from_the_first_visit(client):
    load = made.station_to_set_up(client, sample=True).url("setup")
    analysis = Station.objects.get()
    html = client.get(load).content.decode()
    # The New station page (#201): no tabs and no Inputs panel before the station is set up.
    assert "tabs__list" not in html and "data-inputs-panel" not in html
    assert 'name="base_start"' in html
    assert client.get(f"{analysis.url()}inputs/station")["Location"] == load
    client.post(load, DETAILS)
    html = page(client, analysis, "quality")
    assert states(html) == {"quality": "checking", "results": "locked", "files": "locked"}
    assert "data-inputs-panel" in html and 'data-run="qc"' in html
    assert "<span>Checking…</span>" in html  # the word shows while the checks run (#222)
    run_next()
    html = page(client, analysis, "quality")
    # The first page after the checks shows their verdict in the tab (#222).
    assert states(html)["quality"] == "usable" and states(html)["files"] == "done"
    assert (
        '<span class="max-sm:sr-only">Usable</span><span class="max-sm:hidden" aria-hidden="true">'
        "· 5</span>" in html
    )


def test_failed_checks_need_attention(client):
    analysis = ready_analysis(client)
    Job.objects.filter(pk=analysis.qc_job.pk).update(status=Status.FAILED, error="Broken.")
    html = page(client, analysis, "quality")
    assert states(html)["quality"] == "attention" and "<span>Needs attention</span>" in html


def test_quality_tab_shows_the_verdict_kept_with_the_checks(client):
    """#222: the tab's state is the verdict, kept with the checks when Quality shows them;
    the Results and Files tabs keep their run states."""
    analysis = ready_analysis(client)
    qc = run_next()
    for level, wrong in [("ready", 0), ("usable", 5), ("fix", 1204)]:
        Job.objects.filter(pk=qc.pk).update(result={**qc.result, "verdict": level,
                                                    "verdict_wrong": wrong})  # fmt: skip
        analysis.refresh_from_db()
        tabs = {s.key: s for s in workspace.sections(analysis, "quality")}
        assert tabs["quality"].state == level and tabs["quality"].verdict
        assert tabs["quality"].count == {0: "", 5: "· 5", 1204: "· 1,204"}[wrong]
        assert tabs["files"].state == "done" and not tabs["files"].verdict


def test_quality_tab_works_out_a_verdict_not_kept(client):
    """Checks not yet shown, or with a verdict kept before #222 (its level alone): the tab
    works the verdict out from the checks once, and keeps it."""
    analysis = ready_analysis(client)
    qc = run_next()
    for result in [qc.result, {**qc.result, "verdict": "fix"}]:
        Job.objects.filter(pk=qc.pk).update(result=result)
        analysis.refresh_from_db()
        assert workspace.section_states(analysis)["quality"] == "usable"
        qc.refresh_from_db()
        assert (qc.result["verdict"], qc.result["verdict_wrong"]) == ("usable", 5)


# ---- addresses -------------------------------------------------------------------------------


def test_old_step_addresses_lead_to_their_tabs(client):
    analysis = ready_analysis(client)
    base = f"/w/{analysis.workspace_id}/{analysis.slug}"
    # Before "Use this data": the workspace's address opens Quality, Results go there too.
    assert client.get(f"{base}/")["Location"] == f"{base}/quality"
    assert client.get(f"{base}/indices")["Location"] == f"{base}/quality"
    run_next()
    finish(analysis.indices_job)
    client.post(f"{base}/quality/continue")
    assert client.get(f"{base}/")["Location"] == f"{base}/indices"
    # Each step's address is its tab's (Quality, Results, Files), kept as it was; Data's
    # leads to "Your data" on Quality (#198).
    for path, tab in [("quality", "quality"), ("indices", "results"), ("downloads", "files")]:
        assert re.search(rf'data-tab="{tab}"[^>]*aria-current="page"', page(client, analysis, path))
    assert client.get(f"{base}/load")["Location"] == f"{base}/quality#your-data"
    html = page(client, analysis, "quality")
    assert 'id="your-data"' in html and 'class="coverage-strip"' in html  # #235
    assert 'data-tab="data"' not in html
    # The old Calculate step opens the Index settings sheet over Results (#178, #199).
    response = client.get(f"{base}/recalculate?index=txx")
    assert response["Location"] == f"{base}/indices?settings=open&back=txx"
    assert "data-sheet-autoopen" in page(client, analysis, "indices?settings=open")
    # The old anchors #adjust and #thresholds are kept for js/sheet.js to open the sheets.
    assert 'id="adjust"' in page(client, analysis, "indices")
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
    base = f"/w/{analysis.workspace_id}/{analysis.slug}"
    session_before = dict(first.session.items())
    assert states(page(second, analysis))["results"] == "done"
    edit(first, analysis, "base-period", {"base_start": "1981", "base_end": "2010"})
    assert dict(first.session.items()) == session_before  # nothing about it in the session
    html = page(second, analysis)
    assert "You changed the base period to 1981–2010" in html and states(html)["results"] == "stale"
    # The second tab's out-of-date form changes it back: both see the old results again.
    second.post(f"{base}/setup", DETAILS)
    for tab in (first, second):
        assert states(page(tab, analysis))["results"] == "done"
    analysis.refresh_from_db()
    assert analysis.indices_job == run


# ---- retention -------------------------------------------------------------------------------


def test_retention_keeps_the_jobs_a_station_shows(client, settings):
    """An out-of-date run stays while the page shows it, beside its replacement in
    progress, however old (#231); once the replacement has finished it is purged on its own
    schedule."""
    settings.WORKSPACE_EXPIRY = True
    analysis, _qc, run = in_use(client)
    new_base = {**DETAILS, "base_start": "1981", "base_end": "2010"}
    client.post(f"{analysis.url()}setup", new_base)
    analysis.refresh_from_db()
    new = analysis.indices_job
    long_ago = timezone.now() - dt.timedelta(days=settings.JOB_RETENTION_DAYS + 1)
    Job.objects.filter(pk=run.pk).update(finished_at=long_ago)
    purge_expired()
    assert Job.objects.filter(pk=run.pk).exists() and run.folder.exists()
    html = page(client, analysis)
    assert states(html)["results"] == "stale"  # the old results, beside the new run
    Job.objects.filter(pk=new.pk).update(status=Status.SUCCEEDED, finished_at=timezone.now())
    purge_expired()
    assert not Job.objects.filter(pk=run.pk).exists() and not run.folder.exists()
    assert Job.objects.filter(pk=new.pk).exists()


def test_retention_deletes_the_workspace_once_idle(client, settings):
    """The workspace, with its station, goes once it has not changed for the retention
    period, unless one of its jobs is still queued or running."""
    settings.WORKSPACE_EXPIRY = True
    analysis, _qc, _run = in_use(client)
    client.post(f"{analysis.url()}setup", {**DETAILS, "base_start": "1981"})
    analysis.refresh_from_db()
    long_ago = timezone.now() - dt.timedelta(days=settings.JOB_RETENTION_DAYS + 1)
    Workspace.objects.filter(pk=analysis.workspace_id).update(updated_at=long_ago)
    purge_expired()
    assert Station.objects.filter(pk=analysis.pk).exists()
    analysis.indices_job.request_cancel()
    analysis.qc_job.request_cancel()
    purge_expired()
    assert not Station.objects.filter(pk=analysis.pk).exists()
    assert not Workspace.objects.filter(pk=analysis.workspace_id).exists()
    assert not analysis.folder.exists()


def test_without_expiry_nothing_a_workspace_shows_is_deleted(client, settings):
    """Locally (expiry off, the default) a workspace stays until deleted, and so do the
    jobs it shows, however old (#231)."""
    settings.WORKSPACE_EXPIRY = False
    analysis, qc, run = in_use(client)
    long_ago = timezone.now() - dt.timedelta(days=365)
    Workspace.objects.filter(pk=analysis.workspace_id).update(updated_at=long_ago)
    Job.objects.filter(pk__in=[qc.pk, run.pk]).update(finished_at=long_ago)
    stray = Job.objects.create(kind="station", owner="x", status=Status.SUCCEEDED,
                               finished_at=long_ago)  # fmt: skip
    purge_expired()
    assert Station.objects.filter(pk=analysis.pk).exists() and analysis.folder.exists()
    assert Job.objects.filter(pk__in=[qc.pk, run.pk]).count() == 2
    assert not Job.objects.filter(pk=stray.pk).exists()  # shown by nothing: purged as before
    html = page(client, analysis)
    assert states(html)["results"] == "done"


# ---- the migration ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_migration_drops_analyses_and_batches_and_keeps_their_jobs(settings):
    from migration_workspaces import check

    check(settings.MEDIA_ROOT)
