"""#255: a batch fills its workspace. The base period is the workspace's: a batch's own is
copied onto its workspace (made with it, so the batch is all it holds), then dropped.
``filled_job`` records the run whose stations were added to the workspace
(:mod:`climpact_web.batch.fill`); they are added when the results are next shown, not here,
as that reads the job's files."""

import django.db.models.deletion
from django.db import migrations, models


def copy_base_period(apps, schema_editor):
    BatchRun = apps.get_model("batch", "BatchRun")
    Workspace = apps.get_model("stations", "Workspace")
    for run in BatchRun.objects.all():
        Workspace.objects.filter(pk=run.workspace_id).update(
            base_start=run.base_start, base_end=run.base_end
        )


def copy_base_period_back(apps, schema_editor):
    BatchRun = apps.get_model("batch", "BatchRun")
    for run in BatchRun.objects.select_related("workspace"):
        run.base_start, run.base_end = run.workspace.base_start, run.workspace.base_end
        run.save(update_fields=["base_start", "base_end"])


class Migration(migrations.Migration):
    dependencies = [
        ("batch", "0002_workspace"),
        ("jobs", "0004_workspace_settings"),
        ("stations", "0007_workspace_settings"),
    ]

    operations = [
        migrations.RunPython(copy_base_period, copy_base_period_back),
        migrations.RemoveField(model_name="batchrun", name="base_start"),
        migrations.RemoveField(model_name="batchrun", name="base_end"),
        migrations.AddField(
            model_name="batchrun",
            name="filled_job",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="jobs.job",
            ),
        ),
    ]
