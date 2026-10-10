from django.db import migrations, models


FEATURE_CHOICES = [
    ("hardware_requests", "Hardware requests"),
    ("printing", "Printing"),
    ("events", "Events"),
    ("bookings", "Bookings"),
    ("maintenance", "Maintenance"),
    ("members", "Members"),
    ("api_access", "API access"),
]


class Migration(migrations.Migration):
    dependencies = [("integrations", "0025_webhook_channel")]

    operations = [
        migrations.AlterField(
            model_name=model_name,
            name="feature",
            field=models.CharField(choices=FEATURE_CHOICES, max_length=32),
        )
        for model_name in (
            "notificationpreference", "notificationdeliverylog",
            "notificationrecipient", "chattemplate",
        )
    ]
