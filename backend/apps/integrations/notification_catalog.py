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
    ),
    F.PRINTING: (
        "submitted", "accepted", "started", "rejected", "completed", "failed",
        "collected", "reprinted",
    ),
    F.EVENTS: (
        "published", "cancelled", "completed", "registration_created",
        "registration_cancelled", "registration_promoted", "registration_attended",
    ),
    F.BOOKINGS: (
        "created", "confirmed", "rejected", "cancelled", "completed", "no_show",
    ),
    F.MAINTENANCE: (
        "schedule_created", "schedule_updated", "schedule_deactivated", "logged",
        "schedule_completed",
    ),
    F.MEMBERS: ("request_pending", "member_joined"),
}

# Exact default on/off per (feature, channel). Preserves today's behavior: hardware/printing
# email + hardware Telegram on; bookings email (Part J seam) + bookings Telegram on; Slack/
# Mattermost/Discord always opt-in; events/maintenance have no prior external behavior → off.
# Discord is listed explicitly rather than relying on default_state's False fallback, so the
# table stays a complete picture of every channel a reader can toggle.
DEFAULT_CHANNEL_STATE = {
    F.HARDWARE_REQUESTS: {C.EMAIL: True, C.TELEGRAM: True, C.SLACK: False, C.MATTERMOST: False, C.DISCORD: False, C.NATIVE_PUSH: False},
    F.PRINTING: {C.EMAIL: True, C.TELEGRAM: False, C.SLACK: False, C.MATTERMOST: False, C.DISCORD: False, C.NATIVE_PUSH: False},
    F.EVENTS: {C.EMAIL: False, C.TELEGRAM: False, C.SLACK: False, C.MATTERMOST: False, C.DISCORD: False, C.NATIVE_PUSH: False},
    F.BOOKINGS: {C.EMAIL: True, C.TELEGRAM: True, C.SLACK: False, C.MATTERMOST: False, C.DISCORD: False, C.NATIVE_PUSH: False},
    F.MAINTENANCE: {C.EMAIL: False, C.TELEGRAM: False, C.SLACK: False, C.MATTERMOST: False, C.DISCORD: False, C.NATIVE_PUSH: False},
    F.MEMBERS: {C.EMAIL: False, C.TELEGRAM: False, C.SLACK: False, C.MATTERMOST: False, C.DISCORD: False, C.NATIVE_PUSH: False},
}


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
