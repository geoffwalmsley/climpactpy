"""#254: the jobs one change to a workspace queues count as one start for the daily quota;
a start names its change."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0003_workspace_inputs"),
    ]

    operations = [
        migrations.AddField(
            model_name="jobstart",
            name="change",
            field=models.CharField(blank=True, max_length=36),
        ),
    ]
