"""Chat destination and legacy-channel delivery health."""

from django.db.models import Count, Max, Q
from apps.integrations.dispatch_channels import _channel_configured

def _destinations_section(makerspace):
    """Per-room delivery health for all four chat channels.

    Reports rooms AND the legacy makerspace-column path, because a space that has not been
    given destinations still sends — showing it as "no rooms configured" would read as an
    outage when nothing is wrong.
    """
    from apps.integrations.models import (
        NotificationDeliveryLog,
        NotificationDeliveryStatus,
        NotificationDestination,
    )
    from apps.integrations.notification_enums import ChatNotificationChannel

    rows = list(
        NotificationDestination.objects.filter(makerspace=makerspace).order_by(
            "channel", "label", "id"
        )
    )
    stats = {
        row["destination"]: row
        for row in NotificationDeliveryLog.objects.filter(
            makerspace=makerspace, destination__isnull=False
        )
        .values("destination")
        .annotate(
            last_sent_at=Max("sent_at"),
            failed=Count("id", filter=Q(status=NotificationDeliveryStatus.FAILED)),
        )
    }
    last_errors = {}
    for log in (
        NotificationDeliveryLog.objects.filter(
            makerspace=makerspace,
            destination__isnull=False,
            status=NotificationDeliveryStatus.FAILED,
        )
        .order_by("destination_id", "-created_at")
        .values("destination_id", "error", "created_at")
    ):
        last_errors.setdefault(
            log["destination_id"],
            {"error": (log["error"] or "")[:200], "at": log["created_at"]},
        )

    destinations = []
    for row in rows:
        stat = stats.get(row.pk, {})
        destinations.append(
            {
                "id": row.pk,
                "channel": row.channel,
                "label": row.label,
                "is_active": row.is_active,
                # Never the credential itself — only whether one is present. A health
                # payload is read by staff, and a webhook URL is a bearer secret.
                "configured": _channel_configured(makerspace, row.channel, row),
                "last_sent_at": stat.get("last_sent_at"),
                "failed": stat.get("failed", 0),
                "last_failure": last_errors.get(row.pk),
            }
        )

    channels_with_rooms = {row.channel for row in rows}
    legacy = {
        channel: _legacy_channel_configured(makerspace, channel)
        for channel in ChatNotificationChannel.values
        if channel not in channels_with_rooms
    }
    legacy_deliveries = _legacy_deliveries(makerspace, legacy)
    return {
        "status": (
            "warn"
            if any(item["failed"] for item in destinations)
            or any(item["failed"] for item in legacy_deliveries.values())
            else "ok"
        ),
        "destinations": destinations,
        # Channels still resolving through the makerspace columns (D10 keeps them
        # readable for a release), so the operator can see both halves of the transition.
        "legacy_channels": legacy,
        # The same "failed / last failure" a room gets, for the room-less path. Without it
        # a revoked makerspace-wide Slack webhook failed every alert with nothing to show.
        "legacy_deliveries": legacy_deliveries,
    }


def _legacy_deliveries(makerspace, legacy_channels):
    from apps.integrations.models import NotificationDeliveryLog, NotificationDeliveryStatus

    rows = NotificationDeliveryLog.objects.filter(
        makerspace=makerspace,
        channel__in=list(legacy_channels),
        destination__isnull=True,
        destination_label="",
    )
    stats = {
        row["channel"]: row
        for row in rows.values("channel").annotate(
            last_sent_at=Max("sent_at"),
            failed=Count("id", filter=Q(status=NotificationDeliveryStatus.FAILED)),
        )
    }
    last_errors = {}
    for log in (
        rows.filter(status=NotificationDeliveryStatus.FAILED)
        .order_by("channel", "-created_at")
        .values("channel", "error", "created_at")
    ):
        last_errors.setdefault(
            log["channel"], {"error": (log["error"] or "")[:200], "at": log["created_at"]}
        )
    return {
        channel: {
            "configured": configured,
            "last_sent_at": stats.get(channel, {}).get("last_sent_at"),
            "failed": stats.get(channel, {}).get("failed", 0),
            "last_failure": last_errors.get(channel),
        }
        for channel, configured in legacy_channels.items()
    }


def _legacy_channel_configured(makerspace, channel):
    return _channel_configured(makerspace, channel)


