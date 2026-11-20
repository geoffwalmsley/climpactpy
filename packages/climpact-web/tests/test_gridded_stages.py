"""A gridded run's stages while it calculates, and what to change when it fails (#294,
the GridRun board): the status line and the stages table on the Map tab, the failures'
fixes, a new start beside the results it replaces, the poll that swaps the map in, Cancel,
and starting again with the finished stages kept."""

from __future__ import annotations

import datetime as dt
import json

import pytest
from django.utils import timezone
from test_gridded_web import media, run_jobs, sample_run, setup_data  # noqa: F401

from climpact_web.gridded import stages
from climpact_web.gridded.models import GriddedRun
from climpact_web.gridded.setup_page import size_text
from climpact_web.jobs.models import Job, Status
from climpact_web.jobs.runners import STAGES_FILE, StageTimes, read_stage_times
from climpact_web.jobs.worker import MEMORY_MESSAGE

pytestmark = pytest.mark.django_db


def started(client, **changes) -> GriddedRun:
    """The sample run, started with ``changes`` to its set-up (no job run yet)."""
    run = sample_run(client)
    response = client.post(f"/gridded/{run.pk}/setup/", setup_data(run, **changes))
    assert response.status_code == 302
    run.refresh_from_db()
    return run


def write_stages(job: Job, entries, *, minutes_ago: float = 10, **extra) -> None:
    """A job's stages.json as the runner writes it: ``entries`` are ``(stage, minutes
    after the start, step)``."""
    start = timezone.now() - dt.timedelta(minutes=minutes_ago)
    data = {
        "stages": [
            {"stage": key, "at": (start + dt.timedelta(minutes=at)).isoformat(), "step": step}
            for key, at, step in entries
        ],
        **extra,
    }
    job.folder.mkdir(parents=True, exist_ok=True)
    (job.folder / STAGES_FILE).write_text(json.dumps(data))


def set_job(job: Job, **values) -> Job:
    Job.objects.filter(pk=job.pk).update(**values)
    job.refresh_from_db()
    return job


def running(job: Job, minutes_ago: float = 10, **values) -> Job:
    now = timezone.now()
    return set_job(
        job,
        status=Status.RUNNING,
        started_at=now - dt.timedelta(minutes=minutes_ago),
        heartbeat_at=now,
        worker="test-worker",
        **values,
    )


def stopped(job: Job, status=Status.FAILED, minutes_ago: float = 10, **values) -> Job:
    now = timezone.now()
    return set_job(
        job,
        status=status,
        started_at=now - dt.timedelta(minutes=minutes_ago),
        finished_at=now,
        **values,
    )


def map_tab(client, run) -> str:
    return client.get(f"/gridded/{run.pk}/").content.decode()


def rows(html: str) -> dict[str, str]:
    """Each stage row's state, by its key."""
    import re

    return dict(re.findall(r'data-stage="(\w+)" data-state="(\w+)"', html))


# ---- The stages a job records ---------------------------------------------------------------


def test_stage_times_record_when_each_stage_began(tmp_path):
    seen = []
    times = StageTimes(tmp_path / STAGES_FILE, lambda *a: seen.append(a))
    assert [s["stage"] for s in read_stage_times(tmp_path)["stages"]] == ["check"]

    class Grid:
        def blocks(self):
            return iter([(slice(0, 1), slice(0, 2))] * 4)

        def will_rechunk(self):
            return True

        def rechunk_bytes(self):
            return 600_000_000

    times.opened(Grid())
    for step in (1, 2, 3):
        times("rechunk", step, 7)
    for step in (4, 5, 6, 7):
        times("indices", step, 7)
    times("trends", 1, 2)
    data = read_stage_times(tmp_path)
    assert [(s["stage"], s["step"]) for s in data["stages"]] == [
        ("check", 0),
        ("rechunk", 0),
        ("indices", 3),
        ("trends", 0),
    ]
    assert data["blocks"] == 4 and data["copy"] is True and data["copy_bytes"] == 600_000_000
    assert data["stages"][1]["at"] == data["opened"]  # the copy began when the files were open
    assert len(seen) == 8  # every step passed on to the job's own callback


def test_a_real_run_records_its_stages(client):
    started(client, task="both", indices=["fd", "txx"])
    jobs = run_jobs()
    assert [j.status for j in jobs] == [Status.SUCCEEDED, Status.SUCCEEDED]
    thresholds, indices = (read_stage_times(j.folder) for j in jobs)
    assert [s["stage"] for s in thresholds["stages"]] == ["check", "thresholds"]
    assert [s["stage"] for s in indices["stages"]] == ["check", "indices", "trends"]
    assert indices["blocks"] >= 1 and indices["copy"] is False


# ---- The Map tab while the run calculates ---------------------------------------------------


def test_queued(client):
    run = started(client, task="both", indices=["fd"])
    html = map_tab(client, run)
    assert 'id="gridded-stages"' in html and 'role="status"' in html
    assert "<strong>Waiting to start.</strong>" in html and "hx-get=" in html
    assert f'action="/gridded/{run.pk}/cancel"' in html
    assert rows(html) == {
        "check": "waiting",
        "thresholds": "waiting",
        "indices": "waiting",
        "trends": "waiting",
    }
    assert ">What is being calculated</h2>" in html and ">All settings (Set-up)</a>" in html
    for label, value in (
        ("Files", "tmax, tmin, precip · "),
        ("Grid", "3 × 4, 1991–2010"),
        ("Base period", "1991–2010"),
        ("Indices", "1 · 2 files"),
        ("Started", "Not yet"),
    ):
        assert f"<dt>{label}</dt><dd>{value}" in html, label
    assert "It runs in the background: close this page if you like." in html
    assert 'id="gridded-map"' not in html


def test_each_stage_while_it_runs(client):
    run = started(client, indices=["fd", "txx"])
    job = run.indices_job
    # Checking the files: the job has started, nothing reported yet.
    running(job, minutes_ago=0.1)
    write_stages(job, [("check", 0, 0)], minutes_ago=0.1)
    html = map_tab(client, run)
    assert "<strong>Checking the files.</strong>" in html
    assert rows(html) == {"check": "running", "indices": "waiting", "trends": "waiting"}

    # The cell-first copy: 3 slabs, then 10 blocks counted together.
    running(job, stage="rechunk", step=1, total=13)
    write_stages(
        job,
        [("check", 0, 0), ("rechunk", 1, 0)],
        opened=(timezone.now() - dt.timedelta(minutes=9)).isoformat(),
        blocks=10,
        copy=True,
        copy_bytes=600_000_000,
    )
    html = map_tab(client, run)
    assert "<strong>Making the cell-first copy: 33%.</strong>" in html
    assert rows(html)["rechunk"] == "running" and rows(html)["check"] == "done"
    assert f"a {size_text(600_000_000)} copy laid out by cell" in html

    # The indices: block 6 of 10, with a rate, so the time left shows.
    running(job, stage="indices:fd", step=9, total=13)
    write_stages(
        job,
        [("check", 0, 0), ("rechunk", 1, 0), ("indices", 3, 3)],
        blocks=10,
        copy=True,
    )
    html = map_tab(client, run)
    assert "<strong>Calculating indices: 60%.</strong>" in html
    assert "60% · block 6 of 10" in html and "About 4 min left, 10 min so far." in html
    assert rows(html) == {
        "check": "done",
        "rechunk": "done",
        "indices": "running",
        "trends": "waiting",
    }
    assert '<td class="num code">1:00</td>' in html  # the check's time
    assert 'value="60"' in html  # the bars

    # The trends.
    running(job, stage="trends", step=3, total=12)
    write_stages(
        job,
        [("check", 0, 0), ("rechunk", 1, 0), ("indices", 3, 3), ("trends", 9, 0)],
        blocks=10,
        copy=True,
    )
    html = map_tab(client, run)
    assert "<strong>Calculating trends: 25%.</strong>" in html
    assert rows(html)["indices"] == "done" and rows(html)["trends"] == "running"
    # The run's bar says "calculating" and offers no Download all.
    assert ">calculating</span>" in html and "Download all" not in html


def test_thresholds_then_indices_is_one_table(client):
    run = started(client, task="both", indices=["fd"])
    stopped(run.thresholds_job, status=Status.SUCCEEDED)
    write_stages(run.thresholds_job, [("check", 0, 0), ("thresholds", 1, 0)])
    running(run.indices_job, stage="", minutes_ago=0.1)
    write_stages(run.indices_job, [("check", 0, 0)], minutes_ago=0.1)
    html = map_tab(client, run)
    assert html.count("<tr data-stage=") == 4  # one row a stage, not a card a job
    assert rows(html) == {
        "check": "done",
        "thresholds": "done",
        "indices": "running",
        "trends": "waiting",
    }
    # The indices job opens the files again: its row says so; the line too.
    assert "Checking the files</span>" in html and "<strong>Checking the files.</strong>" in html


def test_indices_from_a_thresholds_file(client):
    run = started(client, indices=["fd"])
    path = "/data/hist.thresholds.1971-2000.nc"
    set_job(run.indices_job, params=dict(run.indices_job.params, thresholds_file=path))
    html = map_tab(client, run)
    assert rows(html) == {
        "check": "waiting",
        "read": "waiting",
        "indices": "waiting",
        "trends": "waiting",
    }
    assert ">Read the thresholds file<" in html and "hist.thresholds.1971-2000.nc" in html
    # A thresholds file that does not fit fails that row, and says what to change.
    job = stopped(run.indices_job, error=f"{path}: missing thresholds ['tx90']")
    write_stages(job, [("check", 0, 0)])
    html = map_tab(client, run)
    assert rows(html)["read"] == "failed" and rows(html)["check"] == "done"
    assert "The run failed in the thresholds file stage." in html
    assert f'href="/gridded/{run.pk}/setup/#task-title"' in html


# ---- When it fails, or is cancelled ---------------------------------------------------------


def test_out_of_memory_names_the_setting(client):
    run = started(client, indices=["fd"], workers=2, max_values=50)
    job = stopped(run.indices_job, error=MEMORY_MESSAGE, stage="indices", step=235, total=1302)
    entries = [("check", 0, 0), ("rechunk", 1, 0), ("indices", 3, 2)]
    write_stages(job, entries, blocks=1300, copy=True)
    html = map_tab(client, run)
    head = "<strong>The run failed in the indices stage.</strong>"
    assert f"{head} <span>Nothing was written.</span>" in html
    assert 'data-announce="now"' in html and "hx-get" not in html
    assert rows(html) == {
        "check": "done",
        "rechunk": "done",
        "indices": "failed",
        "trends": "not_run",
    }
    assert "Failed in block 234 of 1,300" in html
    assert "The run ran out of memory in block 234 of 1,300." in html
    per_core, total = size_text(400e6), size_text(800e6)
    assert (
        f"Each block holds 50 million values (about {per_core} per core, {total} on 2 cores)."
        in html
    )
    assert "Lower Values read at once to 25 million, or use fewer cores" in html
    setup = f"/gridded/{run.pk}/setup/"
    assert f'href="{setup}#id_max_values"' in html and ">Change the computing settings<" in html
    assert f'href="/gridded/{run.pk}/climpact.log"' in html and "The run’s log" in html
    assert f'<a href="{setup}#id_max_values">Change the settings</a>' in html
    assert f'href="/gridded/{run.pk}/delete"' in html
    assert ">What the run calculates</h2>" in html and "It runs in the background" not in html
    assert 'id="gridded-map"' not in html


@pytest.mark.parametrize(
    ("error", "anchor", "words"),
    [
        (
            "pr: unsupported units 'm' (use kg m-2 d-1 or kg m-2 s-1)",
            "#variables-title",
            "Climpact reads temperatures in K or °C",
        ),
        (
            "tmax: a gap between a.nc, which ends on 1999-12-31, and b.nc, which starts on "
            "2001-01-01; the files of a variable must follow on with no day missing",
            "#files-title",
            "Add the missing file or choose other files",
        ),
        (
            "Not enough disk space for the cell-first copy: rechunking the input needs 9.0 GB "
            "in /tmp, 1.0 GB free.",
            "#id_rechunk",
            "turn the copy off",
        ),
        ("Something went wrong during the calculation.", "", "Check the settings on Set-up"),
    ],
)
def test_each_failure_says_what_to_change(client, error, anchor, words):
    run = started(client, indices=["fd"])
    stopped(run.indices_job, error=error)
    html = map_tab(client, run)
    assert words in html
    assert f'href="/gridded/{run.pk}/setup/{anchor}"' in html
    assert rows(html)["check"] == "failed" and rows(html)["indices"] == "not_run"


def test_cancelled(client):
    run = started(client, indices=["fd"])
    job = stopped(run.indices_job, status=Status.CANCELLED, stage="indices", step=2, total=10)
    write_stages(job, [("check", 0, 0), ("indices", 1, 0)], blocks=10)
    html = map_tab(client, run)
    assert "<strong>The run was cancelled in the indices stage.</strong>" in html
    assert rows(html)["indices"] == "cancelled" and rows(html)["trends"] == "not_run"
    assert f'<a href="/gridded/{run.pk}/setup/">Start again on Set-up</a>' in html
    assert "gridded-stages__failure" not in html and "run-status--stopped" in html


def test_cancel_stops_every_job_of_the_run(client):
    run = started(client, task="both", indices=["fd"])
    running(run.thresholds_job)
    response = client.post(f"/gridded/{run.pk}/cancel")
    assert response.status_code == 302 and response["Location"] == f"/gridded/{run.pk}/"
    run.thresholds_job.refresh_from_db()
    run.indices_job.refresh_from_db()
    assert run.thresholds_job.cancel_requested and run.indices_job.status == Status.CANCELLED
    assert "<strong>Cancelling…</strong>" in map_tab(client, run)
    assert client.get(f"/gridded/{run.pk}/cancel").status_code == 405


# ---- Starting again keeps the finished stages ----------------------------------------------


def test_starting_again_keeps_the_finished_stages(client):
    run = started(client, task="both", indices=["fd"])
    thresholds = run.thresholds_job
    params = dict(run.indices_job.params, input_files=["/no/such/file.nc"])
    Job.objects.filter(pk=run.indices_job.pk).update(params=params)
    jobs = run_jobs()
    assert [j.status for j in jobs] == [Status.SUCCEEDED, Status.FAILED]
    html = map_tab(client, run)
    assert "The thresholds file is kept." in html
    assert "starting again with the same files and base period begins at the indices" in html
    assert rows(html)["thresholds"] == "done"

    # Starting again with the same settings (other computing ones) runs the indices only.
    client.post(
        f"/gridded/{run.pk}/setup/", setup_data(run, task="both", indices=["fd"], workers=1)
    )
    run.refresh_from_db()
    assert run.thresholds_job == thresholds and run.indices_job.status == Status.QUEUED
    html = map_tab(client, run)
    assert rows(html)["thresholds"] == "kept" and "Kept from the last start" in html
    (job,) = run_jobs()
    assert job.kind == "gridded-indices" and job.status == Status.SUCCEEDED
    # With another base period, the thresholds run again.
    run.refresh_from_db()
    client.post(
        f"/gridded/{run.pk}/setup/", setup_data(run, task="both", indices=["fd"], base_start=1995)
    )
    run.refresh_from_db()
    assert run.next_thresholds_job is not None and run.next_thresholds_job != thresholds


# ---- A new start beside the results it replaces (#293) --------------------------------------


def test_calculating_again_beside_the_old_results(client):
    run = started(client, indices=["fd"])
    run_jobs()
    run.refresh_from_db()
    client.post(f"/gridded/{run.pk}/setup/", setup_data(run, indices=["fd"], base_start=1995))
    run.refresh_from_db()
    pending = running(run.next_indices_job, stage="indices", step=2, total=4)
    write_stages(pending, [("check", 0, 0), ("indices", 1, 0)], blocks=4)
    html = map_tab(client, run)
    assert 'id="gridded-stages"' in html and 'id="gridded-map"' in html  # the old map stays
    assert html.index('id="gridded-stages"') < html.index('id="gridded-map"')
    assert "<strong>Calculating indices: 50%.</strong>" in html
    assert "Map and Files show the run of " in html and "until this one has finished" in html
    assert ">Stages of the new start</summary>" in html and "again=map" in html
    assert ">What is being calculated</h2>" not in html

    # It finishes: the poll's answer replaces the old map with the new one.
    Job.objects.filter(pk=pending.pk).update(status=Status.QUEUED, started_at=None)
    (job,) = run_jobs()
    assert job.status == Status.SUCCEEDED
    response = client.get(
        f"/gridded/{run.pk}/progress?was_active=1&again=map", HTTP_HX_REQUEST="true"
    )
    html = response.content.decode()
    assert html.index('hx-swap-oob="delete:#gridded-map"') < html.index('id="gridded-map"')
    assert ">base 1995–2010<" in html


def test_a_failed_new_start_keeps_the_old_map(client):
    run = started(client, indices=["fd"])
    run_jobs()
    run.refresh_from_db()
    client.post(f"/gridded/{run.pk}/setup/", setup_data(run, indices=["fd"], base_start=1995))
    run.refresh_from_db()
    job = stopped(run.next_indices_job, error=MEMORY_MESSAGE, stage="indices", step=1, total=4)
    write_stages(job, [("check", 0, 0), ("indices", 1, 0)], blocks=4)
    html = map_tab(client, run)
    assert "<strong>The last start failed in the indices stage.</strong>" in html
    assert "Map and Files still show the run of " in html
    assert 'id="gridded-map"' in html
    assert '<details class="disclosure gridded-stages__again" open>' in html
    assert "hx-get" not in html


# ---- The poll ---------------------------------------------------------------------------------


def test_the_poll_follows_the_run_and_updates_the_bar_when_it_stops(client):
    run = started(client, indices=["fd"])
    url = f"/gridded/{run.pk}/progress?was_active=1"
    html = client.get(url, HTTP_HX_REQUEST="true").content.decode()
    assert html.lstrip().startswith('<div id="gridded-stages"') and "hx-swap-oob" not in html
    stopped(run.indices_job, error="pr: unsupported units 'm'")
    html = client.get(url, HTTP_HX_REQUEST="true").content.decode()
    assert "The run failed in the check stage." in html and "hx-get" not in html
    assert 'hx-swap-oob="innerHTML:[data-context-bar] .context-bar__provenance"' in html
    assert "Run again with other files" in html  # the bar's actions, now that it stopped


def test_stage_rows_of_a_job_run_before_the_stages_were_recorded(client):
    run = started(client, indices=["fd"])
    run_jobs()
    run.refresh_from_db()
    (run.indices_job.folder / STAGES_FILE).unlink()
    table = stages.stage_rows(None, run.indices_job)
    assert [(r.key, r.state) for r in table] == [
        ("check", "done"),
        ("indices", "done"),
        ("trends", "done"),
    ]
    assert table[1].time  # the job's whole time, on its main stage
