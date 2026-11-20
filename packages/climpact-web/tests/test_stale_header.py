"""The header of out-of-date results (#223): after an input changed, the Indices, an
index's page and Files still show the old run's results until the new ones are ready, so
their provenance line describes the run on the page (its base period, coordinates and
settings), not the new inputs, and "Download all" says it is out of date and is no longer
the primary action, in the context bar, in its ⋯ menu for phones and on Files. Checked for
a workspace of one station and for a station in a workspace of several, whose settings are
the workspace's (#254). After a new file, Quality's line and the results' describe the
file their checks and run read (#269), recorded with each job."""

import re

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from test_indices_results import defaults, finish
from test_qc_review import run_next
from test_workspace import edit, in_use, page
from test_workspace_settings import shared_workspace

from climpact_web.jobs.models import Status
from climpact_web.stations import workspace
from climpact_web.stations.forms import QCParamsForm
from climpact_web.stations.views import sample_bytes

pytestmark = pytest.mark.django_db

ZIP = "station.zip"


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.RUNS_DIR = tmp_path / "media" / "runs"
    settings.JOB_RETENTION_DAYS = 7
    return settings


def finish_with_zip(job):
    """:func:`test_indices_results.finish`, with a zip, so Download all is offered."""
    return add_zip(finish(job))


def add_zip(job):
    """Give the finished ``job`` a zip."""
    (job.output_dir / ZIP).write_bytes(b"zip")
    job.result = {**job.result, "zip": ZIP}
    job.save()
    return job


def provenance(html) -> str:
    """The context bar's provenance line, as text."""
    line = re.search(r'<p class="context-bar__provenance">(.*?)</p>', html, re.S).group(1)
    return re.sub(r"<[^>]+>", " ", line)


def zip_buttons(html) -> list[str]:
    """Each link to the zip on the page (R's zip with the provenance file, #239): its
    class and its label."""
    return [
        f"{css} | {label}"
        for css, label in re.findall(
            r'<a href="/w/[^"]*/zip" class="([^"]*)">.*?<span>([^<]*)</span>', html, re.S
        )
    ]


def station_with_zip(client):
    """:func:`test_workspace.in_use`, whose run has a zip."""
    analysis, qc, run = in_use(client)
    add_zip(run)
    return analysis, qc, run


def test_new_base_period_keeps_the_header_on_the_results_shown(client):
    analysis, _qc, run = station_with_zip(client)
    html = page(client, analysis)
    assert "base 1971–2000" in provenance(html)
    # The zip, primary, in the context bar and in its ⋯ menu for phones.
    assert zip_buttons(html) == ["button | Download all (zip, 3\xa0bytes)"] * 2
    edit(client, analysis, "base-period", {"base_start": "1981", "base_end": "2010"})
    analysis.refresh_from_db()
    new = analysis.indices_job
    assert new != run and new.status == Status.QUEUED
    for path in ("indices", "indices/txx", "downloads"):
        html = page(client, analysis, path)
        line = provenance(html)
        assert "base 1971–2000" in line and "1981" not in line, path
    # The Inputs panel shows the new value.
    assert "1981–2010" in page(client, analysis)
    html = page(client, analysis)
    assert zip_buttons(html) == ["button button--secondary | Download all (out of date)"] * 2
    files = page(client, analysis, "downloads")
    assert zip_buttons(files) == [
        "button button--secondary | Download all (zip, 3\xa0bytes, out of date)"
    ]
    # Cancelled: the old results stay, and stay out of date.
    new.status = Status.CANCELLED
    new.save()
    html = page(client, analysis)
    assert "base 1971–2000" in provenance(html)
    assert zip_buttons(html) == ["button button--secondary | Download all (out of date)"] * 2
    # A new run of the new inputs finishes: the header is current again.
    base = f"/w/{analysis.workspace_id}/{analysis.slug}"
    client.post(f"{base}/recalculate", {"recalculate": "1"})
    analysis.refresh_from_db()
    newer = analysis.indices_job
    assert newer not in (run, new) and newer.status == Status.QUEUED
    finish_with_zip(newer)
    html = page(client, analysis)
    assert "base 1981–2010" in provenance(html)
    assert zip_buttons(html) == ["button | Download all (zip, 3\xa0bytes)"] * 2
    files = page(client, analysis, "downloads")
    assert "base 1981–2010" in provenance(files)
    assert zip_buttons(files) == ["button | Download all (zip, 3\xa0bytes)"]


def test_new_settings_and_location_keep_the_header_on_the_results_shown(client):
    analysis, _qc, _run = in_use(client)
    assert "ET-SCI defaults" in provenance(page(client, analysis))
    edit(client, analysis, "settings", {**defaults(), "rx_days": "7"})
    edit(
        client,
        analysis,
        "station",
        {"station_name": analysis.station_name, "latitude": "-33.5", "longitude": "151"},
    )
    for path in ("indices", "downloads"):
        line = provenance(page(client, analysis, path))
        assert "ET-SCI defaults" in line and "0.00°" in line and "33.50" not in line, path
    analysis.refresh_from_db()
    finish(analysis.indices_job)
    line = provenance(page(client, analysis))
    assert "ET-SCI defaults" not in line and "settings not the default" in line
    assert "33.50°\xa0S" in line


def test_a_station_of_several_keeps_the_header_on_its_results(client):
    stations = shared_workspace(client, 3)
    first = stations[0][0]
    edit(client, first, "base-period", {"base_start": "1981", "base_end": "2010"})
    for station, _qc, _run in stations:
        station.refresh_from_db()
        for path in ("indices", "downloads"):
            line = provenance(page(client, station, path))
            assert "base 1971–2000" in line and "1981" not in line, (station.slug, path)
    # One station's new results are ready: its header is current, the others' are not.
    second = stations[1][0]
    finish(second.indices_job)
    assert "base 1981–2010" in provenance(page(client, second))
    assert "base 1971–2000" in provenance(page(client, stations[2][0]))


# ---- the file the checks and results read (#269) ------------------------------------------

SYDNEY = "sydney_observatory_hill_1936-2015.txt"
OLD_FILE = ("1936–2015 · 80 yr", "29,220 days · PR TX TN", SYDNEY)
NEW_FILE = ("1990–2015 · 26 yr", "9,496 days · PR TX TN", "sydney_1990-2015.txt")


def shorter_file():
    """The Sydney sample from 1990 on: a file of fewer years, under another name."""
    lines = sample_bytes().splitlines(keepends=True)
    return SimpleUploadedFile(
        NEW_FILE[2], b"".join(line for line in lines if int(line.split()[0]) >= 1990)
    )


def describes(line, file) -> bool:
    """Whether the provenance ``line`` gives the years of ``file`` and not the other's."""
    other = NEW_FILE if file is OLD_FILE else OLD_FILE
    return file[0] in line and other[0] not in line


def test_a_job_records_the_file_it_reads(client):
    analysis, qc, run = in_use(client)
    for job in (qc, run):
        assert job.inputs["data"] == {
            "name": SYDNEY,
            "first_year": 1936,
            "last_year": 2015,
            "days": 29220,
            "variables": ["prcp", "tmax", "tmin"],
        }
    edit(client, analysis, "file", {"station_file": shorter_file()}, back="quality")
    analysis.refresh_from_db()
    for job in (analysis.qc_job, analysis.indices_job):
        data = job.inputs["data"]
        assert (data["name"], data["first_year"], data["days"]) == (NEW_FILE[2], 1990, 9496)


def test_after_a_new_file_the_lines_describe_the_file_the_shown_jobs_read(client):
    analysis, _qc, _run = in_use(client)
    line = provenance(page(client, analysis, "quality"))
    assert all(text in line for text in OLD_FILE)
    edit(client, analysis, "file", {"station_file": shorter_file()}, back="quality")
    analysis.refresh_from_db()
    new_qc, new_run = analysis.qc_job, analysis.indices_job
    assert new_qc.status == new_run.status == Status.QUEUED
    # While the checks and the run of the new file are on the way, the old ones are shown,
    # out of date, each described by the file it read.
    quality = page(client, analysis, "quality")
    assert "Checking again" in quality
    line = provenance(quality)
    assert all(text in line for text in OLD_FILE) and NEW_FILE[2] not in line
    assert "9,496" not in line
    for path in ("indices", "indices/txx", "downloads"):
        assert describes(provenance(page(client, analysis, path)), OLD_FILE), path
    # The Inputs panel describes the new file, marked changed.
    assert "9,496 days · 3 variables" in quality and 'data-input="file" data-changed' in quality
    # Cancelled: the old checks and results stay, and so do their lines.
    for job in (new_qc, new_run):
        job.status = Status.CANCELLED
        job.save()
    line = provenance(page(client, analysis, "quality"))
    assert all(text in line for text in OLD_FILE)
    for path in ("indices", "downloads"):
        assert describes(provenance(page(client, analysis, path)), OLD_FILE), path
    # Checked again (the thresholds sheet applied as it is, #199) and calculated again:
    # each line describes the new file once its job is ready.
    thresholds = QCParamsForm.initial_for(analysis.workspace.qc_params)
    edit(client, analysis, "thresholds", thresholds, back="quality")
    base = f"/w/{analysis.workspace_id}/{analysis.slug}"
    client.post(f"{base}/recalculate", {"recalculate": "1"})
    analysis.refresh_from_db()
    assert analysis.qc_job != new_qc and analysis.indices_job != new_run
    assert run_next() == analysis.qc_job
    line = provenance(page(client, analysis, "quality"))
    assert all(text in line for text in NEW_FILE) and SYDNEY not in line
    assert describes(provenance(page(client, analysis, "indices")), OLD_FILE)
    finish(analysis.indices_job)
    for path in ("indices", "indices/txx", "downloads"):
        assert describes(provenance(page(client, analysis, path)), NEW_FILE), path


def test_jobs_from_before_the_record_describe_the_current_file(client):
    """A job queued before #269 recorded only the file's hash: its line falls back to the
    current file, as before."""
    analysis, qc, run = in_use(client)
    for job in (qc, run):
        job.inputs = {k: v for k, v in job.inputs.items() if k != "data"}
        job.save()
    edit(client, analysis, "file", {"station_file": shorter_file()}, back="quality")
    analysis.refresh_from_db()
    assert workspace.shown_qc(analysis) == qc and workspace.shown_run(analysis) == run
    assert describes(provenance(page(client, analysis, "quality")), NEW_FILE)
    assert describes(provenance(page(client, analysis, "indices")), NEW_FILE)
