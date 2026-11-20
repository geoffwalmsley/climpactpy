"""Single-station results (#78, #178): the speculative run queued with the default
settings when the station details are confirmed, "Adjust and recalculate" (every field of
R's step 3, validated by the core), the calculation as a job with its stages, the results
dashboard (one card per index table, grouped, filtered), each index's page, the tables not
written, keeping the user on the same index after recalculating, and batch stations.

The results are R's own reference output for the Sydney sample at latitude 0
(``reference/output/lat0``), so "every table appears" and "values match the CSV files"
are checked against the files R writes."""

import html as html_lib
import json
import re
import shutil
from pathlib import Path
from urllib.parse import quote

import pytest
from django.test import Client

from climpact_web.core import numbers
from climpact_web.jobs.models import Job, Status
from climpact_web.jobs.views import OWNER_KEY
from climpact_web.stations import results as results_model
from climpact_web.stations import themes
from climpact_web.stations.forms_indices import IndexParamsForm
from climpact_web.stations.models import Station, Step

REPO = Path(__file__).resolve().parents[3]
LAT0 = REPO / "reference" / "output" / "lat0"
STATION = "sydney_observatory_hill_1936-2015"

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.RUNS_DIR = tmp_path / "media" / "runs"
    return settings


def ready_analysis(client) -> Station:
    """The Sydney sample through step 1: the checks and a speculative run of the indices
    with the default settings are queued (#178)."""
    load = client.post("/station/sample")["Location"]
    data = {"station_name": STATION, "latitude": "0", "longitude": "0",
            "base_start": "1971", "base_end": "2000"}  # fmt: skip
    assert client.post(load, data).status_code == 302
    _, _, space, slug, *_ = load.split("/")  # /w/<id>/<station>/setup
    return Station.objects.get(workspace=space, slug=slug)


def committed_analysis(client) -> Station:
    """As :func:`ready_analysis`, after "Use this data" (without waiting for the checks):
    the results show the speculative run."""
    analysis = ready_analysis(client)
    analysis.step = Step.INDICES
    analysis.save()
    return analysis


def finish(job: Job, outputs: Path = LAT0, skipped=(), rename=None) -> Job:
    """Give ``job`` the files of a finished run: R's ``lat0`` output by default."""
    target = job.output_dir / STATION
    shutil.copytree(outputs / STATION, target)
    for old, new in (rename or {}).items():
        for path in target.glob(f"indices/*_{old}_*.csv"):
            path.rename(path.with_name(path.name.replace(f"_{old}_", f"_{new}_")))
    job.status = Status.SUCCEEDED
    job.result = {"station": STATION, "files": [], "skipped": list(skipped), "zip": None}
    job.save()
    return job


def finished_analysis(client, skipped=()) -> tuple[Station, Job]:
    """A station whose results are a finished run of R's output, made with the plots and
    the zip off: its workspace's settings (#254)."""
    from climpact_web.stations import workspace

    analysis = committed_analysis(client)
    analysis.indices_job.request_cancel()  # replaced by a finished run of R's output
    space = analysis.workspace
    space.index_settings = {**workspace.default_settings(), "plots": False, "zip": False}
    space.save()
    params = {
        "station_file": "station.txt",
        "params": space.index_settings["params"],
        "plots": False,
        "zip": False,
    }
    job = Job.objects.create(
        kind="station",
        owner=analysis.owner,
        params=params,
        inputs=workspace.job_inputs(analysis, "station", params),
    )
    finish(job, skipped=skipped)
    analysis.indices_job = job
    analysis.save()
    return analysis, job


def defaults() -> dict:
    return {
        "plot_title": "",
        "wsdi_days": "1",
        "csdi_days": "1",
        "rx_days": "3",
        "txtn_days": "2",
        "hdd_base": "18",
        "cdd_base": "18",
        "gdd_base": "10",
        "rnnmm": "30",
        "spei_months": "24",
        "custom_enabled": "on",
        "custom_variable": "TN",
        "custom_operator": ">",
        "custom_threshold": "0",
        "plots": "on",
        "zip": "on",
    }


def index_files() -> list[str]:
    folder = LAT0 / STATION / "indices"
    return sorted(p.stem.removeprefix(f"{STATION}_") for p in folder.glob("*.csv"))


def read_table(name: str):
    from climpact.io.climpact_csv import read_climpact_csv

    return read_climpact_csv(LAT0 / STATION / "indices" / f"{STATION}_{name}.csv").data


# ---- step 3: the Index settings sheet (#199) --------------------------------------------


def apply_settings(client, analysis, data, next_page="indices"):
    """Apply the Inputs panel's Index settings sheet (#199) from a station page."""
    return client.post(
        f"{analysis.url()}inputs/settings",
        {**data, "next": f"{analysis.url()}{next_page}"},
    )


def settings_sheet(html: str) -> str:
    """The Index settings sheet (a <dialog>) of a station page."""
    return re.search(r'<dialog class="sheet" id="sheet-settings".*?</dialog>', html, re.S).group(0)


def without_sheets(html: str) -> str:
    """The page without the Inputs panel's sheets: what is on the page itself."""
    return re.sub(r"<dialog.*?</dialog>", "", html, flags=re.S)


def test_the_form_has_every_r_parameter_with_its_default(client):
    """The Index settings sheet (#199; "Adjust and recalculate" from #178) has every
    setting of R's step 3, with its default, while the speculative run goes on."""
    analysis = committed_analysis(client)
    response = client.get(f"{analysis.url()}indices")
    assert response.status_code == 200
    page = response.content.decode()
    assert "Calculating indices" in page
    html = settings_sheet(page)
    assert f'action="{analysis.url()}inputs/settings"' in html
    expected = {"wsdi_days": "1", "csdi_days": "1", "rx_days": "3", "txtn_days": "2",
                "hdd_base": "18.0", "cdd_base": "18.0", "gdd_base": "10.0", "rnnmm": "30.0",
                "spei_months": "24", "custom_threshold": "0.0"}  # fmt: skip
    for name, value in expected.items():
        assert re.search(rf'name="{name}" value="{value}"', html), name
    assert '<option value="TN" selected>' in html and '<option value="&gt;" selected>' in html
    assert 'name="custom_enabled"' in html and "checked" in html
    assert 'name="plot_title"' in html and f'placeholder="{STATION}  ·  0°N, 0°E"' in html
    # The plots, zip and report go with the settings.
    for name in ("plots", "zip", "report"):
        assert f'name="{name}"' in html, name
    # How the parameterised indices are named is in the groups' help (#177), opening in
    # place in the sheet, no longer under each field.
    assert "Written as" not in html
    for name in ("wsdi3", "rx3day", "hddheat18", "r30mm", "24month_spi"):
        assert name in html, name
    assert html.count('data-help-section="calculate.') == 7 and "data-drawer-open" not in html
    # Explanations: every parameter's help topic, and the EHF definition.
    assert "Nairn and Fawcett (2013)" in html
    topics = set(re.findall(r'data-help-topic="([^"]+)"', html))
    fields = ("plot_title", "wsdi_days", "csdi_days", "rx_days", "txtn_days", "hdd_base",
              "cdd_base", "gdd_base", "rnnmm", "spei_months", "custom")  # fmt: skip
    assert {f"param.{f}" for f in fields} <= topics
    assert "index.hwEHF" in topics
    # One button, Apply, at the foot, after the fields, described by what it updates.
    foot = html.split('class="sheet__foot"')[1]
    assert html.index('name="report"') < html.index('class="sheet__foot"')
    assert "<span>Apply</span>" in foot and 'aria-describedby="sheet-settings-form-impact"' in foot
    assert "Updates Indices and Files. Quality stays as it is." in html
    assert 'class="card' not in html


def test_step_3_needs_the_station_details(client):
    load = client.post("/station/sample")["Location"]
    analysis = Station.objects.get()
    assert client.get(f"{analysis.url()}recalculate")["Location"] == load
    assert client.get(f"{analysis.url()}inputs/settings")["Location"] == load


@pytest.mark.parametrize(
    "field, value",
    [
        ("wsdi_days", "0"), ("wsdi_days", "11"), ("csdi_days", "0"), ("csdi_days", "11"),
        ("rx_days", "0"), ("txtn_days", "0"), ("rnnmm", "-1"), ("spei_months", "0"),
        ("rx_days", "2.5"), ("hdd_base", "warm"), ("custom_threshold", ""),
    ],
)  # fmt: skip
def test_invalid_values_are_refused(field, value):
    form = IndexParamsForm({**defaults(), field: value})
    assert not form.is_valid()
    assert form.errors[field]


@pytest.mark.parametrize(
    "changes",
    [
        {"wsdi_days": "10", "csdi_days": "10", "rx_days": "1", "txtn_days": "1", "rnnmm": "0",
         "spei_months": "1", "hdd_base": "-5", "gdd_base": "0.5"},
        {"custom_enabled": "", "custom_threshold": ""},  # no custom index
        {"custom_variable": "PR", "custom_operator": ">=", "custom_threshold": "25.5"},
    ],
)  # fmt: skip
def test_valid_values_are_what_the_core_accepts(changes):
    from climpact.batch import validate_params

    form = IndexParamsForm({k: v for k, v in {**defaults(), **changes}.items() if v != ""})
    assert form.is_valid(), form.errors
    validate_params(form.index_params())  # does not raise
    params = form.job_params()
    from climpact_web.jobs.runners import index_params

    assert index_params(params) == form.index_params()


def test_form_and_core_agree_on_every_boundary():
    """For each value either side of R's limits, the form accepts exactly what
    validate_params accepts."""
    from dataclasses import replace

    from climpact.batch import validate_params
    from climpact.config import IndexParams

    for field in ("wsdi_days", "csdi_days", "rx_days", "txtn_days", "spei_months", "rnnmm"):
        for value in (-1, 0, 1, 2, 10, 11):
            form = IndexParamsForm({**defaults(), field: str(value)})
            try:
                validate_params(replace(IndexParams(), **{field: value}))
                core_ok = True
            except ValueError:
                core_ok = False
            assert form.is_valid() == core_ok, (field, value)


def test_custom_index_units_follow_the_variable(client):
    analysis = ready_analysis(client)
    data = {**defaults(), "custom_variable": "PR", "custom_operator": ">=",
            "custom_threshold": "25.5", "group": "custom"}  # fmt: skip
    html = client.post(f"{analysis.url()}settings/validate", data).content.decode()
    assert '<span class="input-group__unit">mm</span>' in html
    assert 'id="param-custom"' in html and "hx-post=" in html


def test_htmx_checks_one_group_and_warns(client):
    analysis = ready_analysis(client)
    url = f"{analysis.url()}settings/validate"
    html = client.post(url, {**defaults(), "rx_days": "7", "group": "rx_days"}).content.decode()
    assert 'value="7"' in html and 'id="param-rx_days"' in html
    assert "spei" not in html  # only the group asked for
    html = client.post(
        url, {**defaults(), "wsdi_days": "12", "group": "wsdi_days"}
    ).content.decode()
    assert "Enter a whole number from 1 to 10." in html
    html = client.post(
        url, {**defaults(), "spei_months": "12", "group": "spei_months"}
    ).content.decode()
    assert "always calculated" in html
    html = client.post(url, {**defaults(), "rnnmm": "10", "group": "rnnmm"}).content.decode()
    assert "same index as R10mm" in html
    assert client.post(url, {**defaults(), "group": "nope"}).status_code == 400


def test_the_settings_are_a_line_on_the_results_and_a_sheet(client):
    """#178, #199: the settings are a line (the defaults, or what was changed), at the
    foot of the filter rail since #236, whose link opens the Index settings sheet; no form
    on the page but the filters."""
    analysis, _job = finished_analysis(client)
    html = client.get(f"{analysis.url()}indices").content.decode()
    header = re.search(r"<p [^>]*data-settings-line>.*?</p>", html, re.S).group(0)
    assert "Climpact&#x27;s default settings." in header
    sheet = f"{analysis.url()}inputs/settings?next={quote(analysis.url(), safe='')}indices"
    assert f'<a href="{sheet}" data-sheet-open="sheet-settings"' in header
    assert 'id="adjust"' in header  # the old form's anchor (js/sheet.js opens the sheet)
    page = without_sheets(html)
    # The only form is the rail's filters, sent with GET; the line is at the rail's foot (#236).
    assert re.findall(r"<form [^>]*method=\"(\w+)\"", page) == ["get"]
    assert page.index("data-results-filter") < page.index("data-settings-line")
    assert 'name="hdd_base"' not in page and "Adjust and recalculate" not in page
    # This run had the plots and the zip switched off: the panel counts them.
    panel = html.split('data-input="settings"')[1].split("</div>")[0]
    assert '<dd class="inputs-panel__value">2 changed</dd>' in panel


def test_the_settings_page_shows_errors(client):
    """A sheet's form with errors returns on the sheet's own page (#198)."""
    analysis, _job = finished_analysis(client)
    response = apply_settings(client, analysis, {**defaults(), "hdd_base": "warm"})
    html = response.content.decode()
    assert response.status_code == 200 and "data-error-summary" in html
    assert 'id="input-form"' in html and '<h1 class="sheet__title">Index settings</h1>' in html
    assert 'href="#id_hdd_base"' in html  # the summary links to the field
    assert f'name="next" value="{analysis.url()}indices"' in html
    assert Job.objects.filter(kind="station").count() == 2  # nothing queued


def test_the_header_names_the_settings_that_were_changed(client):
    analysis, _job = finished_analysis(client)
    apply_settings(client, analysis, {**defaults(), "rx_days": "7", "custom_enabled": ""})
    finish(Job.objects.latest("created_at"))
    html = client.get(f"{analysis.url()}indices").content.decode()
    header = re.search(r"<p [^>]*data-settings-line>.*?</p>", html, re.S).group(0)
    assert "Settings changed: Days for Rxdday 7 days, Custom threshold index none." in header
    assert 'name="rx_days" value="7"' in settings_sheet(html)
    # The panel counts them, with the report left unticked: "3 changed".
    panel = html.split('data-input="settings"')[1].split("</div>")[0]
    assert '<dd class="inputs-panel__value">3 changed</dd>' in panel


def test_recalculate_queues_a_station_job_with_the_parameters(client):
    analysis = committed_analysis(client)
    speculative = analysis.indices_job
    # Quality's thresholds (#77), the workspace's (#254)
    analysis.workspace.qc_params = {"jump": "15", "flatline_days": "4"}
    analysis.workspace.save()
    data = {**defaults(), "rx_days": "7", "plot_title": "  Sydney   test ", "custom_variable": "TX",
            "custom_operator": ">=", "custom_threshold": "40", "zip": ""}  # fmt: skip
    response = apply_settings(client, analysis, data)
    job = Job.objects.exclude(pk=speculative.pk).get(kind="station")
    assert response["Location"] == f"{analysis.url()}indices"
    # The run it replaces had not finished: it is cancelled, and nothing is kept on screen.
    speculative.refresh_from_db()
    assert speculative.status == Status.CANCELLED and "replaces" not in job.params
    assert not job.is_speculative
    assert (job.kind, job.status, job.title) == ("station", Status.QUEUED, STATION)
    assert job.params["params"]["rx_days"] == 7
    assert job.params["params"]["custom"] == {"variable": "TX", "operator": ">=", "threshold": 40.0}
    assert job.params["plot_title"] == "Sydney test"
    assert job.params["plots"] is True and job.params["zip"] is False
    assert job.params["metadata"]["latitude"] == 0
    from climpact_web.jobs.runners import qc_params

    thresholds = qc_params(job.params["qc"])  # the full run's QC files use them
    assert (thresholds.jump, thresholds.flatline_days, thresholds.iqr_temp) == (15.0, 4, 3.0)
    assert (job.input_dir / "station.txt").read_bytes() == analysis.station_file.read_bytes()
    analysis.refresh_from_db()
    assert analysis.indices_job == job and analysis.step == Step.RESULTS
    # The sheet opens with the settings of the last calculation, and the panel counts
    # them: rx_days, the custom index, the plot title, and the zip and report off.
    html = client.get(f"{analysis.url()}indices").content.decode()
    sheet = settings_sheet(html)
    assert 'name="rx_days" value="7"' in sheet and 'value="Sydney test"' in sheet
    panel = html.split('data-input="settings"')[1].split("</div>")[0]
    assert '<dd class="inputs-panel__value">5 changed</dd>' in panel


def test_the_runner_passes_the_plot_title(monkeypatch, tmp_path):
    import climpact.batch
    from climpact_web.jobs.registry import JobContext
    from climpact_web.jobs.runners import run_station_job

    seen = {}

    def fake_run_station(*args, **kwargs):
        seen.update(kwargs)
        return {}, []

    monkeypatch.setattr(climpact.batch, "run_station", fake_run_station)
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "station.txt").write_text("x")
    params = {"station_file": "station.txt", "params": {}, "plot_title": "My title", "plots": True}
    ctx = JobContext("j", params, tmp_path / "input", tmp_path)
    run_station_job(ctx)
    assert seen["plot_title"] == "My title" and seen["plots"] is True


# ---- step 4: progress ---------------------------------------------------------------------


def test_progress_while_running_then_the_results(client):
    """The defaults path (#178): the run queued when the details were confirmed is the one
    the results follow, with no settings page on the way."""
    analysis = committed_analysis(client)
    job = Job.objects.get(kind="station")
    assert analysis.indices_job == job and job.params["params"]["rx_days"] == 3
    html = client.get(f"{analysis.url()}indices").content.decode()
    assert "Calculating indices" in html and 'class="stages"' in html
    assert f'hx-get="{analysis.url()}indices/progress"' in html
    job.status, job.stage, job.step, job.total = Status.RUNNING, "indices:climpact:spi", 40, 100
    job.save()
    html = client.get(f"{analysis.url()}indices/progress").content.decode()
    # The stage in words, without its ids (#226).
    assert "Calculating the indices" in html and "(spi)" not in html and 'value="40"' in html
    assert html.count("stages__item--done") == 3  # read, quality checks, homogeneity
    assert (
        "stages__item--current" in html and "Draw the plots" in html and "Make the zip file" in html
    )
    assert f'name="next" value="{analysis.url()}' in html  # cancel comes back here
    finish(job)
    response = client.get(f"{analysis.url()}indices/progress")
    assert response.status_code == 204 and response["HX-Redirect"] == f"{analysis.url()}indices"
    assert "data-results-table" in client.get(f"{analysis.url()}indices").content.decode()


def test_a_failed_calculation_shows_why_and_offers_the_settings(client):
    analysis = committed_analysis(client)
    job = Job.objects.get(kind="station")
    job.status, job.error, job.stage = (
        Status.FAILED,
        "The base period has no data.",
        "indices:climpact:fd",
    )
    job.save()
    html = client.get(f"{analysis.url()}indices").content.decode()
    assert "The calculation failed." in html and "The base period has no data." in html
    assert "stages__item--failed" in html
    sheet = f"{analysis.url()}inputs/settings?next={analysis.url()}indices"
    assert f'href="{sheet}" data-sheet-open="sheet-settings"' in html
    response = client.post(f"/jobs/{job.pk}/retry", {"next": f"{analysis.url()}indices"})
    assert response["Location"] == f"{analysis.url()}indices"
    assert client.post(f"/jobs/{job.pk}/cancel", {"next": "https://example.org/"})["Location"] == (
        f"/jobs/{job.pk}/"
    )


def test_no_results_before_use_this_data(client):
    """#178: the speculative run is not shown until the user chooses to use the data, on
    Results or on any page behind it."""
    analysis = ready_analysis(client)
    finish(analysis.indices_job)
    for path in ("indices", "indices/txx", "downloads"):
        response = client.get(f"{analysis.url()}{path}")
        assert response.status_code == 302, path
    assert client.get(f"{analysis.url()}indices")["Location"].endswith("/quality")
    sector = client.get(f"{analysis.url()}sector").content.decode()
    assert "Calculate the indices first" in sector


def test_results_without_a_run_offer_to_calculate(client):
    """When no run was queued (refused in hosted mode, say), Results has one button, which
    opens the Index settings sheet; its Apply queues the run (#199)."""
    analysis = committed_analysis(client)
    analysis.indices_job.request_cancel()
    analysis.indices_job = None
    analysis.save()
    html = client.get(f"{analysis.url()}indices").content.decode()
    assert "The indices are not calculated yet." in html
    assert "<span>Check the settings and calculate</span>" in html
    assert 'data-sheet-open="sheet-settings"' in without_sheets(html)
    assert "<form" not in without_sheets(html).split('class="workspace__main')[1]
    apply_settings(client, analysis, defaults())
    analysis.refresh_from_db()
    assert analysis.indices_job.status == Status.QUEUED and not analysis.indices_job.is_speculative


def test_the_old_settings_addresses_open_the_sheet(client):
    """#178, #199: links, bookmarks and emails to the Calculate step or to "Adjust and
    recalculate" open the Index settings sheet over Results; without JavaScript the page
    goes on to the sheet's own page. Applying returns to the index the user came from."""
    analysis, _job = finished_analysis(client)
    base = f"/w/{analysis.workspace_id}/{analysis.slug}"
    assert client.get(f"{base}/recalculate")["Location"] == f"{base}/indices?settings=open"
    response = client.get(f"{base}/recalculate?index=rx3day")
    assert response["Location"] == f"{base}/indices?settings=open&back=rx3day"
    html = client.get(response["Location"]).content.decode()
    assert "data-sheet-autoopen" in settings_sheet(html)
    assert html.count("data-sheet-autoopen") == 1
    back = f"{base}/indices?index=rx3day"
    assert f'name="next" value="{back}"' in settings_sheet(html)
    page = f"{base}/inputs/settings?next={quote(analysis.url(), safe='')}indices%3Findex%3Drx3day"
    assert f'<noscript><meta http-equiv="refresh" content="0; url={page}">' in html.replace(
        "&amp;", "&"
    )
    assert "data-sheet-autoopen" not in client.get(f"{base}/indices").content.decode()
    # The old form's #adjust anchor is on the settings line, for js/sheet.js.
    assert 'id="adjust"' in client.get(f"{base}/indices").content.decode()
    # A settings form sent from a page from before #199 goes to the sheet's page.
    response = client.post(f"{base}/recalculate", defaults())
    assert (
        response["Location"]
        == f"{base}/inputs/settings?next={quote(analysis.url(), safe='')}indices"
    )
    assert Job.objects.filter(kind="station").count() == 2  # the run shown, one cancelled


# ---- step 4: the dashboard ----------------------------------------------------------------


def test_every_table_of_the_lat0_run_is_on_the_dashboard(client):
    analysis, job = finished_analysis(client)
    html = client.get(f"{analysis.url()}indices").content.decode()
    # Each index's detail links its page (#236).
    linked = set(re.findall(rf'href="{analysis.url()}indices/([^"#?]+)"', html))
    files = index_files()
    assert len(files) == 114
    for name in files:
        key = results_model.card_key(name)
        assert key in linked, name
    # Each table opens on its index's page, which links its CSV file.
    for name in files:
        key = results_model.card_key(name)
        page = client.get(f"{analysis.url()}indices/{key}?series={name}")
        assert page.status_code == 200, name
        assert (
            f"/jobs/{job.pk}/files/{STATION}/indices/{STATION}_{name}.csv" in page.content.decode()
        )
    # One table of every index (#200), with no family accordions.
    assert len(re.findall(ANY_ROW, html)) == len(linked) == 80
    assert 'class="disclosure" id="group-' not in html
    assert "Showing 80 of 80 indices." in html


def test_card_values_match_the_csv_files(client):
    """#236: a row's slope per decade, 95% interval and significance are the trend file's
    (annual row), and the mean in its detail (#263) is the mean of the index table."""
    from climpact.io.climpact_csv import read_climpact_csv

    analysis, _job = finished_analysis(client)
    html = client.get(f"{analysis.url()}indices").content.decode()
    trend = read_climpact_csv(LAT0 / STATION / "trend" / f"{STATION}_trend.csv").data
    for key in ("txx", "su", "prcptot"):
        table = read_table(f"{key}_ANN")
        cells = _cells(_row(html, key))
        row = trend[(trend["Index"] == key) & (trend["Frequency"] == "annual")].iloc[0]
        places = 1 if key == "prcptot" else 2
        slope, lower, upper = (row[c] * 10 for c in ("Slope", "Lower bound", "Upper bound"))
        unit = {"txx": "°C", "su": "days", "prcptot": "mm"}[key]
        assert cells[2] == f"{_signed(slope, places)} {unit}", key
        assert cells[3] == f"{_plain(lower, places)} to {_plain(upper, places)}", key
        significant = row["Lower bound"] > 0 or row["Upper bound"] < 0
        assert cells[4] == ("yes" if significant else "no"), key
        mean = _plain(table[table.columns[1]].mean(), places)
        assert f"<dd>{mean}\u00a0{unit}</dd>" in _detail(html, key), key


def _signed(value: float, places: int) -> str:
    text = _plain(value, places)
    return "+" + text if round(value, places) > 0 else text


def _plain(value: float, places: int) -> str:
    from climpact_web.core import numbers

    return numbers.fixed(value, places)


def _detail(html: str, key: str) -> str:
    return re.search(
        rf'<div class="index-detail[^"]*" id="detail-{re.escape(key)}".*?index-detail__back',
        html,
        re.S,
    ).group(0)


def _row(html: str, key: str) -> str:
    return re.search(rf'<tr [^>]*id="index-{re.escape(key)}".*?</tr>', html, re.S).group(0)


def _cells(row: str) -> list[str]:
    """A row's cells as text, a cell's screen-reader text in place of what it hides."""
    row = re.sub(r'<span[^>]*aria-hidden="true"[^>]*>[^<]*</span>', "", row)
    cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.S)
    texts = (re.sub(r"<[^>]+>", "", c).replace("&nbsp;", " ") for c in cells)
    return [" ".join(re.split(r"[ \t\n]+", t.strip())) for t in texts]


def test_index_page_values_match_the_csv_and_trend_files(client):
    """#237: the index page's statistics and table are the files': Sen's slope and its
    interval per decade as the trend file's annual row, the record and its year, the years
    used, the base-period mean, and every year with its value, rank and the date of its
    extreme (the ``day_of_`` table)."""
    from climpact.io.climpact_csv import read_climpact_csv

    analysis, job = finished_analysis(client)
    html = client.get(f"{analysis.url()}indices/txx").content.decode()
    txx = read_table("txx_ANN")
    trend = read_climpact_csv(LAT0 / STATION / "trend" / f"{STATION}_trend.csv").data
    row = trend[(trend["Index"] == "txx") & (trend.iloc[:, 1] == "annual")].iloc[0]
    lower, slope, upper = (float(row.iloc[k]) * 10 for k in (4, 5, 6))
    assert f'<dd class="index-stats__lead">{numbers.per_decade(slope, "°C")}</dd>' in html
    assert f'<dd class="index-stats__lead">{numbers.interval(lower, upper, "°C")}</dd>' in html
    high = txx.loc[txx["val"].idxmax()]
    present = txx["val"].notna().sum()
    assert f"<dd>{high['val']:g}\u00a0°C, {int(high['time'])}</dd>" in html
    assert f"<dt>Years used</dt><dd>{present} of {len(txx)}</dd>" in html
    base = txx[(txx["time"] >= 1971) & (txx["time"] <= 2000)]["val"].mean()
    assert f"<dt>Base-period mean</dt><dd>{numbers.number(base)}\u00a0°C</dd>" in html
    # The table: every year, most recent first, as the CSV.
    rows = re.findall(
        r'<tr id="value-\d+"(?: class="index-values__missing")?>'
        r'\s*<th scope="row" class="code">(\d+)</th>'
        r'\s*<td class="num">([^<]+)</td>\s*<td class="num">([^<]+)</td>'
        r'\s*<td class="num">([^<]+)</td>',
        html,
    )
    assert [int(r[0]) for r in rows] == list(reversed(txx["time"].astype(int)))
    assert rows[0][1] == numbers.number(txx.iloc[-1]["val"])
    record = next(r for r in rows if r[0] == str(int(high["time"])))
    assert record[3] == "1"
    # The date of each year's maximum, from the run's day-of-occurrence table.
    from datetime import date, timedelta

    days = results_model.build(results_model.run_source(job)).plots["day_of_txx_ANN"]
    first = date(int(txx.iloc[-1]["time"]), 1, 1) + timedelta(days=int(days.values[-1]) - 1)
    assert '<th scope="col">Date of maximum</th>' in html
    assert re.search(rf'<td class="code">{first.isoformat()}</td>', html)
    tnn = client.get(f"{analysis.url()}indices/tnn").content.decode()
    assert '<th scope="col">Date of minimum</th>' in tnn
    assert "Change it and calculate again" not in html  # txx takes no setting
    # Annual and monthly: the period toggle; the days of occurrence are the date column.
    assert re.search(r'aria-current="true">Annual</a>', html)
    monthly = client.get(f"{analysis.url()}indices/txx?series=txx_MON").content.decode()
    assert re.search(r'aria-current="true">Monthly</a>', monthly) and "Monthly values" in monthly
    assert '<th scope="col">Month</th>' in monthly
    for old in ("day_of_txx_ANN", "nope"):
        page = client.get(f"{analysis.url()}indices/txx?series={old}").content.decode()
        assert "Annual values" in page


def test_the_anomaly_view_and_the_years_left_out(client):
    """#237: the chart shows the values or their anomalies from the base-period mean:
    both are drawn, the toggle's links switch them (?view=anomaly without JavaScript), and
    the table gives each year's anomaly. A year left out is an open point on the chart,
    with why in the statistics and the table. SPI, already standardised, has no anomaly
    view; the standardised anomalies' chart of before is gone."""
    analysis, _job = finished_analysis(client)
    url = f"{analysis.url()}indices/txx"
    html = client.get(url).content.decode()
    views = re.findall(r'<svg class="index-plot"[^>]*data-index-view="(\w+)"( hidden)?>', html)
    assert views == [("values", ""), ("anomaly", " hidden")]
    assert (
        f'href="{url}?view=anomaly" data-index-view-link="anomaly">Anomaly from 1971–2000</a>'
        in html
    )
    anomaly = client.get(url, {"view": "anomaly"}).content.decode()
    views = re.findall(r'<svg class="index-plot"[^>]*data-index-view="(\w+)"( hidden)?>', anomaly)
    assert views == [("values", " hidden"), ("anomaly", "")]
    assert re.search(r'data-index-view-link="anomaly" aria-current="true">', anomaly)
    # The period links keep the view.
    assert f'href="{url}?series=txx_MON&amp;view=anomaly" data-index-period>Monthly' in anomaly
    # Each year's anomaly: its value less the base period's mean.
    txx = read_table("txx_ANN")
    base = txx[(txx["time"] >= 1971) & (txx["time"] <= 2000)]["val"].mean()
    last = txx.iloc[-1]
    row = re.search(rf'<th scope="row" class="code">{int(last["time"])}</th>.*?</tr>', html, re.S)
    assert numbers.anomaly(last["val"] - base) in row.group(0)
    # The year left out: an open point on each chart, and why.
    gone = txx[txx["val"].isna()]["time"].astype(int).tolist()
    assert gone
    assert html.count('class="index-plot__gap"') == 2 * len(gone)
    assert "Year left out: incomplete" in html
    year = gone[0]
    row = re.search(
        rf'<tr id="value-{year}" class="index-values__missing">'
        rf'\s*<th scope="row" class="code">{year}</th>.*?</tr>',
        html,
        re.S,
    )
    assert "Left out: " in row.group(0) and "days missing" in row.group(0)
    assert re.search(
        rf"{year} left out: \d+ days? missing, so the year fails the completeness rule.", html
    )
    # SPI: bars, no anomaly view; the old anomalies address is gone.
    spi = client.get(f"{analysis.url()}indices/3month_spi").content.decode()
    assert "data-index-view-link" not in spi and 'class="index-plot__pos"' in spi
    assert "Anomaly</th>" not in spi
    assert client.get(f"{analysis.url()}indices/tmm_ANN/anomalies.json").status_code == 404


def _page_data(html: str) -> dict:
    found = re.search(r'<script id="index-chart-data" type="application/json">(.*?)</script>', html)
    return json.loads(found.group(1))


def test_the_index_chart_hydrates_from_the_pages_data(client):
    """#283: the index page carries its chart's data (charts.js draws it with every layer
    the server's chart has; the server's chart stays as it is, for no JavaScript and
    print): the values and anomalies, the running means, the base period, the years left
    out with their level and why, the dates of the extremes and Sen's slope. ?at=<year>
    selects that year's row and has the chart read it out; an unknown one is ignored.
    The Indices' detail chart reads out each year and opens this page at it."""
    analysis, _job = finished_analysis(client)
    url = f"{analysis.url()}indices/txx"
    html = client.get(url).content.decode()
    assert 'data-chart-data="index-chart-data"' in html and 'data-chart-view="values"' in html
    assert "uPlot.iife.min.js" in html and "js/charts.js" in html
    assert 'id="index-chart-plot" data-chart-plot hidden' in html  # until charts.js draws
    data = _page_data(html)
    txx = read_table("txx_ANN")
    assert data["x"][0] == int(txx["time"].iloc[0]) and len(data["y"]) == len(txx)
    assert data["layers"]["base"] == {"from": 1970.5, "to": 2000.5, "label": "base period"}
    gone = txx[txx["val"].isna()]["time"].astype(int).tolist()
    i = data["x"].index(gone[0])
    assert data["y"][i] is None and "days missing" in dict(data["layers"]["notes"])[i]
    base = txx[(txx["time"] >= 1971) & (txx["time"] <= 2000)]["val"].mean()
    values, anomaly = data["views"]["values"], data["views"]["anomaly"]
    assert dict(values["gaps"])[i] == round(base, 1) and dict(anomaly["gaps"])[i] == 0
    assert anomaly["y"][-1] == pytest.approx(txx["val"].iloc[-1] - base, abs=0.005)
    assert anomaly["offset"] == pytest.approx(base) and anomaly["axis"] == "Anomaly °C"
    assert values["axis"] == "TXx °C" and values["smooth"][5] is not None
    assert data["trend"]["slope"] and data["dates"][-1].startswith(str(data["x"][-1]))
    # ?at=: the row selected; the chart reads it out.
    html = client.get(url, {"at": gone[0]}).content.decode()
    assert f'data-chart-at="{gone[0]}"' in html
    assert f'<tr id="value-{gone[0]}" class="index-values__missing" aria-current="true">' in html
    assert (
        "aria-current" not in client.get(url, {"at": "1800"}).content.decode().split("<tbody>")[1]
    )
    # SPI: bars, no anomaly view, no running mean.
    spi = _page_data(client.get(f"{analysis.url()}indices/3month_spi").content.decode())
    assert (
        spi["bars"]
        and list(spi["views"]) == ["values"]
        and spi["views"]["values"]["smooth"] is None
    )
    # The Indices' detail: each year read out; a year opens this page at it.
    pane = client.get(f"{analysis.url()}indices", {"show": "txx"}).content.decode()
    found = re.search(r"id=\"detail-txx\".*?<svg [^>]*data-readout='([^']+)'", pane, re.S)
    readout = json.loads(html_lib.unescape(found.group(1)))
    assert readout["href"] == f"{url}?at=" and readout["label"] == "TXx"
    assert readout["when"]["first"] == data["x"][0] and "v" not in readout
    # Its values come from the series' chart data when it is first used.
    series = client.get(readout["src"]).json()
    assert series["name"] == "txx_ANN" and series["y"] == pytest.approx(data["y"], abs=0.05)
    assert 'id="detail-txx-keys" hidden>Keyboard: the left and right arrow keys' in pane


def test_daily_ehf_and_tables_without_plots(client):
    analysis, _job = finished_analysis(client)
    html = client.get(f"{analysis.url()}indices/EHFdaily").content.decode()
    table = read_table("EHFdaily")
    top = table.loc[table["Excess Heat Factor"].idxmax()]
    assert "The ten highest days" in html and str(top["date"]) in html
    assert "index-plot" not in html
    html = client.get(f"{analysis.url()}indices/tx95t").content.decode()
    assert "Values by day of the year" in html and "Rank</th>" not in html


def test_tables_not_written_are_listed_with_the_reason(client):
    analysis, _job = finished_analysis(
        client, skipped=["indices/tn10p_ANN", "indices/tn10p_MON", "thres/x"]
    )
    space = analysis.workspace
    space.base_start, space.base_end = 2020, 2030  # outside the data
    space.save()
    html = client.get(f"{analysis.url()}indices").content.decode()
    assert "1 index could not be calculated" in html
    assert "<strong>TN10p</strong> (tn10p_ANN, tn10p_MON)" in html
    assert "percentiles could not be calculated" in html


def test_a_run_that_calculated_no_index_says_why(client):
    """#268: a station whose TX, TN and PR are all missing finishes with every index
    skipped. Its Indices say why and that there is nothing to show, with the way on
    (replace the file); its Files and an index's address open without an error."""
    analysis, job = finished_analysis(client)
    folder = job.output_dir / STATION / "indices"
    skipped = [f"indices/{p.stem.removeprefix(f'{STATION}_')}" for p in folder.glob("*.csv")]
    shutil.rmtree(folder)
    folder.mkdir()
    job.result = {**job.result, "skipped": skipped}
    job.save()
    response = client.get(f"{analysis.url()}indices")
    assert response.status_code == 200
    html = response.content.decode()
    assert re.search(r"\d+ indices could not be calculated", html)
    assert "No index to show" in html
    assert analysis.url("edit_input", "file") in html  # the way on: replace the file
    assert "indices-table" not in html and "index-detail" not in html
    assert client.get(f"{analysis.url()}downloads").status_code == 200
    assert client.get(f"{analysis.url()}indices/txx_ANN").status_code in (302, 404)
    assert client.get(f"{analysis.url()}indices", {"show": "txx_ANN"}).status_code == 200


def test_the_reason_names_a_variable_with_no_data():
    summary = {"variables": [{"key": "prcp", "present": 0}, {"key": "tmax", "present": 9}]}
    [entry] = results_model.skipped_tables(["indices/r30mm_ANN"], summary, None)
    assert entry["name"] == "R30mm" and "no precipitation values" in entry["reason"]
    [entry] = results_model.skipped_tables(["indices/txx_MON"], summary, None)
    assert "missing-data rules" in entry["reason"]


def test_filters_without_javascript(client):
    """#200, #236: the rail is a form sent to the page: a theme (with its count), "Significant
    only" and a search; the table holds every row, the ones filtered out hidden."""
    analysis, _job = finished_analysis(client)
    url = f"{analysis.url()}indices"
    html = client.get(url, {"theme": "drought"}).content.decode()
    shown = re.findall(ROW, html)
    assert set(shown) == {"drought"} and len(shown) == 9  # SPI, SPEI and CDD
    assert "Showing 9 of 80 indices." in html
    # The table holds every row; the hidden ones are hidden, so a clear shows them at once.
    assert len(re.findall(ANY_ROW, html)) == 80
    # "Also measured": every index outside the four headline themes, the daily tables too.
    shown = re.findall(ROW, client.get(url, {"theme": "other"}).content.decode())
    assert set(shown) == {"other"} and len(shown) == 16
    html = client.get(url, {"q": "frost"}).content.decode()
    assert "Showing 1 of 80 indices." in html
    html = client.get(url, {"significant": "1"}).content.decode()
    count = int(re.search(r"Showing (\d+) of 80", html).group(1))
    assert count == 22 and len(re.findall(ROW, html)) == count
    # Each theme with its count, in the rail.
    rail = re.search(r'<form class="indices__rail.*?</form>', html, re.S).group(0)
    assert re.findall(r'value="(\w*)"[^>]*>.*?filter-pill__count">(\d+)<', rail) == [
        ("", "80"), ("heat", "30"), ("cold", "12"), ("rain", "13"), ("drought", "9"),
        ("other", "16"),
    ]  # fmt: skip
    assert "Significant: the 95% interval of Sen's slope excludes zero." in rail
    # The filters combine, and the form is sent to the page.
    html = client.get(url, {"theme": "heat", "significant": "1"}).content.decode()
    assert set(re.findall(ROW, html)) == {"heat"} and "Showing 9 of 80 indices." in html
    assert f'action="{url}"' in html
    # Unknown values are ignored.
    assert "Showing 80 of 80" in client.get(url, {"theme": "nope", "sort": "x"}).content.decode()


# A row of the table shown (not hidden), capturing its theme; and any row.
ROW = r'<tr class="hue-\w+(?: is-selected)?" id="index-[^"]+" data-chip="(\w+)"[^>]*?(?<! hidden)>'
ANY_ROW = r'<tr class="hue-\w+(?: is-selected)?" id="index-'


def _text(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", "", html).replace("&gt;", ">").split())


def test_one_line_answers_above_the_table(client):
    """#236: the theme tiles and the answer band are gone. One line answers above the
    table: the count of significant trends in bold and the mean temperature's trend; the
    rail, the table and the detail pane follow in that order."""
    analysis, _job = finished_analysis(client)
    url = f"{analysis.url()}indices"
    html = client.get(url).content.decode()
    assert (
        '<p class="indices__answer"><strong>22 of 80</strong> indices with a significant trend'
        ' <span class="indices__mean">· TMm +0.19\u00a0°C/decade</span></p>'
    ) in html
    assert "theme-headline" not in html and "answer-band" not in html
    assert html.index("data-results-filter") < html.index("data-results-table")
    assert html.index("data-results-table") < html.index('id="index-detail"')


def test_the_table_shows_the_statistics(client):
    """#236, #263: Code, Index, Slope per decade with its unit, 95% interval, Significant
    and the series; every index with a trend has its interval and significance; a
    percentage's slope is in percentage points; an index without a trend says why to
    screen readers."""
    analysis, job = finished_analysis(client)
    url = f"{analysis.url()}indices"
    html = client.get(url).content.decode()
    head = html.split("<thead>")[1].split("</thead>")[0]
    assert _cells(head) == [
        "Code", "Index", "Slope per decade", "95% interval", "Significant", "1936–2015",
    ]  # fmt: skip
    assert _cells(_row(html, "su")) == [
        "SU", "Summer days", "+5.15 days", "3.79 to 6.54", "yes", "",
    ]  # fmt: skip
    pp = '<abbr title="percentage points">pp</abbr>'
    assert f'+1.31&nbsp;<span class="indices-table__unit">{pp}</span>' in _row(html, "tn90p")
    assert _cells(_row(html, "tx95t"))[2:5] == ["No trend line", "", ""]
    assert _cells(_row(html, "EHFdaily"))[2:5] == ["Daily values", "", ""]
    run = results_model.build(results_model.run_source(job))
    for card in run.cards:
        cells = _cells(_row(html, card.key))
        assert len(cells) == 6, card.key
        if card.trend and card.trend.get("valid"):
            assert " to " in cells[3] and cells[4] in ("yes", "no"), card.key
            assert (cells[4] == "yes") == card.significant, card.key
    assert html.count('<span class="indices-table__yes">') == 22


def test_the_detail_pane_shows_the_selected_index(client):
    """#236, #263: a row's code links to ?show=<key> (the filters and order kept), whose
    detail the server shows beside the table: its code and theme, name and definition, a
    chart with axes (the base period as a band, Sen's slope dashed), the slope, its
    interval, the mean over the record, whether it is significant in words, the years used
    and the method, and its links. The first row shown, the largest trend, is selected by
    default."""
    analysis, job = finished_analysis(client)
    url = f"{analysis.url()}indices"
    html = client.get(url).content.decode()
    first = _order(html)[0]
    assert first != "fd" and _shown(html) == [first] and _current(html) == [first]
    html = client.get(url, {"show": "su", "theme": "heat"}).content.decode()
    assert _shown(html) == ["su"] and _current(html) == ["su"]
    assert 'class="hue-heat is-selected" id="index-su"' in html
    assert 'href="?theme=heat&amp;show=tr#detail-tr" data-index-item="tr"' in html
    assert '<input type="hidden" name="show" value="su">' in html
    detail = re.search(
        r'<div class="index-detail[^>]*id="detail-su".*?Back to the list', html, re.S
    )
    detail = detail.group(0)
    text = " ".join(re.sub(r"<[^>]+>", " ", detail).replace("&gt;", ">").split(" "))
    text = " ".join(text.replace("&#x27;", "'").replace("\n", " ").split(" ")).replace("  ", " ")
    text = re.sub(" +", " ", text)
    assert "SU · Heat Summer days Annual number of days when TX > 25\u00a0°C" in text
    assert "Slope +5.15\u00a0days/decade 95% interval 3.79 to 6.54" in text
    assert re.search(
        r"Mean, 1936–2015 [0-9.]+\u00a0days Significant Yes: the interval excludes zero", text
    )
    assert re.search(r"Years used \d+ of 80 Method Sen's slope \(zyp\)", text)
    # The chart: its axes, three values and three years, the base period, the trend.
    assert re.findall(r'class="index-chart__tick"[^>]*>([^<]+)<', detail)[3:] == [
        "1936", "1975", "2015",
    ]  # fmt: skip
    assert 'class="index-chart__band"' in detail and ">base period<" in detail
    assert 'class="index-chart__trend"' in detail and 'role="img"' in detail
    assert "Annual SU (days), with Sen&#x27;s slope dashed." in detail
    assert "Annual SU from 1936 to 2015." in detail.replace("&#x27;", "'")
    # The links: the index page, its CSV and PNG, and its monthly values where it has some.
    assert f'href="{url}/su"' in detail
    assert f'href="/jobs/{job.pk}/files/{STATION}/indices/{STATION}_su_ANN.csv" download' in detail
    assert ".png" in detail or "PNG" not in detail
    tnn = client.get(url, {"show": "tnn"}).content.decode()
    assert f'href="{url}/tnn?series=tnn_MON"' in tnn and _shown(tnn) == ["tnn"]
    # Unknown: the first row shown.
    html = client.get(url, {"show": "nope", "theme": "rain"}).content.decode()
    first = re.search(r'id="index-([^"]+)" data-chip="rain"', html).group(1)
    assert _shown(html) == [first] and first != "fd"


def _shown(html: str) -> list[str]:
    return re.findall(r'data-index-detail="([^"]+)">', html)


def _current(html: str) -> list[str]:
    return re.findall(r'data-index-item="([^"]+)" aria-current="true"', html)


def flatten(folder: Path) -> None:
    """Make every index table of a run trendless: each table's values alternate between its
    first two values, so every Sen's slope interval includes zero."""
    for path in (folder / "indices").glob("*.csv"):
        if path.stem.endswith("daily"):  # no trend
            continue
        lines = path.read_text().splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith("time,")) + 1
        rows = [line.split(",") for line in lines[start:]]
        present = [r[1] for r in rows if len(r) > 1 and r[1].strip() not in ("NA", "-99.9", "")]
        if len(present) < 2:
            continue
        for i, row in enumerate(rows):
            if len(row) > 1:
                row[1] = present[i % 2]
        path.write_text("\n".join(lines[:start] + [",".join(r) for r in rows]) + "\n")


def test_a_station_without_significant_trends_says_so(client):
    """#175, #236: with no significant trend, the line says so and no row is significant;
    no change is a finding, not an empty page."""
    analysis, job = finished_analysis(client)
    flatten(job.output_dir / STATION)
    html = client.get(f"{analysis.url()}indices").content.decode()
    assert '<p class="indices__answer"><strong>0 of 80</strong> indices with a significant' in html
    assert "indices-table__yes" not in html
    html = client.get(f"{analysis.url()}indices", {"significant": "1"}).content.decode()
    assert "Showing 0 of 80 indices." in html and "No index matches." in html


def test_every_index_has_one_place_in_the_themes():
    """Decision C (#175): every short name of the core's index file is in exactly one theme
    or "Also measured" line; nothing else is in the mapping."""
    shorts = set(results_model.catalogue.by_short())
    placed = [s for theme in themes.THEMES for s in theme.shorts]
    assert len(placed) == len(set(placed)), "an index is in two themes"
    assert set(placed) == shorts
    assert [t.key for t in themes.THEMES if t.headline] == ["heat", "cold", "rain", "drought"]


def test_each_theme_has_its_hue():
    """#196: Heat, Cold, Rain and Drought have hues of their own (--color-heat ...); the
    "Also measured" themes and the cards in no theme share the neutral."""
    assert [themes.hue_of(t.key) for t in themes.THEMES] == [
        "heat", "cold", "rain", "drought", "other", "other", "other",
    ]  # fmt: skip
    assert themes.hue_of("") == "other"


def test_theme_hues_colour_the_rail_rows_detail_and_index_chart(client):
    """#196: each theme's filter, row and detail carries its hue class (the dot, the
    sparkline, the detail's chart line), and an index page's chart frame its index's, so
    the chart line takes the theme's colour."""
    analysis, _job = finished_analysis(client)
    url = f"{analysis.url()}indices"
    html = client.get(url).content.decode()
    for key in ("heat", "cold", "rain", "drought", "other"):
        assert f'<label class="filter-pill hue-{key}"><input type="radio" name="theme"' in html
    assert '<tr class="hue-heat" id="index-txx" data-chip="heat"' in html
    assert '<tr class="hue-other" id="index-EHFdaily" data-chip="other"' in html
    assert '<div class="index-detail hue-heat" id="detail-txx"' in html
    page = client.get(f"{url}/txx").content.decode()
    assert '<div class="index-page__body hue-heat">' in page
    assert '<span class="badge badge--hue hue-heat">Heat</span>' in page
    page = client.get(f"{url}/prcptot").content.decode()
    assert '<div class="index-page__body hue-rain">' in page


def test_every_card_of_the_lat0_run_has_a_theme(client):
    """Every calculated index is in one theme or line, or deliberately in the catalogue
    alone (the daily EHF and ECF tables, which have no trend)."""
    analysis, job = finished_analysis(client)
    source = results_model.run_source(job)
    run = results_model.build(source)
    by_theme: dict[str, list[str]] = {}
    for card in run.cards:
        by_theme.setdefault(card.theme, []).append(card.key)
    assert sorted(by_theme[""]) == sorted(themes.CATALOGUE_ONLY)
    counts = {k: len(v) for k, v in by_theme.items()}
    assert counts == {"heat": 30, "cold": 12, "rain": 13, "drought": 9, "averages": 5,
                      "seasons": 8, "custom": 1, "": 2}  # fmt: skip
    assert {"TX90-HWN", "TN90-HWF", "EHF-HWLI", "wsdi1", "tx2tn2"} <= set(by_theme["heat"])
    assert {"r30mm", "rx3day"} <= set(by_theme["rain"]) and "cdd" in by_theme["drought"]
    # Output names that depend on the settings follow their index.
    info = results_model.catalogue.index_for_output
    for key, theme in (("rx7day", "rain"), ("r25mm", "rain"), ("36month_spei", "drought"),
                       ("wsdi5", "heat"), ("csdi3", "cold"), ("txb3tnb3", "cold"),
                       ("hddheat15", "seasons"), ("gddgrow5", "seasons"),
                       ("TXge40", "custom")):  # fmt: skip
        assert themes.theme_of(key, info(key)) == theme, key


def _named(code: str, name: str, title: bool = False) -> str:
    """An index named codes first (components/index_name.html, #218)."""
    modifier = " index-name--title" if title else ""
    return (
        f'<span class="index-name{modifier}"><code class="index-code">{code}</code> '
        f'<span class="index-name__name">{name}</span></span>'
    )


def test_indices_are_listed_codes_first(client):
    """#218: the code leads, in mono, and the short name follows it: the catalogue's first
    two columns, the index page's title and its previous and next links. R's long name is
    the index page's definition line, and search finds the code, the short name and R's
    names."""
    analysis, _job = finished_analysis(client)
    url = f"{analysis.url()}indices"
    html = client.get(url).content.decode()
    assert _cells(_row(html, "fd"))[:2] == ["FD", "Frost days"]
    assert _cells(_row(html, "TX90-HWN"))[:2] == ["TX90-HWN", "Number of heatwaves"]
    assert _cells(_row(html, "3month_spi"))[:2] == ["SPI3", "SPI, 3 months"]
    assert "SPI, 3\u00a0months" not in _row(html, "3month_spi")
    assert _cells(_row(html, "rx3day"))[:2] == ["Rx3day", "Wettest 3\u00a0days"]
    # The number rules (#226), and the sample's own index, TNgt0.
    assert _cells(_row(html, "tnltm2"))[1] == "Days TN &lt; \u22122\u00a0°C"
    assert _cells(_row(html, "TNgt0"))[1] == "Days TN &gt; 0\u00a0°C"
    assert '<th scope="row" class="code"><span class="hue-dot" aria-hidden="true"></span>' in html
    # The columns: Code, then Index.
    headers = re.findall(r'<th scope="col"[^>]*data-sort-key="(\w+)"', html)
    assert headers[:2] == ["code", "name"]
    # Search finds the code, the short name and R's long name and definition.
    for q in ("tnltm20", "hottest day", "max 1-day pr", "warmest daily tx"):
        found = client.get(url, {"q": q}).content.decode()
        assert "Showing 1 of 80 indices." in found, q
    page = client.get(f"{url}/txx").content.decode()
    assert f"<h1>{_named('TXx', 'Hottest day', title=True)}</h1>" in page
    assert "<title>TXx Hottest day: " in page
    assert "Name in Climpact for R: Max TX." in page
    nav = re.search(r'<p class="context-bar__step">.*?</p>', page, re.S).group(0)
    assert re.search(
        r'rel="prev">.*?<span class="sr-only">Previous:</span> '
        + re.escape(_named("TXge35", "Days TX ≥ 35\u00a0°C")),
        nav,
    )
    assert '<span class="sr-only">Next:</span> ' + _named("TNn", "Coldest night") in nav
    # No R line when R's long name is the short name.
    assert "Name in Climpact for R: Frost days" not in client.get(f"{url}/fd").content.decode()
    # TMge10 counts TM days, whatever R's long name says (#217).
    assert _cells(_row(html, "tmge10"))[1] == "Days TM ≥ 10\u00a0°C"
    assert "TX of at least 10" not in html
    page = client.get(f"{url}/tmge10").content.decode()
    assert f"<h1>{_named('TMge10', 'Days TM ≥ 10\u00a0°C', title=True)}</h1>" in page
    assert "Name in Climpact for R: TM of at least 10\u00a0°C." in page


def test_short_names():
    """#218: every index has a short name; parameters, heatwave aspects, the daily EHF
    tables and the user's own index get theirs from the output name."""
    from climpact_web.help.indices import SHORT_NAMES

    by_short = results_model.catalogue.by_short()
    assert set(SHORT_NAMES) == set(by_short)
    name = results_model.short_name
    assert name("txx", by_short["txx"]) == "Hottest day"
    assert name("EHF-HWLI", by_short["hwEHF"]) == "Total heatwave intensity"
    assert name("TN90-HWA", by_short["hw"]) == "Hottest heatwave's peak"
    assert name("24month_spei", by_short["spei"]) == "SPEI, 24 months"
    assert name("rx7day", by_short["rxdday"]) == "Wettest 7\u00a0days"
    assert name("r25.5mm", by_short["rnnmm"]) == "Days ≥ 25.5\u00a0mm"
    assert name("wsdi4", by_short["wsdid"]) == "Warm spell duration, 4+ days"
    assert name("txb3tnb3", by_short["txbdtnbd"]) == "Cold days and nights, 3 in a row"
    assert name("tx3tn3", by_short["txdtnd"]) == "Hot days and nights, 3 in a row"
    assert name("hddheat18", by_short["hddheatn"]) == "Heating degree days"
    assert name("EHFdaily", by_short["hwEHF"]) == "Daily excess heat factor"
    assert name("TNgt0", None) == "Days TN > 0\u00a0°C"
    assert name("PRge-1", None) == "Days PR ≥ \u22121\u00a0mm"
    assert name("TXle35.5", None) == "Days TX ≤ 35.5\u00a0°C"
    assert name("tnltm2", by_short["tnltm2"]) == "Days TN < \u22122\u00a0°C"
    # The guide's names, before a parameter is chosen.
    assert by_short["rxdday"].short_name() == "Wettest d days"
    assert by_short["rnnmm"].short_name() == "Days ≥ nn mm"
    assert by_short["spi"].short_name() == "SPI, n months"
    # Codes as the board spells them.
    assert results_model.display_name("3month_spi", by_short["spi"]) == "SPI3"
    assert results_model.display_name("EHFdaily", by_short["hwEHF"]) == "EHFdaily"


def _order(html: str) -> list[str]:
    """The keys of the catalogue's rows, in the table's order."""
    return re.findall(r'<tr class="hue-\w+(?: is-selected)?" id="index-([^"]+)"', html)


def _header(html: str, key: str) -> str:
    return re.search(rf'<th scope="col"[^>]*data-sort-key="{key}".*?</th>', html, re.S).group(0)


def test_the_catalogue_sorts_by_column_without_javascript(client):
    """#200: each column header is a link to the page sorted by it, with the filters kept;
    the sorted column has aria-sort, and the line above the table says how it is sorted.
    The rows are the same indices in every order. #263: the page opens sorted by the size
    of the trend (no column's), largest first, the rows without a trend last."""
    from climpact_web.stations.views_indices import sort_cards

    analysis, job = finished_analysis(client)
    url = f"{analysis.url()}indices"
    html = client.get(url).content.decode()
    default = _order(html)
    run = results_model.build(results_model.run_source(job))
    cards = {c.key: c for c in run.cards}
    sizes = [
        abs(cards[k].trend["slope"])
        for k in default
        if cards[k].trend and cards[k].trend.get("valid")
    ]
    assert sizes == sorted(sizes, reverse=True) and default[0] == "gddgrow10"
    assert all(not (cards[k].trend and cards[k].trend.get("valid")) for k in default[len(sizes) :])
    assert "aria-sort" not in html.split("<tbody>")[0]
    assert "indices. Sorted by the size of the trend, largest first.</p>" in html
    assert 'name="sort"' not in html  # the default is kept by leaving it out
    assert 'data-default-sort="size" data-sort="size" data-dir="descending"' in html
    # A first click: names A to Z, the largest trends and the significant first.
    show = default[0]
    assert f'href="{url}?sort=name&amp;dir=ascending&amp;show={show}"' in _header(html, "name")
    assert f'href="{url}?sort=trend&amp;dir=descending&amp;show={show}"' in _header(html, "trend")
    # The order is the function's, which js/results.js mirrors.
    from climpact_web.stations.views_indices import DEFAULT_SORT

    ordered = [c for section in run.sections() for c in section["cards"]]
    assert default == [c.key for c in sort_cards(ordered, DEFAULT_SORT, True)]
    titles = {c.key: c.title for c in run.cards}
    page = client.get(url, {"sort": "name", "dir": "ascending"}).content.decode()
    rows = _order(page)
    assert sorted(rows) == sorted(default)
    assert [titles[k].casefold() for k in rows] == sorted(titles[k].casefold() for k in rows)
    assert 'aria-sort="ascending" data-sort-key="name"' in page
    assert "Showing 80 of 80 indices. Sorted by Index, ascending." in page
    # Sorted, the header links the other way.
    # The detail shown by default is the first row in the order shown.
    first = _order(page)[0]
    assert f'href="{url}?sort=name&amp;dir=descending&amp;show={first}"' in _header(page, "name")
    assert _order(client.get(url, {"sort": "name", "dir": "descending"}).content.decode()) == (
        list(reversed(rows))
    )
    # By trend: largest first, the rows without a trend last.
    page = client.get(url, {"sort": "trend"}).content.decode()  # the column's direction
    assert 'aria-sort="descending" data-sort-key="trend"' in page
    slopes = [
        cards[k].trend["slope"]
        for k in _order(page)
        if cards[k].trend and cards[k].trend.get("valid")
    ]
    assert slopes == sorted(slopes, reverse=True)
    tail = _order(page)[len(slopes) :]
    assert tail and all(not (cards[k].trend and cards[k].trend.get("valid")) for k in tail)
    assert "EHFdaily" in tail
    # By significance: the significant first, then the trends that are not, then none.
    page = client.get(url, {"sort": "significance"}).content.decode()
    first = _order(page)[:22]
    assert all(cards[k].significant for k in first)
    # The filters are kept by the sort links, and the sort by the filter form.
    page = client.get(url, {"theme": "rain", "sort": "code", "dir": "ascending"}).content.decode()
    first = re.findall(r'id="index-([^"]+)" data-chip="rain"', page)[0]
    assert first == "cwd"  # CWD, the first rain index by code
    assert f'href="{url}?theme=rain&amp;sort=name&amp;dir=ascending&amp;show=cwd"' in page
    assert '<input type="hidden" name="sort" value="code">' in page
    assert '<input type="hidden" name="dir" value="ascending">' in page
    assert set(re.findall(ROW, page)) == {"rain"}
    # The same order as the function js/results.js mirrors.
    keys = [c.key for c in sort_cards(run.cards, "code", False)]
    codes = [cards[k].code.casefold() for k in keys]
    assert codes == sorted(codes)


def test_every_index_is_one_click_away(client):
    """#200, #236: every index is a link in the table, whatever the filters hide, to its
    detail, which links its page; an index page's "All indices" leads back to its row."""
    analysis, _job = finished_analysis(client)
    url = f"{analysis.url()}indices"
    html = client.get(url, {"theme": "drought", "q": "zzz"}).content.decode()
    assert "Showing 0 of 80 indices." in html
    assert "No index matches." in html and "data-results-empty hidden" not in html
    rows = re.findall(r'id="index-([^"]+)"[^>]*>\s*<th scope="row" class="code">'
                      r'<span class="hue-dot" aria-hidden="true"></span><a href="([^"]+)"',
                      html)  # fmt: skip
    assert len(rows) == 80
    assert all(
        href == f"?q=zzz&amp;theme=drought&amp;show={key}#detail-{key}" for key, href in rows
    )
    pages = set(re.findall(rf'<a href="{url}/([^"?#]+)">Open full page', html))
    assert pages == {key for key, _href in rows}
    page = client.get(f"{url}/rx1day").content.decode()
    assert f'href="{url}?show=rx1day#index-rx1day">Indices</a>' in page


def test_downloads_and_next_step(client, settings):
    settings.WORKSPACE_EXPIRY = True  # the deletion date is shown (hosted)
    analysis, job = finished_analysis(client)
    html = client.get(f"{analysis.url()}indices").content.decode()
    # The files are on the Files page (#176); here only each index's CSV and PNG, in its
    # detail (#236).
    linked = re.findall(rf'href="/jobs/{job.pk}/files/([^"]+)"', html)
    assert linked and all(f.endswith((".csv", ".png")) for f in linked)
    assert all("/indices/" in f or "/plots/" in f for f in linked)
    assert f'href="{analysis.url()}downloads"' in html
    # The header's two actions (#200): the sector comparison, and without a zip the link
    # to the downloads page as the primary (with a zip, test_downloads).
    actions = re.search(r'<div class="[^"]*results-actions">.*?</div>', html, re.S).group(0)
    assert actions.count('class="button"') == 1 and actions.count("<a ") == 2
    assert f'href="{analysis.url()}downloads"' in actions
    assert f'href="{analysis.url()}sector"' in actions
    # No sector card or other button lower on the page.
    assert 'id="sector-title"' not in html
    # Twice: in the header and again in its ⋯ menu for phones (#203).
    assert html.count(f'href="{analysis.url()}sector"') == 2
    assert client.get(f"{analysis.url()}sector").status_code == 200
    assert "Kept until" in html


def test_units_on_the_stat_row_and_percentage_point_trends(client):
    """#173: the index page's statistics (#237) carry the index's units, and a trend in a percentage
    index is in percentage points per decade, not percent: "pp", spelt out in its
    ``abbr`` (#226)."""
    analysis, _job = finished_analysis(client)
    html = client.get(f"{analysis.url()}indices").content.decode()
    pp = '<abbr title="percentage points">pp</abbr>'
    assert f'+0.65&nbsp;<span class="indices-table__unit">{pp}</span>' in html
    assert "% per decade" not in html and "Slope per decade" in html
    page = client.get(f"{analysis.url()}indices/tx90p").content.decode()
    for label in ("Base-period mean", "Record"):
        assert re.search(rf"<dt>{label}</dt><dd>[0-9.,]+%", page), label
    assert re.search(r'<dd class="index-stats__lead">\S+\u00a0pp/decade</dd>', page)
    days = client.get(f"{analysis.url()}indices/su").content.decode()
    assert re.search(r"<dt>Record</dt><dd>[0-9.,]+\u00a0days, \d{4}</dd>", days)


def test_units_written_the_same_way_everywhere(client):
    """#189: a percentage index (TX90p), a count (SU) and a unitless one (SPI) write
    their values with units one way in the table, its detail and the index page's
    statistics (#237): "12.5%", "20 days", the number alone, never "12.5 %" or a double
    space; #226: a no-break space before the units, "pp" for percentage points."""
    analysis, _job = finished_analysis(client)
    html = client.get(f"{analysis.url()}indices").content.decode()

    assert _cells(_row(html, "tx90p"))[2] == "+0.65 pp"
    assert '+5.15&nbsp;<span class="indices-table__unit">days</span>' in _row(html, "su")
    spi = _cells(_row(html, "3month_spi"))
    assert re.fullmatch(r"[+−]?[0-9.,]+", spi[2])
    # The detail's mean (#263): "12.5%", "20 days", the number alone.
    for key, value in (("tx90p", r"[0-9.,]+%"), ("su", r"[0-9.,]+\u00a0days"),
                       ("3month_spi", r"−?[0-9.,]+")):  # fmt: skip
        mean = re.search(rf'id="detail-{key}".*?<dt>Mean, [^<]+</dt><dd>([^<]+)</dd>', html, re.S)
        assert re.fullmatch(value, mean.group(1)), key
    # The detail: a unitless trend says "/decade" with nothing before it.
    slope = re.search(r'id="detail-3month_spi".*?<dt>Slope</dt><dd>([^<]+)</dd>', html, re.S)
    slope = slope.group(1)
    assert re.fullmatch(r"[+−]?[0-9.]+/decade", slope)
    for key, value, trend in (
        ("tx90p", r"[0-9.,]+%", r"[+−]?[0-9.,]+\u00a0pp/decade"),
        ("su", r"[0-9.,]+\u00a0days", r"[+−]?[0-9.,]+\u00a0days/decade"),
        ("3month_spi", r"−?[0-9.,]+", r"[+−]?[0-9.]+/decade"),
    ):
        page = client.get(f"{analysis.url()}indices/{key}").content.decode()
        assert re.search(rf"<dt>Record</dt><dd>{value}, \d{{4}}(-\d\d)?</dd>", page), key
        assert re.search(rf'<dd class="index-stats__lead">{trend}</dd>', page), key
        assert " %</dd>" not in page


def test_trend_and_stat_units():
    from climpact_web.charts.data import trend_units
    from climpact_web.stations.results import with_units

    assert trend_units("%") == "pp" and trend_units("°C") == "°C"
    assert with_units("12.5", "%") == "12.5%" and with_units("20", "days") == "20\u00a0days"
    assert with_units("0.4", "") == "0.4"


def test_sector_comparison_is_not_a_step(client):
    """#173: the sector page is part of Results: its tab is the current one (#179)."""
    analysis, _job = finished_analysis(client)
    html = client.get(f"{analysis.url()}sector").content.decode()
    assert re.search(r'data-tab="results" data-state="done" aria-current="page"', html)
    assert len(re.findall(r'data-tab="\w+"[^>]*aria-current', html)) == 1
    assert "steps__item" not in html


def test_recalculating_keeps_the_user_on_the_same_index(client):
    analysis, _job = finished_analysis(client)
    page = client.get(f"{analysis.url()}indices/rx3day").content.decode()
    link = f"{analysis.url()}inputs/settings?next={quote(analysis.url(), safe='')}indices%2Frx3day"
    assert f'href="{link}" data-sheet-open="sheet-settings"' in page
    assert "It depends on a setting:" in page
    response = apply_settings(client, analysis, {**defaults(), "rx_days": "7"}, "indices/rx3day")
    assert response["Location"] == f"{analysis.url()}indices/rx3day"
    # While it runs, the index page stays and says so (#237: no Inputs panel; the run's
    # progress is on the Indices).
    html = client.get(response["Location"]).content.decode()
    assert "Recalculating with your new inputs:" in html
    job = Job.objects.latest("created_at")
    finish(job, rename={"rx3day": "rx7day"})
    # The old index address leads to the same index under its new name.
    assert client.get(f"{analysis.url()}indices/rx3day")["Location"].endswith("/indices/rx7day")
    assert client.get(f"{analysis.url()}indices/rx7day").status_code == 200
    # From the old address with ?back=, the results open the index too once it is done.
    response = client.get(f"{analysis.url()}indices?index=rx3day")
    assert response["Location"] == f"{analysis.url()}indices/rx7day"


def test_other_sessions_get_404(client):
    analysis, job = finished_analysis(client)
    other = Client()
    session = other.session
    session[OWNER_KEY] = "someone-else"
    session.save()
    for path in (
        "recalculate",
        "indices",
        "indices/txx",
        "indices/progress",
        "indices/tmm_ANN/anomalies.json",
        "sector",
    ):
        assert other.get(f"{analysis.url()}{path}").status_code == 404, path
    assert other.post(f"{analysis.url()}recalculate", defaults()).status_code == 404
    assert other.post(f"{analysis.url()}inputs/settings", defaults()).status_code == 404
    assert client.get(f"{analysis.url()}indices/nope").status_code == 404


def test_signature_keeps_parameterised_indices_together():
    s = results_model.signature
    assert s("rx3day") == s("rx7day") and s("r30mm") == s("r25.5mm")
    assert s("24month_spi") == s("36month_spi") != s("3month_spi")
    assert s("TNgt0") == s("TXge40") == "custom"
    assert s("TX90-HWN") != s("TN90-HWN")


def test_sparklines_are_small_and_keep_gaps():
    spark = results_model.sparkline([1.0, 2.0, float("nan"), 3.0, 4.0])
    assert spark["line"].count("M") == 2  # a gap where the value is missing
    bars = results_model.sparkline([0.5, -1.0] * 600, bars=True)  # monthly SPI: columns
    assert bars["pos"].count("M") <= results_model.SPARK_WIDTH and bars["neg"]
    assert results_model.sparkline([float("nan")] * 3) == {}


def test_every_index_chart_has_labelled_axes(client):
    """#237: the index page's chart has its axes labelled: the y axis titled with the
    code and units ("TXx °C", "SU days", "Anomaly °C"), round values, and the first and
    last years under the x axis; the definition line is the cleaned definition (#115)."""
    analysis, _job = finished_analysis(client)
    base = f"{analysis.url()}indices"

    def axes(html, view="values"):
        svg = re.search(
            rf'<svg class="index-plot"[^>]*data-index-view="{view}".*?</svg>', html, re.S
        )
        svg = svg.group(0)
        title = re.search(r'class="index-plot__title"[^>]*>([^<]+)</text>', svg).group(1)
        ticks = re.findall(r'class="index-plot__tick"[^>]*>([^<]+)</text>', svg)
        return title, ticks

    html = client.get(f"{base}/txx").content.decode()
    title, ticks = axes(html)
    assert title == "TXx °C" and "1936" in ticks and "2015" in ticks
    assert len([t for t in ticks if re.fullmatch(r"[0-9]+", t) and len(t) <= 2]) >= 3
    assert axes(html, "anomaly")[0] == "Anomaly °C"
    assert "+5" in axes(html, "anomaly")[1]
    html = client.get(f"{base}/su").content.decode()
    assert axes(html)[0] == "SU days"
    assert "Annual number of days when TX &gt; 25\u00a0°C. Unit days." in html
    assert "degrees_C" not in html
    monthly = client.get(f"{base}/txx?series=txx_MON").content.decode()
    assert axes(monthly)[0] == "TXx °C" and "1936" in axes(monthly)[1]


def test_each_section_is_a_tab_named_in_the_title(client):
    """#179: each section page has the station's name as its h1, the tabs under it with
    its own current, and the section's name in the page title. The index and sector pages
    belong to Indices (Results before #236), with their own h1."""
    analysis, _job = finished_analysis(client)
    base = f"/w/{analysis.workspace_id}/{analysis.slug}"
    for path, tab, title in [
        ("/quality", "quality", "Quality"),
        ("/indices", "results", "Indices"),
        ("/downloads", "files", "Files"),
    ]:
        html = client.get(base + path).content.decode()
        assert f'<h1 class="context-bar__name">{STATION}</h1>' in html, path
        assert f"<title>{title}: {STATION}" in html, path
        current = re.findall(r'data-tab="(\w+)" data-state="\w+" aria-current="page"', html)
        assert current == [tab], path
        assert html.count("<h1") == 1 and "steps__item" not in html, path
    # An index's page (#237, the Index board) is a drill-down from the Indices: its own h1,
    # a breadcrumb back to the station and its Indices, and no tabs.
    html = client.get(base + "/indices/txx").content.decode()
    assert f"<h1>{_named('TXx', 'Hottest day', title=True)}</h1>" in html
    assert html.count("<h1") == 1 and "data-tab=" not in html
    crumbs = re.search(r'<ol class="context-bar__breadcrumb">.*?</ol>', html, re.S).group(0)
    assert f'<a href="{base}/">{STATION}</a>' in crumbs and ">Indices</a>" in crumbs


def test_every_section_of_the_station_pages_has_its_help(client):
    """#177: one ⓘ per section of Indices, an index and Files, in page order; no help
    link under a field. The Index settings sheet's groups have their help in place (#199):
    the drawer is behind the modal sheet."""
    analysis, _job = finished_analysis(client)
    base = f"/w/{analysis.workspace_id}/{analysis.slug}"
    expected = {
        "/indices": [
            "results.catalogue",
        ],
        "/indices/txx": ["result.index"],
        "/downloads": ["files.page"],
    }
    for path, ids in expected.items():
        html = client.get(base + path).content.decode()
        page = without_sheets(html)
        assert re.findall(r'href="/help/sections/([^/"?]+)/', page) == ids, path
        assert "help-topic--compact" not in page, path
        sheet = settings_sheet(html)
        assert re.findall(r'data-help-section="([^"]+)"', sheet) == [
            f"calculate.{key}"
            for key in ("plots", "spells", "degree", "prcp", "custom", "ehf", "files")
        ], path
    # The index page's help leads with the index itself.
    html = client.get(base + "/indices/txx").content.decode()
    assert 'href="/help/sections/result.index/?topics=index.txx"' in html
    assert 'aria-label="About this index: TXx"' in html


# ---- speculative runs: cancel and replace (#178) -------------------------------------------


def _station_upload(name="fixed.txt", changed=True):
    """The sample file, without its last day unless ``changed`` is false: a corrected file
    (the same bytes are the same file, which changes nothing, #179)."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    from climpact_web.stations.views import sample_bytes

    data = sample_bytes()
    if changed:
        data = data[: data.rstrip(b"\n").rfind(b"\n") + 1]
    return SimpleUploadedFile(name, data)


def test_a_corrected_file_replaces_the_speculative_run(client):
    analysis = ready_analysis(client)
    old = analysis.indices_job
    response = client.post(f"{analysis.url()}inputs/file", {"station_file": _station_upload()})
    assert response.status_code == 302
    analysis.refresh_from_db()
    old.refresh_from_db()
    assert old.status == Status.CANCELLED
    new = analysis.indices_job
    assert new != old and new.is_speculative and new.status == Status.QUEUED
    assert (new.input_dir / "station.txt").read_bytes() == analysis.station_file.read_bytes()


@pytest.mark.parametrize("address", ["setup", "inputs/file"])
def test_a_new_file_replaces_the_speculative_run_at_once(client, address):
    """Once the details are confirmed, a new file from the setup page (#201, a form left
    open) or the Inputs panel (#198) queues the checks and the run of the new file straight away."""
    analysis = ready_analysis(client)
    old = analysis.indices_job
    data = {"station_file": _station_upload(), "intent": "read"}
    client.post(f"{analysis.url()}{address}", data)
    analysis.refresh_from_db()
    old.refresh_from_db()
    assert old.status == Status.CANCELLED
    new = analysis.indices_job
    assert new != old and new.is_speculative and new.status == Status.QUEUED


def test_new_thresholds_replace_the_run_and_keep_the_settings(client):
    """The full run writes the QC files too, so new thresholds replace it; the settings of
    the last calculation are kept, not reset to the defaults. The data is in use, so the
    replacement is the user's own run, and the results stay, out of date, meanwhile
    (#179)."""
    from climpact_web.stations.forms import QC_DEFAULTS

    analysis, old = finished_analysis(client)
    apply_settings(client, analysis, {**defaults(), "rx_days": "7"})
    analysis.refresh_from_db()
    adjusted = analysis.indices_job
    finish(adjusted)
    thresholds = {**{k: str(v) for k, v in QC_DEFAULTS.items()}, "iqr_temp": "4"}
    client.post(f"{analysis.url()}inputs/thresholds", thresholds)
    analysis.refresh_from_db()
    new = analysis.indices_job
    assert not new.is_speculative and new.params["qc"]["iqr_temp"] == 4.0
    assert new.params["params"]["rx_days"] == 7 and analysis.step == Step.RESULTS
    assert new.params["replaces"] == str(adjusted.pk)
    html = client.get(f"{analysis.url()}indices").content.decode()
    assert "Results are out of date. Recalculating" in html and "data-results-table" in html
    assert "You changed the quality-control thresholds." in html


def test_use_this_data_after_the_run_was_cancelled_queues_a_new_one(client):
    from test_qc_review import run_next

    analysis = ready_analysis(client)
    assert run_next().kind == "qc"  # the checks first, the speculative run waits
    analysis.indices_job.request_cancel()
    client.post(f"{analysis.url()}quality/continue")
    analysis.refresh_from_db()
    job = analysis.indices_job
    assert job.status == Status.QUEUED and not job.is_speculative
    assert job.params["params"]["rx_days"] == 3


def test_a_recalculation_keeps_the_results_until_it_finishes(client):
    """#178: new settings show their run's progress above the results it replaces;
    cancelling it keeps them, a failure says so above them, and success replaces them.
    The settings are the workspace's since #254, so the results are out of date meanwhile:
    the banner says what changed."""
    analysis, old = finished_analysis(client)
    base = f"/w/{analysis.workspace_id}/{analysis.slug}"
    apply_settings(client, analysis, {**defaults(), "rx_days": "7"})
    new = Job.objects.latest("created_at")
    assert new.params["replaces"] == str(old.pk)
    html = client.get(f"{base}/indices").content.decode()
    assert "Results are out of date. Recalculating" in html and "data-results-table" in html
    assert "You changed the settings." in html
    # An index page and Files still show the previous results meanwhile.
    assert client.get(f"{base}/indices/txx").status_code == 200
    assert client.get(f"{base}/downloads").status_code == 200
    # Failed: said above the results, with "Try again".
    Job.objects.filter(pk=new.pk).update(status=Status.FAILED, error="Out of memory.")
    html = client.get(f"{base}/indices").content.decode()
    assert "The recalculation failed" in html and "Out of memory." in html
    assert f'action="/jobs/{new.pk}/retry"' in html and "data-results-table" in html
    # Cancelled: the previous results are the analysis's again.
    Job.objects.filter(pk=new.pk).update(status=Status.QUEUED)
    client.post(f"/jobs/{new.pk}/cancel", {"next": f"{base}/indices"})
    progress = client.get(f"{base}/indices/progress")
    assert progress["HX-Redirect"] == f"{base}/indices"
    html = client.get(f"{base}/indices").content.decode()
    assert "Recalculating" not in html and "data-results-table" in html
    analysis.refresh_from_db()
    assert analysis.indices_job == old
    # Finished: the new results replace them.
    apply_settings(client, analysis, {**defaults(), "rx_days": "7"})
    newer = Job.objects.latest("created_at")
    finish(newer, rename={"rx3day": "rx7day"})
    html = client.get(f"{base}/indices").content.decode()
    assert "Recalculating" not in html and "Days for Rxdday 7 days" in html
