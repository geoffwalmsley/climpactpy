"""The workspace file (#240): Save file downloads a workspace's input files and settings as
``climpact_workspace.zip``; Open a workspace file rebuilds it in this browser, through
Add stations' own routes, and calculates it again. The zip is untrusted: everything out of
the format is refused with a plain message, and nothing is made."""

import io
import json
import re
import stat
import zipfile

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from test_batch import created, media, metadata, run_worker, station  # noqa: F401
from test_batch_workspace import finished_batch
from test_workspace_added import run_all

from climpact_web.core.limits import Refused
from climpact_web.jobs.models import Job
from climpact_web.stations import workspace, workspace_file, workspace_files
from climpact_web.stations.forms import QC_DEFAULTS
from climpact_web.stations.models import Station, Workspace

pytestmark = pytest.mark.django_db


def saved(client, space) -> bytes:
    response = client.get(f"/w/{space.pk}/workspace.zip")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/zip"
    assert 'filename="climpact_workspace.zip"' in response["Content-Disposition"]
    return b"".join(response.streaming_content)


def open_file(client, data: bytes, name="climpact_workspace.zip"):
    return client.post("/w/open/", {"file": SimpleUploadedFile(name, data)})


def entries(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {i.filename: archive.read(i) for i in archive.infolist()}


def rezip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def with_manifest(data: bytes, change) -> bytes:
    files = entries(data)
    record = json.loads(files["workspace.json"])
    change(record)
    files["workspace.json"] = json.dumps(record).encode()
    return rezip(files)


def stations_of(space) -> list[tuple]:
    return sorted(
        (s.station_name, s.latitude, s.longitude, s.file_hash, workspace.own_params(s))
        for s in space.stations.all()
    )


def settings_of(space) -> tuple:
    return (
        space.display_name,
        space.base_start,
        space.base_end,
        space.qc_params,
        workspace.workspace_settings(space),
    )


def trends(client, space) -> str:
    client.get(f"/w/{space.pk}/")  # the batch's results recorded (fill_workspace)
    return workspace_files.trends_csv(workspace_files.entries(space, space.owner))


# ---- saving and opening ------------------------------------------------------------------


def test_save_then_open_gives_the_same_stations_settings_and_results(client):
    run = finished_batch(client, "a", "b", bad=["c"])  # c fails in the run
    space = run.workspace
    space.name = "NSW coast"
    space.save()
    before = trends(client, space)
    assert "a," in before and "b," in before
    data = saved(client, space)

    files = entries(data)
    assert set(files) == {
        "workspace.json",
        "metadata.txt",
        "climpact_run.json",
        "stations/a.txt",
        "stations/b.txt",
        "stations/c.txt",
    }
    record = json.loads(files["workspace.json"])
    assert record["format"] == "climpact-workspace" and record["format_version"] == 1
    assert record["name"] == "NSW coast"
    assert record["settings"]["base_period"] == [2000, 2001]
    assert record["settings"]["quality_thresholds"] == QC_DEFAULTS
    a = next(s for s in record["stations"] if s["name"] == "a")
    assert a["file"] == "stations/a.txt" and a["file_name"] == "a.txt"
    assert (a["latitude"], a["longitude"]) == (-30, 150)
    assert a["params"]["spei_months"] == 24 and a["use_results"] is True
    # The provenance file of every zip (#239), with the failed station and why.
    provenance = json.loads(files["climpact_run.json"])
    assert {s["name"] for s in provenance["stations"]} == {"a", "b", "c"}
    assert provenance["base_period"] == [2000, 2001]
    # R's batch metadata file, for the files in stations/.
    assert files["metadata.txt"].decode().splitlines()[1].startswith("a.txt\t-30\t150\t")

    response = open_file(client, data)
    reopened = Workspace.objects.exclude(pk=space.pk).get()
    assert response["Location"] == f"/w/{reopened.pk}/"
    assert reopened.owner == space.owner
    assert settings_of(reopened) == settings_of(space)
    assert stations_of(reopened) == stations_of(space)
    page = client.get(f"/w/{reopened.pk}/").content.decode()
    assert "NSW coast was opened from the workspace file." in page
    run_all()
    after = trends(client, reopened)
    lines = lambda text: sorted(  # noqa: E731
        line for line in text.splitlines() if line.startswith(("a,", "b,"))
    )
    assert lines(after) == lines(before) and lines(before)
    # The station that failed is opened too, and calculated again.
    assert reopened.stations.filter(station_name="c").exists()


def test_a_workspace_of_one_opens_on_its_station(client):
    client.post("/add/sample", {"show": "indices"})
    sydney = Station.objects.get()
    data = saved(client, sydney.workspace)
    response = open_file(client, data)
    copy = Station.objects.exclude(pk=sydney.pk).get()
    assert copy.source == "sample" and copy.station_name == sydney.station_name
    assert copy.file_hash == sydney.file_hash
    assert (copy.latitude, copy.longitude) == (sydney.latitude, sydney.longitude)
    # Its results were in use: they are again, and its Indices open.
    assert workspace.committed(copy) and not copy.indices_job.is_speculative
    assert response["Location"] == copy.url("results")


def test_the_settings_go_with_the_file(client):
    run = finished_batch(client, "a", "b")
    space = run.workspace
    space.qc_params = {**QC_DEFAULTS, "jump": 25.0}
    chosen = workspace.workspace_settings(space)
    chosen["params"]["custom"] = {"variable": "TN", "operator": ">", "threshold": 5.0}
    chosen["plots"] = False
    space.index_settings = chosen
    space.save()
    open_file(client, saved(client, space))
    reopened = Workspace.objects.exclude(pk=space.pk).get()
    assert settings_of(reopened)[1:] == settings_of(space)[1:]
    # The batch runs with R's thresholds, so each station is calculated again with the
    # workspace's, in the same change: one job for the hosted limits.
    for s in reopened.stations.all():
        assert s.qc_job.params["qc"]["jump"] == 25.0
        assert s.indices_job.kind == "station" and s.indices_job.params["qc"]["jump"] == 25.0
        assert s.indices_job.params["params"]["custom"]["threshold"] == 5.0
        assert s.indices_job.params["plots"] is False
        assert not s.indices_job.is_speculative
    batch = reopened.batches.get().job
    later = Job.objects.filter(created_at__gte=batch.created_at)
    assert later.count() == 5 and {j.params["change"] for j in later} == {batch.params["change"]}


def test_workspaces_and_get_started_lead_to_the_file(client):
    run = finished_batch(client, "a", "b")
    html = client.get("/w/").content.decode()
    assert re.search(r'<a href="/w/open/"[^>]*class="button button--secondary"', html)
    assert ">Open a workspace file<" in html
    assert f'<a href="/w/{run.workspace_id}/workspace.zip" download>Save file' in html
    assert "downloads the workspace's input files and settings as one zip" in html
    start = client.get("/add/").content.decode()
    assert '<a class="add-start__open" href="/w/open/">Or open a saved workspace file</a>' in start
    page = client.get("/w/open/").content.decode()
    assert "<h1>Open a workspace file</h1>" in page and 'type="file" name="file"' in page


def test_a_workspace_with_nothing_to_save(client):
    from test_add_stations import stage

    run = stage(client, a__txt=station())  # files waiting on Add stations, no station yet
    assert '/workspace.zip"' not in client.get("/w/").content.decode()
    response = client.get(f"/w/{run.workspace_id}/workspace.zip", follow=True)
    assert "has no station to save yet" in response.content.decode()


def test_another_sessions_workspace_cannot_be_saved(client):
    run = finished_batch(client, "a", "b")
    other = type(client)()
    assert other.get(f"/w/{run.workspace_id}/workspace.zip").status_code == 404


# ---- refusals ----------------------------------------------------------------------------


@pytest.fixture
def good(client) -> bytes:
    run = finished_batch(client, "a", "b")
    return saved(client, run.workspace)


def refused(client, data: bytes, name="climpact_workspace.zip") -> str:
    before = (Workspace.objects.count(), Station.objects.count(), Job.objects.count())
    response = open_file(client, data, name)
    assert response.status_code == 400
    assert (Workspace.objects.count(), Station.objects.count(), Job.objects.count()) == before
    html = response.content.decode()
    match = re.search(r'class="field__error"[^>]*>(.*?)</p>', html, re.S)
    assert match, html[:3000]
    return re.sub(r"<[^>]+>", "", match[1]).strip()


def test_nothing_chosen(client):
    response = client.post("/w/open/", {})
    assert response.status_code == 400 and "Choose a workspace file." in response.content.decode()


def test_not_a_zip(client):
    assert "This is not a zip file." in refused(client, b"year month day\n")
    assert "This is not a zip file." in refused(client, b"PK\x03\x04 broken")


def test_a_zip_of_station_files_is_not_a_workspace_file(client):
    message = refused(client, rezip({"a.txt": station().encode()}))
    assert "has no workspace.json" in message and "Add stations" in message


@pytest.mark.parametrize(
    ("name", "words"),
    [
        ("../evil.txt", "points outside the workspace file"),
        ("stations/../../evil.txt", "points outside the workspace file"),
        ("/etc/passwd", "is an absolute path"),
        ("C:/evil.txt", "is an absolute path"),
        ("c:evil.txt", "is an absolute path"),
        ("stations\\evil.txt", "has a name no workspace file uses"),
        ("notes.txt", "is not part of a workspace file"),
        ("stations/sub/a.txt", "is not part of a workspace file"),
        ("stations/A.TXT", "is not part of a workspace file"),
    ],
)
def test_entries_out_of_the_format_are_refused(client, good, name, words):
    files = entries(good)
    files[name] = b"x"
    assert words in refused(client, rezip(files))


def test_a_symbolic_link_is_refused(client, good):
    files = entries(good)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            if name == "stations/a.txt":
                info = zipfile.ZipInfo(name)
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, "/etc/passwd")
            else:
                archive.writestr(name, data)
    assert "is a symbolic link" in refused(client, buffer.getvalue())


def test_an_encrypted_entry_is_refused(client, good):
    data = bytearray(rezip(entries(good)))
    # Set the "encrypted" flag of stations/a.txt in its local header and the central
    # directory (zipfile writes no encrypted entries itself).
    name = b"stations/a.txt"
    for signature, flag, name_at in ((b"PK\x03\x04", 6, 30), (b"PK\x01\x02", 8, 46)):
        at = 0
        while (at := data.find(signature, at)) >= 0:
            if data[at + name_at : at + name_at + len(name)] == name:
                data[at + flag] |= 0x1
            at += 4
    assert "is encrypted" in refused(client, bytes(data))


def test_a_name_given_twice_is_refused(client, good):
    files = entries(good)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive, pytest.warns(UserWarning):
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr("stations/a.txt", files["stations/a.txt"])
    assert "stations/a.txt is in it twice" in refused(client, buffer.getvalue())


def test_too_many_files_are_refused(client, good, monkeypatch):
    monkeypatch.setattr(workspace_file, "MAX_ENTRIES", 5)
    files = entries(good)
    files.update({f"stations/x{i}.txt": b"x" for i in range(3)})
    assert "a workspace file holds at most" in refused(client, rezip(files))


def test_a_zip_bomb_is_refused_by_its_ratio_while_it_is_read(client, good):
    files = entries(good)
    files["stations/a.txt"] = b"0" * (3 * 1024 * 1024)  # deflates about 1000 times
    assert "may be a zip bomb" in refused(client, rezip(files))


def test_a_zip_bomb_is_refused_by_its_size(client, good, monkeypatch):
    monkeypatch.setattr(workspace_file, "MAX_UNPACKED_BYTES", 2000)
    assert "may be a zip bomb" in refused(client, good)


def test_a_zip_whose_header_hides_its_size_is_refused(client, good, monkeypatch):
    """The sizes are counted as the data come: a header that says less is no way round."""
    files = entries(good)
    big = b"".join(b"%d\n" % i for i in range(400_000))  # 2.6 MB, compresses about 4 times
    files["stations/a.txt"] = big
    data = bytearray(rezip(files))
    # Rewrite the uncompressed size, in the local header and the central directory, to 100.
    true = len(big).to_bytes(4, "little")
    assert data.count(true) == 2
    data = bytes(data).replace(true, (100).to_bytes(4, "little"))
    assert "cannot be read" in refused(client, data)
    monkeypatch.setattr(workspace_file, "MAX_STATION_BYTES", 1000)
    data = bytearray(rezip(files))
    assert "may be a zip bomb" in refused(client, bytes(data))


def test_malformed_json_is_refused(client, good):
    files = entries(good)
    files["workspace.json"] = b'{"format": "climpact-workspace", '
    assert "workspace.json is not valid JSON" in refused(client, rezip(files))
    files["workspace.json"] = b"[1, 2]"
    assert "does not describe a workspace" in refused(client, rezip(files))
    files["workspace.json"] = b"\xff\xfe"
    assert "is not valid JSON" in refused(client, rezip(files))


def test_a_file_of_another_format_or_a_newer_version_is_refused(client, good):
    other = with_manifest(good, lambda r: r.update(format="something-else"))
    assert "names no workspace format" in refused(client, other)
    newer = with_manifest(good, lambda r: r.update(format_version=2))
    message = refused(client, newer)
    assert "saved by a newer version of Climpact (format 2; this one reads format 1)" in message
    missing = with_manifest(good, lambda r: r.pop("format_version"))
    assert "has no format version" in refused(client, missing)


@pytest.mark.parametrize(
    ("change", "words"),
    [
        (lambda r: r["settings"].update(base_period=[2001, 2000]), "base period"),
        (lambda r: r["settings"].update(base_period="1971"), "base period"),
        (lambda r: r["settings"]["quality_thresholds"].update(jump=500), "quality thresholds"),
        (lambda r: r["settings"]["quality_thresholds"].update(jump=float("nan")), "valid JSON"),
        (lambda r: r["settings"]["indices"]["params"].update(wsdi_days=99), "index settings"),
        (lambda r: r["settings"]["indices"]["params"].update(wsdi_days=[1]), "index settings"),
        (lambda r: r["settings"]["indices"].update(plots="yes"), "output options"),
        (lambda r: r.update(stations=[]), "lists no stations"),
        (lambda r: r["stations"][0].update(name=""), "has no name"),
        (lambda r: r["stations"][0].update(latitude="-30"), "has no latitude"),
        (lambda r: r["stations"][0].update(latitude=-130), "Latitude must be between"),
        (lambda r: r["stations"][0].update(params={"evil": 1}), "index values"),
        (lambda r: r["stations"][0].update(file="stations/zzz.txt"), "is missing"),
        (lambda r: r["stations"][0].update(sha256="0" * 64), "SHA-256 differs"),
        (lambda r: r["stations"][1].update(name=r["stations"][0]["name"]), "station name"),
        (lambda r: r.update(stations=r["stations"][:1]), "stations/b.txt is not part"),
    ],
)
def test_a_manifest_out_of_range_is_refused(client, good, change, words):
    assert words in refused(client, with_manifest(good, change))


def test_an_unreadable_station_file_is_refused(client, good):
    from climpact_web.stations.models import file_digest

    files = entries(good)
    files["stations/a.txt"] = b"not a station file\n"
    record = json.loads(files["workspace.json"])
    record["stations"][0]["sha256"] = file_digest("not a station file\n")
    files["workspace.json"] = json.dumps(record).encode()
    assert "a cannot be opened: Not read" in refused(client, rezip(files))


def test_an_upload_over_the_limit_is_refused(client, good, settings):
    settings.MAX_UPLOAD_MB = 0
    settings.MAX_UPLOAD_BYTES = 100
    response = open_file(client, good)
    assert response.status_code == 413  # the middleware's limit on every upload


def test_a_refusal_by_the_hosted_limits_makes_nothing(client, good, monkeypatch):
    def full(request, change=""):
        raise Refused("active-quota:2", "You already have 2 calculations waiting or running.")

    monkeypatch.setattr("climpact_web.core.limits.check_job_quotas", full)
    before = (Workspace.objects.count(), Station.objects.count())
    response = open_file(client, good)
    assert response.status_code == 429
    assert (Workspace.objects.count(), Station.objects.count()) == before


def test_opening_needs_the_human_check_where_the_site_has_one(client, good, settings, monkeypatch):
    from climpact_web.core import limits

    settings.IS_HOSTED = True
    settings.MIN_FREE_DISK_GB = 0
    settings.TURNSTILE_SITE_KEY = settings.TURNSTILE_SECRET_KEY = "test-key"
    monkeypatch.setattr(limits, "siteverify", lambda token, ip: {"success": token == "ok"})
    assert 'class="cf-turnstile"' in client.get("/w/open/").content.decode()
    before = Workspace.objects.count()
    response = open_file(client, good)
    assert response.status_code == 400 and "could not confirm that you are a person" in (
        response.content.decode()
    )
    assert Workspace.objects.count() == before
    upload = SimpleUploadedFile("climpact_workspace.zip", good)
    response = client.post("/w/open/", {"file": upload, "cf-turnstile-response": "ok"})
    assert response.status_code == 302 and Workspace.objects.count() == before + 1
