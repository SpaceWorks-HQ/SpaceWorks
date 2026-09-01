from django.db import migrations, models


BATCH_SIZE = 500


def _payment_batches(Payment, database, subject_type):
    payments = Payment.objects.using(database).filter(
        subject_type=subject_type,
        subject_label="",
    ).order_by("pk")
    last_pk = 0
    while True:
        batch = list(payments.filter(pk__gt=last_pk)[:BATCH_SIZE])
        if not batch:
            return
        last_pk = batch[-1].pk
        yield batch


def _backfill_live_subjects(
    Payment,
    Subject,
    database,
    subject_type,
    label_field,
    makerspace_field,
    member_field=None,
):
    stamped = 0
    skipped_ownership_mismatch = 0
    fields = ["pk", label_field, makerspace_field]
    if member_field:
        fields.append(member_field)

    for batch in _payment_batches(Payment, database, subject_type):
        subjects = {
            row[0]: row[1:]
            for row in Subject.objects.using(database).filter(
                pk__in=[payment.subject_id for payment in batch]
            ).values_list(*fields)
        }
        updates = []
        for payment in batch:
            subject = subjects.get(payment.subject_id)
            if subject is None:
                continue
            label, makerspace_id, *member_ids = subject
            if makerspace_id != payment.makerspace_id or (
                member_ids and member_ids[0] != payment.member_id
            ):
                skipped_ownership_mismatch += 1
                continue
            payment.subject_label = (label or "")[:255]
            updates.append(payment)
            stamped += 1
        Payment.objects.using(database).bulk_update(
            updates,
            ["subject_label"],
            batch_size=BATCH_SIZE,
        )

    print(
        f"Payment subject label backfill ({subject_type}): "
        f"stamped={stamped}, "
        f"skipped_ownership_mismatch={skipped_ownership_mismatch}"
    )


def _backfill_memberships(Payment, database):
    subject_type = "makerspace_membership"
    stamped = 0
    for batch in _payment_batches(Payment, database, subject_type):
        for payment in batch:
            payment.subject_label = "Membership dues"
        Payment.objects.using(database).bulk_update(
            batch,
            ["subject_label"],
            batch_size=BATCH_SIZE,
        )
        stamped += len(batch)

    print(
        f"Payment subject label backfill ({subject_type}): "
        f"stamped={stamped}, skipped_ownership_mismatch=0"
    )


def forwards(apps, schema_editor):
    Payment = apps.get_model("payments", "Payment")
    Booking = apps.get_model("bookings", "Booking")
    EventRegistration = apps.get_model("events", "EventRegistration")
    database = schema_editor.connection.alias

    # Django migrations are atomic by default, so batching bounds memory only, not
    # transaction size.
    #
    # `machine_service_request` is deliberately NOT backfilled. Its `title` is free text a
    # public member types, so it can hold their name, email or phone, and a snapshot would
    # outlive the `machine_service` purge whose whole job is destroying that. Those rows keep
    # a blank label: the live lookup still names them while the request exists, and they fall
    # back to the generic display afterwards.
    _backfill_live_subjects(
        Payment,
        Booking,
        database,
        "booking",
        "space__name",
        "space__makerspace_id",
    )
    _backfill_live_subjects(
        Payment,
        EventRegistration,
        database,
        "event_registration",
        "event__title",
        "event__makerspace_id",
        "member_id",
    )
    _backfill_memberships(Payment, database)


def backwards(apps, schema_editor):
    Payment = apps.get_model("payments", "Payment")
    database = schema_editor.connection.alias
    Payment.objects.using(database).update(subject_label="")


class Migration(migrations.Migration):
    # Only the apps whose models `forwards` actually loads. `machines` and `makerspaces`
    # were listed too, but nothing here reads them -- machine-service is deliberately not
    # backfilled and membership dues is a literal. Two tests rewind exactly those apps with
    # `MigrationExecutor`, and an unused dependency drags this migration into their rewind
    # for no benefit.
    dependencies = [
        ("payments", "0011_payment_via_makerspace"),
        ("events", "0012_eventregistration_payment_via_makerspace"),
        ("bookings", "0007_bookablespace_payment_amount"),
    ]

    operations = [
        migrations.AddField(
            model_name="payment",
            name="subject_label",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.RunPython(forwards, backwards),
    ]
