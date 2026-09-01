from django.db import migrations


RECIPIENT_COUNT_BELOW_FLOOR = "recipient_count_below_floor"


def backfill_custody_states(apps, schema_editor):
    """Recompute derived custody rows without reopening an existing alarm."""
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    Recipient = apps.get_model("backup", "MakerspaceArchiveRecipient")
    CustodyState = apps.get_model("backup", "MakerspaceArchiveCustodyState")

    for makerspace in Makerspace.objects.order_by("pk").iterator():
        count = Recipient.objects.filter(
            makerspace_id=makerspace.pk,
            verified_at__isnull=False,
            revoked_at__isnull=True,
            compromised_at__isnull=True,
        ).count()
        state = (
            "healthy"
            if count >= 2
            else "degraded_one_recipient"
            if count == 1
            else "floor_breached_zero"
        )
        reason_code = "" if state == "healthy" else RECIPIENT_COUNT_BELOW_FLOOR
        current = CustodyState.objects.filter(makerspace_id=makerspace.pk).first()

        if current is None:
            # This row is wholly derived from stable source rows. Its fixed
            # timestamps and episode make a second execution produce no change.
            CustodyState.objects.create(
                makerspace_id=makerspace.pk,
                state=state,
                reason_code=reason_code,
                entered_at=makerspace.created_at,
                cleared_at=None,
                last_alarm_at=None,
                triggering_recipient_id=None,
                alarm_episode=0 if state == "healthy" else 1,
            )
            continue

        previous_state = current.state
        current.state = state
        current.reason_code = reason_code
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
        # Preserve the episode and delivery marker for an existing unhealthy
        # row. Re-running derived backfill must not make delivery retry it.
        current.save()


def remove_derived_custody_states(apps, schema_editor):
    apps.get_model("backup", "MakerspaceArchiveCustodyState").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("backup", "0008_makerspace_archive_custody_state"),
    ]

    operations = [
        migrations.RunPython(
            backfill_custody_states,
            remove_derived_custody_states,
        ),
    ]
