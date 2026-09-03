import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


DROP_IMMUTABLE_TRIGGER = """
DROP TRIGGER IF EXISTS events_checkin_immutable ON events_eventcheckinevent;
"""

CREATE_IMMUTABLE_TRIGGER = """
CREATE TRIGGER events_checkin_immutable
BEFORE UPDATE OR DELETE ON events_eventcheckinevent
FOR EACH ROW EXECUTE FUNCTION events_reject_checkin_mutation();
"""


def populate_checkin_scope(apps, schema_editor):
    CheckIn = apps.get_model("events", "EventCheckInEvent")
    for row in CheckIn.objects.select_related("registration__event").iterator():
        row.event_id = row.registration.event_id
        row.makerspace_id = row.registration.event.makerspace_id
        row.operation_id = uuid.uuid4()
        if row.actor_id is None:
            row.source = "legacy"
        elif row.source == "staff":
            row.source = "online"
        row.save(
            update_fields=["event", "makerspace", "operation_id", "source"]
        )


def restore_legacy_source_values(apps, schema_editor):
    CheckIn = apps.get_model("events", "EventCheckInEvent")
    CheckIn.objects.exclude(source="qr").update(source="staff")


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0020_member_calendar_feed"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunSQL(DROP_IMMUTABLE_TRIGGER, CREATE_IMMUTABLE_TRIGGER),
        migrations.RenameField(
            model_name="eventcheckinevent",
            old_name="created_at",
            new_name="recorded_at",
        ),
        migrations.RenameField(
            model_name="eventcheckinevent",
            old_name="recorded_by",
            new_name="actor",
        ),
        migrations.AddField(
            model_name="eventcheckinevent",
            name="event",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="check_in_events",
                to="events.event",
            ),
        ),
        migrations.AddField(
            model_name="eventcheckinevent",
            name="makerspace",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="event_check_in_events",
                to="makerspaces.makerspace",
            ),
        ),
        migrations.AddField(
            model_name="eventcheckinevent",
            name="operation_id",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name="eventcheckinevent",
            name="session_id",
            field=models.UUIDField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="eventcheckinevent",
            name="station_version",
            field=models.PositiveIntegerField(blank=True, editable=False, null=True),
        ),
        migrations.RunPython(populate_checkin_scope, restore_legacy_source_values),
        migrations.AlterField(
            model_name="eventcheckinevent",
            name="actor",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="eventcheckinevent",
            name="event",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="check_in_events",
                to="events.event",
            ),
        ),
        migrations.AlterField(
            model_name="eventcheckinevent",
            name="makerspace",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="event_check_in_events",
                to="makerspaces.makerspace",
            ),
        ),
        migrations.AlterField(
            model_name="eventcheckinevent",
            name="operation_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AlterField(
            model_name="eventcheckinevent",
            name="registration",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="check_in_events",
                to="events.eventregistration",
            ),
        ),
        migrations.AlterField(
            model_name="eventcheckinevent",
            name="source",
            field=models.CharField(
                choices=[
                    ("online", "Online staff confirmation"),
                    ("qr", "Online QR check-in"),
                    ("offline_sync", "Authenticated offline synchronization"),
                    ("venue_station", "PIN venue station"),
                    ("legacy", "Legacy attendance history"),
                ],
                max_length=16,
            ),
        ),
        migrations.AddConstraint(
            model_name="eventcheckinevent",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        source__in=("online", "qr", "offline_sync"),
                        actor__isnull=False,
                        station_version__isnull=True,
                    )
                    | models.Q(
                        source="venue_station",
                        actor__isnull=True,
                        station_version__isnull=False,
                    )
                    | models.Q(source="legacy", station_version__isnull=True)
                ),
                name="event_checkin_source_actor_consistent",
            ),
        ),
        migrations.CreateModel(
            name="EventCheckInStationCredential",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "public_token",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                ("pin_digest", models.CharField(editable=False, max_length=128)),
                ("pin_ciphertext", models.BinaryField(editable=False)),
                ("version", models.PositiveIntegerField(default=1, editable=False)),
                ("is_enabled", models.BooleanField(default=True)),
                ("rotated_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("disabled_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "event",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="check_in_station",
                        to="events.event",
                    ),
                ),
            ],
        ),
        migrations.RunSQL(CREATE_IMMUTABLE_TRIGGER, DROP_IMMUTABLE_TRIGGER),
    ]
