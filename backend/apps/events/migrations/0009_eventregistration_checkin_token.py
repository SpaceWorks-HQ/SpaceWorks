from uuid import uuid4

from django.db import migrations, models


BATCH_SIZE = 1000


def populate_checkin_tokens(apps, schema_editor):
    EventRegistration = apps.get_model("events", "EventRegistration")
    registrations = EventRegistration.objects.using(schema_editor.connection.alias)
    batch = []
    for registration in registrations.only("pk").iterator(chunk_size=BATCH_SIZE):
        registration.checkin_token = uuid4()
        batch.append(registration)
        if len(batch) == BATCH_SIZE:
            registrations.bulk_update(
                batch,
                ["checkin_token"],
                batch_size=BATCH_SIZE,
            )
            batch.clear()
    if batch:
        registrations.bulk_update(
            batch,
            ["checkin_token"],
            batch_size=BATCH_SIZE,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0008_event_image_key"),
    ]

    operations = [
        migrations.AddField(
            model_name="eventregistration",
            name="checkin_token",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(
            populate_checkin_tokens,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="eventregistration",
            name="checkin_token",
            field=models.UUIDField(default=uuid4, editable=False, unique=True),
        ),
    ]
