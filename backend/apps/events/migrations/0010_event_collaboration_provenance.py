import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


BATCH_SIZE = 1000


def backfill_registration_provenance(apps, schema_editor):
    EventRegistration = apps.get_model("events", "EventRegistration")
    registrations = EventRegistration.objects.using(schema_editor.connection.alias)
    batch = []
    rows = registrations.values_list("pk", "event__makerspace_id").iterator(
        chunk_size=BATCH_SIZE
    )
    for registration_id, makerspace_id in rows:
        batch.append(
            EventRegistration(
                pk=registration_id,
                registered_via_makerspace_id=makerspace_id,
            )
        )
        if len(batch) == BATCH_SIZE:
            registrations.bulk_update(
                batch,
                ["registered_via_makerspace"],
                batch_size=BATCH_SIZE,
            )
            batch.clear()
    if batch:
        registrations.bulk_update(
            batch,
            ["registered_via_makerspace"],
            batch_size=BATCH_SIZE,
        )


def clear_registration_provenance(apps, schema_editor):
    EventRegistration = apps.get_model("events", "EventRegistration")
    EventRegistration.objects.using(schema_editor.connection.alias).update(
        registered_via_makerspace=None
    )


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0009_eventregistration_checkin_token"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="EventCollaborator",
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
                    "status",
                    models.CharField(
                        choices=[
                            ("invited", "Invited"),
                            ("accepted", "Accepted"),
                            ("declined", "Declined"),
                        ],
                        default="invited",
                        max_length=8,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("responded_at", models.DateTimeField(blank=True, null=True)),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="collaborators",
                        to="events.event",
                    ),
                ),
                (
                    "invited_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "makerspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="event_collaborations",
                        to="makerspaces.makerspace",
                    ),
                ),
                (
                    "responded_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"unique_together": {("event", "makerspace")}},
        ),
        migrations.AddField(
            model_name="eventregistration",
            name="registered_via_makerspace",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="event_registrations_via",
                to="makerspaces.makerspace",
            ),
        ),
        migrations.RunPython(
            backfill_registration_provenance,
            reverse_code=clear_registration_provenance,
        ),
    ]
