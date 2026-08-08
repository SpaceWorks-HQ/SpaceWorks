"""Notification feature/channel enums, kept out of `models.py`.

They live here for one structural reason: `models.py` imports the sibling model modules
(`models_push`, `models_recipients`, `models_sms`) at its foot, and `models_recipients`
needs `NotificationFeature.choices` at class-definition time. Importing it back out of
`models` would make the cycle load-order dependent — fine when Django imports `models`
first, an ImportError the moment anything imports a sibling module first. A leaf module
that depends on nothing in this app cannot be caught in that cycle.

`models.py` re-exports every name below, so `from apps.integrations.models import
NotificationFeature` keeps resolving and no call site had to change.
"""

from django.db import models


class NotificationFeature(models.TextChoices):
    HARDWARE_REQUESTS = "hardware_requests", "Hardware requests"
    PRINTING = "printing", "Printing"
    EVENTS = "events", "Events"
    BOOKINGS = "bookings", "Bookings"
    MAINTENANCE = "maintenance", "Maintenance"
    MEMBERS = "members", "Members"


class NotificationChannel(models.TextChoices):
    EMAIL = "email", "Email"
    TELEGRAM = "telegram", "Telegram"
    SLACK = "slack", "Slack"
    MATTERMOST = "mattermost", "Mattermost"
    DISCORD = "discord", "Discord"
    NATIVE_PUSH = "native_push", "Native push"


class NonEmailNotificationChannel(models.TextChoices):
    TELEGRAM = "telegram", "Telegram"
    SLACK = "slack", "Slack"
    MATTERMOST = "mattermost", "Mattermost"
    DISCORD = "discord", "Discord"
    NATIVE_PUSH = "native_push", "Native push"


class NotificationDeliveryStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SENDING = "sending", "Sending"
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"
    # Terminal, and neither a delivery nor a failure: the makerspace has this channel's
    # module uninstalled. Recorded rather than dropped so an operator can see what the
    # toggle suppressed -- the same contract as EmailLog.Status.SKIPPED.
    SKIPPED = "skipped", "Skipped"


# Chat channels gated by a same-named module key.
#
# Two absences are deliberate. `native_push` is governed by the standalone `mobile.push`
# feature switch, not a module. And `email` is NOT here even though an `email` module key
# exists: some messages send regardless of it (`dispatch.EMAIL_MODULE_EXEMPT` covers
# password reset, email verification and the return reminder), so treating email as
# "gone when the module is off" would hide the matrix column while mail was still going
# out — overstating what the toggle does. Tenant email is gated by
# `dispatch.email_module_blocks`, which knows about the exemptions; this table does not.
CHANNEL_MODULE_KEYS = {
    "telegram": "telegram",
    "slack": "slack",
    "mattermost": "mattermost",
    "discord": "discord",
}
