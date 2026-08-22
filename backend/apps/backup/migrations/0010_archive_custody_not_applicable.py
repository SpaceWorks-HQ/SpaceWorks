import django.utils.timezone
from django.db import migrations, models


RECIPIENT_COUNT_BELOW_FLOOR = "recipient_count_below_floor"


def _recipient_count(Recipient, makerspace_id, database):
    return Recipient.objects.using(database).filter(
        makerspace_id=makerspace_id,
        verified_at__isnull=False,
        revoked_at__isnull=True,
        compromised_at__isnull=True,
    ).count()


def derive_custody_scope(apps, schema_editor):
    database = schema_editor.connection.alias
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    Recipient = apps.get_model("backup", "MakerspaceArchiveRecipient")
    CustodyState = apps.get_model("backup", "MakerspaceArchiveCustodyState")

    for makerspace in Makerspace.objects.using(database).order_by("pk").iterator():
        count = _recipient_count(Recipient, makerspace.pk, database)
        current = (
            CustodyState.objects.using(database)
            .filter(makerspace_id=makerspace.pk)
            .first()
        )
        if current is None:
            state = (
                "not_applicable"
                if makerspace.superadmin_access_enabled
                else "healthy"
                if count >= 2
                else "degraded_one_recipient"
                if count == 1
                else "floor_breached_zero"
            )
            CustodyState.objects.using(database).create(
                makerspace_id=makerspace.pk,
                state=state,
                reason_code=(
                    ""
                    if state in ("healthy", "not_applicable")
                    else RECIPIENT_COUNT_BELOW_FLOOR
                ),
                entered_at=makerspace.created_at,
                cleared_at=(
                    makerspace.updated_at
                    if state in ("healthy", "not_applicable")
                    else None
                ),
                last_alarm_at=None,
                triggering_recipient_id=None,
                alarm_episode=(
                    0 if state in ("healthy", "not_applicable") else 1
                ),
            )
            continue

        previous_state = current.state
        if makerspace.superadmin_access_enabled:
            current.state = "not_applicable"
            current.reason_code = ""
            current.cleared_at = makerspace.updated_at
            current.last_alarm_at = None
            current.triggering_recipient_id = None
            current.save(using=database)
            continue

        state = (
            "healthy"
            if count >= 2
            else "degraded_one_recipient"
            if count == 1
            else "floor_breached_zero"
        )
        current.state = state
        current.reason_code = (
            "" if state == "healthy" else RECIPIENT_COUNT_BELOW_FLOOR
        )
        current.triggering_recipient_id = None
        if state == "healthy":
            if previous_state != "healthy" and current.cleared_at is None:
                current.cleared_at = makerspace.updated_at
            current.last_alarm_at = None
        else:
            current.cleared_at = None
            if previous_state == "healthy":
                current.alarm_episode += 1
                current.entered_at = makerspace.updated_at
                current.last_alarm_at = None
        current.save(using=database)


def restore_pre_scope_custody(apps, schema_editor):
    database = schema_editor.connection.alias
    Recipient = apps.get_model("backup", "MakerspaceArchiveRecipient")
    CustodyState = apps.get_model("backup", "MakerspaceArchiveCustodyState")
    now = django.utils.timezone.now()

    rows = CustodyState.objects.using(database).filter(state="not_applicable")
    for current in rows.order_by("pk").iterator():
        count = _recipient_count(Recipient, current.makerspace_id, database)
        state = (
            "healthy"
            if count >= 2
            else "degraded_one_recipient"
            if count == 1
            else "floor_breached_zero"
        )
        current.state = state
        current.reason_code = (
            "" if state == "healthy" else RECIPIENT_COUNT_BELOW_FLOOR
        )
        current.cleared_at = now if state == "healthy" else None
        current.entered_at = current.entered_at or now
        if state != "healthy" and current.alarm_episode == 0:
            current.alarm_episode = 1
        current.triggering_recipient_id = None
        current.last_alarm_at = None
        current.save(using=database)


class Migration(migrations.Migration):
    dependencies = [("backup", "0009_backfill_makerspace_archive_custody_state")]

    operations = [
        migrations.AlterField(
            model_name="makerspacearchivecustodystate",
            name="state",
            field=models.CharField(
                choices=[
                    ("healthy", "Healthy"),
                    ("not_applicable", "Not applicable"),
                    ("degraded_one_recipient", "Degraded: one recipient"),
                    ("floor_breached_zero", "Floor breached: zero"),
                ],
                default="healthy",
                max_length=32,
            ),
        ),
        migrations.RunPython(derive_custody_scope, restore_pre_scope_custody),
    ]
