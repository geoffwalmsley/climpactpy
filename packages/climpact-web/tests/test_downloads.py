"""The downloads of a station (#79, #176): the Files page with every file, sizes on the
buttons, one "Download all" elsewhere, the PDF report written by the station and batch
jobs."""

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
from climpact_web.stations.models import Step
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
    assert re.search(rf"Download all \(zip, {SIZE}\)", html)
    assert re.search(rf"Download the report \(PDF, {SIZE}\)", html)
    # One primary action, the zip (#176); the Inputs panel's sheets have their own (#198).
    assert re.sub(r"<dialog.*?</dialog>", "", html, flags=re.S).count('class="button"') == 1
    # Every index table, each with its size, and the PNG drawn.
    for name in index_files():
        assert f"{files}{STATION}/indices/{STATION}_{name}.csv" in html, name
    assert f"{files}{STATION}/plots/{STATION}_txx_ANN.png" in html
    links = re.findall(
        r'class="button button--secondary button--sm download-link[^"]*"[^>]*>.*?</a>', html
    )
    assert len(links) > len(index_files())
    assert all(re.search(SIZE, link) for link in links)
    for name in ("trend", "thres", "nastatistics", "outliers", "tmaxmin"):
        assert f"_{name}.csv" in html
    # A file no group names (here the reference run's comparison) is under Other files.
    other = html.split('id="others-title"')[1]
    assert f'href="{files}{STATION}/comparison_summary.csv"' in other
    # Where the chart images of the current view are: one line, no link to a chart (#176).
    assert "use PNG or SVG above its chart" in html and "#index-chart" not in html
    # The index groups are closed disclosures, each with its count and total size.
    groups = re.findall(r"<details class=\"disclosure download-group\"[^>]*>", html)
    assert groups and not any(" open" in g for g in groups)
    assert re.search(rf"\d+ indices, {SIZE}", html)
    # Every link works.
    for href in sorted(set(re.findall(rf'href="({files}[^"]+)"', html)))[:5]:
        assert client.get(href).status_code == 200


def test_downloads_page_says_what_was_not_made(client):
    analysis, job = finished_analysis(client)  # no plots, zip or report
    html = client.get(f"/station/{analysis.pk}/downloads").content.decode()
    assert "Not made. The zip was switched off" in html
    assert "Not made. The report was switched off" in html
    assert "Not made. The plots were switched off" in html
    assert f'href="/station/{analysis.pk}/results?settings=open#adjust"' in html


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
    assert response["Location"] == f"/station/{analysis.pk}/results"


def test_dashboard_and_index_page_offer_one_download(client):
    """Results offer the zip and a link to Files, nothing else; an index page only its
    chart's own exports (#173, #176)."""
    analysis, job = finished_analysis(client)
    complete(job)
    html = client.get(f"/station/{analysis.pk}/results").content.decode()
    assert re.search(rf"Download all \(zip, {SIZE}\)", html)
    # The header: one primary action, the zip, and one secondary link, to Files (#173).
    actions = re.search(r'<div class="[^"]*results-actions">.*?</div>', html, re.S).group(0)
    assert actions.count('class="button"') == 1 and "Download all (zip" in actions
    assert actions.count('class="button button--secondary"') == 1 and actions.count("<a ") == 2
    assert f'href="/station/{analysis.pk}/downloads"' in actions
    # No other file on the page (#176): the zip is its only download.
    files = re.findall(rf'href="/jobs/{job.pk}/files/([^"]+)"', html)
    assert files == [f"{STATION}.zip"]
    assert 'id="downloads"' not in html and "Kept until" in html
    page = client.get(f"/station/{analysis.pk}/results/txx").content.decode()
    # The chart's CSV is the page's one file link; the PNG plot is the no-script image.
    links = re.findall(rf'<a [^>]*href="/jobs/{job.pk}/files/([^"]+)"', page)
    assert links == [f"{STATION}/indices/{STATION}_txx_ANN.csv"]
    assert "data-chart-csv" in page and 'id="files-title"' not in page
    # Files is reached by its tab (#179), the only link to it.
    assert page.count(f'href="/station/{analysis.pk}/downloads"') == 1
    assert f'href="/station/{analysis.pk}/downloads" data-tab="files"' in page


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


def test_the_settings_ask_for_the_report_and_the_job_writes_it(client):
    from test_indices_results import committed_analysis, defaults

    analysis = committed_analysis(client)
    assert analysis.indices_job.params["report"] is True  # the speculative run's default
    form = client.get(f"/station/{analysis.pk}/results").content.decode()
    assert re.search(r'<input type="checkbox" name="report"[^>]*checked', form)
    client.post(f"/station/{analysis.pk}/indices", {**defaults(), "report": "on"})
    job = Job.objects.latest("created_at")
    assert job.params["report"] is True
    client.post(f"/station/{analysis.pk}/indices", defaults())  # unticked
    assert Job.objects.latest("created_at").params["report"] is False
    # The next visit starts from the last calculation's choice.
    form = client.get(f"/station/{analysis.pk}/results").content.decode()
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
    assert re.search(rf"Download \(zip, {SIZE}\)", html)
    assert re.search(rf"Download all \(zip, {SIZE}\)", html)


def test_downloads_page_lists_the_sector_comparison(client):
    """A finished sector comparison (step 5, #90) of the run shown: its corr/ files."""
    from test_sector_web import finished_analysis as sector_analysis
    from test_sector_web import run_next

    analysis, _job = sector_analysis(client)
    page = f"/station/{analysis.pk}/downloads"
    assert 'id="sector-title"' not in client.get(page).content.decode()
    client.post(f"/station/{analysis.pk}/sector", {"sample": "1", "detrend": "on"})
    sector = run_next()
    assert sector.status == Status.SUCCEEDED, sector.log
    html = client.get(page).content.decode()
    assert '<h2 id="sector-title">Sector comparison</h2>' in html
    files = f"/jobs/{sector.pk}/files/"
    csvs = [f for f in sector.result["files"] if f.endswith(".csv")]
    assert csvs and all(f'href="{files}{f}"' in html for f in csvs)
    assert f'href="{files}{sector.result["zip"]}"' in html  # step 5 always zips corr/
    pngs = [f for f in sector.result["files"] if f.endswith(".png")]
    assert pngs and all(f'href="{files}{f}"' in html for f in pngs)
    section = html.split('id="sector-title"')[1].split("</section>")[0]
    links = re.findall(r'download-link[^"]*"[^>]*>.*?</a>', section, re.S)
    assert links and all(re.search(SIZE, link) for link in links)


def test_files_page_reaches_every_file_of_the_station(client):
    """Every file a user could download before #176 is reachable from Files: each file the
    quality check and the calculation wrote (walked on disk), each member of the zip, and
    every file linked from the Results, index and Quality pages."""
    from test_indices_results import finish, ready_analysis
    from test_qc_review import run_next

    analysis = ready_analysis(client)
    qc_job = run_next()  # step 1's "Continue" queued the quality checks
    assert qc_job.kind == "qc" and qc_job.status == Status.SUCCEEDED, qc_job.error
    job = Job.objects.create(
        kind="station",
        owner=analysis.owner,
        params={"station_file": "station.txt", "params": {}, "plots": True, "zip": True},
    )
    finish(job)
    complete(job)
    analysis.refresh_from_db()
    analysis.indices_job = job
    analysis.step = Step.RESULTS
    analysis.save()
    html = client.get(f"/station/{analysis.pk}/downloads").content.decode()
    linked = set(re.findall(r'href="(/jobs/[^"]+/files/[^"]+)"', html))
    qc_names = {h.rsplit("/", 1)[1] for h in linked if h.startswith(f"/jobs/{qc_job.pk}/")}

    def reachable(j, path) -> bool:
        rel = path.relative_to(j.output_dir).as_posix()
        # The run's own copy of a quality-control file is offered from the quality check,
        # which wrote the same file with the same thresholds.
        return f"/jobs/{j.pk}/files/{rel}" in linked or (
            j == job and path.parent.name == "qc" and path.name in qc_names
        )

    for j in (qc_job, job):
        on_disk = [p for p in j.output_dir.rglob("*") if p.is_file()]
        assert on_disk
        missing = [str(p.relative_to(j.output_dir)) for p in on_disk if not reachable(j, p)]
        assert not missing, f"{j.kind} files not on the Files page: {missing}"
    with zipfile.ZipFile(job.output_dir / f"{STATION}.zip") as archive:
        members = {n.rsplit("/", 1)[-1] for n in archive.namelist() if not n.endswith("/")}
    linked_names = {h.rsplit("/", 1)[1] for h in linked}
    assert members and members <= linked_names
    # Whatever another page links to is on Files too.
    for page in ("results", "results/txx", "quality"):
        other = client.get(f"/station/{analysis.pk}/{page}").content.decode()
        assert set(re.findall(r'href="(/jobs/[^"]+/files/[^"]+)"', other)) <= linked, page
    assert all(client.get(h).status_code == 200 for h in sorted(linked)[:3])


def test_files_page_before_the_indices_holds_the_quality_files(client):
    """After the quality checks and before a calculation, Files has their files (#176)."""
    from test_indices_results import ready_analysis
    from test_qc_review import run_next

    analysis = ready_analysis(client)
    qc_job = run_next()
    html = client.get(f"/station/{analysis.pk}/downloads").content.decode()
    assert 'id="quality-files"' in html and "Download all" not in html
    for rel in [*qc_job.result["files"], qc_job.result["zip"]]:
        assert f'href="/jobs/{qc_job.pk}/files/{rel}"' in html, rel
    # The tabs (#179): Files current, Quality done, Results not until "Use this data".
    assert f'href="/station/{analysis.pk}/qc"' not in html
    assert f'href="/station/{analysis.pk}/quality" data-tab="quality"' in html
    assert re.search(r'data-tab="files" data-state="done" aria-current="page"', html)
    assert 'data-tab="results" data-state="locked"' in html
