"""The workspace migrations (#179), checked on whichever database Django is connected to:
SQLite in ``test_workspace.py``, Postgres in ``test_queue_postgres.py`` (run there in a
subprocess with that database's settings).

:func:`check` migrates the stations and jobs apps back to before #179, makes an analysis as
the code before it did (a file, linked checks and run, the run a recalculation replaces,
and an analysis opened from a batch), migrates forward, and checks the backfill: the file's
hash, each linked job's inputs, the batch's ``origin["inputs"]``, and that the workspace
sees all of it as current, as it was. It leaves the database fully migrated.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

BEFORE = [("stations", "0003_qc_params"), ("jobs", "0002_abuse_limits")]
TEXT = "1971 1 1 0.0 25.1 14.2\n1971 1 2 1.5 24.0 15.0\n"
METADATA = {"name": "Testville", "latitude": -33.9, "longitude": 151.2,
            "base_start": 1971, "base_end": 2000}  # fmt: skip
QC = {"iqr_temp": 3.0, "iqr_prec": 5.0, "prec_max": 200.0, "temp_max": 50.0,
      "flatline_days": 4, "jump": 20.0}  # fmt: skip


def check(media_root) -> None:
    from django.core.management import call_command
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    call_command("migrate", "stations", "0003", verbosity=0)
    call_command("migrate", "jobs", "0002", verbosity=0)
    old = MigrationExecutor(connection).loader.project_state(BEFORE).apps
    Analysis, Job = old.get_model("stations", "StationAnalysis"), old.get_model("jobs", "Job")

    def job(kind, **params):
        return Job.objects.create(kind=kind, owner="t", status="succeeded", params=params)

    qc = job("qc", station_file="station.txt", metadata=METADATA, qc=QC)
    settings = {"params": {"rx_days": 3}, "plot_title": "", "plots": True, "zip": True,
                "report": False}  # fmt: skip
    replaced = job("station", station_file="station.txt", metadata=METADATA, qc=QC, **settings)
    run = job("station", station_file="station.txt", metadata=METADATA, qc=QC,
              replaces=str(replaced.pk), **{**settings, "params": {"rx_days": 7}})  # fmt: skip
    batch = job("batch")
    fields = {"station_name": METADATA["name"], "latitude": METADATA["latitude"],
              "longitude": METADATA["longitude"], "qc_params": {"flatline_days": 4}}  # fmt: skip
    analysis = Analysis.objects.create(owner="t", step="results", qc_job=qc, indices_job=run,
                                       **fields)  # fmt: skip
    opened = Analysis.objects.create(
        owner="t", step="qc", origin={"batch": "b", "job": str(batch.pk), "station": "x"},
        **fields,
    )  # fmt: skip
    for a in (analysis, opened):
        folder = Path(media_root) / "stations" / str(a.pk)
        folder.mkdir(parents=True)
        (folder / "station.txt").write_text(TEXT, encoding="utf-8")

    call_command("migrate", verbosity=0)

    from climpact_web.jobs.models import Job as NewJob
    from climpact_web.stations import workspace
    from climpact_web.stations.models import StationAnalysis

    digest = hashlib.sha256(TEXT.encode()).hexdigest()
    analysis = StationAnalysis.objects.get(pk=analysis.pk)
    assert analysis.file_hash == digest
    assert analysis.qc_job.inputs == {"file": digest, "metadata": METADATA, "qc": QC}
    assert analysis.indices_job.inputs["settings"]["params"] == {"rx_days": 7}
    assert analysis.indices_job.inputs["settings"]["report"] is False
    assert NewJob.objects.get(pk=replaced.pk).inputs["settings"]["params"] == {"rx_days": 3}
    assert NewJob.objects.get(pk=batch.pk).inputs == {}  # not linked: nothing to record
    # Everything the analysis links to is current, as it was before the migration.
    assert workspace.qc_changes(analysis, analysis.qc_job) == []
    assert workspace.run_changes(analysis, analysis.indices_job) == []
    # The run it replaces has the old settings: out of date, as #178 showed it.
    assert workspace.run_changes(analysis, NewJob.objects.get(pk=replaced.pk)) == ["settings"]
    opened = StationAnalysis.objects.get(pk=opened.pk)
    assert opened.file_hash == digest
    assert opened.origin["inputs"] == {"file": digest, "metadata": METADATA, "qc": QC}
    assert workspace.run_changes(opened, NewJob.objects.get(pk=batch.pk)) == []
    # JSON lookups on the new column work on this database too.
    assert NewJob.objects.filter(inputs__file=digest).count() == 3
