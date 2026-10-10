from django.core.validators import MaxValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("events", "0023_event_station_binding")]

    operations = [
        migrations.AddField(
            model_name="event", name="cancellation_cutoff_hours",
            field=models.PositiveIntegerField(blank=True, null=True, validators=[MaxValueValidator(8760)]),
        ),
        migrations.AddField(
            model_name="eventseries", name="cancellation_cutoff_hours",
            field=models.PositiveIntegerField(blank=True, null=True, validators=[MaxValueValidator(8760)]),
        ),
    ]
