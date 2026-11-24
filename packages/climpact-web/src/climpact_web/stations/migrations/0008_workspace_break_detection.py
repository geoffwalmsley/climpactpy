"""#365: a workspace's break detection settings (empty: the defaults)."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("stations", "0007_workspace_settings"),
    ]

    operations = [
        migrations.AddField(
            model_name="workspace",
            name="break_detection",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
