from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hardware_requests", "0027_kiosk_replay_resolution")]
    operations = [migrations.AddField(
        model_name="hardwarerequest", name="renewal_count",
        field=models.PositiveIntegerField(default=0),
    )]
