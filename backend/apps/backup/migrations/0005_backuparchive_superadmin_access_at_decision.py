from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("backup", "0004_makerspace_archive_recipients"),
    ]

    operations = [
        migrations.AddField(
            model_name="backuparchive",
            name="superadmin_access_at_decision",
            field=models.BooleanField(null=True),
        ),
    ]
