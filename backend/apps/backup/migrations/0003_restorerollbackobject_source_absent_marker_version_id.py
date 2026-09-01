from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("backup", "0002_backuparchive_archive_sha256"),
    ]

    operations = [
        migrations.AddField(
            model_name="restorerollbackobject",
            name="source_absent_marker_version_id",
            field=models.CharField(blank=True, max_length=512),
        ),
    ]
