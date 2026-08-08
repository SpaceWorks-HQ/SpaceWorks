"""Turn each space's existing chat credential into one space-wide destination.

The old `Makerspace.*_webhook_url` / `telegram_group_chat_id` columns are deliberately
NOT dropped here. Resolution treats "no destination rows for this channel" as "use the
makerspace column", so this migration is additive on both sides: a space that is backfilled
sends through its new destination, and a space that somehow is not (or that configures a
channel through the old settings form before the console catches up) keeps sending exactly
as it did. Dropping the columns in the same phase would be one-way, and a space missed by
the backfill would go silent with nothing to fall back to.

Telegram is included, and it is the one people forget: it never went through the webhook
sender, so a backfill written around `send_webhook` would have left every Telegram space
without a destination. The row carries the chat id ONLY — the bot stays the makerspace's,
because inbound callbacks are authenticated by a single deployment-wide webhook secret.
"""

from django.db import migrations

# Encrypted at rest already; the value is copied as stored ciphertext, never decrypted
# here. A migration that decrypted would need the Fernet key present at migrate time and
# would fail the whole upgrade on a rotated key.
WEBHOOK_COLUMNS = {
    "slack": "slack_webhook_url",
    "mattermost": "mattermost_webhook_url",
    "discord": "discord_webhook_url",
}

LABEL = "Main"


def backfill(apps, schema_editor):
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    NotificationDestination = apps.get_model("integrations", "NotificationDestination")

    rows = []
    for makerspace in Makerspace.objects.all().iterator():
        for channel, column in WEBHOOK_COLUMNS.items():
            value = (getattr(makerspace, column, "") or "").strip()
            if value:
                rows.append(
                    NotificationDestination(
                        makerspace=makerspace,
                        channel=channel,
                        label=LABEL,
                        webhook_url=value,
                        telegram_chat_id="",
                        is_active=True,
                    )
                )
        chat_id = (getattr(makerspace, "telegram_group_chat_id", "") or "").strip()
        if chat_id:
            rows.append(
                NotificationDestination(
                    makerspace=makerspace,
                    channel="telegram",
                    label=LABEL,
                    webhook_url="",
                    telegram_chat_id=chat_id,
                    is_active=True,
                )
            )
    if rows:
        NotificationDestination.objects.bulk_create(rows, batch_size=500)


def unbackfill(apps, schema_editor):
    # Reversible because the source columns were never cleared: deleting the generated
    # rows returns every space to the makerspace-column path it is still on.
    NotificationDestination = apps.get_model("integrations", "NotificationDestination")
    NotificationDestination.objects.filter(label=LABEL).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0020_notificationdeliverylog_destination_label_and_more"),
        # The migration that added `discord_webhook_url`; without it the historical
        # Makerspace model here would not carry the column this backfill reads.
        ("makerspaces", "0055_discord_webhook_and_channel_status"),
    ]

    operations = [migrations.RunPython(backfill, unbackfill)]
