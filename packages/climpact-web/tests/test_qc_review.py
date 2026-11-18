"""Step 2, Check quality (#77): the thresholds, the qc job, the review of its files, the
charts' flags, the tables and their pages, re-uploading a corrected file and going on to
step 3."""

import csv
import io
import json
import re
import shutil
from dataclasses import asdict, fields
from pathlib import Path
from urllib.parse import quote

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from climpact_web.jobs.models import Job, Status
from climpact_web.jobs.registry import RUNNERS
from climpact_web.jobs.worker import claim, run_job
from climpact_web.stations import qc_plots, qc_review
from climpact_web.stations.forms import QC_DEFAULTS, QCParamsForm
from climpact_web.stations.models import Station, Step

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


def start(client, path=STRESS, name="qc_stress_1961-2020") -> Station:
    """Step 1 with the file, then "Continue": the checks are queued at once."""
    response = client.post(
        "/station/new",
        {"station_file": SimpleUploadedFile(path.name, path.read_bytes()), "intent": "read"},
    )
    load = response["Location"]
    response = client.post(load, {"station_name": name, **META})
    analysis = Station.objects.get()
    assert response["Location"] == f"{analysis.url()}quality"
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
    page = client.get(f"{analysis.url()}quality").content.decode()
    assert 'id="qc-progress"' in page and f"{analysis.url()}quality/progress" in page
    # No checks' charts until results; the daily series of "Your data" (#198) is there.
    assert 'id="daily-chart"' in page and 'id="qc-chart' not in page
    # The indices are queued too, with the default settings, behind the checks (#178).
    run = analysis.indices_job
    assert run.kind == "station" and run.is_speculative and run.params["qc"] == QC_DEFAULTS
    assert run.created_at >= job.created_at
    # Visiting step 1 and continuing again with nothing changed does not queue again.
    client.post(f"{analysis.url()}setup", {"station_name": "qc_stress_1961-2020", **META})
    assert Job.objects.count() == 2


def without_sheets(page: str) -> str:
    """The page without the Inputs panel's sheets (#198, #199): what is on the page itself."""
    return re.sub(r"<dialog.*?</dialog>", "", page, flags=re.S)


def test_while_the_checks_run_the_thresholds_are_in_the_inputs_panel(client):
    """#114, #199: the checks start by themselves, so the page says they are running. The
    thresholds are not on the page: the Inputs panel's sheet has them."""
    analysis = start(client)
    page = client.get(f"{analysis.url()}quality").content.decode()
    assert "Running the quality checks…" in page and "Waiting to run" not in page
    assert 'name="iqr_temp"' in page and 'name="iqr_temp"' not in without_sheets(page)
    assert "<form" not in without_sheets(page).split('id="your-data"')[0]
    # Before any check (no job) the page offers to run them: the thresholds sheet does.
    analysis.qc_job = None
    analysis.save()
    page = client.get(f"{analysis.url()}quality").content.decode()
    assert "The checks have not run on this file yet." in page
    sheet = f"{analysis.url()}inputs/thresholds?next={quote(analysis.url(), safe='')}quality"
    assert f'href="{sheet}" data-sheet-open="sheet-thresholds"' in page
    assert "<span>Run the checks</span>" in page


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
    url = f"{analysis.url()}quality/progress"
    assert 'id="qc-progress"' in client.get(url, HTTP_HX_REQUEST="true").content.decode()
    run_next()
    response = client.get(url, HTTP_HX_REQUEST="true")
    assert response.status_code == 204 and response["HX-Refresh"] == "true"
    assert client.get(url)["Location"] == f"{analysis.url()}quality"


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
                url = f"{checked.url()}quality/checks/{check.key}?{query}page={number}"
                html = client.get(url).content.decode()
                shown += re.findall(r'<tr data-date="([\d-]+)"', html)
        assert sorted(shown) == sorted(listed), check.key
    prcp = review.table("outliers", "prcp-high")
    assert prcp.count == 67 and prcp.page(1).pages == 6  # 12 a page


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
    # Minus is U+2212 on the screen (#226).
    assert [c.text for c in tn.cells] == ["1.2", "\u221250", "1963-12-01", "51.2"]


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
    assert verdict.level == "ready" and verdict.title == "Ready to use."
    assert verdict.alert_kind == "success" and verdict.message == "Nothing looks wrong."
    # What may be real is counted, but never changes the level.
    assert verdict.worth == 305 and "305 worth a look" in verdict.facts
    assert verdict.facts[0] == "65,000 values checked"


def test_verdict_a_few_wrong_values_are_usable():
    verdict = qc_review.verdict(checks(tmaxmin=1, toolarge=4, outliers=395), years(80, 1), 87537)
    assert verdict.level == "usable" and verdict.title == "Usable."
    assert verdict.message == "5 values look wrong; the indices can run with them as they are."
    assert verdict.alert_kind == "warning" and verdict.wrong == 5
    assert "5 look wrong (under 0.01%)" in verdict.facts
    assert "1 of 80 years too incomplete for annual values" in verdict.facts


def test_verdict_too_many_wrong_values_is_fix_the_file_first():
    limit = qc_review.VERDICT_LIMITS.wrong_share  # 0.1%
    assert limit == 0.001
    # 65 of 65,000 is 0.1% exactly: still usable; one more is red.
    assert qc_review.verdict(checks(toolarge=65), years(60, 0), 65000).level == "usable"
    verdict = qc_review.verdict(checks(toolarge=60, duplicates=6), years(60, 0), 65000)
    assert verdict.level == "fix" and verdict.title == "Fix the file first."
    assert verdict.too_many_wrong and not verdict.too_many_short
    assert verdict.alert_kind == "error"
    assert verdict.message == "66 values look wrong, 0.1% of the values checked."


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
    # The counts on one line (#235): missing values against all of them.
    assert review.verdict.missing == 25
    assert review.verdict.facts == [
        "65,720 values checked",
        "21 look wrong (0.03%)",
        "105 worth a look",
        "25 missing (0.04%)",
    ]
    # The rail (#264): each "look wrong" check with its variables and count.
    assert [(g.id, g.title, g.variable, g.count) for g in review.wrong] == [
        ("tmaxmin", "TN ≥ TX", "TN", 10),
        ("toolarge", "Out of range", "PR TX TN", 6),
        ("duplicates", "Repeated date", "all rows", 5),
    ]
    groups = [g.check.table_id for g in review.groups]
    assert groups[:2] == ["outliers-prcp-high", "tx_jumps"]  # the largest first
    assert sum(g.count for g in review.groups) == review.verdict.worth == 105
    assert review.quiet == []
    dtr = next(g for g in review.groups if g.check.group == "dtr-high")
    assert dtr.title == "Wide daily range" and dtr.variable == "DTR" and sum(dtr.by_month) == 8
    assert dtr.mostly == "Mostly December"
    titles = {g.check.table_id: (g.title, g.rail_title) for g in review.groups}
    assert titles["tx_jumps"] == ("Large day-to-day change ≥ 20\u00a0°C", "Large day-to-day change")
    assert titles["tn_flatline"] == ("Same TN 6+ days", "")  # more than 5 equal values
    # The bars by month (#235, #264): twelve, an empty month a thin mark.
    bars = dtr.bars
    assert len(bars) == 12 and [b["x"] for b in bars] == [5 * m for m in range(12)]
    assert bars[11]["h"] == qc_review.BARS_H and bars[1]["h"] == 0.6
    months = [r.date[5:7] for r in dtr.check.rows]
    assert months == sorted(months)  # by calendar month
    # Each check's sentence: what it means, then what to look at first.
    rain = review.table("outliers", "prcp-high")
    assert review.group_of(rain).lede.startswith("More than 5 interquartile ranges above")
    assert "look first at the largest" in review.group_of(rain).lede


def test_each_check_has_its_own_columns_largest_first(checked):
    """#264: a check's values table has only the columns it needs, 12 rows a page,
    largest first (how far beyond what the check expects), or by date."""
    review = qc_review.review(checked.qc_job, checked.station_file)
    nb = "\u00a0"
    columns = {g.id: [c for c, _n in g.check.value_columns] for g in review.wrong + review.groups}
    assert columns["outliers-prcp-high"] == [f"PR{nb}mm", f"Month's limit{nb}mm", f"Over by{nb}mm"]
    assert columns["tmaxmin"] == [f"TN{nb}°C", f"TX{nb}°C", f"TN − TX{nb}°C"]
    assert columns["toolarge"] == [f"PR{nb}mm", f"TX{nb}°C", f"TN{nb}°C"]
    assert columns["duplicates"] == ["Rows", "Lines in the file"]
    assert columns["outliers-dtr-high"] == [f"DTR{nb}°C", f"Usual range{nb}°C", f"Beyond by{nb}°C"]
    assert columns["tx_jumps"] == [f"TX{nb}°C", f"Next day{nb}°C", f"Change{nb}°C"]
    assert columns["tn_flatline"] == [f"TN{nb}°C", "Days in a row", "From"]
    for table in review.tables:
        assert all(len(r.values) == len(table.value_columns) for r in table.rows), table.table_id
    rain = review.table("outliers", "prcp-high")
    page = rain.page(1)
    assert len(page.rows) == qc_review.PAGE_SIZE == 12 and page.pages == 6
    sizes = [r.size for r in rain.sorted_rows()]
    assert sizes == sorted(sizes, reverse=True)
    assert [c.text for c in page.rows[0].values] == ["350.5", "21.9", "+328.6"]
    assert page.rows[0].values[0].strong
    dates = [r.date for r in rain.page(1, "date").rows]
    assert dates == sorted(dates) and rain.page(1, "nope").sort == "size"
    assert rain.page_of(rain.sorted_rows()[30].date) == 3
    tmaxmin = review.table("tmaxmin")
    assert [c.text for c in tmaxmin.page(1).rows[0].values] == ["21.3", "9.2", "+12.1"]
    assert [c.text for c in tmaxmin.page(1).rows[-1].values][2] == "0.0"  # TN equals TX
    duplicates = review.table("duplicates")
    assert duplicates.page(1).rows[0].values[0].text == "3"  # the most rows first
    flat = review.table("tn_flatline").row_of("1968-04-11")
    assert [c.text for c in flat.values] == ["0", "12", "1968-04-01"]
    jump = review.table("tx_jumps").row_of("1963-07-03")
    assert [c.text for c in jump.values] == ["27.5", "50", "22.5"]


def test_check_charts_have_axes(checked):
    """#264: When (each value against its date, the selected one ringed) and By calendar
    month (twelve bars), each with three value ticks."""
    review = qc_review.review(checked.qc_job, checked.station_file)
    rain = review.table("outliers", "prcp-high")
    group, top = review.group_of(rain), rain.sorted_rows()[0]
    when = review.when(group, top)
    assert when["dots"].count("M") == 67
    assert [t["text"] for t in when["y_ticks"]] == ["400", "200", "0"]
    years = [(t["text"], t["anchor"]) for t in when["x_ticks"]]
    assert years[0] == (1961, "start") and years[-1] == (2020, "end") and len(years) == 7
    assert (when["first"], when["last"]) == (1961, 2020)
    assert qc_review.WHEN_LEFT < when["ring"]["x"] < qc_review.WHEN_RIGHT
    months = qc_review.months_chart(group.by_month)
    assert len(months["bars"]) == 12 and months["bars"][0]["name"] == "Jan"
    assert [t["text"] for t in months["y_ticks"]] == ["10", "5", "0"]
    assert qc_review._nice(0, 350.5, zero=True) == (0, 400, 200)
    assert qc_review._nice(-9.6, 3.7) == (-10, 10, 0)
    # Temperatures are not drawn from zero.
    high = next(g for g in review.groups if g.check.group == "tmax-high")
    assert not high.zero and high.y_label == "TX\u00a0°C"


def test_selected_value_text_and_its_days(checked):
    """#264: a check's selected value in a sentence (codes first, a no-break space before
    each unit), the 7 days around it as a chart and a table, and its lines in the file."""
    review = qc_review.review(checked.qc_job, checked.station_file)
    toolarge = review.check("toolarge")
    first = review.value(toolarge, toolarge.rows[0])
    assert first.date == "1963-07-02"
    assert first.text == "PR 200.1\u00a0mm, over the 200\u00a0mm limit"
    low = review.value(toolarge, toolarge.rows[1])
    assert low.text == "PR \u22120.1\u00a0mm, below 0\u00a0mm"
    assert len(first.days) == 2 * qc_review.WINDOW_DAYS + 1 == 7
    assert [d["this"] for d in first.days].index(True) == qc_review.WINDOW_DAYS
    # The days around it to one decimal.
    assert all(c.missing or "." in c.text for d in first.days for c in d["cells"])
    # Rain: a bar a day, the limit dashed, three values and three dates.
    chart = first.chart
    assert len(chart["bars"]) == 7 and [b["this"] for b in chart["bars"]].count(True) == 1
    assert chart["limit_y"] is not None and chart["limit_text"] == "200.0\u00a0mm"
    assert len(chart["y_ticks"]) == 3
    assert [t["text"] for t in chart["x_ticks"]] == ["06-29", "07-02", "07-05"]
    assert first.legend == [{"variable": "prcp", "label": "PR\u00a0mm"}]
    assert first.chart_label.endswith("with the limit of 200.0\u00a0mm")
    # Its line in the file (the stress file has no header: line = day of the record).
    assert first.lines and first.lines_text == f"Line {first.lines[0]} in the file"
    tmaxmin = review.check("tmaxmin")
    value = review.value(tmaxmin, tmaxmin.rows[0])
    assert value.text == "TN 9.5\u00a0°C is above TX 8.2\u00a0°C"
    assert [line["variable"] for line in value.chart["lines"]] == ["tmax", "tmin"]
    assert value.chart["ring"] is not None
    texts = [review.value(tmaxmin, r).text for r in tmaxmin.rows]
    assert any(t.startswith("TN 7.4\u00a0°C equals TX") for t in texts)
    # The check's other values among the days are marked.
    assert [d["date"] for d in value.days if d["flagged"]] == [
        "1962-04-10",
        "1962-04-11",
        "1962-04-12",
    ]
    duplicates = review.check("duplicates")
    duplicate = review.value(duplicates, duplicates.rows[0])
    assert duplicate.text.startswith("Given on ") and len(duplicate.lines) == 2
    assert [r.split(":")[0] for r in duplicate.rows_listed] == [
        f"Line {n}" for n in duplicate.lines
    ]
    rain = review.table("outliers", "prcp-high")
    value = review.value(rain, rain.sorted_rows()[0])
    assert value.text == "PR 350.5\u00a0mm, 328.6\u00a0mm over the limit for December"
    jumps = review.check("tx_jumps")
    value = review.value(jumps, jumps.row_of("1963-07-03"))
    assert value.text == ("TX 27.5\u00a0°C, then 50\u00a0°C the next day: a change of 22.5\u00a0°C")
    flat = review.check("tn_flatline")
    value = review.value(flat, flat.row_of("1968-04-11"))
    assert value.text == "TN 0\u00a0°C on 12 days in a row, from 1968-04-01"
    assert review.value(flat, None) is None


def test_months_that_hold_most_rows():
    assert qc_review._mostly([7, 4, 1, 0, 0, 0, 0, 0, 0, 0, 0, 2]) == "Mostly January"
    assert qc_review._mostly([4, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]) == "All in January"
    assert qc_review._mostly([1] * 12) == "All year"  # spread over the year
    assert qc_review._mostly([1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0]) == "Mostly January and February"
    assert qc_review._mostly([2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]) == ""  # too few to say


# ---- The page ----------------------------------------------------------------------------------


def test_results_page(client, checked):
    page = client.get(f"{checked.url()}quality").content.decode()
    # The verdict strip (#235): the level in bold, one sentence, the counts on one line.
    assert "<b>Usable.</b> 21 values look wrong; the indices can run with them as they are." in page
    assert_tab_shows_verdict(page, "usable", "Usable", "warning", "21")
    # One decision (#202): "Go to indices" is the one primary button, after "Flagged
    # values (CSV)" and "Replace file", which opens the Inputs panel's File sheet (#199),
    # so the drop zone is only there.
    verdict = verdict_of(page)
    assert "verdict-strip--usable" in verdict and "65,720 values checked" in verdict
    assert f'action="{checked.url()}quality/continue"' in verdict
    assert verdict.count('class="button button--sm"') == 1
    assert "<span>Go to indices</span>" in verdict
    file_sheet = f"{checked.url()}inputs/file?next={quote(checked.url(), safe='')}quality"
    assert f'<a href="{file_sheet}" data-sheet-open="sheet-file"' in verdict
    assert "<span>Replace file</span>" in verdict
    flagged = f'href="{checked.url()}quality/flagged.csv"'
    assert flagged in verdict and "<span>Flagged values (CSV)</span>" in verdict
    assert (
        verdict.index("Flagged values")
        < verdict.index("Replace file")
        < verdict.index("Go to indices")
    )
    assert "data-dropzone" not in without_sheets(page)
    # Quality's provenance line names the file the checks read (#235).
    provenance = page.split('class="context-bar__provenance"')[1].split("</p>")[0]
    assert "21,915 days · PR TX TN" in provenance and checked.file_name in provenance
    assert "base 1971" not in provenance
    # "Edit inputs" at its end opens the Inputs sheet (#264, as on the Indices, #263), so
    # the rail and the detail have the width: no Inputs panel beside the section.
    assert '<a class="context-bar__edit" href="#inputs-title" data-sheet-open="sheet-inputs"' in (
        provenance
    )
    assert "station-page--inputs-bar" in page
    # No forms on the page but the decision and "Delete" (#199): the thresholds and the
    # file are changed in the Inputs panel's sheets.
    actions = re.findall(r'<form[^>]* action="([^"]+)"', without_sheets(page))
    assert actions == [f"{checked.url()}quality/continue", f"{checked.url()}delete"]
    # The verdict, the coverage and its table, the worklist and its detail pane, then the
    # charts and distributions (#235). "Your data" is only there while the checks run.
    order = ["qc-verdict-title", "coverage-title", "missing-data", "qc-review", "look-wrong",
             "worth-a-look", "qc-detail", "details"]  # fmt: skip
    assert [page.index(f'id="{i}"') for i in order] == sorted(
        page.index(f'id="{i}"') for i in order
    )
    assert 'class="data-chip"' not in page  # "Your data"'s chips
    items = len(qc_review.review(checked.qc_job, checked.station_file).items)
    assert page.count("data-qc-item=") == page.count("data-qc-detail=") == items == 3 + 11
    for name in QC_DEFAULTS:
        assert f'data-help-topic="qcparam.{name}"' in page
    for variable in qc_review.CHART_VARIABLES:
        src = f"/charts/station/{checked.pk}/daily.json?variable={variable}"
        assert f'data-chart-src="{src}"' in page
        assert page.index(src) > page.index('id="details"')
    assert "js/qc.js" in page and "js/charts.js" in page
    assert 'id="distributions"' in page and 'id="thresholds"' in page
    # Details says which thresholds the checks used, and opens their sheet.
    thresholds = without_sheets(page).split('id="thresholds"')[1].split("</p>")[0]
    assert "The checks use R's default thresholds." in thresholds
    assert 'data-sheet-open="sheet-thresholds"' in thresholds and "<input" not in thresholds
    # The files are in Files, not here (#176): one link under Details, no download.
    job = checked.qc_job
    assert f"/jobs/{job.pk}/files/" not in page and " download>" not in page
    files_link = f'href="{checked.url()}downloads#quality-files"'
    assert page.count(files_link) == 1 and page.index(files_link) > page.index('id="details"')
    files = client.get(f"{checked.url()}downloads").content.decode()
    for name in job.result["files"] + [job.result["zip"]]:
        assert f"/jobs/{job.pk}/files/{name}" in files
        assert client.get(f"/jobs/{job.pk}/files/{name}").status_code == 200


def verdict_of(page: str) -> str:
    start = page.index('class="verdict-strip ')
    return page[start : page.index("</section>", start)]


def quality_tab(page: str) -> str:
    """Quality's tab in the context bar (#222)."""
    start = page.index('data-tab="quality"')
    return page[start : page.index("</li>", start)]


def assert_tab_shows_verdict(page: str, level: str, word: str, icon: str, count: str):
    """The tab says what the verdict band says (#222): its word, its icon and its tint,
    with the count of values that look wrong."""
    tab = quality_tab(page)
    assert f'data-state="{level}"' in tab and f"status-dot--{level}" in tab
    assert f"icons.svg#{icon}" in tab and f'<span class="max-sm:sr-only">{word}</span>' in tab
    if count:
        assert f'<span class="max-sm:hidden" aria-hidden="true">· {count}</span>' in tab
        assert f'<span class="sr-only">, {count} values look wrong</span>' in tab
    else:
        assert "·" not in tab and "look wrong" not in tab


def details_shown(page: str) -> list[str]:
    """The ids of the details not hidden (#202): one."""
    return re.findall(r'data-qc-detail="([^"]+)" aria-labelledby="[^"]+">', page)


def selected_rows(page: str) -> list[str]:
    return re.findall(r'data-qc-item="([^"]+)" aria-current="true"', page)


def detail_of(page: str, item_id: str) -> str:
    """A check's detail in the page, up to the next one."""
    start = page.index(f'data-qc-detail="{item_id}"')
    end = page.find("data-qc-detail=", start + 20)
    return page[start : end if end > 0 else len(page)]


def test_every_check_is_in_the_rail(client, checked):
    """#264: each "look wrong" check, then each "worth a look" group, is a row of the
    rail, a link to its detail (?show=), which is in the page, hidden unless selected;
    the first is selected by default. Every value is in one of their tables."""
    review = qc_review.review(checked.qc_job, checked.station_file)
    items = review.items
    assert [i.id for i in items[:3]] == ["tmaxmin", "toolarge", "duplicates"]
    assert [i.wrong for i in items] == [True] * 3 + [False] * len(review.groups)
    assert len({i.id for i in items}) == len(items) == 3 + 11
    assert sum(i.group.count for i in items) == 21 + 105
    page = client.get(f"{checked.url()}quality").content.decode()
    first = items[0]
    assert details_shown(page) == [first.id] and selected_rows(page) == [first.id]
    for item in items:
        assert f'href="?show={item.id}#{item.anchor}" data-qc-item="{item.id}"' in page
        assert f'id="{item.anchor}" data-qc-detail="{item.id}"' in page
    assert review.item("nope").id == items[0].id  # unknown: the first


def test_selecting_without_javascript(client, checked):
    """#202, #264: ?show=<id> shows that check's detail and marks it in the rail; its
    largest value is selected, or the one ?<id>_value= names; a group's pager keeps
    the selection."""
    url = f"{checked.url()}quality"
    page = client.get(f"{url}?show=tmaxmin").content.decode()
    assert details_shown(page) == ["tmaxmin"] and selected_rows(page) == ["tmaxmin"]
    detail = detail_of(page, "tmaxmin")
    assert "Look wrong · TN · 10 rows" in detail and "<span>TN ≥ TX</span>" not in detail
    assert "TN 21.3\u00a0°C is above TX 9.2\u00a0°C" in detail  # the largest first
    assert "data-qc-when" in detail and "qc-fig__ring" in detail
    assert "qc-chart__plot" in detail and "qc-chart__ring" in detail
    days = detail.split('class="table-wrap qc-daytable"')[1].split("</table>")[0]
    assert days.count("<tr") == 1 + 7 and 'class="qc-days__this"' in days
    assert "in the file" in detail and 'data-qc-back="tmaxmin"' in detail
    assert "quality/flagged.csv?check=tmaxmin" in detail
    assert '<tr data-date="1967-02-02" class="is-selected">' in detail
    rail = page.split('data-qc-item="tmaxmin"')[0].rsplit("<a", 1)[1]
    assert "is-selected" in rail
    # Another value, by its address.
    page = client.get(f"{url}?show=tmaxmin&tmaxmin_value=1962-04-10").content.decode()
    detail = detail_of(page, "tmaxmin")
    assert "TN 9.5\u00a0°C is above TX 8.2\u00a0°C" in detail
    assert '<tr data-date="1962-04-10" class="is-selected">' in detail
    assert 'data-qc-value="1962-04-10" aria-current="true"' in detail
    page = client.get(f"{url}?show=outliers-prcp-high").content.decode()
    assert details_shown(page) == ["outliers-prcp-high"]
    detail = detail_of(page, "outliers-prcp-high")
    assert "By calendar month" in detail and "values 1 to 12 of 67, largest first" in detail
    assert "Jan 6, Feb 5" not in detail and "by calendar month: Jan " in detail
    assert (
        'href="?show=outliers-prcp-high&amp;outliers-prcp-high_page=2'
        '&amp;outliers-prcp-high_sort=size#check-outliers-prcp-high"' in detail
    )
    # Unknown: the first check.
    page = client.get(f"{url}?show=nope").content.decode()
    assert details_shown(page) == ["tmaxmin"]


def test_checks_that_found_nothing_are_one_line(client, checked, monkeypatch):
    review = qc_review.review(checked.qc_job, checked.station_file)
    for check in review.checks:
        check.rows, check.count = [], 0
    review.wrong, review.groups = [], []
    review.verdict = qc_review.verdict(review.checks, [], review.verdict.values)
    monkeypatch.setattr(qc_review, "review", lambda job, path: review)
    page = client.get(f"{checked.url()}quality").content.decode()
    assert "8 checks found nothing" in page and 'id="nothing-found"' in page
    assert 'id="qc-review"' not in page and 'id="look-wrong"' not in page
    assert "Ready to use" in page
    assert_tab_shows_verdict(page, "ready", "Ready", "check-circle", "")
    # Green: "Go to indices" alone; the file is replaced from the Inputs panel (#199).
    verdict = verdict_of(page)
    assert verdict.count('class="button button--sm"') == 1
    assert "<span>Go to indices</span>" in verdict and "Flagged values" not in verdict
    assert "Replace file</span>" not in without_sheets(page)


def test_red_verdict_swaps_the_buttons(client, checked, monkeypatch):
    """#174, #202: on red "Replace file" is the primary button and "Go to indices anyway"
    stays beside it, so the user can always go on."""
    review = qc_review.review(checked.qc_job, checked.station_file)
    strict = qc_review.VerdictLimits(wrong_share=0.0)
    review.verdict = qc_review.verdict(review.checks, review.years, review.verdict.values, strict)
    assert review.verdict.level == "fix"
    monkeypatch.setattr(qc_review, "review", lambda job, path: review)
    page = client.get(f"{checked.url()}quality").content.decode()
    verdict = verdict_of(page)
    assert "<b>Fix the file first.</b>" in verdict and "verdict-strip--fix" in verdict
    assert_tab_shows_verdict(page, "fix", "Fix first", "error", "21")
    assert re.search(
        r'<a href="[^"]+" data-sheet-open="sheet-file"[^>]*class="button button--sm"', verdict
    )
    assert "<span>Go to indices anyway</span>" in verdict
    assert 'class="button button--secondary button--sm"' in verdict
    assert verdict.index("Go to indices anyway") < verdict.index("Replace file")


def test_pages_without_javascript(client, checked):
    """The pager's and the sort's links carry the page and order of each table in the
    query string, and the selection (#202, #264); a page asked for without ?show= shows
    its check."""
    page = client.get(f"{checked.url()}quality?outliers-prcp-high_page=6").content.decode()
    assert details_shown(page) == ["outliers-prcp-high"]
    section = detail_of(page, "outliers-prcp-high")
    assert "values 61 to 67 of 67" in section and "Page 6 of 6" in section
    assert (
        'href="?show=outliers-prcp-high&amp;outliers-prcp-high_page=5'
        '&amp;outliers-prcp-high_sort=size#check-outliers-prcp-high"' in section
    )
    page = client.get(f"{checked.url()}quality?outliers-prcp-high_sort=date").content.decode()
    section = detail_of(page, "outliers-prcp-high")
    assert "values 1 to 12 of 67, by date" in section
    dates = re.findall(r'<tr data-date="([\d-]+)"', section)
    assert dates == sorted(dates)
    assert re.search(r'data-qc-sort aria-current="true">Date<', section)


def test_table_page_of_a_date(client, checked):
    """The values fragment (htmx, #264): with ?date= the page that holds that value, the
    value selected; a date the check did not find gets no content."""
    review = qc_review.review(checked.qc_job, checked.station_file)
    row = review.table("outliers", "prcp-high").sorted_rows()[60]
    url = f"{checked.url()}quality/checks/outliers?group=prcp-high&date={row.date}"
    html = client.get(url).content.decode()
    assert "values 61 to 67 of 67" in html
    assert f'<tr data-date="{row.date}" class="is-selected">' in html
    assert f'data-selected="{row.date}"' in html and "data-ring-x=" in html
    assert 'class="qc-value"' in html
    html = client.get(url + "&sort=date&page=1").content.decode()
    assert "by date" in html and 'class="is-selected"' in html
    other = f"{checked.url()}quality/checks/tmaxmin?date={row.date}"
    assert client.get(other, HTTP_HX_REQUEST="true").status_code == 204
    assert client.get(other).status_code == 200
    assert client.get(f"{checked.url()}quality/checks/nope").status_code == 404
    assert client.get(f"{checked.url()}quality/checks/outliers").status_code == 404
    assert client.get(f"{checked.url()}quality/checks/outliers?group=nope").status_code == 404


def sheet_post(client, analysis, key, data, next_page="quality"):
    """Apply the Inputs panel's sheet ``key`` from a station page (#198, #199)."""
    return client.post(
        f"{analysis.url()}inputs/{key}",
        {**data, "next": f"{analysis.url()}{next_page}"},
    )


def test_new_thresholds_run_the_checks_again(client, checked):
    data = {**{k: str(v) for k, v in QC_DEFAULTS.items()}, "jump": "15"}
    response = sheet_post(client, checked, "thresholds", data)
    assert response["Location"] == f"{checked.url()}quality"
    checked.refresh_from_db()
    assert checked.workspace.qc_params["jump"] == 15.0
    assert checked.qc_job.params["qc"]["jump"] == 15.0
    job = run_next()
    review = qc_review.review(job, checked.station_file)
    assert review.check("tx_jumps").count > 10
    # The chart flags with the thresholds of the latest check.
    flags = chart_flags(client, checked, "tmax")
    listed = {r.date for r in review.check("tx_jumps").rows}
    assert {d for d, c in flags if c == "tx_jumps"} == listed
    # The panel says how many were changed, and Details too.
    page = client.get(f"{checked.url()}quality").content.decode()
    panel = page.split('data-input="thresholds"')[1].split("</div>")[0]
    assert '<dd class="inputs-panel__value">1 changed</dd>' in panel
    assert "The checks use R's default thresholds, with 1 changed." in page


def test_the_same_thresholds_run_failed_checks_again(client, checked):
    """#199: Apply on the thresholds sheet is how the checks run again once they failed or
    were stopped; with the checks done it queues nothing."""
    data = {k: str(v) for k, v in QC_DEFAULTS.items()}
    sheet_post(client, checked, "thresholds", data)
    assert Job.objects.count() == 2  # the checks and the speculative run, nothing more
    job = checked.qc_job
    job.status = Status.FAILED
    job.save()
    sheet_post(client, checked, "thresholds", data)
    checked.refresh_from_db()
    assert checked.qc_job != job and checked.qc_job.status == Status.QUEUED


def test_bad_thresholds_are_shown_on_the_sheet_page(client, checked):
    data = {**{k: str(v) for k, v in QC_DEFAULTS.items()}, "temp_max": "99"}
    response = sheet_post(client, checked, "thresholds", data)
    assert response.status_code == 200
    page = response.content.decode()
    assert "Enter a number from 0 to 60." in page and 'id="input-form"' in page
    assert Job.objects.count() == 2  # the checks and the speculative run, nothing more


def test_replaced_file_reruns_the_checks_and_keeps_the_details(client, checked):
    """Acceptance: replacing the file with a fixed one reruns QC without re-entering
    metadata (the File sheet, #198, #199)."""
    data = {**{k: str(v) for k, v in QC_DEFAULTS.items()}, "iqr_temp": "4"}
    sheet_post(client, checked, "thresholds", data)
    run_next()
    fixed = STRESS.read_text().replace("1963\t7\t2\t200.1\t", "1963\t7\t2\t20.1\t")
    assert fixed != STRESS.read_text()
    upload = {"station_file": SimpleUploadedFile("fixed.txt", fixed.encode())}
    response = sheet_post(client, checked, "file", upload)
    assert response["Location"] == f"{checked.url()}quality"
    checked.refresh_from_db()
    assert checked.station_name == "qc_stress_1961-2020" and checked.latitude == 52.38
    assert checked.workspace.qc_params["iqr_temp"] == 4.0
    assert checked.step == Step.QC and checked.file_name == "fixed.txt"
    job = run_next()
    assert job.params["qc"]["iqr_temp"] == 4.0
    review = qc_review.review(job, checked.station_file)
    assert "1963-07-02" not in [r.date for r in review.check("toolarge").rows]


def test_a_bad_replacement_file_shows_its_problems(client, checked):
    upload = {"station_file": SimpleUploadedFile("bad.txt", b"not a station file\n")}
    response = sheet_post(client, checked, "file", upload)
    assert response.status_code == 200
    page = response.content.decode()
    assert "file-problems" in page
    checked.refresh_from_db()  # the analysis and its results are unchanged
    assert checked.file_name == STRESS.name and checked.qc_job.status == Status.SUCCEEDED


def test_use_this_data_opens_the_results(client, checked):
    """#178: "Use this data" goes straight to the results of the run queued with the
    checks, which becomes the user's own; no settings page on the way."""
    speculative = checked.indices_job
    response = client.post(f"{checked.url()}quality/continue")
    assert response["Location"] == f"{checked.url()}indices"
    checked.refresh_from_db()
    assert checked.step == Step.RESULTS and checked.indices_job == speculative
    job = Job.objects.get(kind="station")
    assert not job.is_speculative and job.params["qc"] == QC_DEFAULTS
    page = client.get(f"{checked.url()}indices").content.decode()
    assert "Calculating indices" in page and "indices/progress" in page


def test_continue_needs_finished_checks(client):
    analysis = start(client)
    response = client.post(f"{analysis.url()}quality/continue")
    assert response["Location"] == f"{analysis.url()}quality"
    # The results are not shown before "Use this data" (#178).
    assert client.get(f"{analysis.url()}indices")["Location"].endswith("/quality")


def test_other_sessions_get_404(client, checked):
    from django.test import Client

    other = Client()
    for url in ("quality", "quality/progress", "quality/checks/outliers"):
        assert other.get(f"{checked.url()}{url}").status_code == 404
    for url in ("inputs/thresholds", "inputs/file", "quality/continue"):
        assert other.post(f"{checked.url()}{url}").status_code == 404
    # The old forms' addresses are gone (#199).
    for url in ("quality/run", "quality/file"):
        assert client.post(f"{checked.url()}{url}").status_code == 404


def test_failed_checks_say_so(client):
    analysis = start(client)
    job = analysis.qc_job
    job.status, job.error = Status.FAILED, "Something went wrong."
    job.save()
    page = client.get(f"{analysis.url()}quality").content.decode()
    assert "The checks could not be run." in page and "Something went wrong." in page
    # "Run the checks" opens the thresholds sheet, whose Apply runs them (#199).
    alert = page.split('class="alert alert--error"')[1].split("</div>\n    </div>")[0]
    assert 'data-sheet-open="sheet-thresholds"' in alert and "Run the checks" in alert


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
    assert client.get(f"{checked.url()}quality").status_code == 200


def test_every_section_has_its_help_and_no_field_has_a_link(client, checked):
    """#177: one help link per section of the Quality page opens its help in the drawer
    (#235: "How the checks work" for both lists, quiet); the thresholds have no help link
    of their own (their sheet has)."""
    page = client.get(f"{checked.url()}quality").content.decode()
    assert re.findall(r'href="/help/sections/([^/"?]+)/', page) == [
        "quality.missing",  # the coverage strip's table (#235)
        "quality.verdict",  # "How the checks work", with every check's topic (#235)
        "quality.daily",
        "quality.distributions",
    ]
    # The thresholds sheet's help opens in place, the drawer being behind it (#199).
    assert "help-topic--compact" not in without_sheets(page)


def test_flagged_values_csv(client, checked):
    """#235: "Flagged values (CSV)" lists every value the checks flagged, one row each, in
    R's order of the checks, values as the file has them (hyphen-minus, no units)."""
    response = client.get(f"{checked.url()}quality/flagged.csv")
    assert response.status_code == 200 and response["Content-Type"].startswith("text/csv")
    assert "_flagged_values.csv" in response["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(response.content.decode())))
    assert rows[0] == list(qc_review.FLAGGED_COLUMNS)
    review = qc_review.review(checked.qc_job, checked.station_file)
    kinds = [r[2] for r in rows[1:]]
    assert kinds.count("look wrong") == 21 and kinds.count("worth a look") == 105
    assert ["1962-04-10", "TN ≥ TX", "look wrong", "TN", "9.5", "°C", "TX 8.2"] in rows
    assert ["1963-07-03", "Out of range", "look wrong", "PR", "-0.1", "mm", "limit 0 mm"] in rows
    assert "−" not in response.content.decode() and " " not in response.content.decode()
    assert len(rows) - 1 == len(qc_review.flagged_rows(review))
    other = Client()
    assert other.get(f"{checked.url()}quality/flagged.csv").status_code == 404


def test_one_checks_values_csv(client, checked):
    """#264: a check's detail offers its values alone ("These values (CSV)")."""
    url = f"{checked.url()}quality/flagged.csv"
    response = client.get(f"{url}?check=outliers&group=prcp-high")
    assert "_outliers-prcp-high_values.csv" in response["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(response.content.decode())))
    assert rows[0] == list(qc_review.FLAGGED_COLUMNS) and len(rows) == 1 + 67
    assert {r[1] for r in rows[1:]} == {"Outliers"} and {r[3] for r in rows[1:]} == {"PR"}
    rows = list(csv.reader(io.StringIO(client.get(f"{url}?check=duplicates").content.decode())))
    assert len(rows) == 1 + 5
    assert client.get(f"{url}?check=nope").status_code == 404
    assert client.get(f"{url}?check=outliers&group=nope").status_code == 404
