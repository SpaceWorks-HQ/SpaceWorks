import django.db.models.deletion
from django.db import migrations, models


BATCH_SIZE = 500


def forwards(apps, schema_editor):
    Payment = apps.get_model("payments", "Payment")
    EventRegistration = apps.get_model("events", "EventRegistration")
    database = schema_editor.connection.alias
    payments = Payment.objects.using(database).filter(
        subject_type="event_registration",
        via_makerspace_id__isnull=True,
    ).order_by("pk")

    stamped = 0
    skipped_member_mismatch = 0
    skipped_no_registration = 0
    last_pk = 0
    while True:
        batch = list(payments.filter(pk__gt=last_pk)[:BATCH_SIZE])
        if not batch:
            break
        last_pk = batch[-1].pk
        registrations = {
            registration.pk: registration
            for registration in EventRegistration.objects.using(database).filter(
                pk__in=[payment.subject_id for payment in batch]
            ).select_related("event")
        }
        updates = []
        for payment in batch:
            registration = registrations.get(payment.subject_id)
            if registration is None:
                skipped_no_registration += 1
                continue
            if registration.member_id != payment.member_id:
                skipped_member_mismatch += 1
                continue
            payment.via_makerspace_id = (
                registration.registered_via_makerspace_id
                or registration.event.makerspace_id
            )
            updates.append(payment)
            stamped += 1
        Payment.objects.using(database).bulk_update(
            updates,
            ["via_makerspace"],
            batch_size=BATCH_SIZE,
        )

    print(
        "Payment via_makerspace backfill: "
        f"stamped={stamped}, "
        f"skipped_member_mismatch={skipped_member_mismatch}, "
        f"skipped_no_registration={skipped_no_registration}"
    )


def backwards(apps, schema_editor):
    Payment = apps.get_model("payments", "Payment")
    database = schema_editor.connection.alias
    Payment.objects.using(database).update(via_makerspace_id=None)


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0010_razorpay_provider"),
        ("events", "0011_eventregistration_host_waiver"),
    ]

    operations = [
        migrations.AddField(
            model_name="payment",
            name="via_makerspace",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="payments_via",
                to="makerspaces.makerspace",
            ),
        ),
        migrations.AddIndex(
            model_name="payment",
            index=models.Index(
                fields=["via_makerspace", "member"],
                name="payment_via_makerspace_member_idx",
            ),
        ),
        migrations.RunPython(forwards, backwards),
    ]
