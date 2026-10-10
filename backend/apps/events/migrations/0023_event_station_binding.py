from django.db import migrations, models
from django.db.migrations.exceptions import IrreversibleError
import django.db.models.deletion


def copy_station_credentials(apps, schema_editor):
    OldCredential = apps.get_model("events", "EventCheckInStationCredential")
    Station = apps.get_model("makerspaces", "Station")
    StationCredential = apps.get_model("makerspaces", "StationCredential")
    Binding = apps.get_model("events", "EventStationBinding")
    alias = schema_editor.connection.alias

    for old in OldCredential.objects.using(alias).select_related("event").iterator():
        station = Station.objects.using(alias).create(
            makerspace_id=old.event.makerspace_id,
            kind="event_checkin",
            name=f"event-{old.event_id}",
            created_by_id=None,
        )
        Station.objects.using(alias).filter(pk=station.pk).update(
            created_at=old.created_at,
            updated_at=old.updated_at,
        )
        credential = StationCredential.objects.using(alias).create(
            station_id=station.pk,
            public_token=old.public_token,
            pin_digest=old.pin_digest,
            pin_ciphertext=old.pin_ciphertext,
            version=old.version,
            is_enabled=old.is_enabled,
            rotated_at=old.rotated_at,
            disabled_at=old.disabled_at,
        )
        StationCredential.objects.using(alias).filter(pk=credential.pk).update(
            created_at=old.created_at,
            updated_at=old.updated_at,
        )
        binding = Binding.objects.using(alias).create(
            event_id=old.event_id,
            station_id=station.pk,
        )
        Binding.objects.using(alias).filter(pk=binding.pk).update(
            created_at=old.created_at,
        )


def restore_event_credentials(apps, schema_editor):
    OldCredential = apps.get_model("events", "EventCheckInStationCredential")
    Binding = apps.get_model("events", "EventStationBinding")
    StationCredential = apps.get_model("makerspaces", "StationCredential")
    alias = schema_editor.connection.alias

    for binding in Binding.objects.using(alias).iterator():
        shared = (
            StationCredential.objects.using(alias)
            .filter(station_id=binding.station_id)
            .first()
        )
        if shared is None:
            raise IrreversibleError(
                "An event Station without a credential cannot be reversed."
            )
        old = OldCredential.objects.using(alias).create(
            event_id=binding.event_id,
            public_token=shared.public_token,
            pin_digest=shared.pin_digest,
            pin_ciphertext=shared.pin_ciphertext,
            version=shared.version,
            is_enabled=shared.is_enabled,
            rotated_at=shared.rotated_at,
            disabled_at=shared.disabled_at,
        )
        OldCredential.objects.using(alias).filter(pk=old.pk).update(
            created_at=shared.created_at,
            updated_at=shared.updated_at,
        )
        binding.station.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0022_event_search_vector"),
        ("makerspaces", "0075_shared_station"),
    ]

    operations = [
        migrations.CreateModel(
            name="EventStationBinding",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("event", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="station_binding", to="events.event")),
                ("station", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="event_binding", to="makerspaces.station")),
            ],
        ),
        migrations.RunPython(copy_station_credentials, restore_event_credentials),
        migrations.DeleteModel(name="EventCheckInStationCredential"),
    ]
