import django.db.models.deletion
from django.db import migrations, models


def forwards(apps, schema_editor):
    """Seed payment routing from the provenance that still exists.

    Existing rows have never been through a collaborator purge with this column present,
    so their `registered_via_makerspace` is still the truthful routing target. A row whose
    provenance is already NULL cannot be recovered -- the information was destroyed before
    anywhere durable held it -- and is left NULL rather than guessed at, so it falls back to
    the host exactly as it does today.
    """
    EventRegistration = apps.get_model("events", "EventRegistration")
    EventRegistration.objects.using(schema_editor.connection.alias).filter(
        payment_via_makerspace_id__isnull=True,
        registered_via_makerspace_id__isnull=False,
    ).update(payment_via_makerspace_id=models.F("registered_via_makerspace_id"))


def backwards(apps, schema_editor):
    EventRegistration = apps.get_model("events", "EventRegistration")
    EventRegistration.objects.using(schema_editor.connection.alias).update(
        payment_via_makerspace_id=None
    )


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0011_eventregistration_host_waiver"),
        ("makerspaces", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="eventregistration",
            name="payment_via_makerspace",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="event_registration_payment_routes",
                to="makerspaces.makerspace",
            ),
        ),
        migrations.RunPython(forwards, backwards),
    ]
