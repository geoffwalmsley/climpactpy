"""Single-station results (#78, #178): the speculative run queued with the default
settings when the station details are confirmed, "Adjust and recalculate" (every field of
R's step 3, validated by the core), the calculation as a job with its stages, the results
dashboard (one card per index table, grouped, filtered), each index's page, the tables not
written, keeping the user on the same index after recalculating, and batch stations.

The results are R's own reference output for the Sydney sample at latitude 0
(``reference/output/lat0``), so "every table appears" and "values match the CSV files"
are checked against the files R writes."""

import json
import math
import re
import shutil
from pathlib import Path

import pytest
from django.test import Client

from climpact_web.jobs.models import Job, Status
from climpact_web.jobs.views import OWNER_KEY
from climpact_web.stations import results as results_model
from climpact_web.stations import themes
from climpact_web.stations.forms_indices import IndexParamsForm
from climpact_web.stations.models import StationAnalysis, Step

REPO = Path(__file__).resolve().parents[3]
LAT0 = REPO / "reference" / "output" / "lat0"
STATION = "sydney_observatory_hill_1936-2015"

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.RUNS_DIR = tmp_path / "media" / "runs"
    return settings


def ready_analysis(client) -> StationAnalysis:
    """The Sydney sample through step 1: the checks and a speculative run of the indices
    with the default settings are queued (#178)."""
    load = client.post("/station/sample")["Location"]
    data = {"station_name": STATION, "latitude": "0", "longitude": "0",
            "base_start": "1971", "base_end": "2000"}  # fmt: skip
    assert client.post(load, data).status_code == 302
    return StationAnalysis.objects.get()


def committed_analysis(client) -> StationAnalysis:
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


def finished_analysis(client, skipped=()) -> tuple[StationAnalysis, Job]:
    analysis = committed_analysis(client)
    analysis.indices_job.request_cancel()  # replaced by a finished run of R's output
    job = Job.objects.create(
        kind="station",
        owner=analysis.owner,
        params={"station_file": "station.txt", "params": {}, "plots": False, "zip": False},
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


# ---- step 3: the form --------------------------------------------------------------------


def test_the_form_has_every_r_parameter_with_its_default(client):
    """ "Adjust and recalculate" (#178) has every setting of R's step 3, with its default,
    on the results page while the speculative run goes on."""
    analysis = committed_analysis(client)
    response = client.get(f"/station/{analysis.pk}/results")
    assert response.status_code == 200
    html = response.content.decode()
    assert "Calculating indices" in html and 'id="adjust"' in html
    expected = {"wsdi_days": "1", "csdi_days": "1", "rx_days": "3", "txtn_days": "2",
                "hdd_base": "18.0", "cdd_base": "18.0", "gdd_base": "10.0", "rnnmm": "30.0",
                "spei_months": "24", "custom_threshold": "0.0"}  # fmt: skip
    for name, value in expected.items():
        assert re.search(rf'name="{name}" value="{value}"', html), name
    assert '<option value="TN" selected>' in html and '<option value="&gt;" selected>' in html
    assert 'name="custom_enabled"' in html and "checked" in html
    assert 'name="plot_title"' in html and f'placeholder="{STATION}  ·  0°N, 0°E"' in html
    # How the parameterised indices are named is in the sections' help (#177), no longer
    # under each field.
    assert "Written as" not in html
    for name in ("wsdi3", "rx3day", "hddheat18", "r30mm", "24month_spi"):
        assert name in html, name
    # Explanations: every parameter's help topic, and the EHF definition.
    assert "Nairn and Fawcett (2013)" in html
    topics = set(re.findall(r'data-help-topic="([^"]+)"', html))
    fields = ("plot_title", "wsdi_days", "csdi_days", "rx_days", "txtn_days", "hdd_base",
              "cdd_base", "gdd_base", "rnnmm", "spei_months", "custom")  # fmt: skip
    assert {f"param.{f}" for f in fields} <= topics
    assert "index.hwEHF" in topics


def test_step_3_needs_the_station_details(client):
    load = client.post("/station/sample")["Location"]
    analysis = StationAnalysis.objects.get()
    assert client.get(f"/station/{analysis.pk}/indices")["Location"] == load


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
    html = client.post(f"/station/{analysis.pk}/indices/validate", data).content.decode()
    assert '<span class="input-group__unit">mm</span>' in html
    assert 'id="param-custom"' in html and "hx-post=" in html


def test_htmx_checks_one_group_and_warns(client):
    analysis = ready_analysis(client)
    url = f"/station/{analysis.pk}/indices/validate"
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


def _settings(html: str) -> str:
    """The opening tag of the "Adjust and recalculate" disclosure."""
    return re.search(r'<details[^>]*id="adjust"[^>]*>', html).group(0)


def test_adjust_and_recalculate_on_the_results(client):
    """#178: the settings are a line in the results' header (the defaults, or what was
    changed) and a closed "Adjust and recalculate" disclosure after the indices, whose one
    button, after the fields, is described by the run-time note. No cards inside it."""
    analysis, _job = finished_analysis(client)
    html = client.get(f"/station/{analysis.pk}/results").content.decode()
    header = re.search(r"<p [^>]*data-settings-line>.*?</p>", html, re.S).group(0)
    assert "Climpact&#x27;s default settings." in header
    assert f'href="/station/{analysis.pk}/results?settings=open#adjust"' in header
    assert " open" not in _settings(html)
    assert html.index('id="catalogue"') < html.index('id="adjust"')
    form = re.search(r'<form method="post" action="/station/[^"]+/indices".*?</form>', html, re.S)
    form = form.group(0)
    assert form.index('name="hdd_base"') < form.index("<span>Recalculate</span>")
    buttons = re.findall(r'<button type="submit"[^>]*>', form)
    assert len(buttons) == 1 and 'aria-describedby="run-time"' in buttons[0]
    assert 'id="run-time"' in form and 'class="card' not in form


def test_the_settings_open_on_errors(client):
    analysis, _job = finished_analysis(client)
    response = client.post(f"/station/{analysis.pk}/indices", {**defaults(), "hdd_base": "warm"})
    html = response.content.decode()
    assert response.status_code == 200 and "data-error-summary" in html
    assert " open" in _settings(html) and "data-results-section" in html  # still the results
    assert html.index('id="adjust"') < html.index('name="hdd_base"')
    assert 'href="#id_hdd_base"' in html  # the summary links to the field, now shown
    assert Job.objects.filter(kind="station").count() == 2  # nothing queued


def test_the_header_names_the_settings_that_were_changed(client):
    analysis, _job = finished_analysis(client)
    client.post(
        f"/station/{analysis.pk}/indices", {**defaults(), "rx_days": "7", "custom_enabled": ""}
    )
    finish(Job.objects.latest("created_at"))
    html = client.get(f"/station/{analysis.pk}/results").content.decode()
    header = re.search(r"<p [^>]*data-settings-line>.*?</p>", html, re.S).group(0)
    assert "Settings changed: Days for Rxdday 7 days, Custom threshold index none." in header
    assert 'name="rx_days" value="7"' in html and " open" not in _settings(html)


def test_recalculate_queues_a_station_job_with_the_parameters(client):
    analysis = committed_analysis(client)
    speculative = analysis.indices_job
    analysis.qc_params = {"jump": "15", "flatline_days": "4"}  # step 2's thresholds (#77)
    analysis.save()
    data = {**defaults(), "rx_days": "7", "plot_title": "  Sydney   test ", "custom_variable": "TX",
            "custom_operator": ">=", "custom_threshold": "40", "zip": ""}  # fmt: skip
    response = client.post(f"/station/{analysis.pk}/indices", data)
    job = Job.objects.exclude(pk=speculative.pk).get(kind="station")
    assert response["Location"] == f"/station/{analysis.pk}/results"
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
    # The form opens with the settings of the last calculation.
    html = client.get(f"/station/{analysis.pk}/results").content.decode()
    assert 'name="rx_days" value="7"' in html and 'value="Sydney test"' in html


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
    html = client.get(f"/station/{analysis.pk}/results").content.decode()
    assert "Calculating indices" in html and 'class="stages"' in html
    assert f'hx-get="/station/{analysis.pk}/results/progress"' in html
    job.status, job.stage, job.step, job.total = Status.RUNNING, "indices:climpact:spi", 40, 100
    job.save()
    html = client.get(f"/station/{analysis.pk}/results/progress").content.decode()
    assert "Calculating indices (spi)" in html and 'value="40"' in html
    assert html.count("stages__item--done") == 3  # read, quality checks, homogeneity
    assert (
        "stages__item--current" in html and "Draw the plots" in html and "Make the zip file" in html
    )
    assert 'name="next" value="/station/' in html  # cancel comes back here
    finish(job)
    response = client.get(f"/station/{analysis.pk}/results/progress")
    assert (
        response.status_code == 204 and response["HX-Redirect"] == f"/station/{analysis.pk}/results"
    )
    assert "data-results-section" in client.get(f"/station/{analysis.pk}/results").content.decode()


def test_a_failed_calculation_shows_why_and_offers_the_settings(client):
    analysis = committed_analysis(client)
    job = Job.objects.get(kind="station")
    job.status, job.error, job.stage = (
        Status.FAILED,
        "The base period has no data.",
        "indices:climpact:fd",
    )
    job.save()
    html = client.get(f"/station/{analysis.pk}/results").content.decode()
    assert "The calculation failed." in html and "The base period has no data." in html
    assert "stages__item--failed" in html
    assert f'href="/station/{analysis.pk}/results?settings=open#adjust"' in html
    response = client.post(f"/jobs/{job.pk}/retry", {"next": f"/station/{analysis.pk}/results"})
    assert response["Location"] == f"/station/{analysis.pk}/results"
    assert client.post(f"/jobs/{job.pk}/cancel", {"next": "https://example.org/"})["Location"] == (
        f"/jobs/{job.pk}/"
    )


def test_no_results_before_use_this_data(client):
    """#178: the speculative run is not shown until the user chooses to use the data, on
    Results or on any page behind it."""
    analysis = ready_analysis(client)
    finish(analysis.indices_job)
    for path in ("results", "results/txx", "downloads"):
        response = client.get(f"/station/{analysis.pk}/{path}")
        assert response.status_code == 302, path
    assert client.get(f"/station/{analysis.pk}/results")["Location"].endswith("/quality")
    sector = client.get(f"/station/{analysis.pk}/sector").content.decode()
    assert "Calculate the indices first" in sector


def test_results_without_a_run_offer_to_calculate(client):
    """When no run was queued (refused in hosted mode, say), Results has the settings open
    with one button, which queues it."""
    analysis = committed_analysis(client)
    analysis.indices_job.request_cancel()
    analysis.indices_job = None
    analysis.save()
    html = client.get(f"/station/{analysis.pk}/results").content.decode()
    assert "The indices are not calculated yet." in html and " open" in _settings(html)
    assert "<span>Calculate</span>" in html
    client.post(f"/station/{analysis.pk}/indices", defaults())
    analysis.refresh_from_db()
    assert analysis.indices_job.status == Status.QUEUED and not analysis.indices_job.is_speculative


def test_the_old_calculate_address_opens_adjust_and_recalculate(client):
    """#178: links, bookmarks and emails to the Calculate step land on the settings."""
    analysis, _job = finished_analysis(client)
    base = f"/station/{analysis.pk}"
    assert client.get(f"{base}/indices")["Location"] == f"{base}/results?settings=open#adjust"
    response = client.get(f"{base}/indices?index=rx3day")
    assert response["Location"] == f"{base}/results?settings=open&back=rx3day#adjust"
    html = client.get(response["Location"]).content.decode()
    assert " open" in _settings(html) and 'name="index" value="rx3day"' in html


# ---- step 4: the dashboard ----------------------------------------------------------------


def test_every_table_of_the_lat0_run_is_on_the_dashboard(client):
    analysis, job = finished_analysis(client)
    html = client.get(f"/station/{analysis.pk}/results").content.decode()
    linked = set(re.findall(rf'href="/station/{analysis.pk}/results/([^"#?]+)"', html))
    files = index_files()
    assert len(files) == 114
    for name in files:
        key = results_model.card_key(name)
        assert key in linked, name
    # Each table opens on its index's page, which links its CSV file.
    for name in files:
        key = results_model.card_key(name)
        page = client.get(f"/station/{analysis.pk}/results/{key}?series={name}")
        assert page.status_code == 200, name
        assert (
            f"/jobs/{job.pk}/files/{STATION}/indices/{STATION}_{name}.csv" in page.content.decode()
        )
    # Grouped as the index catalogue, with the families to filter by.
    for title in ("Temperature: extremes, means and range", "Precipitation", "Heatwaves", "Drought",
                  "Your own index"):  # fmt: skip
        assert f">{title}</h3>" in html
    assert html.count('class="index-card"') == len(linked) == 80
    assert "Showing 80 of 80 indices." in html


def test_card_values_match_the_csv_files(client):
    analysis, _job = finished_analysis(client)
    html = client.get(f"/station/{analysis.pk}/results").content.decode()
    txx = read_table("txx_ANN")
    card = re.search(
        r'<li class="index-card"[^>]*>(?:(?!</li>).)*?/results/txx".*?</li>', html, re.S
    ).group(0)
    last = txx.iloc[-1]
    assert f"Latest: {last['val']:g} °C in {int(last['time'])}" in card
    # The trend is the trend file's (annual row), per decade.
    from climpact.io.climpact_csv import read_climpact_csv

    trend = read_climpact_csv(LAT0 / STATION / "trend" / f"{STATION}_trend.csv").data
    row = trend[(trend["Index"] == "txx") & (trend["Frequency"] == "annual")].iloc[0]
    slope = row["Slope"] * 10
    assert f"{'+' if slope > 0 else '−'}{abs(slope):.2f}".rstrip("0") in card
    significant = row["Lower bound"] > 0 or row["Upper bound"] < 0
    assert ("Not significant" not in card) == significant


def test_index_page_values_match_the_csv_and_trend_files(client):
    analysis, job = finished_analysis(client)
    html = client.get(f"/station/{analysis.pk}/results/txx").content.decode()
    txx = read_table("txx_ANN")
    high = txx.loc[txx["val"].idxmax()]
    low = txx.loc[txx["val"].idxmin()]

    def stat(label, value, note):
        value = f"{value:g} °C"  # with the index's units (#173)
        tail = f'</span><span class="stat__value">{value}</span><span class="stat__note">{note}'
        return f"{label}{tail}" in html

    assert stat("Highest", high["val"], int(high["time"]))
    assert stat("Lowest", low["val"], int(low["time"]))
    # The interactive chart reads the job's series, with the run's trend.
    assert f'data-chart-src="/charts/jobs/{job.pk}/series/txx_ANN.json?station={STATION}"' in html
    payload = json.loads(
        client.get(f"/charts/jobs/{job.pk}/series/txx_ANN.json?station={STATION}").content
    )
    assert payload["y"][-1] == txx["val"].iloc[-1]
    # Every row of the trend file for txx: yearly, monthly and the four seasons.
    for label in ("Yearly", "Monthly", "December to February", "September to November"):
        assert f"{label} <span" in html
    # Annual and monthly series and the days of occurrence.
    for label in ("Yearly", "Monthly", "Day of occurrence, yearly", "Day of occurrence, monthly"):
        assert f">{label}</a>" in html
    assert "Change it and calculate again" not in html  # txx takes no setting
    monthly = client.get(f"/station/{analysis.pk}/results/txx?series=txx_MON").content.decode()
    assert "txx_MON.json" in monthly and 'aria-current="page">Monthly' in monthly


def test_standardised_anomalies_where_the_table_has_them(client):
    analysis, job = finished_analysis(client)
    html = client.get(f"/station/{analysis.pk}/results/tmm").content.decode()
    url = f"/station/{analysis.pk}/results/tmm_ANN/anomalies.json"
    assert f'data-chart-src="{url}"' in html
    payload = json.loads(client.get(url).content)
    table = read_table("tmm_ANN")
    column = [c for c in table.columns if c.startswith("standardised")][0]
    expected = [None if math.isnan(v) else v for v in table[column]]
    assert payload["bars"] and payload["y"] == expected and payload["x"][0] == 1936
    assert payload["bar_labels"] == ["Above the mean", "Below the mean"]
    # txx has no standardised column; SPI none either.
    assert (
        "anomalies.json" not in client.get(f"/station/{analysis.pk}/results/txx").content.decode()
    )
    assert client.get(f"/station/{analysis.pk}/results/txx_ANN/anomalies.json").status_code == 404


def test_daily_ehf_and_tables_without_plots(client):
    analysis, _job = finished_analysis(client)
    html = client.get(f"/station/{analysis.pk}/results/EHFdaily").content.decode()
    table = read_table("EHFdaily")
    top = table.loc[table["Excess Heat Factor"].idxmax()]
    assert "The ten highest days" in html and str(top["date"]) in html
    assert "data-chart-src" not in html
    html = client.get(f"/station/{analysis.pk}/results/tx95t").content.decode()
    assert "tx95t_DAY.json" in html


def test_tables_not_written_are_listed_with_the_reason(client):
    analysis, _job = finished_analysis(
        client, skipped=["indices/tn10p_ANN", "indices/tn10p_MON", "thres/x"]
    )
    analysis.base_start, analysis.base_end = 2020, 2030  # outside the data
    analysis.save()
    html = client.get(f"/station/{analysis.pk}/results").content.decode()
    assert "1 index could not be calculated" in html
    assert "<strong>TN10p</strong> (tn10p_ANN, tn10p_MON)" in html
    assert "percentiles could not be calculated" in html


def test_the_reason_names_a_variable_with_no_data():
    summary = {"variables": [{"key": "prcp", "present": 0}, {"key": "tmax", "present": 9}]}
    [entry] = results_model.skipped_tables(["indices/r30mm_ANN"], summary, None)
    assert entry["name"] == "R30mm" and "no precipitation values" in entry["reason"]
    [entry] = results_model.skipped_tables(["indices/txx_MON"], summary, None)
    assert "missing-data rules" in entry["reason"]


def test_filters_without_javascript(client):
    analysis, _job = finished_analysis(client)
    url = f"/station/{analysis.pk}/results"
    html = client.get(url, {"theme": "drought"}).content.decode()
    shown = re.findall(r'<li class="index-card" data-index-theme="(\w+)"[^>]*?(?<!hidden)>', html)
    assert set(shown) == {"drought"} and len(shown) == 9  # SPI, SPEI and CDD
    assert "Showing 9 of 80 indices." in html
    html = client.get(url, {"q": "frost"}).content.decode()
    assert "Showing 1 of 80 indices." in html
    html = client.get(url, {"significant": "1"}).content.decode()
    count = int(re.search(r"Showing (\d+) of 80", html).group(1))
    assert 0 < count < 80 and f"Significant trends only ({count})" in html


def _findings(html: str) -> str:
    return re.search(
        r'<section class="stack" aria-labelledby="findings-title">.*?id="catalogue"', html, re.S
    ).group(0)


def _theme(html: str, key: str) -> str:
    pattern = rf'<section class="card theme-headline[^"]*" aria-labelledby="theme-{key}-title">'
    pattern += ".*?</section>"
    return re.search(pattern, html, re.S).group(0)


def _text(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", "", html).replace("&gt;", ">").split())


def test_findings_by_theme_lead_the_results(client):
    """#175: below the actions, the answer in one sentence, a headline per theme with its
    largest significant trends, and the "Also measured" lines; the catalogue follows."""
    analysis, _job = finished_analysis(client)
    url = f"/station/{analysis.pk}/results"
    html = client.get(url).content.decode()
    findings = _findings(html)
    assert html.index('results-actions"') < html.index(findings) < html.index("data-results-filter")
    assert (
        '<p class="findings__answer">22 of 80 indices changed significantly since 1936. '
        "Mean temperature rose by 0.19\u00a0°C per decade. "
        "Changed: Heat, Cold. No significant change: Rain, Drought.</p>"
    ) in findings
    heat = _theme(findings, "heat")
    assert ">9 changed</span>" in heat
    assert "9 of 22 indices increased significantly." in heat  # 22 of the 30 have a trend
    # Up to three trends, largest change first, plain name then code, units, linked.
    keys = re.findall(rf'href="{url}/([^"#?]+)"', heat)
    assert keys == ["tr", "tn90p", "su"]
    assert f'<a href="{url}/tr">Tropical nights</a> <code class="index-code">TR</code>' in heat
    assert "+4.65\u00a0days per decade" in heat
    assert "+1.31\u00a0percentage points per decade" in heat
    assert heat.count('class="spark"') == 3
    cold = _text(_theme(findings, "cold"))
    assert "4 of 11 indices changed significantly: 2 increased and 2 decreased." in cold
    # No change is a finding too, in a quiet panel without trends.
    for key, n in (("rain", 13), ("drought", 9)):
        panel = _theme(findings, key)
        assert "theme-headline--quiet" in panel and "trend-list" not in panel
        assert f"No significant change across {n} indices." in panel
        assert ">No clear change</span>" in panel
    # Each theme links to its indices in the catalogue, which shows only them.
    link = f'href="{url}?theme=heat#catalogue">See all 30 indices in Heat</a>'
    assert link in heat
    assert "Showing 30 of 80 indices." in client.get(url, {"theme": "heat"}).content.decode()
    # Also measured: one line each, the user's own index with its definition.
    also = _text(re.search(r'aria-labelledby="also-title">.*?</section>', findings, re.S).group(0))
    assert "Averages: 4 of 5 indices increased significantly." in also
    assert "Mean temperature (TMm): +0.19 °C per decade" in also
    assert "Growing season and degree days: 5 of 8 indices changed significantly" in also
    assert "Your own index: Number of days where TN > 0 TNgt0. No significant change." in also
    assert f'href="{url}/TNgt0"' in findings
    # The order of the trends is said where it is used, and explained in its help (#177).
    assert "up to three significant trends, largest first." in findings
    assert "Largest means the trend per decade divided by" in findings  # the ⓘ's help


def test_largest_change_orders_each_themes_trends(client):
    """The trends a theme shows are its largest changes: the slope per decade over the
    series' standard deviation, checked from R's trend file and tables (#113)."""
    from climpact.io.climpact_csv import read_climpact_csv

    analysis, _job = finished_analysis(client)
    url = f"/station/{analysis.pk}/results"
    findings = _findings(client.get(url).content.decode())
    trend = read_climpact_csv(LAT0 / STATION / "trend" / f"{STATION}_trend.csv").data
    annual = trend[trend["Frequency"] == "annual"].set_index("Index")
    significant = annual[(annual["Lower bound"] > 0) | (annual["Upper bound"] < 0)]

    def change(key):
        values = read_table(f"{key}_ANN")
        return abs(annual.loc[key, "Slope"] * 10) / values[values.columns[1]].std()

    for key in ("heat", "cold"):
        shown = re.findall(rf'href="{url}/([^"#?]+)"', _theme(findings, key))
        assert len(shown) == 3, key
        members = [
            k
            for k in significant.index
            if themes.theme_of(k, results_model.catalogue.index_for_output(k)) == key
        ]
        expected = sorted(members, key=lambda k: -change(k))[: len(shown)]
        assert shown == expected, key


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
    """#175: with no significant trend, the answer and every theme say so; no change is a
    finding, not an empty page."""
    analysis, job = finished_analysis(client)
    flatten(job.output_dir / STATION)
    html = client.get(f"/station/{analysis.pk}/results").content.decode()
    findings = _findings(html)
    assert (
        '<p class="findings__answer">No index changed significantly since 1936. '
        "Mean temperature did not change significantly.</p>"
    ) in findings
    for key in ("heat", "cold", "rain", "drought"):
        panel = _theme(findings, key)
        assert "theme-headline--quiet" in panel and "trend-list" not in panel, key
        assert "No significant change across" in panel and "No clear change" in panel, key
    assert "No significant change across 13 indices." in _theme(findings, "rain")
    assert ">Significant</span>" not in html and "Significant trends only (0)" in html


def test_finding_wording():
    """The headline sentences, from the trends: counts of indices with a trend, the
    direction of the significant ones, and no change as a finding."""
    from types import SimpleNamespace

    def card(significant=False, direction="up", valid=True):
        trend = {"valid": valid, "significant": significant, "direction": direction}
        return SimpleNamespace(trend=trend if valid is not None else None, significant=significant)

    finding = themes.finding
    assert finding([card(), card(), card(valid=None)]) == "No significant change across 2 indices."
    assert finding([card()]) == "No significant change in the one index with a trend."
    assert finding([card(True), card()]) == "1 of 2 indices increased significantly."
    assert finding([card(True, "down"), card()]) == "1 of 2 indices decreased significantly."
    assert finding([card(True), card(True, "down"), card()]) == (
        "2 of 3 indices changed significantly: 1 increased and 1 decreased."
    )
    assert finding([card(valid=False), card(valid=None)]) == ""


def test_every_index_has_one_place_in_the_themes():
    """Decision C (#175): every short name of the core's index file is in exactly one theme
    or "Also measured" line; nothing else is in the mapping."""
    shorts = set(results_model.catalogue.by_short())
    placed = [s for theme in themes.THEMES for s in theme.shorts]
    assert len(placed) == len(set(placed)), "an index is in two themes"
    assert set(placed) == shorts
    assert [t.key for t in themes.THEMES if t.headline] == ["heat", "cold", "rain", "drought"]


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


def test_cards_and_index_page_lead_with_the_plain_name(client):
    analysis, _job = finished_analysis(client)
    url = f"/station/{analysis.pk}/results"
    html = client.get(url).content.decode()
    assert f'<a href="{url}/fd">Frost days</a></h4>' in html
    assert '<code class="index-code">FD</code> days' in html
    assert f'<a href="{url}/TX90-HWN">Number of heatwaves (Tx90)</a></h4>' in html
    assert '<code class="index-code">TX90-HWN</code>' in html
    assert f'<a href="{url}/3month_spi">Standardised precipitation index, 3 months</a>' in html
    # Codes still find their index.
    assert "Showing 1 of 80 indices." in client.get(url, {"q": "tnltm20"}).content.decode()
    page = client.get(f"{url}/txx").content.decode()
    assert "<h1>Max TX</h1>" in page and '<code class="index-code">TXx</code>' in page
    assert "<title>Max TX (TXx): " in page


def test_plain_names_of_indices_that_share_a_catalogue_entry():
    by_short = results_model.catalogue.by_short()
    name = results_model.plain_name
    assert name("EHF-HWLI", by_short["hwEHF"]) == "Total heatwave intensity (EHF)"
    assert name("TN90-HWA", by_short["hw"]) == "Peak temperature of the hottest heatwave (Tn90)"
    assert name("24month_spei", by_short["spei"]).endswith(", 24 months")
    assert name("EHFdaily", by_short["hwEHF"]) == "Excess heat factor, daily"
    assert name("TNgt0", None) == "Your own threshold index"
    assert name("fd", by_short["fd"]) == "Frost days"


def _groups(html: str) -> dict[str, str]:
    """Each group's <details> start tag, by group key."""
    pattern = r'(<details class="disclosure" id="group-([\w-]+)"[^>]*>)'
    return {key: tag for tag, key in re.findall(pattern, html)}


def test_groups_are_collapsed_until_filtered_or_linked(client):
    """Groups are <details>, collapsed by default; a filter or search opens the groups it
    shows, and the index page's "All indices" link opens its group, without JavaScript."""
    analysis, _job = finished_analysis(client)
    url = f"/station/{analysis.pk}/results"
    html = client.get(url).content.decode()
    groups = _groups(html)
    assert len(groups) == 8 and not any(" open" in tag for tag in groups.values())
    assert "13 indices · 4 significant</span>" in html  # fixed-threshold group: count
    assert ">14 indices</span>" in html  # precipitation: nothing significant
    # A search opens only the group with a match.
    groups = _groups(client.get(url, {"q": "frost"}).content.decode())
    assert " open" in groups["temperature-thresholds"]
    assert all(" open" not in t and " hidden" in t for k, t in groups.items()
               if k != "temperature-thresholds")  # fmt: skip
    groups = _groups(client.get(url, {"theme": "drought"}).content.decode())
    assert [k for k, t in groups.items() if " open" in t] == ["precipitation", "drought"]
    # Linked from an index's page.
    page = client.get(f"{url}/rx1day").content.decode()
    link = f'href="{url}?group=precipitation#group-precipitation"'
    assert link in page
    groups = _groups(client.get(url, {"group": "precipitation"}).content.decode())
    assert [k for k, t in groups.items() if " open" in t] == ["precipitation"]


def test_downloads_and_next_step(client):
    analysis, job = finished_analysis(client)
    html = client.get(f"/station/{analysis.pk}/results").content.decode()
    # The files are on the Files page, not here (#176).
    assert f"/jobs/{job.pk}/files/" not in html
    assert f'href="/station/{analysis.pk}/downloads"' in html
    # Without a zip, the link to the downloads page is the header's one action (#173;
    # with a zip, test_downloads.test_dashboard_and_index_page_show_sizes).
    actions = re.search(r'<div class="[^"]*results-actions">.*?</div>', html, re.S).group(0)
    assert actions.count('class="button"') == 1 and actions.count("<a ") == 1
    assert f'href="/station/{analysis.pk}/downloads"' in actions
    # The sector comparison is an action lower on the page, not a step (#173).
    sector = re.search(r'<section[^>]*aria-labelledby="sector-title">.*?</section>', html, re.S)
    assert f'href="/station/{analysis.pk}/sector"' in sector.group(0)
    assert f'href="/station/{analysis.pk}/sector"' not in actions
    assert client.get(f"/station/{analysis.pk}/sector").status_code == 200
    assert "Kept until" in html


def test_units_on_the_stat_row_and_percentage_point_trends(client):
    """#173: the index page's stats carry the index's units, and a trend in a percentage
    index is in percentage points per decade, not percent."""
    analysis, _job = finished_analysis(client)
    html = client.get(f"/station/{analysis.pk}/results").content.decode()
    assert "percentage points per decade" in html and "% per decade" not in html
    page = client.get(f"/station/{analysis.pk}/results/tx90p").content.decode()
    for label in ("Highest", "Lowest", "Mean"):
        assert re.search(rf'{label}</span><span class="stat__value">[0-9.,]+%</span>', page)
    assert re.search(r'Trend</span><span class="stat__value">\S+ percentage points</span>', page)
    days = client.get(f"/station/{analysis.pk}/results/su").content.decode()
    assert re.search(r'Highest</span><span class="stat__value">[0-9.,]+ days</span>', days)


def test_trend_and_stat_units():
    from climpact_web.charts.data import trend_units
    from climpact_web.stations.results import with_units

    assert trend_units("%") == "percentage points" and trend_units("°C") == "°C"
    assert with_units("12.5", "%") == "12.5%" and with_units("20", "days") == "20 days"
    assert with_units("0.4", "") == "0.4"


def test_sector_comparison_is_not_a_step(client):
    """#173: the sector page is part of Results: its tab is the current one (#179)."""
    analysis, _job = finished_analysis(client)
    html = client.get(f"/station/{analysis.pk}/sector").content.decode()
    assert re.search(r'data-tab="results" data-state="done" aria-current="page"', html)
    assert len(re.findall(r'data-tab="\w+"[^>]*aria-current', html)) == 1
    assert "steps__item" not in html


def test_recalculating_keeps_the_user_on_the_same_index(client):
    analysis, _job = finished_analysis(client)
    page = client.get(f"/station/{analysis.pk}/results/rx3day").content.decode()
    link = f"/station/{analysis.pk}/results?settings=open&amp;back=rx3day#adjust"
    assert f'href="{link}"' in page
    form = client.get(link.replace("&amp;", "&")).content.decode()
    assert 'name="index" value="rx3day"' in form
    response = client.post(
        f"/station/{analysis.pk}/indices", {**defaults(), "rx_days": "7", "index": "rx3day"}
    )
    assert response["Location"] == f"/station/{analysis.pk}/results?index=rx3day"
    # While it runs, the page stays on the results, under the recalculation's progress.
    html = client.get(response["Location"]).content.decode()
    assert "Recalculating" in html and "results/progress?index=rx3day" in html
    job = Job.objects.latest("created_at")
    finish(job, rename={"rx3day": "rx7day"})
    # When the job ends, the progress fragment sends the browser to the results with the
    # index, which opens the same index under its new name.
    progress = client.get(f"/station/{analysis.pk}/results/progress?index=rx3day")
    assert progress["HX-Redirect"] == f"/station/{analysis.pk}/results?index=rx3day"
    response = client.get(progress["HX-Redirect"])
    assert response["Location"] == f"/station/{analysis.pk}/results/rx7day"
    assert client.get(response["Location"]).status_code == 200
    # An old index address leads to the same index too.
    assert client.get(f"/station/{analysis.pk}/results/rx3day")["Location"].endswith(
        "/results/rx7day"
    )


def test_other_sessions_get_404(client):
    analysis, job = finished_analysis(client)
    other = Client()
    session = other.session
    session[OWNER_KEY] = "someone-else"
    session.save()
    for path in (
        "indices",
        "results",
        "results/txx",
        "results/progress",
        "results/tmm_ANN/anomalies.json",
        "sector",
    ):
        assert other.get(f"/station/{analysis.pk}/{path}").status_code == 404, path
    assert other.post(f"/station/{analysis.pk}/indices", defaults()).status_code == 404
    assert client.get(f"/station/{analysis.pk}/results/nope").status_code == 404


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


def test_change_the_settings_on_the_results_opens_them(client):
    """#115, #178: the header's "Adjust and recalculate" opens the settings in place,
    without JavaScript; they start closed otherwise."""
    analysis, _job = finished_analysis(client)
    html = client.get(f"/station/{analysis.pk}/results").content.decode()
    link = f"/station/{analysis.pk}/results?settings=open#adjust"
    assert f'href="{link}"' in html
    assert " open" in _settings(client.get(link).content.decode())
    assert " open" not in _settings(html)


def test_index_page_chart_title_is_the_cleaned_definition(client):
    """#115: the chart title is the code and the cleaned definition (°C), as the page's
    subtitle, not R's raw plot subtitle."""
    analysis, _job = finished_analysis(client)
    html = client.get(f"/station/{analysis.pk}/results/su").content.decode()
    title = re.search(r'<h2 class="chart__title" id="index-chart-title">(.*?)</h2>', html).group(1)
    assert title == "SU: Annual number of days when TX &gt; 25 °C"
    assert "degrees_C" not in title
    monthly = client.get(f"/station/{analysis.pk}/results/txx?series=txx_MON").content.decode()
    assert re.search(r'id="index-chart-title">TXx: [^<]*</h2>', monthly)


def test_each_section_is_a_tab_named_in_the_title(client):
    """#179: each section page has the station's name as its h1, the tabs under it with
    its own current, and the section's name in the page title. The index and sector pages
    belong to Results, with their own h1."""
    analysis, _job = finished_analysis(client)
    base = f"/station/{analysis.pk}"
    for path, tab, title in [
        ("/load", "data", "Data"),
        ("/quality", "quality", "Quality"),
        ("/results", "results", "Results"),
        ("/downloads", "files", "Files"),
    ]:
        html = client.get(base + path).content.decode()
        assert f'<h1 class="m-0">{STATION}</h1>' in html, path
        assert f"<title>{title}: {STATION}" in html, path
        current = re.findall(r'data-tab="(\w+)" data-state="\w+" aria-current="page"', html)
        assert current == [tab], path
        assert html.count("<h1") == 1 and "steps__item" not in html, path
    html = client.get(base + "/results/txx").content.decode()
    assert "<h1>Max TX</h1>" in html and '<p class="m-0 font-semibold' in html
    assert re.findall(r'data-tab="(\w+)" data-state="\w+" aria-current="page"', html) == ["results"]


def test_every_section_of_the_station_pages_has_its_help(client):
    """#177: one ⓘ per section of Results (with "Adjust and recalculate", #178), an index
    and Files, in page order; no help link under a field."""
    analysis, _job = finished_analysis(client)
    base = f"/station/{analysis.pk}"
    expected = {
        "/results": [
            "results.findings",
            "results.catalogue",
            "calculate.plots",
            "calculate.spells",
            "calculate.degree",
            "calculate.prcp",
            "calculate.custom",
            "calculate.ehf",
            "calculate.files",
        ],
        "/results/txx": ["result.index", "result.trends"],  # no anomalies in this fixture
        "/downloads": ["files.page"],
    }
    for path, ids in expected.items():
        html = client.get(base + path).content.decode()
        assert re.findall(r'href="/help/sections/([^/"?]+)/', html) == ids, path
        assert "help-topic--compact" not in html, path
    # The index page's help leads with the index itself.
    html = client.get(base + "/results/txx").content.decode()
    assert 'href="/help/sections/result.index/?topics=index.txx"' in html
    assert '<span class="sr-only">Help: TXx</span>' in html


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
    response = client.post(
        f"/station/{analysis.pk}/quality/file", {"station_file": _station_upload()}
    )
    assert response.status_code == 302
    analysis.refresh_from_db()
    old.refresh_from_db()
    assert old.status == Status.CANCELLED
    new = analysis.indices_job
    assert new != old and new.is_speculative and new.status == Status.QUEUED
    assert (new.input_dir / "station.txt").read_bytes() == analysis.station_file.read_bytes()


def test_a_new_file_on_load_cancels_the_run_until_the_details_are_confirmed(client):
    analysis = ready_analysis(client)
    old = analysis.indices_job
    client.post(f"/station/{analysis.pk}/file", {"station_file": _station_upload()})
    analysis.refresh_from_db()
    old.refresh_from_db()
    # Cancelled, and kept as the analysis's run (of the old file) until the details are
    # confirmed (#179).
    assert old.status == Status.CANCELLED and analysis.indices_job == old
    data = {"station_name": STATION, "latitude": "0", "longitude": "0",
            "base_start": "1971", "base_end": "2000"}  # fmt: skip
    client.post(f"/station/{analysis.pk}/load", data)
    analysis.refresh_from_db()
    assert analysis.indices_job.is_speculative and analysis.indices_job != old


def test_new_thresholds_replace_the_run_and_keep_the_settings(client):
    """The full run writes the QC files too, so new thresholds replace it; the settings of
    the last calculation are kept, not reset to the defaults. The data is in use, so the
    replacement is the user's own run, and the results stay, out of date, meanwhile
    (#179)."""
    from climpact_web.stations.forms import QC_DEFAULTS

    analysis, old = finished_analysis(client)
    client.post(f"/station/{analysis.pk}/indices", {**defaults(), "rx_days": "7"})
    analysis.refresh_from_db()
    adjusted = analysis.indices_job
    finish(adjusted)
    thresholds = {**{k: str(v) for k, v in QC_DEFAULTS.items()}, "iqr_temp": "4"}
    client.post(f"/station/{analysis.pk}/quality/run", thresholds)
    analysis.refresh_from_db()
    new = analysis.indices_job
    assert not new.is_speculative and new.params["qc"]["iqr_temp"] == 4.0
    assert new.params["params"]["rx_days"] == 7 and analysis.step == Step.RESULTS
    assert new.params["replaces"] == str(adjusted.pk)
    html = client.get(f"/station/{analysis.pk}/results").content.decode()
    assert "Results are out of date. Recalculating" in html and "data-results-section" in html
    assert "You changed the quality-control thresholds." in html


def test_use_this_data_after_the_run_was_cancelled_queues_a_new_one(client):
    from test_qc_review import run_next

    analysis = ready_analysis(client)
    assert run_next().kind == "qc"  # the checks first, the speculative run waits
    analysis.indices_job.request_cancel()
    client.post(f"/station/{analysis.pk}/quality/continue")
    analysis.refresh_from_db()
    job = analysis.indices_job
    assert job.status == Status.QUEUED and not job.is_speculative
    assert job.params["params"]["rx_days"] == 3


def test_a_recalculation_keeps_the_results_until_it_finishes(client):
    """#178: "Recalculate" shows its progress above the results it replaces; cancelling it
    keeps them, a failure says so above them, and success replaces them."""
    analysis, old = finished_analysis(client)
    base = f"/station/{analysis.pk}"
    client.post(f"{base}/indices", {**defaults(), "rx_days": "7"})
    new = Job.objects.latest("created_at")
    assert new.params["replaces"] == str(old.pk)
    html = client.get(f"{base}/results").content.decode()
    assert "Recalculating" in html and "data-results-section" in html
    assert "The results below use the previous settings." in html
    # An index page and Files still show the previous results meanwhile.
    assert client.get(f"{base}/results/txx").status_code == 200
    assert client.get(f"{base}/downloads").status_code == 200
    # Failed: said above the results, with "Try again".
    Job.objects.filter(pk=new.pk).update(status=Status.FAILED, error="Out of memory.")
    html = client.get(f"{base}/results").content.decode()
    assert "The recalculation failed" in html and "Out of memory." in html
    assert f'action="/jobs/{new.pk}/retry"' in html and "data-results-section" in html
    # Cancelled: the previous results are the analysis's again.
    Job.objects.filter(pk=new.pk).update(status=Status.QUEUED)
    client.post(f"/jobs/{new.pk}/cancel", {"next": f"{base}/results"})
    progress = client.get(f"{base}/results/progress")
    assert progress["HX-Redirect"] == f"{base}/results"
    html = client.get(f"{base}/results").content.decode()
    assert "Recalculating" not in html and "data-results-section" in html
    analysis.refresh_from_db()
    assert analysis.indices_job == old
    # Finished: the new results replace them.
    client.post(f"{base}/indices", {**defaults(), "rx_days": "7"})
    newer = Job.objects.latest("created_at")
    finish(newer, rename={"rx3day": "rx7day"})
    html = client.get(f"{base}/results").content.decode()
    assert "Recalculating" not in html and "Days for Rxdday 7 days" in html
