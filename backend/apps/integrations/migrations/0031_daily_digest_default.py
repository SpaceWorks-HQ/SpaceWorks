from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integrations", "0030_notification_timing_policy")]
    operations = [
        migrations.AddField(
            model_name="notificationtimingpolicy", name="daily_digest_default",
            field=models.BooleanField(default=False),
        ),
        # An empty list deliberately disables channel-specific quiet hours, as the
        # existing API permits. Keep model validation aligned with that contract.
        migrations.AlterField(
            model_name="notificationtimingpolicy", name="channels",
            field=models.JSONField(default=list, blank=True),
        ),
    ]
