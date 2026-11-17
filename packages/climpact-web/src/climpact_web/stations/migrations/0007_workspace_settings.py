"""#254: the base period, the quality-control thresholds and the index settings are the
workspace's. A station made under #253 kept its own base period and thresholds, and its
index settings were those of its latest run: they are copied onto its workspace (a
workspace of one, so nothing is lost) before the station's fields are removed. The reverse
copies the workspace's base period and thresholds back onto each of its stations.

The workspace also keeps the last change to its settings while it can be undone (``undo``),
and a job start for the daily quota names the change it belongs to (``jobs`` 0004)."""

from django.db import migrations, models


def settings_of(params):
    p = params or {}
    return {
        "params": p.get("params") or {},
        "plot_title": p.get("plot_title") or "",
        "plots": bool(p.get("plots", True)),
        "zip": bool(p.get("zip", True)),
        "report": bool(p.get("report", True)),
    }


def to_workspace(apps, schema_editor):
    Station = apps.get_model("stations", "Station")
    for station in Station.objects.select_related("workspace", "indices_job"):
        space = station.workspace
        space.base_start, space.base_end = station.base_start, station.base_end
        space.qc_params = station.qc_params or {}
        job = station.indices_job
        if job is not None and job.kind == "station" and (job.params or {}).get("params"):
            space.index_settings = settings_of(job.params)
        space.save(update_fields=["base_start", "base_end", "qc_params", "index_settings"])


def to_stations(apps, schema_editor):
    Station = apps.get_model("stations", "Station")
    for station in Station.objects.select_related("workspace"):
        space = station.workspace
        station.base_start, station.base_end = space.base_start, space.base_end
        station.qc_params = space.qc_params or {}
        station.save(update_fields=["base_start", "base_end", "qc_params"])


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0004_workspace_settings"),
        ("stations", "0006_workspace_station"),
    ]

    operations = [
        migrations.RunPython(to_workspace, to_stations),
        migrations.RemoveField(model_name="station", name="base_end"),
        migrations.RemoveField(model_name="station", name="base_start"),
        migrations.RemoveField(model_name="station", name="qc_params"),
        migrations.AddField(
            model_name="workspace",
            name="undo",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
