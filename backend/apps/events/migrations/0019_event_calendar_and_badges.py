import uuid

from django.conf import settings
from django.db import migrations, models
import django.utils.timezone


def backfill_calendar_identity(apps, schema_editor):
    Event = apps.get_model("events", "Event")
    EventSeries = apps.get_model("events", "EventSeries")
    EventRegistration = apps.get_model("events", "EventRegistration")
    now = django.utils.timezone.now()
    for event in Event.objects.filter(calendar_uid__isnull=True).iterator(chunk_size=500):
        Event.objects.filter(pk=event.pk).update(
            calendar_uid=uuid.uuid4(),
            calendar_updated_at=now,
            timezone_name=settings.TIME_ZONE,
        )
    for series in EventSeries.objects.filter(calendar_uid__isnull=True).iterator(chunk_size=500):
        EventSeries.objects.filter(pk=series.pk).update(
            calendar_uid=uuid.uuid4(), calendar_updated_at=now
        )
    EventRegistration.objects.filter(calendar_updated_at__isnull=True).update(
        calendar_updated_at=now
    )


class Migration(migrations.Migration):
    dependencies = [("events", "0018_event_series")]

    operations = [
        migrations.AddField(
            model_name="event",
            name="badge_template",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="event",
            name="calendar_sequence",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="event",
            name="calendar_uid",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name="event",
            name="calendar_updated_at",
            field=models.DateTimeField(null=True),
        ),
        migrations.AddField(
            model_name="event",
            name="timezone_name",
            field=models.CharField(max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="eventregistration",
            name="calendar_sequence",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="eventregistration",
            name="calendar_updated_at",
            field=models.DateTimeField(null=True),
        ),
        migrations.AddField(
            model_name="eventseries",
            name="calendar_sequence",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="eventseries",
            name="calendar_uid",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name="eventseries",
            name="calendar_updated_at",
            field=models.DateTimeField(null=True),
        ),
        migrations.RunPython(backfill_calendar_identity, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="event",
            name="calendar_uid",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AlterField(
            model_name="event",
            name="calendar_updated_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AlterField(
            model_name="event",
            name="timezone_name",
            field=models.CharField(default=settings.TIME_ZONE, max_length=64),
        ),
        migrations.AlterField(
            model_name="eventregistration",
            name="calendar_updated_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AlterField(
            model_name="eventseries",
            name="calendar_uid",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AlterField(
            model_name="eventseries",
            name="calendar_updated_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
    ]
