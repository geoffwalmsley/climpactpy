from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("gridded", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="griddedrun",
            name="name",
            field=models.CharField(blank=True, max_length=200),
        ),
    ]
