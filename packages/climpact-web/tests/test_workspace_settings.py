"""The settings belong to the workspace (#254): the base period, the quality-control
thresholds and the index settings are read from and written to the ``Workspace``; a change
marks every station's results out of date and queues their replacements as one change,
which counts as one job against the hosted limits and can be undone while it is on the way.
A station's own index values (a batch's metadata line) stay its own.

A workspace has one station until #255 fills one from a batch, so the tests build a
workspace of several stations themselves: stations made through the real flow, then moved
into one workspace."""

import pytest
from django.test import Client
from test_indices_results import defaults, finish
from test_workspace import changed, edit, in_use, page, states

from climpact_web.jobs.models import CHANGE, Job, JobStart, Status
from climpact_web.stations import calculation, workspace
from climpact_web.stations.forms import QC_DEFAULTS
from climpact_web.stations.models import Station, Workspace
from climpact_web.stations.retention import kept_jobs

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.RUNS_DIR = tmp_path / "media" / "runs"
    settings.JOB_RETENTION_DAYS = 7
    return settings


def shared_workspace(client, count=2) -> list[tuple[Station, Job, Job]]:
    """``count`` stations in use (:func:`test_workspace.in_use`) in the first one's
    workspace, each with its finished checks and run, all current."""
    stations = [in_use(client)]
    stations += [in_use(Client()) for _ in range(count - 1)]  # each in a session of its own
    space = stations[0][0].workspace
    for n, (station, qc, run) in enumerate(stations[1:], start=2):
        old = station.workspace
        Station.objects.filter(pk=station.pk).update(
            workspace=space, slug=f"station-{n}", owner=space.owner
        )
        Job.objects.filter(pk__in=[qc.pk, run.pk]).update(owner=space.owner)
        old.delete()
    out = []
    for station, qc, run in stations:
        station.refresh_from_db()
        assert workspace.section_states(station)["results"] == "done"
        out.append((station, qc, run))
    return out


def thresholds(**changes) -> dict:
    return {**{k: str(v) for k, v in QC_DEFAULTS.items()}, **changes}


# ---- the settings are the workspace's --------------------------------------------------


def test_the_sheets_edit_the_workspace(client):
    [(station, _qc, _run)] = shared_workspace(client, 1)
    edit(client, station, "base-period", {"base_start": "1981", "base_end": "2010"})
    edit(client, station, "thresholds", thresholds(jump="15"))
    space = Workspace.objects.get(pk=station.workspace_id)
    assert (space.base_start, space.base_end) == (1981, 2010)
    assert space.qc_params["jump"] == 15.0
    # The index settings are stored on the workspace when they change (#254).
    assert space.index_settings == {}
    edit(client, station, "settings", {**defaults(), "rx_days": "7", "plot_title": "Mine"})
    space.refresh_from_db()
    assert space.index_settings["params"]["rx_days"] == 7
    assert space.index_settings["plot_title"] == "Mine"
    station.refresh_from_db()
    run = station.indices_job
    assert run.params["metadata"]["base_start"] == 1981 and run.params["qc"]["jump"] == 15.0
    assert run.params["params"]["rx_days"] == 7 and run.params["plot_title"] == "Mine"
    # The sheet opens with the workspace's values.
    html = page(client, station, "inputs/settings")
    assert 'name="rx_days" value="7"' in html and 'value="Mine"' in html


def test_a_setting_changed_from_one_station_recalculates_every_station(client):
    stations = shared_workspace(client, 3)
    (first, _, first_run) = stations[0]
    response = edit(client, first, "base-period", {"base_start": "1981", "base_end": "2010"})
    assert response["Location"] == f"{first.url()}indices"
    changes = set()
    for station, qc, run in stations:
        station.refresh_from_db()
        new = station.indices_job
        assert station.qc_job == qc  # the checks do not use the base period
        assert new != run and new.status == Status.QUEUED and not new.is_speculative
        assert new.params["replaces"] == str(run.pk)
        assert new.params["metadata"]["base_start"] == 1981
        changes.add(new.params[CHANGE])
        assert workspace.section_states(station)["results"] == "stale"
        html = page(client, station)
        assert "You changed the base period to 1981–2010. These results use 1971–2000." in html
    assert len(changes) == 1  # one change, one station job per station
    assert Job.objects.filter(kind="station", status=Status.QUEUED).count() == 3
    # New thresholds: the checks and the run of every station, as the same change.
    edit(client, first, "thresholds", thresholds(jump="15"))
    queued = Job.objects.filter(status=Status.QUEUED, cancel_requested=False)
    assert sorted(queued.values_list("kind", flat=True)) == ["qc"] * 3 + ["station"] * 3
    assert len({job.params[CHANGE] for job in queued}) == 1
    # The new runs finish: every station is current again.
    for station, _qc, _run in stations:
        station.refresh_from_db()
        finish(station.indices_job)
    for station, _qc, _run in stations:
        assert workspace.section_states(station)["results"] == "done"
    assert first_run.pk not in {s.indices_job_id for s, _q, _r in stations}


def test_a_sheet_of_a_workspace_of_several_says_so(client):
    stations = shared_workspace(client, 2)
    html = page(client, stations[0][0], "inputs/base-period")
    assert "It applies to all 2 stations of this workspace." in html
    assert "You can undo the change until then." in html
    assert "It applies to" not in page(client, stations[0][0], "inputs/station")


# ---- a station's own values (a batch's metadata line) --------------------------------------


def test_a_station_keeps_its_own_index_values(client):
    (station, _qc, run), (other, _q2, _r2) = shared_workspace(client, 2)
    origin = {"params": {"wsdi_days": 3, "hdd_base": 17.0}, "job": str(run.pk)}
    Station.objects.filter(pk=station.pk).update(origin=origin)
    station.refresh_from_db()
    settings = workspace.station_settings(station)
    assert settings["params"]["wsdi_days"] == 3 and settings["params"]["csdi_days"] == 1
    assert workspace.station_settings(other)["params"]["wsdi_days"] == 1
    assert "this station's line in the batch metadata file" in page(
        client, station, "inputs/settings"
    )
    # A change to the workspace's settings applies to both; the station's own values stay.
    edit(client, other, "settings", {**defaults(), "csdi_days": "4", "wsdi_days": "2"})
    station.refresh_from_db()
    other.refresh_from_db()
    assert station.indices_job.params["params"]["wsdi_days"] == 3
    assert station.indices_job.params["params"]["csdi_days"] == 4
    assert other.indices_job.params["params"]["wsdi_days"] == 2
    # From the station's own sheet, its own value changes for it alone.
    edit(client, station, "settings", {**defaults(), "csdi_days": "4", "wsdi_days": "5"})
    station.refresh_from_db()
    other.refresh_from_db()
    assert station.origin["params"]["wsdi_days"] == 5
    assert station.indices_job.params["params"]["wsdi_days"] == 5
    assert Workspace.objects.get(pk=station.workspace_id).index_settings["params"]["wsdi_days"] == 2
    assert workspace.station_settings(other)["params"]["wsdi_days"] == 2


# ---- the hosted limits (decision 3 of #231) ----------------------------------------------


def test_a_recalculation_of_many_stations_is_one_job_for_the_quotas(client, settings):
    stations = shared_workspace(client, 3)
    first = stations[0][0]
    settings.IS_HOSTED, settings.MIN_FREE_DISK_GB = True, 0
    settings.MAX_ACTIVE_JOBS_PER_IP, settings.MAX_QUEUED_JOBS = 1, 2
    settings.MAX_DAILY_JOBS_PER_IP = 100
    starts = JobStart.objects.count()
    edit(client, first, "thresholds", thresholds(jump="15"))
    # Six jobs (the checks and the run of three stations), one start, one active job.
    queued = Job.objects.filter(status=Status.QUEUED)
    assert queued.count() == 6
    assert JobStart.objects.count() == starts + 1
    # The client's one place is taken: another change is refused, and changes nothing.
    response = edit(client, first, "base-period", {"base_start": "1981", "base_end": "2010"})
    assert response.status_code == 429
    assert "You already have 1 calculation waiting or running" in response.content.decode()
    assert Workspace.objects.get(pk=first.workspace_id).base_start == 1971
    # The daily quota counts the change once.
    settings.MAX_ACTIVE_JOBS_PER_IP = 0
    settings.MAX_QUEUED_JOBS = 0
    settings.MAX_DAILY_JOBS_PER_IP = JobStart.objects.count() + 1
    edit(client, first, "base-period", {"base_start": "1981", "base_end": "2010"})
    assert JobStart.objects.count() == settings.MAX_DAILY_JOBS_PER_IP
    response = edit(client, first, "base-period", {"base_start": "1991", "base_end": "2010"})
    assert response.status_code == 429 and "in the last 24 hours" in response.content.decode()


def test_the_default_daily_quota_allows_a_days_work():
    """#254: one start a change, whatever the number of stations; 50 a day by default."""
    from django.conf import settings

    assert settings.MAX_DAILY_JOBS_PER_IP >= 50


# ---- undo (decision 5 of #231) -----------------------------------------------------------


def test_undo_while_queued_puts_the_settings_and_the_results_back(client):
    stations = shared_workspace(client, 2)
    first = stations[0][0]
    edit(client, first, "thresholds", thresholds(jump="15"))
    html = page(client, first, "quality")
    assert "Undo the change" in html and f'action="{first.url()}undo"' in html
    queued = list(Job.objects.filter(status=Status.QUEUED))
    assert len(queued) == 4
    # The jobs a change replaced are kept while it can be undone.
    assert {str(qc.pk) for _s, qc, _r in stations} <= kept_jobs()
    response = client.post(f"{first.url()}undo", {"next": f"{first.url()}quality"})
    assert response["Location"] == f"{first.url()}quality"
    space = Workspace.objects.get(pk=first.workspace_id)
    assert space.qc_params == {} and space.undo == {}
    for job in queued:
        job.refresh_from_db()
        assert job.status == Status.CANCELLED
    for station, qc, run in stations:
        station.refresh_from_db()
        assert (station.qc_job, station.indices_job) == (qc, run)
        assert workspace.section_states(station) == {
            "quality": "usable", "results": "done", "files": "done",
        }  # fmt: skip
    html = page(client, first, "quality")
    assert "The change was undone. The earlier settings and results are back." in html
    assert "Undo the change" not in html and changed(html) == set()


def test_undo_of_new_index_settings(client):
    [(station, qc, run)] = shared_workspace(client, 1)
    edit(client, station, "settings", {**defaults(), "rx_days": "7"})
    assert states(page(client, station))["results"] == "stale"
    client.post(f"{station.url()}undo")
    station.refresh_from_db()
    assert station.indices_job == run and station.workspace.index_settings == {}
    assert states(page(client, station))["results"] == "done"


def test_undo_is_too_late_once_the_recalculation_has_finished(client):
    [(station, _qc, run)] = shared_workspace(client, 1)
    edit(client, station, "base-period", {"base_start": "1981", "base_end": "2010"})
    station.refresh_from_db()
    new = finish(station.indices_job)
    assert "Undo the change" not in page(client, station)
    response = client.post(f"{station.url()}undo", follow=True)
    assert "the change can no longer be undone" in response.content.decode()
    station.refresh_from_db()
    assert station.indices_job == new and station.workspace.base_start == 1981
    assert run != new


def test_a_change_to_a_station_forgets_the_undo(client):
    [(station, _qc, _run)] = shared_workspace(client, 1)
    edit(client, station, "base-period", {"base_start": "1981", "base_end": "2010"})
    assert Workspace.objects.get(pk=station.workspace_id).undo
    edit(client, station, "station", {"station_name": "renamed", "latitude": "0", "longitude": "0"})
    assert Workspace.objects.get(pk=station.workspace_id).undo == {}
    assert "Undo the change" not in page(client, station)


def test_undo_needs_a_post(client):
    [(station, _qc, _run)] = shared_workspace(client, 1)
    assert client.get(f"{station.url()}undo").status_code == 405
    assert calculation.undo(station.workspace) is False  # nothing to undo


def test_a_view_can_read_where_a_change_stands(client):
    """#234's run status line shows a workspace's recalculation: its jobs, how many have
    finished, and whether Undo is still offered (``workspace.change_state``)."""
    stations = shared_workspace(client, 2)
    first = stations[0][0]
    space = Workspace.objects.get(pk=first.workspace_id)
    assert workspace.change_state(space) is None
    edit(client, first, "base-period", {"base_start": "1981", "base_end": "2010"})
    space.refresh_from_db()
    state = workspace.change_state(space)
    assert (state.total, state.done, state.finished, state.can_undo) == (2, 0, False, True)
    assert {job.kind for job in state.jobs} == {"station"}
    for station, _qc, _run in stations:
        station.refresh_from_db()
        finish(station.indices_job)
        state = workspace.change_state(space)
    assert (state.done, state.failed, state.finished, state.can_undo) == (2, 0, True, False)
    calculation.forget_undo(space)
    assert workspace.change_state(space) is None
