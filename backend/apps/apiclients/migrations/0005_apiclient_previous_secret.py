from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("apiclients", "0004_legacy_v1_scopes")]

    operations = [
        migrations.AddField(
            model_name="apiclient",
            name="previous_secret_encrypted",
            field=models.BinaryField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="apiclient",
            name="previous_secret_valid_until",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
