"""Out-of-date checks are reviewed against the file they read (#308): after a new file,
Quality keeps the earlier checks until the new ones are ready (#179), and their verdict,
counts, year table and values come from the copy of the file those checks read, kept in the
job's own folder, not from the file that replaced it. The verdict kept with the old checks
for the tabs and the overview (#222) stays theirs."""

import re

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from test_stale_header import SYDNEY, shorter_file
from test_workspace import edit, in_use, page

from climpact_web.jobs.models import Status
from climpact_web.stations import qc_review, workspace
from climpact_web.stations.views import sample_bytes

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.RUNS_DIR = tmp_path / "media" / "runs"
    settings.JOB_RETENTION_DAYS = 7
    return settings


def text(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def verdict(html: str) -> str:
    """The verdict strip's text, without its buttons: the level, its sentence and the
    counts."""
    strip = re.search(r'<div class="verdict-strip__text">.*?</div>', html, re.S)
    return text(strip.group(0))


def years(html: str) -> str:
    """The table of missing days per year, as text."""
    table = re.search(r'<details class="disclosure" id="missing-data">.*?</details>', html, re.S)
    return text(table.group(0))


def quality(client, analysis) -> tuple[str, str]:
    html = page(client, analysis, "quality")
    return verdict(html), years(html)


def flagged(client, analysis) -> bytes:
    response = client.get(f"{analysis.url()}quality/flagged.csv")
    assert response.status_code == 200
    return response.content


def test_out_of_date_checks_are_reviewed_against_the_file_they_read(client):
    analysis, qc, _run = in_use(client)
    before = quality(client, analysis)
    csv_before = flagged(client, analysis)
    detail = f"{analysis.url()}quality/checks/tx_jumps"
    jumps_before = client.get(detail).content
    qc.refresh_from_db()
    kept = (qc.result["verdict"], qc.result["verdict_wrong"])
    assert before[0].startswith("Usable.") and "of 80 years" in before[1]
    # A file of 26 years replaces the one of 80: the old checks stay, out of date, while
    # the new ones wait, run or are cancelled.
    edit(client, analysis, "file", {"station_file": shorter_file()}, back="quality")
    analysis.refresh_from_db()
    new = analysis.qc_job
    assert new != qc and workspace.shown_qc(analysis) == qc
    for status in (Status.QUEUED, Status.RUNNING, Status.CANCELLED):
        new.status = status
        new.save()
        assert quality(client, analysis) == before, status
        # The values of the checks are the old file's too: the flagged values and a
        # check's table are as they were.
        assert flagged(client, analysis) == csv_before, status
        assert client.get(detail).content == jumps_before, status
        qc.refresh_from_db()
        assert (qc.result["verdict"], qc.result["verdict_wrong"]) == kept, status
    # The file changed back: the old checks are linked again (#254), and the tab shows the
    # verdict kept with them, of the file they read.
    edit(client, analysis, "file", {"station_file": sample_file()}, back="quality")
    analysis.refresh_from_db()
    assert analysis.qc_job == qc
    assert workspace.section_states(analysis)["quality"] == kept[0]
    assert quality(client, analysis) == before


def test_the_review_reads_the_copy_the_job_kept(client):
    analysis, qc, _run = in_use(client)
    assert qc_review.checked_file(qc) == qc.input_dir / qc.params["station_file"]
    assert qc_review.checked_file(qc).read_bytes() == analysis.station_file.read_bytes()
    # Without its copy (a job folder kept in part), out-of-date checks have no review: the
    # page says nothing rather than judge them against another file.
    edit(client, analysis, "file", {"station_file": shorter_file()}, back="quality")
    qc_review.checked_file(qc).unlink()
    html = page(client, analysis, "quality")
    assert 'class="verdict-strip' not in html


def sample_file():
    """The Sydney sample, as first given."""
    return SimpleUploadedFile(SYDNEY, sample_bytes())
