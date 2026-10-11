from django.db import migrations, models
import django.db.models.deletion


def backfill_running_since(apps, schema_editor):
    settings = apps.get_model("updates", "PlatformUpdateSettings")
    settings.objects.filter(status="running").update(running_since=models.F("updated_at"))


class Migration(migrations.Migration):
    dependencies = [
        ("updates", "0001_initial"),
        ("backup", "0026_backfill_backup_module"),
    ]

    operations = [
        migrations.AddField("platformupdatesettings", "channel", models.CharField(
            choices=[("stable", "Stable"), ("beta", "Beta")], default="stable", max_length=8,
        )),
        migrations.AddField("platformupdatesettings", "release_notes", models.TextField(blank=True)),
        migrations.AddField("platformupdatesettings", "release_url", models.URLField(blank=True)),
        migrations.AddField("platformupdatesettings", "running_since", models.DateTimeField(blank=True, null=True)),
        migrations.AddField("platformupdatesettings", "pre_update_version", models.CharField(blank=True, max_length=80)),
        migrations.AddField("platformupdatesettings", "pre_update_archive", models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
            related_name="platform_update_snapshots", to="backup.backuparchive",
        )),
        migrations.AddField("platformupdatesettings", "rollback_restore", models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
            related_name="platform_update_rollbacks", to="backup.restoreoperation",
        )),
        migrations.RunPython(backfill_running_since, migrations.RunPython.noop),
    ]
