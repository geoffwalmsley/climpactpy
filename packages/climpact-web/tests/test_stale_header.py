"""The header of out-of-date results (#223): after an input changed, the Indices, an
index's page and Files still show the old run's results until the new ones are ready, so
their provenance line describes the run on the page (its base period, coordinates and
settings), not the new inputs, and "Download all" says it is out of date and is no longer
the primary action, in the context bar, in its ⋯ menu for phones and on Files. Checked for
a workspace of one station and for a station in a workspace of several, whose settings are
the workspace's (#254)."""

import re

import pytest
from test_indices_results import defaults, finish
from test_workspace import edit, in_use, page
from test_workspace_settings import shared_workspace

from climpact_web.jobs.models import Status

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
