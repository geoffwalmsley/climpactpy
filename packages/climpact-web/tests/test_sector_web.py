"""Single-station step 5, sector data (#90): the form (R's inputs and defaults), the
sector file checks (plain-language problems at file lines), the job and its progress, the
results (bar chart and scatter plots with tables and files), R's error messages in the page,
batch stations, and that the tables are those of ``climpact sector-correlation``.

The station run is R's own reference output for the Sydney sample (``reference/output/
sydney``), the run R's sector correlation reference (``reference/output/sydney/sector``)
was made from, with R's sample wheat file."""

import re
import shutil
import uuid
from pathlib import Path

import made
import pytest
from django.test import Client

from climpact_web.jobs.models import Job, Status
from climpact_web.jobs.views import OWNER_KEY
from climpact_web.jobs.worker import claim, run_job
from climpact_web.stations import sector_file, sector_plots
from climpact_web.stations.models import Station, Step

REPO = Path(__file__).resolve().parents[3]
SYDNEY = REPO / "reference" / "output" / "sydney"
R_SECTOR = SYDNEY / "sector"
WHEAT = REPO / "reference" / "input" / "sector" / "wheat_yield_nsw_1922-1999.csv"
STATION = "sydney_observatory_hill_1936-2015"

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.RUNS_DIR = tmp_path / "media" / "runs"
    return settings


def ready_analysis(client) -> Station:
    load = made.station_to_set_up(client, sample=True).url("setup")
    data = {"station_name": STATION, "latitude": "-33.86", "longitude": "151.21",
            "base_start": "1971", "base_end": "2000"}  # fmt: skip
    assert client.post(load, data).status_code == 302
    # Step 1 queues the quality checks and a speculative run of the indices (#178).
    Job.objects.all().delete()
    analysis = Station.objects.get()
    analysis.step = Step.INDICES  # "Use this data"
    analysis.save()
    return analysis


def finished_analysis(client) -> tuple[Station, Job]:
    """The Sydney sample with a finished station run: R's reference output."""
    analysis = ready_analysis(client)
    job = Job.objects.create(
        kind="station",
        owner=analysis.owner,
        status=Status.SUCCEEDED,
        params={"station_file": "station.txt", "params": {}, "plots": False, "zip": False},
        result={"station": STATION, "files": [], "skipped": [], "zip": None},
    )
    shutil.copytree(SYDNEY / STATION, job.output_dir / STATION)
    analysis.indices_job = job
    analysis.save()
    return analysis, job


def url(analysis, suffix="") -> str:
    return f"{analysis.url()}sector{suffix}"


def run_next() -> Job:
    job = claim("test")
    assert job is not None
    run_job(job, None)
    job.refresh_from_db()
    return job


def upload(name: str, text: str):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(name, text.encode(), content_type="text/csv")


def sector_text(first=1980, years=15, value=lambda y: 1 + (y % 7) / 10) -> str:
    return "Year,Yield (t/ha)\n" + "".join(f"{y},{value(y)}\n" for y in range(first, first + years))


# ---- the form ------------------------------------------------------------------------------


def test_needs_the_indices_first(client):
    analysis = ready_analysis(client)
    html = client.get(url(analysis)).content.decode()
    assert "Calculate the indices first" in html
    assert f'href="{analysis.url()}indices"' in html
    assert 'name="sector_file"' not in html


def test_form_has_r_inputs_and_defaults(client):
    analysis, _job = finished_analysis(client)
    response = client.get(url(analysis))
    assert response.status_code == 200
    html = response.content.decode()
    # R: sectorDataFile, sectorPlotTitle (the station name), y_axis_label, detrendCheck (on)
    assert 'type="file" name="sector_file"' in html and 'accept=".csv' in html
    assert re.search(r'name="title"[^>]*value="sydney_observatory_hill_1936-2015"', html)
    assert re.search(r'<input type="text" name="y_label"(?![^>]*value=)', html)
    assert re.search(r'name="detrend"[^>]*checked', html)
    assert "Calculate correlations" in html and 'name="sample"' in html
    assert 'href="/station/sample-sector.csv"' in html
    for topic in ("sector.file", "sector.title", "sector.y_label", "sector.detrend"):
        assert f'data-topic="{topic}"' in html or topic.split(".")[1] in html
    analysis.refresh_from_db()
    assert analysis.step == Step.SECTOR


def test_sample_file_is_r_s(client):
    response = client.get("/station/sample-sector.csv")
    assert b"".join(response.streaming_content) == WHEAT.read_bytes()
    assert "wheat_yield_nsw_1922-1999.csv" in response["Content-Disposition"]


def test_core_and_web_agree_on_the_defaults():
    from climpact import sector

    assert sector_file.MIN_COMMON_YEARS == sector.MIN_COMMON_YEARS
    assert sector_file.R_NO_COMMON_DATA == sector.NO_COMMON_DATA
    for name in ("wheat_yield_nsw_1922-1999.csv", "rice.csv", "a.b_c.csv", "noext"):
        assert sector_file.default_y_label(name) == sector.default_y_label(name)


# ---- the file checks -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, message, line",
    [
        ("", "The file is empty.", None),
        ("1922,0.66\n1923,0.7\n", "the first line must hold the column names", 1),
        ("Year;Wheat\n1922;0.66\n", "not a semicolon or a tab", 1),
        ("Year,Wheat,Rice\n1922,1,2\n", "has 3 column names", 1),
        ("Jahr,Wheat\n1922,1\n", "must be named Year, not “Jahr”", 1),
        ("Year,Wheat\n1922,0,66\n", "decimal comma", 2),
        ("Year,Wheat\n\n1922,1\nabc,2\n", "the year “abc” is not a whole number", 4),
        ("Year,Wheat\n1922,lots\n", "“lots” is not a number. Write a missing value as -99.9.", 2),
        ("Year,Wheat\n1922,1\n1922,2\n", "the year 1922 is repeated (first on line 2)", 3),
        ("Year,Wheat\n1923,1\n1922,2\n", "the year 1922 comes after 1923", 3),
        ("Year,Wheat\n", "no data under the column names", None),
        ("Year,Wheat\n1922,-99.9\n1923,NA\n", "Every value in the file is missing", None),
    ],
)
def test_problems_name_the_line(text, message, line):
    result = sector_file.inspect_sector_bytes(text.encode())
    assert not result.ok
    assert message in result.problems[0].message
    assert result.problems[0].line == line


def test_not_a_text_file_and_many_problems():
    result = sector_file.inspect_sector_bytes(b"PK\x03\x04rest")
    assert "not a text file" in result.problems[0].message
    text = "Year,Wheat\n" + "".join(f"{y},x\n" for y in range(1900, 1915))
    result = sector_file.inspect_sector_bytes(text.encode())
    assert result.problem_count == 15 and len(result.problems) == 10 and result.hidden_problems == 5


def test_the_core_reads_what_the_check_accepts(tmp_path):
    from climpact.sector import read_sector_file

    for text in (WHEAT.read_text(), "﻿Year,Yield (t/ha)\n1990,1\n1991,\n1992,NA\n1993,-99.9\n"):
        result = sector_file.inspect_sector_bytes(text.encode("utf-8"))
        assert result.ok, result.problems
        path = tmp_path / "s.csv"
        path.write_text(result.text, encoding="utf-8")
        data = read_sector_file(path)
        assert data.years.tolist() == result.years
        assert int((~(data.values != data.values)).sum()) == result.values


def test_too_few_years_in_common_gives_r_s_message():
    result = sector_file.inspect_sector_bytes(
        sector_text(2000, 20).encode(), list(range(1936, 2010))
    )
    assert result.ok and len(result.common) == 10
    result = sector_file.inspect_sector_bytes(
        sector_text(2007, 20).encode(), list(range(1936, 2016))
    )
    assert not result.ok
    message = result.problems[0].message
    assert "have 9 years in common; at least 10 are needed" in message
    assert sector_file.R_NO_COMMON_DATA in message and "1936 to 2015" in message


def test_problems_shown_in_the_page_and_nothing_queued(client):
    analysis, _job = finished_analysis(client)
    bad = "Year,Wheat\n1950,1\n1950,2\n1951,x\n"
    response = client.post(url(analysis), {"sector_file": upload("bad.csv", bad), "detrend": "on"})
    assert response.status_code == 200
    html = response.content.decode()
    assert "bad.csv was not loaded: it has 2 problems" in html
    assert "Line 3: the year 1950 is repeated" in html and "<code" in html
    assert "Line 4: “x” is not a number" in html
    few = sector_text(2010, 12)
    html = client.post(url(analysis), {"sector_file": upload("few.csv", few)}).content.decode()
    assert "not able to make a correlation, since there is no data in common!" in html
    html = client.post(url(analysis), {"title": "x"}).content.decode()
    assert "Choose a sector data file, or use the sample data." in html
    assert not Job.objects.filter(kind="sector").exists()


# ---- the job and its results --------------------------------------------------------------------


def cli_outputs(tmp_path, detrend: bool) -> Path:
    """What ``climpact sector-correlation`` writes for the same station run."""
    from climpact.sector import run_sector_correlation
    from climpact_web.stations.models import Station

    out = tmp_path / ("cli-detrended" if detrend else "cli-raw")
    shutil.copytree(SYDNEY / STATION / "indices", out / STATION / "indices")
    station_file = Station.objects.get().station_file
    run_sector_correlation(station_file, WHEAT, out, STATION, detrend_sector=detrend)
    return out / STATION / "corr"


@pytest.mark.parametrize("detrend", [True, False])
def test_sydney_wheat_matches_the_command_line_and_r(client, tmp_path, detrend):
    analysis, station_job = finished_analysis(client)
    data = {"title": "", "y_label": "", "sample": "1"}
    if detrend:
        data["detrend"] = "on"
    assert client.post(url(analysis), data)["Location"] == url(analysis)
    job = Job.objects.get(kind="sector")
    analysis.refresh_from_db()
    assert analysis.sector_job == job
    p = job.params
    assert p["station_job"] == str(station_job.pk) and p["station"] == STATION
    assert p["title"] == STATION and p["y_label"] == "wheat" and p["detrend"] is detrend
    assert p["file_name"] == "wheat_yield_nsw_1922-1999.csv" and p["common"] == 64
    assert (job.input_dir / "sector.csv").read_text() == WHEAT.read_text()
    assert (job.input_dir / "station.txt").read_bytes() == analysis.station_file.read_bytes()

    # While it waits: the progress fragment, polled by htmx.
    html = client.get(url(analysis)).content.decode()
    assert "Calculating correlations" in html and f'hx-get="{url(analysis, "/progress")}"' in html
    job = run_next()
    assert job.status == Status.SUCCEEDED, job.log
    progress = client.get(url(analysis, "/progress"))
    assert progress.status_code == 204 and progress["HX-Redirect"] == url(analysis)

    # The tables: those of the command line, and R's correlations.
    corr = job.output_dir / STATION / "corr"
    cli = cli_outputs(tmp_path, detrend)
    csvs = sorted(f.name for f in corr.glob("*.csv"))
    assert csvs == sorted(f.name for f in cli.glob("*.csv")) and len(csvs) == 5
    for name in csvs:
        assert (corr / name).read_text() == (cli / name).read_text(), name
    r_folder = R_SECTOR / ("detrended" if detrend else "raw")
    part = "detrended.wheat.yield" if detrend else "wheat.yield"
    r_table = (r_folder / f"{STATION}_index-sector_correlation_{part}.csv").read_text()
    assert (corr / f"{STATION}_index-sector_correlation_{part}.csv").read_text() == r_table
    assert len(list(corr.glob("*.png"))) == 5
    assert job.result["zip"] == f"{STATION}_corr.zip"

    # The page: every correlation, the four regressions as the core computes them.
    html = client.get(url(analysis)).content.decode()
    rows = [line.split(",") for line in r_table.splitlines()[1:]]
    assert len(rows) == 42
    table = html.split('aria-label="Correlation with each index"')[-1].split("</table>")[0]
    for index, cor, _category in rows:
        assert f'/indices/{index.strip(chr(34))}">' in table
        assert f'<td class="num">{cor.replace("-", "\u2212")}</td>' in table  # #226
    assert html.count('class="sector-plot__bar ') == 42
    assert html.count('class="sector-plot__fit"') == 4

    from climpact.io.station import read_station_rows
    from climpact.sector import read_index_tables, read_sector_file, sector_correlation

    result = sector_correlation(
        read_station_rows(analysis.station_file),
        read_index_tables(SYDNEY / STATION / "indices", STATION),
        read_sector_file(WHEAT),
        STATION,
        detrend,
    )
    for scatter in result.scatters:
        reg = scatter.regression
        shown = next(s for s in job.result["scatters"] if s["name"] == scatter.name)
        assert (shown["slope"], shown["intercept"], shown["r_squared"]) == (
            reg.slope,
            reg.intercept,
            reg.r_squared,
        )
        sign = "+" if reg.intercept >= 0 else "−"
        equation = f"y = {sector_plots.number(reg.slope)} x {sign} "
        assert equation + sector_plots.number(abs(reg.intercept)) in html
        assert f"R² = {sector_plots.number(reg.r_squared)}" in html
    # Fallbacks: tables, CSV and PNG of each chart, and the zip.
    assert html.count("View as table") == 5
    assert html.count("Image (PNG)") == 5 and html.count("Table (CSV)") == 5
    assert f'href="/jobs/{job.pk}/files/{STATION}_corr.zip"' in html
    assert (
        "Change the file or the settings" in html
        and '<details class="disclosure sector-settings" id' in html
    )


def test_bars_in_order_of_strength_and_colours(client):
    analysis, _job = finished_analysis(client)
    client.post(url(analysis), {"sample": "1", "detrend": "on"})
    run_next()
    html = client.get(url(analysis) + "?order=strength").content.decode()
    table = html.split('aria-label="Correlation with each index"')[-1].split("</table>")[0]
    values = [abs(float(v)) for v in re.findall(r'<td class="num">(-?[\d.]+)</td>', table)]
    assert values == sorted(values, reverse=True)
    assert "swatch-chart-tmax" in html and "swatch-chart-prcp" in html
    assert "Temperature" in html and "Precipitation" in html


def test_a_failed_job_shows_r_s_message(client):
    analysis, station_job = finished_analysis(client)
    client.post(url(analysis), {"sample": "1", "detrend": "on"})
    job = Job.objects.get(kind="sector")
    job.status, job.error = Status.FAILED, sector_file.R_NO_COMMON_DATA
    job.save()
    html = client.get(url(analysis)).content.decode()
    assert "The correlations could not be calculated." in html
    assert "Error: not able to make a correlation, since there is no data in common!" in html
    assert 'name="sector_file"' in html  # the form, open, to try again
    assert client.get(url(analysis, "/progress"))["HX-Redirect"] == url(analysis)


def test_the_runner_raises_r_s_error_for_an_index_without_common_years(client):
    """R stops when an index has no year in common with the sector data; the job fails
    with its message, shown in the page."""
    analysis, station_job = finished_analysis(client)
    client.post(url(analysis), {"sample": "1", "detrend": "on"})
    # Every index table moved out of the sector years: R's "no data in common".
    indices = station_job.output_dir / STATION / "indices"
    for path in indices.glob(f"{STATION}_*_ANN.csv"):
        lines = path.read_text().splitlines()
        head, rows = lines[:7], lines[7:]
        shifted = [rows[0]] + [
            re.sub(r"^\d{4}", lambda m: str(int(m[0]) + 500), r) for r in rows[1:]
        ]
        path.write_text("\n".join(head + shifted) + "\n")
    job = run_next()
    assert job.status == Status.FAILED
    assert job.error == sector_file.R_NO_COMMON_DATA
    html = client.get(url(analysis)).content.decode()
    assert "Error: not able to make a correlation" in html


def test_a_new_calculation_of_the_indices_hides_the_old_comparison(client):
    analysis, _job = finished_analysis(client)
    client.post(url(analysis), {"sample": "1", "detrend": "on"})
    run_next()
    assert "sector-results" in client.get(url(analysis)).content.decode()
    newer = Job.objects.create(
        kind="station", owner=analysis.owner, status=Status.SUCCEEDED,
        params={"station_file": "station.txt", "params": {}},
        result={"station": STATION, "files": [], "skipped": []},
    )  # fmt: skip
    shutil.copytree(SYDNEY / STATION, newer.output_dir / STATION)
    analysis.indices_job = newer
    analysis.save()
    html = client.get(url(analysis)).content.decode()
    assert "sector-results" not in html and 'name="sector_file"' in html
    assert client.get(url(analysis, "/progress")).status_code == 404


def test_other_sessions_get_404(client):
    analysis, _job = finished_analysis(client)
    other = Client()
    session = other.session
    session[OWNER_KEY] = "someone-else"
    session.save()
    other.cookies["sessionid"] = session.session_key
    assert other.get(url(analysis)).status_code == 404
    assert other.post(url(analysis), {"sample": "1"}).status_code == 404
    assert other.get(url(analysis, "/progress")).status_code == 404
    assert client.get(f"/station/{uuid.uuid4()}/sector").status_code == 404


# ---- batch stations ------------------------------------------------------------------------------


def test_a_batch_station_opened_as_a_single_station(client, tmp_path):
    """A batch's station, opened from the batch results, is compared with the batch's
    index tables (the runner's batch branch), using the analysis's station file."""
    import datetime as dt

    import numpy as np

    from climpact_web.batch import check

    rng = np.random.default_rng(0)
    lines = []
    day = dt.date(1980, 1, 1)
    while day <= dt.date(1993, 12, 31):
        tx = 25 + 6 * np.sin(day.timetuple().tm_yday / 58) + rng.normal()
        rain = max(0.0, rng.normal(1, 3))
        lines.append(f"{day.year} {day.month} {day.day} {rain:.1f} {tx:.1f} {tx - 9:.1f}")
        day += dt.timedelta(days=1)
    meta = "\t".join(check.COLUMNS) + "\n" + "a.txt\t-30\t150\t3\t3\t18\t18\t10\t3\t30\t2\t24\n"
    run = made.checked_batch(client, meta, **{"a.txt": "\n".join(lines) + "\n"})
    made.queue(client, run, {"base_start": "1981", "base_end": "1990", "workers": "1"})
    batch = run_next()
    assert batch.status == Status.SUCCEEDED, batch.log
    client.get(f"/w/{run.workspace_id}/")  # the workspace of one station opens it
    analysis = Station.objects.get()
    assert analysis.indices_job is None and analysis.origin["station"] == "a"
    html = client.get(url(analysis)).content.decode()
    assert "in the batch run" in html
    text = sector_text(1978, 20, value=lambda y: round(2 + rng.normal(), 2))
    client.post(url(analysis), {"sector_file": upload("maize_yields.csv", text), "detrend": "on"})
    job = Job.objects.get(kind="sector")
    assert job.params["station_job"] == str(batch.pk) and job.params["station"] == "a"
    assert job.params["y_label"] == "maize" and job.params["common"] == 14
    job = run_next()
    assert job.status == Status.SUCCEEDED, job.log
    html = client.get(url(analysis)).content.decode()
    assert "14 years in common, 1980 to 1993." in html
    assert html.count('class="sector-plot__fit"') == 4


# ---- drawing ------------------------------------------------------------------------------


def test_bar_chart_draws_na_and_both_signs():
    bars = [
        sector_plots.Bar("txx", "TXx", 0.3, "temperature"),
        sector_plots.Bar("fd", "FD", None, "temperature"),
        sector_plots.Bar("cdd", "CDD", -0.45, "precipitation"),
    ]
    svg = str(sector_plots.bar_svg(bars, "t"))
    assert svg.count('class="sector-plot__bar ') == 2 and ">NA</text>" in svg
    assert "<title>FD: NA (Temperature)</title>" in svg and ">\u22120.45</text>" in svg
    assert sector_plots._symmetric_ticks([0.3, -0.45])[0] == -0.6


def test_scatter_line_is_the_least_squares_fit():
    rows = [(2000 + i, float(i), 2.0 * i + 1) for i in range(5)] + [(2005, None, 3.0)]
    assert sector_plots.fit(rows) == pytest.approx((2.0, 1.0))
    scatter = sector_plots.Scatter("t", "x", "f.csv", None, rows, 2.0, 1.0, 1.0)
    svg = str(sector_plots.scatter_svg(scatter, "Yield"))
    assert (
        svg.count("<circle") == 5
        and "sector-plot__fit" in svg
        and "<title>2004: 4, 9</title>" in svg
    )
    assert scatter.equation == "y = 2 x + 1" and scatter.r_squared_text == "1"


def test_every_section_has_its_help(client):
    """#177: the sector page's sections each have an ⓘ, the results' too."""
    analysis, _job = finished_analysis(client)
    html = client.get(url(analysis)).content.decode()
    assert re.findall(r'href="/help/sections/([^/"?]+)/', html) == ["sector.data", "sector.plot"]
    # The Inputs panel's sheets have their help in place (#199): not the page's own.
    assert "help-topic--compact" not in re.sub(r"<dialog.*?</dialog>", "", html, flags=re.S)
    client.post(url(analysis), {"sample": "1", "detrend": "on"})
    assert run_next().status == Status.SUCCEEDED
    html = client.get(url(analysis)).content.decode()
    assert re.findall(r'href="/help/sections/([^/"?]+)/', html) == [
        "sector.correlation",
        "sector.scatter",
        "sector.data",
        "sector.plot",
    ]
