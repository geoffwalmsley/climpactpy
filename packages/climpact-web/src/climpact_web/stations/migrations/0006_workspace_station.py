"""#231: workspaces, and a Station model in place of StationAnalysis. Existing analyses are
dropped, not migrated (decided by the maintainer on #231); their folders are deleted as
stray folders once older than the retention period (:mod:`climpact_web.stations.retention`).
Their jobs are no longer kept by anything and expire as usual."""

import uuid

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0003_workspace_inputs"),
        ("stations", "0005_backfill_workspace_inputs"),
    ]

    operations = [
        migrations.CreateModel(
            name="Workspace",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("owner", models.CharField(db_index=True, max_length=64)),
                ("name", models.CharField(blank=True, max_length=100)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "updated_at",
                    models.DateTimeField(db_index=True, default=django.utils.timezone.now),
                ),
                ("base_start", models.IntegerField(default=1971)),
                ("base_end", models.IntegerField(default=2000)),
                ("qc_params", models.JSONField(blank=True, default=dict)),
                ("index_settings", models.JSONField(blank=True, default=dict)),
            ],
            options={
                "ordering": ["-updated_at"],
            },
        ),
        migrations.CreateModel(
            name="Station",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("slug", models.SlugField(max_length=60)),
                ("owner", models.CharField(db_index=True, max_length=64)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "updated_at",
                    models.DateTimeField(db_index=True, default=django.utils.timezone.now),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("upload", "Uploaded file"),
                            ("sample", "Sample data"),
                            ("batch", "From a batch"),
                        ],
                        default="upload",
                        max_length=10,
                    ),
                ),
                ("file_name", models.CharField(blank=True, max_length=255)),
                ("summary", models.JSONField(blank=True, default=dict)),
                ("file_hash", models.CharField(blank=True, max_length=64)),
                ("warnings", models.JSONField(blank=True, default=list)),
                ("station_name", models.CharField(blank=True, max_length=100)),
                ("latitude", models.FloatField(blank=True, null=True)),
                ("longitude", models.FloatField(blank=True, null=True)),
                ("base_start", models.IntegerField(default=1971)),
                ("base_end", models.IntegerField(default=2000)),
                (
                    "step",
                    models.CharField(
                        choices=[
                            ("upload", "Load data"),
                            ("qc", "Check quality"),
                            ("indices", "Calculate indices"),
                            ("results", "Results and downloads"),
                            ("sector", "Compare with sector data"),
                        ],
                        default="upload",
                        max_length=10,
                    ),
                ),
                ("qc_params", models.JSONField(blank=True, default=dict)),
                ("origin", models.JSONField(blank=True, default=dict)),
                (
                    "indices_job",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="jobs.job",
                    ),
                ),
                (
                    "qc_job",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="jobs.job",
                    ),
                ),
                (
                    "sector_job",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="jobs.job",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="stations",
                        to="stations.workspace",
                    ),
                ),
            ],
            options={
                "ordering": ["-updated_at"],
            },
        ),
        migrations.DeleteModel(
            name="StationAnalysis",
        ),
        migrations.AddConstraint(
            model_name="station",
            constraint=models.UniqueConstraint(
                fields=("workspace", "slug"), name="station_slug_unique"
            ),
        ),
    ]
