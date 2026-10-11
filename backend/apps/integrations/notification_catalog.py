"""Feature/channel catalog + default state for the notification matrix (Part K).

The DEFAULT_CHANNEL_STATE table is the authoritative default when no explicit
NotificationPreference row exists — nothing is backfilled. Resolution is fail-closed:
a preference-query failure logs and returns False for that channel, never raising.
"""
import logging

from apps.integrations.models import (
    NotificationChannel,
    NotificationFeature,
    NotificationPreference,
)

logger = logging.getLogger(__name__)

F = NotificationFeature
C = NotificationChannel

# Lifecycle events routed through the fan-out per feature (spec section 6). Draft/CRUD/
# document/status-only actions stay audit-only and are intentionally absent.
FEATURE_EVENTS = {
    F.HARDWARE_REQUESTS: (
        "submitted", "accepted", "rejected", "issued", "partially_returned",
        "returned", "closed_with_issue", "return_reminder",
        "deposit_raised", "late_fee_raised",
        "overdue_escalated",
    ),
    F.PRINTING: (
        "submitted", "accepted", "started", "rejected", "completed", "failed",
        "collected", "reprinted",
    ),
    F.EVENTS: (
        "published", "cancelled", "completed", "registration_created",
        "registration_pending_approval", "registration_waitlisted",
        "registration_approved", "registration_rejected",
        "registration_cancelled", "registration_promoted", "registration_attended",
        "series_published", "series_cancelled", "series_completed",
        "series_generation_failed",
        "reminder",
    ),
    F.BOOKINGS: (
        "created", "confirmed", "rejected", "cancelled", "completed", "no_show",
        "reminder",
    ),
    F.MAINTENANCE: (
        "schedule_created", "schedule_updated", "schedule_deactivated", "logged",
        "schedule_completed",
        "due_soon", "overdue",
    ),
    # request_pending is the existing application-received event; keep its stable key.
    F.MEMBERS: ("request_pending", "member_joined", "approved", "declined",
                "renewal_due", "lapsed", "renewal_failed", "awaiting_payment", "payment_due",
                "renewed", "grace_started", "cancelled"),
    F.API_ACCESS: ("api_key_request_resolved",),
    F.DEVICES: ("offline", "recovered"),
    F.PAYMENTS: ("charge_raised", "payment_due_soon", "payment_due_today", "payment_overdue",
                 "payment_received", "refund_issued", "payment_failed"),
    F.STOCK: ("low_stock", "procurement_received"),
    F.CERTIFICATIONS: ("granted", "revoked", "expiring", "expired"),
}

# Exact default on/off per (feature, channel). Preserves today's behavior: hardware/printing
# email + hardware Telegram on; bookings email (Part J seam) + bookings Telegram on; Slack/
# Mattermost/Discord always opt-in; events/maintenance have no prior external behavior → off.
# Discord is listed explicitly rather than relying on default_state's False fallback, so the
# table stays a complete picture of every channel a reader can toggle.
DEFAULT_CHANNEL_STATE = {
    F.HARDWARE_REQUESTS: {C.EMAIL: True, C.TELEGRAM: True, C.SLACK: False, C.MATTERMOST: False, C.DISCORD: False, C.WEBHOOK: False, C.NATIVE_PUSH: False},
    F.PRINTING: {C.EMAIL: True, C.TELEGRAM: False, C.SLACK: False, C.MATTERMOST: False, C.DISCORD: False, C.WEBHOOK: False, C.NATIVE_PUSH: False},
    F.EVENTS: {C.EMAIL: False, C.TELEGRAM: False, C.SLACK: False, C.MATTERMOST: False, C.DISCORD: False, C.WEBHOOK: False, C.NATIVE_PUSH: False},
    F.BOOKINGS: {C.EMAIL: True, C.TELEGRAM: True, C.SLACK: False, C.MATTERMOST: False, C.DISCORD: False, C.WEBHOOK: False, C.NATIVE_PUSH: False},
    F.MAINTENANCE: {C.EMAIL: False, C.TELEGRAM: False, C.SLACK: False, C.MATTERMOST: False, C.DISCORD: False, C.WEBHOOK: False, C.NATIVE_PUSH: False},
    F.MEMBERS: {C.EMAIL: False, C.TELEGRAM: False, C.SLACK: False, C.MATTERMOST: False, C.DISCORD: False, C.WEBHOOK: False, C.NATIVE_PUSH: False},
    # Preserve the old resolution email + Telegram default, now mutable and metered.
    F.API_ACCESS: {C.EMAIL: True, C.TELEGRAM: True, C.SLACK: False, C.MATTERMOST: False, C.DISCORD: False, C.WEBHOOK: False, C.NATIVE_PUSH: False},
    F.DEVICES: {channel: False for channel in C.values},
    F.PAYMENTS: {channel: False for channel in C.values},
    F.STOCK: {channel: False for channel in C.values},
    F.CERTIFICATIONS: {channel: False for channel in C.values},
}

# Hardware/printing already emit directly; their matrix inbox is explicitly opt-in.
for _feature, _channels in DEFAULT_CHANNEL_STATE.items():
    _channels[C.IN_APP] = _feature not in {F.HARDWARE_REQUESTS, F.PRINTING}


def default_state(feature, channel):
    """The catalog default for a cell (False for any unknown feature/channel)."""
    return DEFAULT_CHANNEL_STATE.get(feature, {}).get(channel, False)


def is_notification_enabled(makerspace, feature, channel):
    """Resolve the (feature, channel) cell: explicit override wins, else the catalog default.

    Fail-closed: any DB error resolving the override logs and returns False for that channel
    so a lookup failure can never break a workflow or silently over-notify.
    """
    try:
        override = (
            NotificationPreference.objects.filter(
                makerspace=makerspace, feature=feature, channel=channel
            )
            .values_list("enabled", flat=True)
            .first()
        )
    except Exception:
        logger.warning(
            "notification_preference_lookup_failed",
            extra={
                "makerspace_id": getattr(makerspace, "pk", None),
                "feature": feature,
                "channel": channel,
            },
        )
        return False
    if override is not None:
        return override
    return default_state(feature, channel)


def receipt_email_default(makerspace):
    """Only the payer's receipt defaults on; an explicit matrix OFF still wins."""
    try:
        override = NotificationPreference.objects.filter(
            makerspace=makerspace, feature=F.PAYMENTS, channel=C.EMAIL,
        ).values_list("enabled", flat=True).first()
        return True if override is None else bool(override)
    except Exception:
        logger.warning("receipt_preference_lookup_failed", extra={"makerspace_id": makerspace.pk})
        return False
