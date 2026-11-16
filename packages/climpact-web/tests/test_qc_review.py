"""Step 2, Check quality (#77): the thresholds, the qc job, the review of its files, the
charts' flags, the tables and their pages, re-uploading a corrected file and going on to
step 3."""

import json
import re
import shutil
from dataclasses import asdict, fields
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from climpact_web.jobs.models import Job, Status
from climpact_web.jobs.registry import RUNNERS
from climpact_web.jobs.worker import claim, run_job
from climpact_web.stations import qc_plots, qc_review
from climpact_web.stations.forms import QC_DEFAULTS, QCParamsForm
from climpact_web.stations.models import StationAnalysis, Step

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parents[3]
STRESS = ROOT / "reference" / "input" / "qc_stress_1961-2020.txt"
STRESS_QC = ROOT / "reference" / "output" / "qc_stress" / "qc_stress_1961-2020" / "qc"
META = {"latitude": "52.38", "longitude": "13.06", "base_start": "1971", "base_end": "2000"}


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.RUNS_DIR = tmp_path / "media" / "runs"


def run_next() -> Job:
    job = claim("test-worker")
    assert job is not None
    return run_job(job, None)


def start(client, path=STRESS, name="qc_stress_1961-2020") -> StationAnalysis:
    """Step 1 with the file, then "Continue": the checks are queued at once."""
    response = client.post(
        "/station/", {"station_file": SimpleUploadedFile(path.name, path.read_bytes())}
    )
    load = response["Location"]
    response = client.post(load, {"station_name": name, **META})
    analysis = StationAnalysis.objects.get()
    assert response["Location"] == f"/station/{analysis.pk}/quality"
    return analysis


@pytest.fixture
def checked(client):
    analysis = start(client)
    job = run_next()
    assert job.status == Status.SUCCEEDED, job.error
    analysis.refresh_from_db()
    return analysis


# ---- Thresholds ------------------------------------------------------------------------------


def test_form_defaults_are_the_core_and_r_defaults():
    from climpact.config import QCParams

    assert QC_DEFAULTS == asdict(QCParams())
    assert list(QCParamsForm().fields) == [f.name for f in fields(QCParams)]


@pytest.mark.parametrize(
    "name, low, high",
    [
        ("iqr_temp", 1, 10),
        ("iqr_prec", 1, None),
        ("prec_max", 0, 1500),
        ("temp_max", 0, 60),
        ("flatline_days", 3, 15),
        ("jump", 5, 30),
    ],
)
def test_form_limits_are_those_of_the_r_app(name, low, high):
    """numericInput min and max in singleStationStep2UI.R."""
    ok = {k: str(v) for k, v in QC_DEFAULTS.items()}
    assert QCParamsForm({**ok, name: str(low)}).is_valid()
    assert not QCParamsForm({**ok, name: str(low - 1)}).is_valid()
    if high is not None:
        assert QCParamsForm({**ok, name: str(high)}).is_valid()
        assert not QCParamsForm({**ok, name: str(high + 1)}).is_valid()
    assert not QCParamsForm({**ok, name: ""}).is_valid()


def test_qc_runner_takes_the_thresholds():
    from climpact.config import QCParams
    from climpact_web.jobs.runners import qc_params

    assert "qc" in RUNNERS
    assert qc_params(None) == QCParams()
    assert qc_params({"jump": "15", "flatline_days": 7.0}) == QCParams(jump=15.0, flatline_days=7)


# ---- The job and its files -------------------------------------------------------------------


def test_continue_from_step_one_queues_the_checks(client):
    analysis = start(client)
    job = analysis.qc_job
    assert job.kind == "qc" and job.status == Status.QUEUED
    assert job.params["qc"] == QC_DEFAULTS
    assert job.params["metadata"]["name"] == "qc_stress_1961-2020"
    page = client.get(f"/station/{analysis.pk}/quality").content.decode()
    assert 'id="qc-progress"' in page and f"/station/{analysis.pk}/quality/progress" in page
    assert "chart_scripts" not in page and "uPlot" not in page  # no charts until results
    # The indices are queued too, with the default settings, behind the checks (#178).
    run = analysis.indices_job
    assert run.kind == "station" and run.is_speculative and run.params["qc"] == QC_DEFAULTS
    assert run.created_at >= job.created_at
    # Visiting step 1 and continuing again with nothing changed does not queue again.
    client.post(f"/station/{analysis.pk}/load", {"station_name": "qc_stress_1961-2020", **META})
    assert Job.objects.count() == 2


def test_while_the_checks_run_the_thresholds_are_tucked_away(client):
    """#114: the checks start by themselves, so the page says they are running and the
    thresholds form is behind "Change the thresholds", not a "Run" button in view."""
    analysis = start(client)
    page = client.get(f"/station/{analysis.pk}/quality").content.decode()
    assert "Running the quality checks…" in page and "Waiting to run" not in page
    assert "Run the quality checks" not in page
    details = re.search(r'<details class="disclosure"[^>]*>\s*<summary>.*?</summary>', page, re.S)
    assert details and "Change the thresholds<" in details.group(0)
    assert " open" not in details.group(0).split(">")[0]
    assert page.index("<summary>", details.start()) < page.index('name="iqr_temp"')
    assert "Restart the checks with these thresholds" in page
    # Before any check (no job) the form is in view, to run them by hand.
    analysis.qc_job = None
    analysis.save()
    page = client.get(f"/station/{analysis.pk}/quality").content.decode()
    assert "Run the quality checks" in page and "Change the thresholds<" not in page


def test_qc_job_writes_the_qc_files_like_r(checked):
    job = checked.qc_job
    names = sorted(Path(f).name for f in job.result["files"])
    expected = sorted(p.name for p in STRESS_QC.iterdir())
    assert names == expected
    for name in expected:
        ours = (job.output_dir / "qc_stress_1961-2020" / "qc" / name).read_text().splitlines()
        theirs = (STRESS_QC / name).read_text().splitlines()
        # Everything but the date of calculation is R's text.
        assert [line for line in ours if "Date_of_calculation" not in line] == [
            line for line in theirs if "Date_of_calculation" not in line
        ], name
    assert job.result["zip"] == "qc_stress_1961-2020.zip"
    assert (job.output_dir / job.result["zip"]).is_file()
    assert job.result["qc"] == QC_DEFAULTS


def test_progress_fragment_refreshes_the_page_when_done(client):
    analysis = start(client)
    url = f"/station/{analysis.pk}/quality/progress"
    assert 'id="qc-progress"' in client.get(url, HTTP_HX_REQUEST="true").content.decode()
    run_next()
    response = client.get(url, HTTP_HX_REQUEST="true")
    assert response.status_code == 204 and response["HX-Refresh"] == "true"
    assert client.get(url)["Location"] == f"/station/{analysis.pk}/quality"


# ---- Every flag on the chart and in the table (acceptance) -----------------------------------


def file_flags(name: str) -> list[str]:
    qcfile = qc_review.read_qc_file(STRESS_QC / f"qc_stress_1961-2020_{name}.csv")
    return [qc_review.iso_date(values[0]) for _section, values in qcfile.rows]


def test_every_flag_of_the_stress_station_is_in_its_table(client, checked):
    """Every row of every file is on the screen (#174): each "look wrong" check in its
    table, each "worth a look" check in its groups' tables, page by page."""
    review = qc_review.review(checked.qc_job, checked.station_file)
    for check in review.checks:
        dates = file_flags(check.key)
        listed = [row.date for row in check.rows]
        if check.key == "duplicates":
            assert listed == list(dict.fromkeys(dates))  # one row per repeated date
        else:
            assert listed == dates, check.key
        # And on the pages of its tables, in the browser.
        shown = []
        for table in review.tables:
            if table.key != check.key:
                continue
            query = f"group={table.group}&" if table.group else ""
            for number in range(1, table.page(1).pages + 1):
                url = f"/station/{checked.pk}/quality/checks/{check.key}?{query}page={number}"
                html = client.get(url).content.decode()
                shown += re.findall(r'<tr data-date="([\d-]+)"', html)
        assert sorted(shown) == sorted(listed), check.key
    prcp = review.table("outliers", "prcp-high")
    assert prcp.count == 67 and prcp.page(1).pages == 2  # 50 a page


CHART_OF = {
    "tmaxmin": ("tmax", "tmin", "dtr"),
    "toolarge": None,  # the variables over the limits
    "duplicates": ("tmax", "tmin", "dtr", "prcp"),
    "tx_jumps": ("tmax",),
    "tn_jumps": ("tmin",),
    "tx_flatline": ("tmax",),
    "tn_flatline": ("tmin",),
}


def chart_flags(client, analysis, variable) -> set[tuple[str, str]]:
    import datetime as dt

    payload = client.get(f"/charts/station/{analysis.pk}/daily.json?variable={variable}").json()
    assert [s["key"] for s in payload["series"]] == [variable]
    start = dt.date.fromisoformat(payload["start"])
    return {
        ((start + dt.timedelta(days=day)).isoformat(), check)
        for day, v, check in payload["flags"]["points"]
    }


def test_every_flag_of_the_stress_station_is_on_its_chart(client, checked):
    flags = {v: chart_flags(client, checked, v) for v in qc_review.CHART_VARIABLES}
    for check, variables in CHART_OF.items():
        for date in file_flags(check):
            on = [v for v in qc_review.CHART_VARIABLES if (date, check) in flags[v]]
            if variables is None:
                assert on, (check, date)
            else:
                assert set(variables) <= set(on), (check, date, on)
    outliers = qc_review.read_qc_file(STRESS_QC / "qc_stress_1961-2020_outliers.csv")
    variable = {"Prec": "prcp", "TX": "tmax", "TN": "tmin", "DTR": "dtr"}
    for section, values in outliers.rows:
        date = qc_review.iso_date(values[0])
        assert (date, "outliers") in flags[variable[section.split()[0]]], (section, date)


def test_table_rows_point_at_the_chart_that_shows_them(checked):
    review = qc_review.review(checked.qc_job, checked.station_file)
    for check in review.checks:
        for row in check.rows:
            assert row.chart in qc_review.CHART_VARIABLES
    assert {r.chart for r in review.check("outliers").rows} == {"prcp", "tmax", "tmin", "dtr"}
    assert review.check("toolarge").rows[0].chart == "prcp"  # 200.1 mm


# ---- What the tables add -------------------------------------------------------------------


def test_jump_rows_show_both_days_and_the_change(checked):
    review = qc_review.review(checked.qc_job, checked.station_file)
    tx = review.check("tx_jumps").rows[0]
    assert tx.date == "1963-07-03"
    assert [c.text for c in tx.cells] == ["27.5", "50", "1963-07-04", "22.5"]
    tn = review.check("tn_jumps").rows[0]
    # The file's TN column holds the day's value (R's slip); the change is worked out.
    assert [c.text for c in tn.cells] == ["1.2", "-50", "1963-12-01", "51.2"]


def test_flatline_rows_give_the_run(checked):
    review = qc_review.review(checked.qc_job, checked.station_file)
    row = review.check("tn_flatline").rows[0]
    assert row.date == "1968-04-11"
    assert [c.text for c in row.cells] == ["0", "12", "1968-04-01 to 1968-04-12"]


def test_duplicate_rows_list_each_row_of_the_date(checked):
    review = qc_review.review(checked.qc_job, checked.station_file)
    row = next(r for r in review.check("duplicates").rows if r.date == "1980-01-20")
    assert row.cells[0].text == "3"
    assert row.cells[1].text.count(";") == 2


def test_outlier_rows_give_the_usual_range_of_the_month(checked):
    from climpact import qc
    from climpact.config import QCParams
    from climpact.io.station import merged_rows, read_station_file

    review = qc_review.review(checked.qc_job, checked.station_file)
    row = next(r for r in review.check("outliers").rows if r.chart == "tmax")
    rows = merged_rows(read_station_file(STRESS))
    month = rows["date"].dt.month == int(row.date[5:7])
    stats = qc.boxplot_stats(rows.loc[month, "tmax"].to_numpy(), QCParams().iqr_temp)
    assert row.cells[-1].text == f"{round(stats[0], 2):g} to {round(stats[4], 2):g}"
    strong = [c for c in row.cells if c.strong]
    assert len(strong) == 1 and strong[0].text == row.cells[2].text  # the TX value


def test_qc_file_reader_reads_sections_and_empty_messages(tmp_path):
    path = tmp_path / "x_tx_jumps.csv"
    path.write_text('"Description: ","d"\n"Station: ","x"\nDate,TX\n"NO LARGE TX JUMPS FOUND"\n')
    qcfile = qc_review.read_qc_file(path)
    assert qcfile.rows == [] and qcfile.empty_message == "NO LARGE TX JUMPS FOUND"
    assert qcfile.meta["Station"] == "x"
    outliers = qc_review.read_qc_file(STRESS_QC / "qc_stress_1961-2020_outliers.csv")
    sections = list(dict.fromkeys(s for s, _v in outliers.rows))
    assert sections[0] == "Prec up" and "DTR low" in sections


# ---- Missing data and the summary --------------------------------------------------------------


def test_missing_data_follows_nastatistics_and_the_climdex_rules(checked):
    review = qc_review.review(checked.qc_job, checked.station_file)
    nastat = qc_review.read_qc_file(STRESS_QC / "qc_stress_1961-2020_nastatistics.csv")
    assert len(review.years) == len(nastat.rows)
    for year, (_s, values) in zip(review.years, nastat.rows, strict=True):
        assert year.year == int(values[0])
        assert [year.days[k] for k in ("prcp", "tmax", "tmin")] == [int(v) for v in values[1:]]


def test_climdex_rules_for_a_year(tmp_path):
    text = "".join(
        f"2001 {m} {d} {'-99.9' if (m == 3 and d <= 4) else '1'} 20 10\n"
        for m in range(1, 13)
        for d in range(1, 29)
    )
    station = tmp_path / "s.txt"
    station.write_text(text)
    rows = qc_review.StationRows.read(station)
    nastat = qc_review.QCFile({}, ["Year", "Prec", "TX", "TN"], [("", ["2001", "4", "0", "0"])])
    (year,) = qc_review.missing_by_year(nastat, rows)
    # Days 29-31 of each month are absent: every month of 31 days misses 3 (allowed), but
    # March misses 4 more and February none.
    assert year.months["prcp"] == 1 and year.no_annual["prcp"]
    assert year.months["tmax"] == 0 and not year.no_annual["tmax"]


def years(n: int, short: int) -> list:
    """``n`` years, ``short`` of them too incomplete for annual values."""
    return [
        qc_review.YearMissing(1961 + i, {"prcp": 0}, {"prcp": 0}, {"prcp": i < short})
        for i in range(n)
    ]


def checks(**counts) -> list:
    """Checks with ``counts`` rows (by key; the others none)."""
    out = []
    for key, title, kind in qc_review.CHECKS:
        rows = [qc_review.Row("2001-01-01", [], "tmax")] * counts.get(key, 0)
        out.append(qc_review.Check(key, str(title), kind, "", [], [], rows, None, len(rows)))
    return out


def test_verdict_clean_data_is_ready_to_use():
    verdict = qc_review.verdict(checks(outliers=300, tx_jumps=5), years(60, 1), 65000)
    assert verdict.level == "ready" and verdict.title == "Ready to use"
    assert verdict.alert_kind == "success"
    # What may be real is counted, but never changes the level.
    assert verdict.worth == 305 and "305 values are unusual but may be real." in verdict.message
    assert verdict.facts[0] == "65,000 values checked"


def test_verdict_a_few_wrong_values_are_usable():
    verdict = qc_review.verdict(checks(tmaxmin=1, toolarge=4, outliers=395), years(80, 1), 87537)
    assert verdict.level == "usable" and verdict.title == "Usable. 5 values look wrong."
    assert verdict.alert_kind == "warning" and verdict.wrong == 5
    assert "5 look wrong (under 0.01%)" in verdict.facts
    assert "1 of 80 years too incomplete for annual values" in verdict.facts


def test_verdict_too_many_wrong_values_is_fix_the_file_first():
    limit = qc_review.VERDICT_LIMITS.wrong_share  # 0.1%
    assert limit == 0.001
    # 65 of 65,000 is 0.1% exactly: still usable; one more is red.
    assert qc_review.verdict(checks(toolarge=65), years(60, 0), 65000).level == "usable"
    verdict = qc_review.verdict(checks(toolarge=60, duplicates=6), years(60, 0), 65000)
    assert verdict.level == "fix" and verdict.title == "Fix the file first"
    assert verdict.too_many_wrong and not verdict.too_many_short
    assert verdict.alert_kind == "error"
    assert "66 values look wrong, 0.1% of the values checked." in verdict.message
    assert "use the data as it is" in verdict.message  # the user can always go on


def test_verdict_too_many_incomplete_years_is_fix_the_file_first():
    assert qc_review.VERDICT_LIMITS.short_years_share == 0.10
    assert qc_review.verdict(checks(), years(60, 6), 65000).level == "ready"  # 10% exactly
    verdict = qc_review.verdict(checks(), years(60, 7), 65000)
    assert verdict.level == "fix" and verdict.too_many_short and not verdict.too_many_wrong
    assert "7 of 60 years have too much missing data for annual values." in verdict.message


def test_verdict_limits_can_be_changed_in_one_place():
    strict = qc_review.VerdictLimits(wrong_share=0.0, short_years_share=0.0)
    assert qc_review.verdict(checks(tmaxmin=1), years(60, 0), 65000, strict).level == "fix"
    assert qc_review.verdict(checks(), years(60, 1), 65000, strict).level == "fix"


def test_stress_station_verdict_and_worklist(checked):
    review = qc_review.review(checked.qc_job, checked.station_file)
    # 10 + 6 + 5 = 21 of 65,720 values (0.03%), no year too incomplete: amber.
    assert review.verdict.level == "usable" and review.verdict.wrong == 21
    assert review.verdict.values == 65720 and review.verdict.short_years == 0
    assert [f.check.key for f in review.findings] == ["tmaxmin", "toolarge", "duplicates"]
    assert len(review.findings[0].findings) == qc_review.FINDINGS_SHOWN  # 10 shown
    assert not review.findings[0].more and not review.findings[1].more
    groups = [g.check.table_id for g in review.groups]
    assert groups[:2] == ["outliers-prcp-high", "tx_jumps"]  # the largest first
    assert sum(g.count for g in review.groups) == review.verdict.worth == 105
    assert review.quiet == []
    dtr = next(g for g in review.groups if g.check.group == "dtr-high")
    assert dtr.title == "Wide daily range (DTR)" and sum(dtr.by_month) == 8
    months = [r.date[5:7] for r in dtr.check.rows]
    assert months == sorted(months)  # by calendar month


def test_finding_text_and_its_days(checked):
    review = qc_review.review(checked.qc_job, checked.station_file)
    toolarge = review.findings[1]
    first = toolarge.findings[0]
    assert first.date == "1963-07-02" and first.text == "Rain 200.1 mm, over the 200 mm limit"
    assert len(first.days) == 2 * qc_review.WINDOW_DAYS + 1
    assert [d["this"] for d in first.days].index(True) == qc_review.WINDOW_DAYS
    assert first.spark["ring"] is not None and first.spark["lines"][0]["variable"] == "prcp"
    texts = [f.text for f in review.findings[0].findings]
    assert any("equals the maximum" in t for t in texts)
    assert any("is above the maximum" in t for t in texts)
    assert review.findings[2].findings[0].text.startswith("Given on ")


def test_months_that_hold_most_rows():
    assert qc_review._mostly([7, 4, 1, 0, 0, 0, 0, 0, 0, 0, 0, 2]) == "Mostly in January"
    assert qc_review._mostly([4, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]) == "All in January"
    assert qc_review._mostly([1] * 12) == ""  # spread over the year
    assert qc_review._mostly([2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]) == ""  # too few to say


# ---- The page ----------------------------------------------------------------------------------


def test_results_page(client, checked):
    page = client.get(f"/station/{checked.pk}/quality").content.decode()
    assert "Usable. 21 values look wrong." in page
    # One decision: "Use this data" is the one primary button; "Upload a corrected file"
    # opens the file picker (no drop zone), keeping the re-upload behind it.
    verdict = page[
        page.index('class="alert alert--warning qc-verdict"') : page.index('id="look-wrong"')
    ]
    assert f'action="/station/{checked.pk}/quality/continue"' in verdict
    assert verdict.count('class="button"') == 1 and "<span>Use this data</span>" in verdict
    assert f'action="/station/{checked.pk}/quality/file"' in verdict
    assert "data-file-button" in verdict and "Upload a corrected file" in verdict
    assert 'id="id_station_file_helptext"' in verdict  # what choosing a file does
    assert "data-dropzone" not in page
    # The worklist, then everything else under Details.
    order = ["look-wrong", "worth-a-look", "missing-data", "details"]
    assert [page.index(f'id="{i}"') for i in order] == sorted(
        page.index(f'id="{i}"') for i in order
    )
    assert page.count("data-qc-finding") == 10 + 6 + 5
    for name in QC_DEFAULTS:
        assert f'data-help-topic="qcparam.{name}"' in page
    for variable in qc_review.CHART_VARIABLES:
        src = f"/charts/station/{checked.pk}/daily.json?variable={variable}"
        assert f'data-chart-src="{src}"' in page
        assert page.index(src) > page.index('id="details"')
    assert "js/qc.js" in page and "js/charts.js" in page
    assert 'id="distributions"' in page and 'id="thresholds"' in page
    # The files are in Files, not here (#176): one link under Details, no download.
    job = checked.qc_job
    assert f"/jobs/{job.pk}/files/" not in page and " download>" not in page
    files_link = f'href="/station/{checked.pk}/downloads#quality-files"'
    assert page.count(files_link) == 1 and page.index(files_link) > page.index('id="details"')
    files = client.get(f"/station/{checked.pk}/downloads").content.decode()
    for name in job.result["files"] + [job.result["zip"]]:
        assert f"/jobs/{job.pk}/files/{name}" in files
        assert client.get(f"/jobs/{job.pk}/files/{name}").status_code == 200


def test_checks_that_found_nothing_are_one_line(client, checked, monkeypatch):
    review = qc_review.review(checked.qc_job, checked.station_file)
    for check in review.checks:
        check.rows, check.count = [], 0
    review.findings, review.groups = [], []
    review.verdict = qc_review.verdict(review.checks, [], review.verdict.values)
    monkeypatch.setattr(qc_review, "review", lambda job, path: review)
    page = client.get(f"/station/{checked.pk}/quality").content.decode()
    assert "8 checks found nothing" in page and 'id="nothing-found"' in page
    assert 'id="look-wrong"' not in page and 'id="worth-a-look"' not in page
    assert "Ready to use" in page
    # Green: "Use this data" alone; the upload button is under Details.
    assert "Upload a corrected file" in page.split('id="details"')[1]
    assert "Upload a corrected file" not in page.split('id="details"')[0]


def test_pages_without_javascript(client, checked):
    """The pager's links carry the page of each table in the query string."""
    page = client.get(f"/station/{checked.pk}/quality?outliers-prcp-high_page=2").content.decode()
    section = page[page.index('id="qc-table-outliers-prcp-high"') :]
    assert "rows 51 to 67 of 67" in section
    assert 'href="?outliers-prcp-high_page=1#check-outliers-prcp-high"' in section


def test_table_page_of_a_date(client, checked):
    review = qc_review.review(checked.qc_job, checked.station_file)
    row = review.table("outliers", "prcp-high").rows[60]
    url = f"/station/{checked.pk}/quality/checks/outliers?group=prcp-high&date={row.date}"
    html = client.get(url).content.decode()
    assert "rows 51 to 67 of 67" in html
    selected = f'<tr data-date="{row.date}" tabindex="-1" class="is-selected" aria-current="true">'
    assert selected in html
    assert client.get(f"/station/{checked.pk}/quality/checks/nope").status_code == 404
    assert client.get(f"/station/{checked.pk}/quality/checks/outliers").status_code == 404
    assert (
        client.get(f"/station/{checked.pk}/quality/checks/outliers?group=nope").status_code == 404
    )


def test_new_thresholds_run_the_checks_again(client, checked):
    data = {**{k: str(v) for k, v in QC_DEFAULTS.items()}, "jump": "15"}
    response = client.post(f"/station/{checked.pk}/quality/run", data)
    assert response["Location"] == f"/station/{checked.pk}/quality#qc-status"
    checked.refresh_from_db()
    assert checked.qc_params["jump"] == 15.0 and checked.qc_job.params["qc"]["jump"] == 15.0
    job = run_next()
    review = qc_review.review(job, checked.station_file)
    assert review.check("tx_jumps").count > 10
    # The chart flags with the thresholds of the latest check.
    flags = chart_flags(client, checked, "tmax")
    listed = {r.date for r in review.check("tx_jumps").rows}
    assert {d for d, c in flags if c == "tx_jumps"} == listed


def test_bad_thresholds_are_shown_on_the_page(client, checked):
    data = {**{k: str(v) for k, v in QC_DEFAULTS.items()}, "temp_max": "99"}
    response = client.post(f"/station/{checked.pk}/quality/run", data)
    assert response.status_code == 200
    assert "Enter a number from 0 to 60." in response.content.decode()
    assert Job.objects.count() == 2  # the checks and the speculative run, nothing more


def test_reupload_reruns_the_checks_and_keeps_the_details(client, checked):
    """Acceptance: re-uploading a fixed file reruns QC without re-entering metadata."""
    data = {**{k: str(v) for k, v in QC_DEFAULTS.items()}, "iqr_temp": "4"}
    client.post(f"/station/{checked.pk}/quality/run", data)
    run_next()
    fixed = STRESS.read_text().replace("1963\t7\t2\t200.1\t", "1963\t7\t2\t20.1\t")
    assert fixed != STRESS.read_text()
    response = client.post(
        f"/station/{checked.pk}/quality/file",
        {"station_file": SimpleUploadedFile("fixed.txt", fixed.encode())},
    )
    assert response["Location"] == f"/station/{checked.pk}/quality#qc-status"
    checked.refresh_from_db()
    assert checked.station_name == "qc_stress_1961-2020" and checked.latitude == 52.38
    assert checked.qc_params["iqr_temp"] == 4.0
    assert checked.step == Step.QC and checked.file_name == "fixed.txt"
    job = run_next()
    assert job.params["qc"]["iqr_temp"] == 4.0
    review = qc_review.review(job, checked.station_file)
    assert "1963-07-02" not in [r.date for r in review.check("toolarge").rows]


def test_reupload_of_a_bad_file_shows_its_problems(client, checked):
    response = client.post(
        f"/station/{checked.pk}/quality/file",
        {"station_file": SimpleUploadedFile("bad.txt", b"not a station file\n")},
    )
    assert response.status_code == 200
    page = response.content.decode()
    assert "file-problems" in page
    checked.refresh_from_db()  # the analysis and its results are unchanged
    assert checked.file_name == STRESS.name and checked.qc_job.status == Status.SUCCEEDED


def test_use_this_data_opens_the_results(client, checked):
    """#178: "Use this data" goes straight to the results of the run queued with the
    checks, which becomes the user's own; no settings page on the way."""
    speculative = checked.indices_job
    response = client.post(f"/station/{checked.pk}/quality/continue")
    assert response["Location"] == f"/station/{checked.pk}/results"
    checked.refresh_from_db()
    assert checked.step == Step.RESULTS and checked.indices_job == speculative
    job = Job.objects.get(kind="station")
    assert not job.is_speculative and job.params["qc"] == QC_DEFAULTS
    page = client.get(f"/station/{checked.pk}/results").content.decode()
    assert "Calculating indices" in page and "results/progress" in page


def test_continue_needs_finished_checks(client):
    analysis = start(client)
    response = client.post(f"/station/{analysis.pk}/quality/continue")
    assert response["Location"] == f"/station/{analysis.pk}/quality"
    # The results are not shown before "Use this data" (#178).
    assert client.get(f"/station/{analysis.pk}/results")["Location"].endswith("/quality")


def test_other_sessions_get_404(client, checked):
    from django.test import Client

    other = Client()
    for url in ("quality", "quality/progress", "quality/checks/outliers"):
        assert other.get(f"/station/{checked.pk}/{url}").status_code == 404
    for url in ("quality/run", "quality/file", "quality/continue"):
        assert other.post(f"/station/{checked.pk}/{url}").status_code == 404


def test_failed_checks_say_so(client):
    analysis = start(client)
    job = analysis.qc_job
    job.status, job.error = Status.FAILED, "Something went wrong."
    job.save()
    page = client.get(f"/station/{analysis.pk}/quality").content.decode()
    assert "The checks could not be run." in page and "Something went wrong." in page
    assert f'action="/station/{analysis.pk}/quality/run"' in page


# ---- Distribution plots ------------------------------------------------------------------------


def test_monthly_boxes_match_the_outliers(checked):
    review = qc_review.review(checked.qc_job, checked.station_file)
    plots = {p["key"]: p for p in qc_plots.monthly_boxes(review.rows, review.params)}
    assert set(plots) == {"prcp", "tmax", "tmin", "dtr"}
    outliers = qc_review.read_qc_file(STRESS_QC / "qc_stress_1961-2020_outliers.csv")
    count = {"Prec": 0, "TX": 0, "TN": 0, "DTR": 0}
    for section, _values in outliers.rows:
        count[section.split()[0]] += 1
    names = {"Prec": "prcp", "TX": "tmax", "TN": "tmin", "DTR": "dtr"}
    for label, key in names.items():
        assert sum(r["outliers"] for r in plots[key]["rows"]) == count[label], key
        assert plots[key]["svg"].startswith("<svg")


def test_decimals_and_histogram(tmp_path):
    station = tmp_path / "s.txt"
    station.write_text(
        "2001 1 1 1.5 20.0 10.5\n2001 1 2 0 20.5 -1.3\n"
        "2001 1 3 45 21.0 10.0\n2001 1 4 3 -99.9 9.9\n"
    )
    rows = qc_review.StationRows.read(station)
    dec = {p["key"]: p for p in qc_plots.decimals(rows)}
    assert [r["count"] for r in dec["tmax"]["rows"]][:6] == [2, 0, 0, 0, 0, 1]
    assert dec["prcp"]["total"] == 3  # non-zero only
    assert dec["tmin"]["rows"][7]["count"] == 1  # -1.3 %% 1 is 0.7, as in R
    hist = qc_plots.precipitation_histogram(rows)
    assert hist["total"] == 3
    assert [r["count"] for r in hist["rows"]][:2] == [1, 1] and hist["rows"][-1]["count"] == 1


def test_annual_boxes_use_rs_ranges(checked):
    review = qc_review.review(checked.qc_job, checked.station_file)
    plots = qc_plots.annual_boxes(review.rows)
    assert len(plots[0]["rows"]) == 60  # 1961-2020


def test_chart_payload_rejects_unknown_variables(client, checked):
    assert client.get(f"/charts/station/{checked.pk}/daily.json?variable=x").status_code == 404
    dtr = client.get(f"/charts/station/{checked.pk}/daily.json?variable=dtr").json()
    assert dtr["series"][0]["token"] == "--chart-7" and list(dtr["panels"]) == ["dtr"]
    both = client.get(f"/charts/station/{checked.pk}/daily.json").json()
    assert [s["key"] for s in both["series"]] == ["tmax", "tmin", "prcp"]
    assert json.dumps(both["flags"]).count("dtr") == 0


def test_job_folder_cleanup_does_not_break_the_page(client, checked):
    shutil.rmtree(checked.qc_job.output_dir)
    assert client.get(f"/station/{checked.pk}/quality").status_code == 200


def test_every_section_has_its_help_and_no_field_has_a_link(client, checked):
    """#177: one ⓘ per section of the Quality page opens its help in the drawer; the
    worklist groups and the thresholds have no help link of their own."""
    page = client.get(f"/station/{checked.pk}/quality").content.decode()
    assert re.findall(r'href="/help/sections/([^/"?]+)/', page) == [
        "quality.verdict",
        "quality.wrong",
        "quality.worth",
        "quality.missing",
        "quality.daily",
        "quality.distributions",
        "quality.thresholds",
    ]
    assert "help-topic--compact" not in page
