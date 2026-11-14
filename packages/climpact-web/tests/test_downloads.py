"""The downloads of a station run (#79): the downloads page, sizes on the buttons, the PDF
report written by the station and batch jobs."""

import re
import shutil
import zipfile

import pytest
from django.test import Client
from test_indices_results import LAT0, STATION, finished_analysis, index_files, media  # noqa: F401
from test_jobs import station_job

from climpact_web.jobs.models import Job, Status
from climpact_web.jobs.runners import run_station_job
from climpact_web.stations import downloads as model
from climpact_web.stations.views_indices import current_source

pytestmark = pytest.mark.django_db
SIZE = r"[0-9.]+\xa0(bytes|KB|MB)"


def complete(job: Job, plots=True, report=True) -> None:
    """Add what a run with plots, report and zip writes: a PNG, the report, the zip."""
    from climpact.config import IndexParams, StationMetadata
    from climpact.plots import zip_station
    from climpact.report import write_report

    station_dir = job.output_dir / STATION
    if plots:
        (station_dir / "plots").mkdir(exist_ok=True)
        (station_dir / "plots" / f"{STATION}_txx_ANN.png").write_bytes(b"\x89PNG" + b"0" * 2000)
        (station_dir / "plots" / f"{STATION}_all_plots.pdf").write_bytes(b"%PDF" + b"0" * 9000)
    result = dict(job.result)
    if report:
        path = write_report(job.output_dir, StationMetadata(STATION), IndexParams())
        result["report"] = path.name
    result["zip"] = zip_station(job.output_dir, STATION).name
    job.result = result
    job.params = {**job.params, "plots": plots, "zip": True, "report": report}
    job.save()


def test_downloads_page_lists_every_file_with_its_size(client):
    analysis, job = finished_analysis(client)
    complete(job)
    response = client.get(f"/station/{analysis.pk}/downloads")
    assert response.status_code == 200
    html = response.content.decode()
    files = f"/jobs/{job.pk}/files/"
    assert f'href="{files}{STATION}.zip"' in html
    assert f'href="{files}{STATION}_report.pdf"' in html
    assert f'href="{files}{STATION}/plots/{STATION}_all_plots.pdf"' in html
    assert re.search(rf"Download \(ZIP, {SIZE}\)", html)
    assert re.search(rf"Download \(PDF, {SIZE}\)", html)
    # Every index table, each with its size, and the PNG drawn.
    for name in index_files():
        assert f"{files}{STATION}/indices/{STATION}_{name}.csv" in html, name
    assert f"{files}{STATION}/plots/{STATION}_txx_ANN.png" in html
    links = re.findall(
        r'class="button button--secondary button--sm download-link"[^>]*>.*?</a>', html
    )
    assert len(links) > len(index_files())
    assert all(re.search(SIZE, link) for link in links)
    for name in ("trend", "thres", "nastatistics", "outliers", "tmaxmin"):
        assert f"_{name}.csv" in html
    # Where the chart images of the current view are.
    assert "PNG (a picture) or SVG" in html and "#index-chart" in html
    # Every link works.
    for href in sorted(set(re.findall(rf'href="({files}[^"]+)"', html)))[:5]:
        assert client.get(href).status_code == 200


def test_downloads_page_says_what_was_not_made(client):
    analysis, job = finished_analysis(client)  # no plots, zip or report
    html = client.get(f"/station/{analysis.pk}/downloads").content.decode()
    assert "Not made: the zip was switched off" in html
    assert "Not made in this calculation: the report" in html
    assert "Not made: the plots were switched off" in html
    assert f'href="/station/{analysis.pk}/indices"' in html


def test_downloads_page_redirects_and_is_private(client):
    analysis, job = finished_analysis(client)
    assert Client().get(f"/station/{analysis.pk}/downloads").status_code == 404
    job.status = Status.RUNNING
    job.save()
    response = client.get(f"/station/{analysis.pk}/downloads")
    assert response["Location"] == f"/station/{analysis.pk}/results"
    analysis.indices_job = None
    analysis.save()
    response = client.get(f"/station/{analysis.pk}/downloads")
    assert response["Location"] == f"/station/{analysis.pk}/indices"


def test_dashboard_and_index_page_show_sizes(client):
    analysis, job = finished_analysis(client)
    complete(job)
    html = client.get(f"/station/{analysis.pk}/results").content.decode()
    assert re.search(rf"Download everything \(zip, {SIZE}\)", html)
    assert re.search(rf"PDF report \({SIZE}\)", html)
    assert re.search(rf"All plots \(PDF, {SIZE}\)", html)
    assert re.search(rf"Trends \(CSV, {SIZE}\)", html)
    assert f'href="/station/{analysis.pk}/downloads"' in html
    page = client.get(f"/station/{analysis.pk}/results/txx").content.decode()
    assert re.search(rf"The table \(CSV, {SIZE}\)", page)
    assert re.search(rf"plot of this series \(PNG, {SIZE}\)", page)
    assert "PNG or SVG above the chart saves that view" in page


def test_report_path_of_a_batch_station(client, tmp_path):
    analysis, job = finished_analysis(client)
    _job, source = current_source(analysis)
    assert model.report_path(source) == job.output_dir / f"{STATION}_report.pdf"
    batch = Job.objects.create(
        kind="batch",
        owner=analysis.owner,
        status=Status.SUCCEEDED,
        result={"stations": [{"name": STATION, "report": f"reports/{STATION}_report.pdf"}]},
    )
    shutil.copytree(LAT0 / STATION, batch.output_dir / "b" / STATION)
    from dataclasses import replace

    batch_source = replace(source, job=batch, folder=batch.output_dir / "b", from_batch=True)
    assert model.report_path(batch_source) == batch.output_dir / "reports" / f"{STATION}_report.pdf"
    assert model.main_downloads(batch_source)["report"] is None  # not written here


def test_station_job_writes_the_report_beside_the_zip(settings, tmp_path):
    job = station_job(zip=True)
    job.params = {**job.params, "report": True}
    job.save()
    from climpact_web.jobs.registry import JobContext

    stages = []
    ctx = JobContext(
        str(job.pk),
        job.params,
        job.input_dir,
        job.output_dir,
        lambda stage, step, total: stages.append(stage),
    )
    result = run_station_job(ctx)
    assert result["report"] == "stn_report.pdf"
    assert (job.output_dir / "stn_report.pdf").read_bytes().startswith(b"%PDF")
    assert stages[-2:] == ["report", "zip"]
    with zipfile.ZipFile(job.output_dir / "stn.zip") as archive:
        assert not [n for n in archive.namelist() if "report" in n]


def test_step_3_asks_for_the_report_and_the_job_writes_it(client):
    from test_indices_results import defaults, ready_analysis

    analysis = ready_analysis(client)
    form = client.get(f"/station/{analysis.pk}/indices").content.decode()
    assert re.search(r'<input type="checkbox" name="report"[^>]*checked', form)
    client.post(f"/station/{analysis.pk}/indices", {**defaults(), "report": "on"})
    job = Job.objects.latest("created_at")
    assert job.params["report"] is True
    client.post(f"/station/{analysis.pk}/indices", defaults())  # unticked
    assert Job.objects.latest("created_at").params["report"] is False
    # The next visit starts from the last calculation's choice.
    form = client.get(f"/station/{analysis.pk}/indices").content.decode()
    assert not re.search(r'<input type="checkbox" name="report"[^>]*checked', form)


def test_batch_with_plots_writes_each_station_report(client):
    """A batch with plots also writes each station's report, outside the batch folder, and
    the results page offers it with its size."""
    from test_batch import created, metadata, run_worker, station

    run = created(client, metadata("a.txt"), **{"a.txt": station()})
    data = {"base_start": "2000", "base_end": "2001", "workers": "1", "plots": "on"}
    client.post(f"/batch/{run.pk}/run", data)
    run.refresh_from_db()
    assert run.job.params["report"] is True
    job = run_worker()
    assert job.status == Status.SUCCEEDED, job.log
    [entry] = job.result["stations"]
    assert entry["report"] == "reports/a_report.pdf"
    assert (job.output_dir / "reports" / "a_report.pdf").read_bytes().startswith(b"%PDF")
    with zipfile.ZipFile(job.output_dir / f"{job.params['folder']}.zip") as archive:
        assert not [n for n in archive.namelist() if "report" in n]
    html = client.get(f"/batch/{run.pk}/results").content.decode()
    assert f"/jobs/{job.pk}/files/reports/a_report.pdf" in html
    assert re.search(rf"PDF report \({SIZE}\)", html)
    assert re.search(rf"Download \(zip, {SIZE}\)", html)
    assert re.search(rf"Download everything \(zip, {SIZE}\)", html)


def test_downloads_page_lists_the_sector_comparison(client):
    """A finished sector comparison (step 5, #90) of the run shown: its corr/ files."""
    from test_sector_web import finished_analysis as sector_analysis
    from test_sector_web import run_next

    analysis, _job = sector_analysis(client)
    page = f"/station/{analysis.pk}/downloads"
    assert "Sector comparison" not in client.get(page).content.decode()
    client.post(f"/station/{analysis.pk}/sector", {"sample": "1", "detrend": "on"})
    sector = run_next()
    assert sector.status == Status.SUCCEEDED, sector.log
    html = client.get(page).content.decode()
    assert "Sector comparison" in html
    files = f"/jobs/{sector.pk}/files/"
    csvs = [f for f in sector.result["files"] if f.endswith(".csv")]
    assert csvs and all(f'href="{files}{f}"' in html for f in csvs)
    assert f'href="{files}{sector.result["zip"]}"' in html  # step 5 always zips corr/
    pngs = [f for f in sector.result["files"] if f.endswith(".png")]
    assert pngs and all(f'href="{files}{f}"' in html for f in pngs)
    section = html.split('id="sector-title"')[1].split("</section>")[0]
    links = re.findall(r'download-link"[^>]*>.*?</a>', section, re.S)
    assert links and all(re.search(SIZE, link) for link in links)
