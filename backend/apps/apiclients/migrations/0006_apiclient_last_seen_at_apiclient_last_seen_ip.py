from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("apiclients", "0005_apiclient_previous_secret")]

    operations = [
        migrations.AddField(
            model_name="apiclient",
            name="last_seen_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="apiclient",
            name="last_seen_ip",
            field=models.GenericIPAddressField(blank=True, null=True),
        ),
    ]
