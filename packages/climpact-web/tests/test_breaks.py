"""Possible breaks on a station's Quality page (#365): the checks' job runs the core's
homogeneity module ``detect`` with the workspace's break detection settings and station
history file; the page shows each series' breaks beside the checks; a change to the
settings reruns the checks' job alone, never the indices; the break tests' files are in
the zips and Files."""

import io
import json
import re
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.test import RequestFactory
from test_qc_review import details_shown, run_next
from test_workspace import in_use, page

from climpact_web.jobs.models import Job, Status
from climpact_web.stations import breaks, calculation, workspace
from climpact_web.stations.models import Workspace

pytestmark = pytest.mark.django_db

SERIES = ["tx-annual", "tx-monthly", "tn-annual", "tn-monthly", "prcp-annual"]


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.RUNS_DIR = tmp_path / "media" / "runs"


def change(client, station, **settings):
    """Change the workspace's break detection settings, as one change (#254)."""
    request = RequestFactory().post("/")
    request.session = client.session
    assert calculation.change_settings(request, station, break_detection=settings)
    station.refresh_from_db()
    return Workspace.objects.get(pk=station.workspace_id)


def write_history(station, text: str) -> None:
    path = breaks.history_path(station.workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


# ---- the job ---------------------------------------------------------------------------------


def test_the_checks_look_for_breaks_and_the_indices_do_not(client):
    station, qc, run = in_use(client)
    # The checks' job: the module's options (the defaults) and the settings it records.
    options = {
        "methods": "pettitt,snht,pmf,pmt",
        "variables": "TX,TN,PRCP",
        "series": "annual,monthly",
        "level": 0.95,
        "min_years": 5,
    }
    assert qc.params["homogeneity"] == options and "station_history" not in qc.params
    assert qc.inputs["breaks"] == {"on": True, **options, "history": ""}
    names = sorted(Path(f).relative_to(qc.result["station"]).as_posix() for f in qc.result["files"])
    station_name = qc.result["station"]
    assert f"homogeneity/{station_name}_breaks.csv" in names
    assert f"homogeneity/{station_name}_tests.csv" in names
    assert {"homogeneity/breaks", "homogeneity/tests"} <= set(qc.result["reports"])
    series = json.loads((qc.output_dir.parent / qc.result["breaks_series"]).read_text())
    assert sorted(series["values"]) == ["PRCP", "TN", "TX"] and series["history"] == []
    assert not (qc.output_dir / qc.result["breaks_series"]).exists()  # not a file to download
    # The calculation never looks for breaks, and does not depend on their settings.
    assert "homogeneity" not in run.params and "breaks" not in (run.inputs or {})
    assert "breaks" not in workspace.job_inputs(station, "station", run.params)


def test_quality_shows_each_series_beside_the_checks(client):
    station, qc, _run = in_use(client)
    html = page(client, station, "quality")
    # The rail's third section, after the checks, with a row per series.
    assert html.index('id="worth-a-look"') < html.index('id="possible-breaks"')
    for key in SERIES:
        assert f'data-qc-item="breaks-{key}"' in html and f'data-qc-detail="breaks-{key}"' in html
    rail = html.split('id="possible-breaks"')[1].split("</section>")[0]
    assert "Possible breaks around" in rail and "The data are not adjusted." in rail
    assert "How the break tests work" in html and "/help/sections/quality.breaks/" in html
    # The verdict's level is the checks'; its counts line links to the breaks.
    verdict = html.split('id="qc-verdict-title"')[1].split("</section>")[0]
    assert '<a href="?show=breaks-tx-annual#detail-breaks-tx-annual">' in verdict
    assert "possible breaks in TX TN PRCP</a>" in verdict
    # A check is shown first; ?show= shows a series instead, without JavaScript.
    assert details_shown(html) != ["breaks-tx-annual"]
    html = client.get(f"{station.url()}quality?show=breaks-tx-annual").content.decode()
    assert details_shown(html) == ["breaks-tx-annual"]
    assert re.search(r'data-qc-item="breaks-tx-annual" aria-current="true"', html)
    detail = html.split('data-qc-detail="breaks-tx-annual"')[1].split("</section>")[0]
    assert (
        "Possible breaks · TX annual · " in detail and "TX annual: possible breaks around" in detail
    )
    # The chart: axes, the segments' means, a mark per date, its read-out and table view.
    assert 'class="qc-fig__plot breaks-chart breaks-chart--tmax"' in detail
    assert 'class="breaks-chart__steps"' in detail and "break-mark--strong" in detail
    assert "data-readout=" in detail and "data-qc-months-table" in detail
    assert "dates with possible breaks:" in detail  # the text summary
    # Which tests agree, the four tests, the breaks table and the two files.
    for text in ("Which tests agree", "The four tests", "Last before", "Critical value"):
        assert text in detail
    assert "no history file" in detail
    for name in ("breaks", "tests"):
        assert f'/jobs/{qc.pk}/files/{qc.result["reports"][f"homogeneity/{name}"]}"' in detail


def test_a_change_to_the_settings_reruns_the_checks_job_only(client):
    station, qc, run = in_use(client)
    write_history(
        station,
        "date,event,station\n1956-12,Screen moved 20 m east,sydney_observatory_hill_1936-2015\n"
        "2000-01-01,Electronic sensors,sydney_observatory_hill_1936-2015\n"
        "1990,Another station's event,Elsewhere\n",
    )
    history = {"name": "nsw_history.csv", "sha256": "abc"}
    settings = {"methods": ["pettitt", "pmf"], "variables": ["TX"], "series": ["annual"]}
    space = change(client, station, **settings, level=0.9, min_years=3, history=history)
    new = station.qc_job
    assert new != qc and new.status == Status.QUEUED
    assert station.indices_job == run  # the indices don't change
    assert new.params["homogeneity"] == {
        "methods": "pettitt,pmf",
        "variables": "TX",
        "series": "annual",
        "level": 0.9,
        "min_years": 3,
    }
    assert new.params["station_history"] == breaks.HISTORY_FILE
    assert (new.input_dir / breaks.HISTORY_FILE).is_file()
    # Meanwhile the checks are current, their breaks out of date; the change can be undone.
    assert workspace.qc_changes(station, qc) == [] and workspace.breaks_changes(station, qc)
    assert workspace.section_states(station)["results"] == "done"
    html = page(client, station, "quality")
    assert "The checks are out of date" not in html and "Checking again" not in html
    assert "<span>Go to indices</span>" in html
    detail = html.split('data-qc-detail="breaks-tx-annual"')[1].split("</section>")[0]
    assert "These breaks come from the earlier settings (95%, segments of 5+ years)." in detail
    assert "Looking for breaks with the new settings." in detail
    assert workspace.undo_available(space)
    # The new breaks: two tests on TX annual, the station's own history beside them.
    job = run_next()
    assert job == new and job.status == Status.SUCCEEDED, job.error
    station.refresh_from_db()
    found = breaks.review(station.workspace, job)
    assert [(s.variable, s.freq) for s in found.series] == [("TX", "annual")]
    assert [t.method for t in found.series[0].tests] == ["pettitt", "pmf"]
    assert found.has_history and not found.stale
    assert [e["text"] for e in found.events] == ["Screen moved 20 m east", "Electronic sensors"]
    assert any("Screen moved 20 m east" in b.history for b in found.series[0].breaks)
    html = page(client, station, "quality")
    assert "These breaks come from the earlier settings" not in html
    assert 'class="breaks-chart__event"' in html and "Station history" in html


def test_undo_puts_the_settings_and_the_breaks_back(client):
    station, qc, run = in_use(client)
    space = change(client, station, level=0.99)
    assert calculation.undo(space)
    station.refresh_from_db()
    space.refresh_from_db()
    assert space.break_detection == {} and station.qc_job == qc and station.indices_job == run
    assert not workspace.breaks_changes(station, qc)
    assert Job.objects.filter(status=Status.CANCELLED, kind="qc").count() == 1


def test_turned_off(client):
    station, qc, _run = in_use(client)
    change(client, station, on=False)  # reruns the checks' job without the module
    html = page(client, station, "quality")
    rail = html.split('id="possible-breaks"')[1].split("</section>")[0]
    assert "Turned off for this workspace." in rail and "Turn it on in Workspace settings" in rail
    assert 'data-qc-detail="breaks-' not in html and "possible breaks in" not in html
    assert calculation.qc_job_params(station).keys() == {"station_file", "metadata", "qc"}
    assert breaks.inputs_of(station.workspace) == {"on": False}
    job = run_next()
    assert job.status == Status.SUCCEEDED and "homogeneity" not in job.params
    assert not breaks.has_results(job) and "breaks_series" not in job.result


def test_checks_from_before_break_detection(client):
    station, qc, _run = in_use(client)
    qc.result["reports"] = {k: v for k, v in qc.result["reports"].items() if "homog" not in k}
    qc.save()
    rail = page(client, station, "quality").split('id="possible-breaks"')[1].split("</section>")[0]
    assert "Not looked for: these checks ran before break detection was on." in rail


def test_a_history_file_that_cannot_be_read_is_left_out(client):
    station, _qc, _run = in_use(client)
    write_history(station, "date,event\n1956-12,Moved\n1997/06,New screen\n")
    change(client, station, history={"name": "bad.csv", "sha256": "bad"})
    job = run_next()
    assert job.status == Status.SUCCEEDED, job.error
    assert job.result["history_error"] == (
        "station_history.csv, line 3: date '1997/06' is not YYYY-MM-DD, YYYY-MM or YYYY"
    )
    station.refresh_from_db()
    html = client.get(f"{station.url()}quality?show=breaks-tx-annual").content.decode()
    assert "The station history file was not used: station_history.csv, line 3" in html


# ---- the files --------------------------------------------------------------------------------


def test_the_zips_and_files_hold_the_break_tests(client):
    station, qc, _run = in_use(client)
    name = qc.result["station"]
    response = client.get(f"{station.url()}zip")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content))) as archive:
        names = archive.namelist()
        record = json.loads(archive.read("climpact_run.json"))
    assert f"homogeneity/{name}_breaks.csv" in names and f"homogeneity/{name}_tests.csv" in names
    assert record["settings"]["break_detection"]["on"] is True
    response = client.get(f"/w/{station.workspace_id}/files/everything.zip")
    with zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content))) as archive:
        names = archive.namelist()
    assert any(n.endswith(f"/homogeneity/{name}_breaks.csv") for n in names)
    files = page(client, station, "downloads")
    assert "Possible breaks" in files and "Break tests" in files


# ---- reading the files -----------------------------------------------------------------------


def b(method, last, first, significance="yes", shift=1.0):
    return breaks.Break(method, last, first, significance, 1.0, 1.0, None, shift, "degC", "")


def test_breaks_are_grouped_by_date_and_graded_by_the_evidence():
    groups = breaks.group_breaks(
        [
            b("pettitt", "1987", "1988"),
            b("pmt", "1987", "1988", "maybe"),
            b("snht", "1998", "1999"),
            b("pmt", "2005", "2006"),
            b("pmf", "2010", "2011", "maybe"),
            b("pmf", "2014", "2015"),
            b("pmt", "2018", "2019", "no"),
        ],
        "annual",
    )
    assert [(g.when, g.grade, g.count) for g in groups] == [
        ("1987/88", "strong", 2),  # two tests, one yes
        ("1998/99", "normal", 1),  # one test
        ("2005/06", "quiet", 1),  # PMT alone
        ("2010/11", "quiet", 1),  # a maybe
        ("2014/15", "strong", 1),  # PMF
    ]  # RHtests' "no" is not a break
    monthly = breaks.group_breaks(
        [b("snht", "1997-01", "1997-02"), b("pmt", "1997-10", "1997-11")], "monthly"
    )
    assert [(g.when, g.count) for g in monthly] == [("1997-01", 2)]


def write_table(path: Path, columns: list[str], rows: list[list]) -> None:
    lines = ['"Description: ","test"', ",".join(columns)]
    lines += [",".join(str(v) for v in row) for row in rows]
    path.write_text("\n".join(lines) + "\n")


def fake_job(tmp_path, tests, rows, params=None):
    out = tmp_path / "job" / "output"
    (out / "s" / "homogeneity").mkdir(parents=True)
    write_table(
        out / "s/homogeneity/s_tests.csv",
        [
            "variable",
            "series",
            "method",
            "first",
            "last",
            "values",
            "breaks",
            "possible",
            "status",
            "note",
        ],
        tests,
    )
    write_table(
        out / "s/homogeneity/s_breaks.csv",
        ["variable", "series", "method", "last_before", "first_after", "significance",
         "statistic", "critical_value", "p_value", "shift", "units", "station_history"],
        rows,
    )  # fmt: skip
    (out.parent / "breaks_series.json").write_text(
        json.dumps(
            {"first": 1995, "values": {"TX": [20.1, None, 21.0, 20.5], "TN": [10, 11, 10, 9]}}
        )
    )
    reports = {
        "homogeneity/tests": "s/homogeneity/s_tests.csv",
        "homogeneity/breaks": "s/homogeneity/s_breaks.csv",
    }
    return SimpleNamespace(
        output_dir=out,
        result={"station": "s", "reports": reports, "breaks_series": "breaks_series.json"},
        params={"homogeneity": {"level": 0.95, "min_years": 5}, **(params or {})},
        is_finished=True,
    )


def test_series_not_tested_and_maybes(tmp_path):
    space = SimpleNamespace(break_detection={}, pk="x")
    note = "9 values; at least 10 are needed"
    tests = [
        ["TX", "annual", m, 1995, 1998, 4, "NA", "NA", "not tested", note]
        for m in ("pettitt", "snht", "pmf", "pmt")
    ]
    tests += [["TN", "annual", "pettitt", 1995, 1998, 4, 0, 0, "no breaks found", ""]]
    tests += [["TN", "annual", "pmt", 1995, 1998, 4, 0, 2, "no breaks found", ""]]
    rows = [
        ["TN", "annual", "pmt", 1995, 1996, "maybe", 2.37, 2.4, "NA", -0.4, "degC", ""],
        ["TN", "annual", "pmt", 1997, 1998, "maybe", 2.5, 2.6, "NA", 0.3, "degC", ""],
    ]
    found = breaks.review(space, fake_job(tmp_path, tests, rows))
    tx, tn = found.series
    assert tx.headline == "TX annual: not tested" and tx.rail_text == "4 of 4 not tested"
    assert tx.tests[0].result == f"Not tested: {note}"
    assert tn.maybe_only and tn.headline == "TN annual: 2 maybes, around 1995 and 1997"
    assert [t.result for t in tn.tests] == ["No breaks found", "2 maybes"]
    assert found.sentence == (
        "2 possible breaks, all maybes, in TN annual. 4 tests could not run. "
        "The data are not adjusted."
    )
    assert found.counts_text == "possible breaks in TN · 4 tests not run"
    chart = found.chart(tn)
    assert chart.rows[0] == {"year": 1995, "value": "10", "segment": "1995"}
    assert chart.height == breaks.AXIS + 24  # no station history: no room for it


def test_no_breaks(tmp_path):
    space = SimpleNamespace(break_detection={}, pk="x")
    tests = [
        ["TX", "annual", m, 1995, 1998, 60, 0, 0, "no breaks found", ""] for m in breaks.METHODS
    ]
    found = breaks.review(space, fake_job(tmp_path, tests, []))
    assert (
        found.sentence == "No breaks found by 4 tests in the 1 series. The data are not adjusted."
    )
    assert found.counts_text == "no possible breaks (4 tests)"
    assert found.series[0].headline == "TX annual: no breaks found"


def test_numbers_follow_the_rules():
    row = breaks.Break("pettitt", "1987", "1988", "yes", 9814.0, 5240.2, 0.0, 1.2345, "degC", "")
    assert (row.statistic_text, row.critical_text, row.p_text) == ("9,814", "5,240", "< 0.00005")
    assert row.shift_text == "+1.23 °C"
    assert (
        breaks.Break("pmf", "1", "2", "yes", 3.57, 6.32, None, -16.2, "%", "").shift_text == "−16%"
    )
    assert breaks.Break("snht", "1", "2", "yes", 1, 1, 0.0207, 1, "degC", "").p_text == "0.021"
    assert breaks.Break("snht", "1", "2", "yes", 1, 1, 0.00007, 1, "degC", "").p_text == "0.00007"
