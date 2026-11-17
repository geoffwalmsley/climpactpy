"""The workspace migration (#231), checked on whichever database Django is connected to:
SQLite in ``test_workspace.py``, Postgres in ``test_queue_postgres.py`` (run there in a
subprocess with that database's settings).

:func:`check` migrates the stations and batch apps back to before #231, makes an analysis
and a batch as the code before it did, with a job each, migrates forward, and checks that
the analysis and batch are dropped (the maintainer's decision on #231) while their jobs
stay, and that the new models work: a new station makes a workspace of one with a slug, a
new batch a workspace of its own, and JSON lookups on the workspace's settings work. It
leaves the database fully migrated.
"""

from __future__ import annotations

BEFORE = [("stations", "0005_backfill_workspace_inputs"), ("batch", "0001_initial")]


def check(media_root) -> None:
    from django.core.management import call_command
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    call_command("migrate", "batch", "0001", verbosity=0)
    call_command("migrate", "stations", "0005", verbosity=0)
    old = MigrationExecutor(connection).loader.project_state(BEFORE).apps
    Analysis, Batch = (
        old.get_model("stations", "StationAnalysis"),
        old.get_model("batch", "BatchRun"),
    )
    Job = old.get_model("jobs", "Job")
    run = Job.objects.create(kind="station", owner="t", status="succeeded")
    batch_job = Job.objects.create(kind="batch", owner="t", status="succeeded")
    Analysis.objects.create(owner="t", station_name="Testville", indices_job=run)
    Batch.objects.create(owner="t", metadata_name="metadata.txt", job=batch_job)

    call_command("migrate", verbosity=0)

    from climpact_web.batch.models import BatchRun
    from climpact_web.jobs.models import Job as NewJob
    from climpact_web.stations.models import Station, Workspace

    assert not BatchRun.objects.exists() and not Station.objects.exists()
    assert NewJob.objects.filter(pk__in=[run.pk, batch_job.pk]).count() == 2

    station = Station.objects.create(owner="t", station_name="Sydney Observatory Hill")
    assert station.slug == "sydney-observatory-hill"
    assert station.workspace.owner == "t" and station.workspace.display_name == str(station)
    batch = BatchRun.objects.create(owner="t", metadata_name="metadata.txt")
    assert batch.workspace_id != station.workspace_id
    Workspace.objects.filter(pk=station.workspace_id).update(qc_params={"jump": 25.0})
    assert Workspace.objects.filter(qc_params__jump=25.0).count() == 1
