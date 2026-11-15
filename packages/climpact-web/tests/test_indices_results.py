"""Single-station steps 3 and 4 (#78): the index parameters form (every field of R's step
3, validated by the core), the calculation as a job with its stages, the results
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
    """The Sydney sample through step 1, so steps 3 and 4 open (no quality checks run)."""
    load = client.post("/station/sample")["Location"]
    data = {"station_name": STATION, "latitude": "0", "longitude": "0",
            "base_start": "1971", "base_end": "2000"}  # fmt: skip
    assert client.post(load, data).status_code == 302
    return StationAnalysis.objects.get()


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
    analysis = ready_analysis(client)
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
    analysis = ready_analysis(client)
    response = client.get(f"/station/{analysis.pk}/indices")
    assert response.status_code == 200
    html = response.content.decode()
    expected = {"wsdi_days": "1", "csdi_days": "1", "rx_days": "3", "txtn_days": "2",
                "hdd_base": "18.0", "cdd_base": "18.0", "gdd_base": "10.0", "rnnmm": "30.0",
                "spei_months": "24", "custom_threshold": "0.0"}  # fmt: skip
    for name, value in expected.items():
        assert re.search(rf'name="{name}" value="{value}"', html), name
    assert '<option value="TN" selected>' in html and '<option value="&gt;" selected>' in html
    assert 'name="custom_enabled"' in html and "checked" in html
    assert 'name="plot_title"' in html and f'placeholder="{STATION}  ·  0°N, 0°E"' in html
    # The names the parameterised indices will be written under.
    for name in (
        "wsdi1",
        "csdi1",
        "rx3day",
        "tx2tn2",
        "hddheat18",
        "r30mm",
        "24month_spi",
        "TNgt0",
    ):
        assert f"<code>{name}" in html, name
    # Explanations: every parameter's help topic, and the EHF definition.
    assert "Nairn and Fawcett (2013)" in html
    topics = set(re.findall(r'data-help-topic="([^"]+)"', html))
    fields = ("plot_title", "wsdi_days", "csdi_days", "rx_days", "txtn_days", "hdd_base",
              "cdd_base", "gdd_base", "rnnmm", "spei_months", "custom")  # fmt: skip
    assert {f"param.{f}" for f in fields} <= topics
    assert "index.hwEHF" in topics
    # The quality checks were not run: the page says so but lets the user go on.
    assert "quality checks have not been run" in html
    analysis.refresh_from_db()
    assert analysis.step == Step.INDICES


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


def test_custom_index_name_and_units_follow_the_values(client):
    analysis = ready_analysis(client)
    data = {**defaults(), "custom_variable": "PR", "custom_operator": ">=",
            "custom_threshold": "25.5", "group": "custom"}  # fmt: skip
    html = client.post(f"/station/{analysis.pk}/indices/validate", data).content.decode()
    assert "<code>PRge25.5</code>" in html
    assert '<span class="input-group__unit">mm</span>' in html
    assert 'id="param-custom"' in html and "hx-post=" in html


def test_htmx_checks_one_group_and_warns(client):
    analysis = ready_analysis(client)
    url = f"/station/{analysis.pk}/indices/validate"
    html = client.post(url, {**defaults(), "rx_days": "7", "group": "rx_days"}).content.decode()
    assert "<code>rx7day</code>" in html and 'id="param-rx_days"' in html
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


DEFAULTS_NOTE = '<span class="small muted">Climpact'


def _settings(html: str) -> str:
    """The opening tag of the "Change the settings" disclosure."""
    return re.search(r'<details[^>]*id="settings"[^>]*>', html).group(0)


def test_the_primary_action_comes_before_the_settings(client):
    """#114: "Calculate with these settings" straight after the intro, the parameter cards
    in a "Change the settings" disclosure that starts closed with the defaults, and the
    button at the end of the form kept, under a different name."""
    analysis = ready_analysis(client)
    html = client.get(f"/station/{analysis.pk}/indices").content.decode()
    form = re.search(r'<form method="post" action="/station/[^"]+/indices".*?</form>', html, re.S)
    form = form.group(0)
    top = form.index("Calculate with these settings")
    assert top < form.index('id="settings"') < form.index('name="hdd_base"')
    assert form.index('name="hdd_base"') < form.index("<span>Calculate indices</span>")
    assert " open" not in _settings(html) and DEFAULTS_NOTE in html
    # Both submit the one form; the top button is described by the run-time note.
    buttons = re.findall(r'<button type="submit"[^>]*>', form)
    assert len(buttons) == 2 and 'aria-describedby="run-time"' in buttons[0]
    assert 'id="run-time"' in form


def test_the_settings_open_on_errors(client):
    analysis = ready_analysis(client)
    response = client.post(f"/station/{analysis.pk}/indices", {**defaults(), "hdd_base": "warm"})
    html = response.content.decode()
    assert response.status_code == 200 and "data-error-summary" in html
    assert " open" in _settings(html)
    assert html.index('id="settings"') < html.index('name="hdd_base"')
    assert 'href="#id_hdd_base"' in html  # the summary links to the field, now shown


@pytest.mark.parametrize(
    "changes, opened",
    [
        ({}, False),
        ({"rx_days": 7}, True),
        ({"hdd_base": 18}, False),  # an int is the same as the default 18.0
        ({"plot_title": "Sydney"}, True),
        ({"custom_enabled": False}, True),
        ({"custom_threshold": 40.0}, True),
        ({"plots": False, "zip": False, "report": False}, False),  # outside the disclosure
    ],
)
def test_the_settings_open_when_a_value_is_not_the_default(changes, opened):
    from climpact_web.stations.forms_indices import initial_from_params

    initial = {**initial_from_params(None), **changes}
    assert IndexParamsForm(initial=initial).settings_open() is opened


def test_the_settings_of_a_changed_last_run_are_shown_open(client):
    analysis = ready_analysis(client)
    client.post(f"/station/{analysis.pk}/indices", {**defaults(), "rx_days": "7"})
    html = client.get(f"/station/{analysis.pk}/indices").content.decode()
    assert " open" in _settings(html) and DEFAULTS_NOTE not in html


def test_calculate_queues_a_station_job_with_the_parameters(client):
    analysis = ready_analysis(client)
    analysis.qc_params = {"jump": "15", "flatline_days": "4"}  # step 2's thresholds (#77)
    analysis.save()
    data = {**defaults(), "rx_days": "7", "plot_title": "  Sydney   test ", "custom_variable": "TX",
            "custom_operator": ">=", "custom_threshold": "40", "zip": ""}  # fmt: skip
    response = client.post(f"/station/{analysis.pk}/indices", data)
    job = Job.objects.get(kind="station")
    assert response["Location"] == f"/station/{analysis.pk}/results"
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
    html = client.get(f"/station/{analysis.pk}/indices").content.decode()
    assert 'name="rx_days" value="7"' in html and 'value="Sydney test"' in html
    assert "settings of your last calculation" in html


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
    analysis = ready_analysis(client)
    client.post(f"/station/{analysis.pk}/indices", defaults())
    job = Job.objects.get(kind="station")
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
    assert 'class="index-grid"' in client.get(f"/station/{analysis.pk}/results").content.decode()


def test_a_failed_calculation_shows_why_and_offers_the_settings(client):
    analysis = ready_analysis(client)
    client.post(f"/station/{analysis.pk}/indices", defaults())
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
    assert f'href="/station/{analysis.pk}/indices"' in html
    response = client.post(f"/jobs/{job.pk}/retry", {"next": f"/station/{analysis.pk}/results"})
    assert response["Location"] == f"/station/{analysis.pk}/results"
    assert client.post(f"/jobs/{job.pk}/cancel", {"next": "https://example.org/"})["Location"] == (
        f"/jobs/{job.pk}/"
    )


def test_results_without_a_calculation_go_to_step_3(client):
    analysis = ready_analysis(client)
    assert (
        client.get(f"/station/{analysis.pk}/results")["Location"]
        == f"/station/{analysis.pk}/indices"
    )


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
        assert f">{title}</h2>" in html
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
        tail = f'</span><span class="stat__value">{value:g}</span><span class="stat__note">{note}'
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
    html = client.get(url, {"family": "drought"}).content.decode()
    shown = re.findall(r'<li class="index-card" data-family="(\w+)"[^>]*?(?<!hidden)>', html)
    assert set(shown) == {"drought"} and len(shown) == 8
    assert "Showing 8 of 80 indices." in html
    html = client.get(url, {"q": "frost"}).content.decode()
    assert "Showing 1 of 80 indices." in html
    html = client.get(url, {"significant": "1"}).content.decode()
    count = int(re.search(r"Showing (\d+) of 80", html).group(1))
    assert 0 < count < 80 and f"Significant trends only ({count})" in html


def _summary(html: str) -> str:
    return re.search(r'<section class="card stack trend-summary".*?</section>', html, re.S).group(0)


def test_significant_trends_lead_the_dashboard_largest_first(client):
    """Below the actions, the significant trends: every card marked significant, largest
    change (slope per decade over the series' standard deviation) first (#113)."""
    analysis, _job = finished_analysis(client)
    html = client.get(f"/station/{analysis.pk}/results").content.decode()
    summary = _summary(html)
    # First thing after the action row; before the filters and the groups.
    assert html.index('class="cluster results-actions"') < html.index(summary)
    assert html.index(summary) < html.index("data-results-filter")
    keys = re.findall(rf'href="/station/{analysis.pk}/results/([^"#?]+)"', summary)
    cards = re.findall(r'<li class="index-card"(?:(?!</li>).)*?</li>', html, re.S)
    significant = {
        re.search(r"/results/([^\"#?]+)\"", c).group(1) for c in cards if ">Significant</span>" in c
    }
    assert len(keys) == len(set(keys)) == len(significant) == 22
    assert set(keys) == significant
    assert "22 of 80 indices changed significantly" in summary
    # The order, checked from the files: the trend file's annual slope per decade over
    # the standard deviation of the annual table, for the indices the trend file has.
    from climpact.io.climpact_csv import read_climpact_csv

    trend = read_climpact_csv(LAT0 / STATION / "trend" / f"{STATION}_trend.csv").data
    annual = trend[trend["Frequency"] == "annual"].set_index("Index")
    change = {}
    for key in keys:
        if key in annual.index:
            table = read_table(f"{key}_ANN")
            values = table[table.columns[1]]
            change[key] = abs(annual.loc[key, "Slope"] * 10) / values.std()
    assert len(change) >= 15
    checked = [k for k in keys if k in change]
    assert [round(change[k], 6) for k in checked] == sorted(
        (round(v, 6) for v in change.values()), reverse=True
    )
    # Plain name, code and the trend per decade, linked to the index's page.
    link = f'<a href="/station/{analysis.pk}/results/tnm">Mean TN</a>'
    assert f'{link} <code class="index-code">TNm</code>' in summary
    assert "°C per decade" in summary and 'class="spark"' in summary


def test_no_significant_trend_says_so(client, monkeypatch):
    analysis, _job = finished_analysis(client)
    monkeypatch.setattr(results_model.RunResults, "significant", lambda self: [])
    summary = _summary(client.get(f"/station/{analysis.pk}/results").content.decode())
    assert "No index has a significant trend" in summary and "<ol" not in summary


def test_cards_and_index_page_lead_with_the_plain_name(client):
    analysis, _job = finished_analysis(client)
    url = f"/station/{analysis.pk}/results"
    html = client.get(url).content.decode()
    assert f'<a href="{url}/fd">Frost days</a></h3>' in html
    assert '<code class="index-code">FD</code> days' in html
    assert f'<a href="{url}/TX90-HWN">Number of heatwaves (Tx90)</a></h3>' in html
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
    pattern = r'(<details class="disclosure results-section" id="group-([\w-]+)"[^>]*>)'
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
    groups = _groups(client.get(url, {"family": "drought"}).content.decode())
    assert [k for k, t in groups.items() if " open" in t] == ["drought"]
    # Linked from an index's page.
    page = client.get(f"{url}/rx1day").content.decode()
    link = f'href="{url}?group=precipitation#group-precipitation"'
    assert link in page
    groups = _groups(client.get(url, {"group": "precipitation"}).content.decode())
    assert [k for k, t in groups.items() if " open" in t] == ["precipitation"]


def test_downloads_and_next_step(client):
    analysis, job = finished_analysis(client)
    html = client.get(f"/station/{analysis.pk}/results").content.decode()
    assert f"/jobs/{job.pk}/files/{STATION}/trend/{STATION}_trend.csv" in html
    assert f'href="/station/{analysis.pk}/downloads"' in html
    # The optional step 5 is in the action row at the top (#113).
    actions = re.search(r'<div class="cluster results-actions">.*?</div>', html, re.S).group(0)
    assert f'href="/station/{analysis.pk}/sector"' in actions
    assert "Compare with sector data" in actions
    assert client.get(f"/station/{analysis.pk}/sector").status_code == 200
    assert "Kept until" in html


def test_recalculating_keeps_the_user_on_the_same_index(client):
    analysis, _job = finished_analysis(client)
    page = client.get(f"/station/{analysis.pk}/results/rx3day").content.decode()
    assert f'href="/station/{analysis.pk}/indices?index=rx3day"' in page
    form = client.get(f"/station/{analysis.pk}/indices?index=rx3day").content.decode()
    assert 'name="index" value="rx3day"' in form
    response = client.post(
        f"/station/{analysis.pk}/indices", {**defaults(), "rx_days": "7", "index": "rx3day"}
    )
    assert response["Location"] == f"/station/{analysis.pk}/results?index=rx3day"
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
    """#115: the results page's "Change the settings" lands on the settings open, without
    JavaScript, even when the last run used the defaults (which start closed)."""
    analysis, _job = finished_analysis(client)
    html = client.get(f"/station/{analysis.pk}/results").content.decode()
    actions = re.search(r'<div class="cluster results-actions">.*?</div>', html, re.S).group(0)
    link = f"/station/{analysis.pk}/indices?settings=open#settings"
    assert f'href="{link}"' in actions
    assert " open" in _settings(client.get(link).content.decode())
    assert " open" not in _settings(client.get(f"/station/{analysis.pk}/indices").content.decode())


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


def test_step_names_and_headings_match(client):
    """#115: each step's heading is the step's name or starts with it."""
    analysis, _job = finished_analysis(client)
    for path, h1 in [
        (f"/station/{analysis.pk}/load", "Load data: check it and describe the station"),
        (f"/station/{analysis.pk}/indices", "Calculate indices"),
        (f"/station/{analysis.pk}/results", "Results and downloads"),
    ]:
        html = client.get(path).content.decode()
        assert f"<h1>{h1}</h1>" in html
        steps = re.search(r'<ol class="steps container">.*?</ol>', html, re.S).group(0)
        step = re.search(r'aria-current="step">.*?</span>\s*([^<]+)', steps, re.S).group(1)
        assert h1.startswith(step.strip()), (path, step)
