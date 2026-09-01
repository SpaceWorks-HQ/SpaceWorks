"""Chat destinations — one row per room a makerspace posts into.

Before this, a makerspace had exactly one webhook per channel, stored as a column on
`Makerspace`. That makes "send laser faults to the laser team's channel and printer
faults to the print room" unexpressible. A destination is that room, and its scope link
tables say which subjects belong to it.

Three things about the shape are load-bearing:

**The credential is typed per channel, not one overloaded column.** Slack, Mattermost and
Discord each need an incoming-webhook URL; Telegram needs a chat id. A single
`credential` field would mean different things on different rows, with nothing to stop a
webhook URL being saved as a chat id. Two nullable columns and a per-channel check
constraint make the wrong row unrepresentable.

**Telegram destinations carry NO bot token.** The original reason was inbound: accept/reject
buttons posted back to a single registered webhook authenticated by one
`TELEGRAM_WEBHOOK_SECRET`, so a second bot's callbacks could not be authenticated or routed.
**Those buttons are gone** — chat is a notification channel now, not a decision surface — so
that argument has expired, and the rule stands on the outbound half instead: one bot identity
per makerspace across all of its rooms is what makes per-machine rooms read as a single
sender rather than a handful of unrelated bots, and it keeps the token surface to one secret
per tenant. If a button is ever reintroduced, per-bot destinations need per-bot webhook
secrets and inbound routing first — its own phase, exactly as before.

**No scope links means space-wide**, which is deliberately the OPPOSITE default to role
machine-scope. An unscoped *role* must see nothing (access fails closed); an unscoped
*room* should see everything, because a room is not a permission.
"""

from django.db import models

from apps.integrations.notification_enums import ChatNotificationChannel
from apps.makerspaces.secrets import decrypt_value, encrypt_value

# Channels whose credential is a webhook URL. Telegram is the exception on the other side
# of every branch in this module, so it is named once here rather than in each check.
WEBHOOK_CHANNELS = (
    ChatNotificationChannel.SLACK,
    ChatNotificationChannel.MATTERMOST,
    ChatNotificationChannel.DISCORD,
)


class NotificationDestination(models.Model):
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="notification_destinations",
    )
    channel = models.CharField(max_length=16, choices=ChatNotificationChannel.choices)
    label = models.CharField(max_length=80)
    # Fernet ciphertext, exactly like the Makerspace columns it replaces. Never echoed by
    # a serializer -- the staff API exposes a `*_set` boolean instead.
    webhook_url = models.TextField(blank=True, default="")
    telegram_chat_id = models.CharField(max_length=64, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        channel__in=[channel.value for channel in WEBHOOK_CHANNELS],
                        telegram_chat_id="",
                    )
                    & ~models.Q(webhook_url="")
                )
                | models.Q(
                    channel=ChatNotificationChannel.TELEGRAM,
                    webhook_url="",
                )
                & ~models.Q(telegram_chat_id=""),
                name="notification_destination_credential_matches_channel",
            ),
            models.UniqueConstraint(
                fields=["makerspace", "channel", "label"],
                name="uniq_notification_destination_label",
            ),
        ]
        indexes = [
            models.Index(fields=["makerspace", "channel", "is_active"]),
        ]
        ordering = ["makerspace_id", "channel", "label", "id"]

    def set_webhook_url(self, raw):
        self.webhook_url = encrypt_value(raw)

    def get_webhook_url(self):
        return decrypt_value(self.webhook_url)

    def __str__(self):
        return f"{self.makerspace_id}:{self.channel}/{self.label}"


class DestinationMachineTypeScope(models.Model):
    destination = models.ForeignKey(
        NotificationDestination,
        on_delete=models.CASCADE,
        related_name="machine_type_scopes",
    )
    machine_type = models.ForeignKey(
        "machines.MachineType",
        on_delete=models.CASCADE,
        related_name="notification_destination_scopes",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["destination", "machine_type"],
                name="uniq_destination_machine_type_scope",
            )
        ]


class DestinationMachineScope(models.Model):
    destination = models.ForeignKey(
        NotificationDestination,
        on_delete=models.CASCADE,
        related_name="machine_scopes",
    )
    machine = models.ForeignKey(
        "machines.Machine",
        on_delete=models.CASCADE,
        related_name="notification_destination_scopes",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["destination", "machine"],
                name="uniq_destination_machine_scope",
            )
        ]


class DestinationCategoryScope(models.Model):
    destination = models.ForeignKey(
        NotificationDestination,
        on_delete=models.CASCADE,
        related_name="category_scopes",
    )
    category = models.ForeignKey(
        "inventory.Category",
        on_delete=models.CASCADE,
        related_name="notification_destination_scopes",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["destination", "category"],
                name="uniq_destination_category_scope",
            )
        ]
