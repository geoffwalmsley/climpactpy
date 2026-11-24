"""Break detection's settings (#367, the BreakSettings board): the fourth item of Workspace
settings and its form; applying it reruns each station's checks' job alone, with its
progress and Undo on Workspace settings and the overview; the station history file read
when chosen, or refused with the line that is wrong, kept with the workspace under its
SHA-256, in the workspace file and copied with a station; the Stations table's Possible
breaks column."""

import hashlib
import io
import json
import re
import zipfile
from html import unescape
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from test_add_stations import meta_line, review_url, stage
from test_batch import HEADER, media, station  # noqa: F401
from test_workspace import in_use
from test_workspace_overview import status_line

from climpact_web.jobs.models import Job, Status
from climpact_web.jobs.worker import claim, run_job
from climpact_web.stations import break_settings, breaks, overview, workspace, workspace_file
from climpact_web.stations.models import Station, Workspace

pytestmark = pytest.mark.django_db

DEFAULTS = {
    "on": "on",
    "methods": ["pettitt", "snht", "pmf", "pmt"],
    "variables": ["TX", "TN", "PRCP"],
    "series": ["annual", "monthly"],
    "level": "0.95",
    "min_years": "5",
}
HISTORY = (
    "date,event,station\n1987-11,Screen moved 20 m east,a\n1998-01,New sensors,a\n2001,Moved,c\n"
)


def run_queued() -> list[Job]:
    """Run every job waiting, in turn."""
    done = []
    while (job := claim("test-worker")) is not None:
        done.append(run_job(job))
    return done


def two_stations(client):
    """A workspace of two stations, a and b, added on Add stations, checked and
    calculated."""
    meta = HEADER + meta_line("a.txt") + meta_line("b.txt", "-31", "151")
    run = stage(client, meta__txt=meta, a__txt=station(seed=1), b__txt=station(seed=2))
    client.post(
        review_url(run),
        {"intent": "settings", "base_start": "2000", "base_end": "2001", "workers": "1"},
    )
    data = {"intent": "add", "file-0": "a.txt", "name-0": "a", "file-1": "b.txt", "name-1": "b"}
    assert client.post(review_url(run), data).status_code == 302
    assert all(job.status == Status.SUCCEEDED for job in run_queued())
    url = f"/w/{run.workspace_id}/"
    assert client.get(url).status_code == 200  # records how the batch went
    return Workspace.objects.get(pk=run.workspace_id), url


def upload(text: str, name: str = "nsw_history.csv") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, text.encode(), content_type="text/csv")


def text(html: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


# ---- the settings list and the form --------------------------------------------------------


def test_workspace_settings_list_break_detection(client):
    space, url = two_stations(client)
    html = client.get(f"{url}settings/").content.decode()
    assert "Settings for all 2 stations." in html
    items = re.findall(r'data-setting="([\w-]+)"', html)
    assert items == ["base-period", "thresholds", "settings", "breaks"]
    item = html.split('data-setting="breaks"')[1].split("</div>")[0]
    assert "Break detection" in item and f'href="{url}settings/breaks"' in item
    assert text(item).count(
        "On · Pettitt, SNHT, PMF, PMT · TX TN PRCP · annual and monthly · 95% · segments of 5+ "
        "years · no station history."
    )
    # The form: each field with what the workspace has (the defaults), and what applying
    # updates.
    html = client.get(f"{url}settings/breaks").content.decode()
    assert f'action="{url}settings/breaks"' in html and 'enctype="multipart/form-data"' in html
    assert re.search(r'<input type="checkbox" name="on"[^>]*checked', html)
    for m in DEFAULTS["methods"]:
        assert re.search(rf'value="{m}"[^>]*checked', html)
    assert re.search(r'<option value="0.95" selected>95%</option>', html)
    assert '<option value="0.9999">99.99%</option>' in html
    assert re.search(r'name="min_years" value="5"', html)
    assert "PMT</strong> <span>· RHtests&#x27; penalised maximal t test" in html
    assert "Applying looks for breaks again in all 2 stations, about 5 s." in html
    assert "The checks and the indices don&#x27;t change." in html
    assert "or drop it here · no file" in text(html)
    assert "<code>date,event</code>" in html  # the hint's columns, in mono


def test_applying_reruns_the_checks_only_with_undo(client):
    space, url = two_stations(client)
    stations = {s.station_name: s for s in space.stations.all()}
    before = {n: (s.qc_job_id, s.indices_job_id) for n, s in stations.items()}
    verdicts = {n: workspace.section_states(s)["quality"] for n, s in stations.items()}
    response = client.post(f"{url}settings/breaks", {**DEFAULTS, "level": "0.9", "min_years": "3"})
    assert response.status_code == 302 and response["Location"] == f"{url}settings/"
    space.refresh_from_db()
    assert space.break_detection == {
        **breaks.DEFAULTS,
        "level": 0.9,
        "min_years": 3,
        "history": None,
    }
    assert space.undo["fields"] == ["break_detection"]
    for name, s in stations.items():
        s.refresh_from_db()
        assert s.qc_job_id != before[name][0] and s.qc_job.status == Status.QUEUED
        assert s.qc_job.params["homogeneity"]["level"] == 0.9
        assert s.indices_job_id == before[name][1]  # the indices don't change
        # The checks stay current: their verdict stays, only the breaks are looked for.
        assert workspace.section_states(s)["quality"] == verdicts[name]
    # Quality: the checks as they were, no progress panel, the breaks out of date; it
    # polls for the new ones.
    a = stations["a"]
    html = client.get(f"{a.url()}quality").content.decode()
    assert "Running the quality checks" not in html and 'id="qc-progress"' in html
    assert "Looking for breaks" in html and "Checking quality" not in html
    # Workspace settings: the change's progress and Undo, polled.
    html = client.get(f"{url}settings/").content.decode()
    line = text(
        html.split('id="settings-change"')[1].split('role="status">')[1].split("</form>")[0]
    )
    assert line.startswith(
        "Break detection changed. Looking for breaks in 2 stations: 0 of 2 done. The indices "
        "don't change."
    )
    assert f'hx-get="{url}settings/progress"' in html
    assert f'<input type="hidden" name="next" value="{url}settings/">' in html
    assert "Undo it from the run status line on the overview" not in html
    # The overview: the run status line, the verdicts, and the breaks being looked for.
    html = client.get(url).content.decode()
    assert status_line(html).startswith(
        "running: Looking for breaks: 0 of 2 stations done. The indices don&#x27;t change."
    )
    assert "Undo the change" in html and "hx-get" in html.split('id="workspace-progress"')[1][:300]
    cells = re.findall(r'data-breaks="(\w+)"', html)
    assert cells == ["checking", "checking"]
    # Undo, from Workspace settings, returns there with the settings and checks as before.
    response = client.post(f"{url}undo", {"next": f"{url}settings/"})
    assert response["Location"] == f"{url}settings/"
    space.refresh_from_db()
    assert space.break_detection == {} and space.undo == {}
    for name, s in stations.items():
        s.refresh_from_db()
        assert (s.qc_job_id, s.indices_job_id) == before[name]
    # Undo refuses an address elsewhere.
    client.post(f"{url}settings/breaks", {**DEFAULTS, "level": "0.99"})
    response = client.post(f"{url}undo", {"next": "https://example.com/"})
    assert response["Location"] == url


def test_the_line_says_how_it_went(client):
    space, url = two_stations(client)
    client.post(f"{url}settings/breaks", {**DEFAULTS, "series": ["annual"]})
    assert len(run_queued()) == 2
    html = client.get(f"{url}settings/progress").content.decode()
    assert "hx-get" not in html
    assert text(html) == (
        "Break detection changed. Breaks looked for again in 2 of 2 stations. The indices "
        "didn't change."
    )
    # Once it has finished, the page itself shows no line, and the overview the usual one.
    assert 'id="settings-change"' not in client.get(f"{url}settings/").content.decode()
    assert status_line(client.get(url).content.decode()).startswith("done: 2 stations")
    # Applying the same settings again changes nothing.
    response = client.post(f"{url}settings/breaks", {**DEFAULTS, "series": ["annual"]})
    assert response.status_code == 302 and not Job.objects.filter(status=Status.QUEUED).exists()


def test_an_empty_choice_is_refused_inline(client):
    space, url = two_stations(client)
    html = client.post(f"{url}settings/breaks", {**DEFAULTS, "methods": []}).content.decode()
    assert "Choose at least one test." in html and 'id="id_methods_error"' in html
    html = client.post(
        f"{url}settings/breaks", {**DEFAULTS, "variables": ["PRCP"], "series": ["monthly"]}
    ).content.decode()
    assert "PRCP is tested yearly only: choose Annual, or TX or TN." in html
    for bad in ({"level": "0.5"}, {"min_years": "0"}, {"min_years": "51"}):
        assert client.post(f"{url}settings/breaks", {**DEFAULTS, **bad}).status_code == 200
    space.refresh_from_db()
    assert space.break_detection == {} and not space.undo
    # Off, the others keep what they hold, even nothing.
    off = {k: v for k, v in DEFAULTS.items() if k != "on"}
    response = client.post(f"{url}settings/breaks", {**off, "methods": [], "level": "0.99"})
    assert response.status_code == 302
    space.refresh_from_db()
    assert space.break_detection["on"] is False and space.break_detection["methods"] == []
    assert space.break_detection["level"] == 0.99
    assert break_settings.summary(space) == "Off."
    html = client.get(f"{url}settings/breaks").content.decode()
    assert not re.search(r'name="methods" value="\w+"[^>]*checked', html)
    assert re.search(r'<option value="0.99" selected>', html)


def test_off_hides_the_column(client):
    space, url = two_stations(client)
    run_queued()
    assert "Possible breaks" in client.get(url).content.decode()
    off = {k: v for k, v in DEFAULTS.items() if k != "on"}
    client.post(f"{url}settings/breaks", off)
    html = client.get(url).content.decode()
    assert "Possible breaks" not in html and "data-breaks=" not in html


# ---- the station history file ---------------------------------------------------------------


def test_a_history_file_is_read_when_chosen(client):
    space, url = two_stations(client)
    response = client.post(f"{url}settings/breaks/history", {"history": upload(HISTORY)})
    html = response.content.decode()
    assert (
        '<span class="code">nsw_history.csv</span> · <strong>3 events for 2 stations</strong>'
        in html
    )
    assert re.findall(r'<td class="code">([\d-]+)</td>', html) == ["1987-11", "1998-01", "2001"]
    assert "a 2, c 1 · b has none." in text(html)
    assert "Replace" in html and 'name="remove_history"' in html and "history_sha" not in html
    # Nothing is kept until the form is applied.
    assert not breaks.history_dir(space).exists()
    # An event naming no station applies to none, and says so.
    html = client.post(
        f"{url}settings/breaks/history", {"history": upload("date,event,station\n1990,x,\n")}
    ).content.decode()
    assert "no station 1 · a and b have none." in text(html)
    # Without a station column: for every station.
    html = client.post(
        f"{url}settings/breaks/history", {"history": upload("date,event\n1990,Moved\n")}
    ).content.decode()
    assert "1 event for every station" in html and "has none" not in html
    # Refused, with the line that is wrong.
    bad = "date,event\n1956-12,Moved\n\n1997/06,New screen\n"
    html = client.post(f"{url}settings/breaks/history", {"history": upload(bad)}).content.decode()
    assert "nsw_history.csv</span> · not used" in html and 'role="alert"' in html
    assert "Line 4: date <code>1997/06</code> is not YYYY-MM-DD, YYYY-MM or YYYY." in html
    assert "Choose another file" in html
    # Nothing chosen: the workspace's own (none).
    html = client.post(f"{url}settings/breaks/history").content.decode()
    assert "Choose file" in html


@pytest.mark.parametrize(
    ("content", "problem"),
    [
        ("when,what\n2000,x\n", "The station history needs the columns date and event."),
        ("date,event\n2000,a,b\n", "Line 2: more fields than columns"),
        ("date,event\n2000-13,x\n", "Line 2: date"),
        ("date,event,station\n2000,x,a\n20001,y,b\n", "Line 3: date"),
    ],
)
def test_history_problems(content, problem):
    history = break_settings.read_history(content.encode(), "h.csv")
    assert not history.ok and problem in history.error
    latin = break_settings.read_history("date,event\n2000,Déménagé\n".encode("latin-1"), "h")
    assert "not UTF-8" in latin.error
    big = break_settings.read_history(b"date,event\n" + b"2000,x\n" * 200_000, "h")
    assert "larger than 1,024 kB" in big.error


def test_the_history_reader_agrees_with_the_core(tmp_path):
    from climpact.homogeneity.detect import read_station_history

    files = [
        "date,event\n1987-11,Moved\n1998-01-15,New sensors\n2001,Fence\n",
        "﻿Date , Event ,Station\n1987,Moved,a\n1990,Other,b\n",
        'date,event\n1987,"Moved, 20 m east"\n',
        "date,event\n1987,a,b\n",
        "date,event\n87-11,Moved\n",
        "event,station\n1987,a\n",
    ]
    for content in files:
        path = tmp_path / "h.csv"
        path.write_text(content, encoding="utf-8")
        history = break_settings.read_history(content.encode(), "h.csv")
        try:
            core = read_station_history(path, "a")
        except ValueError as exc:
            core_error = str(exc)
            assert not history.ok, content
            line = re.search(r"line (\d+)", core_error)
            if line:
                assert f"Line {line.group(1)}:" in history.error, (content, core_error)
        else:
            assert history.ok, (content, history.error)
            mine = [e for e in history.events if not history.has_station or e.station == "a"]
            assert [e.text for e in mine] == [e.text for e in core]


def test_a_history_file_reaches_the_checks_and_can_be_replaced_or_removed(client):
    space, url = two_stations(client)
    form = {**DEFAULTS, "history": upload(HISTORY)}
    assert client.post(f"{url}settings/breaks", form).status_code == 302
    space.refresh_from_db()
    sha = hashlib.sha256(HISTORY.encode()).hexdigest()
    assert space.break_detection["history"] == {
        "name": "nsw_history.csv",
        "sha256": sha,
        "events": 3,
        "stations": 2,
    }
    assert breaks.history_path(space).read_text() == HISTORY
    assert break_settings.summary(space).endswith("· history: 3 events for 2 stations.")
    for s in space.stations.all():
        assert s.qc_job.params["station_history"] == breaks.HISTORY_FILE
        assert (s.qc_job.input_dir / breaks.HISTORY_FILE).read_text() == HISTORY
    # The form shows it, with Replace and Remove.
    html = client.get(f"{url}settings/breaks").content.decode()
    assert "3 events for 2 stations" in html and "Screen moved 20 m east" in html
    run_queued()
    # Replaced: the earlier file stays while the change can be undone, for Undo.
    other = "date,event\n1990,Moved\n"
    client.post(f"{url}settings/breaks", {**DEFAULTS, "history": upload(other, "b.csv")})
    space.refresh_from_db()
    assert breaks.history_path(space).read_text() == other
    assert sorted(p.name for p in breaks.history_dir(space).iterdir()) == sorted(
        [f"{sha}.csv", f"{hashlib.sha256(other.encode()).hexdigest()}.csv"]
    )
    client.post(f"{url}undo")
    space.refresh_from_db()
    assert breaks.history_path(space).read_text() == HISTORY
    # Removed: the settings are the first ones again, whose checks each station has
    # already (``workspace.settle``), so nothing runs and the files go.
    response = client.post(f"{url}settings/breaks", {**DEFAULTS, "remove_history": "on"})
    space.refresh_from_db()
    assert space.break_detection == {} and breaks.history_path(space) is None
    assert not space.undo and not list(breaks.history_dir(space).iterdir())
    for s in space.stations.all():
        assert s.qc_job.status == Status.SUCCEEDED and "station_history" not in s.qc_job.params
    html = client.get(response["Location"]).content.decode()
    assert "Break detection changed. Each station has its breaks for these settings" in html


def test_a_form_problem_keeps_the_file_chosen(client):
    space, url = two_stations(client)
    response = client.post(
        f"{url}settings/breaks", {**DEFAULTS, "methods": [], "history": upload(HISTORY)}
    )
    html = response.content.decode()
    sha = hashlib.sha256(HISTORY.encode()).hexdigest()
    assert response.status_code == 200 and "Choose at least one test." in html
    assert f'name="history_sha" value="{sha}"' in html and "3 events for 2 stations" in html
    # Sent again without choosing the file again: it is used.
    client.post(
        f"{url}settings/breaks", {**DEFAULTS, "history_sha": sha, "history_name": "nsw.csv"}
    )
    space.refresh_from_db()
    assert space.break_detection["history"]["sha256"] == sha
    assert space.break_detection["history"]["name"] == "nsw.csv"
    # A bad file is refused, and nothing changes.
    response = client.post(
        f"{url}settings/breaks", {**DEFAULTS, "history": upload("date,event\nx,y\n")}
    )
    assert response.status_code == 200 and "Line 2: date" in response.content.decode()
    assert Workspace.objects.get(pk=space.pk).break_detection == space.break_detection


# ---- the Stations table ------------------------------------------------------------------------


def test_the_stations_table_flags_the_breaks(client):
    sydney, _qc, _run = in_use(client)
    space = sydney.workspace
    (row,) = overview.rows(space, sydney.owner)
    assert row.breaks.state == "found" and row.breaks.text == "TX TN PRCP"
    assert row.breaks.url == f"{sydney.url('qc')}?show=breaks-tx-annual#detail-breaks-tx-annual"
    found = breaks.flag(sydney.qc_job)
    assert row.breaks.title == (
        f"Possible breaks in TX TN PRCP, found by {found.found_by} of {found.tested} tests. "
        "The data are not adjusted."
    )
    assert found.tested == 20 and not found.untested and row.breaks.note == ""
    # The verdict stays apart.
    assert row.quality.state == "usable"


def test_the_breaks_cell_states(monkeypatch):
    one = SimpleNamespace(qc_job=None, url=lambda section: "/w/x/s/quality")
    checking = overview._breaks(one, overview.Quality("checking", "Checking…"))
    assert (checking.state, checking.text) == ("checking", "Checking…")
    flags = {
        "none": breaks.Flag((), "", "", 0, 17, 3),
        "found": breaks.Flag(("TN",), "breaks-tn-monthly", "detail-x", 2, 17, 3),
    }
    monkeypatch.setattr(workspace, "shown_qc", lambda s: "job")
    monkeypatch.setattr(workspace, "breaks_changes", lambda s, job: [])
    quiet = overview.Quality("ready", "Ready")
    monkeypatch.setattr(breaks, "flag", lambda job: flags["none"])
    cell = overview._breaks(one, quiet)
    assert (cell.state, cell.text, cell.note) == ("none", "none", " · 3 not tested")
    monkeypatch.setattr(breaks, "flag", lambda job: flags["found"])
    cell = overview._breaks(one, quiet)
    assert (cell.text, cell.note, cell.label) == (
        "TN",
        " · 3 not tested",
        ", found by 2 of 17 tests",
    )
    monkeypatch.setattr(workspace, "breaks_changes", lambda s, job: ["breaks"])
    assert overview._breaks(one, quiet).note == " · 3 not tested · out of date"
    monkeypatch.setattr(breaks, "flag", lambda job: None)
    assert overview._breaks(one, quiet).text == "–"


# ---- kept with the workspace ---------------------------------------------------------------


def test_the_workspace_file_keeps_break_detection(client):
    space, url = two_stations(client)
    client.post(f"{url}settings/breaks", {**DEFAULTS, "level": "0.99", "history": upload(HISTORY)})
    run_queued()
    space.refresh_from_db()
    buffer = io.BytesIO()
    owner = space.owner
    workspace_file.write(space, owner, [], buffer)
    archive = zipfile.ZipFile(buffer)
    record = json.loads(archive.read("workspace.json"))
    assert record["format_version"] == 2
    assert record["settings"]["break_detection"] == {
        **{k: v for k, v in breaks.DEFAULTS.items()},
        "level": 0.99,
        "station_history": {
            "file": "station_history.csv",
            "name": "nsw_history.csv",
            "sha256": hashlib.sha256(HISTORY.encode()).hexdigest(),
        },
    }
    assert archive.read("station_history.csv").decode() == HISTORY
    opened = workspace_file.read(io.BytesIO(buffer.getvalue()))
    assert opened.break_detection == space.break_detection and opened.history == HISTORY.encode()
    # Changed since it was saved: refused.
    tampered = io.BytesIO()
    with zipfile.ZipFile(tampered, "w") as out:
        for info in archive.infolist():
            data = archive.read(info)
            out.writestr(
                info, data + b"2003,x,a\n" if info.filename.endswith("history.csv") else data
            )
    with pytest.raises(workspace_file.NotAWorkspaceFile, match="SHA-256 differs"):
        workspace_file.read(io.BytesIO(tampered.getvalue()))
    # A file of format 1 has no break detection: the defaults.
    old = io.BytesIO()
    record["format_version"] = 1
    del record["settings"]["break_detection"]
    with zipfile.ZipFile(old, "w") as out:
        for info in archive.infolist():
            if info.filename == "workspace.json":
                out.writestr(info, json.dumps(record))
            elif info.filename != "station_history.csv":
                out.writestr(info, archive.read(info))
    opened = workspace_file.read(io.BytesIO(old.getvalue()))
    assert opened.break_detection == {} and opened.history is None


def test_opening_and_copying_bring_the_history_file(client):
    space, url = two_stations(client)
    client.post(
        f"{url}settings/breaks", {**DEFAULTS, "series": ["annual"], "history": upload(HISTORY)}
    )
    run_queued()
    space.refresh_from_db()
    buffer = io.BytesIO()
    workspace_file.write(space, space.owner, [], buffer)
    response = client.post(
        "/w/open/", {"file": SimpleUploadedFile("climpact_workspace.zip", buffer.getvalue())}
    )
    assert response.status_code == 302, response.content.decode()[:2000]
    opened = Workspace.objects.exclude(pk=space.pk).get()
    assert opened.break_detection == space.break_detection
    assert breaks.history_path(opened).read_text() == HISTORY
    for s in opened.stations.all():
        if s.qc_job is not None:
            assert s.qc_job.params["homogeneity"]["series"] == "annual"
            assert (s.qc_job.input_dir / breaks.HISTORY_FILE).read_text() == HISTORY
    # Copy a station to a new workspace: the settings and the file go with it.
    a = space.stations.get(station_name="a")
    response = client.post(a.url("copy"), {"target": "new"})
    assert response.status_code == 302
    copy = Station.objects.exclude(workspace__in=[space, opened]).get()
    assert copy.workspace.break_detection == space.break_detection
    assert breaks.history_path(copy.workspace).read_text() == HISTORY
    assert copy.qc_job.params["station_history"] == breaks.HISTORY_FILE
