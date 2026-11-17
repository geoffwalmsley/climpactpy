"""#231: a batch fills a workspace. Existing batches are dropped, not migrated (decided by
the maintainer on #231): their rows are deleted here, and their folders as stray folders
once older than the retention period (:mod:`climpact_web.batch.retention`)."""

import django.db.models.deletion
from django.db import migrations, models


def drop_batches(apps, schema_editor):
    apps.get_model("batch", "BatchRun").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("batch", "0001_initial"),
        ("stations", "0006_workspace_station"),
    ]

    operations = [
        migrations.RunPython(drop_batches, migrations.RunPython.noop),
        migrations.AddField(
            model_name="batchrun",
            name="workspace",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="batches",
                to="stations.workspace",
            ),
            preserve_default=False,
        ),
    ]
