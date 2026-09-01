from django.db import migrations, models


def seed_recovery_singleton(apps, schema_editor):
    State = apps.get_model("backup", "DeploymentRecoveryState")
    State.objects.get_or_create(pk=1, defaults={"mode": "normal"})


class Migration(migrations.Migration):
    dependencies = [("backup", "0021_host_database_identity")]

    operations = [
        migrations.AlterField(
            model_name="deploymentrecoverystate",
            name="mode",
            field=models.CharField(
                choices=[
                    ("normal", "Normal"),
                    ("target_import", "Target import"),
                    ("quiesced", "Quiesced"),
                    ("quarantined", "Quarantined"),
                ],
                default="normal",
                max_length=16,
            ),
        ),
        migrations.RunPython(seed_recovery_singleton, migrations.RunPython.noop),
    ]
